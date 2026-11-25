"""Post-J.20 Stage 1B.13 — universal canonical validation and bounded error sanitization (mock-only).

Focused tests for invalid/noncanonical identifiers, validation-before-side-effects,
request/policy binding rejects, alias/malformed inputs, backend/schema leakage
sentinels, persistence error classification, bounded outward errors, and preserved
contracts/compatibility. No Docker/host/transport/privileged operations.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid

import pytest

from broker.app.db import BrokerDBError
from broker.app.firewall_controller import MockFirewallController
from broker.app.firewall_controller_contract import (
    FirewallControllerIdempotencyError,
    FirewallControllerRequestError,
    _validate_request,
)
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import (
    FirewallControllerBackendError,
    FirewallControllerPersistenceError,
)
from broker.firewall_controller_service.ownership_store import (
    BrokerDBCanonicalError,
    ControllerOwnershipStore,
)
from broker.firewall_controller_service.request_validator import RequestValidator
from broker.firewall_controller_service.rule_schema_v1 import (
    RuleSchemaError,
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend

BACKEND_SENTINEL = "SENTINEL_BACKEND_1B13_LEAK"
SCHEMA_SENTINEL = "SENTINEL_SCHEMA_1B13_LEAK"
PERSIST_SENTINEL = "SENTINEL_PERSIST_1B13_LEAK"
CANON_SENTINEL = "SENTINEL_CANON_1B13_LEAK"


def _db_path(tmp_path, name="s1b13.db"):
    return str(tmp_path / name)


def _store(tmp_path, name="s1b13.db"):
    return ControllerOwnershipStore(db_path=_db_path(tmp_path, name))


def _svc(store, backend=None):
    return FirewallControllerService(
        allowed_uids={1000},
        allowed_gids={1000},
        ownership_store=store,
        backend=backend or authorized_backend(),
    )


def _base_rule(**overrides):
    r = {
        "family": "ipv4",
        "direction": "ingress",
        "protocol": "tcp",
        "source_cidr": "10.13.0.0/24",
        "destination_cidr": "10.13.1.0/24",
        "port_start": 443,
        "port_end": 443,
        "action": "accept",
    }
    r.update(overrides)
    return r


def _install_req(pid="p1b13", ver=1, key=None, **overrides):
    rules = [_base_rule()]
    norm = validate_and_normalize_rules(rules, sorted({r["family"] for r in rules}))
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid,
        "policy_version": ver,
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


def _op_req(base, **overrides):
    req = dict(base)
    req["request_id"] = str(uuid.uuid4())
    req["operation_id"] = str(uuid.uuid4())
    req["idempotency_key"] = str(uuid.uuid4())
    req.update(overrides)
    return req


def _assert_no_sentinel(obj, sentinel):
    text = repr(obj)
    assert sentinel not in text, f"sentinel leaked: {sentinel}"


class _CountingStore:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if callable(attr):
            def wrapped(*args, **kwargs):
                self.calls.append(name)
                return attr(*args, **kwargs)
            return wrapped
        return attr


class _CountingBackend:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if callable(attr):
            def wrapped(*args, **kwargs):
                self.calls.append(name)
                return attr(*args, **kwargs)
            return wrapped
        return attr


class _LeakyBackend:
    def __init__(self, inner=None):
        self.inner = inner or authorized_backend()

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if callable(attr):
            def wrapped(*args, **kwargs):
                if name in ("install_policy", "inspect_policy", "verify_policy", "revoke_policy", "remove_stale_policy", "health_check"):
                    raise RuntimeError(BACKEND_SENTINEL)
                return attr(*args, **kwargs)
            return wrapped
        return attr


class _LeakyErrorBackend:
    """Return ok=False with sentinel-bearing error_message (no exception raise)."""
    def __init__(self, inner=None):
        self.inner = inner or authorized_backend()

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if callable(attr):
            def wrapped(*args, **kwargs):
                if name == "inspect_policy":
                    return {"status": "error", "error_code": "BACKEND_ERROR", "error_message": BACKEND_SENTINEL, "result": {}}
                return attr(*args, **kwargs)
            return wrapped
        return attr


# --- invalid/noncanonical identifiers + validation before side effects ---

@pytest.mark.parametrize("field,bad", [
    ("policy_id", "bad\nid"),
    ("policy_id", "bad\rid"),
    ("policy_id", " bad"),
    ("policy_id", "bad "),
    ("policy_id", ["p"]),
    ("policy_id", 123),
    ("request_id", "req\n1"),
    ("operation_id", "op\t1"),
    ("idempotency_key", "k\x001"),
])
def test_service_rejects_noncanonical_identifiers_before_side_effects(tmp_path, field, bad):
    inner_store = _store(tmp_path, f"id-{field}.db")
    store = _CountingStore(inner_store)
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    req = _install_req(pid="valid-pid")
    req[field] = bad
    with pytest.raises(Exception) as exc:
        svc.install_policy(req)
    _assert_no_sentinel(exc.value, "traceback")
    # No ownership/idempotency/audit side effects and no backend dispatch.
    assert inner_store.list_ownerships() == []
    assert inner_store.get_lifecycle_history() == []
    assert backend.calls == []


def test_service_rejects_invalid_optional_identifier_before_side_effects(tmp_path):
    inner_store = _store(tmp_path, "opt.db")
    store = _CountingStore(inner_store)
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    req = _install_req(pid="valid-pid", instance_id="bad\ninst")
    with pytest.raises(Exception):
        svc.install_policy(req)
    assert inner_store.list_ownerships() == []
    assert backend.calls == []


# --- request/policy binding validation (no side effects) ---

def test_service_rejects_policy_binding_mismatch_before_mutation(tmp_path):
    store = _store(tmp_path, "bind.db")
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    req = _install_req(pid="bind-p")
    assert svc.install_policy(req)["status"] == "ok"
    # try inspect with mismatched digest/version binding
    bad = _op_req(req, compiled_rule_digest="f" * 64)
    before = list(store.get_lifecycle_history())
    with pytest.raises(Exception):
        svc.inspect_policy(bad)
    after = list(store.get_lifecycle_history())
    assert len(after) == len(before)


# --- alias / malformed-input fail-closed ---

@pytest.mark.parametrize("mutator", [
    lambda r: r.update({"rules": "not-a-list"}) or r,
    lambda r: r.update({"compiled_rule_digest": "not-a-digest"}) or r,
    lambda r: r.update({"policy_version": -1}) or r,
    lambda r: r.update({"policy_version": "1"}) or r,
    lambda r: r.update({"policy_version": True}) or r,
])
def test_malformed_inputs_fail_closed_without_side_effects(tmp_path, mutator):
    inner_store = _store(tmp_path, "mal.db")
    store = _CountingStore(inner_store)
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    req = _install_req(pid="mal-p")
    mutator(req)
    with pytest.raises(Exception):
        svc.install_policy(req)
    assert inner_store.list_ownerships() == []
    assert backend.calls == []


# --- schema exception-message leakage (service + app controller + request validator) ---

def test_service_schema_error_does_not_leak_raw_message(tmp_path, monkeypatch):
    store = _store(tmp_path, "schema.db")
    svc = _svc(store)

    def boom(*args, **kwargs):
        raise RuleSchemaError("INVALID_RULE", SCHEMA_SENTINEL)

    monkeypatch.setattr(
        "broker.firewall_controller_service.controller_service.validate_install_policy_rules",
        boom,
    )
    req = _install_req(pid="schema-p")
    with pytest.raises(FirewallControllerRequestError) as exc:
        svc.install_policy(req)
    assert exc.value.error_code == "REQUEST_INVALID"
    _assert_no_sentinel(exc.value, SCHEMA_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "message", ""), SCHEMA_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "details", {}), SCHEMA_SENTINEL)


def test_app_controller_schema_error_does_not_leak_raw_message(monkeypatch):
    ctrl = MockFirewallController()

    def boom(*args, **kwargs):
        raise RuleSchemaError("INVALID_RULE", SCHEMA_SENTINEL)

    monkeypatch.setattr(
        "broker.firewall_controller_service.rule_schema_v1.validate_install_policy_rules",
        boom,
    )
    req = _install_req(pid="app-schema")
    with pytest.raises(FirewallControllerRequestError) as exc:
        ctrl.install_policy(req)
    assert exc.value.error_code == "REQUEST_INVALID"
    _assert_no_sentinel(exc.value, SCHEMA_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "message", ""), SCHEMA_SENTINEL)


def test_request_validator_does_not_leak_raw_internal_exception(monkeypatch):
    rv = RequestValidator()

    def boom(req):
        raise ValueError(SCHEMA_SENTINEL)

    monkeypatch.setattr("broker.firewall_controller_service.request_validator._validate_request", boom)
    with pytest.raises(FirewallControllerRequestError) as exc:
        rv.validate({})
    assert exc.value.error_code == "REQUEST_INVALID"
    _assert_no_sentinel(exc.value, SCHEMA_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "message", ""), SCHEMA_SENTINEL)


# --- backend exception-message leakage ---

def test_service_backend_exception_does_not_leak_sentinel(tmp_path):
    store = _store(tmp_path, "be.db")
    svc = _svc(store, backend=_LeakyBackend())
    req = _install_req(pid="be-p")
    # install path: backend called during dispatch; sentinel-bearing internal exception must not leak
    # and must retain the established bounded backend-error class contract.
    with pytest.raises(FirewallControllerBackendError) as exc:
        svc.install_policy(req)
    assert str(exc.value) == "Backend operation failed"
    _assert_no_sentinel(exc.value, BACKEND_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "args", ()), BACKEND_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "message", ""), BACKEND_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "details", {}), BACKEND_SENTINEL)


# --- persistence error classification and no storage-failure -> validation conversion ---

def test_persistence_failure_is_not_reported_as_request_validation(tmp_path):
    store = _store(tmp_path, "persist.db")
    svc = _svc(store)

    def boom(*args, **kwargs):
        raise BrokerDBError(PERSIST_SENTINEL)

    store.create_idempotency_record = boom  # force persistence failure at a persistence boundary
    req = _install_req(pid="persist-p")
    with pytest.raises(Exception) as exc:
        svc.install_policy(req)
    assert not isinstance(exc.value, FirewallControllerRequestError)
    # Must be classified as persistence/storage failure, not validation, and must not leak sentinel.
    assert isinstance(exc.value, (FirewallControllerPersistenceError, BrokerDBError))
    assert not isinstance(exc.value, FirewallControllerRequestError)
    _assert_no_sentinel(exc.value, PERSIST_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "args", ()), PERSIST_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "message", ""), PERSIST_SENTINEL)
    _assert_no_sentinel(getattr(exc.value, "details", {}), PERSIST_SENTINEL)


def test_canonical_sanitization_preserves_categories_without_leakage():
    svc = _svc(_store_pathless())

    with pytest.raises(PermissionError) as own:
        svc._sanitize_canonical_policy_error(BrokerDBCanonicalError(CANON_SENTINEL, BrokerDBCanonicalError.OWNERSHIP))
    _assert_no_sentinel(own.value, CANON_SENTINEL)

    with pytest.raises(FirewallControllerRequestError) as integ:
        svc._sanitize_canonical_policy_error(BrokerDBCanonicalError(CANON_SENTINEL, BrokerDBCanonicalError.INTEGRITY))
    assert integ.value.error_code == "REQUEST_INVALID"
    _assert_no_sentinel(integ.value, CANON_SENTINEL)

    with pytest.raises(FirewallControllerPersistenceError) as pers:
        svc._sanitize_canonical_policy_error(BrokerDBCanonicalError(CANON_SENTINEL, BrokerDBCanonicalError.PERSISTENCE))
    assert pers.value.error_code == "PERSISTENCE_FAILURE"
    _assert_no_sentinel(pers.value, CANON_SENTINEL)

    with pytest.raises(FirewallControllerPersistenceError) as plain:
        svc._sanitize_canonical_policy_error(BrokerDBError(CANON_SENTINEL))
    assert plain.value.error_code == "PERSISTENCE_FAILURE"
    _assert_no_sentinel(plain.value, CANON_SENTINEL)


def _store_pathless():
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), "s1b13-cat.db"))


# --- bounded public errors / app controller responses ---

def test_bounded_backend_error_is_persisted_and_replayed(tmp_path):
    store = _store(tmp_path, "replay-leak.db")
    base = _install_req(pid="replay-leak-p")
    assert _svc(store).install_policy(base)["status"] == "ok"
    inspect_req = _op_req(base, idempotency_key="replay-leak-key")
    svc = _svc(store, backend=_LeakyErrorBackend())

    first = svc.inspect_policy(inspect_req)
    assert first["status"] == "error"
    assert first["error_code"] == "BACKEND_ERROR"
    assert first["error_message"] == "Backend failure"
    _assert_no_sentinel(first, BACKEND_SENTINEL)

    replay = svc.inspect_policy(inspect_req)
    assert replay == first
    _assert_no_sentinel(replay, BACKEND_SENTINEL)
    raw = json.loads(
        store.get_idempotency_record("replay-leak-key", "inspect_policy")["response_json"]
    )
    _assert_no_sentinel(raw, BACKEND_SENTINEL)


def test_app_controller_install_invalid_request_is_bounded(monkeypatch):
    ctrl = MockFirewallController()

    def boom(*args, **kwargs):
        raise RuleSchemaError("INVALID_RULE", SCHEMA_SENTINEL)

    monkeypatch.setattr(
        "broker.firewall_controller_service.rule_schema_v1.validate_install_policy_rules",
        boom,
    )
    with pytest.raises(FirewallControllerRequestError) as exc:
        ctrl.install_policy(_install_req(pid="app-bounded"))
    _assert_no_sentinel(exc.value, SCHEMA_SENTINEL)


def test_app_controller_health_rejects_invalid_identifiers_without_leakage():
    ctrl = MockFirewallController()
    with pytest.raises(FirewallControllerRequestError) as exc:
        ctrl.health_check({"policy_id": "bad\nid", "request_id": "r1", "operation_id": "o1", "idempotency_key": "k1"})
    assert exc.value.error_code == "REQUEST_INVALID"
    # bounded field-oriented message is acceptable; must not contain sentinel/control internals
    assert "Invalid" in str(exc.value)


# --- compatibility / existing exception contracts preserved ---

def test_existing_contract_validation_basics_preserved():
    with pytest.raises(FirewallControllerRequestError):
        _validate_request({"request_id": "r"})
    with pytest.raises(FirewallControllerRequestError):
        _validate_request({
            "request_id": "r", "operation_id": "o", "idempotency_key": "k",
            "policy_id": "p", "policy_version": -1, "compiled_rule_digest": "a" * 64,
        })


def test_idempotency_conflict_class_preserved(tmp_path):
    store = _store(tmp_path, "idem.db")
    svc = _svc(store)
    req = _install_req(pid="idem-p", key="same-key")
    assert svc.install_policy(req)["status"] == "ok"
    # Same key, different valid payload => idempotency conflict (not request-invalid).
    req2 = _install_req(pid="idem-p", key="same-key")
    req2["rules"][0]["port_start"] = 8443
    req2["rules"][0]["port_end"] = 8443
    norm = validate_and_normalize_rules(req2["rules"], sorted({r["family"] for r in req2["rules"]}))
    req2["compiled_rule_digest"] = compiled_rule_digest(norm)
    req2["compiled"] = {}
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(req2)


def test_legacy_no_rules_install_still_supported(tmp_path):
    store = _store(tmp_path, "legacy.db")
    svc = _svc(store)
    req = {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": "legacy-p",
        "policy_version": 1,
        "compiled_rule_digest": "a" * 64,
        "compiled": {},
        "peer_uid": 1000,
        "peer_gid": 1000,
    }
    res = svc.install_policy(req)
    assert res["status"] == "ok"


def test_reconciliation_persistence_failure_classification_preserved(tmp_path):
    # preserve 1B.6 contract: canonical read storage failure => RECONCILIATION_PERSISTENCE_FAILURE
    store = _store(tmp_path, "recon.db")
    svc = _svc(store)
    req = _install_req(pid="recon-p")
    assert svc.install_policy(req)["status"] == "ok"

    class FailRead(ControllerOwnershipStore):
        def __init__(self, inner):
            self.inner = inner
            self.fail = False

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def get_canonical_policy_body(self, *args, **kwargs):
            if self.fail:
                raise BrokerDBError(PERSIST_SENTINEL)
            return self.inner.get_canonical_policy_body(*args, **kwargs)

    wrapped = FailRead(store)
    svc2 = _svc(wrapped)
    wrapped.fail = True
    out = svc2.reconcile_pending_operations(_op_req(req))
    assert out["status"] == "error"
    assert out["error_code"] == "RECONCILIATION_PERSISTENCE_FAILURE"
    _assert_no_sentinel(out, PERSIST_SENTINEL)
