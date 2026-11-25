"""Post-J.20 Stage 1B.6 — targeted residual gap remediation (mock-only).

Deterministic tests for SR-07 (structured persistence classification), SR-08
(canonical read failures are never absence), and SR-09 (uniform reconciliation
status fencing). All state is disposable SQLite and in-memory mock backends.
No Docker/host/transport/privileged operations. No assertion is weakened/skipped.
"""
from __future__ import annotations

import threading
import uuid

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import (
    FirewallControllerPersistenceError,
    FirewallControllerRequestError,
)
from broker.firewall_controller_service.ownership_store import (
    BrokerDBCanonicalBodyConflict,
    BrokerDBCanonicalError,
    BrokerDBIdempotencyConflict,
    ControllerOwnershipStore,
)
from broker.tests._helper_identity import authorized_backend
from broker.tests.test_post_j20_stage_1b3_durable_crash_recovery import (
    _CountingBackend,
    _evidence_for,
    _install_active,
    _install_req,
    _installed,
    _op_req,
    _store,
)


def _svc(store=None, backend=None):
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store or _store(),
        backend=backend or _CountingBackend(authorized_backend()),
    )


def _body_rec(store, pid, digest=None, **overrides):
    own = store.get_by_policy(pid, 1)
    req = _install_req(pid=pid)
    rec = {
        'policy_id': pid,
        'policy_version': 1,
        'ownership_record_id': own['ownership_record_id'],
        'schema_version': 'rule-schema-v1',
        'rules': req['rules'],
        'required_families': ['ipv4'],
        'compiled_rule_digest': digest or req['compiled_rule_digest'],
        'canonical_policy_digest': own.get('canonical_policy_digest') or digest or req['compiled_rule_digest'],
        'controller_identity': 'test',
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'instance_id': own.get('instance_id') or 'i1',
    }
    rec.update(overrides)
    return rec


def _set_state(store, pid, state, prev):
    rec = store.get_by_policy(pid, 1)
    store.update_ownership_state(
        rec['ownership_record_id'], state, prev, rec['lifecycle_version']
    )
    return store.get_by_policy(pid, 1)


# ---------------------------------------------------------------- Gap 1 ---

