"""Post-J.20 Stage 1B.3 — durable crash recovery and reconciliation (mock-only).

Deterministic fault injection plus real spawned-process kills at durable boundaries.
All state is a disposable SQLite DB and a file-backed *mock* backend (test-only).
No Docker/host/transport/privileged operations. No assertions weakened or skipped.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import (
    FirewallControllerBackendError,
    FirewallControllerIdempotencyError,
    FirewallControllerPersistenceError,
)
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend
from broker.tests.test_firewall_controller_cross_process_crash_recovery import (
    _be_load,
    _make_file_backed_backend,
    _wait_for_signal,
)


# ---------------------------------------------------------------- helpers ---

def _db_path(name="b3.db"):
    return os.path.join(tempfile.mkdtemp(), name)


def _rule():
    return {
        "family": "ipv4", "direction": "ingress", "protocol": "tcp",
        "source_cidr": "10.0.0.0/24", "destination_cidr": "10.0.1.0/24",
        "port_start": 80, "port_end": 80, "action": "accept",
    }


def _install_req(pid=None, key=None, **overrides):
    rules = [_rule()]
    norm = validate_and_normalize_rules(rules, ['ipv4'])
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid or f"p-{uuid.uuid4()}", "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(norm), "compiled": {},
        "rules": rules, "required_families": ['ipv4'],
        "peer_uid": 1000, "peer_gid": 1000, "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


def _op_req(pid, digest, key=None, ver=1):
    return {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid, "policy_version": ver,
        "compiled_rule_digest": digest,
        "peer_uid": 1000, "peer_gid": 1000, "instance_id": "i1", "network_id": "n1",
    }


class _FaultStore(ControllerOwnershipStore):
    """In-process fault injection for deterministic durable-boundary failures."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_get_by_policy = False
        self.fail_pending_scan = False
        self.fail_before_complete = False
        self.fail_complete = False
        self.raise_after_evidence = False
        self.fail_evidence = False
        self.fail_history_on = None
        self.fail_commit = False
        self._db_proxy = None
        self._arm_commit_failure()

    def _arm_commit_failure(self):
        class FailingCommitConn:
            def __init__(self, real, owner):
                self._real = real
                self._owner = owner

            def commit(self):
                if self._owner.fail_commit:
                    self._owner.fail_commit = False
                    raise sqlite3.OperationalError('injected commit failure')
                return self._real.commit()

            def __getattr__(self, name):
                return getattr(self._real, name)

        class DBProxy:
            def __init__(self, real, owner):
                self._real = real
                self._owner = owner

            def _get_conn(self):
                return FailingCommitConn(self._real._get_conn(), self._owner)

            def __getattr__(self, name):
                return getattr(self._real, name)

        self._db_proxy = DBProxy(self.db, self)
        self.db = self._db_proxy

    def get_by_policy(self, *args, **kwargs):
        if self.fail_get_by_policy:
            raise BrokerDBError('injected authoritative read failure')
        return super().get_by_policy(*args, **kwargs)

    def get_pending_idempotency(self):
        if self.fail_pending_scan:
            raise BrokerDBError('injected ledger scan failure')
        return super().get_pending_idempotency()

    def complete_idempotency_record(self, *args, **kwargs):
        if self.fail_before_complete:
            raise BrokerDBError('injected failure before idempotency completion')
        if self.fail_complete:
            raise BrokerDBError('injected idempotency completion failure')
        return super().complete_idempotency_record(*args, **kwargs)

    def store_evidence(self, ev):
        if self.fail_evidence:
            raise BrokerDBError('injected evidence persistence failure')
        result = super().store_evidence(ev)
        if self.raise_after_evidence:
            self.raise_after_evidence = False
            raise BrokerDBError('injected crash after durable evidence persistence')
        return result

    def record_lifecycle_transition(self, *args, **kwargs):
        new_state = args[4] if len(args) > 4 else kwargs.get('new_state')
        if new_state == self.fail_history_on:
            raise BrokerDBError('injected lifecycle history persistence failure')
        return super().record_lifecycle_transition(*args, **kwargs)


