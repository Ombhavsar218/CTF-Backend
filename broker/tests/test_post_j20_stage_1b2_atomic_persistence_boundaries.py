"""Post-J.20 Stage 1B.2 — atomic persistence boundaries (mock-only).

Deterministic fault injection at every grouped-write boundary. All state is a
disposable SQLite DB; all backend effects are the existing in-memory mock. No
Docker/host/transport/privileged operations. No assertions weakened or skipped.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


# ---------------------------------------------------------------- helpers ---

def _db_path(name="b2.db"):
    return os.path.join(tempfile.mkdtemp(), name)


class _FailingCommitConn:
    """Connection proxy that fails exactly one commit when armed."""
    def __init__(self, real, owner):
        self._real = real
        self._owner = owner

    def commit(self):
        if self._owner.armed:
            self._owner.armed = False
            raise sqlite3.OperationalError('injected commit failure')
        return self._real.commit()

    def __getattr__(self, name):
        return getattr(self._real, name)


class _DBProxy:
    """Proxy around BrokerDB used only to arm commit failures."""
    def __init__(self, real):
        self._real = real
        self.armed = False

    def _get_conn(self):
        conn = self._real._get_conn()
        if self.armed:
            return _FailingCommitConn(conn, self)
        return conn

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AtomicFaultStore(ControllerOwnershipStore):
    """Subclass fault store: overrides fire for calls made through the store."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._db_proxy = _DBProxy(self.db)
        self.db = self._db_proxy
        self.fail_before_group = False
        self.fail_ownership = False
        self.fail_history = False
        self.fail_history_on_new_state = None
        self.fail_evidence = False
        self.fail_audit = False
        self.fail_idem_complete = False
        self.fail_commit = False
        self.fail_commit_on_group = None
        self.groups_entered = 0

    @contextmanager
    def atomic_write(self):
        self.groups_entered += 1
        if self.fail_before_group:
            raise BrokerDBError('injected failure before transaction start')
        if self.fail_commit and (
            self.fail_commit_on_group is None
            or self.groups_entered == self.fail_commit_on_group
        ):
            self.fail_commit = False
            self._db_proxy.armed = True
        try:
            with super().atomic_write() as conn:
                yield conn
        finally:
            self._db_proxy.armed = False

    def create_ownership(self, rec):
        if self.fail_ownership:
            raise BrokerDBError('injected ownership persistence failure')
        return super().create_ownership(rec)

    def record_lifecycle_transition(self, *args, **kwargs):
        new_state = args[4] if len(args) > 4 else kwargs.get('new_state')
        if self.fail_history or new_state == self.fail_history_on_new_state:
            raise BrokerDBError('injected lifecycle history persistence failure')
        return super().record_lifecycle_transition(*args, **kwargs)

    def store_evidence(self, ev):
        if self.fail_evidence:
            raise BrokerDBError('injected evidence persistence failure')
        return super().store_evidence(ev)

    def record_audit(self, *args, **kwargs):
        if self.fail_audit:
            raise BrokerDBError('injected audit persistence failure')
        return super().record_audit(*args, **kwargs)

    def complete_idempotency_record(self, *args, **kwargs):
        if self.fail_idem_complete:
            raise BrokerDBError('injected idempotency completion persistence failure')
        return super().complete_idempotency_record(*args, **kwargs)


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
    return _AtomicFaultStore(db_path=path or _db_path())


def _svc(store=None, backend=None):
    store = store or _store()
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        backend=backend or _CountingBackend(authorized_backend()),
        ownership_store=store,
    )


def _base_rule(**overrides):
    rule = {
        "family": "ipv4", "direction": "ingress", "protocol": "tcp",
        "source_cidr": "10.0.0.0/24", "destination_cidr": "10.0.1.0/24",
        "port_start": 80, "port_end": 80, "action": "accept",
    }
    rule.update(overrides)
    return rule


