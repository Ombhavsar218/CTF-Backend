"""N-02 canonical rule-schema-v1 validation tests (mock-only, real controller path)."""
import copy
import os
import tempfile
import uuid

import pytest

from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore

from broker.app.firewall_controller_contract import FirewallControllerRequestError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.rule_schema_v1 import (
    canonical_policy_digest,
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


def _svc(store=None):
    return FirewallControllerService(
        allowed_uids={1000},
        allowed_gids={1000},
        backend=authorized_backend(),
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


def _fresh_store():
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), "schema.db"))


def _install_req(pid=None, rules=None, **overrides):
    rules = [_base_rule()] if rules is None else rules
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": pid or f"p-{uuid.uuid4()}",
        "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(rules),
        "compiled": {},
        "rules": copy.deepcopy(rules),
        "required_families": sorted({r["family"] for r in rules}),
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
    }
    req.update(overrides)
    return req


def test_valid_tcp_and_udp_rules_install_via_controller():
    svc = _svc(_fresh_store())
    rules = [_base_rule(protocol="tcp"), _base_rule(protocol="udp", port_start=53, port_end=53, action="drop")]
    req = _install_req(rules=rules)
    res = svc.install_policy(req)
    assert res["status"] == "ok"
    assert req["rules"] == validate_and_normalize_rules(rules, sorted({r["family"] for r in rules}))


def test_invalid_protocol_and_icmp_rejected():
    svc = _svc(_fresh_store())
    for proto in ("icmp", "icmpv6", "sctp", "any"):
        with pytest.raises(FirewallControllerRequestError):
            svc.install_policy(_install_req(rules=[_base_rule(protocol=proto)]))


def test_missing_and_unknown_fields_rejected():
    svc = _svc(_fresh_store())
    missing = _base_rule()
    del missing["action"]
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(_install_req(rules=[missing]))
    unknown = _base_rule()
    unknown["extra"] = "x"
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(_install_req(rules=[unknown]))


def test_incorrect_types_and_port_boundaries_rejected():
    svc = _svc(_fresh_store())
    bad_cases = [
        _base_rule(port_start="80"),
        _base_rule(port_start=True),
        _base_rule(port_start=0),
        _base_rule(port_end=65536),
        _base_rule(port_end=79),
        _base_rule(action=True),
    ]
    for rule in bad_cases:
        with pytest.raises(FirewallControllerRequestError):
            svc.install_policy(_install_req(rules=[rule]))


def test_invalid_ip_cidr_and_family_mismatch_rejected():
    svc = _svc(_fresh_store())
    bad = [
        _base_rule(source_cidr="10.0.0.1/24"),  # host bits
        _base_rule(source_cidr="01.0.0.0/24"),
        _base_rule(source_cidr="10.0.0.0/0"),
        _base_rule(source_cidr="127.0.0.0/8"),
        _base_rule(family="ipv6", source_cidr="10.0.0.0/24", destination_cidr="2400:cb00:1::/48"),
        _base_rule(family="ipv6", source_cidr="2400:CB00:1::/48", destination_cidr="2400:cb00:2::/48"),
        _base_rule(family="ipv6", source_cidr="fe80::/10", destination_cidr="2400:cb00:2::/48"),
        _base_rule(family="ipv6", source_cidr="::ffff:10.0.0.0/96", destination_cidr="2400:cb00:2::/48"),
        _base_rule(family="ipv6", source_cidr="2001:db8:1::/48", destination_cidr="2400:cb00:2::/48"),  # documentation
    ]
    for rule in bad:
        with pytest.raises(FirewallControllerRequestError):
            svc.install_policy(_install_req(rules=[rule]))


def test_normalization_and_digest_stability_differentiation():
    r1 = _base_rule()
    n1 = validate_and_normalize_rules([r1], ["ipv4"])
    d1 = compiled_rule_digest(n1)
    d1b = compiled_rule_digest(validate_and_normalize_rules([copy.deepcopy(r1)], ["ipv4"]))
    assert d1 == d1b
    r2 = _base_rule(port_start=81, port_end=81)
    d2 = compiled_rule_digest(validate_and_normalize_rules([r2], ["ipv4"]))
    assert d1 != d2


def test_caller_controlled_identity_and_ownership_fields_rejected_in_rules():
    svc = _svc(_fresh_store())
    rule = _base_rule()
    rule["peer_uid"] = 1000
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(_install_req(rules=[rule]))


def test_compiled_digest_mismatch_rejected():
    svc = _svc(_fresh_store())
    req = _install_req()
    req["compiled_rule_digest"] = "b" * 64
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(req)


def test_duplicate_ambiguous_and_full_range_accept_rejected():
    svc = _svc(_fresh_store())
    r = _base_rule()
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(_install_req(rules=[r, copy.deepcopy(r)]))
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(_install_req(rules=[r, _base_rule(action="drop")]))
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(_install_req(rules=[_base_rule(port_start=1, port_end=65535, action="accept")]))
    # full range drop is permitted
    ok = _install_req(rules=[_base_rule(port_start=1, port_end=65535, action="drop")])
    assert _svc(_fresh_store()).install_policy(ok)["status"] == "ok"


def test_required_families_validation_and_ipv6_behavior():
    svc = _svc(_fresh_store())
    r6 = _base_rule(family="ipv6", source_cidr="2400:cb00:1::/48", destination_cidr="2400:cb00:2::/48")
    req = _install_req(rules=[r6], required_families=["ipv6"])
    req["compiled_rule_digest"] = compiled_rule_digest(validate_and_normalize_rules([r6], ["ipv6"]))
    assert svc.install_policy(req)["status"] == "ok"
    with pytest.raises(FirewallControllerRequestError):
        bad = _install_req(rules=[r6], required_families=["ipv4"])
        bad["compiled_rule_digest"] = "a" * 64
        svc.install_policy(bad)
