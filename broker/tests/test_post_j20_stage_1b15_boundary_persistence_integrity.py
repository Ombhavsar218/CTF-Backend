"""Post-J.20 Stage 1B.15 — legacy/canonical boundary and persistence integrity.

Mock-only deterministic verification. No Docker, UDS, SO_PEERCRED, privileged
helper, host firewall, live backend, cloud, or Stage 1C operations are performed.
"""
from __future__ import annotations

import json
import sqlite3
import uuid

import pytest

from broker.app.db import BrokerDB, BrokerDBError
from broker.app.firewall_controller import MockFirewallController
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import (
    FirewallControllerBackendError,
    FirewallControllerIdempotencyError,
    FirewallControllerRequestError,
)
from broker.firewall_controller_service.helper_contract import (
    HelperContractError,
    HelperOperation,
    SCHEMA_VERSION,
    validate_helper_request,
)
from broker.firewall_controller_service.ownership_store import (
    BrokerDBCanonicalError,
    ControllerOwnershipStore,
)
from broker.firewall_controller_service.rule_schema_v1 import (
    PROTOCOL_SCHEMA_VERSION,
    RULE_SCHEMA_VERSION,
    RuleSchemaError,
    compiled_rule_digest,
    validate_and_normalize_rules,
    validate_install_policy_rules,
)
from broker.tests._helper_identity import authorized_backend
from broker.tests.test_post_j20_stage_1b3_durable_crash_recovery import (
    _CountingBackend,
    _install_active,
    _installed,
    _op_req,
)

LEGACY_MARKERS = (
    "ip_version",
    "source_component",
    "targets",
    "dest_ip",
    "dest_subnet",
    "dest_port",
    "default_action",
    "rule_count",
)


def _rule(**overrides):
    rule = {
        "family": "ipv4",
        "direction": "ingress",
        "protocol": "tcp",
        "source_cidr": "10.0.0.0/24",
        "destination_cidr": "10.0.1.0/24",
        "port_start": 443,
        "port_end": 443,
        "action": "accept",
    }
    rule.update(overrides)
    return rule


def _digest_for(rules):
    return compiled_rule_digest(validate_and_normalize_rules(rules, required_families=["ipv4"]))


def _install_req(pid, key=None, *, rules=None, **overrides):
    rules = rules if rules is not None else [_rule()]
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid,
        "policy_version": 1,
        "compiled_rule_digest": _digest_for(rules),
        "compiled": {},
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
    }
    if rules is not None:
        req["rules"] = [dict(r) for r in rules]
        req["required_families"] = ["ipv4"]
    req.update(overrides)
    return req


def _legacy_compiled(pid, digest="a" * 64):
    return {
        "policy_id": pid,
        "rules": [{
            "policy_id": pid,
            "instance_id": "i1",
            "source_component": "broker",
            "direction": "egress",
            "ip_version": "ipv4",
            "protocol": "tcp",
            "network_id": "n1",
            "dest_ip": "10.0.0.5",
            "dest_subnet": None,
            "dest_port": 443,
            "action": "ACCEPT",
            "default_action": "DROP",
        }],
        "compiled_rule_digest": digest,
        "rule_count": 1,
        "canonical": "legacy-flat-rule-json",
    }


def _svc(store, backend=None):
    return FirewallControllerService(
        allowed_uids={1000},
        allowed_gids={1000},
        ownership_store=store,
        backend=backend or _CountingBackend(authorized_backend()),
    )


def _assert_no_install_side_effects(store, pid, key):
    assert store.get_by_policy(pid, 1) is None
    assert store.get_idempotency_record(key, "install_policy") is None
    assert store.get_canonical_policy_body(pid, 1) is None


# --- Boundary: fail closed on mixed/legacy representations -----------------

def test_service_rejects_mixed_canonical_rules_with_legacy_flat_fields(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "mixed-fields.db"))
    svc = _svc(store)
    req = _install_req(
        "b15-mixed-fields",
        ip_version="ipv4",
        source_component="broker",
        targets=[{"network_id": "n1", "ip": "10.0.0.5"}],
    )
    key = req["idempotency_key"]

    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(req)

    _assert_no_install_side_effects(store, "b15-mixed-fields", key)


