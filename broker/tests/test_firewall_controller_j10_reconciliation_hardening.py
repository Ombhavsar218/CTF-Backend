"""Phase 2L.2J.10 focused reconciliation hardening tests (mock-only).

Covers feasible, deterministic evidence for:
- Inventory/accounting contract (per-policy API), no unknown adoption
- Evidence-based state derivation/fail-closed cases
- CAS/concurrency safety (stale version/state, concurrent reconcile)
- Crash/restart/reopen recovery behavior (disposable DBs)
- Narrow N-02 canonical authority checks in reconcile paths
- J.8 idempotency regression sanity
"""
from __future__ import annotations

import os
import tempfile
import threading
import uuid

import pytest

from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import FirewallControllerIdempotencyError
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


def _store(path=None):
    if path is None:
        path = os.path.join(tempfile.mkdtemp(), "j10.db")
    return ControllerOwnershipStore(db_path=path)


def _svc(store=None, backend=None):
    store = store or _store()
    backend = backend or authorized_backend()
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000}, backend=backend, ownership_store=store
    )


def _base_rule(**overrides):
    r = {
        "family": "ipv4",
        "direction": "ingress",
        "protocol": "tcp",
        "source_cidr": "10.0.0.0/24",
        "destination_cidr": "10.0.1.0/24",
        "port_start": 80,
        "port_end": 80,
        "action": "accept",
    }
    r.update(overrides)
    return r


def _install_req(pid=None, rules=None, **overrides):
    rules = [_base_rule()] if rules is None else rules
    norm = validate_and_normalize_rules(rules, sorted({r["family"] for r in rules}))
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": pid or f"p-{uuid.uuid4()}",
        "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(norm),
        "compiled": {},
        "rules": [dict(r) for r in rules],
        "required_families": sorted({r["family"] for r in rules}),
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
    }
    req.update(overrides)
    return req


def _op_req(pid, digest, **overrides):
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": pid,
        "policy_version": 1,
        "compiled_rule_digest": digest,
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
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
    return digest


# --- A: Inventory contract/completeness (per-policy API) ---

def test_reconcile_unknown_ownership_not_adopted_fail_closed():
    store = _store()
    svc = _svc(store)
    req = _op_req("no-such-policy", "a" * 64)
    res = svc.reconcile_pending_operations(req)
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "no-such-policy" and u.get("reason") == "no_ownership_no_adoption" for u in uncertain)
    assert store.get_by_policy("no-such-policy", 1) is None


def test_reconcile_per_policy_accounts_for_target_record_only_in_result():
    store = _store()
    svc = _svc(store)
    d1 = _install_active(store, svc, "p-a")
    d2 = _install_active(store, svc, "p-b")
    res = svc.reconcile_pending_operations(_op_req("p-a", d1))
    assert res.get("status") == "ok"
    result = res.get("result") or {}
    mentioned = set()
    for bucket in ("reconciled", "uncertain", "errors", "adopted"):
        for item in (result.get(bucket) or []):
            if item.get("policy_id"):
                mentioned.add(item.get("policy_id"))
    assert "p-a" in mentioned
    # Per-policy API contract: only targeted record accounted for in this response.
    assert "p-b" not in mentioned


# --- B: Evidence-based derived-state validation / fail-closed ---

def test_verified_state_without_valid_evidence_fails_closed():
    store = _store()
    svc = _svc(store)
    req = _install_req(pid="p-ver-noev")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-ver-noev", 1)
    oid = own["ownership_record_id"]
    store.update_ownership_state(oid, "VERIFYING", own.get("installation_state"), own.get("lifecycle_version"))
    own = store.get_by_policy("p-ver-noev", 1)
    store.update_ownership_state(oid, "VERIFIED", "VERIFYING", own.get("lifecycle_version"))
    # No verification evidence stored -> reconcile must not promote to ACTIVE.
    res = svc.reconcile_pending_operations(_op_req("p-ver-noev", digest))
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-ver-noev" and u.get("reason") == "verified_without_valid_evidence" for u in uncertain)
    own2 = store.get_by_policy("p-ver-noev", 1)
    assert own2.get("installation_state") == "VERIFIED"


