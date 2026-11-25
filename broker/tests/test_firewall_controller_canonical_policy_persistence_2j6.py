"""Phase 2L.2J.6 - canonical policy-body persistence and trusted read-back tests (mock-only)."""
import json
import os
import tempfile
import uuid

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


def _store():
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), "policy-body.db"))


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
    return req, norm


def _create_ownership(store, pid, version=1, digest=None, owner="i1", network="n1"):
    oid = str(uuid.uuid4())
    store.create_ownership({
        "ownership_record_id": oid,
        "policy_id": pid,
        "policy_version": version,
        "instance_id": owner,
        "network_id": network,
        "canonical_policy_digest": digest or ("a" * 64),
        "installation_state": "REQUESTED",
        "address_family": "ipv4",
    })
    return oid


def test_install_persists_canonical_policy_body_and_trusted_readback_succeeds():
    store = _store()
    svc = _svc(store)
    req, norm = _req(pid="p-body")
    assert svc.install_policy(req)["status"] == "ok"
    own, body = store.read_trusted_canonical_policy_body("p-body", 1)
    assert own["policy_id"] == "p-body"
    assert body["schema_version"] == "rule-schema-v1"
    assert body["rules"] == norm
    assert body["compiled_rule_digest"] == compiled_rule_digest(norm)


def test_store_rejects_canonical_body_digest_mismatch_on_write():
    store = _store()
    norm = validate_and_normalize_rules([_base_rule()], ["ipv4"])
    oid = _create_ownership(store, "p1", digest=compiled_rule_digest(norm))
    with pytest.raises(BrokerDBError):
        store.store_canonical_policy_body({
            "ownership_record_id": oid,
            "policy_id": "p1",
            "policy_version": 1,
            "schema_version": "rule-schema-v1",
            "rules": [_base_rule()],
            "required_families": ["ipv4"],
            "compiled_rule_digest": "f" * 64,
            "canonical_policy_digest": "f" * 64,
        })


def test_trusted_readback_fails_closed_on_corrupt_json_and_digest_mismatch():
    store = _store()
    norm = validate_and_normalize_rules([_base_rule()], ["ipv4"])
    digest = compiled_rule_digest(norm)
    oid = _create_ownership(store, "p1", digest=digest)
    store.store_canonical_policy_body({
        "ownership_record_id": oid,
        "policy_id": "p1",
        "policy_version": 1,
        "schema_version": "rule-schema-v1",
        "rules": [_base_rule()],
        "required_families": ["ipv4"],
        "compiled_rule_digest": digest,
        "canonical_policy_digest": digest,
    })
    # Corrupt JSON
    store.db.execute("UPDATE controller_policy_bodies SET canonical_rules_json=? WHERE policy_id=? AND policy_version=?", ("{bad", "p1", 1))
    with pytest.raises(BrokerDBError):
        store.read_trusted_canonical_policy_body("p1", 1)
    # Restore valid JSON but tamper stored digest
    store.db.execute(
        "UPDATE controller_policy_bodies SET canonical_rules_json=?, compiled_rule_digest=? WHERE policy_id=? AND policy_version=?",
        (json.dumps(norm, sort_keys=True, separators=(',', ':'), ensure_ascii=True), "0" * 64, "p1", 1),
    )
    with pytest.raises(BrokerDBError):
        store.read_trusted_canonical_policy_body("p1", 1)


def test_trusted_readback_fails_closed_on_owner_version_binding_mismatch():
    store = _store()
    norm = validate_and_normalize_rules([_base_rule()], ["ipv4"])
    digest = compiled_rule_digest(norm)
    oid = _create_ownership(store, "p1", version=1, digest=digest, owner="i1")
    store.store_canonical_policy_body({
        "ownership_record_id": oid,
        "policy_id": "p1",
        "policy_version": 1,
        "schema_version": "rule-schema-v1",
        "rules": [_base_rule()],
        "required_families": ["ipv4"],
        "compiled_rule_digest": digest,
        "canonical_policy_digest": digest,
    })
    with pytest.raises(BrokerDBError):
        store.read_trusted_canonical_policy_body("p1", 1, expected_owner_id="other-owner")
    with pytest.raises(BrokerDBError):
        store.read_trusted_canonical_policy_body("p1", 1, expected_ownership_record_id=str(uuid.uuid4()))
    with pytest.raises(BrokerDBError):
        store.read_trusted_canonical_policy_body("p1", 1, expected_compiled_rule_digest="b" * 64)


def test_trusted_readback_rejects_unsupported_schema_version():
    store = _store()
    norm = validate_and_normalize_rules([_base_rule()], ["ipv4"])
    digest = compiled_rule_digest(norm)
    oid = _create_ownership(store, "p1", digest=digest)
    store.store_canonical_policy_body({
        "ownership_record_id": oid,
        "policy_id": "p1",
        "policy_version": 1,
        "schema_version": "rule-schema-v1",
        "rules": [_base_rule()],
        "required_families": ["ipv4"],
        "compiled_rule_digest": digest,
        "canonical_policy_digest": digest,
    })
    store.db.execute("UPDATE controller_policy_bodies SET schema_version=? WHERE policy_id=? AND policy_version=?", ("rule-schema-v0", "p1", 1))
    with pytest.raises(BrokerDBError):
        store.read_trusted_canonical_policy_body("p1", 1)


def test_legacy_install_without_rules_does_not_require_canonical_body():
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
    assert svc.install_policy(req)["status"] == "ok"
    assert store.get_canonical_policy_body(req["policy_id"], 1) is None
