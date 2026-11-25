"""Phase 2L.2G.3.10 — identifier-validation entry-point remediation tests.

Covers the two 3.9 findings:

- F-3.9-01: ``health_check`` must validate canonical caller identifiers before
  any ownership/idempotency store or backend access.
- F-3.9-02: ``reconcile_pending_operations`` must validate caller identifiers
  before its ownership lookup.

The tests are mock-only. They do not exercise real transport, privileged
helpers, firewalls, hosts, or production databases.
"""
import os
import tempfile
import uuid

import pytest

from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend


_OMIT = object()

_BAD_POLICY_IDS = [
    'p1\n',
    'p1\r',
    ' p1',
    'p1 ',
    'p1\t',
    'p1\x00',
    ['p1'],
    {'policy_id': 'p1'},
    123,
    True,
    b'p1',
    'a' * 129,
]

_BAD_OPTIONAL_IDS = [
    '',
    'i1\n',
    'i1\r',
    ' i1',
    'i1 ',
    'i1\t',
    'i1\x00',
    ['i1'],
    {'id': 'i1'},
    123,
    True,
    b'i1',
    'i' * 129,
]


class _CountingStore:
    """Count every method call made against the real store."""

    def __init__(self, inner):
        object.__setattr__(self, 'inner', inner)
        object.__setattr__(self, 'calls', [])

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if callable(attr):
            def wrapped(*args, **kwargs):
                self.calls.append(name)
                return attr(*args, **kwargs)
            return wrapped
        return attr


class _CountingBackend:
    """Count health and inspect calls without changing backend behavior."""

    def __init__(self, inner):
        self.inner = inner
        self.health_calls = 0
        self.inspect_calls = 0

    def health_check(self, req):
        self.health_calls += 1
        return self.inner.health_check(req)

    def inspect_policy(self, req):
        self.inspect_calls += 1
        return self.inner.inspect_policy(req)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _store(name='entrypoint.db'):
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), name))