def _install_req(pid=None, key=None, rules=None, **overrides):
    rules = [_base_rule()] if rules is None else rules
    norm = validate_and_normalize_rules(rules, sorted({r["family"] for r in rules}))
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid or f"p-{uuid.uuid4()}", "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(norm), "compiled": {},
        "rules": [dict(r) for r in rules],
        "required_families": sorted({r["family"] for r in rules}),
        "peer_uid": 1000, "peer_gid": 1000, "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


def _op_req(pid, digest, key=None, **overrides):
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid, "policy_version": 1,
        "compiled_rule_digest": digest, "peer_uid": 1000, "peer_gid": 1000,
        "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


def _install_active(store, svc, pid):
    req = _install_req(pid=pid)
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    assert svc.verify_policy(_op_req(pid, digest))["status"] == "ok"
    own = store.get_by_policy(pid, 1)
    assert own and own.get("installation_state") == "ACTIVE"
    return digest, own


def _state(store, pid):
    rec = store.get_by_policy(pid, 1)
    return rec.get('installation_state') if rec else None


def _hist(store, pid):
    return store.get_lifecycle_history() and [
        h for h in store.get_lifecycle_history() if h.get('policy_id') == pid
    ] or []


def _audit_count(store):
    return len(store.db.query('SELECT * FROM controller_audit'))


def _idem(store, key, operation='install_policy'):
    return store.get_idempotency_record(key, operation)


def _evidences(store, pid, result):
    return [e for e in store.get_evidence_by_policy(pid, 1)
            if e.get('verification_result') == result]


def _with_key(req, key):
    r = dict(req)
    r['idempotency_key'] = key
    return r


# ------------------------------------------------ intent / pre-transaction ---

def test_intent_group_rolls_back_ownership_audit_and_history():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    req = _install_req(pid='b2-intent', key='b2-intent-key')
    store.fail_history_on_new_state = 'REQUESTED'
    with pytest.raises(BrokerDBError):
        svc.install_policy(req)

    assert store.get_by_policy('b2-intent', 1) is None
    assert _hist(store, 'b2-intent') == []
    assert _audit_count(store) == 0
    assert be.install_calls == 0
    # The idempotency intent was committed before the failed group and survives.
    idem = _idem(store, 'b2-intent-key')
    assert idem and idem.get('status') == 'PENDING'
    assert idem.get('operation_outcome') in ('INTENT_RECORDED', 'IN_PROGRESS')

    store.fail_history_on_new_state = None
    assert svc.install_policy(_with_key(req, 'b2-intent-key-2'))['status'] == 'ok'
    assert _state(store, 'b2-intent') == 'INSTALLING'
    assert len(_hist(store, 'b2-intent')) == 2
    assert be.install_calls == 1


def test_intent_group_rolls_back_on_ownership_failure():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    req = _install_req(pid='b2-ownership', key='b2-ownership-key')
    store.fail_ownership = True
    with pytest.raises(BrokerDBError):
        svc.install_policy(req)
    assert store.get_by_policy('b2-ownership', 1) is None
    assert _hist(store, 'b2-ownership') == []
    assert _audit_count(store) == 0
    assert be.install_calls == 0
    assert _idem(store, 'b2-ownership-key') is not None

    store.fail_ownership = False
    assert svc.install_policy(_with_key(req, 'b2-ownership-key-2'))['status'] == 'ok'
    assert _state(store, 'b2-ownership') == 'INSTALLING'
    assert len(_hist(store, 'b2-ownership')) == 2


def test_intent_group_rolls_back_on_audit_failure():
    store = _store(); svc = _svc(store)
    req = _install_req(pid='b2-audit', key='b2-audit-key')
    store.fail_audit = True
    with pytest.raises(BrokerDBError):
        svc.install_policy(req)
    assert store.get_by_policy('b2-audit', 1) is None
    assert _hist(store, 'b2-audit') == []
    assert _idem(store, 'b2-audit-key') is not None

    store.fail_audit = False
    assert svc.install_policy(_with_key(req, 'b2-audit-key-2'))['status'] == 'ok'
    assert len(_hist(store, 'b2-audit')) == 2


