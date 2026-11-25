import uuid, tempfile, os
from broker.firewall_controller_service.mock_transport import MockControllerTransport
from broker.firewall_controller_service.peer_identity import PeerIdentity
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore

def _req(pid='ptt4x', ver=1, digest='a'*64, key=None):
    return {
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': key or str(uuid.uuid4()),
        'policy_id': pid,
        'policy_version': ver,
        'compiled_rule_digest': digest,
        'compiled': {},
        'instance_id': 'i1',
        'network_id': 'n1',
    }

db = tempfile.mktemp(suffix='.db')
svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, ownership_store=ControllerOwnershipStore(db_path=db))
t = MockControllerTransport(service=svc)
peer = PeerIdentity(uid=1000, gid=1000)
req = _req('ptt4x')
req['peer_uid'] = 9999
req['peer_gid'] = 9999
try:
    r = t.install_policy(req, peer)
    print(r)
except Exception as e:
    print(type(e))
    print(e)
    import traceback
    traceback.print_exc()
finally:
    try:
        os.unlink(db)
    except:
        pass
