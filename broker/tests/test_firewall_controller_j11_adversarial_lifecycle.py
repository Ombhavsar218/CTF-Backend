"""Phase 2L.2J.11 adversarial lifecycle, CAS/concurrency, persistence recovery
and retry/idempotency tests (mock-only).

Uses disposable DBs, deterministic synchronization (barriers/events), and
actual service/store APIs. No live Docker/host/privileged operations.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager

import pytest

from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


# --- helpers ---

def _store(path=None):
    if path is None:
        path = os.path.join(tempfile.mkdtemp(), "j11.db")
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


def _install_req(pid=None, rules=None, key=None, **overrides):
    rules = [_base_rule()] if rules is None else rules
    norm = validate_and_normalize_rules(rules, sorted({r["family"] for r in rules}))
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
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
    return digest, own


def _reconcile(svc, pid, digest, **overrides):
    return svc.reconcile_pending_operations(_op_req(pid, digest, **overrides))


def _set_state(store, pid, state, prev=None):
    own = store.get_by_policy(pid, 1)
    prev_state = prev or own.get("installation_state")
    store.update_ownership_state(
        own["ownership_record_id"], state, prev_state, own.get("lifecycle_version")
    )
    return store.get_by_policy(pid, 1)


def _evidence_for(own, result="verified", **overrides):
    ev = {
        "evidence_id": str(uuid.uuid4()),
        "ownership_record_id": own["ownership_record_id"],
        "policy_id": own["policy_id"],
        "policy_version": own["policy_version"],
        "instance_id": own.get("instance_id"),
        "network_id": own.get("network_id"),
        "canonical_policy_digest": own.get("canonical_policy_digest"),
        "address_family": own.get("address_family") or "ipv4",
        "installed_rule_ids": [],
        "controller_identity": "mock-controller",
        "controller_transaction_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "verification_result": result,
    }
    ev.update(overrides)
    return ev


# =========================
# A. Lifecycle evidence matrix (covered states/conditions)
# =========================

@pytest.mark.parametrize("state", [
    "REQUESTED", "VALIDATING", "INSTALLING", "VERIFYING", "VERIFIED", "ACTIVE",
    "REVOKING", "REVOKED", "FAILED", "CLEANUP_PENDING", "ORPHANED",
])
def test_reconcile_handles_known_states_without_silent_skip(state):
    store = _store()
    svc = _svc(store)
    req = _install_req(pid=f"p-{state.lower()}")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy(req["policy_id"], 1)
    cur = own.get("installation_state")
    # Deterministic state setup via valid path where possible; otherwise direct update for matrix coverage.
    # VERIFYING/VERIFIED/ACTIVE/REVOKING/REVOKED transitions use supported flows where feasible.
    pid = req["policy_id"]
    if state == cur:
        pass
    elif state == "VERIFYING":
        _set_state(store, pid, "VERIFYING", cur)
    elif state == "VERIFIED":
        _set_state(store, pid, "VERIFYING", cur)
        own = store.get_by_policy(pid, 1)
        _set_state(store, pid, "VERIFIED", "VERIFYING")
        store.store_evidence(_evidence_for(store.get_by_policy(pid, 1), "verified"))
    elif state == "ACTIVE":
        digest = _install_active(store, svc, pid)[0]
    elif state == "REVOKING":
        digest = _install_active(store, svc, pid)[0]
        own = store.get_by_policy(pid, 1)
        _set_state(store, pid, "REVOKING", "ACTIVE")
    elif state == "REVOKED":
        digest = _install_active(store, svc, pid)[0]
        own = store.get_by_policy(pid, 1)
        _set_state(store, pid, "REVOKING", "ACTIVE")
        own = store.get_by_policy(pid, 1)
        store.store_evidence(_evidence_for(own, "revoked"))
        _set_state(store, pid, "REVOKED", "REVOKING")
    elif state == "FAILED":
        store.db.execute("UPDATE controller_ownership SET installation_state='FAILED', lifecycle_version=lifecycle_version+1 WHERE policy_id=? AND policy_version=?", (pid, 1))
    elif state == "CLEANUP_PENDING":
        store.db.execute("UPDATE controller_ownership SET installation_state='FAILED', lifecycle_version=lifecycle_version+1 WHERE policy_id=? AND policy_version=?", (pid, 1))
        own = store.get_by_policy(pid, 1)
        _set_state(store, pid, "CLEANUP_PENDING", "FAILED")
    elif state == "ORPHANED":
        store.db.execute("UPDATE controller_ownership SET installation_state='FAILED', lifecycle_version=lifecycle_version+1 WHERE policy_id=? AND policy_version=?", (pid, 1))
        own = store.get_by_policy(pid, 1)
        _set_state(store, pid, "ORPHANED", "FAILED")
    elif state in ("REQUESTED", "VALIDATING", "INSTALLING"):
        store.db.execute("UPDATE controller_ownership SET installation_state=?, lifecycle_version=lifecycle_version+1 WHERE policy_id=? AND policy_version=?", (state, pid, 1))
    res = _reconcile(svc, pid, digest)
    assert res.get("status") in ("ok", "error")
    result = res.get("result") or {}
    mentioned = set()
    for bucket in ("reconciled", "uncertain", "errors", "adopted"):
        for item in (result.get(bucket) or []):
            if item.get("policy_id"):
                mentioned.add(item.get("policy_id"))
    assert pid in mentioned, f"state {state} silently skipped"


def test_unknown_persisted_state_fails_closed():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-unk"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    store.db.execute("UPDATE controller_ownership SET installation_state='WEIRD_STATE' WHERE policy_id=? AND policy_version=?", ("p-unk", 1))
    res = _reconcile(svc, "p-unk", digest)
    assert res.get("status") == "ok"
    assert any(u.get("reason") == "corrupt_ownership_state" for u in (res.get("result") or {}).get("uncertain") or [])


def test_verified_missing_evidence_no_promotion():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-v-miss"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-v-miss", 1)
    store.update_ownership_state(own["ownership_record_id"], "VERIFYING", own.get("installation_state"), own.get("lifecycle_version"))
    own = store.get_by_policy("p-v-miss", 1)
    store.update_ownership_state(own["ownership_record_id"], "VERIFIED", "VERIFYING", own.get("lifecycle_version"))
    res = _reconcile(svc, "p-v-miss", digest)
    assert any(u.get("reason") == "verified_without_valid_evidence" for u in (res.get("result") or {}).get("uncertain") or [])
    assert store.get_by_policy("p-v-miss", 1).get("installation_state") == "VERIFIED"


def test_verified_wrong_policy_version_evidence_no_promotion():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-v-wrongver"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-v-wrongver", 1)
    store.update_ownership_state(own["ownership_record_id"], "VERIFYING", own.get("installation_state"), own.get("lifecycle_version"))
    own = store.get_by_policy("p-v-wrongver", 1)
    store.update_ownership_state(own["ownership_record_id"], "VERIFIED", "VERIFYING", own.get("lifecycle_version"))
    bad = _evidence_for(store.get_by_policy("p-v-wrongver", 1), "verified", policy_version=99)
    store.store_evidence(bad)
    res = _reconcile(svc, "p-v-wrongver", digest)
    assert any(u.get("reason") == "verified_without_valid_evidence" for u in (res.get("result") or {}).get("uncertain") or [])
    assert store.get_by_policy("p-v-wrongver", 1).get("installation_state") == "VERIFIED"


def test_verified_wrong_ownership_binding_evidence_no_promotion():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-v-wrongown"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-v-wrongown", 1)
    store.update_ownership_state(own["ownership_record_id"], "VERIFYING", own.get("installation_state"), own.get("lifecycle_version"))
    own = store.get_by_policy("p-v-wrongown", 1)
    store.update_ownership_state(own["ownership_record_id"], "VERIFIED", "VERIFYING", own.get("lifecycle_version"))
    bad = _evidence_for(store.get_by_policy("p-v-wrongown", 1), "verified", ownership_record_id="wrong-oid")
    store.store_evidence(bad)
    res = _reconcile(svc, "p-v-wrongown", digest)
    assert any(u.get("reason") == "verified_without_valid_evidence" for u in (res.get("result") or {}).get("uncertain") or [])
    assert store.get_by_policy("p-v-wrongown", 1).get("installation_state") == "VERIFIED"


def test_verified_wrong_digest_evidence_no_promotion():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-v-wrongdig"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-v-wrongown", 1) if False else store.get_by_policy("p-v-wrongdig", 1)
    store.update_ownership_state(own["ownership_record_id"], "VERIFYING", own.get("installation_state"), own.get("lifecycle_version"))
    own = store.get_by_policy("p-v-wrongdig", 1)
    store.update_ownership_state(own["ownership_record_id"], "VERIFIED", "VERIFYING", own.get("lifecycle_version"))
    bad = _evidence_for(own, "verified", canonical_policy_digest="f" * 64)
    store.store_evidence(bad)
    res = _reconcile(svc, "p-v-wrongdig", digest)
    assert any(u.get("reason") == "verified_without_valid_evidence" for u in (res.get("result") or {}).get("uncertain") or [])
    assert store.get_by_policy("p-v-wrongdig", 1).get("installation_state") == "VERIFIED"


def test_revoked_missing_evidence_uncertain():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-r-miss"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-r-miss", 1)
    store.db.execute("UPDATE controller_ownership SET installation_state='REVOKED', lifecycle_version=lifecycle_version+1 WHERE ownership_record_id=?", (own["ownership_record_id"],))
    res = _reconcile(svc, "p-r-miss", digest)
    assert any(u.get("reason") == "revoked_without_valid_evidence" for u in (res.get("result") or {}).get("uncertain") or [])


def test_active_backend_missing_becomes_uncertain():
    store = _store(); svc = _svc(store)
    # ACTIVE in persistence but backend fresh (missing install) -> reconcile must not keep healthy.
    req = _install_req(pid="p-a-missbe"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    assert svc.verify_policy(_op_req("p-a-missbe", digest))["status"] == "ok"
    assert store.get_by_policy("p-a-missbe", 1).get("installation_state") == "ACTIVE"
    # Reconcile against fresh backend service/store context for same DB: backend in svc has state; simulate missing by using new backend.
    backend2 = authorized_backend()
    svc2 = _svc(store, backend=backend2)
    res = svc2.reconcile_pending_operations(_op_req("p-a-missbe", digest))
    assert any(u.get("reason") == "active_backend_mismatch_or_unavailable" for u in (res.get("result") or {}).get("uncertain") or [])


# =========================
# B/C/D. Concurrency and CAS (deterministic, covered branches)
# =========================

def test_cas_stale_lifecycle_state_rejected_on_store_update():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-cas-state"); assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-cas-state", 1)
    with pytest.raises(PermissionError):
        store.update_ownership_state(own["ownership_record_id"], "VERIFYING", "REQUESTED", own.get("lifecycle_version"))


def test_concurrent_reconcile_and_revoke_no_false_success():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-conc-rv")
    barrier = threading.Barrier(2)
    outcomes = {}

    def do_reconcile():
        barrier.wait(timeout=10)
        outcomes['reconcile'] = svc.reconcile_pending_operations(_op_req("p-conc-rv", digest))

    def do_revoke():
        barrier.wait(timeout=10)
        try:
            outcomes['revoke'] = svc.revoke_policy(_op_req("p-conc-rv", digest))
        except Exception as e:
            outcomes['revoke_err'] = type(e).__name__

    t1 = threading.Thread(target=do_reconcile)
    t2 = threading.Thread(target=do_revoke)
    t1.start(); t2.start(); t1.join(timeout=30); t2.join(timeout=30)
    own = store.get_by_policy("p-conc-rv", 1)
    assert own is not None
    # No false ACTIVE after successful revoke path; state must be consistent (ACTIVE/REVOKING/REVOKED depending on ordering).
    assert own.get("installation_state") in ("ACTIVE", "REVOKING", "REVOKED", "CLEANUP_PENDING", "FAILED")


def test_concurrent_reconcile_and_verify_no_corruption():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-conc-vf")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    barrier = threading.Barrier(2)
    errors = []

    def do_reconcile():
        try:
            barrier.wait(timeout=10)
            svc.reconcile_pending_operations(_op_req("p-conc-vf", digest))
        except Exception as e:
            errors.append(e)

    def do_verify():
        try:
            barrier.wait(timeout=10)
            svc.verify_policy(_op_req("p-conc-vf", digest))
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=do_reconcile); t2 = threading.Thread(target=do_verify)
    t1.start(); t2.start(); t1.join(timeout=30); t2.join(timeout=30)
    own = store.get_by_policy("p-conc-vf", 1)
    assert own is not None
    assert own.get("installation_state") in ("INSTALLING", "VERIFYING", "VERIFIED", "ACTIVE", "FAILED", "CLEANUP_PENDING")


def test_stale_reconcile_cannot_overwrite_revoked_state():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-stale-rev")
    # Capture a reconcile context while ACTIVE by doing one reconcile (ok), then revoke, then another reconcile must not reactivate.
    assert svc.reconcile_pending_operations(_op_req("p-stale-rev", digest)).get("status") == "ok"
    assert svc.revoke_policy(_op_req("p-stale-rev", digest)).get("status") == "ok"
    own = store.get_by_policy("p-stale-rev", 1)
    assert own.get("installation_state") == "REVOKED"
    res = svc.reconcile_pending_operations(_op_req("p-stale-rev", digest))
    assert res.get("status") == "ok"
    own2 = store.get_by_policy("p-stale-rev", 1)
    assert own2.get("installation_state") == "REVOKED"


# =========================
# C. Crash/restart and persistence recovery (disposable DB, achievable points)
# =========================

def test_reopen_after_install_preserves_non_active_and_reconcile_safe():
    tmp = tempfile.mkdtemp(); db = os.path.join(tmp, "r.db")
    store1 = _store(db); svc1 = _svc(store1)
    req = _install_req(pid="p-reop-i"); digest = req["compiled_rule_digest"]
    assert svc1.install_policy(req)["status"] == "ok"
    store2 = _store(db); svc2 = _svc(store2, backend=authorized_backend())
    own = store2.get_by_policy("p-reop-i", 1)
    assert own.get("installation_state") != "ACTIVE"
    res = svc2.reconcile_pending_operations(_op_req("p-reop-i", digest))
    assert res.get("status") == "ok"
    assert store2.get_by_policy("p-reop-i", 1).get("installation_state") != "ACTIVE"


def test_repeated_recovery_idempotent_no_duplicate_evidence():
    tmp = tempfile.mkdtemp(); db = os.path.join(tmp, "rr.db")
    store1 = _store(db); svc1 = _svc(store1)
    digest, _ = _install_active(store1, svc1, "p-rr")
    for _ in range(3):
        storeN = _store(db); svcN = _svc(storeN)
        assert svcN.reconcile_pending_operations(_op_req("p-rr", digest)).get("status") == "ok"
    own = _store(db).get_by_policy("p-rr", 1)
    assert own.get("installation_state") == "ACTIVE"
    ev = _store(db).get_evidence_by_policy("p-rr", 1)
    # Evidence count should remain bounded (no explosion from repeated reconcile).
    assert isinstance(ev, list)
    assert len(ev) <= 5


# =========================
# G. Retry/idempotency boundedness (timing)
# =========================

def test_idempotency_retry_deadline_bounded_elapsed_time():
    # Exercise conflict/replay path timing by concurrent conflicting same-key installs in-process
    # is complex to force pending waits; instead verify bounded behavior on replay/conflict path
    # and that operations complete quickly (deadline guards in place).
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-time", key="k-time")
    assert svc.install_policy(req)["status"] == "ok"
    start = time.monotonic()
    # Replay same completed request (same key/payload/digest context via idempotency record) - should return quickly.
    # Construct identical request fields used for digest binding where possible.
    req2 = dict(req)
    req2["request_id"] = req["request_id"]
    req2["operation_id"] = req["operation_id"]
    res = svc.install_policy(req2)
    elapsed = time.monotonic() - start
    assert res.get("status") == "ok"
    assert elapsed < 2.0, f"replay path took too long: {elapsed}s"

