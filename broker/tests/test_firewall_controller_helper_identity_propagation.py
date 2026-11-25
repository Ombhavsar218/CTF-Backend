"""Phase 2L.2G.3.2 — Helper identity propagation and contract hardening (mock-only).

Focus:
- explicit per-request identity propagation (no implicit UID/GID defaults)
- request JSON cannot establish identity/authorization
- mandatory/exact schema version
- strict digest, compiled-policy data boundary, and authoritative ownership reference
- timeout contract is documented as a future transport/process responsibility

All identity providers here are mock seams only. They do NOT prove kernel-authenticated
peer identity (UDS/SO_PEERCRED) and must never be used in production.
"""
import os
import sys
import tempfile
import uuid

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for p in [_ROOT, os.path.dirname(_HERE), os.path.join(_ROOT, 'ctf-platform-be')]:
    if p not in sys.path:
        sys.path.insert(0, p)

from broker.firewall_controller_service.helper_contract import (
    COMPILED_ALLOWED_KEYS,
    HelperContractError,
    HelperOperation,
    MAX_TIMEOUT_MS,
    SCHEMA_VERSION,
    TIMEOUT_ENFORCEMENT_LAYER,
    validate_helper_request,
)
from broker.firewall_controller_service.helper_authorization import (
    MockHelperAuthorizationProvider,
    MockHelperIdentityProvider,
    MockHelperPeerIdentity,
)
from broker.firewall_controller_service.mock_backend import MockFirewallBackend
from broker.firewall_controller_service.mock_helper_executor import MockHelperExecutor
from broker.firewall_controller_service.errors import FirewallControllerAuthError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ident(uid=1000, gid=1000):
    return MockHelperPeerIdentity(uid=uid, gid=gid, source='test-mock-2g32')


def _auth(uids=None, gids=None, operations=None):
    return MockHelperAuthorizationProvider(
        allowed_uids={1000} if uids is None else uids,
        allowed_gids={1000} if gids is None else gids,
        allowed_operations=set(HelperOperation) if operations is None else operations,
    )


def _req(op=HelperOperation.INSTALL_POLICY, **over):
    r = {
        'schema_version': SCHEMA_VERSION,
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': str(uuid.uuid4()),
        'policy_id': 'pol-1',
        'policy_version': 1,
        'compiled_rule_digest': 'a' * 64,
        'ownership_reference': 'own-1',
        'instance_id': 'inst-1',
        'network_id': 'net-1',
        'address_family': 'ipv4',
        'timeout_ms': 5000,
        'compiled': {},
    }
    if op == HelperOperation.HEALTH_CHECK:
        r.pop('policy_id', None)
        r.pop('policy_version', None)
        r.pop('compiled_rule_digest', None)
        r.pop('ownership_reference', None)
    r.update(over)
    return r


class _CountingProvider:
    def __init__(self, identity):
        self._identity = identity
        self.calls = 0

    def get_identity(self):
        self.calls += 1
        return self._identity


class _SequenceProvider:
    def __init__(self, identities):
        self._identities = list(identities)
        self.calls = 0

    def get_identity(self):
        idx = min(self.calls, len(self._identities) - 1)
        self.calls += 1
        return self._identities[idx]


class _RaisingProvider:
    def get_identity(self):
        raise RuntimeError('mock identity provider unavailable')


# ---------------------------------------------------------------------------
# 1. No implicit identity / allowlist defaults
# ---------------------------------------------------------------------------

def test_backend_without_identity_provider_fails_closed():
    # Explicit helper allowlists but no explicitly injected identity provider.
    be = MockFirewallBackend(helper_auth=_auth())
    with pytest.raises(FirewallControllerAuthError):
        be.install_policy(_req())


def test_backend_without_auth_fails_closed():
    # Explicit identity provider but no explicit allowlists -> empty allowlists deny.
    be = MockFirewallBackend(identity_provider=MockHelperIdentityProvider(_ident()))
    with pytest.raises(FirewallControllerAuthError):
        be.install_policy(_req())


def test_executor_constructor_has_no_implicit_identity_or_allowlists():
    ex = MockHelperExecutor()
    assert ex.auth.allowed_uids == set()
    assert ex.auth.allowed_gids == set()
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.HEALTH_CHECK, _req(HelperOperation.HEALTH_CHECK), identity=_ident())


