"""Phase 2L.2G.3.8 — residual risk remediation (test-only, mock-only).

Covers:
- R-01: install backend failure persistence errors are not swallowed.
- R-02: controller/pre-persistence policy/instance/network identifier validation.
- R-03: corrupt stored idempotency digests fail closed without cached disclosure.

No real transport, privileged helper, firewall, host, or production database
behavior is exercised here.
"""
import os
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from broker.app.db import BrokerDBError
from broker.app.firewall_controller_contract import (
    FirewallControllerIdempotencyError,
    FirewallControllerRequestError,
)
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.audit import MockAuditSink
from broker.firewall_controller_service.errors import FirewallControllerPersistenceError
from broker.firewall_controller_service.helper_contract import (
    SCHEMA_VERSION,
    HelperContractError,
    HelperOperation,
    validate_helper_request,
)
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend


_OMIT = object()


def _store(name='residual.db'):
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), name))


def _svc(store=None, backend=None, uids=None, gids=None, audit=None, **kwargs):
    return FirewallControllerService(
        allowed_uids=uids if uids is not None else {1000},
        allowed_gids=gids if gids is not None else {1000},
        ownership_store=store or _store(),
        backend=backend or authorized_backend(),
        audit=audit,
        **kwargs,
    )


def _req(pid='p1', ver=1, digest='a' * 64, key=None, inst='i1', net='n1',
         uid=1000, gid=1000, **extra):
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
        'address_family': 'ipv4',
        'required_families': ['ipv4'],
    }
    if inst is not _OMIT:
        req['instance_id'] = inst
    if net is not _OMIT:
        req['network_id'] = net
    req.update(extra)
    return req


def _new_request(base, **extra):
    req = dict(base)
    req['request_id'] = str(uuid.uuid4())
    req['operation_id'] = str(uuid.uuid4())
    req['idempotency_key'] = str(uuid.uuid4())
    req.update(extra)
    return req


def _install_active(svc, pid='p1', uid=1000):
    base = _req(pid=pid, uid=uid, gid=uid)
    assert svc.install_policy(base)['status'] == 'ok'
    assert svc.verify_policy(_new_request(base))['status'] == 'ok'
    return base