def test_failure_before_transaction_start_fails_closed():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    req = _install_req(pid='b2-before', key='b2-before-key')
    store.fail_before_group = True
    with pytest.raises(BrokerDBError):
        svc.install_policy(req)
    assert store.get_by_policy('b2-before', 1) is None
    assert be.install_calls == 0
    assert _idem(store, 'b2-before-key') is not None

    store.fail_before_group = False
    assert svc.install_policy(_with_key(req, 'b2-before-key-2'))['status'] == 'ok'
    assert _state(store, 'b2-before') == 'INSTALLING'


def test_commit_failure_during_intent_group_rolls_back_all_grouped_writes():
    store = _store(); svc = _svc(store)
    req = _install_req(pid='b2-commit-intent', key='b2-ci-key')
    store.fail_commit = True
    with pytest.raises(BrokerDBError):
        svc.install_policy(req)
    assert store.get_by_policy('b2-commit-intent', 1) is None
    assert _hist(store, 'b2-commit-intent') == []
    assert _audit_count(store) == 0
    # Prior committed intent (idempotency) remains available for retry.
    assert _idem(store, 'b2-ci-key') is not None

    assert svc.install_policy(_with_key(req, 'b2-ci-key-2'))['status'] == 'ok'
    assert _state(store, 'b2-commit-intent') == 'INSTALLING'


# ------------------------------------------- install/verify grouped writes ---

def test_install_success_history_failure_keeps_intent_state():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    req = _install_req(pid='b2-install', key='b2-install-key')
    store.fail_history_on_new_state = 'INSTALLING'
    with pytest.raises(BrokerDBError):
        svc.install_policy(req)
    assert _state(store, 'b2-install') == 'REQUESTED'
    assert len(_hist(store, 'b2-install')) == 1
    assert all(h['new_state'] != 'INSTALLING' for h in _hist(store, 'b2-install'))
    assert _idem(store, 'b2-install-key').get('operation_outcome') != 'SUCCEEDED'
    # Backend effect exists but the mock controller's idempotency key keeps one effect.
    assert list(be.inner.ctrl.installed) == ['b2-install']

    store.fail_history_on_new_state = None
    assert svc.install_policy(_with_key(req, 'b2-install-key-2'))['status'] == 'ok'
    assert _state(store, 'b2-install') == 'INSTALLING'
    assert len(_hist(store, 'b2-install')) == 3
    assert len([h for h in _hist(store, 'b2-install') if h['new_state'] == 'INSTALLING']) == 1
    assert list(be.inner.ctrl.installed) == ['b2-install']


def test_install_success_commit_failure_rolls_back_state_and_history():
    store = _store(); svc = _svc(store)
    req = _install_req(pid='b2-install-commit', key='b2-ic-key')
    # group 1 = intent, group 2 = install-success transition
    store.fail_commit = True
    store.fail_commit_on_group = 2
    with pytest.raises(BrokerDBError):
        svc.install_policy(req)
    assert _state(store, 'b2-install-commit') == 'REQUESTED'
    assert len(_hist(store, 'b2-install-commit')) == 1
    assert all(h['new_state'] != 'INSTALLING' for h in _hist(store, 'b2-install-commit'))

    store.fail_commit_on_group = None
    assert svc.install_policy(_with_key(req, 'b2-ic-key-2'))['status'] == 'ok'
    assert _state(store, 'b2-install-commit') == 'INSTALLING'
    assert len(_hist(store, 'b2-install-commit')) == 3
    assert len([h for h in _hist(store, 'b2-install-commit') if h['new_state'] == 'INSTALLING']) == 1


