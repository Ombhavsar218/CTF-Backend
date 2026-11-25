"""Phase 2L.2G.3.4 — ID-03/04/05/06 remediation tests (mock-only)."""
import os
import tempfile
import uuid

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import (
    FirewallControllerAuthError,
    FirewallControllerIdempotencyError,
)
from broker.firewall_controller_service.helper_authorization import (
    MockHelperAuthorizationProvider,
    MockHelperIdentityProvider,
    MockHelperPeerIdentity,
)
from broker.firewall_controller_service.helper_contract import (
    HelperContractError,
    HelperOperation,
    SCHEMA_VERSION,
    validate_helper_request,
)
from broker.firewall_controller_service.mock_helper_executor import MockHelperExecutor
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend


IDENT = MockHelperPeerIdentity(uid=1000, gid=1000, source='test-2g34')


def _store():
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), 'remediation.db'))


def _svc(store=None, backend=None, uids=None, gids=None):
    return FirewallControllerService(
        allowed_uids=uids if uids is not None else {1000},
        allowed_gids=gids if gids is not None else {1000},
        ownership_store=store or _store(),
        backend=backend or authorized_backend(),
    )


def _req(pid='p1', ver=1, digest='a' * 64, key=None, uid=1000, gid=1000, **extra):
    req = {
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': key or str(uuid.uuid4()),
        'policy_id': pid,
        'policy_version': ver,
        'compiled_rule_digest': digest,
        'compiled': {},
        'peer_uid': uid,
        'peer_gid': gid,
        'instance_id': 'i1',
        'network_id': 'n1',
        'required_families': ['ipv4'],
    }
    req.update(extra)
    return req


def _hreq(**extra):
    req = {
        'schema_version': SCHEMA_VERSION,
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': str(uuid.uuid4()),
        'policy_id': 'p1',
        'policy_version': 1,
        'compiled_rule_digest': 'a' * 64,
        'ownership_reference': '11111111-2222-3333-4444-555555555555',
        'instance_id': 'i1',
        'network_id': 'n1',
        'address_family': 'ipv4',
        'timeout_ms': 5000,
        'compiled': {},
    }
    req.update(extra)
    return req


class _CountingInstallBackend:
    def __init__(self, inner):
        self.inner = inner
        self.install_calls = 0

    def install_policy(self, req):
        self.install_calls += 1
        return self.inner.install_policy(req)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _BrokenReadStore(ControllerOwnershipStore):
    def get_by_policy(self, policy_id, policy_version):
        raise BrokerDBError('injected ownership read failure')


class _BrokenIdempotencyStore(ControllerOwnershipStore):
    def get_idempotency_record(self, idempotency_key, operation_type):
        raise BrokerDBError('injected idempotency read failure')


# ---------------------------------------------------------------------------
# ID-03: authorization and ownership validation before idempotency replay
# ---------------------------------------------------------------------------

def test_unauthorized_identity_cannot_retrieve_cached_success_response():
    backend = _CountingInstallBackend(authorized_backend())
    svc = _svc(backend=backend)
    req = _req(pid='idem-unauth', key='idem-unauth-key')
    assert svc.install_policy(req)['status'] == 'ok'

    unauthorized = dict(req)
    unauthorized['peer_uid'] = 9999
    unauthorized['peer_gid'] = 9999
    with pytest.raises(FirewallControllerAuthError):
        svc.install_policy(unauthorized)
    assert backend.install_calls == 1


def test_authorized_identical_request_receives_original_response():
    backend = _CountingInstallBackend(authorized_backend())
    svc = _svc(backend=backend)
    req = _req(pid='idem-same', key='idem-same-key')
    first = svc.install_policy(req)
    second = svc.install_policy(dict(req))
    assert second == first
    assert backend.install_calls == 1


def test_same_key_different_digest_is_rejected():
    svc = _svc()
    req = _req(pid='idem-digest', key='idem-digest-key')
    assert svc.install_policy(req)['status'] == 'ok'
    changed = dict(req)
    changed['compiled_rule_digest'] = 'b' * 64
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(changed)


def test_identity_change_does_not_inherit_another_identity_cached_response():
    svc = _svc(uids={1000, 2000})
    req = _req(pid='idem-identity', key='idem-identity-key', uid=1000)
    assert svc.install_policy(req)['status'] == 'ok'
    other = dict(req)
    other['peer_uid'] = 2000
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(other)


def test_replay_does_not_bypass_current_ownership_validation():
    store = _store()
    svc = _svc(store)
    req = _req(pid='idem-ownership', key='idem-ownership-key')
    assert svc.install_policy(req)['status'] == 'ok'
    rec = store.get_by_policy('idem-ownership', 1)
    store.db.execute(
        'UPDATE controller_ownership SET instance_id=? WHERE ownership_record_id=?',
        ('i-changed', rec['ownership_record_id']),
    )
    with pytest.raises(PermissionError):
        svc.install_policy(dict(req))


# ---------------------------------------------------------------------------
# ID-04: storage failures remain distinguishable from absence
# ---------------------------------------------------------------------------