def test_service_rejects_legacy_compiled_rules_before_persistence(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "legacy-compiled.db"))
    svc = _svc(store)
    req = _install_req(
        "b15-legacy-compiled",
        rules=None,
        compiled_rule_digest="a" * 64,
        compiled=_legacy_compiled("b15-legacy-compiled"),
    )
    req.pop("rules", None)
    req.pop("required_families", None)
    key = req["idempotency_key"]

    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(req)

    _assert_no_install_side_effects(store, "b15-legacy-compiled", key)


def test_mock_adapter_rejects_legacy_compiled_rules_before_state_change():
    c = MockFirewallController()
    req = _install_req(
        "b15-adapter-legacy",
        rules=None,
        compiled_rule_digest="a" * 64,
        compiled=_legacy_compiled("b15-adapter-legacy"),
    )
    req.pop("rules", None)
    req.pop("required_families", None)

    with pytest.raises(FirewallControllerRequestError):
        c.install_policy(req)

    assert "b15-adapter-legacy" not in c.installed
    assert req["compiled_rule_digest"] not in c.verified


def test_mock_adapter_rejects_mixed_canonical_and_legacy_fields():
    c = MockFirewallController()
    req = _install_req("b15-adapter-mixed", ip_version="ipv4", dest_ip="10.0.0.5")

    with pytest.raises(FirewallControllerRequestError):
        c.install_policy(req)

    assert "b15-adapter-mixed" not in c.installed


def test_schema_v1_compiled_mirror_without_top_level_rules_is_rejected():
    req = {
        "compiled": {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "rules": [_rule()],
        }
    }
    with pytest.raises(RuleSchemaError):
        validate_install_policy_rules(req)


def test_helper_contract_independently_rejects_legacy_compiled_shape():
    req = {
        "schema_version": SCHEMA_VERSION,
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": "b15-helper-legacy",
        "policy_version": 1,
        "compiled_rule_digest": "a" * 64,
        "ownership_reference": "oid-helper",
        "compiled": _legacy_compiled("b15-helper-legacy"),
    }
    with pytest.raises(HelperContractError):
        validate_helper_request(req, HelperOperation.INSTALL_POLICY)


def test_install_paths_do_not_bypass_schema_validator(monkeypatch, tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "validator-bypass.db"))
    svc = _svc(store)
    req = _install_req("b15-validator-service")
    key = req["idempotency_key"]

    def _patched(*args, **kwargs):
        raise RuleSchemaError("VALIDATOR_BYPASS_SENTINEL", "validator invoked")

    monkeypatch.setattr(
        "broker.firewall_controller_service.controller_service.validate_install_policy_rules",
        _patched,
    )
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(req)
    _assert_no_install_side_effects(store, "b15-validator-service", key)

    monkeypatch.setattr(
        "broker.firewall_controller_service.rule_schema_v1.validate_install_policy_rules",
        _patched,
    )
    adapter = MockFirewallController()
    adapter_req = _install_req("b15-validator-adapter")
    with pytest.raises(FirewallControllerRequestError):
        adapter.install_policy(adapter_req)
    assert "b15-validator-adapter" not in adapter.installed


# --- Boundary: representation stays separate through read/reconcile --------

def test_legacy_no_rules_install_stays_compatible_without_canonical_body(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "legacy-no-rules.db"))
    svc = _svc(store)
    req = _install_req("b15-legacy-ok", rules=None, compiled_rule_digest="a" * 64)
    req.pop("rules", None)
    req.pop("required_families", None)

    res = svc.install_policy(req)

    assert res["status"] == "ok"
    rec = store.get_by_policy("b15-legacy-ok", 1)
    assert rec is not None
    assert rec["canonical_policy_digest"] == "a" * 64
    assert store.get_canonical_policy_body("b15-legacy-ok", 1) is None
    inspect = svc.inspect_policy(_op_req("b15-legacy-ok", "a" * 64))
    assert inspect["status"] == "ok"
    assert "canonical_policy" not in json.dumps(inspect)


