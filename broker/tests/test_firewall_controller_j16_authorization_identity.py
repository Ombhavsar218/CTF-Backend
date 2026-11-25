"""Phase 2L.2J.16 authorization, identity, and error-boundary tests (mock-only)."""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.authorization import MockAuthorizationProvider
from broker.firewall_controller_service.authorization_strict import StrictAuthorizationProvider
from broker.firewall_controller_service.errors import FirewallControllerAuthError
from broker.firewall_controller_service.mock_transport import MockControllerTransport
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.peer_identity import PeerIdentity
from broker.firewall_controller_service.rule_schema_v1 import compiled_rule_digest, validate_and_normalize_rules
from broker.tests._helper_identity import authorized_backend


def _db(name="j16.db"):
    return os.path.join(tempfile.mkdtemp(), name)


def _store(path=None):
    return ControllerOwnershipStore(db_path=path or _db())


def _svc(store=None, *, auth=None, strict_auth=True, allowed_uids=None, allowed_gids=None, backend=None):
    store = store or _store()
    backend = backend or authorized_backend()
    if strict_auth and auth is None:
        return FirewallControllerService(
            allowed_uids={1000} if allowed_uids is None else allowed_uids,
            allowed_gids={1000} if allowed_gids is None else allowed_gids,
            backend=backend,
            ownership_store=store,
            strict_auth=True,
        )
    return FirewallControllerService(
        auth=auth,
        backend=backend,
        ownership_store=store,
        strict_auth=strict_auth,
        allowed_uids=allowed_uids,
        allowed_gids=allowed_gids,
    )


def _base_rule(**overrides):
    r = {
        "family": "ipv4", "direction": "ingress", "protocol": "tcp",
        "source_cidr": "10.0.0.0/24", "destination_cidr": "10.0.1.0/24",
        "port_start": 80, "port_end": 80, "action": "accept",
    }
    r.update(overrides)
    return r


def _install_req(pid="p-j16", key=None, **overrides):
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


def _install_active(store, svc, pid):
    req = _install_req(pid=pid)
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    assert svc.verify_policy(_op_req(pid, digest))["status"] == "ok"
    own = store.get_by_policy(pid, 1)
    assert own and own.get("installation_state") == "ACTIVE"
    return digest, own


# 14. Unsafe dependency injection or construction

def test_implicit_nonstrict_construction_rejected_fail_closed():
    with pytest.raises(FirewallControllerAuthError):
        FirewallControllerService(strict_auth=False, ownership_store=_store())


def test_explicit_test_only_mock_auth_requires_explicit_injection():
    # Explicit injection remains possible for controlled tests; implicit path is blocked.
    svc = FirewallControllerService(auth=MockAuthorizationProvider(), ownership_store=_store())
    assert svc is not None


# 1. Missing caller identity (strict)

@pytest.mark.parametrize("op", ["install_policy", "inspect_policy", "verify_policy", "revoke_policy", "remove_stale_policy", "reconcile_pending_operations"])
def test_missing_peer_identity_rejected_before_sensitive_side_effects(op):
    store = _store()
    svc = _svc(store)
    if op == "install_policy":
        req = _install_req(pid=f"p-miss-{op}")
    else:
        digest, _ = _install_active(store, svc, f"p-base-{op}")
        req = _op_req(f"p-base-{op}", digest)
    req.pop("peer_uid", None); req.pop("peer_gid", None)
    with pytest.raises(FirewallControllerAuthError):
        getattr(svc, op)(req)
    # For install, ownership must not be created on auth failure.
    if op == "install_policy":
        assert store.get_by_policy(f"p-miss-{op}", 1) is None


# 2. Malformed caller identity

@pytest.mark.parametrize("uid,gid", [("abc", 1000), (1000, "abc"), (None, 1000), (1000, None), ("", 1000)])
def test_malformed_peer_identity_rejected(uid, gid):
    store = _store(); svc = _svc(store)
    req = _install_req(pid=f"p-mal-{uid}-{gid}")
    req["peer_uid"] = uid; req["peer_gid"] = gid
    with pytest.raises(FirewallControllerAuthError):
        svc.install_policy(req)
    assert store.get_by_policy(req["policy_id"], 1) is None


# 3/4. Spoofed caller identity / caller-trusted flags rejected

@pytest.mark.parametrize("bad_field", ["caller_trusted", "verified", "trusted", "auth_identity", "x_identity", "source_identity"])
def test_caller_supplied_trusted_identity_flags_rejected(bad_field):
    store = _store(); svc = _svc(store)
    req = _install_req(pid=f"p-spoof-{bad_field}")
    req[bad_field] = True
    with pytest.raises(FirewallControllerAuthError):
        svc.install_policy(req)
    assert store.get_by_policy(req["policy_id"], 1) is None


# 5-10 unauthorized operations

@pytest.mark.parametrize("op", ["install_policy", "inspect_policy", "verify_policy", "revoke_policy", "remove_stale_policy", "reconcile_pending_operations"])
def test_unauthorized_uid_rejected(op):
    store = _store(); svc = _svc(store)
    if op == "install_policy":
        req = _install_req(pid=f"p-unauth-{op}", peer_uid=9999)
    else:
        digest, _ = _install_active(store, svc, f"p-ua-base-{op}")
        req = _op_req(f"p-ua-base-{op}", digest, peer_uid=9999)
    with pytest.raises(FirewallControllerAuthError):
        getattr(svc, op)(req)