def test_get_by_policy_returns_none_only_for_genuine_absence():
    store = _store()
    assert store.get_by_policy('missing', 1) is None


def test_get_by_policy_propagates_storage_error(monkeypatch):
    store = _store()

    def boom(*args, **kwargs):
        raise BrokerDBError('injected query failure')

    monkeypatch.setattr(store.db, 'query', boom)
    with pytest.raises(BrokerDBError):
        store.get_by_policy('p1', 1)


def test_get_idempotency_record_propagates_storage_error(monkeypatch):
    store = _store()

    def boom(*args, **kwargs):
        raise BrokerDBError('injected query failure')

    monkeypatch.setattr(store.db, 'query', boom)
    with pytest.raises(BrokerDBError):
        store.get_idempotency_record('k1', 'install_policy')


def test_ownership_and_evidence_listing_propagates_storage_error(monkeypatch):
    store = _store()

    def boom(*args, **kwargs):
        raise BrokerDBError('injected query failure')

    monkeypatch.setattr(store.db, 'query', boom)
    with pytest.raises(BrokerDBError):
        store.list_ownerships()
    with pytest.raises(BrokerDBError):
        store.get_evidence_by_policy('p1', 1)


def test_controller_fails_closed_when_ownership_storage_read_fails():
    store = _BrokenReadStore(db_path=os.path.join(tempfile.mkdtemp(), 'broken.db'))
    svc = _svc(store)
    with pytest.raises(BrokerDBError):
        svc.install_policy(_req(pid='storage-fail'))
    # No side effect and no ownership record should have been fabricated.
    assert store.db.query('SELECT * FROM controller_ownership') == []


def test_reconciliation_does_not_treat_storage_failure_as_missing_ownership():
    store = _BrokenReadStore(db_path=os.path.join(tempfile.mkdtemp(), 'broken-recon.db'))
    svc = _svc(store)
    with pytest.raises(BrokerDBError):
        svc.reconcile_pending_operations(_req(pid='storage-recon'))


def test_idempotency_storage_read_failure_fails_closed():
    store = _BrokenIdempotencyStore(db_path=os.path.join(tempfile.mkdtemp(), 'broken-idem.db'))
    svc = _svc(store)
    with pytest.raises(BrokerDBError):
        svc.install_policy(_req(pid='idem-storage', key='idem-storage-key'))


# ---------------------------------------------------------------------------
# ID-05: operation allowlists are fail-closed and explicit
# ---------------------------------------------------------------------------

def test_missing_operation_allowlist_denies_all_helper_operations():
    auth = MockHelperAuthorizationProvider(allowed_uids={1000}, allowed_gids={1000})
    ex = MockHelperExecutor(auth=auth)
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.HEALTH_CHECK, _hreq(), identity=IDENT)


def test_empty_operation_allowlist_denies_all_helper_operations():
    auth = MockHelperAuthorizationProvider(
        allowed_uids={1000}, allowed_gids={1000}, allowed_operations=set()
    )
    ex = MockHelperExecutor(auth=auth)
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.HEALTH_CHECK, _hreq(), identity=IDENT)


def test_only_explicitly_configured_operation_is_allowed():
    auth = MockHelperAuthorizationProvider(
        allowed_uids={1000}, allowed_gids={1000},
        allowed_operations={HelperOperation.HEALTH_CHECK},
    )
    ex = MockHelperExecutor(auth=auth)
    assert ex.execute(HelperOperation.HEALTH_CHECK, _hreq(), identity=IDENT)['status'] == 'ok'
    with pytest.raises(FirewallControllerAuthError):
        ex.execute(HelperOperation.INSTALL_POLICY, _hreq(), identity=IDENT)


def test_unknown_helper_operation_is_rejected():
    ex = MockHelperExecutor(auth=MockHelperAuthorizationProvider(
        allowed_uids={1000}, allowed_gids={1000}, allowed_operations=set(HelperOperation)
    ))
    res = ex.execute_method('not_a_helper_operation', _hreq(), identity=IDENT)
    assert res['status'] == 'error'
    assert res['error_code'] == 'OPERATION_NOT_ALLOWED'


def test_authorized_backend_fixture_explicitly_configures_operations():
    backend = authorized_backend()
    assert backend.executor.auth.allowed_operations == set(HelperOperation)


# ---------------------------------------------------------------------------
# ID-06: compiled-policy data boundary limitations
# ---------------------------------------------------------------------------

def test_compiled_policy_unknown_nested_field_rejected():
    req = _hreq(compiled={'rules': [{'unknown_nested': 1}]})
    with pytest.raises(HelperContractError):
        validate_helper_request(req, HelperOperation.INSTALL_POLICY)


def test_compiled_policy_unsupported_type_rejected():
    req = _hreq(compiled={'rules': [object()]})
    with pytest.raises(HelperContractError):
        validate_helper_request(req, HelperOperation.INSTALL_POLICY)


def test_compiled_policy_raw_expression_field_rejected():
    req = _hreq(compiled={'raw_iptables_expression': 'iptables -A INPUT -j ACCEPT'})
    with pytest.raises(HelperContractError):
        validate_helper_request(req, HelperOperation.INSTALL_POLICY)