def test_revoked_state_without_evidence_fails_closed():
    store = _store()
    svc = _svc(store)
    req = _install_req(pid="p-rev-noev")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-rev-noev", 1)
    oid = own["ownership_record_id"]
    # Force REVOKED terminal state without revocation evidence (simulated corrupt/incomplete persistence).
    store.db.execute("UPDATE controller_ownership SET installation_state='REVOKED', lifecycle_version=lifecycle_version+1 WHERE ownership_record_id=?", (oid,))
    res = svc.reconcile_pending_operations(_op_req("p-rev-noev", digest))
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-rev-noev" and u.get("reason") == "revoked_without_valid_evidence" for u in uncertain)


# --- C: CAS / concurrency ---

def test_store_cas_rejects_stale_version_update():
    store = _store()
    svc = _svc(store)
    req = _install_req(pid="p-cas")
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-cas", 1)
    with pytest.raises(PermissionError):
        store.update_ownership_state(
            own["ownership_record_id"], "FAILED", own.get("installation_state"), (own.get("lifecycle_version") or 0) - 1
        )


def test_concurrent_reconcile_same_policy_no_corruption_or_duplicate_promotion():
    store = _store()
    svc = _svc(store)
    digest = _install_active(store, svc, "p-conc-rec")
    barrier = threading.Barrier(4)
    results = [None] * 4
    errors = [None] * 4

    def worker(i):
        try:
            barrier.wait(timeout=10)
            results[i] = svc.reconcile_pending_operations(_op_req("p-conc-rec", digest))
        except Exception as e:
            errors[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert all(e is None for e in errors)
    assert all(isinstance(r, dict) for r in results)
    own = store.get_by_policy("p-conc-rec", 1)
    assert own.get("installation_state") == "ACTIVE"
    hist = store.get_lifecycle_history(own.get("ownership_record_id"))
    # Repeated/concurrent reconcile of consistent ACTIVE record must not create duplicate transitions.
    active_promotions = [h for h in hist if h.get("new_state") == "ACTIVE" and h.get("prev_state") == "VERIFIED"]
    assert len(active_promotions) <= 1


# --- D: Crash/restart/persistence recovery (disposable DB reopen) ---

def test_restart_reopen_preserves_state_and_reconcile_remains_safe():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "restart.db")
    store1 = _store(db_path)
    svc1 = _svc(store1)
    digest = _install_active(store1, svc1, "p-restart")
    # Simulate restart/reopen
    store2 = _store(db_path)
    svc2 = _svc(store2)
    own = store2.get_by_policy("p-restart", 1)
    assert own and own.get("installation_state") == "ACTIVE"
    res = svc2.reconcile_pending_operations(_op_req("p-restart", digest))
    assert res.get("status") == "ok"
    own2 = store2.get_by_policy("p-restart", 1)
    assert own2.get("installation_state") == "ACTIVE"


def test_uncertain_backend_install_not_promoted_after_reopen():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "uncertain.db")
    store1 = _store(db_path)
    svc1 = _svc(store1)
    req = _install_req(pid="p-uncertain")
    digest = req["compiled_rule_digest"]
    assert svc1.install_policy(req)["status"] == "ok"
    # Simulate process restart: new service/store, backend has no installed state knowledge in this fresh backend.
    store2 = _store(db_path)
    backend2 = authorized_backend()  # fresh mock backend state
    svc2 = _svc(store2, backend=backend2)
    res = svc2.reconcile_pending_operations(_op_req("p-uncertain", digest))
    assert res.get("status") == "ok"
    own = store2.get_by_policy("p-uncertain", 1)
    assert own.get("installation_state") != "ACTIVE"
    assert own.get("installation_state") != "VERIFIED"


# --- E: Narrow N-02 canonical authority in reconcile ---

def test_reconcile_rejects_canonical_body_owner_mismatch_via_trusted_readback():
    store = _store()
    svc = _svc(store)
    digest = _install_active(store, svc, "p-ownrb")
    # Corrupt ownership binding on canonical body row to force mismatch (trusted read-back must fail closed).
    store.db.execute(
        "UPDATE controller_policy_bodies SET ownership_record_id=? WHERE policy_id=? AND policy_version=?",
        ("wrong-oid", "p-ownrb", 1),
    )
    res = svc.reconcile_pending_operations(_op_req("p-ownrb", digest))
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-ownrb" for u in uncertain)


# --- F: J.8 idempotency regression sanity (covered by existing suites) ---
# J.8 cross-process/create-race/idempotency regression suites are executed as part of
# focused and full broker regressions for this phase; no additional J.10-specific
# idempotency tests added here to avoid duplicating fragile payload-construction logic.
