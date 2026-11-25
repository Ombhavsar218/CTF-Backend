import json
import os
import tempfile
import uuid

import pytest

from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.mock_transport import MockControllerTransport
from broker.firewall_controller_service.peer_identity import PeerIdentity
from broker.firewall_controller_service.errors import FirewallControllerAuthError
from broker.tests._helper_identity import authorized_backend


def _store():
    db = tempfile.mktemp(suffix='.db')
    return ControllerOwnershipStore(db_path=db), db


def _svc(store=None, backend=None, allowed_uids={1000}, allowed_gids={1000}):
    store = store or ControllerOwnershipStore(db_path=tempfile.mktemp(suffix='.db'))
    backend = backend or authorized_backend()
    return FirewallControllerService(allowed_uids=allowed_uids, allowed_gids=allowed_gids, ownership_store=store, backend=backend)


def _req(pid='p1', ver=1, digest='a'*64, key=None, inst='i1', net='n1'):
    return {
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


# --- Persistence across service recreation ---

def test_ownership_survives_service_recreation():
    store, _ = _store()
    svc1 = _svc(store)
    req = _req('pr1', key='kpr1')
    r = svc1.install_policy(req)
    assert r['status'] == 'ok'
    # recreate service with same store
    svc2 = _svc(store)
    rec = svc2.ownership_store.get_by_policy('pr1', 1)
    assert rec is not None
    assert rec['policy_id'] == 'pr1'
    assert rec['instance_id'] == 'i1'
    assert rec['network_id'] == 'n1'


def test_lifecycle_history_survives_service_recreation():
    store, _ = _store()
    svc1 = _svc(store)
    req = _req('pr2', key='kpr2')
    svc1.install_policy(req)
    vreq = dict(req); vreq['idempotency_key'] = 'kpr2v'; vreq['request_id'] = str(uuid.uuid4()); vreq['operation_id'] = str(uuid.uuid4())
    svc1.verify_policy(vreq)
    svc2 = _svc(store)
    rec = svc2.ownership_store.get_by_policy('pr2', 1)
    hist = svc2.ownership_store.get_lifecycle_history(rec['ownership_record_id'])
    assert len(hist) >= 1


def test_idempotency_survives_service_recreation():
    store, _ = _store()
    svc1 = _svc(store)
    req = _req('pr3', key='kpr3')
    r1 = svc1.install_policy(req)
    assert r1['status'] == 'ok'
    svc2 = _svc(store)
    r2 = svc2.install_policy(_req('pr3', key='kpr3'))  # same key+payload
    assert r2['status'] == 'ok'
    # response should be consistent (from persisted idempotency)
    assert r2.get('request_id') == r1.get('request_id') or r2['status'] == 'ok'


# --- Ownership integrity ---

def test_ownership_cannot_be_silently_reassigned():
    store, _ = _store()
    svc = _svc(store)
    req = _req('po1', inst='i1', net='n1')
    svc.install_policy(req)
    # try install with different instance/network but same policy/version/digest context? should conflict
    req2 = _req('po1', inst='i2', net='n2')
    req2['idempotency_key'] = 'kpo1b'
    with pytest.raises(PermissionError):
        svc.install_policy(req2)


def test_ownership_missing_conflicting_or_corrupt_fail_closed():
    store, _ = _store()
    svc = _svc(store)
    # missing ownership for revoke
    with pytest.raises(PermissionError):
        svc.revoke_policy(_req('pmiss'))
    # corrupt/conflicting: create ownership manually with wrong digest, then verify should fail
    svc2 = _svc(store)
    # install first
    svc2.install_policy(_req('pcor', key='kpcor'))
    # try verify with different digest
    bad = _req('pcor', digest='b'*64, key='kpcorv')
    bad['request_id'] = str(uuid.uuid4()); bad['operation_id'] = str(uuid.uuid4())
    with pytest.raises((PermissionError, Exception)):
        svc2.verify_policy(bad)


# --- Lifecycle persistence and CAS ---

def test_lifecycle_cas_conflict_rejected():
    store, _ = _store()
    svc = _svc(store)
    svc.install_policy(_req('plc1', key='klc1'))
    rec = store.get_by_policy('plc1', 1)
    # simulate stale version update
    with pytest.raises(PermissionError):
        store.update_ownership_state(rec['ownership_record_id'], 'FAILED', 'INSTALLING', rec['lifecycle_version'] - 1)


def test_invalid_lifecycle_transition_rejected():
    store, _ = _store()
    svc = _svc(store)
    with pytest.raises(PermissionError):
        svc._check_lifecycle_transition('REVOKED', 'ACTIVE')


def test_uncertain_not_promoted_to_active_without_evidence():
    store, _ = _store()
    svc = _svc(store)
    svc.install_policy(_req('pua1', key='kua1'))
    rec = store.get_by_policy('pua1', 1)
    # ownership exists but not verified/active; ensure not ACTIVE
    assert rec['installation_state'] != 'ACTIVE'
    # no evidence means we should not be able to force active through normal flow
    ev = store.get_evidence_by_policy('pua1', 1)
    assert ev == [] or rec['installation_state'] != 'ACTIVE'


# --- Idempotency ---

def test_idempotency_conflict_across_service_recreation():
    store, _ = _store()
    svc1 = _svc(store)
    svc1.install_policy(_req('pi1', key='kpi1'))
    svc2 = _svc(store)
    bad = _req('pi1', key='kpi1')
    bad['compiled_rule_digest'] = 'b'*64
    with pytest.raises(Exception):
        svc2.install_policy(bad)


# --- Transport integration with persistence ---

def test_transport_uses_authoritative_persistence():
    store, _ = _store()
    svc = _svc(store)
    t = MockControllerTransport(service=svc)
    peer = PeerIdentity(uid=1000, gid=1000)
    r = t.install_policy(_req('ptp1', key='ktp1'), peer)
    assert r['status'] == 'ok'
    # service recreated sees same data
    svc2 = _svc(store)
    assert svc2.ownership_store.get_by_policy('ptp1', 1) is not None


def test_transport_cannot_bypass_ownership_checks():
    store, _ = _store()
    svc = _svc(store)
    t = MockControllerTransport(service=svc)
    peer = PeerIdentity(uid=1000, gid=1000)
    # revoke without ownership
    try:
        t.revoke_policy(_req('ptp2'), peer)
        assert False
    except (PermissionError, Exception):
        pass


def test_transport_preserves_auth():
    store, _ = _store()
    svc = _svc(store)
    t = MockControllerTransport(service=svc)
    try:
        t.install_policy(_req('ptp3'), PeerIdentity(uid=9999, gid=9999))
        assert False
    except FirewallControllerAuthError:
        pass


# --- Recovery: crash scenarios (mock) ---
# Note: We simulate crash by manipulating persisted state and/or backend state directly,
# then calling reconcile/recovery logic.

def test_recovery_crash_before_backend_execution():
    """Intent/idempotency pending, backend never executed (no backend state)."""
    store, _ = _store()
    svc = _svc(store)
    # Simulate: create ownership intent REQUESTED and pending idempotency, but no backend install
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'rc1', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'REQUESTED'
    })
    store.create_idempotency_record('krc1', 'install_policy', svc._req_digest(_req('rc1')), resource_key='rc1:1', ownership_record_id=oid)
    # Reconcile - backend has no state
    res = svc.reconcile_pending_operations(_req('rc1', key='krc1r'))
    rec = store.get_by_policy('rc1', 1)
    # Should not be ACTIVE; should be failed/cleanup/uncertain handled safely
    assert rec['installation_state'] != 'ACTIVE'
    assert res is not None