def test_canonical_body_persists_with_only_schema_v1_rule_fields(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "canonical-body.db"))
    svc = _svc(store)
    req = _install_req("b15-canonical-body")
    assert svc.install_policy(req)["status"] == "ok"

    body = store.get_canonical_policy_body("b15-canonical-body", 1)
    assert body is not None
    assert body["schema_version"] == RULE_SCHEMA_VERSION
    rules = json.loads(body["canonical_rules_json"])
    assert rules == validate_and_normalize_rules([_rule()], required_families=["ipv4"])
    assert not any(marker in body["canonical_rules_json"] for marker in LEGACY_MARKERS)

    _own, info = store.read_trusted_canonical_policy_body("b15-canonical-body", 1)
    assert info["schema_version"] == RULE_SCHEMA_VERSION
    assert info["rules"] == rules


def test_no_legacy_to_canonical_conversion_on_readback_or_reconcile(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "no-conversion.db"))
    svc = _svc(store)
    req = _install_req("b15-no-conversion", rules=None, compiled_rule_digest="a" * 64)
    req.pop("rules", None)
    req.pop("required_families", None)
    assert svc.install_policy(req)["status"] == "ok"

    inspect = svc.inspect_policy(_op_req("b15-no-conversion", "a" * 64))
    reconcile = svc.reconcile_pending_operations(_op_req("b15-no-conversion", "a" * 64))

    assert "canonical_policy" not in json.dumps(inspect)
    assert "canonical_policy" not in json.dumps(reconcile)
    assert store.get_canonical_policy_body("b15-no-conversion", 1) is None
    assert store.db.query(
        "SELECT COUNT(*) AS n FROM firewall_policies WHERE policy_id=?",
        ("b15-no-conversion",),
    )[0]["n"] == 0


def test_reconciliation_does_not_downgrade_persisted_canonical_body(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "reconcile-canonical.db"))
    svc = _svc(store)
    digest = _installed(store, svc, "b15-reconcile-canonical")
    before = store.get_canonical_policy_body("b15-reconcile-canonical", 1)

    res = svc.reconcile_pending_operations(_op_req("b15-reconcile-canonical", digest))

    after = store.get_canonical_policy_body("b15-reconcile-canonical", 1)
    assert res["status"] == "ok"
    assert after == before
    assert after["schema_version"] == RULE_SCHEMA_VERSION
    assert not any(marker in json.dumps(res) for marker in LEGACY_MARKERS)


# --- Persistence integrity -------------------------------------------------

def test_canonical_body_digest_tamper_fails_closed(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "digest-tamper.db"))
    svc = _svc(store)
    digest = _installed(store, svc, "b15-digest-tamper")
    store.db.execute(
        "UPDATE controller_policy_bodies SET compiled_rule_digest=? WHERE policy_id=? AND policy_version=?",
        ("b" * 64, "b15-digest-tamper", 1),
    )

    with pytest.raises(FirewallControllerRequestError):
        svc.inspect_policy(_op_req("b15-digest-tamper", digest))
    with pytest.raises(BrokerDBCanonicalError) as exc:
        store.read_trusted_canonical_policy_body("b15-digest-tamper", 1)
    assert exc.value.category == BrokerDBCanonicalError.INTEGRITY


def test_canonical_body_ownership_binding_tamper_fails_closed(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "owner-tamper.db"))
    svc = _svc(store)
    digest = _installed(store, svc, "b15-owner-tamper")
    store.db.execute(
        "UPDATE controller_policy_bodies SET ownership_record_id=? WHERE policy_id=? AND policy_version=?",
        ("forged-owner", "b15-owner-tamper", 1),
    )

    with pytest.raises(PermissionError):
        svc.inspect_policy(_op_req("b15-owner-tamper", digest))
    with pytest.raises(BrokerDBCanonicalError) as exc:
        store.read_trusted_canonical_policy_body("b15-owner-tamper", 1)
    assert exc.value.category == BrokerDBCanonicalError.OWNERSHIP


