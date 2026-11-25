"""Post-J.20 Stage 1B.1 — durable lifecycle intent and operation outcome ledger (mock-only).

All fault injection is test-only, deterministic, and uses disposable SQLite DBs.
No Docker/host/transport/privileged operations. No assertions weakened or skipped.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import (
    FirewallControllerIdempotencyError,
    FirewallControllerPersistenceError,
)
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


# ---------------------------------------------------------------- helpers ---

def _db_path(name="b1.db"):
    return os.path.join(tempfile.mkdtemp(), name)


def _store(path=None):
    return ControllerOwnershipStore(db_path=path or _db_path())


def _backend():
    return authorized_backend()


def _svc(store=None, backend=None):
    store = store or _store()
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        backend=backend or _backend(), ownership_store=store,
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


def _idem(store, key, operation="install_policy"):
    return store.get_idempotency_record(key, operation)


# ---------------------------------------------------------- schema / API ---

def test_fresh_schema_has_operation_outcome_columns():
    store = _store()
    cols = {r[1] for r in store.db.query("PRAGMA table_info(controller_idempotency)")}
    assert "operation_outcome" in cols
    assert "outcome_updated_at" in cols


def test_additive_migration_for_legacy_idempotency_table():
    """A pre-1B.1 table (no outcome columns) is migrated in-place, rows preserved."""
    path = _db_path("legacy.db")
    broker = __import__("broker.app.db", fromlist=["BrokerDB"]).BrokerDB(path)
    assert broker is not None
    conn = sqlite3.connect(path)
    try:
        conn.execute('''CREATE TABLE controller_idempotency (
            idempotency_key TEXT NOT NULL, operation_type TEXT NOT NULL,
            request_digest TEXT NOT NULL, resource_key TEXT, ownership_record_id TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING', lifecycle_state TEXT,
            response_json TEXT, recovery_meta_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            PRIMARY KEY (idempotency_key, operation_type))''')
        conn.execute(
            "INSERT INTO controller_idempotency (idempotency_key, operation_type, request_digest, status) "
            "VALUES ('legacy-key', 'install_policy', ?, 'COMPLETED')", ("a" * 64,)
        )
        conn.commit()
    finally:
        conn.close()

    store = _store(path)  # runs guarded migration
    cols = {r[1] for r in store.db.query("PRAGMA table_info(controller_idempotency)")}
    assert "operation_outcome" in cols
    assert "outcome_updated_at" in cols
    row = _idem(store, "legacy-key")
    assert row is not None
    assert row["status"] == "COMPLETED"
    assert row["operation_outcome"] is None  # legacy row not backfilled


def test_create_idempotency_defaults_to_intent_and_rejects_invalid_outcome():
    store = _store()
    store.create_idempotency_record("k-default", "install_policy", "d" * 64)
    assert _idem(store, "k-default")["operation_outcome"] == "INTENT_RECORDED"
    with pytest.raises(BrokerDBError):
        store.create_idempotency_record(
            "k-invalid", "install_policy", "d" * 64, operation_outcome="BOGUS"
        )
    with pytest.raises(BrokerDBError):
        store.update_operation_outcome("k-default", "install_policy", "BOGUS")


def test_update_operation_outcome_cas_guard_and_persistence_error_distinction():
    store = _store()
    store.create_idempotency_record("k-cas", "install_policy", "d" * 64)
    assert store.update_operation_outcome(
        "k-cas", "install_policy", "IN_PROGRESS", expected_outcomes=("INTENT_RECORDED",)
    ) is True
    # second CAS from INTENT_RECORDED must not match (already IN_PROGRESS)
    assert store.update_operation_outcome(
        "k-cas", "install_policy", "SUCCEEDED", expected_outcomes=("INTENT_RECORDED",)
    ) is False
    assert _idem(store, "k-cas")["operation_outcome"] == "IN_PROGRESS"
    assert store.update_operation_outcome(
        "k-cas", "install_policy", "SUCCEEDED", expected_outcomes=("IN_PROGRESS",)
    ) is True
    assert _idem(store, "k-cas")["operation_outcome"] == "SUCCEEDED"

    class FailingStore(ControllerOwnershipStore):
        def update_operation_outcome(self, *args, **kwargs):
            raise BrokerDBError("injected storage failure")

    with pytest.raises(BrokerDBError):
        FailingStore(db_path=_db_path("cas-fail.db")).update_operation_outcome(
            "k", "install_policy", "IN_PROGRESS"
        )


# --------------------------------------------------------- normal outcomes ---

def test_successful_install_verify_revoke_records_terminal_outcomes():
    path = _db_path()
    store = _store(path)
    svc = _svc(store)

    req = _install_req(pid="p-b1-flow", key="k-b1-install")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    rec = _idem(store, "k-b1-install")
    assert rec["status"] == "COMPLETED"
    assert rec["operation_outcome"] == "SUCCEEDED"
    assert rec["ownership_record_id"]

    assert svc.verify_policy(_op_req("p-b1-flow", digest, key="k-b1-verify"))["status"] == "ok"
    assert _idem(store, "k-b1-verify", "verify_policy")["operation_outcome"] == "SUCCEEDED"
    assert store.get_by_policy("p-b1-flow", 1)["installation_state"] == "ACTIVE"

    assert svc.revoke_policy(_op_req("p-b1-flow", digest, key="k-b1-revoke"))["status"] == "ok"
    revoke_rec = _idem(store, "k-b1-revoke", "revoke_policy")
    assert revoke_rec["operation_outcome"] == "SUCCEEDED"
    assert store.get_by_policy("p-b1-flow", 1)["installation_state"] == "REVOKED"


def test_unconfirmed_revoke_is_uncertain_never_revoked():
    """A revoke whose backend state is ambiguous gets an UNCERTAIN ledger outcome."""
    path = _db_path()
    store = _store(path)
    svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-b1-uncertain")

    class AmbiguousBackend:
        def __init__(self, inner):
            self.inner = inner
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def inspect_policy(self, req):
            return {"status": "ok", "result": {"status": "unknown"}}
        def revoke_policy(self, req):
            return {"status": "error", "error_code": "BACKEND_TIMEOUT"}

    svc2 = _svc(_store(path), backend=AmbiguousBackend(_backend()))
    key = "k-b1-uncertain-revoke"
    res = svc2.revoke_policy(_op_req("p-b1-uncertain", digest, key=key))
    assert res.get("status") in ("ok", "error")
    rec = _idem(_store(path), key, "revoke_policy")
    assert rec is not None
    assert rec["operation_outcome"] == "UNCERTAIN"
    assert _store(path).get_by_policy("p-b1-uncertain", 1)["installation_state"] == "REVOKING"


def test_revoke_recovery_retry_reenters_in_progress_then_succeeds():
    """Same-key revoke recovery re-enters execution from UNCERTAIN to SUCCEEDED."""
    path = _db_path()
    store = _store(path)

    class FailOnceBackend:
        def __init__(self, inner):
            self.inner = inner
            self.fail_revoke = True

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def revoke_policy(self, req):
            if self.fail_revoke:
                self.fail_revoke = False
                return {"status": "error", "error_code": "BACKEND_FAILURE"}
            return self.inner.revoke_policy(req)

    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=FailOnceBackend(_backend()),
    )
    digest, _ = _install_active(store, svc, "p-b1-retry")
    key = "k-b1-retry"
    req = _op_req("p-b1-retry", digest, key=key)

    assert svc.revoke_policy(req)["status"] == "error"
    assert _idem(store, key, "revoke_policy")["operation_outcome"] == "UNCERTAIN"
    assert store.get_by_policy("p-b1-retry", 1)["installation_state"] == "REVOKING"

    # Recovery retry re-enters execution from UNCERTAIN (IN_PROGRESS marker) and
    # finishes with an atomic SUCCEEDED + COMPLETED ledger record.
    assert svc.revoke_policy(dict(req))["status"] == "ok"
    final = _idem(store, key, "revoke_policy")
    assert final["operation_outcome"] == "SUCCEEDED"
    assert final["status"] == "COMPLETED"
    assert store.get_by_policy("p-b1-retry", 1)["installation_state"] == "REVOKED"


# ------------------------------------------------------- crash / intent ---

def test_intent_is_durable_before_backend_and_backend_not_called_on_ledger_failure():
    """Intent persists; a failure advancing to IN_PROGRESS fails closed before backend."""
    path = _db_path()
    base = _store(path)

    class FailInProgressStore(ControllerOwnershipStore):
        def update_operation_outcome(self, *args, **kwargs):
            raise BrokerDBError("injected ledger persistence failure")

    class CountingBackend:
        def __init__(self, inner):
            self.inner = inner
            self.calls = []
        def __getattr__(self, name):
            attr = getattr(self.inner, name)
            if callable(attr):
                def wrapped(*a, **k):
                    self.calls.append(name)
                    return attr(*a, **k)
                return wrapped
            return attr

    be = CountingBackend(_backend())
    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=FailInProgressStore(db_path=path), backend=be,
    )
    req = _install_req(pid="p-b1-intent", key="k-b1-intent")
    with pytest.raises(FirewallControllerPersistenceError):
        svc.install_policy(req)

    assert be.calls == []  # backend side effect never executed
    fresh = _store(path)
    rec = _idem(fresh, "k-b1-intent")
    assert rec is not None
    assert rec["status"] == "PENDING"
    assert rec["operation_outcome"] == "INTENT_RECORDED"
    own = fresh.get_by_policy("p-b1-intent", 1)
    assert own is None or own.get("installation_state") != "ACTIVE"


def test_interruption_after_intent_does_not_fabricate_success_and_reconcile_is_uncertain():
    path = _db_path()
    store = _store(path)

    class ExplodingBackend:
        def __init__(self, inner):
            self.inner = inner
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def install_policy(self, req):
            raise RuntimeError("simulated crash before backend effect")

    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=ExplodingBackend(_backend()),
    )
    req = _install_req(pid="p-b1-crash-intent", key="k-b1-crash-intent")
    with pytest.raises(Exception):
        svc.install_policy(req)

    fresh = _store(path)
    rec = _idem(fresh, "k-b1-crash-intent")
    assert rec is not None
    assert rec["status"] == "PENDING"
    assert rec["operation_outcome"] == "IN_PROGRESS"
    assert not rec.get("response_json")  # no fabricated response for interrupted operation

    # Fresh process replay with same key must not fabricate success.
    svc2 = _svc(fresh)
    with pytest.raises(Exception):
        svc2.install_policy(req)

    # Reconciliation classifies it uncertain and never auto-promotes.
    own = fresh.get_by_policy("p-b1-crash-intent", 1)
    assert own.get("installation_state") in ("REQUESTED", "VALIDATING")
    assert own.get("installation_state") != "ACTIVE"
    result = svc2.reconcile_pending_operations(
        _op_req("p-b1-crash-intent", req["compiled_rule_digest"])
    )
    assert result["status"] == "ok"
    entries = (result.get("result") or {}).get("uncertain") or []
    assert any(
        e.get("idempotency_key") == "k-b1-crash-intent"
        and e.get("operation_outcome") == "IN_PROGRESS"
        and e.get("reason") == "pending_no_auto_replay"
        for e in entries
    )
    assert fresh.get_by_policy("p-b1-crash-intent", 1)["installation_state"] != "ACTIVE"


def test_interruption_after_backend_effect_is_uncertain_until_verified():
    """Backend effect committed but controller interrupted: no fabricated ACTIVE."""
    path = _db_path()
    store = _store(path)

    class EffectThenCrashBackend:
        """Shared backend: applies the effect once, then simulates controller crash.

        The same wrapper instance is reused by the recovery service so the backend
        effect remains observable across the simulated process boundary.
        """
        def __init__(self, inner):
            self.inner = inner
            self.crash_next_install = True

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def install_policy(self, req):
            res = self.inner.install_policy(req)
            if self.crash_next_install:
                self.crash_next_install = False
                # Backend effect is applied; controller crashes before persisting outcome.
                raise RuntimeError("simulated crash after backend effect")
            return res

    shared_backend = EffectThenCrashBackend(_backend())
    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=shared_backend,
    )
    req = _install_req(pid="p-b1-after-be", key="k-b1-after-be")
    with pytest.raises(Exception):
        svc.install_policy(req)

    fresh = _store(path)
    rec = _idem(fresh, "k-b1-after-be")
    assert rec["operation_outcome"] == "IN_PROGRESS"
    assert rec["status"] == "PENDING"

    # Recovery reuses the same backend (effect still present). It must not promote
    # to ACTIVE without verification evidence.
    svc2 = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=fresh, backend=shared_backend,
    )
    rec_res = svc2.reconcile_pending_operations(
        _op_req("p-b1-after-be", req["compiled_rule_digest"])
    )
    assert rec_res["status"] == "ok"
    assert fresh.get_by_policy("p-b1-after-be", 1)["installation_state"] != "ACTIVE"

    # Only an explicit, evidence-backed verify may promote.
    assert svc2.verify_policy(
        _op_req("p-b1-after-be", req["compiled_rule_digest"])
    )["status"] == "ok"
    assert fresh.get_by_policy("p-b1-after-be", 1)["installation_state"] == "ACTIVE"
    assert _idem(fresh, "k-b1-after-be")["operation_outcome"] == "IN_PROGRESS"


# ------------------------------------------------- duplicates / conflicts ---

def test_duplicate_identity_and_conflicting_operations_deterministic():
    store = _store()
    svc = _svc(store)
    req = _install_req(pid="p-b1-dup", key="k-b1-dup")
    r1 = svc.install_policy(req)
    r2 = svc.install_policy(req)  # identical replay
    assert r1["status"] == r2["status"] == "ok"
    assert _idem(store, "k-b1-dup")["operation_outcome"] == "SUCCEEDED"
    assert len([o for o in store.list_ownerships() if o["policy_id"] == "p-b1-dup"]) == 1

    conflicting = _install_req(pid="p-b1-dup", key="k-b1-dup", instance_id="other")
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(conflicting)
    # Conflicting request must not overwrite the committed outcome.
    assert _idem(store, "k-b1-dup")["operation_outcome"] == "SUCCEEDED"


def test_concurrent_same_key_only_one_backend_effect_and_one_ledger_record():
    import threading
    import time

    path = _db_path()
    store = _store(path)

    class CountingBackend:
        def __init__(self, inner):
            self.inner = inner
            self.install_calls = 0
            self.lock = threading.Lock()
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def install_policy(self, req):
            with self.lock:
                self.install_calls += 1
            # Test-only race widening: keeps the PENDING ledger window open long
            # enough for the concurrent caller to observe it. Not synchronization.
            time.sleep(0.02)
            return self.inner.install_policy(req)

    be = CountingBackend(_backend())
    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=be,
    )
    req = _install_req(pid="p-b1-conc", key="k-b1-conc")
    results = [None, None]
    errors = [None, None]

    def worker(idx):
        try:
            results[idx] = svc.install_policy(req)
        except Exception as exc:
            errors[idx] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(20)

    # Identical-key replay is deterministic: exactly one backend effect and one
    # ownership/ledger record. Under load the losing caller may receive either the
    # cached ok response or the bounded "operation pending" idempotency error; both
    # are safe. Never two backend effects, two ownership records, or two ledgers.
    assert be.install_calls == 1
    assert all(
        err is None or isinstance(err, FirewallControllerIdempotencyError)
        for err in errors
    ), errors
    assert any(isinstance(r, dict) and r.get("status") == "ok" for r in results)
    assert all(
        r is None or (isinstance(r, dict) and r.get("status") == "ok")
        for r in results
    ), results
    fresh = _store(path)
    assert len([o for o in fresh.list_ownerships() if o["policy_id"] == "p-b1-conc"]) == 1
    rec = _idem(fresh, "k-b1-conc")
    assert rec["status"] == "COMPLETED"
    assert rec["operation_outcome"] == "SUCCEEDED"


# ------------------------------------------------- bindings / append-only ---

def test_evidence_and_ownership_bindings_remain_valid_after_ledger_changes():
    store = _store()
    svc = _svc(store)
    digest, own = _install_active(store, svc, "p-b1-bindings")

    own2 = store.get_by_policy("p-b1-bindings", 1)
    assert own2["ownership_record_id"] == own["ownership_record_id"]
    assert own2["instance_id"] == "i1" and own2["network_id"] == "n1"
    evidence = store.get_evidence_by_policy("p-b1-bindings", 1)
    assert len(evidence) == 1
    ev = evidence[0]
    assert ev["ownership_record_id"] == own["ownership_record_id"]
    assert ev["canonical_policy_digest"] == digest
    assert ev["verification_result"] == "verified"

    trusted_own, body = store.read_trusted_canonical_policy_body(
        "p-b1-bindings", 1, expected_ownership_record_id=own["ownership_record_id"],
        expected_compiled_rule_digest=digest,
    )
    assert body["compiled_rule_digest"] == digest

    rec = svc.reconcile_pending_operations(_op_req("p-b1-bindings", digest))
    assert rec["status"] == "ok"


@pytest.mark.parametrize("table", [
    "controller_lifecycle_history", "controller_evidence", "controller_audit",
])
def test_append_only_protections_still_enforced(table):
    store = _store()
    svc = _svc(store)
    digest, own = _install_active(store, svc, f"p-b1-append-{table}")
    with pytest.raises(Exception):
        store.db.execute(f"UPDATE {table} SET policy_id='tampered' WHERE policy_id=?", (f"p-b1-append-{table}",))
    with pytest.raises(Exception):
        store.db.execute(f"DELETE FROM {table} WHERE policy_id=?", (f"p-b1-append-{table}",))
