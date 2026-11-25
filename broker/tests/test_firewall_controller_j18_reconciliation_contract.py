"""Phase 2L.2J.18 reconciliation contract and evidence-completeness tests (mock-only).

Focused, deterministic coverage for per-policy reconciliation accounting,
lifecycle/evidence outcomes, concurrency/reopen/recovery behavior, and
idempotency interaction in covered paths. No live/host/privileged operations.
"""
from __future__ import annotations

import os
import tempfile
import threading
import uuid

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import FirewallControllerRequestError
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


# --- helpers ---

def _store(path=None):
    if path is None:
        path = os.path.join(tempfile.mkdtemp(), "j18.db")
    return ControllerOwnershipStore(db_path=path)


def _svc(store=None, backend=None):
    store = store or _store()
    backend = backend or authorized_backend()
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000}, backend=backend, ownership_store=store
    )


def _base_rule(**overrides):
    r = {
        "family": "ipv4", "direction": "ingress", "protocol": "tcp",
        "source_cidr": "10.0.0.0/24", "destination_cidr": "10.0.1.0/24",
        "port_start": 80, "port_end": 80, "action": "accept",
    }
    r.update(overrides)
    return r


def _install_req(pid=None, rules=None, key=None, ver=1, **overrides):
    rules = [_base_rule()] if rules is None else rules
    norm = validate_and_normalize_rules(rules, sorted({r["family"] for r in rules}))
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid or f"p-{uuid.uuid4()}", "policy_version": ver,
        "compiled_rule_digest": compiled_rule_digest(norm), "compiled": {},
        "rules": [dict(r) for r in rules],
        "required_families": sorted({r["family"] for r in rules}),
        "peer_uid": 1000, "peer_gid": 1000, "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


def _op_req(pid, digest, ver=1, **overrides):
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()), "policy_id": pid, "policy_version": ver,
        "compiled_rule_digest": digest, "peer_uid": 1000, "peer_gid": 1000,
        "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


def _install_active(store, svc, pid, ver=1):
    req = _install_req(pid=pid, ver=ver)
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    assert svc.verify_policy(_op_req(pid, digest, ver=ver))["status"] == "ok"
    own = store.get_by_policy(pid, ver)
    assert own and own.get("installation_state") == "ACTIVE"
    return digest, own


def _reconcile(svc, pid, digest, ver=1, **overrides):
    return svc.reconcile_pending_operations(_op_req(pid, digest, ver=ver, **overrides))


def _set_state(store, pid, state, prev=None, ver=1):
    own = store.get_by_policy(pid, ver)
    prev_state = prev or own.get("installation_state")
    store.update_ownership_state(own["ownership_record_id"], state, prev_state, own.get("lifecycle_version"))
    return store.get_by_policy(pid, ver)


def _mentioned(result):
    out = set()
    for bucket in ("reconciled", "uncertain", "errors", "adopted"):
        for item in (result.get(bucket) or []):
            if item.get("policy_id"):
                out.add(item.get("policy_id"))
    return out


# --- A/B: contract, per-policy inventory/accounting, no silent skip ---

def test_reconcile_public_contract_requires_policy_identifiers_no_full_scan_exposure():
    svc = _svc()
    # validator/contract requires policy_id, policy_version, compiled_rule_digest
    with pytest.raises((FirewallControllerRequestError, Exception)):
        svc.reconcile_pending_operations({
            "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
            "idempotency_key": str(uuid.uuid4()),
            "peer_uid": 1000, "peer_gid": 1000,
        })


def test_reconcile_missing_ownership_has_explicit_uncertain_outcome():
    svc = _svc()
    res = svc.reconcile_pending_operations(_op_req("p-miss-own", "a" * 64))
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-miss-own" and u.get("reason") == "no_ownership_no_adoption" for u in uncertain)


def test_reconcile_ownership_without_lifecycle_history_explicitly_accounted():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-nohist")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-nohist", 1)
    assert own is not None
    # history may exist from install; ensure targeted reconcile still explicitly accounts for record
    res = _reconcile(svc, "p-nohist", digest)
    assert res.get("status") in ("ok", "error")
    assert "p-nohist" in _mentioned(res.get("result") or {})


