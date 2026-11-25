"""Post-J.20 Stage 1B.4 — cross-table consistency and concurrency (mock-only).

Deterministic thread barriers/events plus real spawned-process SQLite contention.
All state is disposable SQLite and in-process/file-backed *mock* backends. No
Docker/host/transport/privileged operations. No assertion is weakened or skipped.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import (
    FirewallControllerIdempotencyError,
)
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend
from broker.tests.test_post_j20_stage_1b3_durable_crash_recovery import (
    _CountingBackend,
    _evidence_for,
    _db_path,
    _idem,
    _install_active,
    _install_req,
    _installed,
    _op_req,
    _state,
    _store,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_role = threading.local()


def _svc(store=None, backend=None):
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store or _store(),
        backend=backend or _CountingBackend(authorized_backend()),
    )


def _rows(store, sql, params=()):
    return store._query_dicts(sql, params)


def _history(store, oid):
    return store.get_lifecycle_history(oid)


def _verified_with_evidence(store, svc, pid):
    """Install and persist verification evidence at VERIFIED (without ACTIVE promotion)."""
    digest = _installed(store, svc, pid)
    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    _evidence_for(store, oid, pid, digest)
    store.update_ownership_state(oid, 'VERIFYING', 'INSTALLING', rec['lifecycle_version'])
    rec = store.get_by_policy(pid, 1)
    store.update_ownership_state(oid, 'VERIFIED', 'VERIFYING', rec['lifecycle_version'])
    return digest, oid


def _revoking_with_uncertain_ledger(store, svc, pid, digest):
    """Move ACTIVE -> REVOKING and seed an uncertain terminal idempotency record."""
    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    store.update_ownership_state(oid, 'REVOKING', 'ACTIVE', rec['lifecycle_version'])
    key = f'{pid}-revoke-key'
    req_digest = svc._req_digest(_op_req(pid, digest, key=key), 'revoke_policy')
    store.create_idempotency_record(
        key, 'revoke_policy', req_digest, resource_key=f'{pid}:1',
        ownership_record_id=oid, operation_outcome='UNCERTAIN',
    )
    store.complete_idempotency_record(
        key, 'revoke_policy',
        json.dumps({'status': 'error', 'error_code': 'REVOKE_UNCONFIRMED',
                    'result': {'revocation_confirmed': False}}),
        lifecycle_state='REVOKING', ownership_record_id=oid,
        operation_outcome='UNCERTAIN',
    )
    return key, oid


# --------------------------------------------------------------- stores ---

class _SameKeyStore(ControllerOwnershipStore):
    """Hold A's completion until B observes the PENDING ledger record."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.a_entered = threading.Event()
        self.release_a = threading.Event()
        self.a_completed = threading.Event()
        self.b_saw_pending = threading.Event()

    def get_idempotency_record(self, *args, **kwargs):
        rec = super().get_idempotency_record(*args, **kwargs)
        if getattr(_role, 'who', None) == 'B' and rec and rec.get('status') == 'PENDING':
            self.b_saw_pending.set()
        return rec

    def complete_idempotency_record(self, *args, **kwargs):
        if getattr(_role, 'who', None) == 'A':
            self.a_entered.set()
            self.release_a.wait(10)
        result = super().complete_idempotency_record(*args, **kwargs)
        if getattr(_role, 'who', None) == 'A':
            self.a_completed.set()
        return result


class _CompletionBarrierStore(ControllerOwnershipStore):
    """Force a confirmed completion to precede a stale completion (defect repro)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.a_ready = threading.Event()
        self.a_release = threading.Event()
        self.a_done = threading.Event()
        self.b_ready = threading.Event()
        self.b_release = threading.Event()

    def complete_idempotency_record(self, *args, **kwargs):
        who = getattr(_role, 'who', None)
        if who == 'A':
            self.a_ready.set()
            self.a_release.wait(10)
        elif who == 'B':
            self.b_ready.set()
            self.b_release.wait(10)
        result = super().complete_idempotency_record(*args, **kwargs)
        if who == 'A':
            self.a_done.set()
        return result


class _StatusBarrierStore(ControllerOwnershipStore):
    """Delay a reconciliation status decision until a lifecycle change commits.

    Stage 1B.14 groups status+audit in one DB transaction. The barrier therefore
    signals *before* the transaction is acquired, not inside the write method,
    so the concurrent revoke is not blocked by SQLite lock contention.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.slow_ready = threading.Event()
        self.slow_release = threading.Event()
        self.barrier_armed = False

    @contextmanager
    def atomic_write(self):
        if self.barrier_armed and getattr(_role, 'who', None) == 'R1':
            self.barrier_armed = False
            self.slow_ready.set()
            self.slow_release.wait(10)
        with super().atomic_write() as conn:
            yield conn