class _BackendErrorOnInstall:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def install_policy(self, req):
        self.calls += 1
        return {
            'status': 'error', 'request_id': req.get('request_id'),
            'operation_id': req.get('operation_id'),
            'error_code': 'INSTALL_FAILED', 'error_message': 'mock failure',
            'result': {},
        }

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _BackendReadbackFails:
    def __init__(self, inner):
        self.inner = inner

    def inspect_policy(self, req):
        raise RuntimeError('mock readback unavailable')

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _CountingBackend:
    def __init__(self, inner):
        self.inner = inner
        self.install_calls = 0
        self.verify_calls = 0
        self.revoke_calls = 0

    def install_policy(self, req):
        self.install_calls += 1
        return self.inner.install_policy(req)

    def verify_policy(self, req):
        self.verify_calls += 1
        return self.inner.verify_policy(req)

    def revoke_policy(self, req):
        self.revoke_calls += 1
        return self.inner.revoke_policy(req)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _store(path=None):
    return _FaultStore(db_path=path or _db_path())


def _svc(store=None, backend=None):
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store or _store(),
        backend=backend or _CountingBackend(authorized_backend()),
    )


def _state(store, pid, ver=1):
    rec = store.get_by_policy(pid, ver)
    return rec.get('installation_state') if rec else None


def _hist(store, oid):
    return store.get_lifecycle_history(oid)


def _idem(store, key, op='install_policy'):
    return store.get_idempotency_record(key, op)


def _sql(store, sql, params=()):
    conn = store._get_conn_fk()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _reconcile(svc, pid, digest, ver=1):
    return svc.reconcile_pending_operations(_op_req(pid, digest, ver=ver))


def _evidence_for(store, oid, pid, digest, result='verified', **overrides):
    ev = {
        'evidence_id': str(uuid.uuid4()), 'ownership_record_id': oid,
        'policy_id': pid, 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1',
        'canonical_policy_digest': digest, 'address_family': 'ipv4',
        'installed_rule_ids': [], 'controller_identity': 'test',
        'controller_transaction_id': str(uuid.uuid4()),
        'request_id': str(uuid.uuid4()), 'verification_result': result,
    }
    ev.update(overrides)
    store.store_evidence(ev)
    return ev['evidence_id']


def _installed(store, svc, pid):
    req = _install_req(pid=pid)
    assert svc.install_policy(req)['status'] == 'ok'
    return req['compiled_rule_digest']


def _install_active(store, svc, pid):
    digest = _installed(store, svc, pid)
    assert svc.verify_policy(_op_req(pid, digest))['status'] == 'ok'
    return digest


def _verifying_with_evidence(store, svc, pid):
    """Install, persist verification evidence, then simulate the VERIFYING crash point."""
    digest = _installed(store, svc, pid)
    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    store.raise_after_evidence = True
    with pytest.raises(BrokerDBError):
        svc.verify_policy(_op_req(pid, digest))
    rec = store.get_by_policy(pid, 1)
    assert rec.get('installation_state') == 'INSTALLING'
    assert any(e.get('verification_result') == 'verified'
               for e in store.get_evidence_by_policy(pid, 1))
    store.update_ownership_state(oid, 'VERIFYING', 'INSTALLING', rec['lifecycle_version'])
    return digest, oid


# --------------------------------------------------- in-process recovery ---

def test_intent_only_crash_stays_uncertain_and_never_fabricates_success():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    req = _install_req(pid='b3-intent', key='b3-intent-key')

    class ExplodeBackend:
        def __init__(self, inner):
            self.inner = inner

        def install_policy(self, req):
            raise RuntimeError('simulated crash after intent persistence')

        def __getattr__(self, name):
            return getattr(self.inner, name)

    svc2 = _svc(store, ExplodeBackend(be))
    with pytest.raises(FirewallControllerBackendError):
        svc2.install_policy(req)
    idem = _idem(store, 'b3-intent-key')
    assert idem and idem['status'] == 'PENDING'
    assert idem['operation_outcome'] in ('INTENT_RECORDED', 'IN_PROGRESS')
    assert not idem.get('response_json')
    assert store.get_by_policy('b3-intent', 1) is not None
    assert _state(store, 'b3-intent') in ('REQUESTED', 'VALIDATING')
    assert be.install_calls == 0

    res = _reconcile(svc, 'b3-intent', req['compiled_rule_digest'])
    assert res['status'] == 'ok'
    uncertain = res['result']['uncertain']
    assert any(e.get('idempotency_key') == 'b3-intent-key'
               and e.get('reason') == 'pending_no_auto_replay' for e in uncertain)
    assert _state(store, 'b3-intent') != 'ACTIVE'


