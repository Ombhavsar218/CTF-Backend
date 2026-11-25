"""Phase 2L.2G.3.4 — authoritative ownership binding remediation tests (mock-only).

These tests exercise the controller boundary only. No real transport, privileged helper,
firewall, routing, or host state is involved.
"""
import os
import tempfile
import uuid

import pytest

from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import FirewallControllerAuthError
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend


def _store():
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), 'ownership.db'))


def _svc(store=None, backend=None):
    return FirewallControllerService(
        allowed_uids={1000},
        allowed_gids={1000},
        ownership_store=store or _store(),
        backend=backend or authorized_backend(),
    )


def _req(pid='p1', ver=1, digest='a' * 64, key=None, inst='i1', net='n1', **extra):
    req = {
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': key or str(uuid.uuid4()),
        'policy_id': pid,
        'policy_version': ver,
        'compiled_rule_digest': digest,
        'compiled': {},
        'peer_uid': 1000,
        'peer_gid': 1000,
        'instance_id': inst,
        'network_id': net,
        'required_families': ['ipv4'],
    }
    req.update(extra)
    return req


def _new_request(base, **extra):
    req = dict(base)
    req['request_id'] = str(uuid.uuid4())
    req['operation_id'] = str(uuid.uuid4())
    req['idempotency_key'] = str(uuid.uuid4())
    req.update(extra)
    return req


def _install_active(svc, pid='p1', **extra):
    base = _req(pid=pid, **extra)
    assert svc.install_policy(base)['status'] == 'ok'
    assert svc.verify_policy(_new_request(base))['status'] == 'ok'
    return base


def _record(store, pid='p1', ver=1):
    rec = store.get_by_policy(pid, ver)
    assert rec is not None
    return rec


class _CapturingBackend:
    def __init__(self, inner):
        self.inner = inner
        self.requests = []

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

    def health_check(self, req):
        self.requests.append(dict(req))
        return self.inner.health_check(req)


class _SpoofingVerifyBackend(_CapturingBackend):
    def verify_policy(self, req):
        self.requests.append(dict(req))
        res = self.inner.verify_policy(req)
        if isinstance(res.get('result'), dict):
            res = dict(res)
            res['result'] = dict(res['result'])
            res['result']['instance_id'] = 'spoofed-instance'
            res['result']['network_id'] = 'spoofed-network'
            res['result']['ownership_record_id'] = 'spoofed-ownership'
            res['result']['canonical_policy_digest'] = 'b' * 64
        return res


class _MutatingVerifyBackend(_CapturingBackend):
    def __init__(self, inner, store, ownership_record_id):
        super().__init__(inner)
        self.store = store
        self.ownership_record_id = ownership_record_id

    def verify_policy(self, req):
        res = self.inner.verify_policy(req)
        self.store.db.execute(
            'UPDATE controller_ownership SET instance_id=? WHERE ownership_record_id=?',
            ('i-changed-during-backend', self.ownership_record_id),
        )
        return res


def test_evidence_uses_persisted_ownership_not_backend_or_caller_metadata():
    store = _store()
    backend = _SpoofingVerifyBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='ev1')
    rec = _record(store, 'ev1')

    evidence = store.get_evidence_by_policy('ev1', 1)
    assert evidence
    ev = evidence[0]
    assert ev['ownership_record_id'] == rec['ownership_record_id']
    assert ev['instance_id'] == 'i1'
    assert ev['network_id'] == 'n1'
    assert ev['canonical_policy_digest'] == 'a' * 64
    assert ev['instance_id'] != 'spoofed-instance'
    assert ev['network_id'] != 'spoofed-network'
    assert ev['ownership_record_id'] != 'spoofed-ownership'
    assert ev['canonical_policy_digest'] != 'b' * 64


def test_helper_requests_are_stamped_from_persisted_ownership():
    store = _store()
    backend = _CapturingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='cap1')
    rec = _record(store, 'cap1')

    sent = backend.requests[-1]
    assert sent['ownership_reference'] == rec['ownership_record_id']
    assert sent['ownership_record_id'] == rec['ownership_record_id']
    assert sent['instance_id'] == rec['instance_id'] == 'i1'
    assert sent['network_id'] == rec['network_id'] == 'n1'
    assert sent['compiled_rule_digest'] == rec['canonical_policy_digest'] == 'a' * 64


def test_correct_ownership_and_matching_digest_inspect_succeeds():
    svc = _svc()
    base = _install_active(svc, pid='ok1')
    res = svc.inspect_policy(_new_request(base))
    assert res['status'] == 'ok'
    assert res['result']['status'] == 'installed'


@pytest.mark.parametrize('field,value', [
    ('instance_id', 'spoofed-instance'),
    ('network_id', 'spoofed-network'),
    ('ownership_record_id', 'spoofed-ownership'),
    ('ownership_reference', 'spoofed-reference'),
])
def test_spoofed_ownership_metadata_rejected(field, value):
    svc = _svc()
    base = _install_active(svc, pid=f'spoof-{field}')
    req = _new_request(base, **{field: value})
    with pytest.raises(PermissionError):
        svc.inspect_policy(req)


