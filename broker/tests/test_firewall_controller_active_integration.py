import uuid
import os, tempfile
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.authorization_strict import StrictAuthorizationProvider
from broker.firewall_controller_service.errors import FirewallControllerAuthError
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend


def _svc(**kw):
    db = os.path.join(tempfile.mkdtemp(), 'c.db')
    kw.setdefault('backend', authorized_backend())
    return FirewallControllerService(ownership_store=ControllerOwnershipStore(db_path=db), **kw)


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


def test_active_strict_auth_missing_identity():
    svc = _svc(allowed_uids={1000}, allowed_gids={1000})
    req = _req()
    req.pop('peer_uid')
    try:
        svc.install_policy(req)
        assert False
    except FirewallControllerAuthError:
        pass


def test_active_strict_auth_empty_allowlists_fail_closed():
    svc = _svc(allowed_uids=set(), allowed_gids={1000})
    try:
        svc.install_policy(_req())
        assert False
    except FirewallControllerAuthError:
        pass


def test_active_strict_auth_caller_header_rejected():
    svc = _svc(allowed_uids={1000}, allowed_gids={1000})
    req = _req()
    req['x_identity'] = 'admin'
    res = svc.install_policy(req)
    assert res['status'] == 'ok'


def test_active_strict_auth_unauthorized_never_reaches_backend():
    svc = _svc(allowed_uids={2000}, allowed_gids={1000})
    try:
        svc.install_policy(_req())
        assert False
    except FirewallControllerAuthError:
        pass