def test_crash_after_ownership_intent_preserves_committed_intent():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    req = _install_req(pid='b3-own', key='b3-own-key')
    store.fail_history_on = 'REQUESTED'
    with pytest.raises(BrokerDBError):
        svc.install_policy(req)
    # Group rollback: ownership intent and history are absent, ledger intent survives.
    assert store.get_by_policy('b3-own', 1) is None
    assert _idem(store, 'b3-own-key') is not None
    assert be.install_calls == 0
    store.fail_history_on = None
    assert svc.install_policy(_install_req(pid='b3-own', key='b3-own-key-2'))['status'] == 'ok'
    assert _state(store, 'b3-own') == 'INSTALLING'


def test_backend_effect_then_crash_is_uncertain_without_duplicate_effect():
    path = _db_path(); store = _store(path)
    be = _CountingBackend(authorized_backend())

    class EffectThenCrash:
        def __init__(self, inner):
            self.inner = inner
            self.crash = True

        def install_policy(self, req):
            res = self.inner.install_policy(req)
            if self.crash:
                self.crash = False
                raise RuntimeError('simulated crash after durable backend effect')
            return res

        def __getattr__(self, name):
            return getattr(self.inner, name)

    shared = EffectThenCrash(be)
    svc = _svc(store, shared)
    req = _install_req(pid='b3-effect', key='b3-effect-key')
    with pytest.raises(FirewallControllerBackendError):
        svc.install_policy(req)
    assert be.install_calls == 1
    assert _state(store, 'b3-effect') in ('REQUESTED', 'VALIDATING', 'INSTALLING')
    assert _state(store, 'b3-effect') != 'ACTIVE'
    assert _idem(store, 'b3-effect-key')['status'] == 'PENDING'

    fresh = _store(path)
    svc2 = _svc(fresh, shared)
    res = _reconcile(svc2, 'b3-effect', req['compiled_rule_digest'])
    assert res['status'] == 'ok'
    assert _state(fresh, 'b3-effect') != 'ACTIVE'
    assert be.install_calls == 1  # recovery never repeats the install effect
    # Explicit, evidence-backed verification is the only promotion path.
    assert svc2.verify_policy(_op_req('b3-effect', req['compiled_rule_digest']))['status'] == 'ok'
    assert _state(fresh, 'b3-effect') == 'ACTIVE'
    assert be.install_calls == 1


def test_evidence_then_crash_does_not_autopromote_and_explicit_verify_recovers():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    digest, oid = _verifying_with_evidence(store, svc, 'b3-evidence')
    assert _state(store, 'b3-evidence') == 'VERIFYING'
    assert be.verify_calls == 1
    res = _reconcile(svc, 'b3-evidence', digest)
    assert res['status'] == 'ok'
    assert _state(store, 'b3-evidence') == 'ACTIVE'
    assert any(r.get('action') == 'verifying_recovered_with_evidence'
               for r in res['result']['reconciled'])
    assert be.verify_calls == 1  # no duplicate backend verification


def test_verifying_without_evidence_stays_uncertain():
    store = _store(); svc = _svc(store)
    digest = _installed(store, svc, 'b3-verifying-none')
    rec = store.get_by_policy('b3-verifying-none', 1)
    store.update_ownership_state(rec['ownership_record_id'], 'VERIFYING',
                                 rec['installation_state'], rec['lifecycle_version'])
    res = _reconcile(svc, 'b3-verifying-none', digest)
    assert res['status'] == 'ok'
    assert any(u.get('reason') == 'verifying_state_uncertain'
               for u in res['result']['uncertain'])
    assert _state(store, 'b3-verifying-none') == 'VERIFYING'


def test_verifying_with_mismatched_evidence_stays_uncertain():
    store = _store(); svc = _svc(store)
    digest = _installed(store, svc, 'b3-verifying-bad')
    rec = store.get_by_policy('b3-verifying-bad', 1)
    oid = rec['ownership_record_id']
    # Only evidence with a mismatched digest exists: it cannot prove verification.
    _evidence_for(store, oid, 'b3-verifying-bad', 'f' * 64)
    store.update_ownership_state(oid, 'VERIFYING', 'INSTALLING', rec['lifecycle_version'])
    res = _reconcile(svc, 'b3-verifying-bad', digest)
    assert res['status'] == 'ok'
    assert any(u.get('reason') == 'verifying_state_uncertain'
               for u in res['result']['uncertain'])
    assert _state(store, 'b3-verifying-bad') == 'VERIFYING'


