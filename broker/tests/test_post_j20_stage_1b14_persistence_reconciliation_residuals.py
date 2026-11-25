"""Post-J.20 Stage 1B.14 — persistence classification and reconciliation residuals.

Deterministic mock-only tests for the confirmed Stage 1B.12 residuals that remain
after Stage 1B.13: canonical read classification, guarded reconciliation fallbacks,
failed-branch guard capture, status/audit atomicity and VERIFYING journaling.

No Docker/host/UDS/privileged/firewall/live-backend operations are performed.
"""
from __future__ import annotations

import uuid

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import (
    FirewallControllerBackendError,
    FirewallControllerPersistenceError,
    FirewallControllerRequestError,
)
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend
from broker.tests.test_post_j20_stage_1b3_durable_crash_recovery import (
    _CountingBackend,
    _install_active,
    _installed,
    _op_req,
)

SENTINEL_READ_1B14 = "SENTINEL_1B14_RAW_READ_ERROR"
SENTINEL_PERSIST_1B14 = "SENTINEL_1B14_RAW_PERSIST_ERROR"
SENTINEL_AUDIT_1B14 = "SENTINEL_1B14_RAW_AUDIT_ERROR"
SENTINEL_HISTORY_1B14 = "SENTINEL_1B14_RAW_HISTORY_ERROR"


def _svc(store, backend=None):
    return FirewallControllerService(
        allowed_uids={1000},
        allowed_gids={1000},
        ownership_store=store,
        backend=backend or _CountingBackend(authorized_backend()),
    )


def _assert_bounded(exc, *sentinels):
    text = f"{type(exc).__name__}: {exc}"
    for sentinel in sentinels:
        assert sentinel not in text, f"raw internal detail leaked: {sentinel}"
    assert len(str(exc)) <= 200


def _set_reconciliation_marker(store, pid, marker):
    conn = store._get_conn_fk()
    try:
        conn.execute(
            "UPDATE controller_ownership SET reconciliation_status=? WHERE policy_id=? AND policy_version=?",
            (marker, pid, 1),
        )
        conn.commit()
    finally:
        conn.close()


def _audit_events(store, event_type, oid):
    return store._query_dicts(
        "SELECT * FROM controller_audit WHERE event_type=? AND ownership_record_id=?",
        (event_type, oid),
    )