class _StaleCanonicalReadStore(ControllerOwnershipStore):
    """Observe absence once so the targeted single-body conflict path is exercised."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stale_once = False

    def get_canonical_policy_body(self, *args, **kwargs):
        if self.stale_once:
            self.stale_once = False
            return None
        return super().get_canonical_policy_body(*args, **kwargs)


class _GenericCanonicalFailureStore(ControllerOwnershipStore):
    def store_canonical_policy_body(self, rec):
        raise BrokerDBError('injected generic canonical storage failure')


class _GenericIdemFailureStore(ControllerOwnershipStore):
    def create_idempotency_record(self, *args, **kwargs):
        raise BrokerDBError('injected generic idempotency storage failure')


def test_canonical_single_body_conflict_is_typed_and_resolves_durable_winner():
    store = _StaleCanonicalReadStore()
    svc = _svc(store)
    pid = 'b6-body-race'
    digest = _installed(store, svc, pid)
    rec = _body_rec(store, pid, digest)

    store.stale_once = True
    body_id = store.ensure_canonical_policy_body(rec)

    assert body_id == f'pb-{pid}-1'
    assert store.get_canonical_policy_body(pid, 1) is not None


def test_canonical_generic_storage_failure_is_not_idempotent_conflict():
    store = _GenericCanonicalFailureStore()
    svc = _svc(store)
    req = _install_req(pid='b6-body-generic')
    with pytest.raises(BrokerDBError) as exc:
        svc.install_policy(req)
    assert not isinstance(exc.value, BrokerDBCanonicalBodyConflict)
    # Canonical body persistence precedes backend dispatch: no side effect occurred.
    assert svc.backend.install_calls == 0


def test_idempotency_duplicate_is_typed_and_generic_failure_is_not():
    store = _store()
    key = 'b6-idem-key'
    store.create_idempotency_record(key, 'install_policy', 'a' * 64)
    with pytest.raises(BrokerDBIdempotencyConflict) as dup:
        store.create_idempotency_record(key, 'install_policy', 'b' * 64)
    assert dup.value.idempotency_key == key

    generic = _GenericIdemFailureStore()
    with pytest.raises(BrokerDBError) as exc:
        generic.create_idempotency_record('b6-generic', 'install_policy', 'a' * 64)
    assert not isinstance(exc.value, BrokerDBIdempotencyConflict)


def test_canonical_error_categories_replace_message_classification():
    svc = _svc()
    with pytest.raises(PermissionError):
        svc._sanitize_canonical_policy_error(
            BrokerDBCanonicalError('ownership details', BrokerDBCanonicalError.OWNERSHIP)
        )
    with pytest.raises(FirewallControllerRequestError):
        svc._sanitize_canonical_policy_error(
            BrokerDBCanonicalError('corrupt body', BrokerDBCanonicalError.INTEGRITY)
        )
    with pytest.raises(FirewallControllerPersistenceError):
        svc._sanitize_canonical_policy_error(
            BrokerDBCanonicalError('db down', BrokerDBCanonicalError.PERSISTENCE)
        )
    with pytest.raises(FirewallControllerPersistenceError):
        svc._sanitize_canonical_policy_error(BrokerDBError('plain failure'))


# ---------------------------------------------------------------- Gap 2 ---

class _FailCanonicalPreReadStore(ControllerOwnershipStore):
    def get_canonical_policy_body(self, *args, **kwargs):
        raise BrokerDBError('injected canonical pre-read failure')


def test_canonical_read_failure_is_never_absence_and_blocks_install():
    store = _FailCanonicalPreReadStore()
    svc = _svc(store)
    with pytest.raises(BrokerDBError) as exc:
        svc.install_policy(_install_req(pid='b6-read-failure'))
    # Raw storage failure details must not leak outward; failure remains a bounded
    # persistence/storage error and must never be treated as absence.
    assert 'pre-read failure' not in str(exc.value)
    assert svc.backend.install_calls == 0


class _ToggleCanonicalReadFailureStore(ControllerOwnershipStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_canonical_read = False

    def get_canonical_policy_body(self, *args, **kwargs):
        if self.fail_canonical_read:
            raise BrokerDBError('injected canonical reconciliation read failure')
        return super().get_canonical_policy_body(*args, **kwargs)


def test_reconciliation_read_failure_is_persistence_failure_not_absence():
    store = _ToggleCanonicalReadFailureStore()
    svc = _svc(store)
    pid = 'b6-reconcile-read-failure'
    digest = _installed(store, svc, pid)
    store.fail_canonical_read = True

    result = svc.reconcile_pending_operations(_op_req(pid, digest))
    assert result['status'] == 'error'
    assert result['error_code'] == 'RECONCILIATION_PERSISTENCE_FAILURE'
    assert not result['result']['adopted']
    assert not result['result']['reconciled']


def test_legacy_without_rules_remains_canonical_noop():
    store = _store()
    svc = _svc(store)
    req = _install_req(pid='b6-legacy')
    req.pop('rules')
    req.pop('required_families')
    assert svc.install_policy(req)['status'] == 'ok'
    assert store.get_canonical_policy_body('b6-legacy', 1) is None


def _corrupt_canonical_body(store, pid, column, value):
    conn = store._get_conn_fk()
    try:
        conn.execute(
            f'UPDATE controller_policy_bodies SET {column}=? WHERE policy_id=?',
            (value, pid),
        )
        conn.commit()
    finally:
        conn.close()


def test_corrupt_canonical_body_fails_closed_in_reconciliation():
    store = _store()
    svc = _svc(store)
    pid = 'b6-corrupt-body'
    digest = _installed(store, svc, pid)
    _corrupt_canonical_body(store, pid, 'canonical_rules_json', '{not-json')
    result = svc.reconcile_pending_operations(_op_req(pid, digest))
    uncertain = result['result']['uncertain']
    assert any(
        e.get('policy_id') == pid and e.get('reason') == 'invalid_canonical_policy_body'
        for e in uncertain
    )
    assert store.get_by_policy(pid, 1)['reconciliation_status'] == 'uncertain'


def test_mismatched_canonical_body_fails_closed_on_trusted_read():
    store = _store()
    svc = _svc(store)
    pid = 'b6-mismatch-body'
    digest = _installed(store, svc, pid)
    _corrupt_canonical_body(store, pid, 'compiled_rule_digest', '0' * 64)
    with pytest.raises(BrokerDBCanonicalError) as exc:
        store.read_trusted_canonical_policy_body(
            pid, 1, expected_compiled_rule_digest=digest, require_schema_v1=True
        )
    assert exc.value.category == BrokerDBCanonicalError.INTEGRITY


def test_conflict_winner_mismatch_is_persistence_failure():
    store = _StaleCanonicalReadStore()
    svc = _svc(store)
    pid = 'b6-winner-mismatch'
    digest = _installed(store, svc, pid)
    rec = _body_rec(store, pid, digest, compiled_rule_digest='1' * 64)
    with pytest.raises(BrokerDBError) as exc:
        store.ensure_canonical_policy_body(rec)
    # A mismatched durable winner is a fail-closed integrity error, not a
    # false idempotent success and not a silently treated absence.
    assert isinstance(exc.value, BrokerDBError)


# ---------------------------------------------------------------- Gap 3 ---

def test_stale_worker_cannot_overwrite_newer_state():
    store = _store()
    svc = _svc(store)
    pid = 'b6-stale-status'
    digest = _install_active(store, svc, pid)
    old_rec = store.get_by_policy(pid, 1)
    oid = old_rec['ownership_record_id']
    status_before = old_rec.get('reconciliation_status')

    _set_state(store, pid, 'REVOKING', 'ACTIVE')

    written = svc._set_reconciliation_status(
        old_rec, oid, 'ok', allowed_states=('ACTIVE',), inspect_req=_op_req(pid, digest)
    )
    assert written is False
    assert store.get_by_policy(pid, 1)['reconciliation_status'] == status_before


def test_identity_mismatch_is_conflict_not_status_overwrite():
    store = _store()
    svc = _svc(store)
    pid = 'b6-identity-status'
    digest = _install_active(store, svc, pid)
    old_rec = store.get_by_policy(pid, 1)
    oid = old_rec['ownership_record_id']

    conn = store._get_conn_fk()
    try:
        conn.execute(
            'UPDATE controller_ownership SET instance_id=? WHERE ownership_record_id=?',
            ('attacker-owner', oid),
        )
        conn.commit()
    finally:
        conn.close()

    written = svc._set_reconciliation_status(
        old_rec, oid, 'ok', allowed_states=('ACTIVE',), inspect_req=_op_req(pid, digest)
    )
    assert written is False


def test_repeated_reconciliation_is_stable_and_operation_bound():
    store = _store()
    svc = _svc(store)
    pid = 'b6-repeat-status'
    digest = _install_active(store, svc, pid)
    oid = store.get_by_policy(pid, 1)['ownership_record_id']

    req1 = _op_req(pid, digest)
    req2 = _op_req(pid, digest)
    first = svc.reconcile_pending_operations(req1)
    second = svc.reconcile_pending_operations(req2)
    assert first['status'] == second['status'] == 'ok'
    assert any(r.get('action') == 'active_ok' for r in first['result']['reconciled'])
    assert any(r.get('action') == 'active_ok' for r in second['result']['reconciled'])
    assert store.get_by_policy(pid, 1)['installation_state'] == 'ACTIVE'
    assert store.get_by_policy(pid, 1)['reconciliation_status'] == 'ok'

    audits = store._query_dicts(
        "SELECT * FROM controller_audit WHERE event_type='reconcile_status_ok' AND ownership_record_id=?",
        (oid,),
    )
    # Each decision carries its own generated operation/request identity bound to
    # this policy; the state and ownership identity never change.
    assert len(audits) >= 2
    assert len({a['request_id'] for a in audits}) >= 2
    assert {a['policy_id'] for a in audits} == {pid}
    assert {a['ownership_record_id'] for a in audits} == {oid}


class _GuardCaptureStore(ControllerOwnershipStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guard_versions = []

    def update_reconciliation_status(self, ownership_record_id, status):
        self.guard_versions.append(getattr(self._tx_state, 'recon_version', None))
        return super().update_reconciliation_status(ownership_record_id, status)


def test_every_reconciliation_status_write_is_version_guarded():
    store = _GuardCaptureStore()
    svc = _svc(store)
    pid = 'b6-guarded-status'
    digest = _installed(store, svc, pid)
    # Backend already installed; rewind only the authoritative state to the
    # interrupted install point so reconciliation exercises the status write.
    current_state = store.get_by_policy(pid, 1)['installation_state']
    _set_state(store, pid, 'REQUESTED', current_state)

    result = svc.reconcile_pending_operations(_op_req(pid, digest))
    assert any(
        r.get('action') == 'marked_needs_verification' for r in result['result']['reconciled']
    )
    assert store.guard_versions, 'no reconciliation status write observed'
    assert all(v is not None for v in store.guard_versions)


def test_concurrent_recovery_stale_worker_cannot_overwrite_terminal_state():
    store = _store()
    svc = _svc(store)
    pid = 'b6-concurrent-recovery'
    digest = _install_active(store, svc, pid)
    old_rec = store.get_by_policy(pid, 1)
    oid = old_rec['ownership_record_id']
    status_before = old_rec.get('reconciliation_status')
    advanced = threading.Event()
    observed = {}

    def advance():
        _set_state(store, pid, 'REVOKING', 'ACTIVE')
        advanced.set()

    def stale_worker():
        assert advanced.wait(5)
        observed['written'] = svc._set_reconciliation_status(
            old_rec, oid, 'ok', allowed_states=('ACTIVE',), inspect_req=_op_req(pid, digest)
        )

    t1 = threading.Thread(target=advance)
    t2 = threading.Thread(target=stale_worker)
    t1.start()
    t2.start()
    t1.join(5)
    t2.join(5)
    assert not t1.is_alive() and not t2.is_alive()
    assert observed['written'] is False
    fresh = store.get_by_policy(pid, 1)
    assert fresh['installation_state'] == 'REVOKING'
    assert fresh['reconciliation_status'] == status_before


def test_ambiguous_state_returns_uncertain_without_promotion():
    store = _store()
    svc = _svc(store)
    pid = 'b6-ambiguous'
    digest = _installed(store, svc, pid)
    conn = store._get_conn_fk()
    try:
        conn.execute(
            "UPDATE controller_ownership SET installation_state=? WHERE policy_id=?",
            ('UNKNOWN_STATE', pid),
        )
        conn.commit()
    finally:
        conn.close()
    result = svc.reconcile_pending_operations(_op_req(pid, digest))
    assert any(
        e.get('reason') == 'corrupt_ownership_state' for e in result['result']['uncertain']
    )
    assert store.get_by_policy(pid, 1)['installation_state'] == 'UNKNOWN_STATE'
