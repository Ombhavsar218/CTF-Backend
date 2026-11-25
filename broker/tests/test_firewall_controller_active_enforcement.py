import uuid
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.errors import FirewallControllerAuthError
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


def test_install_creates_ownership():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('p100')
    res = svc.install_policy(req)
    assert res['status'] == 'ok'
    rec = svc.ownership_store.get_by_policy('p100', 1)
    assert rec is not None


def test_revoke_requires_ownership():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('p200')
    try:
        svc.revoke_policy(req)
        assert False
    except PermissionError:
        pass


def test_verify_requires_ownership():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('p300')
    vreq = dict(req)
    vreq['request_id'] = str(uuid.uuid4())
    vreq['operation_id'] = str(uuid.uuid4())
    vreq['idempotency_key'] = 'v1'
    try:
        svc.verify_policy(vreq)
        assert False
    except PermissionError:
        pass


def test_idempotency_conflict_active():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('p400', key='ik1')
    req2 = dict(req)
    req2['compiled_rule_digest'] = 'b'*64
    req2['request_id'] = str(uuid.uuid4())
    req2['operation_id'] = str(uuid.uuid4())
    svc.install_policy(req)
    try:
        svc.install_policy(req2)
        assert False
    except Exception as e:
        assert 'conflict' in str(e).lower() or type(e).__name__ == 'FirewallControllerIdempotencyError'
