import uuid
from broker.firewall_controller_service.mock_transport import MockControllerTransport
from broker.firewall_controller_service.peer_identity import PeerIdentity
from broker.firewall_controller_service.errors import FirewallControllerAuthError


def _req(pid='pt1', ver=1, digest='a'*64, key=None):
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


from broker.firewall_controller_service import FirewallControllerService
from broker.tests._helper_identity import authorized_backend


def test_transport_valid_identity():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    t = MockControllerTransport(service=svc)
    peer = PeerIdentity(uid=1000, gid=1000)
    r = t.install_policy(_req('ptt1'), peer)
    assert r['status'] == 'ok'


def test_transport_missing_identity():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    t = MockControllerTransport(service=svc)
    try:
        t.install_policy(_req('ptt2'), None)
        assert False
    except FirewallControllerAuthError:
        pass


def test_transport_unauthorized():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    t = MockControllerTransport(service=svc)
    peer = PeerIdentity(uid=9999, gid=9999)
    try:
        t.install_policy(_req('ptt3'), peer)
        assert False
    except FirewallControllerAuthError:
        pass


def test_transport_caller_identity_ignored():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    t = MockControllerTransport(service=svc)
    peer = PeerIdentity(uid=1000, gid=1000)
    req = _req('ptt4')
    req['peer_uid'] = 9999  # caller tries to override
    req['peer_gid'] = 9999
    r = t.install_policy(req, peer)
    assert r['status'] == 'ok'
