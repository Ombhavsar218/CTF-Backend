"""Phase 2L.2G.3 — Privileged helper contract and mock integration tests (mock-only)."""
import os, sys, tempfile, uuid
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for p in [_ROOT, os.path.dirname(_HERE), os.path.join(_ROOT, 'ctf-platform-be')]:
    if p not in sys.path:
        sys.path.insert(0, p)

from broker.firewall_controller_service.helper_contract import (
    HelperOperation, METHOD_TO_OPERATION, SCHEMA_VERSION, MAX_REQUEST_BYTES, MAX_TIMEOUT_MS,
    validate_helper_request, HelperContractError,
)
from broker.firewall_controller_service.helper_authorization import (
    MockHelperAuthorizationProvider, MockHelperIdentityProvider, MockHelperPeerIdentity,
)
from broker.firewall_controller_service.mock_helper_executor import MockHelperExecutor
from broker.firewall_controller_service.mock_backend import MockFirewallBackend
from broker.firewall_controller_service.errors import FirewallControllerAuthError, FirewallControllerIdempotencyError


def _base_req(op=HelperOperation.INSTALL_POLICY, **over):
    r = {
        'schema_version': SCHEMA_VERSION,
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': str(uuid.uuid4()),
        'policy_id': 'pol-1',
        'policy_version': 1,
        'compiled_rule_digest': 'a'*64,
        'ownership_reference': 'own-1',
        'instance_id': 'inst-1',
        'network_id': 'net-1',
        'address_family': 'ipv4',
        'timeout_ms': 5000,
    }
    r.update(over)
    return r

IDENT = MockHelperPeerIdentity(uid=1000, gid=1000, source='test-helper-contract')

def _ok_auth():
    return MockHelperAuthorizationProvider(
        allowed_uids={1000}, allowed_gids={1000}, allowed_operations=set(HelperOperation),
    )

def _executor(auth=None):
    return MockHelperExecutor(auth=auth or _ok_auth())


# --- Valid enum operations ---
@pytest.mark.parametrize('method,op', list(METHOD_TO_OPERATION.items()))
def test_valid_enum_operations(method, op):
    ex = _executor()
    req = _base_req(op) if op != HelperOperation.HEALTH_CHECK else {
        'schema_version': SCHEMA_VERSION, 'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()),
        'idempotency_key': str(uuid.uuid4()), 'compiled_rule_digest': '0'*64, 'policy_id': 'health', 'policy_version': 0,
    }
    # health uses relaxed fields in contract; adjust
    if op == HelperOperation.HEALTH_CHECK:
        req = {'schema_version': SCHEMA_VERSION, 'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': str(uuid.uuid4())}
    resp = ex.execute_method(method, req, identity=IDENT)
    assert isinstance(resp, dict)
    assert resp.get('operation_id') == req.get('operation_id')
    assert 'status' in resp

# --- Unknown operation rejection ---
def test_unknown_operation_rejection():
    ex = _executor()
    resp = ex.execute_method('totally_unknown_op', _base_req(), identity=IDENT)
    assert resp.get('status') == 'error'
    assert resp.get('error_code') == 'OPERATION_NOT_ALLOWED'

# --- Unknown schema fields ---
def test_unknown_schema_fields_rejected():
    req = _base_req(arbitrary_unknown_field='x')
    with pytest.raises(HelperContractError) as e:
        validate_helper_request(req, HelperOperation.INSTALL_POLICY)
    assert e.value.code == 'INVALID_REQUEST'

# --- Invalid request types ---
def test_invalid_request_types():
    with pytest.raises(HelperContractError):
        validate_helper_request('not-a-dict', HelperOperation.INSTALL_POLICY)
    with pytest.raises(HelperContractError):
        validate_helper_request(_base_req(policy_version='1'), HelperOperation.INSTALL_POLICY)
    with pytest.raises(HelperContractError):
        validate_helper_request(_base_req(timeout_ms='fast'), HelperOperation.INSTALL_POLICY)

# --- Missing peer identity ---
def test_missing_peer_identity_fails_closed():
    auth = MockHelperAuthorizationProvider(allowed_uids={1000}, allowed_gids={1000})
    ex = MockHelperExecutor(auth=auth)
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.HEALTH_CHECK, {'schema_version': SCHEMA_VERSION, 'request_id': 'r1', 'operation_id': 'o1', 'idempotency_key': 'k1'}, identity=None)