def test_identity_provider_unavailable_fails_closed():
    be = MockFirewallBackend(identity_provider=_RaisingProvider(), helper_auth=_auth())
    with pytest.raises(FirewallControllerAuthError):
        be.install_policy(_req())


def test_missing_identity_at_executor_fails_closed():
    ex = MockHelperExecutor(auth=_auth())
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.HEALTH_CHECK, _req(HelperOperation.HEALTH_CHECK), identity=None)


@pytest.mark.parametrize('uid,gid', [(1000, 2000), (2000, 1000), (9999, 9999), (0, 0)])
def test_unlisted_uid_or_gid_denied(uid, gid):
    ex = MockHelperExecutor(auth=_auth(uids={1000}, gids={1000}))
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.HEALTH_CHECK, _req(HelperOperation.HEALTH_CHECK), identity=_ident(uid, gid))


def test_empty_allowlists_denied_even_with_valid_identity():
    ex = MockHelperExecutor(auth=_auth(uids=set(), gids=set()))
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.HEALTH_CHECK, _req(HelperOperation.HEALTH_CHECK), identity=_ident())


# ---------------------------------------------------------------------------
# 2. Request JSON can never establish identity/authorization
# ---------------------------------------------------------------------------

def test_request_json_identity_claims_do_not_grant_authorization():
    # Provider says uid 9999 (unauthorized). Request JSON tries to claim uid 1000.
    be = MockFirewallBackend(
        helper_auth=_auth(),
        identity_provider=MockHelperIdentityProvider(_ident(9999, 9999)),
    )
    spoof = _req(peer_uid=1000, uid=1000, gid=1000, caller_trusted=True, authorized=True, is_admin=True)
    with pytest.raises(FirewallControllerAuthError):
        be.install_policy(spoof)


def test_request_json_identity_claims_are_stripped_and_provider_identity_wins():
    # Provider says uid 1000 (authorized). Request JSON claims uid 9999; must be ignored.
    be = MockFirewallBackend(
        helper_auth=_auth(),
        identity_provider=MockHelperIdentityProvider(_ident(1000, 1000)),
    )
    resp = be.install_policy(_req(peer_uid=9999, peer_gid=9999, uid=9999))
    assert resp['status'] == 'ok'


def test_direct_contract_rejects_identity_claim_fields():
    for field, value in (
        ('peer_uid', 0),
        ('peer_gid', 0),
        ('uid', 0),
        ('gid', 0),
        ('caller_trusted', True),
        ('authorized', True),
        ('is_admin', True),
        ('auth_identity', 'root'),
    ):
        with pytest.raises(HelperContractError) as e:
            validate_helper_request(_req(**{field: value}), HelperOperation.INSTALL_POLICY)
        assert e.value.code == 'UNAUTHORIZED_CLAIM'


# ---------------------------------------------------------------------------
# 3. Per-request identity (changes are independently authorized)
# ---------------------------------------------------------------------------

def test_identity_changes_between_requests_are_independently_authorized():
    provider = _SequenceProvider([_ident(1000, 1000), _ident(9999, 9999)])
    be = MockFirewallBackend(helper_auth=_auth(), identity_provider=provider)

    r1 = _req(policy_id='seq-ok', idempotency_key=str(uuid.uuid4()))
    assert be.install_policy(r1)['status'] == 'ok'

    r2 = _req(policy_id='seq-denied', idempotency_key=str(uuid.uuid4()))
    with pytest.raises(FirewallControllerAuthError):
        be.install_policy(r2)

    assert provider.calls == 2


def test_identity_provider_consulted_once_per_request():
    provider = _CountingProvider(_ident())
    be = MockFirewallBackend(helper_auth=_auth(), identity_provider=provider)
    be.install_policy(_req(policy_id='cnt-1', idempotency_key=str(uuid.uuid4())))
    be.install_policy(_req(policy_id='cnt-2', idempotency_key=str(uuid.uuid4())))
    assert provider.calls == 2


# ---------------------------------------------------------------------------
# 4. Authorization happens before backend execution
# ---------------------------------------------------------------------------