def test_verify_evidence_failure_leaves_state_unchanged():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    req = _install_req(pid='b2-evidence')
    digest = req['compiled_rule_digest']
    assert svc.install_policy(req)['status'] == 'ok'
    assert _state(store, 'b2-evidence') == 'INSTALLING'
    vreq = _op_req('b2-evidence', digest, key='b2-ev-key')

    store.fail_evidence = True
    with pytest.raises(BrokerDBError):
        svc.verify_policy(vreq)
    assert _state(store, 'b2-evidence') == 'INSTALLING'
    assert _evidences(store, 'b2-evidence', 'verified') == []
    assert all(h['new_state'] not in ('VERIFIED', 'ACTIVE') for h in _hist(store, 'b2-evidence'))

    store.fail_evidence = False
    assert svc.verify_policy(_with_key(vreq, 'b2-ev-key-2'))['status'] == 'ok'
    assert _state(store, 'b2-evidence') == 'ACTIVE'
    assert len(_evidences(store, 'b2-evidence', 'verified')) == 1


def test_verify_transition_history_failure_returns_to_uncertain_state():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active_setup_install_only(store, svc, 'b2-verify-hist')
    vreq = _op_req('b2-verify-hist', digest, key='b2-vh-key')
    store.fail_history_on_new_state = 'VERIFIED'
    with pytest.raises(BrokerDBError):
        svc.verify_policy(vreq)
    assert _state(store, 'b2-verify-hist') == 'VERIFYING'
    assert all(h['new_state'] != 'VERIFIED' for h in _hist(store, 'b2-verify-hist'))
    # Evidence is a separate boundary and remains durable.
    assert len(_evidences(store, 'b2-verify-hist', 'verified')) == 1

    store.fail_history_on_new_state = None
    assert svc.verify_policy(_with_key(vreq, 'b2-vh-key-2'))['status'] == 'ok'
    assert _state(store, 'b2-verify-hist') == 'ACTIVE'


def test_verify_active_history_failure_never_false_active():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active_setup_install_only(store, svc, 'b2-active-hist')
    vreq = _op_req('b2-active-hist', digest, key='b2-ah-key')
    store.fail_history_on_new_state = 'ACTIVE'
    with pytest.raises(BrokerDBError):
        svc.verify_policy(vreq)
    assert _state(store, 'b2-active-hist') == 'VERIFIED'
    assert len(_evidences(store, 'b2-active-hist', 'verified')) == 1
    assert all(h['new_state'] != 'ACTIVE' for h in _hist(store, 'b2-active-hist'))

    store.fail_history_on_new_state = None
    result = svc.reconcile_pending_operations(
        _op_req('b2-active-hist', digest, key='b2-ah-reconcile')
    )
    assert result['status'] == 'ok'
    assert any(r.get('action') == 'promoted_to_active' for r in result['result']['reconciled'])
    assert _state(store, 'b2-active-hist') == 'ACTIVE'


def _install_active_setup_install_only(store, svc, pid):
    req = _install_req(pid=pid)
    assert svc.install_policy(req)['status'] == 'ok'
    return req['compiled_rule_digest'], store.get_by_policy(pid, 1)


# --------------------------------------------------------- revoke grouped ---

def test_revoke_initiate_history_failure_prevents_backend_effect():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    digest, _ = _install_active(store, svc, 'b2-revoke-init')
    req = _op_req('b2-revoke-init', digest, key='b2-ri-key')

    store.fail_history_on_new_state = 'REVOKING'
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(req)
    assert _state(store, 'b2-revoke-init') == 'ACTIVE'
    assert all(h['new_state'] != 'REVOKING' for h in _hist(store, 'b2-revoke-init'))
    assert be.revoke_calls == 0
    assert 'b2-revoke-init' in be.inner.ctrl.installed

    store.fail_history_on_new_state = None
    assert svc.revoke_policy(dict(req))['status'] == 'ok'
    assert _state(store, 'b2-revoke-init') == 'REVOKED'
    assert be.revoke_calls == 1
    assert 'b2-revoke-init' not in be.inner.ctrl.installed