# --- Unauthorized mock identity ---
def test_unauthorized_mock_identity():
    ident = MockHelperPeerIdentity(uid=9999, gid=9999)
    auth = MockHelperAuthorizationProvider(allowed_uids={1000}, allowed_gids={1000})
    ex = MockHelperExecutor(auth=auth)
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.HEALTH_CHECK, {'schema_version': SCHEMA_VERSION, 'request_id': 'r1', 'operation_id': 'o1', 'idempotency_key': 'k1'}, identity=ident)

# --- Empty authorization allowlist ---
def test_empty_authorization_allowlist_fails_closed():
    ident = MockHelperPeerIdentity(uid=1000, gid=1000)
    auth = MockHelperAuthorizationProvider(allowed_uids=set(), allowed_gids=set())
    ex = MockHelperExecutor(auth=auth)
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.HEALTH_CHECK, {'schema_version': SCHEMA_VERSION, 'request_id': 'r1', 'operation_id': 'o1', 'idempotency_key': 'k1'}, identity=ident)

# --- Caller-supplied identity rejection ---
def test_caller_supplied_identity_rejected():
    req = _base_req(peer_uid=0, peer_gid=0)
    with pytest.raises(HelperContractError) as e:
        validate_helper_request(req, HelperOperation.INSTALL_POLICY)
    assert e.value.code == 'UNAUTHORIZED_CLAIM'
    req2 = _base_req(caller_trusted=True)
    with pytest.raises(HelperContractError):
        validate_helper_request(req2, HelperOperation.INSTALL_POLICY)

# --- Invalid policy and address values ---
def test_invalid_policy_and_address_values():
    with pytest.raises(HelperContractError):
        validate_helper_request(_base_req(policy_version=-1), HelperOperation.INSTALL_POLICY)
    with pytest.raises(HelperContractError):
        validate_helper_request(_base_req(compiled_rule_digest='short'), HelperOperation.INSTALL_POLICY)
    with pytest.raises(HelperContractError):
        validate_helper_request(_base_req(source_cidr='999.0.0.1/99'), HelperOperation.INSTALL_POLICY)
    with pytest.raises(HelperContractError):
        validate_helper_request(_base_req(address_family='ipv4', destination_cidr='2001:db8::/32'), HelperOperation.INSTALL_POLICY)
    with pytest.raises(HelperContractError):
        validate_helper_request(_base_req(protocol='bogus'), HelperOperation.INSTALL_POLICY)
    with pytest.raises(HelperContractError):
        validate_helper_request(_base_req(port=70000), HelperOperation.INSTALL_POLICY)

# --- Request and response size limits ---
def test_request_size_limit():
    big = _base_req(compiled={'blob': 'x' * (MAX_REQUEST_BYTES)})
    with pytest.raises(HelperContractError) as e:
        validate_helper_request(big, HelperOperation.INSTALL_POLICY)
    assert e.value.code in ('REQUEST_TOO_LARGE', 'INVALID_REQUEST')

# --- Timeout behavior ---
def test_timeout_behavior():
    ex = _executor()
    ex.inject_timeout.add(HelperOperation.INSTALL_POLICY)
    resp = ex.execute(HelperOperation.INSTALL_POLICY, _base_req(), identity=IDENT)
    assert resp.get('status') == 'error'
    assert resp.get('error_code') == 'TIMEOUT'
    with pytest.raises(HelperContractError):
        validate_helper_request(_base_req(timeout_ms=MAX_TIMEOUT_MS + 1), HelperOperation.INSTALL_POLICY)

# --- Idempotent replay ---
def test_idempotent_replay():
    ex = _executor()
    req = _base_req()
    r1 = ex.execute(HelperOperation.INSTALL_POLICY, req, identity=IDENT)
    r2 = ex.execute(HelperOperation.INSTALL_POLICY, req, identity=IDENT)
    assert r1.get('status') == r2.get('status') == 'ok'
    assert any(e['event_type'] == 'helper_idempotent_replay' for e in ex.audit_events)

