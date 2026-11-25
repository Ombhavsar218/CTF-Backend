"""Post-J.20 Stage 1B.17 — identity trust, reconciliation integrity, policy binding.

Mock-only deterministic regression suite. It reproduces the concrete Stage 1B.16
findings R16-01..R16-07 and R16-09 before remediation and verifies each correction
afterwards. No Docker/host/UDS/kernel/privileged/host-firewall work is performed.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from types import SimpleNamespace

import pytest

import broker.app.auth as broker_auth
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.authorization import MockAuthorizationProvider
from broker.firewall_controller_service.authorization_strict import StrictAuthorizationProvider
from broker.firewall_controller_service.errors import (
    FirewallControllerAuthError,
    FirewallControllerBackendError,
)
from broker.firewall_controller_service.helper_authorization import (
    MockHelperAuthorizationProvider,
    MockHelperPeerIdentity,
)
from broker.firewall_controller_service.helper_contract import (
    HelperOperation,
    SCHEMA_VERSION,
)
from broker.firewall_controller_service.mock_helper_executor import MockHelperExecutor
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    RuleSchemaError,
    canonical_policy_digest,
    compiled_rule_digest,
    validate_and_normalize_rules,
    validate_install_policy_rules,
)
from broker.tests._helper_identity import authorized_backend
from broker.tests.test_post_j20_stage_1b3_durable_crash_recovery import (
    _CountingBackend,
    _evidence_for,
    _installed,
    _op_req,
    _sql,
    _state,
)

SENTINEL_ERROR_1B17 = "SENTINEL_1B17_RAW_INTERNAL_DETAIL_DO_NOT_LEAK"


# ------------------------------------------------------------------ helpers ---

def _db_path(name="b17.db"):
    return os.path.join(tempfile.mkdtemp(), name)


def _store():
    return ControllerOwnershipStore(db_path=_db_path())


def _rule(**overrides):
    r = {
        "family": "ipv4", "direction": "ingress", "protocol": "tcp",
        "source_cidr": "10.0.0.0/24", "destination_cidr": "10.0.1.0/24",
        "port_start": 80, "port_end": 80, "action": "accept",
    }
    r.update(overrides)
    return r


def _install_req(pid="p-b17", key=None, **overrides):
    rules = [_rule()]
    norm = validate_and_normalize_rules(rules, ["ipv4"])
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid, "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(norm), "compiled": {},
        "rules": rules, "required_families": ["ipv4"],
        "peer_uid": 1000, "peer_gid": 1000, "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


def _svc(store=None, backend=None):
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store or _store(),
        backend=backend or _CountingBackend(authorized_backend()),
    )


class _FakeRequest:
    def __init__(self, peer=None, path="/broker/v1/health"):
        self.state = SimpleNamespace(peer_credentials=peer)
        self.url = SimpleNamespace(path=path)


class _RecordingAuthorizer:
    def __init__(self):
        self.seen_peer = None
        self.seen_token = None

    def verify_peer(self, peer_info=None):
        self.seen_peer = dict(peer_info or {})
        return True

    def verify_token(self, token=""):
        self.seen_token = token
        return True


class _BackendWithState:
    def __init__(self, inner, backend_state):
        self.inner = inner
        self.backend_state = backend_state

    def inspect_policy(self, req):
        return {
            "status": "ok",
            "result": {"status": self.backend_state},
            "request_id": req.get("request_id"),
            "operation_id": req.get("operation_id"),
        }

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _FailingStatusStore(ControllerOwnershipStore):
    def update_reconciliation_status(self, ownership_record_id, status):
        from broker.app.db import BrokerDBError
        raise BrokerDBError("injected reconciliation status persistence failure")


class _VersionBumpingStatusStore(ControllerOwnershipStore):
    def update_reconciliation_status(self, ownership_record_id, status):
        _sql(self, "UPDATE controller_ownership SET lifecycle_version=lifecycle_version+1 WHERE ownership_record_id=?", (ownership_record_id,))
        return super().update_reconciliation_status(ownership_record_id, status)


# ------------------------------------------------- R16-01 / R16-05 identity ---

def test_r16_01_trusted_mock_peer_identity_cannot_be_overridden_by_headers(monkeypatch):
    recorder = _RecordingAuthorizer()
    monkeypatch.setattr(broker_auth, "authorizer", recorder)
    request = _FakeRequest(peer={"uid": 1000, "gid": 1000, "user": "flaghunt-mgr", "source": "mock-transport"})
    asyncio.run(broker_auth.require_broker_auth(request, "9999", "9999", "attacker", None))
    assert recorder.seen_peer["uid"] == 1000
    assert recorder.seen_peer["gid"] == 1000
    assert recorder.seen_peer["user"] == "flaghunt-mgr"
    assert "attacker" not in recorder.seen_peer.values()
    assert 9999 not in recorder.seen_peer.values()


def test_r16_01_conflicting_headers_do_not_change_trusted_identity(monkeypatch):
    recorder = _RecordingAuthorizer()
    monkeypatch.setattr(broker_auth, "authorizer", recorder)
    trusted = {"uid": 1000, "gid": 1000, "user": "flaghunt-mgr"}
    for uid, gid, user in (("9999", None, None), (None, "9999", None), (None, None, "evil")):
        request = _FakeRequest(peer=dict(trusted))
        asyncio.run(broker_auth.require_broker_auth(request, uid, gid, user, None))
        assert recorder.seen_peer == trusted


def test_r16_01_mock_header_contract_remains_available_without_trusted_transport(monkeypatch):
    recorder = _RecordingAuthorizer()
    monkeypatch.setattr(broker_auth, "authorizer", recorder)
    asyncio.run(broker_auth.require_broker_auth(_FakeRequest(peer=None), "1000", "1000", "flaghunt-mgr", None))
    assert recorder.seen_peer == {"uid": 1000, "gid": 1000, "user": "flaghunt-mgr"}


@pytest.mark.parametrize("flag", ["trusted", "verified", "caller_trusted", "auth_identity", "x_identity", "source_identity"])
def test_r16_05_caller_controller_verified_cannot_suppress_strict_rejection(flag):
    provider = StrictAuthorizationProvider(allowed_uids={1000}, allowed_gids={1000})
    req = {"peer_uid": 1000, "peer_gid": 1000, flag: True, "controller_verified": True}
    with pytest.raises(FirewallControllerAuthError):
        provider.authorize(req, "install_policy")


def test_r16_05_service_rejects_caller_trust_flag_without_ownership_side_effect():
    store = _store()
    svc = _svc(store)
    req = _install_req(pid="p-b17-trust")
    req["trusted"] = True
    req["controller_verified"] = True
    with pytest.raises(FirewallControllerAuthError):
        svc.install_policy(req)
    assert store.get_by_policy("p-b17-trust", 1) is None


def test_r16_05_mock_authorizer_also_rejects_controller_verified_alias():
    provider = MockAuthorizationProvider()
    with pytest.raises(FirewallControllerAuthError):
        provider.authorize({"verified": True, "controller_verified": True}, "install_policy")


# ------------------------------------------- R16-02 reconciliation status ---

def test_r16_02_verified_promotion_persists_reconciliation_status():
    store = _store()
    svc = _svc(store)
    pid = "b17-prom-active"
    digest = _installed(store, svc, pid)
    rec = store.get_by_policy(pid, 1)
    _evidence_for(store, rec["ownership_record_id"], pid, digest)
    _sql(store, "UPDATE controller_ownership SET installation_state='VERIFIED' WHERE policy_id=? AND policy_version=?", (pid, 1))
    res = svc.reconcile_pending_operations(_op_req(pid, digest))
    assert any(r.get("action") == "promoted_to_active" for r in res["result"]["reconciled"])
    assert _state(store, pid) == "ACTIVE"
    assert store.get_by_policy(pid, 1).get("reconciliation_status") == "ok"


def test_r16_02_revoke_confirmation_persists_reconciliation_status():
    store = _store()
    backend = _BackendWithState(_CountingBackend(authorized_backend()), "revoked")
    svc = _svc(store, backend)
    pid = "b17-prom-revoke"
    digest = _installed(store, svc, pid)
    _sql(store, "UPDATE controller_ownership SET installation_state='REVOKING' WHERE policy_id=? AND policy_version=?", (pid, 1))
    res = svc.reconcile_pending_operations(_op_req(pid, digest))
    assert any(r.get("action") == "revoke_confirmed" for r in res["result"]["reconciled"])
    assert _state(store, pid) == "REVOKED"
    assert store.get_by_policy(pid, 1).get("reconciliation_status") == "ok"


def test_r16_02_verifying_recovery_persists_reconciliation_status():
    store = _store()
    svc = _svc(store)
    pid = "b17-prom-verifying"
    digest = _installed(store, svc, pid)
    rec = store.get_by_policy(pid, 1)
    _evidence_for(store, rec["ownership_record_id"], pid, digest)
    _sql(store, "UPDATE controller_ownership SET installation_state='VERIFYING' WHERE policy_id=? AND policy_version=?", (pid, 1))
    res = svc.reconcile_pending_operations(_op_req(pid, digest))
    assert any(r.get("action") == "verifying_recovered_with_evidence" for r in res["result"]["reconciled"])
    assert _state(store, pid) == "ACTIVE"
    assert store.get_by_policy(pid, 1).get("reconciliation_status") == "ok"


def test_r16_02_status_persistence_failure_is_fail_closed():
    store = _FailingStatusStore(db_path=_db_path())
    svc = _svc(store)
    pid = "b17-status-fail"
    digest = _installed(store, svc, pid)
    rec = store.get_by_policy(pid, 1)
    _evidence_for(store, rec["ownership_record_id"], pid, digest)
    _sql(store, "UPDATE controller_ownership SET installation_state='VERIFIED' WHERE policy_id=? AND policy_version=?", (pid, 1))
    res = svc.reconcile_pending_operations(_op_req(pid, digest))
    assert res["status"] == "error"
    assert res.get("error_code") == "RECONCILIATION_PERSISTENCE_FAILURE"
    assert not res["result"]["reconciled"]


def test_r16_02_status_cas_conflict_is_uncertain_not_reconciled():
    store = _VersionBumpingStatusStore(db_path=_db_path())
    svc = _svc(store)
    pid = "b17-status-cas"
    digest = _installed(store, svc, pid)
    rec = store.get_by_policy(pid, 1)
    _evidence_for(store, rec["ownership_record_id"], pid, digest)
    _sql(store, "UPDATE controller_ownership SET installation_state='VERIFIED' WHERE policy_id=? AND policy_version=?", (pid, 1))
    res = svc.reconcile_pending_operations(_op_req(pid, digest))
    assert res["status"] == "ok"
    assert not res["result"]["reconciled"]
    assert any(e.get("reason") == "reconciliation_state_changed" for e in res["result"]["uncertain"])


# --------------------------------------- R16-03 ownership scope contract ---

def test_r16_03_unsupported_heuristic_ownership_claim_is_rejected():
    req = _install_req(pid="b17-cidr-reject")
    claim = {
        "ownership_record_id": "o-b17", "policy_id": "b17-cidr-reject", "policy_version": 1,
        "instance_id": "i1", "network_id": "n1", "network_cidr": "10.0.0.0/16",
    }
    with pytest.raises(RuleSchemaError) as exc:
        validate_install_policy_rules(req, ownership_rec=claim)
    assert exc.value.code == "UNSUPPORTED_OWNERSHIP_SCOPE"


def test_r16_03_explicit_owned_cidrs_are_enforced_when_supplied():
    in_scope = _install_req(pid="b17-cidr-ok")
    scope = {
        "ownership_record_id": "o-b17", "policy_id": "b17-cidr-ok", "policy_version": 1,
        "instance_id": "i1", "network_id": "n1",
        "owned_network_cidrs": ["10.0.0.0/16", "10.0.1.0/24"],
    }
    assert validate_install_policy_rules(in_scope, ownership_rec=scope) is not None
    out_scope = _install_req(pid="b17-cidr-out", rules=[_rule(source_cidr="10.99.0.0/24")])
    out_scope["compiled_rule_digest"] = compiled_rule_digest(
        validate_and_normalize_rules(out_scope["rules"], ["ipv4"])
    )
    with pytest.raises(RuleSchemaError) as exc:
        validate_install_policy_rules(out_scope, ownership_rec=scope)
    assert exc.value.code == "INVALID_RULE"


def test_r16_03_no_ownership_context_remains_backward_compatible():
    assert validate_install_policy_rules(_install_req(pid="b17-cidr-compat")) is not None


# -------------------------------------- R16-06 exact policy identity match ---

def test_r16_06_pending_ledger_filter_does_not_match_overlapping_prefix():
    store = _store()
    svc = _svc(store)
    digest = _installed(store, svc, "p1")
    store.create_idempotency_record("b17-ledger-p1", "install_policy", "a" * 64,
                                    resource_key="p1:1", ownership_record_id="o1",
                                    lifecycle_state="INSTALLING")
    store.create_idempotency_record("b17-ledger-p10", "install_policy", "b" * 64,
                                    resource_key="p10:1", ownership_record_id="o10",
                                    lifecycle_state="INSTALLING")
    res = svc.reconcile_pending_operations(_op_req("p1", digest))
    keys = {e.get("idempotency_key") for e in res["result"]["uncertain"]}
    assert "b17-ledger-p1" in keys
    assert "b17-ledger-p10" not in keys


def test_r16_06_ledger_filter_is_exact_in_both_directions():
    store = _store()
    svc = _svc(store)
    digests = {pid: _installed(store, svc, pid) for pid in ("p1", "p10")}
    store.create_idempotency_record("b17-exact-p1", "install_policy", "a" * 64,
                                    resource_key="p1:1", ownership_record_id="o1",
                                    lifecycle_state="INSTALLING")
    store.create_idempotency_record("b17-exact-p10", "install_policy", "c" * 64,
                                    resource_key="p10:1", ownership_record_id="o10",
                                    lifecycle_state="INSTALLING")
    for pid, own_key, other_key in (("p1", "b17-exact-p1", "b17-exact-p10"),
                                    ("p10", "b17-exact-p10", "b17-exact-p1")):
        res = svc.reconcile_pending_operations(_op_req(pid, digests[pid]))
        keys = {e.get("idempotency_key") for e in res["result"]["uncertain"]}
        assert own_key in keys
        assert other_key not in keys


# ------------------------------------ R16-04 / R16-09 canonical integrity ---

def test_r16_04_compiled_rule_digest_is_not_a_canonical_policy_digest():
    rules = [_rule()]
    norm = validate_and_normalize_rules(rules, ["ipv4"])
    req = _install_req(pid="b17-digest-alias")
    req["canonical_policy_digest"] = compiled_rule_digest(norm)
    with pytest.raises(RuleSchemaError) as exc:
        validate_install_policy_rules(req)
    assert exc.value.code == "INVALID_DIGEST"


def test_r16_04_complete_canonical_digest_is_accepted_and_bindings_independent():
    rules = [_rule()]
    norm = validate_and_normalize_rules(rules, ["ipv4"])
    good = _install_req(pid="b17-digest-ok")
    good["canonical_policy_digest"] = canonical_policy_digest(
        "b17-digest-ok", 1, "", ["ipv4"], norm, instance_id="i1", network_id="n1"
    )
    assert validate_install_policy_rules(good) is not None

    for field, value in (("policy_id", "b17-digest-changed"), ("policy_version", 2), ("instance_id", "i2")):
        changed = _install_req(pid="b17-digest-ok")
        changed[field] = value
        changed["canonical_policy_digest"] = good["canonical_policy_digest"]
        with pytest.raises(RuleSchemaError) as exc:
            validate_install_policy_rules(changed)
        assert exc.value.code == "INVALID_DIGEST"

    changed_rules = _install_req(pid="b17-digest-ok", rules=[_rule(port_end=81)])
    changed_rules["compiled_rule_digest"] = compiled_rule_digest(
        validate_and_normalize_rules(changed_rules["rules"], ["ipv4"])
    )
    changed_rules["canonical_policy_digest"] = good["canonical_policy_digest"]
    with pytest.raises(RuleSchemaError) as exc:
        validate_install_policy_rules(changed_rules)
    assert exc.value.code == "INVALID_DIGEST"


def test_r16_09_nonempty_compiled_representation_is_always_validated():
    req = _install_req(pid="b17-mirror-repr", compiled={"unexpected_representation": True})
    with pytest.raises(RuleSchemaError):
        validate_install_policy_rules(req)


def test_r16_09_nested_legacy_markers_are_detected_beyond_old_depth_bound():
    marker = {"targets": []}
    nested = marker
    for _ in range(9):
        nested = {"nested": nested}
    req = _install_req(pid="b17-mirror-deep", compiled=nested)
    with pytest.raises(RuleSchemaError) as exc:
        validate_install_policy_rules(req)
    assert exc.value.code == "AMBIGUOUS_RULE"


def test_r16_09_empty_legacy_compiled_object_remains_compatible():
    assert validate_install_policy_rules(_install_req(pid="b17-mirror-empty", compiled={})) is not None


# --------------------------------------------------------- R16-07 errors ---

class _ExplodingStateController:
    def install_policy(self, req):
        raise RuntimeError(SENTINEL_ERROR_1B17)


def test_r16_07_internal_helper_exception_text_is_not_returned():
    executor = MockHelperExecutor(
        auth=MockHelperAuthorizationProvider(
            allowed_uids={1000}, allowed_gids={1000}, allowed_operations=set(HelperOperation)
        ),
        state_controller=_ExplodingStateController(),
    )
    req = {
        "schema_version": SCHEMA_VERSION,
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()),
        "policy_id": "b17-error", "policy_version": 1,
        "compiled_rule_digest": "a" * 64,
        "ownership_reference": "o-b17", "instance_id": "i1", "network_id": "n1",
        "address_family": "ipv4", "timeout_ms": 5000,
    }
    identity = MockHelperPeerIdentity(uid=1000, gid=1000, source="b17-test")
    resp = executor.execute(HelperOperation.INSTALL_POLICY, req, identity=identity)
    assert resp["status"] == "error"
    assert resp["error_code"] == "EXECUTION_ERROR"
    assert SENTINEL_ERROR_1B17 not in resp.get("error_message", "")
    assert len(resp.get("error_message", "")) <= 200
    assert any(e["event_type"] == "helper_execution_failed" for e in executor.audit_events)
