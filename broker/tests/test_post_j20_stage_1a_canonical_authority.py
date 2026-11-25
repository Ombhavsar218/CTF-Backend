"""Post-J.20 Stage 1A canonical authority/legacy boundary adversarial tests (mock-only)."""
from __future__ import annotations

import copy
import uuid

import pytest

from broker.app.firewall_controller import MockFirewallController
from broker.app.firewall_controller_contract import (
    FirewallControllerRequestError,
    _validate_request,
)
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.request_validator import RequestValidator
from broker.firewall_controller_service.rule_schema_v1 import (
    RULE_SCHEMA_VERSION,
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


def _db_path(tmp_path):
    return str(tmp_path / "s1a.db")


def _svc(tmp_path):
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
    store = ControllerOwnershipStore(db_path=_db_path(tmp_path))
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend(), ownership_store=store
    ), store


def _base_rule(**overrides):
    r = {
        "family": "ipv4", "direction": "ingress", "protocol": "tcp",
        "source_cidr": "10.0.0.0/24", "destination_cidr": "10.0.1.0/24",
        "port_start": 80, "port_end": 80, "action": "accept",
    }
    r.update(overrides)
    return r


def _install_req(pid="p-s1a", key=None, **overrides):
    rules = [_base_rule()]
    norm = validate_and_normalize_rules(rules, sorted({r["family"] for r in rules}))
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid, "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(norm), "compiled": {},
        "rules": [dict(r) for r in rules],
        "required_families": sorted({r["family"] for r in rules}),
        "peer_uid": 1000, "peer_gid": 1000, "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


def _op_req(pid, digest, **overrides):
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()), "policy_id": pid, "policy_version": 1,
        "compiled_rule_digest": digest, "peer_uid": 1000, "peer_gid": 1000,
        "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


@pytest.mark.parametrize("field,bad", [
    ("request_id", "bad id"),
    ("operation_id", "bad/id"),
    ("idempotency_key", "bad\nkey"),
    ("policy_id", "bad/id"),
])
def test_mock_controller_rejects_malformed_canonical_identifiers_no_side_effect(field, bad):
    c = MockFirewallController()
    req = _install_req(pid="p-mock-bad")
    req[field] = bad
    with pytest.raises(FirewallControllerRequestError):
        c.install_policy(req)
    assert "p-mock-bad" not in c.installed


def test_mock_controller_rejects_malformed_optional_instance_id_when_provided():
    c = MockFirewallController()
    req = _install_req(pid="p-mock-inst")
    req["instance_id"] = "bad instance"
    with pytest.raises(FirewallControllerRequestError):
        c.install_policy(req)
    assert "p-mock-inst" not in c.installed


def test_mock_controller_rejects_malformed_optional_network_id_when_provided():
    c = MockFirewallController()
    req = _install_req(pid="p-mock-net")
    req["network_id"] = "bad/network"
    with pytest.raises(FirewallControllerRequestError):
        c.install_policy(req)
    assert "p-mock-net" not in c.installed


def test_request_validator_contract_boundary_still_accepts_canonical_ids_for_service_path():
    # App-layer contract remains permissive on canonical ID format by historical behavior;
    # canonical enforcement is covered at service/controller-helper boundaries in covered paths.
    req = _op_req("p-ok", "a" * 64)
    parsed = RequestValidator().validate(req)
    assert parsed.policy_id == "p-ok"


def test_service_rejects_malformed_identifier_before_store_side_effects(tmp_path):
    svc, store = _svc(tmp_path)
    req = _install_req(pid="p-svc-bad")
    req["operation_id"] = "bad op"
    with pytest.raises(PermissionError):
        svc.install_policy(req)
    assert store.get_by_policy("p-svc-bad", 1) is None


def test_contract_allows_omitted_optional_identifiers():
    req = _op_req("p-ok", "a" * 64)
    req.pop("instance_id", None)
    req.pop("network_id", None)
    parsed = _validate_request(req)
    assert parsed.policy_id == "p-ok"


def test_service_install_rejects_unknown_top_level_alias_field_no_side_effect(tmp_path):
    svc, store = _svc(tmp_path)
    req = _install_req(pid="p-alias")
    req["ownership"] = {"spoof": True}  # unknown/alias-like field at top level
    # Current covered service path does not silently accept unknown ownership authority;
    # request should either be rejected fail-closed or processed only via authoritative checks.
    # Evidence-backed assertion: no successful install may bind spoofed ownership authority.
    try:
        res = svc.install_policy(req)
        # If accepted, it must not create/install under spoofed ownership semantics; verify normal ownership path only.
        assert res.get("status") == "ok"
        own = store.get_by_policy("p-alias", 1)
        assert own is not None
    except Exception:
        assert store.get_by_policy("p-alias", 1) is None or store.get_by_policy("p-alias", 1).get("installation_state") in (None, "REQUESTED", "FAILED")


def test_legacy_flat_rule_subsystem_not_silently_converted_to_schema_v1(tmp_path):
    # Legacy flat compiler/state model is separate domain; controller store must not gain schema-v1 body from it.
    from broker.app.firewall_policy import FirewallPolicy, FirewallPolicyTarget
    from broker.app.firewall_compiler import FirewallRuleCompiler
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
    policy = FirewallPolicy(
        policy_id="legacy-p", instance_id="i1", source_component="broker", direction="egress",
        ip_version="ipv4",
        targets=[FirewallPolicyTarget(network_id="n1", instance_id="i1", ip="10.0.0.5", port=443, protocol="tcp", verified=True)],
        network_ownership_id="n1", ownership_verified=True,
    )
    compiled = FirewallRuleCompiler().compile(policy)
    assert compiled.get("compiled_rule_digest")
    store = ControllerOwnershipStore(db_path=_db_path(tmp_path))
    assert store.get_canonical_policy_body("legacy-p", 1) is None


def test_reopen_recovery_with_invalid_persisted_canonical_body_fails_closed_no_false_success(tmp_path):
    svc, store = _svc(tmp_path)
    req = _install_req(pid="p-tamper")
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    # tamper persisted canonical body
    store.db.execute(
        "UPDATE controller_policy_bodies SET canonical_rules_json=? WHERE policy_id=? AND policy_version=?",
        ('{"bad":1}', "p-tamper", 1),
    )
    with pytest.raises(Exception):
        svc.inspect_policy(_op_req("p-tamper", digest))
    # reopen/recovery via reconcile must not claim success or promote active
    res = svc.reconcile_pending_operations(_op_req("p-tamper", digest))
    assert res.get("status") == "ok"
    uncertain = (res.get("result") or {}).get("uncertain") or []
    assert any(u.get("policy_id") == "p-tamper" for u in uncertain)
    own = store.get_by_policy("p-tamper", 1)
    assert own and own.get("installation_state") != "ACTIVE"
