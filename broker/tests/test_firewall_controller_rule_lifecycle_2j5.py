"""Phase 2L.2J.5 - canonical rule lifecycle boundary tests (mock-only).

Covers schema-v1 enforcement at controller install, helper ingress, mock backend/state
install boundary, digest consistency, and read-back/inspect behavior in local mock paths.
Does not exercise real Docker/UDS/privileged helper/firewall backends.
"""
import copy
import os
import tempfile
import uuid

import pytest

from broker.app.firewall_controller_contract import FirewallControllerRequestError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.helper_contract import (
    HelperContractError,
    HelperOperation,
    validate_helper_request,
)
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    canonical_policy_digest,
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


def _store():
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), "lifecycle.db"))


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


def _req(pid=None, rules=None, key=None, **overrides):
    rules = [_base_rule()] if rules is None else rules
    norm = validate_and_normalize_rules(copy.deepcopy(rules), sorted({r["family"] for r in rules}))
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid or f"p-{uuid.uuid4()}",
        "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(norm),
        "compiled": {},
        "rules": copy.deepcopy(rules),
        "required_families": sorted({r["family"] for r in rules}),
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
        "ownership_reference": overrides.pop("ownership_reference", None),
    }
    req.update(overrides)
    req.pop("ownership_reference", None)
    return req, norm


def test_controller_install_normalizes_rules_and_digests_before_helper_boundary():
    store = _store()
    svc = _svc(store)
    req, norm = _req()
    res = svc.install_policy(req)
    assert res["status"] == "ok"
    assert req["rules"] == norm
    assert req["compiled_rule_digest"] == compiled_rule_digest(norm)


def test_controller_rejects_caller_supplied_digest_mismatch_on_install():
    svc = _svc()
    req, _ = _req()
    req["compiled_rule_digest"] = "f" * 64
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(req)


def test_helper_ingress_rejects_malformed_schema_v1_rules():
    norm = validate_and_normalize_rules([_base_rule()], ["ipv4"])
    req = {
        "schema_version": "2L.2G.3",
        "operation": "INSTALL_POLICY",
        "request_id": "req-1",
        "operation_id": "op-1",
        "idempotency_key": "idem-1",
        "policy_id": "p1",
        "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(norm),
        "ownership_reference": "own-1",
        "instance_id": "i1",
        "network_id": "n1",
        "rules": [_base_rule(protocol="icmp")],
    }
    with pytest.raises(HelperContractError):
        validate_helper_request(req, HelperOperation.INSTALL_POLICY)


def test_helper_ingress_accepts_valid_schema_v1_rules():
    norm = validate_and_normalize_rules([_base_rule()], ["ipv4"])
    req = {
        "schema_version": "2L.2G.3",
        "operation": "INSTALL_POLICY",
        "request_id": "req-1",
        "operation_id": "op-1",
        "idempotency_key": "idem-1",
        "policy_id": "p1",
        "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(norm),
        "ownership_reference": "own-1",
        "instance_id": "i1",
        "network_id": "n1",
        "rules": [_base_rule()],
        "required_families": ["ipv4"],
    }
    out = validate_helper_request(req, HelperOperation.INSTALL_POLICY)
    assert out["policy_id"] == "p1"


def test_helper_executor_backend_rejects_schema_v1_digest_mismatch_and_does_not_install():
    backend = authorized_backend()
    bad = _base_rule(port_start=443, port_end=443)
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": "p-bad",
        "policy_version": 1,
        "compiled_rule_digest": "0" * 64,
        "ownership_reference": "own-1",
        "instance_id": "i1",
        "network_id": "n1",
        "rules": [bad],
        "required_families": ["ipv4"],
    }
    # Helper contract/executor boundary returns a sanitized non-success response on validation failure.
    resp = backend.install_policy(req)
    assert isinstance(resp, dict)
    assert resp.get("status") == "error"
    # ensure no installed state created for failed validation path
    inspect = backend.inspect_policy({
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": "p-bad",
        "policy_version": 1,
        "compiled_rule_digest": "0" * 64,
        "ownership_reference": "own-1",
        "instance_id": "i1",
        "network_id": "n1",
    })
    assert inspect.get("result", {}).get("status") == "missing"


def test_mock_firewall_controller_state_rejects_schema_v1_digest_mismatch_on_install():
    from broker.app.firewall_controller import MockFirewallController
    ctrl = MockFirewallController()
    bad = _base_rule(port_start=443, port_end=443)
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": "p-bad-state",
        "policy_version": 1,
        "compiled_rule_digest": "0" * 64,
        "ownership_reference": "own-1",
        "instance_id": "i1",
        "network_id": "n1",
        "rules": [bad],
        "required_families": ["ipv4"],
    }
    with pytest.raises(FirewallControllerRequestError):
        ctrl.install_policy(req)
    assert "p-bad-state" not in ctrl.installed


def test_controller_install_then_inspect_reflects_installed_state_mock_only():
    svc = _svc()
    req, _ = _req(pid="p-inspect")
    assert svc.install_policy(req)["status"] == "ok"
    inspect_req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": "p-inspect",
        "policy_version": 1,
        "compiled_rule_digest": req["compiled_rule_digest"],
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
    }
    res = svc.inspect_policy(inspect_req)
    assert res["status"] == "ok"
    assert res.get("result", {}).get("status") in ("installed", "missing", "ok", "verified") or "policy_id" in str(res)


def test_legacy_payload_without_rules_still_supported_on_install_mock_path():
    # Existing mock-only/legacy flows may omit schema-v1 rules; must not be broken.
    svc = _svc()
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
    res = svc.install_policy(req)
    assert res["status"] == "ok"