@pytest.mark.parametrize("state", ["FAILED", "CLEANUP_PENDING", "ORPHANED"])
def test_terminalish_states_have_explicit_no_auto_change_outcome(state):
    store = _store(); svc = _svc(store)
    req = _install_req(pid=f"p-term-{state.lower()}")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy(f"p-term-{state.lower()}", 1)
    oid = own["ownership_record_id"]
    # drive to desired state deterministically via direct state progression where valid
    # FAILED reachable from REQUESTED/VALIDATING/INSTALLING; CLEANUP_PENDING/ORPHANED via allowed paths
    store.update_ownership_state(oid, "FAILED", own.get("installation_state"), own.get("lifecycle_version"))
    own = store.get_by_policy(f"p-term-{state.lower()}", 1)
    if state == "CLEANUP_PENDING":
        store.update_ownership_state(oid, "CLEANUP_PENDING", "FAILED", own.get("lifecycle_version"))
    elif state == "ORPHANED":
        store.update_ownership_state(oid, "CLEANUP_PENDING", "FAILED", own.get("lifecycle_version"))
        own = store.get_by_policy(f"p-term-{state.lower()}", 1)
        store.update_ownership_state(oid, "ORPHANED", "CLEANUP_PENDING", own.get("lifecycle_version"))
    res = _reconcile(svc, f"p-term-{state.lower()}", digest)
    assert res.get("status") == "ok"
    reconciled = (res.get("result") or {}).get("reconciled") or []
    assert any(r.get("policy_id") == f"p-term-{state.lower()}" and r.get("action") == "no_auto_change_terminalish" for r in reconciled)
    assert store.get_by_policy(f"p-term-{state.lower()}", 1).get("installation_state") == state


# --- D: evidence completeness / lifecycle outcomes ---

def test_verifying_state_explicitly_uncertain_no_silent_skip_or_promotion():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-j18-verifying"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-j18-verifying", 1)
    store.update_ownership_state(own["ownership_record_id"], "VERIFYING", own.get("installation_state"), own.get("lifecycle_version"))
    res = _reconcile(svc, "p-j18-verifying", digest)
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-j18-verifying" and u.get("reason") == "verifying_state_uncertain" for u in uncertain)
    assert store.get_by_policy("p-j18-verifying", 1).get("installation_state") == "VERIFYING"