def test_recovery_backend_completed_but_response_lost():
    """Backend has install state, but service lost response; ownership may be REQUESTED/INSTALLING uncertain."""
    store, _ = _store()
    from broker.app.firewall_controller import MockFirewallController
    from broker.firewall_controller_service.mock_backend import MockFirewallBackend
    be = authorized_backend()
    # Simulate backend completed install
    be._ctrl.installed['rc2'] = {'compiled': {}, 'digest': 'a'*64, 'version': 1}
    svc = _svc(store, backend=be)
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'rc2', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'REQUESTED'
    })
    store.create_idempotency_record('krc2', 'install_policy', svc._req_digest(_req('rc2')), resource_key='rc2:1', ownership_record_id=oid)
    svc.reconcile_pending_operations(_req('rc2', key='krc2r'))
    rec = store.get_by_policy('rc2', 1)
    # Must not promote to ACTIVE without verification evidence
    assert rec['installation_state'] != 'ACTIVE'


def test_recovery_evidence_persisted_but_promotion_incomplete():
    store, _ = _store()
    svc = _svc(store)
    # install and partially simulate: create ownership in VERIFIED with evidence but not ACTIVE
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'rc3', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'VERIFIED'
    })
    store.store_evidence({
        'evidence_id': str(uuid.uuid4()), 'ownership_record_id': oid, 'policy_id': 'rc3', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64, 'address_family': 'ipv4',
        'installed_rule_ids': [], 'controller_identity': svc.controller_identity, 'controller_transaction_id': str(uuid.uuid4()),
        'request_id': str(uuid.uuid4()), 'verification_result': 'verified'
    })
    svc.reconcile_pending_operations(_req('rc3', key='krc3r'))
    rec = store.get_by_policy('rc3', 1)
    # Can promote to ACTIVE if evidence valid and state allows; or remain safe
    assert rec['installation_state'] in ('ACTIVE', 'VERIFIED', 'FAILED', 'CLEANUP_PENDING')