def test_canonical_body_requires_authoritative_ownership_binding(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "owner-required.db"))
    rec = {
        "policy_id": "b15-owner-required",
        "policy_version": 1,
        "ownership_record_id": "missing-owner",
        "rules": [_rule()],
        "required_families": ["ipv4"],
        "compiled_rule_digest": _digest_for([_rule()]),
    }
    with pytest.raises(BrokerDBCanonicalError) as exc:
        store.store_canonical_policy_body(rec)
    assert exc.value.category == BrokerDBCanonicalError.OWNERSHIP
    assert store.get_canonical_policy_body("b15-owner-required", 1) is None


def test_evidence_binding_rejects_mismatched_authority(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "evidence-binding.db"))
    svc = _svc(store)
    digest = _install_active(store, svc, "b15-evidence-binding")
    rec = store.get_by_policy("b15-evidence-binding", 1)

    assert svc._find_valid_verification_evidence(rec) is not None
    bad_digest = dict(rec, canonical_policy_digest="c" * 64)
    bad_owner = dict(rec, ownership_record_id="forged-owner")
    bad_family = dict(rec, address_family="ipv6")
    assert svc._find_valid_verification_evidence(bad_digest) is None
    assert svc._find_valid_verification_evidence(bad_owner) is None
    assert svc._find_valid_verification_evidence(bad_family) is None
    assert digest == rec["canonical_policy_digest"]


def test_append_only_history_evidence_and_audit_reject_mutation(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "append-only.db"))
    svc = _svc(store)
    _install_active(store, svc, "b15-append-only")
    oid = store.get_by_policy("b15-append-only", 1)["ownership_record_id"]
    store.record_audit("test_event", {"policy_id": "b15-append-only"}, {}, oid)

    cases = (
        ("UPDATE controller_lifecycle_history SET new_state=? WHERE ownership_record_id=?", ("FORGED", oid)),
        ("DELETE FROM controller_lifecycle_history WHERE ownership_record_id=?", (oid,)),
        ("UPDATE controller_evidence SET verification_result=? WHERE ownership_record_id=?", ("forged", oid)),
        ("DELETE FROM controller_evidence WHERE ownership_record_id=?", (oid,)),
        ("UPDATE controller_audit SET event_type=? WHERE ownership_record_id=?", ("forged", oid)),
        ("DELETE FROM controller_audit WHERE ownership_record_id=?", (oid,)),
    )
    for sql, params in cases:
        with pytest.raises(BrokerDBError):
            store.db.execute(sql, params)

    assert store.get_lifecycle_history(oid)
    assert store.get_evidence_by_ownership(oid)
    assert store._query_dicts(
        "SELECT * FROM controller_audit WHERE ownership_record_id=?", (oid,)
    )


def test_canonical_body_is_not_append_only_but_trusted_read_detects_tamper(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "body-not-append-only.db"))
    svc = _svc(store)
    _installed(store, svc, "b15-body-tamper")

    altered = [_rule(destination_cidr="10.0.2.0/24")]
    store.db.execute(
        "UPDATE controller_policy_bodies SET canonical_rules_json=? WHERE policy_id=? AND policy_version=?",
        (json.dumps(altered), "b15-body-tamper", 1),
    )
    body = store.get_canonical_policy_body("b15-body-tamper", 1)
    assert json.loads(body["canonical_rules_json"]) == altered

    with pytest.raises(BrokerDBCanonicalError) as exc:
        store.read_trusted_canonical_policy_body("b15-body-tamper", 1)
    assert exc.value.category == BrokerDBCanonicalError.INTEGRITY


def test_corrupt_stored_idempotency_digest_fails_closed_without_new_side_effects(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "idempotency-corrupt.db"))
    svc = _svc(store)
    req = _install_req("b15-idem-corrupt")
    key = req["idempotency_key"]
    assert svc.install_policy(req)["status"] == "ok"
    store.db.execute(
        "UPDATE controller_idempotency SET request_digest=? WHERE idempotency_key=? AND operation_type=?",
        ("corrupt-digest", key, "install_policy"),
    )
    state_before = store.get_by_policy("b15-idem-corrupt", 1)

    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(req)

    assert store.get_by_policy("b15-idem-corrupt", 1) == state_before
    assert len(store._query_dicts(
        "SELECT * FROM controller_idempotency WHERE idempotency_key=? AND operation_type=?",
        (key, "install_policy"),
    )) == 1


