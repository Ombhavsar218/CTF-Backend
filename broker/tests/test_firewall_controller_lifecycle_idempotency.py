import uuid
import json
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import FirewallControllerIdempotencyError
from broker.tests._helper_identity import authorized_backend


def _req(pid='p1', ver=1, digest='a'*64, key=None):
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
        'instance_id': 'i1',
        'network_id': 'n1',
    }


def test_lifecycle_verify_activates():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('pl1')
    res = svc.install_policy(req)
    assert res['status'] == 'ok'
    vreq = dict(req)
    vreq['request_id'] = str(uuid.uuid4())
    vreq['operation_id'] = str(uuid.uuid4())
    vreq['idempotency_key'] = 'vk1'
    vres = svc.verify_policy(vreq)
    assert vres['status'] == 'ok'
    rec = svc.ownership_store.get_by_policy('pl1', 1)
    assert rec['installation_state'] == 'ACTIVE'
    hist = svc.ownership_store.get_lifecycle_history(rec['ownership_record_id'])
    assert len(hist) >= 3


def test_idempotency_sqlite_same_key_same_request():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('pi1', key='ik-same')
    res1 = svc.install_policy(req)
    res2 = svc.install_policy(req)
    assert res1['status'] == res2['status']
    idem = svc.ownership_store.get_idempotency_record('ik-same', 'install_policy')
    assert idem is not None


def test_idempotency_conflict_sqlite():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('pi2', key='ik-diff')
    req2 = dict(req)
    req2['compiled_rule_digest'] = 'b'*64
    req2['request_id'] = str(uuid.uuid4())
    req2['operation_id'] = str(uuid.uuid4())
    svc.install_policy(req)
    try:
        svc.install_policy(req2)
        assert False
    except FirewallControllerIdempotencyError:
        pass


def test_revoke_requires_ownership_lc():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('pr1')
    try:
        svc.revoke_policy(req)
        assert False
    except PermissionError:
        pass


def test_inspect_requires_ownership_lc():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('pin1')
    try:
        svc.inspect_policy(req)
        assert False
    except PermissionError:
        pass