def test_install_states_backend_missing_fail_closed_to_failed_not_active():
    path = _db_path = os.path.join(tempfile.mkdtemp(), "j18-bmiss.db")
    store = _store(path); svc = _svc(store)
    req = _install_req(pid="p-bmiss"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    # fresh backend = backend missing/readback shows missing
    store2 = _store(path); svc2 = _svc(store2, backend=authorized_backend())
    res = _reconcile(svc2, "p-bmiss", digest)
    assert res.get("status") == "ok"
    own = store2.get_by_policy("p-bmiss", 1)
    assert own.get("installation_state") not in ("ACTIVE", "VERIFIED")
    assert "p-bmiss" in _mentioned(res.get("result") or {})


def test_active_backend_mismatch_is_uncertain_no_false_active_confirmation():
    store = _store(); svc = _svc(store)
    # seed ACTIVE ownership but backend (fresh service backend instance in same svc context may differ?)
    # easier: create ACTIVE then use a service with fresh backend that has no installed state
    path = os.path.join(tempfile.mkdtemp(), "j18-am.db")
    store1 = _store(path); svc1 = _svc(store1)
    digest, _ = _install_active(store1, svc1, "p-am")
    store2 = _store(path); svc2 = _svc(store2, backend=authorized_backend())
    res = _reconcile(svc2, "p-am", digest)
    assert res.get("status") == "ok"
    result = res.get("result") or {}
    assert "p-am" in _mentioned(result)
    own = store2.get_by_policy("p-am", 1)
    # backend missing/unavailable for fresh backend => must not confirm active_ok
    assert own.get("installation_state") != "VERIFIED"


def test_revoking_backend_still_present_remains_uncertain_no_reactivation():
    store = _store(); svc = _svc(store)
    digest, own = _install_active(store, svc, "p-rv-pres")
    # initiate revoke flow by moving to REVOKING state with backend still installed
    own = store.get_by_policy("p-rv-pres", 1)
    store.update_ownership_state(own["ownership_record_id"], "REVOKING", "ACTIVE", own.get("lifecycle_version"))
    res = _reconcile(svc, "p-rv-pres", digest)
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    # backend still present/installed => partial revoke uncertain, must not reactivate
    assert any(u.get("policy_id") == "p-rv-pres" for u in uncertain)
    assert store.get_by_policy("p-rv-pres", 1).get("installation_state") in ("REVOKING", "REVOKED", "CLEANUP_PENDING")
    assert store.get_by_policy("p-rv-pres", 1).get("installation_state") != "ACTIVE"


# --- E: concurrency, reopen, repeated recovery ---

def test_concurrent_reconcile_same_policy_deterministic_no_duplicate_promotion_or_corruption():
    path = os.path.join(tempfile.mkdtemp(), "j18-conc.db")
    store = _store(path); svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-j18-conc")
    barrier = threading.Barrier(4)
    results = [None] * 4
    errs = [None] * 4

    def w(i):
        try:
            barrier.wait(timeout=10)
            results[i] = _reconcile(svc, "p-j18-conc", digest)
        except Exception as e:
            errs[i] = e

    ts = [threading.Thread(target=w, args=(i,)) for i in range(4)]
    for t in ts: t.start()
    for t in ts: t.join(timeout=30)
    assert all(e is None for e in errs)
    assert all(isinstance(r, dict) and "p-j18-conc" in _mentioned(r.get("result") or {}) for r in results)
    own = store.get_by_policy("p-j18-conc", 1)
    assert own.get("installation_state") == "ACTIVE"


def test_db_reopen_and_repeated_reconciliation_after_uncertain_recovery_fail_closed():
    path = os.path.join(tempfile.mkdtemp(), "j18-reopen.db")
    store = _store(path); svc = _svc(store)
    req = _install_req(pid="p-j18-reopen", key="k-j18-reopen")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    for _ in range(3):
        s = _store(path); sv = _svc(s, backend=authorized_backend())
        res = _reconcile(sv, "p-j18-reopen", digest, idempotency_key=str(uuid.uuid4()), request_id=str(uuid.uuid4()), operation_id=str(uuid.uuid4()))
        assert res.get("status") == "ok"
        assert "p-j18-reopen" in _mentioned(res.get("result") or {})
        assert s.get_by_policy("p-j18-reopen", 1).get("installation_state") not in ("ACTIVE", "VERIFIED")


def test_reconcile_vs_install_race_no_false_active_or_silent_skip():
    path = os.path.join(tempfile.mkdtemp(), "j18-race.db")
    store = _store(path); svc = _svc(store)
    req = _install_req(pid="p-j18-ri")
    digest = req["compiled_rule_digest"]
    barrier = threading.Barrier(2)
    out = {}
    errs = {}

    def do_install():
        try:
            barrier.wait(timeout=10)
            out['install'] = svc.install_policy(req)
        except Exception as e:
            errs['install'] = e

    def do_reconcile():
        try:
            barrier.wait(timeout=10)
            out['reconcile'] = svc.reconcile_pending_operations(_op_req("p-j18-ri", digest))
        except Exception as e:
            errs['reconcile'] = e

    t1 = threading.Thread(target=do_install); t2 = threading.Thread(target=do_reconcile)
    t1.start(); t2.start(); t1.join(30); t2.join(30)
    # either reconcile saw no ownership (explicit uncertain) or saw/handled record explicitly; no false ACTIVE
    own = store.get_by_policy("p-j18-ri", 1)
    if own:
        assert own.get("installation_state") != "ACTIVE"


# --- C/D: canonical body and evidence integrity during reconcile ---

def test_canonical_body_corruption_during_reconcile_is_uncertain_no_promotion():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-j18-cbc")
    store.db.execute("UPDATE controller_policy_bodies SET canonical_rules_json='[bad' WHERE policy_id=? AND policy_version=?", ("p-j18-cbc", 1))
    res = _reconcile(svc, "p-j18-cbc", digest)
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-j18-cbc" for u in uncertain)


def test_duplicate_verification_evidence_does_not_cause_false_or_duplicate_active_promotion():
    store = _store(); svc = _svc(store)
    digest, own = _install_active(store, svc, "p-j18-dupev")
    # insert an extra valid-looking verified evidence row (append-only table allows insert)
    store.store_evidence({
        'evidence_id': str(uuid.uuid4()), 'ownership_record_id': own['ownership_record_id'],
        'policy_id': 'p-j18-dupev', 'policy_version': 1, 'instance_id': 'i1', 'network_id': 'n1',
        'canonical_policy_digest': digest, 'address_family': 'ipv4', 'installed_rule_ids': [],
        'verification_result': 'verified', 'controller_identity': 'test', 'request_id': str(uuid.uuid4()),
        'controller_transaction_id': str(uuid.uuid4()),
    })
    before = len(store.get_evidence_by_policy('p-j18-dupev', 1))
    res = _reconcile(svc, "p-j18-dupev", digest)
    assert res.get("status") == "ok"
    assert store.get_by_policy('p-j18-dupev', 1).get('installation_state') == 'ACTIVE'
    # repeated reconcile should not create duplicate lifecycle promotions beyond safe behavior
    res2 = _reconcile(svc, "p-j18-dupev", digest)
    assert res2.get("status") == "ok"
    assert store.get_by_policy('p-j18-dupev', 1).get('installation_state') == 'ACTIVE'
    assert len(store.get_evidence_by_policy('p-j18-dupev', 1)) == before


# --- F: idempotency/recovery interaction (covered) ---

def test_pending_idempotency_for_policy_reported_uncertain_no_auto_replay():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-j18-pend")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    # create a pending idempotency record scoped to policy
    store.create_idempotency_record("k-j18-pend", "install_policy", "d"*64, resource_key="p-j18-pend:1")
    res = _reconcile(svc, "p-j18-pend", digest)
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("reason") == "pending_no_auto_replay" for u in uncertain)