def _svc(store, backend=None, validator=None):
    return FirewallControllerService(
        allowed_uids={1000},
        allowed_gids={1000},
        ownership_store=store,
        backend=backend or authorized_backend(),
        validator=validator,
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


def _health_req(**kwargs):
    return _req(pid=kwargs.pop('pid', 'health'), ver=kwargs.pop('ver', 0),
                digest=kwargs.pop('digest', '0' * 64), **kwargs)


# ---------------------------------------------------------------------------
# F-3.9-01 — health_check validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('bad_policy_id', _BAD_POLICY_IDS, ids=[repr(v) for v in _BAD_POLICY_IDS])
def test_health_check_rejects_invalid_policy_id_before_any_access(bad_policy_id):
    store = _CountingStore(_store('hc-policy.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    key = 'hc-invalid-policy'

    with pytest.raises(PermissionError) as exc:
        svc.health_check(_health_req(pid=bad_policy_id, key=key))

    assert 'Invalid policy_id' in str(exc.value)
    assert store.calls == []
    assert backend.health_calls == 0
    assert store.inner.get_idempotency_record(key, 'health_check') is None
    assert store.inner.list_ownerships() == []


@pytest.mark.parametrize('bad_instance_id', _BAD_OPTIONAL_IDS,
                         ids=[repr(v) for v in _BAD_OPTIONAL_IDS])
def test_health_check_rejects_invalid_instance_id_before_any_access(bad_instance_id):
    store = _CountingStore(_store('hc-instance.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    key = 'hc-invalid-instance'

    with pytest.raises(PermissionError) as exc:
        svc.health_check(_health_req(inst=bad_instance_id, key=key))

    assert 'Invalid instance_id' in str(exc.value)
    assert store.calls == []
    assert backend.health_calls == 0
    assert store.inner.get_idempotency_record(key, 'health_check') is None


@pytest.mark.parametrize('bad_network_id', _BAD_OPTIONAL_IDS,
                         ids=[repr(v) for v in _BAD_OPTIONAL_IDS])
def test_health_check_rejects_invalid_network_id_before_any_access(bad_network_id):
    store = _CountingStore(_store('hc-network.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    key = 'hc-invalid-network'

    with pytest.raises(PermissionError) as exc:
        svc.health_check(_health_req(net=bad_network_id, key=key))

    assert 'Invalid network_id' in str(exc.value)
    assert store.calls == []
    assert backend.health_calls == 0
    assert store.inner.get_idempotency_record(key, 'health_check') is None


@pytest.mark.parametrize('inst,net', [
    (_OMIT, _OMIT),
    (None, None),
])
def test_health_check_preserves_omitted_and_none_optional_semantics(inst, net):
    store = _store('hc-optional.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    key = 'hc-valid-optional'

    res = svc.health_check(_health_req(inst=inst, net=net, key=key))

    assert res['status'] == 'ok'
    assert res['controller_id']
    assert backend.health_calls == 1
    idem = store.get_idempotency_record(key, 'health_check')
    assert idem is not None
    assert idem['status'] == 'COMPLETED'
    assert idem['resource_key'] == 'health:0'


def test_health_check_valid_request_replays_idempotently():
    store = _store('hc-replay.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    req = _health_req(key='hc-valid-replay')

    first = svc.health_check(req)
    second = svc.health_check(req)

    assert first['status'] == second['status'] == 'ok'
    assert backend.health_calls == 1


def test_health_check_invalid_list_does_not_leak_broker_db_error():
    store = _CountingStore(_store('hc-list.db'))
    svc = _svc(store)

    with pytest.raises(PermissionError) as exc:
        svc.health_check(_health_req(pid=['p1'], key='hc-list-error'))

    assert 'Invalid policy_id' in str(exc.value)
    assert store.calls == []


# ---------------------------------------------------------------------------
# F-3.9-02 — reconcile_pending_operations validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('bad_policy_id', _BAD_POLICY_IDS, ids=[repr(v) for v in _BAD_POLICY_IDS])
def test_reconcile_rejects_invalid_policy_id_before_store_access(bad_policy_id):
    store = _CountingStore(_store('recon-policy.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)

    with pytest.raises(PermissionError) as exc:
        svc.reconcile_pending_operations(_req(pid=bad_policy_id, key='recon-invalid-policy'))

    assert 'Invalid policy_id' in str(exc.value)
    assert store.calls == []
    assert backend.inspect_calls == 0
    assert store.inner.list_ownerships() == []
    assert store.inner.get_lifecycle_history() == []


@pytest.mark.parametrize('bad_instance_id', _BAD_OPTIONAL_IDS,
                         ids=[repr(v) for v in _BAD_OPTIONAL_IDS])
def test_reconcile_rejects_invalid_instance_id_before_store_access(bad_instance_id):
    store = _CountingStore(_store('recon-instance.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)

    with pytest.raises(PermissionError) as exc:
        svc.reconcile_pending_operations(_req(pid='recon-instance', inst=bad_instance_id,
                                              key='recon-invalid-instance'))

    assert 'Invalid instance_id' in str(exc.value)
    assert store.calls == []
    assert backend.inspect_calls == 0


@pytest.mark.parametrize('bad_network_id', _BAD_OPTIONAL_IDS,
                         ids=[repr(v) for v in _BAD_OPTIONAL_IDS])
def test_reconcile_rejects_invalid_network_id_before_store_access(bad_network_id):
    store = _CountingStore(_store('recon-network.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)

    with pytest.raises(PermissionError) as exc:
        svc.reconcile_pending_operations(_req(pid='recon-network', net=bad_network_id,
                                              key='recon-invalid-network'))

    assert 'Invalid network_id' in str(exc.value)
    assert store.calls == []
    assert backend.inspect_calls == 0


def test_reconcile_invalid_input_does_not_mutate_seeded_lifecycle_or_evidence():
    inner = _store('recon-seeded.db')
    svc = _svc(inner)
    base = _req(pid='recon-seeded')
    assert svc.install_policy(base)['status'] == 'ok'
    assert svc.verify_policy(_new_request(base))['status'] == 'ok'

    before_rec = dict(inner.get_by_policy('recon-seeded', 1))
    before_history = list(inner.get_lifecycle_history())
    before_evidence = list(inner.get_evidence_by_policy('recon-seeded', 1))

    store = _CountingStore(inner)
    svc2 = _svc(store)
    with pytest.raises(PermissionError):
        svc2.reconcile_pending_operations(_new_request(base, instance_id=''))

    assert store.calls == []
    assert dict(inner.get_by_policy('recon-seeded', 1)) == before_rec
    assert list(inner.get_lifecycle_history()) == before_history
    assert list(inner.get_evidence_by_policy('recon-seeded', 1)) == before_evidence
    assert inner.get_idempotency_record(base['idempotency_key'], 'install_policy') is not None


def test_reconcile_invalid_list_does_not_leak_broker_db_error():
    store = _CountingStore(_store('recon-list.db'))
    svc = _svc(store)

    with pytest.raises(PermissionError) as exc:
        svc.reconcile_pending_operations(_req(pid=['p1'], key='recon-list-error'))

    assert 'Invalid policy_id' in str(exc.value)
    assert store.calls == []


def test_reconcile_valid_policy_specific_request_remains_functional():
    store = _store('recon-valid.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend=backend)
    base = _req(pid='recon-valid')
    assert svc.install_policy(base)['status'] == 'ok'
    assert svc.verify_policy(_new_request(base))['status'] == 'ok'

    res = svc.reconcile_pending_operations(_new_request(base))

    assert res['status'] == 'ok'
    assert any(item == {'policy_id': 'recon-valid', 'action': 'active_ok'}
               for item in res['result']['reconciled'])
    assert backend.inspect_calls >= 1


@pytest.mark.parametrize('inst,net', [
    (_OMIT, _OMIT),
    (None, None),
])
def test_reconcile_preserves_omitted_and_none_optional_semantics(inst, net):
    store = _store('recon-optional.db')
    svc = _svc(store)
    base = _req(pid='recon-optional')
    assert svc.install_policy(base)['status'] == 'ok'
    assert svc.verify_policy(_new_request(base))['status'] == 'ok'

    res = svc.reconcile_pending_operations(_req(pid='recon-optional', inst=inst, net=net))

    assert res['status'] == 'ok'
    assert any(item == {'policy_id': 'recon-optional', 'action': 'active_ok'}
               for item in res['result']['reconciled'])


class _NoopValidator:
    """Only for exercising the documented no-policy full-scan branch."""

    def validate(self, req):
        return None


def test_reconcile_full_scan_without_policy_id_remains_supported():
    store = _store('recon-scan.db')
    svc = _svc(store, validator=_NoopValidator())
    req = {
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': str(uuid.uuid4()),
        'peer_uid': 1000,
        'peer_gid': 1000,
    }

    res = svc.reconcile_pending_operations(req)

    assert res['status'] == 'ok'
    assert res['result']['reconciled'] == []


def test_reconcile_full_scan_rejects_supplied_invalid_optional_identifier():
    store = _CountingStore(_store('recon-scan-invalid.db'))
    svc = _svc(store, validator=_NoopValidator())
    req = {
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': str(uuid.uuid4()),
        'peer_uid': 1000,
        'peer_gid': 1000,
        'instance_id': 'i1\n',
    }

    with pytest.raises(PermissionError) as exc:
        svc.reconcile_pending_operations(req)

    assert 'Invalid instance_id' in str(exc.value)
    assert store.calls == []