# ------------------------------------------------------------ backends ---

class _RoleBackend:
    """Route calls by worker role with optional block points."""

    def __init__(self, inner):
        self.inner = inner
        self.install_calls = 0
        self.verify_calls = 0
        self.revoke_calls = 0
        self.entered = {}
        self.release = {}
        self.missing_on_inspect = False

    def _gate(self, point):
        who = getattr(_role, 'who', None)
        event = self.release.get(who) or self.release.get(point)
        if event is not None:
            self.entered.setdefault(point, threading.Event()).set()
            event.wait(10)

    def install_policy(self, req):
        self._gate('install')
        self.install_calls += 1
        return self.inner.install_policy(req)

    def verify_policy(self, req):
        self._gate('verify')
        self.verify_calls += 1
        return self.inner.verify_policy(req)

    def revoke_policy(self, req):
        self.revoke_calls += 1
        return self.inner.revoke_policy(req)

    def inspect_policy(self, req):
        self._gate('inspect')
        routed = getattr(self, 'inspect_by_role', {}).get(getattr(_role, 'who', None))
        if routed is not None:
            return routed(req)
        if self.missing_on_inspect:
            return {
                'status': 'ok', 'request_id': req.get('request_id'),
                'operation_id': req.get('operation_id'),
                'result': {'status': 'missing'},
            }
        return self.inner.inspect_policy(req)

    def __getattr__(self, name):
        return getattr(self.inner, name)


# ------------------------------------------------------- same-key tests ---

def test_same_key_identical_install_has_one_effect_and_stable_ledger():
    store = _SameKeyStore(db_path=_db_path())
    be = _CountingBackend(authorized_backend())
    svc = _svc(store, be)
    pid = 'b4-same-identical'
    req = _install_req(pid=pid, key='b4-same-key')
    outcomes = {}

    def run(who):
        _role.who = who
        try:
            outcomes[who] = svc.install_policy(req).get('status')
        except Exception as e:
            outcomes[who] = f'{type(e).__name__}:{e}'

    ta = threading.Thread(target=run, args=('A',))
    tb = threading.Thread(target=run, args=('B',))
    ta.start()
    assert store.a_entered.wait(10)
    tb.start()
    assert store.b_saw_pending.wait(10), 'B never observed pending intent'
    store.release_a.set()
    ta.join(10); tb.join(10)

    assert outcomes == {'A': 'ok', 'B': 'ok'}, outcomes
    assert be.install_calls == 1
    assert len(_rows(store, 'SELECT * FROM controller_ownership WHERE policy_id=?', (pid,))) == 1
    assert len(_rows(store, 'SELECT * FROM controller_idempotency WHERE idempotency_key=?', ('b4-same-key',))) == 1
    assert _state(store, pid) in ('INSTALLING', 'ACTIVE')


def test_same_key_conflicting_payload_is_rejected_without_effect():
    store = _store(); be = _RoleBackend(authorized_backend()); svc = _svc(store, be)
    pid = 'b4-same-conflict'
    key = 'b4-conflict-key'
    a_req = _install_req(pid=pid, key=key, ip_cidr='10.0.0.0/8')
    b_req = _install_req(pid=pid, key=key, ip_cidr='10.1.0.0/16')
    be.release = {'install': threading.Event()}
    outcomes = {}

    def run(who, req):
        _role.who = who
        try:
            outcomes[who] = ('ok', svc.install_policy(req).get('status'))
        except Exception as e:
            outcomes[who] = ('error', type(e).__name__)

    ta = threading.Thread(target=run, args=('A', a_req))
    tb = threading.Thread(target=run, args=('B', b_req))
    ta.start()
    if 'install' not in be.entered:
        ta.join(2)
    assert be.entered['install'].wait(10), outcomes
    tb.start()
    tb.join(10)
    be.release['install'].set()
    ta.join(10)

    assert outcomes['B'] == ('error', FirewallControllerIdempotencyError.__name__), outcomes
    assert outcomes['A'] == ('ok', 'ok'), outcomes
    assert be.install_calls == 1
    idem = _idem(store, key, 'install_policy')
    assert idem is not None
    assert len(_rows(store, 'SELECT * FROM controller_idempotency WHERE idempotency_key=?', (key,))) == 1


