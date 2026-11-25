"""Phase 2L.2G.3.6 — revoke recovery, idempotency integrity, and fail-closed hardening.

Mock-only controller/helper-boundary tests. No real transport, privileged helper,
firewall backend, routing, host, systemd, or production database is touched.
"""
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from broker.app.db import BrokerDBError
from broker.app.firewall_controller_contract import FirewallControllerRequestError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.authorization_strict import StrictAuthorizationProvider
from broker.firewall_controller_service.errors import (
    FirewallControllerAuthError,
    FirewallControllerBackendError,
    FirewallControllerIdempotencyError,
)
from broker.firewall_controller_service.helper_contract import (
    HelperContractError,
    HelperOperation,
    SCHEMA_VERSION,
    validate_helper_request,
)
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _store(name='hardening.db', cls=ControllerOwnershipStore):
    return cls(db_path=os.path.join(tempfile.mkdtemp(), name))


def _svc(store=None, backend=None, uids=None, gids=None, **kwargs):
    return FirewallControllerService(
        allowed_uids=uids if uids is not None else {1000},
        allowed_gids=gids if gids is not None else {1000},
        ownership_store=store or _store(),
        backend=backend or authorized_backend(),
        **kwargs,
    )


def _req(pid='p1', ver=1, digest='a' * 64, key=None, inst='i1', net='n1',
         family='ipv4', include_family=True, uid=1000, gid=1000, **extra):
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
        'instance_id': inst,
        'network_id': net,
    }
    if include_family and family is not None:
        req['address_family'] = family
        req['required_families'] = [family]
    req.update(extra)
    return req


def _new_request(base, **extra):
    req = dict(base)
    req['request_id'] = str(uuid.uuid4())
    req['operation_id'] = str(uuid.uuid4())
    req['idempotency_key'] = str(uuid.uuid4())
    req.update(extra)
    return req


def _install_active(svc, pid='p1', family='ipv4', **extra):
    base = _req(pid=pid, family=family, **extra)
    assert svc.install_policy(base)['status'] == 'ok'
    assert svc.verify_policy(_new_request(base))['status'] == 'ok'
    assert _state(svc.ownership_store, pid) == 'ACTIVE'
    return base


def _state(store, pid='p1', ver=1):
    rec = store.get_by_policy(pid, ver)
    assert rec is not None
    return rec['installation_state']


def _record(store, pid='p1', ver=1):
    rec = store.get_by_policy(pid, ver)
    assert rec is not None
    return rec


def _revoked_evidence(store, pid='p1', ver=1):
    return [e for e in store.get_evidence_by_policy(pid, ver)
            if e['verification_result'] == 'revoked']


def _seed_terminal_revoked(store, pid='p1', family='ipv4', evidence=True, overrides=None):
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': pid, 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a' * 64,
        'installed_rule_ids': [], 'address_family': family, 'installation_state': 'REVOKED',
    })
    if evidence:
        ev = {
            'evidence_id': str(uuid.uuid4()), 'ownership_record_id': oid,
            'policy_id': pid, 'policy_version': 1, 'instance_id': 'i1',
            'network_id': 'n1', 'canonical_policy_digest': 'a' * 64,
            'address_family': family, 'installed_rule_ids': [],
            'controller_identity': 'test', 'controller_transaction_id': str(uuid.uuid4()),
            'request_id': str(uuid.uuid4()), 'verification_result': 'revoked',
        }
        ev.update(overrides or {})
        store.store_evidence(ev)
    return oid


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


class _CountingBackend:
    def __init__(self, inner):
        self.inner = inner
        self.revoke_calls = 0
        self.install_calls = 0
        self.inspect_calls = 0

    def revoke_policy(self, req):
        self.revoke_calls += 1
        return self.inner.revoke_policy(req)

    def install_policy(self, req):
        self.install_calls += 1
        return self.inner.install_policy(req)

    def inspect_policy(self, req):
        self.inspect_calls += 1
        return self.inner.inspect_policy(req)

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