def test_revoke_evidence_failure_keeps_revoking_without_false_success():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    digest, _ = _install_active(store, svc, 'b2-revoke-ev')
    req = _op_req('b2-revoke-ev', digest, key='b2-rev-key')

    store.fail_evidence = True
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(req)
    assert _state(store, 'b2-revoke-ev') == 'REVOKING'
    assert _evidences(store, 'b2-revoke-ev', 'revoked') == []
    assert all(h['new_state'] != 'REVOKED' for h in _hist(store, 'b2-revoke-ev'))
    idem = _idem(store, 'b2-rev-key', 'revoke_policy')
    assert idem and idem.get('operation_outcome') != 'SUCCEEDED'

    store.fail_evidence = False
    assert svc.revoke_policy(dict(req))['status'] == 'ok'
    assert _state(store, 'b2-revoke-ev') == 'REVOKED'
    assert len(_evidences(store, 'b2-revoke-ev', 'revoked')) == 1
    assert be.revoke_calls == 1  # readback confirmed; no duplicate backend effect


def test_revoke_completion_history_failure_preserves_evidence():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    digest, _ = _install_active(store, svc, 'b2-revoke-hist')
    req = _op_req('b2-revoke-hist', digest, key='b2-rh-key')

    store.fail_history_on_new_state = 'REVOKED'
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(req)
    assert _state(store, 'b2-revoke-hist') == 'REVOKING'
    assert len(_evidences(store, 'b2-revoke-hist', 'revoked')) == 1
    assert all(h['new_state'] != 'REVOKED' for h in _hist(store, 'b2-revoke-hist'))

    store.fail_history_on_new_state = None
    assert svc.revoke_policy(dict(req))['status'] == 'ok'
    assert _state(store, 'b2-revoke-hist') == 'REVOKED'
    assert len(_evidences(store, 'b2-revoke-hist', 'revoked')) == 1
    assert be.revoke_calls == 1


def test_revoke_completion_commit_failure_preserves_prior_evidence():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    digest, _ = _install_active(store, svc, 'b2-revoke-commit')
    req = _op_req('b2-revoke-commit', digest, key='b2-rc-key')

    # group 1 = REVOKING initiation, group 2 = REVOKED completion
    store.groups_entered = 0
    store.fail_commit = True
    store.fail_commit_on_group = 2
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(req)
    assert _state(store, 'b2-revoke-commit') == 'REVOKING'
    assert len(_evidences(store, 'b2-revoke-commit', 'revoked')) == 1
    assert all(h['new_state'] != 'REVOKED' for h in _hist(store, 'b2-revoke-commit'))

    store.fail_commit_on_group = None
    assert svc.revoke_policy(dict(req))['status'] == 'ok'
    assert _state(store, 'b2-revoke-commit') == 'REVOKED'
    assert be.revoke_calls == 1


def test_idempotency_completion_failure_preserves_committed_group():
    store = _store(); be = _CountingBackend(authorized_backend()); svc = _svc(store, be)
    digest, _ = _install_active(store, svc, 'b2-idem-fail')
    req = _op_req('b2-idem-fail', digest, key='b2-if-key')

    store.fail_idem_complete = True
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(req)
    assert _state(store, 'b2-idem-fail') == 'REVOKED'
    assert len(_evidences(store, 'b2-idem-fail', 'revoked')) == 1
    assert any(h['new_state'] == 'REVOKED' for h in _hist(store, 'b2-idem-fail'))
    idem = _idem(store, 'b2-if-key', 'revoke_policy')
    assert idem and idem.get('status') != 'COMPLETED'

    store.fail_idem_complete = False
    assert svc.revoke_policy(dict(req))['status'] == 'ok'
    assert be.revoke_calls == 1
    assert _idem(store, 'b2-if-key', 'revoke_policy').get('status') == 'COMPLETED'


def test_previously_committed_intent_survives_later_group_failure():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active_setup_install_only(store, svc, 'b2-survive')
    install_idem = _idem(store, _store_last_key(store), 'install_policy')
    assert install_idem is not None
    vreq = _op_req('b2-survive', digest, key='b2-survive-v')

    store.fail_history_on_new_state = 'ACTIVE'
    with pytest.raises(BrokerDBError):
        svc.verify_policy(vreq)
    # Earlier committed intent and state remain intact and readable.
    assert store.get_by_policy('b2-survive', 1) is not None
    assert _state(store, 'b2-survive') == 'VERIFIED'
    assert any(h['new_state'] == 'REQUESTED' for h in _hist(store, 'b2-survive'))
    assert any(h['new_state'] == 'INSTALLING' for h in _hist(store, 'b2-survive'))
    assert len(_evidences(store, 'b2-survive', 'verified')) == 1