@pytest.mark.parametrize('operation', ['inspect_policy', 'verify_policy', 'revoke_policy', 'remove_stale_policy'])
def test_mismatched_digest_rejected_for_every_ownership_operation(operation):
    store = _store()
    backend = _CapturingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid=f'dig-{operation}')
    req = _new_request(base, compiled_rule_digest='b' * 64)
    before = _record(store, f'dig-{operation}')['installation_state']
    with pytest.raises(PermissionError):
        getattr(svc, operation)(req)
    assert _record(store, f'dig-{operation}')['installation_state'] == before
    assert f'dig-{operation}' in backend.inner.ctrl.installed


@pytest.mark.parametrize('operation', ['inspect_policy', 'verify_policy', 'revoke_policy', 'remove_stale_policy'])
def test_missing_ownership_rejected(operation):
    svc = _svc()
    with pytest.raises(PermissionError):
        getattr(svc, operation)(_req(pid=f'absent-{operation}'))


def test_wrong_policy_id_or_version_rejected_as_missing_ownership():
    svc = _svc()
    _install_active(svc, pid='wrong-target')
    with pytest.raises(PermissionError):
        svc.inspect_policy(_new_request(_req(pid='different-policy')))
    with pytest.raises(PermissionError):
        svc.inspect_policy(_new_request(_req(pid='wrong-target', ver=2)))


def test_stale_policy_version_rejected():
    svc = _svc()
    _install_active(svc, pid='stale')
    stale = _req(pid='stale', ver=2)
    with pytest.raises(PermissionError):
        svc.inspect_policy(stale)


def test_ownership_record_belonging_to_another_instance_rejected():
    store = _store()
    svc = _svc(store)
    _install_active(svc, pid='inst-a', inst='i-a', net='n-a')
    _install_active(svc, pid='inst-b', inst='i-b', net='n-b')
    req = _new_request(_req(pid='inst-a', inst='i-b', net='n-b'))
    with pytest.raises(PermissionError):
        svc.inspect_policy(req)


def test_concurrent_authoritative_ownership_change_invalidates_old_request():
    store = _store()
    svc = _svc(store)
    base = _install_active(svc, pid='changing')
    rec = _record(store, 'changing')
    store.db.execute(
        'UPDATE controller_ownership SET instance_id=?, network_id=? WHERE ownership_record_id=?',
        ('i-changed', 'n-changed', rec['ownership_record_id']),
    )
    with pytest.raises(PermissionError):
        svc.inspect_policy(_new_request(base))


def test_ownership_change_during_backend_execution_prevents_promotion():
    store = _store()
    base = _req(pid='change-during-backend')
    backend = _MutatingVerifyBackend(authorized_backend(), store, None)

    # Install first so the ownership record exists, then wire the mutating backend.
    setup_svc = _svc(store, authorized_backend())
    assert setup_svc.install_policy(base)['status'] == 'ok'
    rec = _record(store, 'change-during-backend')
    backend.ownership_record_id = rec['ownership_record_id']

    svc = _svc(store, backend)
    with pytest.raises(PermissionError):
        svc.verify_policy(_new_request(base))

    current = _record(store, 'change-during-backend')
    assert current['installation_state'] == 'INSTALLING'
    assert current['instance_id'] == 'i-changed-during-backend'
    assert store.get_evidence_by_policy('change-during-backend', 1) == []


def test_reconciliation_rejects_mismatched_ownership_fields():
    store = _store()
    svc = _svc(store)
    base = _req(pid='recon-mismatch')
    assert svc.install_policy(base)['status'] == 'ok'
    rec_before = _record(store, 'recon-mismatch')
    with pytest.raises(PermissionError):
        svc.reconcile_pending_operations(_new_request(base, compiled_rule_digest='b' * 64))
    assert _record(store, 'recon-mismatch')['installation_state'] == rec_before['installation_state']


def test_reconciliation_requests_use_persisted_ownership_fields():
    store = _store()
    backend = _CapturingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _req(pid='recon-use')
    assert svc.install_policy(base)['status'] == 'ok'
    rec = _record(store, 'recon-use')
    res = svc.reconcile_pending_operations(_new_request(base))
    assert res['status'] == 'ok'
    inspect_reqs = [r for r in backend.requests if r.get('policy_id') == 'recon-use' and r.get('ownership_reference')]
    assert inspect_reqs
    sent = inspect_reqs[-1]
    assert sent['ownership_reference'] == rec['ownership_record_id']
    assert sent['instance_id'] == rec['instance_id']
    assert sent['network_id'] == rec['network_id']
    assert sent['compiled_rule_digest'] == rec['canonical_policy_digest']


def test_first_install_ignores_caller_supplied_ownership_reference():
    store = _store()
    svc = _svc(store)
    req = _req(pid='first-own', ownership_reference='caller-controlled')
    assert svc.install_policy(req)['status'] == 'ok'
    rec = _record(store, 'first-own')
    assert rec['ownership_record_id'] != 'caller-controlled'


def test_existing_ownership_reference_mismatch_rejected_on_install():
    svc = _svc()
    base = _install_active(svc, pid='reinstall-ref')
    req = _new_request(base, ownership_reference='caller-controlled')
    with pytest.raises(PermissionError):
        svc.install_policy(req)