def test_verifying_recovery_fails_closed_when_readback_unavailable():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    digest, oid = _verifying_with_evidence(store, svc, 'b3-verifying-readback')
    failed = _BackendReadbackFails(be)
    svc2 = _svc(store, failed)
    res = _reconcile(svc2, 'b3-verifying-readback', digest)
    assert res['status'] == 'ok'
    assert any(u.get('reason') == 'verifying_state_uncertain'
               for u in res['result']['uncertain'])
    assert _state(store, 'b3-verifying-readback') == 'VERIFYING'
    assert be.verify_calls == 1


def test_repeated_verifying_recovery_is_bounded_and_does_not_duplicate_history():
    store = _store(); svc = _svc(store)
    digest, oid = _verifying_with_evidence(store, svc, 'b3-repeat')
    h0 = len(_hist(store, oid))
    e0 = len(store.get_evidence_by_policy('b3-repeat', 1))
    r1 = _reconcile(svc, 'b3-repeat', digest)
    r2 = _reconcile(svc, 'b3-repeat', digest)
    assert r1['status'] == r2['status'] == 'ok'
    assert _state(store, 'b3-repeat') == 'ACTIVE'
    assert len(_hist(store, oid)) == h0 + 2
    assert len(store.get_evidence_by_policy('b3-repeat', 1)) == e0
    assert not any(r.get('action') == 'verifying_recovered_with_evidence'
                   for r in r2['result']['reconciled'])


def test_verified_history_then_crash_before_active_is_recovered():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    digest = _installed(store, svc, 'b3-verified')
    oid = store.get_by_policy('b3-verified', 1)['ownership_record_id']
    store.fail_history_on = 'ACTIVE'
    with pytest.raises(BrokerDBError):
        svc.verify_policy(_op_req('b3-verified', digest))
    assert _state(store, 'b3-verified') == 'VERIFIED'
    assert any(e.get('verification_result') == 'verified'
               for e in store.get_evidence_by_policy('b3-verified', 1))
    store.fail_history_on = None
    res = _reconcile(svc, 'b3-verified', digest)
    assert res['status'] == 'ok'
    assert _state(store, 'b3-verified') == 'ACTIVE'
    assert any(r.get('action') == 'promoted_to_active' for r in res['result']['reconciled'])
    assert be.verify_calls == 1


def test_crash_before_idempotency_completion_leaves_no_fabricated_response():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    req = _install_req(pid='b3-pending', key='b3-pending-key')
    store.fail_before_complete = True
    with pytest.raises(BrokerDBError):
        svc.install_policy(req)
    assert be.install_calls == 1
    assert _state(store, 'b3-pending') == 'INSTALLING'
    idem = _idem(store, 'b3-pending-key')
    assert idem['status'] == 'PENDING'
    assert not idem.get('response_json')
    assert idem['operation_outcome'] != 'SUCCEEDED'
    # Same-key retry is rejected without a second backend effect.
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(req)
    assert be.install_calls == 1
    res = _reconcile(svc, 'b3-pending', req['compiled_rule_digest'])
    assert res['status'] == 'ok'
    assert _state(store, 'b3-pending') != 'ACTIVE'


def test_reconcile_initial_read_storage_failure_propagates_not_absence():
    store = _store(); svc = _svc(store)
    store.fail_get_by_policy = True
    with pytest.raises(BrokerDBError):
        _reconcile(svc, 'b3-readfail', 'a' * 64)
    store.fail_get_by_policy = False
    # A storage failure is never reinterpreted as missing ownership or backend uncertainty.
    assert store.get_by_policy('b3-readfail', 1) is None