def test_unauthorized_operation_rejected_before_backend_execution():
    ex = MockHelperExecutor(auth=_auth(operations={HelperOperation.HEALTH_CHECK}))
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.INSTALL_POLICY, _req(policy_id='never-installed'), identity=_ident())
    assert 'never-installed' not in ex._ctrl.installed
    assert not any(e['event_type'] == 'helper_execution_completed' for e in ex.audit_events)


def test_execute_method_uses_same_authorization_path():
    ex = MockHelperExecutor(auth=_auth())
    with pytest.raises(FirewallControllerAuthError):
        ex.execute_method('install_policy', _req(), identity=None)


# ---------------------------------------------------------------------------
# 5. Mandatory exact schema version
# ---------------------------------------------------------------------------

def test_schema_version_exact_match_accepted():
    assert validate_helper_request(_req(), HelperOperation.INSTALL_POLICY)


@pytest.mark.parametrize('value,expected_code', [
    (None, 'INVALID_REQUEST'),
    ('', 'INVALID_REQUEST'),
    (123, 'INVALID_REQUEST'),
    ('1', 'UNSUPPORTED_SCHEMA_VERSION'),
    ('2L.2G.2', 'UNSUPPORTED_SCHEMA_VERSION'),
    ('2l.2g.3', 'UNSUPPORTED_SCHEMA_VERSION'),
])
def test_schema_version_invalid_or_unsupported_rejected(value, expected_code):
    with pytest.raises(HelperContractError) as e:
        validate_helper_request(_req(schema_version=value), HelperOperation.INSTALL_POLICY)
    assert e.value.code == expected_code


def test_missing_schema_version_rejected():
    r = _req()
    del r['schema_version']
    with pytest.raises(HelperContractError) as e:
        validate_helper_request(r, HelperOperation.INSTALL_POLICY)
    assert e.value.code == 'INVALID_REQUEST'


def test_schema_version_alias_field_rejected():
    r = _req()
    r['schemaVersion'] = r.pop('schema_version')
    with pytest.raises(HelperContractError) as e:
        validate_helper_request(r, HelperOperation.INSTALL_POLICY)
    assert e.value.code in ('INVALID_REQUEST', 'UNSUPPORTED_SCHEMA_VERSION')


# ---------------------------------------------------------------------------
# 6. Strict digest format
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('digest', [
    'a' * 63,
    'a' * 65,
    'short',
    'z' * 64,
    'g' * 64,
    'a' * 62 + '!0',
    '',
])
def test_invalid_digest_rejected(digest):
    with pytest.raises(HelperContractError):
        validate_helper_request(_req(compiled_rule_digest=digest), HelperOperation.INSTALL_POLICY)


def test_valid_sha256_hex_digest_accepted():
    validate_helper_request(_req(compiled_rule_digest='A1b2' * 16), HelperOperation.INSTALL_POLICY)


# ---------------------------------------------------------------------------
# 7. Compiled policy: strict data-only structure
# ---------------------------------------------------------------------------

def test_compiled_policy_allowed_data_shape_accepted():
    compiled = {
        'metadata': {'digest': 'a' * 64},
        'families': ['ipv4'],
        'rules': ['tcp:443'],
        'entries': [{'metadata': {'digest': 'b' * 64}}],
    }
    validate_helper_request(_req(compiled=compiled), HelperOperation.INSTALL_POLICY)


def test_compiled_policy_unexpected_nested_field_rejected():
    for compiled in (
        {'rules': [{'unexpected': 'x'}]},
        {'unknown_top': {}},
    ):
        with pytest.raises(HelperContractError) as e:
            validate_helper_request(_req(compiled=compiled), HelperOperation.INSTALL_POLICY)
        assert e.value.code == 'INVALID_REQUEST'


@pytest.mark.parametrize('payload', [
    'tcp; rm -rf /',
    '$(reboot)',
    '`id`',
    'nft add rule inet filter input accept',
    'iptables -F',
    '/bin/sh -c id',
    'a && b',
    'a || b',
    'a\nb',
])
def test_compiled_policy_executable_or_expression_content_rejected(payload):
    with pytest.raises(HelperContractError):
        validate_helper_request(
            _req(compiled={'metadata': {'digest': payload}}),
            HelperOperation.INSTALL_POLICY,
        )


