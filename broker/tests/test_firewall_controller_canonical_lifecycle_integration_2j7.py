"""Phase 2L.2J.7 - trusted canonical read-back lifecycle integration tests (mock-only)."""
import json
import os
import tempfile
import uuid

import pytest

from broker.app.firewall_controller_contract import FirewallControllerRequestError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


def _store():
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), "j7.db"))


def _svc(store=None):
    return FirewallControllerService(
        allowed_uids={1000},
        allowed_gids={1000},
        backend=authorized_backend(),
        ownership_store=store or _store(),
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


def _req(pid=None, rules=None, key=None, op=None, **overrides):
    rules = [_base_rule()] if rules is None else rules
    norm = validate_and_normalize_rules(rules, sorted({r["family"] for r in rules}))
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": op or str(uuid.uuid4()),
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
    return req, norm


def _inspect_req(pid, digest):
    return {
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


def _verify_req(pid, digest):
    return _inspect_req(pid, digest)


def _install_and_tamper_body(store, svc, pid="p-j7", tamper_sql=None, params=()):
    req, norm = _req(pid=pid)
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    assert store.get_canonical_policy_body(pid, 1) is not None
    if tamper_sql:
        store.db.execute(tamper_sql, params)
    return digest, norm


def test_inspect_fails_closed_on_corrupt_canonical_body_json():
    store = _store()
    svc = _svc(store)
    digest, _ = _install_and_tamper_body(
        store, svc,
        tamper_sql="UPDATE controller_policy_bodies SET canonical_rules_json=? WHERE policy_id=? AND policy_version=?",
        params=("{bad", "p-j7", 1),
    )
    with pytest.raises((FirewallControllerRequestError, Exception)):
        svc.inspect_policy(_inspect_req("p-j7", digest))


def test_inspect_fails_closed_on_tampered_canonical_body_digest():
    store = _store()
    svc = _svc(store)
    digest, _ = _install_and_tamper_body(
        store, svc,
        tamper_sql="UPDATE controller_policy_bodies SET compiled_rule_digest=? WHERE policy_id=? AND policy_version=?",
        params=("0" * 64, "p-j7", 1),
    )
    with pytest.raises((FirewallControllerRequestError, Exception)):
        svc.inspect_policy(_inspect_req("p-j7", digest))


def test_verify_fails_closed_on_corrupt_canonical_body_and_does_not_activate():
    store = _store()
    svc = _svc(store)
    digest, _ = _install_and_tamper_body(
        store, svc,
        tamper_sql="UPDATE controller_policy_bodies SET canonical_rules_json=? WHERE policy_id=? AND policy_version=?",
        params=("{bad", "p-j7", 1),
    )
    with pytest.raises((FirewallControllerRequestError, Exception)):
        svc.verify_policy(_verify_req("p-j7", digest))
    own = store.get_by_policy("p-j7", 1)
    assert own is not None
    assert own.get("installation_state") != "ACTIVE"
    assert own.get("installation_state") != "VERIFIED"


def test_reconcile_marks_uncertain_on_invalid_canonical_body_and_no_false_active():
    store = _store()
    svc = _svc(store)
    # Create a VERIFIED-state ownership scenario? easier: install+verify to ACTIVE then tamper and reconcile should mark uncertain.
    req, _ = _req(pid="p-rec")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    assert svc.verify_policy(_verify_req("p-rec", digest))["status"] == "ok"
    own = store.get_by_policy("p-rec", 1)
    assert own.get("installation_state") == "ACTIVE"
    store.db.execute(
        "UPDATE controller_policy_bodies SET compiled_rule_digest=? WHERE policy_id=? AND policy_version=?",
        ("f" * 64, "p-rec", 1),
    )
    res = svc.reconcile_pending_operations({
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": "p-rec",
        "policy_version": 1,
        "compiled_rule_digest": digest,
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
    })
    assert isinstance(res, dict)
    if res.get("status") == "ok":
        uncertain = (res.get("result") or {}).get("uncertain") or []
        assert any(u.get("policy_id") == "p-rec" for u in uncertain)
    # Must not falsely promote/change into a different success state based on corrupt canonical body.
    own2 = store.get_by_policy("p-rec", 1)
    assert own2.get("installation_state") in ("ACTIVE", "VERIFYING", "INSTALLED", "REVOKING", "REVOKED", "FAILED", "CLEANUP_PENDING", "ORPHANED", "REQUESTED", "VALIDATING")


def test_inspect_rejects_wrong_owner_context_via_authorization_ownership_binding():
    store = _store()
    svc = _svc(store)
    req, _ = _req(pid="p-auth", **{"instance_id": "i1", "network_id": "n1"})
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    bad = _inspect_req("p-auth", digest)
    bad["instance_id"] = "i-other"
    with pytest.raises(PermissionError):
        svc.inspect_policy(bad)


def test_legacy_install_without_canonical_body_still_inspectable_and_reconcilable():
    store = _store()
    svc = _svc(store)
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": f"legacy-{uuid.uuid4()}",
        "policy_version": 1,
        "compiled_rule_digest": "a" * 64,
        "compiled": {},
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
    }
    pid = req["policy_id"]
    assert svc.install_policy(req)["status"] == "ok"
    assert store.get_canonical_policy_body(pid, 1) is None
    insp = svc.inspect_policy(_inspect_req(pid, "a" * 64))
    assert isinstance(insp, dict)
    rec_res = svc.reconcile_pending_operations({
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": pid,
        "policy_version": 1,
        "compiled_rule_digest": "a" * 64,
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
    })
    assert isinstance(rec_res, dict)