@pytest.mark.parametrize("op", ["install_policy", "inspect_policy", "verify_policy", "revoke_policy", "remove_stale_policy", "reconcile_pending_operations"])
def test_unauthorized_gid_rejected(op):
    store = _store(); svc = _svc(store)
    if op == "install_policy":
        req = _install_req(pid=f"p-ug-{op}", peer_gid=9999)
    else:
        digest, _ = _install_active(store, svc, f"p-ug-base-{op}")
        req = _op_req(f"p-ug-base-{op}", digest, peer_gid=9999)
    with pytest.raises(FirewallControllerAuthError):
        getattr(svc, op)(req)


# 11. Wrong-owner evidence access (binding/ownership mismatch)

def test_wrong_owner_binding_cannot_access_or_mutate_state():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-wo")
    # wrong instance binding must fail closed
    with pytest.raises(Exception):
        svc.inspect_policy(_op_req("p-wo", digest, instance_id="other"))
    with pytest.raises(Exception):
        svc.verify_policy(_op_req("p-wo", digest, instance_id="other"))


# 12. Wrong-owner / conflicting idempotency access

def test_same_idempotency_key_different_payload_rejected_fail_closed():
    store = _store(); svc = _svc(store)
    req1 = _install_req(pid="p-idem", key="k-same")
    assert svc.install_policy(req1)["status"] == "ok"
    req2 = _install_req(pid="p-idem", key="k-same", instance_id="i2")
    with pytest.raises(Exception):
        svc.install_policy(req2)
    assert len([o for o in store.list_ownerships() if o.get("policy_id") == "p-idem"]) == 1


# 13. Direct-service invocation without required authorization context

def test_direct_service_call_without_peer_identity_fails_closed():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-direct")
    req.pop("peer_uid", None); req.pop("peer_gid", None)
    with pytest.raises(FirewallControllerAuthError):
        svc.install_policy(req)
    assert store.get_by_policy("p-direct", 1) is None


# 15. Missing/unexpected request fields

def test_missing_required_field_rejected_no_side_effect():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-missf")
    req.pop("policy_id")
    with pytest.raises(Exception):
        svc.install_policy(req)
    assert store.get_by_policy("p-missf", 1) is None


# 16. Invalid identifier and digest values

@pytest.mark.parametrize("field,value", [
    ("request_id", "bad id"),
    ("operation_id", "../bad"),
    ("idempotency_key", "bad\nkey"),
    ("policy_id", "bad/id"),
])
def test_invalid_identifier_values_rejected_fail_closed(field, value):
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-validid" if field != "policy_id" else "p-ok")
    req[field] = value
    with pytest.raises(Exception):
        svc.install_policy(req)


def test_invalid_digest_rejected_fail_closed():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-badd")
    req["compiled_rule_digest"] = "not-a-digest"
    with pytest.raises(Exception):
        svc.install_policy(req)
    assert store.get_by_policy("p-badd", 1) is None


# 17/18. Unexpected internal exception and bounded error behavior

def test_validation_failure_does_not_claim_success_or_create_state():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-valfail")
    req["policy_version"] = -1
    with pytest.raises(Exception):
        svc.install_policy(req)
    assert store.get_by_policy("p-valfail", 1) is None


# 19. No-side-effect guarantees after auth/validation rejection (inspect path)

def test_unauthorized_inspect_has_no_state_mutation():
    store = _store(); svc = _svc(store)
    digest, own = _install_active(store, svc, "p-nse")
    before = store.get_by_policy("p-nse", 1)
    with pytest.raises(FirewallControllerAuthError):
        svc.inspect_policy(_op_req("p-nse", digest, peer_uid=9999))
    after = store.get_by_policy("p-nse", 1)
    assert after.get("installation_state") == before.get("installation_state")
    assert after.get("lifecycle_version") == before.get("lifecycle_version")


# 20. Existing authorized workflows continue to work

def test_authorized_workflow_install_verify_inspect_revoke():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-okflow")
    insp = svc.inspect_policy(_op_req("p-okflow", digest))
    assert insp.get("status") == "ok"
    rev = svc.revoke_policy(_op_req("p-okflow", digest))
    assert isinstance(rev, dict)


# Mock transport identity propagation (spoof resistance at boundary)

def test_mock_transport_injects_peer_identity_not_caller_payload():
    store = _store(); svc = _svc(store)
    t = MockControllerTransport(service=svc)
    req = _install_req(pid="p-mt")
    # caller tries to claim different identity in payload; transport must inject real peer
    req["peer_uid"] = 9999; req["peer_gid"] = 9999
    peer = PeerIdentity(uid=1000, gid=1000)
    res = t.install_policy(req, peer)
    assert res.get("status") == "ok"


def test_mock_transport_missing_peer_fails_closed():
    store = _store(); svc = _svc(store)
    t = MockControllerTransport(service=svc)
    with pytest.raises(FirewallControllerAuthError):
        t.install_policy(_install_req(pid="p-mt-miss"), None)

