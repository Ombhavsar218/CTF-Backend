from broker.firewall_controller_service import FirewallControllerService
import uuid

def _req(pid='p100', ver=1, digest='a'*64, key=None):
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
req = _req('p100')
try:
    res = svc.install_policy(req)
    print(res)
except Exception as e:
    print(type(e))
    print(e)
    import traceback
    traceback.print_exc()
