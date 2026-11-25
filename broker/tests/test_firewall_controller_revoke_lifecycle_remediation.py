"""Phase 2L.2G.3.4 — successful revoke lifecycle remediation tests (mock-only).

No real firewall, helper process, transport, or host state is exercised.
"""
import os
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.helper_contract import HelperOperation
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend


def _store():
    return ControllerOwnershipStore(db_path=os.path.join(tempfile.mkdtemp(), 'revoke.db'))


def _svc(store=None, backend=None):
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
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
    assert svc.ownership_store.get_by_policy(pid, 1)['installation_state'] == 'ACTIVE'
    return base


def _state(store, pid='p1', ver=1):
    rec = store.get_by_policy(pid, ver)
    assert rec is not None
    return rec['installation_state']


def _revoked_evidence(store, pid='p1', ver=1):
    return [e for e in store.get_evidence_by_policy(pid, ver) if e['verification_result'] == 'revoked']


class _CountingBackend:
    def __init__(self, inner):
        self.inner = inner
        self.revoke_calls = 0

    def revoke_policy(self, req):
        self.revoke_calls += 1
        return self.inner.revoke_policy(req)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _ReadbackFailBackend:
    def __init__(self, inner):
        self.inner = inner
        self.fail_readback = True
        self.revoke_calls = 0

    def inspect_policy(self, req):
        if self.fail_readback:
            raise RuntimeError('injected read-back failure')
        return self.inner.inspect_policy(req)

    def revoke_policy(self, req):
        self.revoke_calls += 1
        return self.inner.revoke_policy(req)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _MutatingRevokeBackend:
    def __init__(self, inner, store, ownership_record_id):
        self.inner = inner
        self.store = store
        self.ownership_record_id = ownership_record_id

    def revoke_policy(self, req):
        res = self.inner.revoke_policy(req)
        self.store.db.execute(
            'UPDATE controller_ownership SET instance_id=? WHERE ownership_record_id=?',
            ('i-changed-during-revoke', self.ownership_record_id),
        )
        return res

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _FaultStore(ControllerOwnershipStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_revocation_evidence = False
        self.fail_revoked_update = False

    def store_evidence(self, ev):
        if self.fail_revocation_evidence and ev.get('verification_result') == 'revoked':
            raise BrokerDBError('injected revocation evidence persistence failure')
        return super().store_evidence(ev)

    def update_ownership_state(self, ownership_record_id, new_state, prev_state=None, expected_version=None):
        if self.fail_revoked_update and new_state == 'REVOKED':
            raise BrokerDBError('injected lifecycle persistence failure')
        return super().update_ownership_state(ownership_record_id, new_state, prev_state, expected_version)


def test_successful_revoke_matching_digest_is_confirmed_and_evidence_gated():
    store = _store()
    backend = authorized_backend()
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-ok')
    rec = store.get_by_policy('rev-ok', 1)

    res = svc.revoke_policy(_new_request(base))
    assert res['status'] == 'ok'
    assert _state(store, 'rev-ok') == 'REVOKED'
    assert 'rev-ok' not in backend.ctrl.installed
    evs = _revoked_evidence(store, 'rev-ok')
    assert len(evs) == 1
    assert evs[0]['ownership_record_id'] == rec['ownership_record_id']
    assert evs[0]['instance_id'] == rec['instance_id'] == 'i1'
    assert evs[0]['network_id'] == rec['network_id'] == 'n1'
    assert evs[0]['canonical_policy_digest'] == rec['canonical_policy_digest'] == 'a' * 64

    history = store.get_lifecycle_history(rec['ownership_record_id'])
    assert any(h['prev_state'] == 'REVOKING' and h['new_state'] == 'REVOKED' for h in history)
    assert not any(h['prev_state'] == 'REVOKING' and h['new_state'] == 'REVOKING' for h in history)


def test_mismatched_digest_never_revokes():
    store = _store()
    backend = authorized_backend()
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-baddigest')

    with pytest.raises(PermissionError):
        svc.revoke_policy(_new_request(base, compiled_rule_digest='b' * 64))

    assert _state(store, 'rev-baddigest') == 'ACTIVE'
    assert 'rev-baddigest' in backend.ctrl.installed
    assert _revoked_evidence(store, 'rev-baddigest') == []


def test_ownership_change_during_revoke_prevents_revoked_promotion():
    store = _store()
    backend = authorized_backend()
    setup_svc = _svc(store, backend)
    base = _install_active(setup_svc, pid='rev-change-during')
    rec = store.get_by_policy('rev-change-during', 1)
    mutating = _MutatingRevokeBackend(backend, store, rec['ownership_record_id'])
    svc = _svc(store, mutating)

    with pytest.raises(PermissionError):
        svc.revoke_policy(_new_request(base))

    current = store.get_by_policy('rev-change-during', 1)
    assert current['installation_state'] == 'REVOKING'
    assert current['instance_id'] == 'i-changed-during-revoke'
    assert _revoked_evidence(store, 'rev-change-during') == []
    assert 'rev-change-during' not in backend.ctrl.installed


def test_repeated_revoke_same_idempotency_key_returns_original_response():
    store = _store()
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-repeat')
    req = _new_request(base, idempotency_key='rev-repeat-key')

    first = svc.revoke_policy(req)
    second = svc.revoke_policy(dict(req))
    assert first['status'] == 'ok'
    assert second == first
    assert backend.revoke_calls == 1
    assert _state(store, 'rev-repeat') == 'REVOKED'


def test_repeated_revoke_with_new_key_is_idempotent_without_backend_side_effect():
    store = _store()
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-newkey')
    assert svc.revoke_policy(_new_request(base))['status'] == 'ok'
    calls_after_success = backend.revoke_calls

    again = svc.revoke_policy(_new_request(base))
    assert again['status'] == 'ok'
    assert again['result']['already_revoked'] is True
    assert backend.revoke_calls == calls_after_success
    assert _state(store, 'rev-newkey') == 'REVOKED'


def test_backend_revoke_failure_keeps_revoking_and_retry_succeeds():
    store = _store()
    backend = authorized_backend()
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-fail')
    backend.ctrl.fail_revoke = True

    first = svc.revoke_policy(_new_request(base))
    assert first['status'] == 'error'
    assert _state(store, 'rev-fail') == 'REVOKING'
    assert 'rev-fail' in backend.ctrl.installed
    assert _revoked_evidence(store, 'rev-fail') == []

    backend.ctrl.fail_revoke = False
    second = svc.revoke_policy(_new_request(base))
    assert second['status'] == 'ok'
    assert _state(store, 'rev-fail') == 'REVOKED'
    assert 'rev-fail' not in backend.ctrl.installed


def test_backend_success_followed_by_readback_failure_is_not_revoked():
    store = _store()
    backend = _ReadbackFailBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-readback')

    res = svc.revoke_policy(_new_request(base))
    assert res['status'] == 'error'
    assert res['error_code'] == 'REVOKE_UNCONFIRMED'
    assert _state(store, 'rev-readback') == 'REVOKING'
    assert _revoked_evidence(store, 'rev-readback') == []
    assert 'rev-readback' not in backend.inner.ctrl.installed


def test_retry_after_readback_failure_does_not_issue_duplicate_revoke():
    store = _store()
    backend = _ReadbackFailBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-no-duplicate')

    assert svc.revoke_policy(_new_request(base))['error_code'] == 'REVOKE_UNCONFIRMED'
    assert backend.revoke_calls == 1
    assert _state(store, 'rev-no-duplicate') == 'REVOKING'

    # Read-back now succeeds and shows the backend already applied revocation.
    backend.fail_readback = False
    second = svc.revoke_policy(_new_request(base))
    assert second['status'] == 'ok'
    assert backend.revoke_calls == 1
    assert _state(store, 'rev-no-duplicate') == 'REVOKED'
    assert len(_revoked_evidence(store, 'rev-no-duplicate')) == 1


def test_evidence_persistence_failure_keeps_revoking_then_retry_succeeds():
    store = _FaultStore(db_path=os.path.join(tempfile.mkdtemp(), 'revoke-evidence.db'))
    backend = authorized_backend()
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-evidence')

    store.fail_revocation_evidence = True
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(_new_request(base))
    assert _state(store, 'rev-evidence') == 'REVOKING'
    assert _revoked_evidence(store, 'rev-evidence') == []

    store.fail_revocation_evidence = False
    assert svc.revoke_policy(_new_request(base))['status'] == 'ok'
    assert _state(store, 'rev-evidence') == 'REVOKED'


def test_lifecycle_persistence_failure_keeps_revoking_then_retry_succeeds():
    store = _FaultStore(db_path=os.path.join(tempfile.mkdtemp(), 'revoke-lifecycle.db'))
    backend = authorized_backend()
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-lifecycle')

    store.fail_revoked_update = True
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(_new_request(base))
    assert _state(store, 'rev-lifecycle') == 'REVOKING'
    assert len(_revoked_evidence(store, 'rev-lifecycle')) == 1

    store.fail_revoked_update = False
    assert svc.revoke_policy(_new_request(base))['status'] == 'ok'
    assert _state(store, 'rev-lifecycle') == 'REVOKED'
    assert len(_revoked_evidence(store, 'rev-lifecycle')) == 1


def test_restart_while_revoking_reconciles_with_evidence_before_revoked():
    store = _store()
    backend = _ReadbackFailBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-restart')

    # Backend revoke succeeds but the read-back fails, leaving REVOKING.
    assert svc.revoke_policy(_new_request(base))['status'] == 'error'
    assert _state(store, 'rev-restart') == 'REVOKING'

    # Simulated restart: a fresh controller service using the same persistence.
    backend.fail_readback = False
    svc2 = _svc(store, backend)
    res = svc2.reconcile_pending_operations(_new_request(base))
    assert res['status'] == 'ok'
    assert _state(store, 'rev-restart') == 'REVOKED'
    assert len(_revoked_evidence(store, 'rev-restart')) == 1


@pytest.mark.parametrize('injection', ['timeout', 'uncertain'])
def test_uncertain_backend_outcome_is_retryable(injection):
    store = _store()
    backend = authorized_backend()
    svc = _svc(store, backend)
    base = _install_active(svc, pid=f'rev-{injection}')

    target = backend.executor.inject_timeout if injection == 'timeout' else backend.executor.inject_uncertain
    target.add(HelperOperation.REVOKE_POLICY)
    first = svc.revoke_policy(_new_request(base))
    assert first['status'] == 'error'
    assert _state(store, f'rev-{injection}') == 'REVOKING'
    assert _revoked_evidence(store, f'rev-{injection}') == []

    target.discard(HelperOperation.REVOKE_POLICY)
    second = svc.revoke_policy(_new_request(base))
    assert second['status'] == 'ok'
    assert _state(store, f'rev-{injection}') == 'REVOKED'


def test_concurrent_revoke_requests_converge_without_invalid_transition():
    store = _store()
    backend = authorized_backend()
    svc = _svc(store, backend)
    base = _install_active(svc, pid='rev-concurrent')

    barrier = threading.Barrier(2)
    results = []
    errors = []
    lock = threading.Lock()

    def worker(idx):
        try:
            barrier.wait(timeout=5)
            res = svc.revoke_policy(_new_request(base, idempotency_key=f'rev-concurrent-{idx}'))
            with lock:
                results.append(res)
        except Exception as e:
            with lock:
                errors.append(e)

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(worker, i) for i in range(2)]
        for f in as_completed(futures):
            f.result(timeout=15)

    assert not errors, [type(e).__name__ for e in errors]
    assert all(r['status'] == 'ok' for r in results)
    assert _state(store, 'rev-concurrent') == 'REVOKED'
    assert len(_revoked_evidence(store, 'rev-concurrent')) >= 1
    assert 'rev-concurrent' not in backend.ctrl.installed