class _UnknownCanonicalReadStore(ControllerOwnershipStore):
    def __init__(self, *args, exc_factory=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.exc_factory = exc_factory
        self.fail_next = False

    def get_canonical_policy_body(self, *args, **kwargs):
        if self.fail_next:
            self.fail_next = False
            raise self.exc_factory()
        return super().get_canonical_policy_body(*args, **kwargs)


class _NestedReconcileReadFailureStore(ControllerOwnershipStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_nested = False

    def read_trusted_canonical_policy_body(self, *args, **kwargs):
        if self.fail_nested:
            self.fail_nested = False
            raise BrokerDBError(SENTINEL_READ_1B14)
        return super().read_trusted_canonical_policy_body(*args, **kwargs)


class _NoGuardStoreProxy:
    """Legacy/test store shape with no reconciliation guard context manager."""

    def __init__(self, inner):
        object.__setattr__(self, "inner", inner)

    def __getattr__(self, name):
        if name == "reconciliation_version_guard":
            raise AttributeError(name)
        return getattr(self.inner, name)


class _VersionBumpingStatusStore(ControllerOwnershipStore):
    """Advance lifecycle version after the guard read to force a CAS miss."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bump_next_status_write = False

    def update_reconciliation_status(self, ownership_record_id, status):
        if self.bump_next_status_write:
            self.bump_next_status_write = False
            conn = self._get_conn_fk()
            try:
                conn.execute(
                    "UPDATE controller_ownership SET lifecycle_version=lifecycle_version+1 WHERE ownership_record_id=?",
                    (ownership_record_id,),
                )
                conn.commit()
            finally:
                conn.close()
        return super().update_reconciliation_status(ownership_record_id, status)


class _AuditFailureStore(ControllerOwnershipStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_reconcile_audit = False

    def record_audit(self, event_type, req=None, details=None, ownership_record_id=None):
        if self.fail_reconcile_audit and str(event_type).startswith("reconcile_status_"):
            self.fail_reconcile_audit = False
            raise BrokerDBError(SENTINEL_AUDIT_1B14)
        return super().record_audit(event_type, req, details, ownership_record_id)


class _VerifyingHistoryFailureStore(ControllerOwnershipStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_verifying_history = False

    def record_lifecycle_transition(self, *args, **kwargs):
        if self.fail_verifying_history and len(args) > 4 and args[4] == "VERIFYING":
            self.fail_verifying_history = False
            raise BrokerDBError(SENTINEL_HISTORY_1B14)
        return super().record_lifecycle_transition(*args, **kwargs)


class _BackendStateBackend:
    def __init__(self, inner, state):
        self.inner = inner
        self.state = state

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def inspect_policy(self, req):
        return {"status": "ok", "result": {"status": self.state}}


def test_unknown_canonical_read_failure_is_backend_error_and_bounded(tmp_path):
    store = _UnknownCanonicalReadStore(
        db_path=str(tmp_path / "unknown-read.db"),
        exc_factory=lambda: OSError(SENTINEL_READ_1B14),
    )
    svc = _svc(store)
    digest = _installed(store, svc, "b14-unknown-read")
    rec = store.get_by_policy("b14-unknown-read", 1)
    store.fail_next = True

    # Direct canonical-boundary classification: unknown internal faults must not
    # be reported as caller validation failures.
    with pytest.raises(FirewallControllerBackendError) as exc:
        svc._read_trusted_canonical_policy_body(
            _op_req("b14-unknown-read", digest), rec, operation="verify_policy"
        )
    _assert_bounded(exc.value, SENTINEL_READ_1B14)

    # Public boundary remains bounded and fail-closed.
    store.fail_next = True
    with pytest.raises(FirewallControllerBackendError) as public_exc:
        svc.verify_policy(_op_req("b14-unknown-read", digest))
    _assert_bounded(public_exc.value, SENTINEL_READ_1B14)
    assert store.get_by_policy("b14-unknown-read", 1)["installation_state"] == "INSTALLING"


def test_persistence_category_read_failure_stays_persistence_error_and_bounded(tmp_path):
    store = _UnknownCanonicalReadStore(
        db_path=str(tmp_path / "persist-read.db"),
        exc_factory=lambda: FirewallControllerPersistenceError(SENTINEL_PERSIST_1B14),
    )
    svc = _svc(store)
    digest = _installed(store, svc, "b14-persist-read")
    rec = store.get_by_policy("b14-persist-read", 1)
    store.fail_next = True

    # A persistence-category exception is still a persistence failure even when
    # it arrives from a nested read rather than the outer DB wrapper.
    with pytest.raises(FirewallControllerPersistenceError) as exc:
        svc._read_trusted_canonical_policy_body(
            _op_req("b14-persist-read", digest), rec, operation="verify_policy"
        )
    _assert_bounded(exc.value, SENTINEL_PERSIST_1B14)

    store.fail_next = True
    with pytest.raises(FirewallControllerPersistenceError) as public_exc:
        svc.verify_policy(_op_req("b14-persist-read", digest))
    _assert_bounded(public_exc.value, SENTINEL_PERSIST_1B14)
    assert store.get_by_policy("b14-persist-read", 1)["installation_state"] == "INSTALLING"


def test_nested_reconciliation_read_storage_failure_is_persistence_not_invalid(tmp_path):
    store = _NestedReconcileReadFailureStore(db_path=str(tmp_path / "nested-read.db"))
    svc = _svc(store)
    digest = _install_active(store, svc, "b14-nested-read")
    store.fail_nested = True

    result = svc.reconcile_pending_operations(_op_req("b14-nested-read", digest))
    payload = result.get("result") or {}

    assert any(e.get("error_code") == "PERSISTENCE_FAILURE" for e in payload.get("errors") or [])
    assert not any(
        u.get("reason") == "invalid_canonical_policy_body"
        for u in payload.get("uncertain") or []
    )
    assert not any(a.get("policy_id") == "b14-nested-read" for a in payload.get("adopted") or [])
    assert SENTINEL_READ_1B14 not in repr(payload)
    assert store.get_by_policy("b14-nested-read", 1)["installation_state"] == "ACTIVE"


def test_missing_guard_context_fails_closed_without_status_write(tmp_path):
    inner = ControllerOwnershipStore(db_path=str(tmp_path / "no-guard.db"))
    store = _NoGuardStoreProxy(inner)
    svc = _svc(store)
    digest = _install_active(store, svc, "b14-no-guard")
    rec = inner.get_by_policy("b14-no-guard", 1)
    oid = rec["ownership_record_id"]
    marker = "b14-marker-no-guard"
    _set_reconciliation_marker(inner, "b14-no-guard", marker)

    written = svc._set_reconciliation_status(
        store.get_by_policy("b14-no-guard", 1),
        oid,
        "failed",
        allowed_states=("ACTIVE",),
        inspect_req=_op_req("b14-no-guard", digest),
    )

    assert written is False
    assert inner.get_by_policy("b14-no-guard", 1)["reconciliation_status"] == marker
    assert _audit_events(inner, "reconcile_status_failed", oid) == []


def test_missing_allowed_states_fails_closed_without_status_write(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "no-states.db"))
    svc = _svc(store)
    digest = _install_active(store, svc, "b14-no-states")
    rec = store.get_by_policy("b14-no-states", 1)
    oid = rec["ownership_record_id"]
    marker = "b14-marker-no-states"
    _set_reconciliation_marker(store, "b14-no-states", marker)

    written = svc._set_reconciliation_status(
        rec, oid, "failed", inspect_req=_op_req("b14-no-states", digest)
    )

    assert written is False
    assert store.get_by_policy("b14-no-states", 1)["reconciliation_status"] == marker
    assert _audit_events(store, "reconcile_status_failed", oid) == []


def test_needs_verification_status_conflict_is_uncertain_not_success(tmp_path):
    store = _VersionBumpingStatusStore(db_path=str(tmp_path / "needs-verification.db"))
    svc = _svc(store)
    digest = _installed(store, svc, "b14-needs-verification")
    store.bump_next_status_write = True

    result = svc.reconcile_pending_operations(_op_req("b14-needs-verification", digest))
    payload = result.get("result") or {}

    assert not any(
        r.get("action") == "marked_needs_verification"
        for r in payload.get("reconciled") or []
    )
    assert any(
        u.get("reason") == "reconciliation_state_changed"
        for u in payload.get("uncertain") or []
    )
    assert store.get_by_policy("b14-needs-verification", 1)["installation_state"] == "INSTALLING"


def test_failed_status_conflict_is_uncertain_not_success(tmp_path):
    store = _VersionBumpingStatusStore(db_path=str(tmp_path / "failed-status.db"))
    backend = _BackendStateBackend(authorized_backend(), "missing")
    svc = _svc(store, backend=backend)
    digest = _installed(store, svc, "b14-failed-status")
    store.bump_next_status_write = True

    result = svc.reconcile_pending_operations(_op_req("b14-failed-status", digest))
    payload = result.get("result") or {}

    assert not any(
        r.get("action") == "marked_failed_backend_missing"
        for r in payload.get("reconciled") or []
    )
    assert any(
        u.get("reason") == "reconciliation_state_changed"
        for u in payload.get("uncertain") or []
    )
    assert store.get_by_policy("b14-failed-status", 1)["installation_state"] == "FAILED"


def test_status_and_audit_are_atomic_when_audit_fails(tmp_path):
    store = _AuditFailureStore(db_path=str(tmp_path / "status-audit.db"))
    svc = _svc(store)
    digest = _install_active(store, svc, "b14-status-audit")
    rec = store.get_by_policy("b14-status-audit", 1)
    oid = rec["ownership_record_id"]
    marker = "b14-marker-audit-atomic"
    _set_reconciliation_marker(store, "b14-status-audit", marker)
    store.fail_reconcile_audit = True

    result = svc.reconcile_pending_operations(_op_req("b14-status-audit", digest))
    payload = result.get("result") or {}

    assert store.get_by_policy("b14-status-audit", 1)["reconciliation_status"] == marker
    assert any(e.get("error_code") == "PERSISTENCE_FAILURE" for e in payload.get("errors") or [])
    assert SENTINEL_AUDIT_1B14 not in repr(payload)
    assert _audit_events(store, "reconcile_status_ok", oid) == []


def test_verifying_transition_is_journaled_with_state_history(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "verifying-journal.db"))
    svc = _svc(store)
    digest = _installed(store, svc, "b14-verifying-journal")
    oid = store.get_by_policy("b14-verifying-journal", 1)["ownership_record_id"]

    assert svc.verify_policy(_op_req("b14-verifying-journal", digest))["status"] == "ok"

    history = store.get_lifecycle_history(oid)
    verifying_rows = [
        h for h in history
        if h.get("prev_state") == "INSTALLING" and h.get("new_state") == "VERIFYING"
    ]
    assert len(verifying_rows) == 1
    assert store.get_by_policy("b14-verifying-journal", 1)["installation_state"] == "ACTIVE"


def test_verifying_history_failure_does_not_produce_active_state(tmp_path):
    store = _VerifyingHistoryFailureStore(db_path=str(tmp_path / "verifying-fault.db"))
    svc = _svc(store)
    digest = _installed(store, svc, "b14-verifying-fault")
    store.fail_verifying_history = True

    with pytest.raises(BrokerDBError):
        svc.verify_policy(_op_req("b14-verifying-fault", digest))

    rec = store.get_by_policy("b14-verifying-fault", 1)
    assert rec["installation_state"] == "INSTALLING"
    assert SENTINEL_HISTORY_1B14 not in repr(rec)


def test_repeated_reconcile_preserves_status_and_audit_idempotence(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "repeat-reconcile.db"))
    svc = _svc(store)
    digest = _install_active(store, svc, "b14-repeat")
    oid = store.get_by_policy("b14-repeat", 1)["ownership_record_id"]

    for _ in range(3):
        result = svc.reconcile_pending_operations(_op_req("b14-repeat", digest))
        assert result["status"] == "ok"
        assert (result.get("result") or {}).get("errors") == []

    assert store.get_by_policy("b14-repeat", 1)["installation_state"] == "ACTIVE"
    # Each reconcile call carries a distinct operation_id, so one audit record per
    # call is expected; idempotency means no lifecycle transition or state drift.
    assert len(_audit_events(store, "reconcile_status_ok", oid)) == 3
    assert store.get_by_policy("b14-repeat", 1)["reconciliation_status"] == "ok"