def test_reconcile_pending_ledger_scan_failure_is_classified():
    store = _store(); svc = _svc(store)
    digest = _installed(store, svc, 'b3-scanfail')
    store.fail_pending_scan = True
    res = _reconcile(svc, 'b3-scanfail', digest)
    store.fail_pending_scan = False
    assert res['status'] == 'error'
    assert res['error_code'] == 'RECONCILIATION_PERSISTENCE_FAILURE'
    assert any(e.get('error_code') == 'PERSISTENCE_FAILURE' for e in res['result']['errors'])


def test_install_failure_split_write_reports_granular_persistence_state():
    store = _store(); be = _BackendErrorOnInstall(authorized_backend()); svc = _svc(store, be)
    req = _install_req(pid='b3-fail', key='b3-fail-key')
    store.fail_history_on = 'FAILED'
    with pytest.raises(FirewallControllerPersistenceError) as exc:
        svc.install_policy(req)
    details = exc.value.details or {}
    assert details.get('failure_state_persisted') is True
    assert details.get('lifecycle_history_persisted') is False
    assert details.get('backend_error_code') == 'INSTALL_FAILED'
    assert _state(store, 'b3-fail') == 'FAILED'
    assert _idem(store, 'b3-fail-key')['operation_outcome'] != 'SUCCEEDED'


def test_revoke_evidence_then_crash_recovers_without_duplicate_effect():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    pid = 'b3-revoke'
    digest = _install_active(store, svc, pid)
    store.update_ownership_state(store.get_by_policy(pid, 1)['ownership_record_id'],
                                 'REVOKING', 'ACTIVE',
                                 store.get_by_policy(pid, 1)['lifecycle_version'])
    store.fail_history_on = 'REVOKED'
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(_op_req(pid, digest, key='b3-revoke-key'))
    assert _state(store, pid) == 'REVOKING'
    assert any(e.get('verification_result') == 'revoked'
               for e in store.get_evidence_by_policy(pid, 1))
    assert be.revoke_calls == 1
    store.fail_history_on = None
    res = _reconcile(svc, pid, digest)
    assert res['status'] == 'ok'
    assert _state(store, pid) == 'REVOKED'
    assert be.revoke_calls == 1
    assert len([e for e in store.get_evidence_by_policy(pid, 1)
                if e.get('verification_result') == 'revoked']) == 1


def test_conflicting_duplicate_is_distinct_from_pending_and_uncertain():
    store = _store(); svc = _svc(store)
    req = _install_req(pid='b3-conflict', key='b3-conflict-key')
    assert svc.install_policy(req)['status'] == 'ok'
    conflict = _install_req(pid='b3-conflict', key='b3-conflict-key', instance_id='other')
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(conflict)
    assert _idem(store, 'b3-conflict-key')['operation_outcome'] == 'SUCCEEDED'
    pending_digest = _installed(store, svc, 'b3-conflict-pending')
    store.create_idempotency_record('b3-pending-key', 'install_policy', 'd' * 64,
                                    resource_key='b3-conflict-pending:1')
    res = _reconcile(svc, 'b3-conflict-pending', pending_digest)
    assert any(e.get('reason') == 'pending_no_auto_replay' for e in res['result']['uncertain'])


def test_canonical_body_persisted_before_crash_is_validated_on_recovery():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    digest, oid = _verifying_with_evidence(store, svc, 'b3-canonical')
    body = store.get_canonical_policy_body('b3-canonical', 1)
    assert body is not None and body.get('compiled_rule_digest') == digest
    _sql(store,
         'UPDATE controller_policy_bodies SET canonical_rules_json=? WHERE policy_body_id=?',
         ('{corrupt', body['policy_body_id']))
    res = _reconcile(svc, 'b3-canonical', digest)
    assert res['status'] == 'ok'
    assert _state(store, 'b3-canonical') == 'VERIFYING'
    assert any(u.get('reason') == 'invalid_canonical_policy_body'
               for u in res['result']['uncertain'])


# ------------------------------------------- real spawned-process helpers ---

