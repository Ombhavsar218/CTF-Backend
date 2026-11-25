"""Phase 2L.2J.9 focused RR-05 reconciliation integrity tests (mock-only).

Deterministic, temporary-DB tests covering covered-state accounting and
fail-closed reconciliation behaviors without live firewall/host integration.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


def _store():
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), "j9.db"))


def _svc(store=None, backend=None):
    store = store or _store()
    backend = backend or authorized_backend()
    return FirewallControllerService(
        allowed_uids={1000},
        allowed_gids={1000},
        backend=backend,
        ownership_store=store,
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


def _reconcile_policy(svc, pid, digest, **overrides):
    return svc.reconcile_pending_operations(_op_req(pid, digest, **overrides))


def _install_active(store, svc, pid):
    req = _install_req(pid=pid)
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    assert svc.verify_policy(_op_req(pid, digest))["status"] == "ok"
    own = store.get_by_policy(pid, 1)
    assert own and own.get("installation_state") == "ACTIVE"
    return digest


def test_reconcile_does_not_silently_skip_verifying_state():
    store = _store()
    svc = _svc(store)
    req = _install_req(pid="p-verifying")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-verifying", 1)
    oid = own["ownership_record_id"]
    ver = own.get("lifecycle_version") or 0
    # Move to VERIFYING deterministically (valid transition from INSTALLING in this flow).
    store.update_ownership_state(oid, "VERIFYING", own.get("installation_state"), ver)
    res = _reconcile_policy(svc, "p-verifying", digest)
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-verifying" and u.get("reason") == "verifying_state_uncertain" for u in uncertain)
    own2 = store.get_by_policy("p-verifying", 1)
    assert own2.get("installation_state") == "VERIFYING"


def test_reconcile_repeated_active_policy_is_idempotent_and_safe():
    store = _store()
    svc = _svc(store)
    digest = _install_active(store, svc, "p-repeat")
    r1 = _reconcile_policy(svc, "p-repeat", digest)
    r2 = _reconcile_policy(svc, "p-repeat", digest)
    assert r1.get("status") == "ok"
    assert r2.get("status") == "ok"
    own = store.get_by_policy("p-repeat", 1)
    assert own.get("installation_state") == "ACTIVE"
    hist = store.get_lifecycle_history(own.get("ownership_record_id"))
    assert isinstance(hist, list)


def test_reconcile_accounts_for_each_owned_record_without_silent_skip():
    store = _store()
    svc = _svc(store)
    d1 = _install_active(store, svc, "p-m1")
    req2 = _install_req(pid="p-m2")
    d2 = req2["compiled_rule_digest"]
    assert svc.install_policy(req2)["status"] == "ok"
    for pid, digest in (("p-m1", d1), ("p-m2", d2)):
        res = _reconcile_policy(svc, pid, digest)
        assert res.get("status") in ("ok", "error")
        result = res.get("result") or {}
        mentioned = set()
        for bucket in ("reconciled", "uncertain", "errors", "adopted"):
            for item in (result.get(bucket) or []):
                if item.get("policy_id"):
                    mentioned.add(item.get("policy_id"))
        assert pid in mentioned, f"owned record {pid} silently skipped by reconcile"


def test_reconcile_tampered_canonical_body_marks_uncertain_no_false_active():
    store = _store()
    svc = _svc(store)
    digest = _install_active(store, svc, "p-tamper-rec")
    store.db.execute(
        "UPDATE controller_policy_bodies SET compiled_rule_digest=? WHERE policy_id=? AND policy_version=?",
        ("e" * 64, "p-tamper-rec", 1),
    )
    res = _reconcile_policy(svc, "p-tamper-rec", digest)
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-tamper-rec" for u in uncertain)
    own = store.get_by_policy("p-tamper-rec", 1)
    assert own.get("installation_state") == "ACTIVE"


def test_reconcile_unknown_persisted_state_fails_closed_uncertain():
    store = _store()
    svc = _svc(store)
    req = _install_req(pid="p-unknown")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-unknown", 1)
    store.db.execute(
        "UPDATE controller_ownership SET installation_state=? WHERE ownership_record_id=?",
        ("NOT_A_REAL_STATE", own["ownership_record_id"]),
    )
    res = _reconcile_policy(svc, "p-unknown", digest)
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-unknown" and u.get("reason") == "corrupt_ownership_state" for u in uncertain)
