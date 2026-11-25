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


def test_lifecycle_version_increments():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('pc1')
    svc.install_policy(req)
    rec = svc.ownership_store.get_by_policy('pc1', 1)
    v0 = rec.get('lifecycle_version') or 0
    vreq = dict(req)
    vreq['request_id'] = str(uuid.uuid4())
    vreq['operation_id'] = str(uuid.uuid4())
    vreq['idempotency_key'] = 'vkc1'
    svc.verify_policy(vreq)
    rec2 = svc.ownership_store.get_by_policy('pc1', 1)
    v1 = rec2.get('lifecycle_version') or 0
    assert v1 > v0


def test_idempotency_conflict_different_request():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('pc2', key='ikc2')
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


def test_same_key_completed_replay():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('pc3', key='ikc3')
    r1 = svc.install_policy(req)
    r2 = svc.install_policy(req)
    assert r1['status'] == r2['status']