def _store_last_key(store):
    rows = store.db.query("SELECT idempotency_key FROM controller_idempotency "
                          "WHERE operation_type='install_policy' ORDER BY created_at DESC LIMIT 1")
    return rows[0][0] if rows else None


# -------------------------------------------------- integrity / concurrency ---

def test_append_only_and_foreign_keys_preserved_after_grouped_writes():
    store = _store(); svc = _svc(store)
    _install_active(store, svc, 'b2-integrity')
    rec = store.get_by_policy('b2-integrity', 1)
    oid = rec['ownership_record_id']
    conn = sqlite3.connect(store.db.db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('UPDATE controller_lifecycle_history SET result=? WHERE ownership_record_id=?',
                         ('tampered', oid))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('DELETE FROM controller_lifecycle_history WHERE ownership_record_id=?', (oid,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('UPDATE controller_audit SET event_type=? WHERE ownership_record_id=?',
                         ('tampered', oid))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('DELETE FROM controller_evidence WHERE ownership_record_id=?', (oid,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                'INSERT INTO controller_policy_bodies '
                '(policy_body_id, ownership_record_id, policy_id, policy_version, schema_version, '
                'canonical_rules_json, compiled_rule_digest) VALUES (?,?,?,?,?,?,?)',
                ('bad', 'missing-owner', 'b2-integrity', 1, 'v1', '[]', 'x' * 64),
            )
    finally:
        conn.close()
    assert store.db.query('PRAGMA foreign_keys')


def test_nested_atomic_write_joins_outer_transaction():
    store = _store()
    oid = str(uuid.uuid4())
    rec = {
        'ownership_record_id': oid, 'policy_id': 'b2-nested', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a' * 64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'REQUESTED',
    }
    with pytest.raises(BrokerDBError):
        with store.atomic_write():
            store.create_ownership(rec)
            with store.atomic_write():
                store.record_lifecycle_transition(
                    oid, 'b2-nested', 1, None, 'REQUESTED', 'o', 'r',
                    'nested', 'ok',
                )
            raise BrokerDBError('injected outer failure')
    assert store.get_by_policy('b2-nested', 1) is None
    assert store.get_lifecycle_history(oid) == []
    assert store.groups_entered == 2

    with store.atomic_write():
        store.create_ownership(rec)
        with store.atomic_write():
            store.record_lifecycle_transition(
                oid, 'b2-nested', 1, None, 'REQUESTED', 'o', 'r', 'nested', 'ok',
            )
    assert store.get_by_policy('b2-nested', 1) is not None
    assert len(store.get_lifecycle_history(oid)) == 1


def test_cas_conflict_rolls_back_grouped_history():
    store = _store()
    oid = str(uuid.uuid4())
    rec = {
        'ownership_record_id': oid, 'policy_id': 'b2-cas', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a' * 64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'REQUESTED',
    }
    store.create_ownership(rec)
    barrier = threading.Barrier(2)
    outcomes = []

    def worker():
        barrier.wait(timeout=5)
        try:
            with store.atomic_write():
                store.update_ownership_state(oid, 'INSTALLING', 'REQUESTED', 0)
                store.record_lifecycle_transition(
                    oid, 'b2-cas', 1, 'REQUESTED', 'INSTALLING', 'o', 'r', 'cas', 'ok',
                )
            outcomes.append('ok')
        except PermissionError:
            outcomes.append('conflict')

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=15)
        assert not th.is_alive()

    assert sorted(outcomes) == ['conflict', 'ok']
    assert _state(store, 'b2-cas') == 'INSTALLING'
    hist = store.get_lifecycle_history(oid)
    assert len(hist) == 1 and hist[0]['new_state'] == 'INSTALLING'