class _CountingBackend:
    def __init__(self, inner):
        self.inner = inner
        self.install_calls = 0
        self.inspect_calls = 0

    def install_policy(self, req):
        self.install_calls += 1
        return self.inner.install_policy(req)

    def inspect_policy(self, req):
        self.inspect_calls += 1
        return self.inner.inspect_policy(req)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _FailingInstallBackend:
    def __init__(self, inner):
        self.inner = inner
        self.install_calls = 0

    def install_policy(self, req):
        self.install_calls += 1
        return {
            'status': 'error',
            'request_id': req.get('request_id'),
            'operation_id': req.get('operation_id'),
            'error_code': 'INSTALL_FAILED',
            'error_message': 'mock install failure',
        }

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _TargetedFaultStore:
    """Inject only FAILED-transition persistence failures."""

    def __init__(self, inner, *, fail_failed_state=False, fail_failed_history=False,
                 state_exc=None, history_exc=None):
        self.inner = inner
        self.fail_failed_state = fail_failed_state
        self.fail_failed_history = fail_failed_history
        self.state_exc = state_exc or BrokerDBError('injected failure state persistence failure')
        self.history_exc = history_exc or BrokerDBError('injected lifecycle history persistence failure')

    def update_ownership_state(self, ownership_record_id, new_state, prev_state=None,
                               expected_version=None):
        if new_state == 'FAILED' and self.fail_failed_state:
            raise self.state_exc
        return self.inner.update_ownership_state(
            ownership_record_id, new_state, prev_state, expected_version
        )

    def record_lifecycle_transition(self, *args, **kwargs):
        new_state = kwargs.get('new_state')
        if new_state is None and len(args) >= 5:
            new_state = args[4]
        if new_state == 'FAILED' and self.fail_failed_history:
            raise self.history_exc
        return self.inner.record_lifecycle_transition(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _AdvancingFailedStateStore:
    """Advance the lifecycle state just before the controller's FAILED CAS write."""

    def __init__(self, inner):
        self.inner = inner
        self.advanced = False

    def update_ownership_state(self, ownership_record_id, new_state, prev_state=None,
                               expected_version=None):
        if new_state == 'FAILED' and not self.advanced:
            self.advanced = True
            self.inner.update_ownership_state(
                ownership_record_id, 'INSTALLING', prev_state, expected_version
            )
            return self.inner.update_ownership_state(
                ownership_record_id, new_state, prev_state, expected_version
            )
        return self.inner.update_ownership_state(
            ownership_record_id, new_state, prev_state, expected_version
        )

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _CorruptDigestStore:
    """Return a corrupt request_digest for one idempotency record without mutating storage."""

    def __init__(self, inner, key, operation, corrupt_value):
        self.inner = inner
        self.key = key
        self.operation = operation
        self.corrupt_value = corrupt_value

    def get_idempotency_record(self, idempotency_key, operation_type):
        rec = self.inner.get_idempotency_record(idempotency_key, operation_type)
        if rec and idempotency_key == self.key and operation_type == self.operation:
            rec = dict(rec)
            rec['request_digest'] = self.corrupt_value
        return rec

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _ExplodingCorruptAudit(MockAuditSink):
    def log(self, event_type, req=None, details=None):
        if event_type == 'idempotency_digest_corrupt':
            raise RuntimeError('audit sink unavailable')
        return super().log(event_type, req, details)


def _helper_req(**extra):
    req = {
        'schema_version': SCHEMA_VERSION,
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': str(uuid.uuid4()),
        'policy_id': 'p1',
        'policy_version': 1,
        'compiled_rule_digest': 'a' * 64,
        'ownership_reference': str(uuid.uuid4()),
        'instance_id': 'i1',
        'network_id': 'n1',
        'address_family': 'ipv4',
        'timeout_ms': 5000,
        'compiled': {},
    }
    req.update(extra)
    return req


def _setup_completed_inspect(store, backend, pid, key):
    svc = _svc(store, backend, uids={1000, 2000}, gids={1000, 2000})
    base = _install_active(svc, pid=pid)
    replay_req = _new_request(base, idempotency_key=key)
    first = svc.inspect_policy(replay_req)
    assert first['status'] == 'ok'
    return svc, base, first


# ---------------------------------------------------------------------------
# R-01 — install failure persistence errors
# ---------------------------------------------------------------------------

def test_install_backend_failure_persists_failed_state_and_history():
    store = _store('r01-ok.db')
    backend = _FailingInstallBackend(authorized_backend())
    svc = _svc(store, backend)
    req = _req(pid='r01-ok', key='r01-ok-key')

    res = svc.install_policy(req)
    assert res['status'] == 'error'
    assert res['error_code'] == 'INSTALL_FAILED'

    rec = store.get_by_policy('r01-ok', 1)
    assert rec is not None
    assert rec['installation_state'] == 'FAILED'
    idem = store.get_idempotency_record('r01-ok-key', 'install_policy')
    assert idem is not None and idem['status'] == 'COMPLETED'
    history = store.get_lifecycle_history(rec['ownership_record_id'])
    assert any(h['new_state'] == 'FAILED' and h['result'] == 'error' for h in history)

    # A completed error response is replayable and does not invoke the backend again.
    # Outward backend error messages are bounded/sanitized (no raw backend text leak),
    # while status/error_code and durable failure semantics are preserved.
    replay = svc.install_policy(_req(pid='r01-ok', key='r01-ok-key'))
    assert replay['status'] == res['status'] == 'error'
    assert replay.get('error_code') == res.get('error_code') == 'INSTALL_FAILED'
    assert replay.get('error_message') == res.get('error_message')
    assert 'mock install failure' not in str(replay)
    assert backend.install_calls == 1


@pytest.mark.parametrize('error_message', [
    'injected transition write failure',
    'database is locked: secret detail must not leak',
])
def test_install_failure_state_write_failure_is_sanitized(error_message):
    base = _store('r01-state.db')
    fault = _TargetedFaultStore(
        base, fail_failed_state=True, state_exc=BrokerDBError(error_message),
    )
    backend = _FailingInstallBackend(authorized_backend())
    svc = _svc(fault, backend)
    req = _req(pid='r01-state', key='r01-state-key')

    with pytest.raises(FirewallControllerPersistenceError) as exc:
        svc.install_policy(req)

    err = exc.value
    assert err.error_code == 'PERSISTENCE_FAILURE'
    assert str(err) == 'Install failure could not be fully persisted'
    assert error_message not in str(err)
    assert 'secret detail' not in str(err)
    assert err.details['failure_state_persisted'] is False
    assert err.details['lifecycle_history_persisted'] is False
    assert err.details['backend_error_code'] == 'INSTALL_FAILED'
    assert err.__cause__ is None
    assert err.__suppress_context__ is True

    rec = base.get_by_policy('r01-state', 1)
    assert rec is not None
    assert rec['installation_state'] == 'REQUESTED'
    idem = base.get_idempotency_record('r01-state-key', 'install_policy')
    assert idem is not None and idem['status'] == 'PENDING'
    assert not any(h['new_state'] == 'FAILED'
                   for h in base.get_lifecycle_history(rec['ownership_record_id']))


def test_install_failure_history_write_failure_is_sanitized_and_not_overclaimed():
    base = _store('r01-history.db')
    fault = _TargetedFaultStore(base, fail_failed_history=True)
    backend = _FailingInstallBackend(authorized_backend())
    svc = _svc(fault, backend)
    req = _req(pid='r01-history', key='r01-history-key')

    with pytest.raises(FirewallControllerPersistenceError) as exc:
        svc.install_policy(req)

    err = exc.value
    assert err.error_code == 'PERSISTENCE_FAILURE'
    assert str(err) == 'Install failure could not be fully persisted'
    assert err.details['failure_state_persisted'] is True
    assert err.details['lifecycle_history_persisted'] is False
    assert err.details['backend_error_code'] == 'INSTALL_FAILED'

    rec = base.get_by_policy('r01-history', 1)
    assert rec is not None and rec['installation_state'] == 'FAILED'
    idem = base.get_idempotency_record('r01-history-key', 'install_policy')
    assert idem is not None and idem['status'] == 'PENDING'
    assert not any(h['new_state'] == 'FAILED'
                   for h in base.get_lifecycle_history(rec['ownership_record_id']))


def test_install_failure_does_not_overwrite_advanced_or_uncertain_state():
    base = _store('r01-advanced.db')
    racing = _AdvancingFailedStateStore(base)
    backend = _FailingInstallBackend(authorized_backend())
    svc = _svc(racing, backend)
    req = _req(pid='r01-advanced', key='r01-advanced-key')

    with pytest.raises(FirewallControllerPersistenceError) as exc:
        svc.install_policy(req)

    err = exc.value
    assert err.details['failure_state_persisted'] is False
    assert err.details['lifecycle_history_persisted'] is False
    assert err.details['reason'] == 'ownership_state_changed'
    rec = base.get_by_policy('r01-advanced', 1)
    assert rec is not None
    assert rec['installation_state'] == 'INSTALLING'
    idem = base.get_idempotency_record('r01-advanced-key', 'install_policy')
    assert idem is not None and idem['status'] == 'PENDING'
    assert not any(h['new_state'] == 'FAILED'
                   for h in base.get_lifecycle_history(rec['ownership_record_id']))


def test_install_failure_persistence_recovery_after_db_available():
    base = _store('r01-recover.db')
    fault = _TargetedFaultStore(
        base, fail_failed_state=True,
        state_exc=BrokerDBError('database is locked'),
    )
    failed_backend = _FailingInstallBackend(authorized_backend())
    failed_svc = _svc(fault, failed_backend)
    old_key = 'r01-recover-old-key'
    with pytest.raises(FirewallControllerPersistenceError):
        failed_svc.install_policy(_req(pid='r01-recover', key=old_key))

    old_idem = base.get_idempotency_record(old_key, 'install_policy')
    assert old_idem is not None and old_idem['status'] == 'PENDING'
    rec = base.get_by_policy('r01-recover', 1)
    assert rec is not None and rec['installation_state'] == 'REQUESTED'

    # Persistence is available again. A deliberate new attempt uses a fresh
    # idempotency key and is not blocked by the durable PENDING record.
    healthy_backend = _CountingBackend(authorized_backend())
    healthy_svc = _svc(base, healthy_backend)
    new_key = 'r01-recover-new-key'
    res = healthy_svc.install_policy(_req(pid='r01-recover', key=new_key))
    assert res['status'] == 'ok'
    assert healthy_backend.install_calls == 1
    assert base.get_by_policy('r01-recover', 1)['installation_state'] == 'INSTALLING'
    assert base.get_idempotency_record(new_key, 'install_policy')['status'] == 'COMPLETED'
    assert base.get_idempotency_record(old_key, 'install_policy')['status'] == 'PENDING'


# ---------------------------------------------------------------------------
# R-02 — strict pre-persistence identifier validation
# ---------------------------------------------------------------------------

_BAD_IDS = [
    'p1\n',
    'p1\r',
    ' p1',
    'p1 ',
    'p 1',
    'p\t1',
    'p\x00',
    'p' * 129,
    '',
    None,
    123,
    ['p1'],
    {'id': 'p1'},
]
# None is the documented optional instance/network value; it is tested separately.
_BAD_OPTIONAL_IDS = [value for value in _BAD_IDS if value is not None]


def _assert_no_persistence(store, key):
    assert store.list_ownerships() == []
    assert store.get_lifecycle_history() == []
    assert store.get_idempotency_record(key, 'install_policy') is None


@pytest.mark.parametrize('bad_policy_id', _BAD_IDS, ids=[repr(v) for v in _BAD_IDS])
def test_invalid_policy_id_rejected_before_persistence(bad_policy_id):
    store = _store('r02-policy.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    req = _req(pid=bad_policy_id, key='r02-policy-key')

    with pytest.raises((PermissionError, FirewallControllerRequestError)):
        svc.install_policy(req)

    assert backend.install_calls == 0
    _assert_no_persistence(store, 'r02-policy-key')


@pytest.mark.parametrize('bad_instance_id', _BAD_OPTIONAL_IDS,
                         ids=[repr(v) for v in _BAD_OPTIONAL_IDS])
def test_invalid_instance_id_rejected_before_persistence(bad_instance_id):
    store = _store('r02-instance.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    req = _req(pid='r02-instance', inst=bad_instance_id, key='r02-instance-key')

    with pytest.raises((PermissionError, FirewallControllerRequestError)):
        svc.install_policy(req)

    assert backend.install_calls == 0
    _assert_no_persistence(store, 'r02-instance-key')


@pytest.mark.parametrize('bad_network_id', _BAD_OPTIONAL_IDS,
                         ids=[repr(v) for v in _BAD_OPTIONAL_IDS])
def test_invalid_network_id_rejected_before_persistence(bad_network_id):
    store = _store('r02-network.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    req = _req(pid='r02-network', net=bad_network_id, key='r02-network-key')

    with pytest.raises((PermissionError, FirewallControllerRequestError)):
        svc.install_policy(req)

    assert backend.install_calls == 0
    _assert_no_persistence(store, 'r02-network-key')


@pytest.mark.parametrize('inst,net', [
    (None, None),
    (_OMIT, _OMIT),
])
def test_optional_instance_network_omission_remains_supported(inst, net):
    store = _store('r02-optional.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    req = _req(pid='r02-optional', inst=inst, net=net)

    res = svc.install_policy(req)
    assert res['status'] == 'ok'
    rec = store.get_by_policy('r02-optional', 1)
    assert rec is not None
    assert rec['instance_id'] == ''
    assert rec['network_id'] == ''


def test_controller_identifier_rule_matches_helper_contract():
    from broker.firewall_controller_service.helper_contract import _ID_RE as helper_id_re
    assert FirewallControllerService._ID_RE.pattern == helper_id_re.pattern


@pytest.mark.parametrize('pid,inst,net', [
    ('A' * 128, 'i' * 128, 'n' * 128),
    ('P-1_2.3:4', 'I-1_2.3:4', 'N-1_2.3:4'),
])
def test_valid_boundary_identifiers_accepted(pid, inst, net):
    store = _store('r02-valid.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)

    res = svc.install_policy(_req(pid=pid, inst=inst, net=net))
    assert res['status'] == 'ok'
    rec = store.get_by_policy(pid, 1)
    assert rec is not None
    assert rec['policy_id'] == pid
    assert rec['instance_id'] == inst
    assert rec['network_id'] == net


@pytest.mark.parametrize('field,bad_value', [
    ('instance_id', 'i1\n'),
    ('instance_id', 'i1\r'),
    ('network_id', 'n1\n'),
    ('network_id', 'n1\r'),
])
def test_corrupt_authoritative_identifier_fails_closed(field, bad_value):
    store = _store('r02-authoritative.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    oid = str(uuid.uuid4())
    rec = {
        'ownership_record_id': oid,
        'policy_id': 'r02-authoritative',
        'policy_version': 1,
        'instance_id': 'i1',
        'network_id': 'n1',
        'canonical_policy_digest': 'a' * 64,
        'installed_rule_ids': [],
        'address_family': 'ipv4',
        'installation_state': 'ACTIVE',
    }
    rec[field] = bad_value
    store.create_ownership(rec)

    with pytest.raises(PermissionError):
        svc.inspect_policy(_req(pid='r02-authoritative', inst=None, net=None))

    assert backend.inspect_calls == 0
    assert store.get_by_policy('r02-authoritative', 1)['installation_state'] == 'ACTIVE'


@pytest.mark.parametrize('field,bad_value', [
    ('instance_id', 'i1\n'),
    ('network_id', 'n1\r'),
    ('instance_id', 'i1\r\n'),
    ('network_id', ' n1'),
])
def test_helper_contract_rejects_malformed_optional_identifiers(field, bad_value):
    req = _helper_req(**{field: bad_value})
    with pytest.raises(HelperContractError) as exc:
        validate_helper_request(req, HelperOperation.INSPECT_POLICY)
    assert exc.value.code == 'INVALID_REQUEST'


# ---------------------------------------------------------------------------
# R-03 — corrupt stored idempotency digests
# ---------------------------------------------------------------------------

_CORRUPT_DIGESTS = [
    None,
    '',
    'not-a-digest',
    'a' * 63,
    'a' * 65,
    'g' * 64,
    123,
    b'a' * 64,
]


@pytest.mark.parametrize('corrupt', _CORRUPT_DIGESTS,
                         ids=[repr(v) for v in _CORRUPT_DIGESTS])
def test_corrupt_stored_digest_denies_replay_without_disclosure(corrupt):
    store = _store('r03-corrupt.db')
    backend = _CountingBackend(authorized_backend())
    key = 'r03-corrupt-key'
    _, base, _ = _setup_completed_inspect(store, backend, 'r03-corrupt', key)
    original_digest = store.get_idempotency_record(key, 'inspect_policy')['request_digest']

    wrapper = _CorruptDigestStore(store, key, 'inspect_policy', corrupt)
    audit = MockAuditSink()
    replay_svc = _svc(wrapper, backend, uids={1000, 2000}, gids={1000, 2000}, audit=audit)
    before = backend.inspect_calls

    with pytest.raises(FirewallControllerIdempotencyError) as exc:
        replay_svc.inspect_policy(_new_request(base, idempotency_key=key))

    assert str(exc.value) == FirewallControllerService._IDEMPOTENCY_DIGEST_CORRUPT_MESSAGE
    assert exc.value.error_code == 'IDEMPOTENCY_CONFLICT'
    assert exc.value.details.get('reason') == 'stored_request_digest_invalid'
    assert backend.inspect_calls == before
    assert any(e['event_type'] == 'idempotency_digest_corrupt' for e in audit.events)
    # The corrupt value was not persisted/repaired by the denial path.
    assert store.get_idempotency_record(key, 'inspect_policy')['request_digest'] == original_digest


def test_corrupt_digest_audit_failure_does_not_prevent_denial():
    store = _store('r03-audit.db')
    backend = _CountingBackend(authorized_backend())
    key = 'r03-audit-key'
    _, base, _ = _setup_completed_inspect(store, backend, 'r03-audit', key)

    wrapper = _CorruptDigestStore(store, key, 'inspect_policy', '')
    replay_svc = _svc(
        wrapper, backend, uids={1000, 2000}, gids={1000, 2000},
        audit=_ExplodingCorruptAudit(),
    )
    with pytest.raises(FirewallControllerIdempotencyError) as exc:
        replay_svc.inspect_policy(_new_request(base, idempotency_key=key))
    assert str(exc.value) == FirewallControllerService._IDEMPOTENCY_DIGEST_CORRUPT_MESSAGE


def test_valid_digest_with_matching_peer_and_ownership_replays():
    store = _store('r03-match.db')
    backend = _CountingBackend(authorized_backend())
    key = 'r03-match-key'
    _, base, first = _setup_completed_inspect(store, backend, 'r03-match', key)
    before = backend.inspect_calls

    second = _svc(store, backend, uids={1000, 2000}, gids={1000, 2000}).inspect_policy(
        _new_request(base, idempotency_key=key)
    )
    assert second == first
    assert backend.inspect_calls == before


def test_valid_digest_with_different_authorized_peer_is_rejected():
    store = _store('r03-peer.db')
    backend = _CountingBackend(authorized_backend())
    key = 'r03-peer-key'
    _, base, _ = _setup_completed_inspect(store, backend, 'r03-peer', key)
    before = backend.inspect_calls

    svc = _svc(store, backend, uids={1000, 2000}, gids={1000, 2000})
    with pytest.raises(FirewallControllerIdempotencyError) as exc:
        svc.inspect_policy(_new_request(
            base, idempotency_key=key, peer_uid=2000, peer_gid=2000,
        ))
    assert 'conflict' in str(exc.value).lower()
    assert backend.inspect_calls == before


def test_corrupt_digest_after_process_restart_denies_and_is_not_repaired():
    store = _store('r03-restart.db')
    backend = _CountingBackend(authorized_backend())
    key = 'r03-restart-key'
    _, base, _ = _setup_completed_inspect(store, backend, 'r03-restart', key)
    db_path = store.db.db_path
    store.db.execute(
        'UPDATE controller_idempotency SET request_digest=? '
        'WHERE idempotency_key=? AND operation_type=?',
        ('', key, 'inspect_policy'),
    )
    before = backend.inspect_calls

    fresh_store = ControllerOwnershipStore(db_path=db_path)
    fresh_svc = _svc(fresh_store, backend, uids={1000, 2000}, gids={1000, 2000})
    with pytest.raises(FirewallControllerIdempotencyError) as exc:
        fresh_svc.inspect_policy(_new_request(base, idempotency_key=key))
    assert str(exc.value) == FirewallControllerService._IDEMPOTENCY_DIGEST_CORRUPT_MESSAGE
    assert backend.inspect_calls == before
    assert fresh_store.get_idempotency_record(key, 'inspect_policy')['request_digest'] == ''


def test_concurrent_replay_with_corrupt_digest_never_returns_cached_response():
    store = _store('r03-concurrent.db')
    backend = _CountingBackend(authorized_backend())
    key = 'r03-concurrent-key'
    _, base, _ = _setup_completed_inspect(store, backend, 'r03-concurrent', key)
    wrapper = _CorruptDigestStore(store, key, 'inspect_policy', '')
    svc = _svc(wrapper, backend, uids={1000, 2000}, gids={1000, 2000})
    before = backend.inspect_calls
    outcomes = []

    def replay():
        try:
            outcomes.append(('response', svc.inspect_policy(
                _new_request(base, idempotency_key=key)
            )))
        except Exception as exc:  # pragma: no cover - failure reporting
            outcomes.append(('error', exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(replay) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    assert len(outcomes) == 2
    assert all(kind == 'error' for kind, _ in outcomes)
    assert all(isinstance(exc, FirewallControllerIdempotencyError) for _, exc in outcomes)
    assert backend.inspect_calls == before