class _RevokeThenFailBackend:
    """Backend applies revoke, then the controller "loses" the response."""

    def __init__(self, inner):
        self.inner = inner
        self.revoke_calls = 0

    def revoke_policy(self, req):
        self.revoke_calls += 1
        self.inner.revoke_policy(req)
        raise RuntimeError('simulated lost response after backend success')

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _ExplodingRevokeBackend:
    def __init__(self, inner):
        self.inner = inner
        self.revoke_calls = 0

    def revoke_policy(self, req):
        self.revoke_calls += 1
        raise AssertionError('revoke must not be executed')

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _FaultStore(ControllerOwnershipStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_revocation_evidence = False
        self.fail_revoked_update = False
        self.fail_reconciliation_status = False
        self.fail_lifecycle_history = False
        self.fail_complete_idempotency = False

    def store_evidence(self, ev):
        if self.fail_revocation_evidence and ev.get('verification_result') == 'revoked':
            raise BrokerDBError('injected revocation evidence persistence failure')
        return super().store_evidence(ev)

    def update_ownership_state(self, ownership_record_id, new_state, prev_state=None, expected_version=None):
        if self.fail_revoked_update and new_state == 'REVOKED':
            raise BrokerDBError('injected lifecycle persistence failure')
        return super().update_ownership_state(ownership_record_id, new_state, prev_state, expected_version)

    def update_reconciliation_status(self, ownership_record_id, status):
        if self.fail_reconciliation_status:
            raise BrokerDBError('injected reconciliation status persistence failure')
        return super().update_reconciliation_status(ownership_record_id, status)

    def record_lifecycle_transition(self, *args, **kwargs):
        if self.fail_lifecycle_history:
            raise BrokerDBError('injected lifecycle history persistence failure')
        return super().record_lifecycle_transition(*args, **kwargs)

    def complete_idempotency_record(self, *args, **kwargs):
        if self.fail_complete_idempotency:
            raise BrokerDBError('injected idempotency response persistence failure')
        return super().complete_idempotency_record(*args, **kwargs)


class _BrokenReadStore(ControllerOwnershipStore):
    def get_by_policy(self, policy_id, policy_version):
        raise BrokerDBError('injected ownership read failure')


def _force_revoking(store, backend, pid='p1'):
    """Move an ACTIVE record to REVOKING and remove the backend policy."""
    rec = _record(store, pid)
    store.update_ownership_state(rec['ownership_record_id'], 'REVOKING', 'ACTIVE', rec['lifecycle_version'])
    inner = getattr(backend, 'inner', backend)
    inner.ctrl.installed.pop(pid, None)


# ---------------------------------------------------------------------------
# F-01 — Same-key uncertain revoke retry
# ---------------------------------------------------------------------------

def test_same_key_retry_after_backend_failure_reads_back_and_recovers():
    store = _store('f01-backend-fail.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f01-fail')
    key = 'f01-fail-key'
    req = _new_request(base, idempotency_key=key)

    backend.inner.ctrl.fail_revoke = True
    first = svc.revoke_policy(req)
    assert first['status'] == 'error'
    assert _state(store, 'f01-fail') == 'REVOKING'
    assert _revoked_evidence(store, 'f01-fail') == []

    backend.inner.ctrl.fail_revoke = False
    second = svc.revoke_policy(dict(req))
    assert second['status'] == 'ok'
    assert _state(store, 'f01-fail') == 'REVOKED'
    assert 'f01-fail' not in backend.inner.ctrl.installed
    assert len(_revoked_evidence(store, 'f01-fail')) == 1
    assert backend.revoke_calls >= 2


def test_same_key_retry_after_backend_success_lost_response_recovers_without_duplicate_revoke():
    store = _store('f01-lost-response.db')
    backend = _RevokeThenFailBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f01-lost')
    key = 'f01-lost-key'
    req = _new_request(base, idempotency_key=key)

    with pytest.raises(FirewallControllerBackendError):
        svc.revoke_policy(req)
    assert _state(store, 'f01-lost') == 'REVOKING'
    assert 'f01-lost' not in backend.inner.ctrl.installed
    assert backend.revoke_calls == 1

    second = svc.revoke_policy(dict(req))
    assert second['status'] == 'ok'
    assert _state(store, 'f01-lost') == 'REVOKED'
    assert backend.revoke_calls == 1  # read-back confirmed; no duplicate destructive call
    assert len(_revoked_evidence(store, 'f01-lost')) == 1


def test_same_key_retry_after_readback_failure_recovers():
    store = _store('f01-readback.db')
    backend = _ReadbackFailBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f01-readback')
    key = 'f01-readback-key'
    req = _new_request(base, idempotency_key=key)

    first = svc.revoke_policy(req)
    assert first['status'] == 'error'
    assert first['error_code'] == 'REVOKE_UNCONFIRMED'
    assert _state(store, 'f01-readback') == 'REVOKING'
    assert backend.revoke_calls == 1

    backend.fail_readback = False
    second = svc.revoke_policy(dict(req))
    assert second['status'] == 'ok'
    assert _state(store, 'f01-readback') == 'REVOKED'
    assert backend.revoke_calls == 1
    assert len(_revoked_evidence(store, 'f01-readback')) == 1


def test_same_key_retry_after_evidence_persistence_failure_recovers():
    store = _FaultStore(db_path=os.path.join(tempfile.mkdtemp(), 'f01-evidence.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f01-evidence')
    key = 'f01-evidence-key'
    req = _new_request(base, idempotency_key=key)

    store.fail_revocation_evidence = True
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(req)
    assert _state(store, 'f01-evidence') == 'REVOKING'
    assert _revoked_evidence(store, 'f01-evidence') == []

    store.fail_revocation_evidence = False
    second = svc.revoke_policy(dict(req))
    assert second['status'] == 'ok'
    assert _state(store, 'f01-evidence') == 'REVOKED'
    assert len(_revoked_evidence(store, 'f01-evidence')) == 1


def test_same_key_retry_after_lifecycle_persistence_failure_recovers():
    store = _FaultStore(db_path=os.path.join(tempfile.mkdtemp(), 'f01-lifecycle.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f01-lifecycle')
    key = 'f01-lifecycle-key'
    req = _new_request(base, idempotency_key=key)

    store.fail_revoked_update = True
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(req)
    assert _state(store, 'f01-lifecycle') == 'REVOKING'
    assert len(_revoked_evidence(store, 'f01-lifecycle')) == 1

    store.fail_revoked_update = False
    second = svc.revoke_policy(dict(req))
    assert second['status'] == 'ok'
    assert _state(store, 'f01-lifecycle') == 'REVOKED'
    assert len(_revoked_evidence(store, 'f01-lifecycle')) == 1


def test_same_key_retry_when_backend_state_unknown_stays_uncertain():
    store = _store('f01-unknown.db')
    backend = _ReadbackFailBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f01-unknown')
    key = 'f01-unknown-key'
    req = _new_request(base, idempotency_key=key)

    first = svc.revoke_policy(req)
    assert first['status'] == 'error'
    second = svc.revoke_policy(dict(req))
    assert second['status'] == 'error'
    assert second['error_code'] == 'REVOKE_UNCONFIRMED'
    assert _state(store, 'f01-unknown') == 'REVOKING'
    assert _revoked_evidence(store, 'f01-unknown') == []
    assert 'f01-unknown' not in backend.inner.ctrl.installed


def test_same_key_retry_when_backend_still_present_reissues_revoke():
    store = _store('f01-present.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f01-present')
    key = 'f01-present-key'
    req = _new_request(base, idempotency_key=key)

    backend.inner.ctrl.fail_revoke = True
    assert svc.revoke_policy(req)['status'] == 'error'
    assert 'f01-present' in backend.inner.ctrl.installed

    backend.inner.ctrl.fail_revoke = False
    assert svc.revoke_policy(dict(req))['status'] == 'ok'
    assert _state(store, 'f01-present') == 'REVOKED'
    assert 'f01-present' not in backend.inner.ctrl.installed
    assert backend.revoke_calls >= 2


def test_concurrent_same_key_revoke_retries_converge():
    store = _store('f01-concurrent.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f01-concurrent')
    key = 'f01-concurrent-key'

    backend.inner.ctrl.fail_revoke = True
    assert svc.revoke_policy(_new_request(base, idempotency_key=key))['status'] == 'error'
    backend.inner.ctrl.fail_revoke = False

    barrier = threading.Barrier(2)
    results = []
    errors = []
    lock = threading.Lock()

    def worker():
        try:
            barrier.wait(timeout=5)
            res = svc.revoke_policy(_new_request(base, idempotency_key=key))
            with lock:
                results.append(res)
        except Exception as e:  # pragma: no cover - failure reporting
            with lock:
                errors.append(e)

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(worker) for _ in range(2)]
        for f in as_completed(futures):
            f.result(timeout=20)

    assert not errors, [type(e).__name__ for e in errors]
    assert all(r['status'] == 'ok' for r in results)
    assert _state(store, 'f01-concurrent') == 'REVOKED'
    assert 'f01-concurrent' not in backend.inner.ctrl.installed
    assert len(_revoked_evidence(store, 'f01-concurrent')) >= 1


def test_different_key_retry_after_failure_still_recovers():
    store = _store('f01-newkey.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f01-newkey')

    backend.inner.ctrl.fail_revoke = True
    assert svc.revoke_policy(_new_request(base))['status'] == 'error'
    backend.inner.ctrl.fail_revoke = False
    assert svc.revoke_policy(_new_request(base))['status'] == 'ok'
    assert _state(store, 'f01-newkey') == 'REVOKED'


# ---------------------------------------------------------------------------
# F-02 — Persistence failures are propagated, not masked
# ---------------------------------------------------------------------------

def test_reconcile_propagates_revocation_evidence_persistence_failure():
    store = _FaultStore(db_path=os.path.join(tempfile.mkdtemp(), 'f02-evidence.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f02-evidence')
    _force_revoking(store, backend, 'f02-evidence')

    store.fail_revocation_evidence = True
    res = svc.reconcile_pending_operations(_new_request(base, pid='f02-evidence'))
    assert res['status'] == 'error'
    assert res['error_code'] == 'RECONCILIATION_PERSISTENCE_FAILURE'
    assert any(e.get('error_code') == 'PERSISTENCE_FAILURE' for e in res['result']['errors'])
    assert _state(store, 'f02-evidence') == 'REVOKING'
    assert _revoked_evidence(store, 'f02-evidence') == []


def test_reconcile_propagates_revoked_lifecycle_persistence_failure():
    store = _FaultStore(db_path=os.path.join(tempfile.mkdtemp(), 'f02-lifecycle.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f02-lifecycle')
    _force_revoking(store, backend, 'f02-lifecycle')

    store.fail_revoked_update = True
    res = svc.reconcile_pending_operations(_new_request(base, pid='f02-lifecycle'))
    assert res['status'] == 'error'
    assert res['error_code'] == 'RECONCILIATION_PERSISTENCE_FAILURE'
    assert _state(store, 'f02-lifecycle') == 'REVOKING'
    assert len(_revoked_evidence(store, 'f02-lifecycle')) == 1


def test_reconcile_propagates_reconciliation_status_persistence_failure():
    store = _FaultStore(db_path=os.path.join(tempfile.mkdtemp(), 'f02-status.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f02-status')
    assert 'f02-status' in backend.inner.ctrl.installed

    store.fail_reconciliation_status = True
    res = svc.reconcile_pending_operations(_new_request(base, pid='f02-status'))
    assert res['status'] == 'error'
    assert res['error_code'] == 'RECONCILIATION_PERSISTENCE_FAILURE'
    assert any(e.get('error_code') == 'PERSISTENCE_FAILURE' for e in res['result']['errors'])
    assert _state(store, 'f02-status') == 'ACTIVE'


def test_reconcile_preserves_backend_uncertainty_as_non_persistence_outcome():
    store = _store('f02-backend-uncertain.db')
    backend = _ReadbackFailBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f02-backend-uncertain')
    _force_revoking(store, backend, 'f02-backend-uncertain')

    backend.fail_readback = True
    res = svc.reconcile_pending_operations(_new_request(base, pid='f02-backend-uncertain'))
    assert res['status'] == 'ok'
    assert any(u.get('reason') == 'backend_readback_unavailable_during_revoke'
               for u in res['result']['uncertain'])
    assert res['result']['errors'] == []
    assert _state(store, 'f02-backend-uncertain') == 'REVOKING'


def test_reconcile_recovers_after_database_restoration():
    store = _FaultStore(db_path=os.path.join(tempfile.mkdtemp(), 'f02-restore.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f02-restore')
    _force_revoking(store, backend, 'f02-restore')

    store.fail_revocation_evidence = True
    assert svc.reconcile_pending_operations(_new_request(base, pid='f02-restore'))['status'] == 'error'
    assert _state(store, 'f02-restore') == 'REVOKING'

    store.fail_revocation_evidence = False
    res = svc.reconcile_pending_operations(_new_request(base, pid='f02-restore'))
    assert res['status'] == 'ok'
    assert _state(store, 'f02-restore') == 'REVOKED'
    assert len(_revoked_evidence(store, 'f02-restore')) == 1


def test_idempotency_response_persistence_failure_is_not_masked_and_retry_recovers():
    store = _FaultStore(db_path=os.path.join(tempfile.mkdtemp(), 'f02-idem.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f02-idem')
    key = 'f02-idem-key'
    req = _new_request(base, idempotency_key=key)

    store.fail_complete_idempotency = True
    with pytest.raises(BrokerDBError):
        svc.revoke_policy(req)
    assert _state(store, 'f02-idem') == 'REVOKED'
    assert len(_revoked_evidence(store, 'f02-idem')) == 1

    store.fail_complete_idempotency = False
    res = svc.revoke_policy(dict(req))
    assert res['status'] == 'ok'
    assert _state(store, 'f02-idem') == 'REVOKED'
    assert backend.revoke_calls == 1


def test_reconcile_ownership_lookup_failure_is_not_treated_as_absence():
    store = _BrokenReadStore(db_path=os.path.join(tempfile.mkdtemp(), 'f02-lookup.db'))
    svc = _svc(store)
    with pytest.raises(BrokerDBError):
        svc.reconcile_pending_operations(_req(pid='f02-lookup'))


# ---------------------------------------------------------------------------
# F-03 — Unknown lifecycle states fail closed but do not disappear
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('bad_state', ['BOGUS_STATE', '', 'revoked'])
def test_reconcile_reports_unknown_lifecycle_state_without_rewriting(bad_state):
    store = _store('f03-unknown.db')
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'f03', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a' * 64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'REQUESTED',
    })
    conn = sqlite3.connect(store.db.db_path)
    conn.execute('UPDATE controller_ownership SET installation_state=? WHERE ownership_record_id=?',
                 (bad_state, oid))
    conn.commit()
    conn.close()

    svc = _svc(store)
    res = svc.reconcile_pending_operations(_req(pid='f03'))
    assert res['status'] == 'ok'
    assert any(u.get('reason') == 'corrupt_ownership_state' for u in res['result']['uncertain'])
    assert _state(store, 'f03') == bad_state


def test_reconcile_preserves_valid_records_when_another_state_is_corrupt():
    store = _store('f03-mixed.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    _install_active(svc, pid='f03-valid')

    bad_oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': bad_oid, 'policy_id': 'f03-bad', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a' * 64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'BOGUS_STATE',
    })

    # Reconcile the corrupt record; the unrelated valid record must be preserved
    # exactly as persisted (no auto-adoption or rewrite).
    res = svc.reconcile_pending_operations(_req(pid='f03-bad'))
    assert res['status'] == 'ok'
    reasons = {u.get('reason') for u in res['result']['uncertain']}
    assert 'corrupt_ownership_state' in reasons
    assert _state(store, 'f03-bad') == 'BOGUS_STATE'
    assert _state(store, 'f03-valid') == 'ACTIVE'

    # The valid record still reconciles normally afterwards.
    valid = svc.reconcile_pending_operations(_req(pid='f03-valid'))
    assert valid['status'] == 'ok'
    assert any(r.get('action') == 'active_ok' for r in valid['result']['reconciled'])


# ---------------------------------------------------------------------------
# F-04 — Address family is part of authoritative ownership identity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('operation', ['inspect_policy', 'verify_policy', 'revoke_policy', 'remove_stale_policy'])
def test_cross_family_substitution_rejected_for_every_ownership_operation(operation):
    store = _store('f04-family.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid=f'f04-{operation}', family='ipv6')
    before = _state(store, f'f04-{operation}')

    spoof = _new_request(base, address_family='ipv4', required_families=['ipv4'])
    with pytest.raises(PermissionError):
        getattr(svc, operation)(spoof)
    assert _state(store, f'f04-{operation}') == before
    assert f'f04-{operation}' in backend.inner.ctrl.installed


def test_required_family_mismatch_without_explicit_address_family_rejected():
    store = _store('f04-required.db')
    svc = _svc(store)
    base = _install_active(svc, pid='f04-required', family='ipv6')
    spoof = _new_request(base, address_family=None, required_families=['ipv4'])
    with pytest.raises(PermissionError):
        svc.inspect_policy(spoof)


def test_persisted_family_change_invalidates_in_flight_ownership_identity():
    store = _store('f04-mutate.db')
    svc = _svc(store)
    base = _install_active(svc, pid='f04-mutate', family='ipv4')
    rec = _record(store, 'f04-mutate')
    store.db.execute(
        'UPDATE controller_ownership SET address_family=? WHERE ownership_record_id=?',
        ('ipv6', rec['ownership_record_id']),
    )
    with pytest.raises(PermissionError):
        svc.inspect_policy(_new_request(base))
    assert _record(store, 'f04-mutate')['address_family'] == 'ipv6'


def test_reconcile_requires_matching_evidence_family_for_active_promotion():
    store = _store('f04-evidence.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'f04-ev', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a' * 64,
        'installed_rule_ids': [], 'address_family': 'ipv6', 'installation_state': 'VERIFIED',
    })
    store.store_evidence({
        'evidence_id': str(uuid.uuid4()), 'ownership_record_id': oid,
        'policy_id': 'f04-ev', 'policy_version': 1, 'instance_id': 'i1',
        'network_id': 'n1', 'canonical_policy_digest': 'a' * 64,
        'address_family': 'ipv4', 'installed_rule_ids': [],
        'controller_identity': 'test', 'controller_transaction_id': str(uuid.uuid4()),
        'request_id': str(uuid.uuid4()), 'verification_result': 'verified',
    })
    res = svc.reconcile_pending_operations(_req(pid='f04-ev', family='ipv6'))
    assert res['status'] == 'ok'
    assert any(u.get('reason') == 'verified_without_valid_evidence'
               for u in res['result']['uncertain'])
    assert _state(store, 'f04-ev') == 'VERIFIED'


def test_revocation_evidence_requires_matching_family():
    store = _store('f04-revoked-family.db')
    svc = _svc(store, _ExplodingRevokeBackend(authorized_backend()))
    # Seed with mismatched evidence family (append-only evidence cannot be mutated in place).
    _seed_terminal_revoked(store, pid='f04-revoked', family='ipv4', overrides={'address_family': 'ipv6'})
    with pytest.raises(PermissionError):
        svc.revoke_policy(_req(pid='f04-revoked', family='ipv4'))
    assert _state(store, 'f04-revoked') == 'REVOKED'


# ---------------------------------------------------------------------------
# F-05 — Complete canonical idempotency digest
# ---------------------------------------------------------------------------

def test_same_key_same_compiled_body_replays():
    store = _store('f05-same.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    req = _req(pid='f05-same', key='f05-same-key', compiled={'rules': []})
    assert svc.install_policy(req)['status'] == 'ok'
    assert svc.install_policy(dict(req))['status'] == 'ok'
    assert backend.install_calls == 1


def test_same_key_different_compiled_body_is_rejected():
    store = _store('f05-body.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    req = _req(pid='f05-body', key='f05-body-key', compiled={'rules': []})
    assert svc.install_policy(req)['status'] == 'ok'
    changed = dict(req)
    changed['compiled'] = {'rules': [{'digest': 'b' * 64}]}
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(changed)
    assert backend.install_calls == 1


def test_same_key_different_nested_compiled_content_is_rejected():
    store = _store('f05-nested.db')
    svc = _svc(store)
    req = _req(pid='f05-nested', key='f05-nested-key', compiled={'metadata': {'digest': 'c' * 64}})
    assert svc.install_policy(req)['status'] == 'ok'
    changed = dict(req)
    changed['compiled'] = {'metadata': {'digest': 'd' * 64}}
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(changed)


@pytest.mark.parametrize('field,value', [
    ('address_family', 'ipv6'),
    ('required_families', ['ipv6']),
    ('instance_id', 'i-changed'),
    ('network_id', 'n-changed'),
    ('policy_version', 2),
    ('compiled_rule_digest', 'b' * 64),
])
def test_same_key_changed_security_field_is_rejected(field, value):
    store = _store('f05-field.db')
    svc = _svc(store)
    req = _req(pid='f05-field', key='f05-field-key')
    assert svc.install_policy(req)['status'] == 'ok'
    changed = dict(req)
    changed[field] = value
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.install_policy(changed)


def test_same_key_different_operation_uses_separate_idempotency_scope():
    store = _store('f05-op.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f05-op')
    key = 'f05-op-key'
    assert svc.inspect_policy(_new_request(base, idempotency_key=key))['status'] == 'ok'
    assert svc.revoke_policy(_new_request(base, idempotency_key=key))['status'] == 'ok'
    assert _state(store, 'f05-op') == 'REVOKED'


def test_key_reuse_after_process_restart_replays_bound_response():
    store = _store('f05-restart.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    req = _req(pid='f05-restart', key='f05-restart-key')
    first = svc.install_policy(req)
    assert first['status'] == 'ok'

    svc2 = _svc(store, backend)
    second = svc2.install_policy(dict(req))
    assert second == first
    assert backend.install_calls == 1


def test_unsupported_compiled_value_type_fails_closed():
    svc = _svc(_store('f05-unsupported.db'))
    req = _req(pid='f05-unsupported', key='f05-unsupported-key',
               compiled={'metadata': {'value': object()}})
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(req)


def test_noncanonical_nan_compiled_value_fails_closed():
    svc = _svc(_store('f05-nan.db'))
    req = _req(pid='f05-nan', key='f05-nan-key',
               compiled={'metadata': {'value': float('nan')}})
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(req)


def test_non_string_compiled_dict_key_fails_closed():
    svc = _svc(_store('f05-keytype.db'))
    req = _req(pid='f05-keytype', key='f05-keytype-key',
               compiled={'metadata': {1: 'value'}})
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(req)


# ---------------------------------------------------------------------------
# F-06 — Already-REVOKED records require valid revocation evidence
# ---------------------------------------------------------------------------

def test_already_revoked_without_evidence_is_rejected():
    store = _store('f06-no-evidence.db')
    backend = _ExplodingRevokeBackend(authorized_backend())
    svc = _svc(store, backend)
    _seed_terminal_revoked(store, pid='f06-no-evidence', evidence=False)

    with pytest.raises(PermissionError):
        svc.revoke_policy(_req(pid='f06-no-evidence'))
    assert _state(store, 'f06-no-evidence') == 'REVOKED'
    assert _revoked_evidence(store, 'f06-no-evidence') == []
    assert backend.revoke_calls == 0


def test_already_revoked_with_mismatched_evidence_is_rejected():
    store = _store('f06-mismatch.db')
    svc = _svc(store, _ExplodingRevokeBackend(authorized_backend()))
    _seed_terminal_revoked(store, pid='f06-mismatch',
                           overrides={'canonical_policy_digest': 'b' * 64})
    with pytest.raises(PermissionError):
        svc.revoke_policy(_req(pid='f06-mismatch'))


def test_already_revoked_with_wrong_family_evidence_is_rejected():
    store = _store('f06-family.db')
    svc = _svc(store, _ExplodingRevokeBackend(authorized_backend()))
    _seed_terminal_revoked(store, pid='f06-family', family='ipv4',
                           overrides={'address_family': 'ipv6'})
    with pytest.raises(PermissionError):
        svc.revoke_policy(_req(pid='f06-family', family='ipv4'))


def test_already_revoked_with_valid_evidence_is_idempotent_success():
    store = _store('f06-valid.db')
    backend = _ExplodingRevokeBackend(authorized_backend())
    svc = _svc(store, backend)
    _seed_terminal_revoked(store, pid='f06-valid')
    res = svc.revoke_policy(_req(pid='f06-valid'))
    assert res['status'] == 'ok'
    assert res['result']['already_revoked'] is True
    assert backend.revoke_calls == 0
    assert _state(store, 'f06-valid') == 'REVOKED'


def test_reconcile_revoked_without_evidence_is_uncertain():
    store = _store('f06-reconcile.db')
    svc = _svc(store)
    _seed_terminal_revoked(store, pid='f06-reconcile', evidence=False)
    res = svc.reconcile_pending_operations(_req(pid='f06-reconcile'))
    assert res['status'] == 'ok'
    assert any(u.get('reason') == 'revoked_without_valid_evidence'
               for u in res['result']['uncertain'])
    assert _state(store, 'f06-reconcile') == 'REVOKED'
    assert _revoked_evidence(store, 'f06-reconcile') == []


def test_reconcile_revoked_with_valid_evidence_is_reconciled():
    store = _store('f06-reconcile-valid.db')
    svc = _svc(store)
    _seed_terminal_revoked(store, pid='f06-reconcile-valid')
    res = svc.reconcile_pending_operations(_req(pid='f06-reconcile-valid'))
    assert res['status'] == 'ok'
    assert any(r.get('action') == 'already_revoked' for r in res['result']['reconciled'])


# ---------------------------------------------------------------------------
# F-07 — Strict full-string identifier and digest validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('bad_digest', [
    'a' * 64 + '\n',
    'a' * 64 + '\r',
    'a' * 64 + '\r\n',
    'a' * 64 + ' ',
    ' ' + 'a' * 64,
    'a' * 63,
    'a' * 65,
    'g' * 64,
    'a' * 63 + 'g',
])
def test_helper_contract_rejects_non_exact_digest(bad_digest):
    with pytest.raises(HelperContractError):
        validate_helper_request(_hreq(compiled_rule_digest=bad_digest),
                                HelperOperation.INSTALL_POLICY)


@pytest.mark.parametrize('good_digest', ['a' * 64, 'A' * 64, '0123456789abcdef' * 4])
def test_helper_contract_accepts_exact_digest(good_digest):
    validate_helper_request(_hreq(compiled_rule_digest=good_digest),
                            HelperOperation.INSTALL_POLICY)


@pytest.mark.parametrize('field', ['request_id', 'operation_id', 'idempotency_key'])
@pytest.mark.parametrize('bad_value', ['abc\n', 'abc\r', 'abc\r\n', ' abc', 'abc ', 'ab c', 'abc!'])
def test_helper_contract_rejects_non_exact_identifiers(field, bad_value):
    with pytest.raises(HelperContractError):
        validate_helper_request(_hreq(**{field: bad_value}), HelperOperation.INSTALL_POLICY)


def test_helper_contract_accepts_identifier_boundaries():
    validate_helper_request(_hreq(request_id='a'), HelperOperation.INSTALL_POLICY)
    validate_helper_request(_hreq(request_id='a' * 128), HelperOperation.INSTALL_POLICY)
    with pytest.raises(HelperContractError):
        validate_helper_request(_hreq(request_id='a' * 129), HelperOperation.INSTALL_POLICY)


def test_controller_rejects_digest_with_trailing_newline():
    svc = _svc(_store('f07-controller.db'))
    req = _req(pid='f07-controller', digest='a' * 64 + '\n')
    # J.15: canonical digest validation is enforced fail-closed at contract/request boundary.
    with pytest.raises(Exception):
        svc.install_policy(req)
    assert svc.ownership_store.get_by_policy('f07-controller', 1) is None


def test_controller_rejects_nonhex_stored_digest():
    store = _store('f07-stored.db')
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'f07-stored', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a' * 64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'ACTIVE',
    })
    store.db.execute(
        'UPDATE controller_ownership SET canonical_policy_digest=? WHERE ownership_record_id=?',
        ('a' * 64 + '\n', oid),
    )
    svc = _svc(store)
    with pytest.raises(PermissionError):
        svc.inspect_policy(_req(pid='f07-stored'))


# ---------------------------------------------------------------------------
# F-08 — Explicit empty controller operation allowlist denies everything
# ---------------------------------------------------------------------------

def test_strict_auth_none_operations_uses_documented_supported_default():
    auth = StrictAuthorizationProvider(allowed_uids={1000}, allowed_gids={1000},
                                       allowed_operations=None)
    assert 'install_policy' in auth.allowed_operations
    assert auth.authorize({'peer_uid': 1000, 'peer_gid': 1000}, 'install_policy') is True


def test_strict_auth_explicit_empty_operations_denies_every_operation():
    auth = StrictAuthorizationProvider(allowed_uids={1000}, allowed_gids={1000},
                                       allowed_operations=set())
    assert auth.allowed_operations == set()
    for operation in ('health_check', 'install_policy', 'inspect_policy',
                      'verify_policy', 'revoke_policy', 'remove_stale_policy',
                      'reconcile_pending_operations'):
        with pytest.raises(FirewallControllerAuthError):
            auth.authorize({'peer_uid': 1000, 'peer_gid': 1000}, operation)


def test_strict_auth_partial_operations_allows_only_configured_operation():
    auth = StrictAuthorizationProvider(allowed_uids={1000}, allowed_gids={1000},
                                       allowed_operations={'health_check'})
    assert auth.authorize({'peer_uid': 1000, 'peer_gid': 1000}, 'health_check') is True
    with pytest.raises(FirewallControllerAuthError):
        auth.authorize({'peer_uid': 1000, 'peer_gid': 1000}, 'install_policy')


def test_strict_auth_complete_operations_allows_all_supported_operations():
    operations = {
        'health_check', 'install_policy', 'inspect_policy', 'verify_policy',
        'revoke_policy', 'remove_stale_policy', 'reconcile_pending_operations',
    }
    auth = StrictAuthorizationProvider(allowed_uids={1000}, allowed_gids={1000},
                                       allowed_operations=operations)
    for operation in operations:
        assert auth.authorize({'peer_uid': 1000, 'peer_gid': 1000}, operation) is True


def test_service_explicit_empty_operations_denies_every_request():
    svc = _svc(_store('f08-empty.db'), allowed_operations=set())
    with pytest.raises(FirewallControllerAuthError):
        svc.install_policy(_req(pid='f08-empty'))


def test_service_omitted_operations_uses_default_and_allows_install():
    store = _store('f08-default.db')
    svc = _svc(store)
    assert svc.install_policy(_req(pid='f08-default'))['status'] == 'ok'
    assert _state(store, 'f08-default') in ('REQUESTED', 'INSTALLING')


# ---------------------------------------------------------------------------
# F-09 — Ownership-bound idempotency replay
# ---------------------------------------------------------------------------

def test_replay_same_identity_and_same_ownership_returns_cached_response():
    store = _store('f09-same.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f09-same')
    key = 'f09-same-key'
    first = svc.inspect_policy(_new_request(base, idempotency_key=key))
    second = svc.inspect_policy(_new_request(base, idempotency_key=key))
    assert second == first
    assert backend.inspect_calls >= 1


def test_replay_different_identity_is_rejected():
    store = _store('f09-identity.db')
    svc = _svc(store, uids={1000, 2000}, gids={1000, 2000})
    base = _install_active(svc, pid='f09-identity')
    key = 'f09-identity-key'
    req = _new_request(base, idempotency_key=key, peer_uid=1000, peer_gid=1000)
    assert svc.inspect_policy(req)['status'] == 'ok'
    other = _new_request(base, idempotency_key=key, peer_uid=2000, peer_gid=2000)
    with pytest.raises(FirewallControllerIdempotencyError):
        svc.inspect_policy(other)


def test_replay_after_ownership_record_replacement_is_rejected():
    store = _store('f09-replaced.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _install_active(svc, pid='f09-replaced')
    key = 'f09-replaced-key'
    req = _new_request(base, idempotency_key=key)
    assert svc.inspect_policy(req)['status'] == 'ok'

    old = _record(store, 'f09-replaced')
    store.db.execute('DELETE FROM controller_ownership WHERE ownership_record_id=?',
                     (old['ownership_record_id'],))
    new_oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': new_oid, 'policy_id': 'f09-replaced', 'policy_version': 1,
        'instance_id': old['instance_id'], 'network_id': old['network_id'],
        'canonical_policy_digest': old['canonical_policy_digest'],
        'installed_rule_ids': [], 'address_family': old['address_family'],
        'installation_state': 'ACTIVE',
    })

    with pytest.raises(PermissionError):
        svc.inspect_policy(_new_request(base, idempotency_key=key))


def test_replay_after_in_place_instance_change_with_omitted_fields_is_rejected():
    store = _store('f09-instance.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _req(pid='f09-instance', inst=None, net=None)
    assert svc.install_policy(base)['status'] == 'ok'
    assert svc.verify_policy(_new_request(base))['status'] == 'ok'
    key = 'f09-instance-key'
    replay_req = _new_request(base, idempotency_key=key)
    assert svc.inspect_policy(replay_req)['status'] == 'ok'
    rec = _record(store, 'f09-instance')
    store.db.execute(
        'UPDATE controller_ownership SET instance_id=? WHERE ownership_record_id=?',
        ('i-changed', rec['ownership_record_id']),
    )
    with pytest.raises(PermissionError):
        svc.inspect_policy(_new_request(base, idempotency_key=key))


def test_replay_after_family_change_with_omitted_family_is_rejected():
    store = _store('f09-family.db')
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _req(pid='f09-family', include_family=False)
    assert svc.install_policy(base)['status'] == 'ok'
    assert svc.verify_policy(_new_request(base))['status'] == 'ok'
    key = 'f09-family-key'
    replay_req = _new_request(base, idempotency_key=key)
    assert svc.inspect_policy(replay_req)['status'] == 'ok'
    rec = _record(store, 'f09-family')
    store.db.execute(
        'UPDATE controller_ownership SET address_family=? WHERE ownership_record_id=?',
        ('ipv6', rec['ownership_record_id']),
    )
    with pytest.raises(PermissionError):
        svc.inspect_policy(_new_request(base, idempotency_key=key))


class _SignalingStore(ControllerOwnershipStore):
    """Blocks a replay after idempotency lookup so ownership can change concurrently."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.signal_key = None
        self.signal = threading.Event()
        self.release = threading.Event()
        self._signaled = False

    def get_idempotency_record(self, idempotency_key, operation_type):
        rec = super().get_idempotency_record(idempotency_key, operation_type)
        if (self.signal_key is not None and idempotency_key == self.signal_key
                and not self._signaled):
            self._signaled = True
            self.signal.set()
            self.release.wait(timeout=5)
        return rec


def test_concurrent_replay_and_ownership_change_never_returns_stale_success():
    store = _SignalingStore(db_path=os.path.join(tempfile.mkdtemp(), 'f09-concurrent.db'))
    backend = _CountingBackend(authorized_backend())
    svc = _svc(store, backend)
    base = _req(pid='f09-concurrent', inst=None, net=None)
    assert svc.install_policy(base)['status'] == 'ok'
    assert svc.verify_policy(_new_request(base))['status'] == 'ok'

    key = 'f09-concurrent-key'
    replay_req = _new_request(base, idempotency_key=key)
    assert svc.inspect_policy(replay_req)['status'] == 'ok'

    rec = _record(store, 'f09-concurrent')
    store.signal_key = key
    store._signaled = False
    store.signal.clear()
    store.release.clear()

    outcome = {}

    def replier():
        try:
            outcome['response'] = svc.inspect_policy(_new_request(base, idempotency_key=key))
        except Exception as e:  # pragma: no cover - failure reporting
            outcome['error'] = e

    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(replier)
        assert store.signal.wait(timeout=5)
        store.db.execute(
            'UPDATE controller_ownership SET instance_id=? WHERE ownership_record_id=?',
            ('i-changed-concurrently', rec['ownership_record_id']),
        )
        store.release.set()
        future.result(timeout=10)

    assert 'error' in outcome
    assert isinstance(outcome['error'], PermissionError)
    assert 'response' not in outcome