def test_idempotency_completion_cas_rejects_stale_outcome(tmp_path):
    store = ControllerOwnershipStore(db_path=str(tmp_path / "idempotency-cas.db"))
    key = "b15-cas-key"
    store.create_idempotency_record(
        key, "install_policy", "a" * 64,
        resource_key="b15-cas-policy:1",
        operation_outcome="SUCCEEDED",
    )

    completed = store.complete_idempotency_record(
        key, "install_policy", "{}",
        operation_outcome="FAILED",
        expected_outcomes=("IN_PROGRESS",),
    )

    assert completed is False
    row = store.get_idempotency_record(key, "install_policy")
    assert row["status"] == "PENDING"
    assert row["operation_outcome"] == "SUCCEEDED"


def test_foreign_key_enforcement_is_controller_scoped_not_global(tmp_path):
    path = str(tmp_path / "fk-scope.db")
    store = ControllerOwnershipStore(db_path=path)

    conn = store._get_conn_fk()
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()
    raw = store.db._get_conn()
    try:
        assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    finally:
        raw.close()

    values = (
        "pb-fk-missing", "forged-owner", "b15-fk-missing", 1,
        RULE_SCHEMA_VERSION,
        json.dumps([_rule()]), json.dumps(["ipv4"]),
        _digest_for([_rule()]), "a" * 64, "test", "req", "op",
    )
    sql = (
        "INSERT INTO controller_policy_bodies "
        "(policy_body_id, ownership_record_id, policy_id, policy_version, schema_version, "
        "canonical_rules_json, required_families_json, compiled_rule_digest, "
        "canonical_policy_digest, controller_identity, request_id, operation_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    with pytest.raises(BrokerDBError):
        store._execute_fk(sql, values)
    assert store.get_canonical_policy_body("b15-fk-missing", 1) is None

    # Base BrokerDB connections do not enable foreign keys; this is recorded as a
    # partial control, not treated as a global persistence guarantee.
    store.db.execute(sql, values)
    assert store.get_canonical_policy_body("b15-fk-missing", 1) is not None
    with pytest.raises(BrokerDBCanonicalError):
        store.read_trusted_canonical_policy_body("b15-fk-missing", 1)


def test_schema_version_and_additive_idempotency_migration_are_preserved(tmp_path):
    path = str(tmp_path / "schema-migration.db")
    BrokerDB(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("DROP TABLE IF EXISTS controller_idempotency")
        conn.execute(
            "CREATE TABLE controller_idempotency ("
            "idempotency_key TEXT NOT NULL, operation_type TEXT NOT NULL, "
            "request_digest TEXT NOT NULL, resource_key TEXT, ownership_record_id TEXT, "
            "status TEXT NOT NULL DEFAULT 'PENDING', lifecycle_state TEXT, "
            "response_json TEXT, recovery_meta_json TEXT, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "completed_at TIMESTAMP, PRIMARY KEY (idempotency_key, operation_type))"
        )
        conn.execute(
            "INSERT INTO controller_idempotency "
            "(idempotency_key, operation_type, request_digest, resource_key, status) "
            "VALUES (?,?,?,?,?)",
            ("legacy-key", "install_policy", "a" * 64, "p:1", "COMPLETED"),
        )
        conn.commit()
    finally:
        conn.close()

    store = ControllerOwnershipStore(db_path=path)
    columns = {row[1] for row in store.db.query("PRAGMA table_info(controller_idempotency)")}
    assert {"operation_outcome", "outcome_updated_at"}.issubset(columns)
    row = store.get_idempotency_record("legacy-key", "install_policy")
    assert row is not None
    assert row["status"] == "COMPLETED"
    assert row["operation_outcome"] is None
    assert any(r["version"] == 1 for r in store.db.query("SELECT version FROM schema_version"))
