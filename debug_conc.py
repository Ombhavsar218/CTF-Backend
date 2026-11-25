import uuid
from broker.firewall_controller_service import FirewallControllerService

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

svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000})
req = _req('pc1')
svc.install_policy(req)
rec = svc.ownership_store.get_by_policy('pc1', 1)
print(type(rec))
v0 = rec.get('lifecycle_version') if hasattr(rec,'get') else 0
print(v0)
vreq = dict(req)
vreq['request_id'] = str(uuid.uuid4())
vreq['operation_id'] = str(uuid.uuid4())
vreq['idempotency_key'] = 'vkc1'
svc.verify_policy(vreq)
rec2 = svc.ownership_store.get_by_policy('pc1', 1)
print(type(rec2))
v1 = rec2.get('lifecycle_version') if hasattr(rec2,'get') else 0
print(v1)