# --- Conflicting idempotency keys ---
def test_conflicting_idempotency_keys():
    ex = _executor()
    req = _base_req()
    ex.execute(HelperOperation.INSTALL_POLICY, req, identity=IDENT)
    req2 = dict(req); req2['compiled_rule_digest'] = 'b'*64
    with pytest.raises(FirewallControllerIdempotencyError):
        ex.execute(HelperOperation.INSTALL_POLICY, req2, identity=IDENT)

# --- Partial execution failure ---
def test_partial_execution_failure():
    ex = _executor()
    ex._ctrl.fail_install_ipv6 = True  # mock state injection
    resp = ex.execute(HelperOperation.INSTALL_POLICY, _base_req(), identity=IDENT)
    assert resp.get('status') == 'error'
    assert resp.get('error_code') == 'INSTALL_FAILED'

# --- Audit record creation ---
def test_audit_record_creation_sanitized():
    ex = _executor()
    ex.execute(HelperOperation.INSTALL_POLICY, _base_req(), identity=IDENT)
    types = [e['event_type'] for e in ex.audit_events]
    assert 'helper_request_received' in types
    assert 'helper_authorization_passed' in types
    assert 'helper_execution_completed' in types
    for e in ex.audit_events:
        s = str(e)
        assert 'token' not in s.lower()
        assert 'secret' not in s.lower()

# --- Uncertain operation recovery (helper boundary + controller integration) ---
def test_uncertain_outcome_does_not_promote_active(tmp_path_factory=pytest):
    from broker.firewall_controller_service import FirewallControllerService
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
    db = os.path.join(tempfile.mkdtemp(), 'c.db')
    store = ControllerOwnershipStore(db_path=db)
    # backend/executor returns uncertain
    ex = _executor()
    ex.inject_uncertain.add(HelperOperation.INSTALL_POLICY)
    backend = MockFirewallBackend(executor=ex, identity_provider=MockHelperIdentityProvider(IDENT))
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, ownership_store=store, backend=backend)
    req = _base_req(policy_id='uc1', ownership_reference='uc1', instance_id='i1', network_id='n1')
    req.update({'peer_uid': 1000, 'peer_gid': 1000, 'compiled': {}})
    try:
        resp = svc.install_policy(req)
    except Exception:
        resp = None
    rec = store.get_by_policy('uc1', 1)
    if rec:
        assert rec['installation_state'] != 'ACTIVE'

# --- Evidence-gated ACTIVE promotion (controller uses helper-backed backend) ---
def test_evidence_gated_active_promotion():
    from broker.firewall_controller_service import FirewallControllerService
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
    db = os.path.join(tempfile.mkdtemp(), 'c.db')
    store = ControllerOwnershipStore(db_path=db)
    backend = MockFirewallBackend(  # explicit mock identity (no implicit default)
        helper_auth=MockHelperAuthorizationProvider(
            allowed_uids={1000}, allowed_gids={1000}, allowed_operations=set(HelperOperation)
        ),
        identity_provider=MockHelperIdentityProvider(IDENT),
    )
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, ownership_store=store, backend=backend)
    req = _base_req(policy_id='eg1', instance_id='i1', network_id='n1')
    req.pop('ownership_reference', None)
    req.update({'peer_uid': 1000, 'peer_gid': 1000, 'compiled': {}})
    svc.install_policy(req)
    rec = store.get_by_policy('eg1', 1)
    assert rec and rec['installation_state'] != 'ACTIVE'
    vreq = dict(req); vreq['request_id']=str(uuid.uuid4()); vreq['operation_id']=str(uuid.uuid4()); vreq['idempotency_key']=str(uuid.uuid4())
    svc.verify_policy(vreq)
    rec2 = store.get_by_policy('eg1', 1)
    assert rec2['installation_state'] == 'ACTIVE'
    assert len(store.get_evidence_by_policy('eg1', 1)) >= 1

# --- Mock executor never executes shell / host state (structural) ---
def test_mock_executor_no_shell_host_state():
    ex = _executor()
    # No subprocess/os.system attributes used for execution; state is in-memory mock controller only
    assert not hasattr(ex, 'shell') and not hasattr(ex, 'subprocess')
    ex.execute(HelperOperation.INSTALL_POLICY, _base_req(policy_id='nh1'), identity=IDENT)
    # host is untouched by design (mock only); internal mock state is acceptable
    assert 'nh1' in ex._ctrl.installed
