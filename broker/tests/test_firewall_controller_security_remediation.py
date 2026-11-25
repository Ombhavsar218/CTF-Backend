import uuid
import os
import tempfile
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.authorization_strict import StrictAuthorizationProvider
from broker.firewall_controller_service.errors import FirewallControllerAuthError
from broker.app.firewall_controller_contract import FirewallControllerRequestError, FirewallControllerIdempotencyError
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
    }


def test_strict_auth_missing_identity():
    svc = _svc(auth=StrictAuthorizationProvider({1000},{1000}))
    req = _req()
    req.pop('peer_uid')
    try:
        svc.install_policy(req)
        assert False
    except FirewallControllerAuthError:
        pass


def test_strict_auth_unauthorized_uid():
    svc = _svc(auth=StrictAuthorizationProvider({2000},{1000}))
    try:
        svc.install_policy(_req())
        assert False
    except FirewallControllerAuthError:
        pass


def test_strict_auth_caller_trusted_rejected():
    svc = _svc(auth=StrictAuthorizationProvider({1000},{1000}))
    req = _req()
    req['caller_trusted'] = True
    try:
        svc.install_policy(req)
        assert False
    except FirewallControllerAuthError:
        pass


def test_strict_auth_header_ignored():
    svc = _svc(auth=StrictAuthorizationProvider({1000},{1000}))
    req = _req()
    req['x_identity'] = 'admin'
    # should still work if peer identity valid
    res = svc.install_policy(req)
    assert res['status'] == 'ok'