def test_compiled_policy_depth_limit():
    value = 'leaf'
    for _ in range(8):
        value = {'policy': value}
    with pytest.raises(HelperContractError):
        validate_helper_request(_req(compiled=value), HelperOperation.INSTALL_POLICY)


# ---------------------------------------------------------------------------
# 8. Authoritative ownership reference (no permissive fallback)
# ---------------------------------------------------------------------------

def test_ownership_reference_required_even_with_instance_and_policy_ids():
    r = _req()
    del r['ownership_reference']
    with pytest.raises(HelperContractError) as e:
        validate_helper_request(r, HelperOperation.INSTALL_POLICY)
    assert e.value.code == 'INVALID_REQUEST'


@pytest.mark.parametrize('value', [None, '', '   ', 123, 'bad id!'])
def test_invalid_ownership_reference_rejected(value):
    with pytest.raises(HelperContractError):
        validate_helper_request(_req(ownership_reference=value), HelperOperation.INSTALL_POLICY)


def test_ownership_record_id_is_accepted_as_explicit_reference():
    r = _req(ownership_record_id='11111111-2222-3333-4444-555555555555')
    del r['ownership_reference']
    validate_helper_request(r, HelperOperation.INSTALL_POLICY)


# ---------------------------------------------------------------------------
# 9. Timeout contract documentation
# ---------------------------------------------------------------------------

def test_timeout_bound_validated():
    validate_helper_request(_req(timeout_ms=MAX_TIMEOUT_MS), HelperOperation.INSTALL_POLICY)
    for bad in (0, -1, MAX_TIMEOUT_MS + 1, 'fast', None):
        if bad is None:
            continue
        with pytest.raises(HelperContractError):
            validate_helper_request(_req(timeout_ms=bad), HelperOperation.INSTALL_POLICY)


def test_timeout_enforcement_is_declared_future_layer():
    assert 'transport' in TIMEOUT_ENFORCEMENT_LAYER.lower()


# ---------------------------------------------------------------------------
# 10. Controller integration: persisted ownership, not caller claims
# ---------------------------------------------------------------------------

class _CapturingBackend:
    def __init__(self, inner):
        self.inner = inner
        self.requests = []

    def health_check(self, req):
        self.requests.append(dict(req))
        return self.inner.health_check(req)

    def install_policy(self, req):
        self.requests.append(dict(req))
        return self.inner.install_policy(req)

    def inspect_policy(self, req):
        self.requests.append(dict(req))
        return self.inner.inspect_policy(req)

    def verify_policy(self, req):
        self.requests.append(dict(req))
        return self.inner.verify_policy(req)

    def revoke_policy(self, req):
        self.requests.append(dict(req))
        return self.inner.revoke_policy(req)

    def remove_stale_policy(self, req):
        self.requests.append(dict(req))
        return self.inner.remove_stale_policy(req)

    def reconcile_pending_operations(self, req):
        self.requests.append(dict(req))
        return self.inner.reconcile_pending_operations(req)


def test_controller_injects_persisted_ownership_reference_not_caller_value():
    from broker.firewall_controller_service import FirewallControllerService
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
    from broker.tests._helper_identity import authorized_backend

    db = os.path.join(tempfile.mkdtemp(), 'ownref.db')
    store = ControllerOwnershipStore(db_path=db)
    capturing = _CapturingBackend(authorized_backend())
    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=capturing,
    )
    req = _req(policy_id='ownref-1', idempotency_key=str(uuid.uuid4()))
    req.update({'peer_uid': 1000, 'peer_gid': 1000})
    req['ownership_reference'] = 'caller-spoofed-id'
    resp = svc.install_policy(req)
    assert resp['status'] == 'ok'

    rec = store.get_by_policy('ownref-1', 1)
    assert rec is not None
    sent = capturing.requests[-1]
    assert sent['ownership_reference'] == rec['ownership_record_id']
    assert sent['ownership_reference'] != 'caller-spoofed-id'
    assert sent['schema_version'] == SCHEMA_VERSION