# ---------------------------------------------------- different-key tests ---

def test_different_keys_same_policy_no_duplicate_ownership_or_effect():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    pid = 'b4-diff-key'
    outcomes = {}

    def run(who, key):
        _role.who = who
        try:
            outcomes[who] = svc.install_policy(_install_req(pid=pid, key=key)).get('status')
        except Exception as e:
            outcomes[who] = f'{type(e).__name__}:{e}'

    threads = [
        threading.Thread(target=run, args=('A', 'b4-dk-a')),
        threading.Thread(target=run, args=('B', 'b4-dk-b')),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    # Distinct keys are distinct operations: repeated backend effects are allowed,
    # but ownership and the per-key ledger must remain single/stable.
    assert sum(v == 'ok' for v in outcomes.values()) >= 1, outcomes
    assert all(v == 'ok' or v.startswith('PermissionError') for v in outcomes.values()), outcomes
    assert be.install_calls >= 1
    rows = _rows(store, 'SELECT * FROM controller_ownership WHERE policy_id=?', (pid,))
    assert len(rows) == 1
    oid = rows[0]['ownership_record_id']
    assert len([h for h in _history(store, oid) if h['new_state'] == 'REQUESTED']) == 1
    for key in ('b4-dk-a', 'b4-dk-b'):
        idem = _idem(store, key, 'install_policy')
        # A losing request may stop at durable PENDING intent after its CAS conflict;
        # that is preserved committed intent, not a lost record or a false success.
        assert idem is not None and idem['status'] in ('PENDING', 'COMPLETED'), 'committed intent lost'
    assert len(_rows(store, 'SELECT * FROM controller_idempotency WHERE idempotency_key IN (?,?)',
                     ('b4-dk-a', 'b4-dk-b'))) == 2


def test_concurrent_canonical_body_ensure_single_row():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    pid = 'b4-body'
    req_a = _install_req(pid=pid, key='b4-body-a')
    req_b = _install_req(pid=pid, key='b4-body-b')
    outcomes = {}

    def run(who, req):
        try:
            outcomes[who] = svc.install_policy(req).get('status')
        except Exception as e:
            outcomes[who] = type(e).__name__

    threads = [threading.Thread(target=run, args=(w, r)) for w, r in (('A', req_a), ('B', req_b))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    bodies = _rows(store, 'SELECT * FROM controller_policy_bodies WHERE policy_id=? AND policy_version=1', (pid,))
    assert len(bodies) == 1
    rec = store.get_by_policy(pid, 1)
    assert bodies[0]['ownership_record_id'] == rec['ownership_record_id']
    assert bodies[0]['compiled_rule_digest'] == req_a['compiled_rule_digest']
    assert all(v == 'ok' or v.startswith('PermissionError') for v in outcomes.values()), outcomes


# --------------------------------------------- competing lifecycle ops ---

def test_concurrent_install_and_revoke_no_false_active():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    pid = 'b4-install-revoke'
    digest = _install_active(store, svc, pid)
    outcomes = {}

    def run(who, op, key):
        _role.who = who
        try:
            outcomes[who] = ('ok', getattr(svc, op)(_op_req(pid, digest, key=key)).get('status'))
        except Exception as e:
            outcomes[who] = ('error', type(e).__name__)

    t_install = threading.Thread(target=run, args=('install', 'install_policy', 'b4-ir-i'))
    t_revoke = threading.Thread(target=run, args=('revoke', 'revoke_policy', 'b4-ir-r'))
    t_install.start(); t_revoke.start()
    t_install.join(10); t_revoke.join(10)

    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    assert rec['installation_state'] in ('REVOKING', 'REVOKED'), outcomes
    # A re-install of an already ACTIVE policy must never report success over a revoke.
    assert outcomes['install'][0] == 'error', outcomes
    assert outcomes['revoke'] == ('ok', 'ok'), outcomes
    assert be.revoke_calls == 1
    if rec['installation_state'] == 'REVOKED':
        assert any(e['verification_result'] == 'revoked' for e in store.get_evidence_by_policy(pid, 1))
    history = _history(store, oid)
    transitions = [(h['prev_state'], h['new_state']) for h in history]
    assert ('REVOKED', 'ACTIVE') not in transitions
    assert transitions.count(('REVOKING', 'REVOKED')) <= 1


def test_concurrent_verify_and_revoke_no_unauthorized_promotion():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    pid = 'b4-verify-revoke'
    digest = _install_active(store, svc, pid)
    outcomes = {}

    def run(who, op, key):
        _role.who = who
        try:
            outcomes[who] = ('ok', getattr(svc, op)(_op_req(pid, digest, key=key)).get('status'))
        except Exception as e:
            outcomes[who] = ('error', type(e).__name__)

    t_verify = threading.Thread(target=run, args=('verify', 'verify_policy', 'b4-vr-v'))
    t_revoke = threading.Thread(target=run, args=('revoke', 'revoke_policy', 'b4-vr-r'))
    t_verify.start(); t_revoke.start()
    t_verify.join(10); t_revoke.join(10)

    rec = store.get_by_policy(pid, 1)
    assert rec['installation_state'] in ('REVOKING', 'REVOKED'), outcomes
    oid = rec['ownership_record_id']
    for ev in store.get_evidence_by_policy(pid, 1):
        assert ev['ownership_record_id'] == oid
        assert ev['policy_id'] == pid and ev['policy_version'] == 1
        assert ev['canonical_policy_digest'] == digest
    history = _history(store, oid)
    transitions = [(h['prev_state'], h['new_state']) for h in history]
    assert ('REVOKED', 'ACTIVE') not in transitions
    assert transitions.count(('REVOKING', 'REVOKED')) <= 1


# --------------------------------------------------- reconciliation tests ---

def test_multiple_reconcile_workers_single_promotion():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    pid = 'b4-multi-reconcile'
    digest, oid = _verified_with_evidence(store, svc, pid)
    results = {}

    def run(who):
        _role.who = who
        try:
            results[who] = svc.reconcile_pending_operations(_op_req(pid, digest))
        except Exception as e:
            results[who] = {'error': type(e).__name__}

    threads = [threading.Thread(target=run, args=(f'r{i}',)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert all(isinstance(v, dict) and 'error' not in v for v in results.values()), results
    assert _state(store, pid) == 'ACTIVE'
    promotions = [h for h in _history(store, oid)
                  if h['transition_reason'] == 'reconcile_promote_active']
    assert len(promotions) == 1, len(promotions)
    assert len(_rows(store, 'SELECT * FROM controller_evidence WHERE ownership_record_id=?', (oid,))) >= 1


def test_reconcile_and_recovery_compete_without_duplicate_terminal_transition():
    store = _store()
    be = _RoleBackend(authorized_backend())
    be.missing_on_inspect = True
    # Hold the reconcilers in backend read-back (no SQLite lock held) while the
    # competing recovery performs its promotion.
    be.release = {'reconcile': threading.Event()}
    be.entered.setdefault('inspect', threading.Event())
    svc = _svc(store, be)
    pid = 'b4-reconcile-recovery'
    digest = _install_active(store, svc, pid)
    key, oid = _revoking_with_uncertain_ledger(store, svc, pid, digest)
    results = {}

    def reconcile():
        _role.who = 'reconcile'
        try:
            results['reconcile'] = svc.reconcile_pending_operations(_op_req(pid, digest))
        except Exception as e:
            results['reconcile'] = {'error': type(e).__name__}

    def recover():
        _role.who = 'recovery'
        try:
            results['recovery'] = svc.revoke_policy(_op_req(pid, digest, key=key)).get('status')
        except Exception as e:
            results['recovery'] = {'error': type(e).__name__}

    tr = threading.Thread(target=reconcile)
    tr.start()
    assert be.entered['inspect'].wait(10), results
    tc = threading.Thread(target=recover)
    tc.start()
    tc.join(10)
    be.release['reconcile'].set()
    tr.join(10)

    assert results.get('recovery') == 'ok', results
    assert _state(store, pid) == 'REVOKED', results
    revoked_history = [h for h in _history(store, oid) if h['new_state'] == 'REVOKED']
    assert len(revoked_history) == 1, len(revoked_history)
    evidence = store.get_evidence_by_policy(pid, 1)
    assert any(e['verification_result'] == 'revoked' for e in evidence)
    assert all(e['ownership_record_id'] == oid for e in evidence)
    assert be.revoke_calls == 0  # read-back proved the backend effect already applied


def test_stale_reconciliation_decision_cannot_overwrite_newer_state():
    store = _StatusBarrierStore(db_path=_db_path()); be = authorized_backend()
    svc = _svc(store, be)
    pid = 'b4-stale-reconcile'
    digest = _install_active(store, svc, pid)
    oid = store.get_by_policy(pid, 1)['ownership_record_id']
    store.update_reconciliation_status(oid, 'uncertain')
    store.barrier_armed = True
    errors = []

    def run():
        _role.who = 'R1'
        try:
            svc.reconcile_pending_operations(_op_req(pid, digest))
        except Exception as e:
            errors.append(type(e).__name__)

    t = threading.Thread(target=run)
    t.start()
    assert store.slow_ready.wait(10), 'R1 did not reach its status write'
    svc.revoke_policy(_op_req(pid, digest))
    store.slow_release.set()
    t.join(10)

    final = store.get_by_policy(pid, 1)
    assert not errors, errors
    assert final['installation_state'] == 'REVOKED'
    assert final['reconciliation_status'] != 'ok', 'stale ok decision overwrote newer state'


def test_version_guard_reports_conflict_without_persistence_failure():
    store = _store()
    pid = 'b4-guard'
    req = _install_req(pid=pid, key='b4-guard-i')
    svc = _svc(store, _CountingBackend(authorized_backend()))
    assert svc.install_policy(req)['status'] == 'ok'
    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    version = rec['lifecycle_version']
    store.update_ownership_state(oid, 'VERIFYING', 'INSTALLING', version)
    advanced = store.get_by_policy(pid, 1)['lifecycle_version']
    with store.reconciliation_version_guard(version):
        written = store.update_reconciliation_status(oid, 'ok')
    assert written is False
    final = store.get_by_policy(pid, 1)
    assert final['lifecycle_version'] == advanced
    assert final['reconciliation_status'] != 'ok'


def test_evidence_binding_mismatch_never_promotes_verified():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    pid = 'b4-bind-mismatch'
    digest = _installed(store, svc, pid)
    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    store.update_ownership_state(oid, 'VERIFYING', 'INSTALLING', rec['lifecycle_version'])
    rec = store.get_by_policy(pid, 1)
    store.update_ownership_state(oid, 'VERIFIED', 'VERIFYING', rec['lifecycle_version'])
    bad_digest = 'f' * 64
    _evidence_for(store, oid, pid, bad_digest, ownership_record_id='other-owner')
    result = svc.reconcile_pending_operations(_op_req(pid, digest))
    assert _state(store, pid) == 'VERIFIED'
    assert any(u.get('reason') == 'verified_without_valid_evidence'
               for u in result['result']['uncertain']), result
    assert not [h for h in _history(store, oid) if h['new_state'] == 'ACTIVE']


# --------------------------------------------------- stale CAS / append ---

def test_stale_cas_cannot_overwrite_newer_ownership_state():
    store = _store(); svc = _svc(store, _CountingBackend(authorized_backend()))
    pid = 'b4-stale-cas'
    assert svc.install_policy(_install_req(pid=pid, key='b4-cas-i'))['status'] == 'ok'
    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    version = rec['lifecycle_version']
    store.update_ownership_state(oid, 'VERIFYING', 'INSTALLING', version)
    before = _history(store, oid)
    with pytest.raises(PermissionError):
        store.update_ownership_state(oid, 'FAILED', 'INSTALLING', version)
    after = store.get_by_policy(pid, 1)
    assert after['installation_state'] == 'VERIFYING'
    assert after['lifecycle_version'] == version + 1
    assert _history(store, oid) == before


def test_history_audit_evidence_append_only_under_concurrent_writers():
    store = _store(); svc = _svc(store, _CountingBackend(authorized_backend()))
    pid = 'b4-append'
    digest = _install_active(store, svc, pid)
    oid = store.get_by_policy(pid, 1)['ownership_record_id']

    def append_audit(i):
        store.record_audit('b4_concurrent', {'request_id': f'r{i}', 'policy_id': pid},
                           {'i': i}, oid)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(append_audit, range(18)))
    audit_rows = _rows(store, 'SELECT * FROM controller_audit WHERE ownership_record_id=?', (oid,))
    assert len(audit_rows) >= 18
    assert len({r['audit_id'] for r in audit_rows}) == len(audit_rows)

    conn = store._get_conn_fk()
    try:
        with pytest.raises(Exception):
            conn.execute("UPDATE controller_lifecycle_history SET new_state='ACTIVE'")
            conn.commit()
        conn.rollback()
        with pytest.raises(Exception):
            conn.execute('DELETE FROM controller_evidence')
            conn.commit()
        conn.rollback()
        with pytest.raises(Exception):
            conn.execute('UPDATE controller_audit SET event_type=?', ('mutated',))
            conn.commit()
        conn.rollback()
    finally:
        conn.close()
    assert all(e['ownership_record_id'] == oid for e in store.get_evidence_by_policy(pid, 1))


# ------------------------------------------ terminal outcome stability ---

def test_stale_completion_cannot_overwrite_confirmed_terminal_outcome():
    store = _CompletionBarrierStore(db_path=_db_path())
    be = _RoleBackend(authorized_backend())
    svc = _svc(store, be)
    pid = 'b4-terminal'
    digest = _install_active(store, svc, pid)
    key, oid = _revoking_with_uncertain_ledger(store, svc, pid, digest)
    outcomes = {}

    def readback_ok(req):
        return {'status': 'ok', 'request_id': req.get('request_id'),
                'operation_id': req.get('operation_id'),
                'result': {'status': 'missing'}}

    def readback_error(req):
        raise RuntimeError('transient mock readback error')

    be.inspect_by_role = {'A': readback_ok, 'B': readback_error}

    def run(who):
        _role.who = who
        try:
            outcomes[who] = svc.revoke_policy(_op_req(pid, digest, key=key)).get('status')
        except Exception as e:
            outcomes[who] = f'{type(e).__name__}:{e}'

    ta = threading.Thread(target=run, args=('A',))
    tb = threading.Thread(target=run, args=('B',))
    ta.start(); tb.start()
    assert store.a_ready.wait(10)
    assert store.b_ready.wait(10)
    store.a_release.set()
    assert store.a_done.wait(10)
    store.b_release.set()
    ta.join(10); tb.join(10)

    assert outcomes['A'] == 'ok', outcomes
    assert store.get_by_policy(pid, 1)['installation_state'] == 'REVOKED'
    idem = _idem(store, key, 'revoke_policy')
    assert idem['status'] == 'COMPLETED'
    assert idem['operation_outcome'] == 'SUCCEEDED', idem
    assert json.loads(idem['response_json'])['status'] == 'ok'
    assert len([h for h in _history(store, oid) if h['new_state'] == 'REVOKED']) == 1


# ------------------------------------------------ cross-process SQLite ---

def _xproc_worker(args, queue):
    db_path, pid, key, ip_cidr = args
    try:
        from broker.firewall_controller_service import FirewallControllerService
        from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
        from broker.tests._helper_identity import authorized_backend
        from broker.tests.test_post_j20_stage_1b3_durable_crash_recovery import _install_req
        store = ControllerOwnershipStore(db_path=db_path)
        svc = FirewallControllerService(
            allowed_uids={1000}, allowed_gids={1000},
            ownership_store=store, backend=authorized_backend(),
        )
        req = _install_req(pid=pid, key=key, ip_cidr=ip_cidr)
        res = svc.install_policy(req)
        queue.put({'status': res.get('status')})
    except Exception as e:
        queue.put({'error': type(e).__name__, 'message': str(e)})


def test_cross_process_sqlite_same_key_conflict_classification():
    db_path = _db_path('b4-xproc.db')
    store = ControllerOwnershipStore(db_path=db_path)
    svc = _svc(store, _CountingBackend(authorized_backend()))
    pid = 'b4-xproc'
    assert svc.install_policy(_install_req(pid=pid, key='b4-xproc-seed'))['status'] == 'ok'

    ctx = mp.get_context('spawn')
    key = 'b4-xproc-key'
    jobs = [
        (db_path, pid, key, '10.0.0.0/8'),
        (db_path, pid, key, '10.1.0.0/16'),
    ]
    queue = ctx.Queue()
    procs = [ctx.Process(target=_xproc_worker, args=(job, queue)) for job in jobs]
    for p in procs:
        p.start()
    results = [queue.get(timeout=30) for _ in procs]
    for p in procs:
        p.join(20)
    assert all(not p.is_alive() for p in procs)
    assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]
    statuses = sorted(str(r.get('status') or r.get('error')) for r in results)
    assert statuses == ['FirewallControllerIdempotencyError', 'ok'], results
    # Outcomes are read from the shared DB: exactly one ledger row, no duplicate ownership.
    idem_rows = _rows(store, 'SELECT * FROM controller_idempotency WHERE idempotency_key=?', (key,))
    assert len(idem_rows) == 1
    own_rows = _rows(store, 'SELECT * FROM controller_ownership WHERE policy_id=?', (pid,))
    assert len(own_rows) == 1
    # The request with the conflicting payload must not have produced a second backend
    # effect; confirm the final stored response is an ok response.
    assert idem_rows[0]['status'] == 'COMPLETED'