class _CrashStore(ControllerOwnershipStore):
    """Kills the OS process at a named durable boundary (worker-only)."""

    crash_after = None
    group_count = 0

    def _maybe_crash(self, name):
        if self.crash_after == name:
            os._exit(9)

    @contextmanager
    def atomic_write(self):
        with super().atomic_write() as conn:
            yield conn
        type(self).group_count += 1
        self._maybe_crash(f'group{type(self).group_count}')

    def create_idempotency_record(self, *args, **kwargs):
        result = super().create_idempotency_record(*args, **kwargs)
        self._maybe_crash('intent')
        return result

    def store_evidence(self, ev):
        result = super().store_evidence(ev)
        self._maybe_crash('evidence')
        return result

    def update_ownership_state(self, *args, **kwargs):
        result = super().update_ownership_state(*args, **kwargs)
        if len(args) > 1 and args[1] == 'VERIFYING':
            self._maybe_crash('verifying')
        return result

    def complete_idempotency_record(self, *args, **kwargs):
        if self.crash_after == 'before_complete':
            os._exit(9)
        result = super().complete_idempotency_record(*args, **kwargs)
        self._maybe_crash('complete')
        return result


class _KillAfterBackendSave:
    """Signals then kills only after the file-backed mock backend state is durable."""

    def __init__(self, inner, sig_path):
        self.inner = inner
        self.sig_path = sig_path

    def install_policy(self, req):
        res = self.inner.install_policy(req)
        with open(self.sig_path, 'a', encoding='utf-8') as f:
            f.write('blocked_at:after_backend_save\n')
        # Real OS-process death after the mock backend effect is durably saved.
        os._exit(9)
        return res  # pragma: no cover

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _w_install_crash(args):
    db_path, be_path, sig_path, crash_after, pid, key = args
    store = _CrashStore(db_path=db_path)
    store.crash_after = crash_after
    backend = _make_file_backed_backend(be_path)
    if sig_path:
        backend = _KillAfterBackendSave(backend, sig_path)
    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=backend,
    )
    try:
        svc.install_policy(_op_req(pid, 'a' * 64, key=key))
    except BaseException:
        pass
    return {'pid': os.getpid()}


def _w_verify_crash(args):
    db_path, be_path, crash_after, pid, digest, key = args
    store = _CrashStore(db_path=db_path)
    store.crash_after = crash_after
    backend = _make_file_backed_backend(be_path)
    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=backend,
    )
    try:
        svc.verify_policy(_op_req(pid, digest, key=key))
    except BaseException:
        pass
    return {'pid': os.getpid()}


def _w_revoke_crash(args):
    db_path, be_path, crash_after, pid, digest, key = args
    store = _CrashStore(db_path=db_path)
    store.crash_after = crash_after
    backend = _make_file_backed_backend(be_path)
    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=backend,
    )
    try:
        svc.revoke_policy(_op_req(pid, digest, key=key))
    except BaseException:
        pass
    return {'pid': os.getpid()}


def _w_reconcile(args):
    db_path, be_path, pid, ver, digest, fail_mode = args
    from broker.firewall_controller_service import FirewallControllerService as Svc
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore as Store
    backend = _make_file_backed_backend(be_path, fail_mode=fail_mode)
    svc = Svc(allowed_uids={1000}, allowed_gids={1000},
              ownership_store=Store(db_path=db_path), backend=backend)
    res = svc.reconcile_pending_operations(_op_req(pid, digest, ver=ver))
    rec = svc.ownership_store.get_by_policy(pid, ver)
    oid = rec['ownership_record_id'] if rec else None
    return {
        'result': res,
        'state': rec.get('installation_state') if rec else None,
        'history_count': len(svc.ownership_store.get_lifecycle_history(oid)) if oid else 0,
        'evidence_count': len(svc.ownership_store.get_evidence_by_policy(pid, ver)),
        'pending': [i.get('idempotency_key') for i in svc.ownership_store.get_pending_idempotency()],
    }


def _w_reconcile_file(args):
    db_path, be_path, pid, ver, digest, fail_mode, out_path = args
    result = _w_reconcile((db_path, be_path, pid, ver, digest, fail_mode))
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f)


def _spawn(ctx, target, args, timeout=30):
    proc = ctx.Process(target=target, args=(args,))
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
    exitcode = proc.exitcode
    proc.close()
    return exitcode