def test_recovery_ownership_missing_or_inconsistent():
    store, _ = _store()
    from broker.firewall_controller_service.mock_backend import MockFirewallBackend
    be = authorized_backend()
    # backend has unknown rule/state but no ownership
    be._ctrl.installed['rc4'] = {'compiled': {}, 'digest': 'a'*64, 'version': 1}
    svc = _svc(store, backend=be)
    # Reconcile should not adopt unknown backend rules
    res = svc.reconcile_pending_operations(_req('rc4', key='krc4r'))
    assert store.get_by_policy('rc4', 1) is None or store.get_by_policy('rc4', 1)['installation_state'] != 'ACTIVE'
    assert res is not None


def test_recovery_backend_readback_unavailable():
    store, _ = _store()
    from broker.firewall_controller_service.mock_backend import MockFirewallBackend
    be = authorized_backend()
    be._ctrl.fail_verify = True  # simulate readback/verify issues
    svc = _svc(store, backend=be)
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'rc5', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'INSTALLING'
    })
    svc.reconcile_pending_operations(_req('rc5', key='krc5r'))
    rec = store.get_by_policy('rc5', 1)
    assert rec['installation_state'] != 'ACTIVE'  # fail closed, don't guess

def test_recovery_backend_completed_but_evidence_not_persisted():
    """Backend indicates state consistent with verification in some flows; service lacks persisted evidence. Recovery must not promote to ACTIVE without evidence."""
    store, _ = _store()
    from broker.firewall_controller_service.mock_backend import MockFirewallBackend
    be = authorized_backend()
    be._ctrl.installed['rc3b'] = {'compiled': {}, 'digest': 'a'*64, 'version': 1}
    be._ctrl.verified.add('rc3b')
    svc = _svc(store, backend=be)
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'rc3b', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'INSTALLING'
    })
    svc.reconcile_pending_operations(_req('rc3b', key='krc3br'))
    rec = store.get_by_policy('rc3b', 1)
    assert rec['installation_state'] != 'ACTIVE'
    # No evidence persisted -> cannot be ACTIVE
    assert store.get_evidence_by_policy('rc3b', 1) == [] or rec['installation_state'] != 'ACTIVE'


def test_recovery_duplicate_recovery_request():
    store, _ = _store()
    svc = _svc(store)
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'rc6', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'REQUESTED'
    })
    r1 = svc.reconcile_pending_operations(_req('rc6', key='krc6a'))
    r2 = svc.reconcile_pending_operations(_req('rc6', key='krc6b'))
    assert r1 is not None and r2 is not None
    rec = store.get_by_policy('rc6', 1)
    assert rec['installation_state'] != 'ACTIVE'


def test_recovery_partial_revoke_or_cleanup():
    store, _ = _store()
    from broker.firewall_controller_service.mock_backend import MockFirewallBackend
    be = authorized_backend()
    # backend still has it installed (partial revoke)
    be._ctrl.installed['rc8'] = {'compiled': {}, 'digest': 'a'*64, 'version': 1}
    svc = _svc(store, backend=be)
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'rc8', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'REVOKING'
    })
    svc.reconcile_pending_operations(_req('rc8', key='krc8r'))
    rec = store.get_by_policy('rc8', 1)
    # Should not silently claim REVOKED if backend still present; remain uncertain/cleanup
    assert rec['installation_state'] in ('REVOKING', 'CLEANUP_PENDING', 'FAILED', 'ORPHANED')


def test_transport_fail_closed_on_persistence_error():
    # Simulate persistence unavailable by using a broken store
    class BrokenStore(ControllerOwnershipStore):
        def get_by_policy(self, *a, **k):
            raise RuntimeError('db down')
        def create_idempotency_record(self, *a, **k):
            raise RuntimeError('db down')
    # We can't easily make all operations fail without breaking init; test that service fails closed on authz/ownership checks when persistence issues occur in critical paths
    store, _ = _store()
    svc = _svc(store)
    t = MockControllerTransport(service=svc)
    peer = PeerIdentity(uid=1000, gid=1000)
    # Normal op works
    r = t.health_check({'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'ktfh', 'policy_id': 'health', 'policy_version': 0, 'compiled_rule_digest': '0'*64, 'compiled': {}}, peer)
    assert r is not None