def _fresh_reconcile(ctx, db_path, be_path, pid, digest, ver=1, fail_mode=None):
    out_path = _db_path('b3-reconcile.json')
    exitcode = _spawn(ctx, _w_reconcile_file,
                      (db_path, be_path, pid, ver, digest, fail_mode, out_path))
    assert exitcode == 0, f'recovery worker exit={exitcode}'
    with open(out_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ------------------------------------------------ real process crash tests ---

def test_xproc_crash_after_intent_persistence_never_fabricates_success():
    ctx = mp.get_context('spawn')
    db_path, be_path = _db_path('b3-xintent.db'), _db_path('b3-xintent.json')
    key, pid, digest = 'b3-xintent-key', 'b3-xintent', 'a' * 64
    exitcode = _spawn(ctx, _w_install_crash, (db_path, be_path, None, 'intent', pid, key))
    assert exitcode == 9
    store = _store(db_path)
    idem = _idem(store, key)
    assert idem and idem['status'] == 'PENDING'
    assert store.get_by_policy(pid, 1) is None
    assert _be_load(be_path).get('installed', {}) == {}
    rec = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert rec['result']['status'] == 'ok'
    assert rec['state'] is None
    assert any(i == key for i in rec['pending'])


def test_xproc_crash_after_ownership_transition_preserves_committed_intent():
    ctx = mp.get_context('spawn')
    db_path, be_path = _db_path('b3-xown.db'), _db_path('b3-xown.json')
    key, pid, digest = 'b3-xown-key', 'b3-xown', 'a' * 64
    exitcode = _spawn(ctx, _w_install_crash, (db_path, be_path, None, 'group1', pid, key))
    assert exitcode == 9
    store = _store(db_path)
    assert _state(store, pid) == 'REQUESTED'
    assert len(_hist(store, store.get_by_policy(pid, 1)['ownership_record_id'])) == 1
    assert _idem(store, key) is not None
    assert _be_load(be_path).get('installed', {}) == {}
    rec = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert rec['result']['status'] == 'ok'
    assert rec['state'] in ('REQUESTED', 'FAILED')
    assert rec['state'] != 'ACTIVE'


def test_xproc_crash_after_durable_backend_effect_before_completion():
    ctx = mp.get_context('spawn')
    db_path, be_path, sig = (_db_path('b3-xbackend.db'),
                             _db_path('b3-xbackend.json'),
                             _db_path('b3-xbackend.sig'))
    key, pid, digest = 'b3-xbackend-key', 'b3-xbackend', 'a' * 64
    exitcode = _spawn(ctx, _w_install_crash,
                      (db_path, be_path, sig, None, pid, key))
    assert exitcode == 9
    assert _wait_for_signal(sig, 'after_backend_save')
    assert pid in _be_load(be_path)['installed']  # effect is durable before the kill
    store = _store(db_path)
    assert _state(store, pid) in ('REQUESTED', 'VALIDATING')
    assert _idem(store, key)['status'] == 'PENDING'
    rec = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert rec['result']['status'] == 'ok'
    assert rec['state'] in ('VALIDATING', 'INSTALLING', 'FAILED')
    assert rec['state'] != 'ACTIVE'
    again = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert again['state'] == rec['state']
    assert again['history_count'] == rec['history_count']
    assert again['evidence_count'] == rec['evidence_count']
    assert pid in _be_load(be_path)['installed']


def test_xproc_crash_after_evidence_persistence_then_fresh_recovery():
    ctx = mp.get_context('spawn')
    db_path, be_path = _db_path('b3-xev.db'), _db_path('b3-xev.json')
    pid, digest, key = 'b3-xev', 'a' * 64, 'b3-xev-install'
    # Install in a worker without crashing so backend state is file-durable.
    assert _spawn(ctx, _w_install_crash,
                  (db_path, be_path, None, None, pid, key)) in (0, None)
    store = _store(db_path)
    assert _state(store, pid) == 'INSTALLING'
    exitcode = _spawn(ctx, _w_verify_crash, (db_path, be_path, 'evidence', pid, digest, 'b3-xev-verify'))
    assert exitcode == 9
    store = _store(db_path)
    assert any(e.get('verification_result') == 'verified'
               for e in store.get_evidence_by_policy(pid, 1))
    rec = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert rec['result']['status'] == 'ok'
    assert rec['state'] in ('INSTALLING', 'ACTIVE')
    assert rec['state'] != 'ACTIVE' or rec['evidence_count'] >= 1


def test_xproc_crash_after_verified_history_before_active_recovers():
    ctx = mp.get_context('spawn')
    db_path, be_path = _db_path('b3-xver.db'), _db_path('b3-xver.json')
    pid, digest = 'b3-xver', 'a' * 64
    assert _spawn(ctx, _w_install_crash,
                  (db_path, be_path, None, None, pid, 'b3-xver-install')) in (0, None)
    # Stage 1B.14 journals VERIFYING as grouped write #1; VERIFIED history is #2.
    exitcode = _spawn(ctx, _w_verify_crash, (db_path, be_path, 'group2', pid, digest, 'b3-xver-verify'))
    assert exitcode == 9
    assert _state(_store(db_path), pid) == 'VERIFIED'
    rec = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert rec['result']['status'] == 'ok'
    assert rec['state'] == 'ACTIVE'
    assert any(r.get('action') == 'promoted_to_active' for r in rec['result']['result']['reconciled'])
    again = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert again['state'] == 'ACTIVE'
    assert again['history_count'] == rec['history_count']


def test_xproc_crash_before_idempotency_completion_is_not_fabricated():
    ctx = mp.get_context('spawn')
    db_path, be_path = _db_path('b3-xcomplete.db'), _db_path('b3-xcomplete.json')
    key, pid, digest = 'b3-xcomplete-key', 'b3-xcomplete', 'a' * 64
    exitcode = _spawn(ctx, _w_install_crash,
                      (db_path, be_path, None, 'before_complete', pid, key))
    assert exitcode == 9
    store = _store(db_path)
    assert _state(store, pid) == 'INSTALLING'
    idem = _idem(store, key)
    assert idem['status'] == 'PENDING' and not idem.get('response_json')
    assert pid in _be_load(be_path)['installed']
    rec = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert rec['result']['status'] == 'ok'
    assert rec['state'] != 'ACTIVE'
    assert key in rec['pending']


def test_xproc_recovery_with_unavailable_readback_stays_uncertain():
    ctx = mp.get_context('spawn')
    db_path, be_path = _db_path('b3-xread.db'), _db_path('b3-xread.json')
    pid, digest, key = 'b3-xread', 'a' * 64, 'b3-xread-install'
    assert _spawn(ctx, _w_install_crash,
                  (db_path, be_path, None, None, pid, key)) in (0, None)
    before = _state(_store(db_path), pid)
    rec = _fresh_reconcile(ctx, db_path, be_path, pid, digest, fail_mode='readback_unavailable')
    assert rec['result']['status'] == 'ok'
    assert rec['state'] == before
    assert rec['state'] != 'ACTIVE'
    assert any(u.get('reason') in ('backend_readback_unavailable', 'pending_no_auto_replay')
               for u in rec['result']['result']['uncertain'])


def test_xproc_revoke_crash_after_evidence_before_promotion_recovers():
    ctx = mp.get_context('spawn')
    db_path, be_path = _db_path('b3-xrevoke.db'), _db_path('b3-xrevoke.json')
    pid, digest = 'b3-xrevoke', 'a' * 64
    assert _spawn(ctx, _w_install_crash,
                  (db_path, be_path, None, None, pid, 'b3-xrevoke-install')) in (0, None)
    # Drive to REVOKING in-process using a fresh file-backed backend state.
    from broker.firewall_controller_service import FirewallControllerService as Svc
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore as Store
    svc = Svc(allowed_uids={1000}, allowed_gids={1000},
              ownership_store=Store(db_path=db_path),
              backend=_make_file_backed_backend(be_path))
    # Verify first (file backend records verified), then mark REVOKING with CAS.
    assert svc.verify_policy(_op_req(pid, digest))['status'] == 'ok'
    rec0 = svc.ownership_store.get_by_policy(pid, 1)
    svc.ownership_store.update_ownership_state(rec0['ownership_record_id'], 'REVOKING',
                                               'ACTIVE', rec0['lifecycle_version'])
    exitcode = _spawn(ctx, _w_revoke_crash, (db_path, be_path, 'evidence', pid, digest, 'b3-xrevoke-key'))
    assert exitcode == 9
    assert _state(_store(db_path), pid) == 'REVOKING'
    rec = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert rec['result']['status'] == 'ok'
    assert rec['state'] == 'REVOKED'
    assert rec['evidence_count'] >= 1
    again = _fresh_reconcile(ctx, db_path, be_path, pid, digest)
    assert again['state'] == 'REVOKED'
    assert again['history_count'] == rec['history_count']
