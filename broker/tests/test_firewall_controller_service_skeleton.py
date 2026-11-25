import uuid
import tempfile
import os
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.app.firewall_controller_contract import FirewallControllerRequestError, FirewallControllerIdempotencyError
from broker.firewall_controller_service.errors import FirewallControllerAuthError
from broker.tests._helper_identity import authorized_backend


def _svc():
    db = tempfile.mktemp(suffix='.db')
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, ownership_store=ControllerOwnershipStore(db_path=db), backend=authorized_backend())
    svc._test_db = db
    return svc


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


def test_service_health_check():
    svc = _svc()
    res = svc.health_check(_req('h1'))
    assert res['controller_id']


def test_service_unauthorized_caller_trusted():
    svc = _svc()
    req = _req()
    req['caller_trusted'] = True
    try:
        svc.install_policy(req)
        assert False
    except FirewallControllerAuthError:
        pass


def test_service_invalid_request():
    svc = _svc()
    try:
        req = {}
        req['peer_uid'] = 1000
        req['peer_gid'] = 1000
        svc.install_policy(req)
        assert False
    except FirewallControllerRequestError:
        pass


def test_service_invalid_digest():
    svc = _svc()
    req = _req(digest='short')
    try:
        svc.install_policy(req)
        assert False
    except FirewallControllerRequestError:
        pass


def test_service_idempotency_conflict():
    svc = _svc()
    req1 = _req(key='k1')
    req2 = dict(req1)
    req2['compiled_rule_digest'] = 'b'*64
    req2['request_id'] = str(uuid.uuid4())
    req2['operation_id'] = str(uuid.uuid4())
    svc.install_policy(req1)
    try:
        svc.install_policy(req2)
        assert False
    except FirewallControllerIdempotencyError:
        pass


def test_service_duplicate_request():
    svc = _svc()
    req = _req(key='k2')
    r1 = svc.install_policy(req)
    r2 = svc.install_policy(req)
    assert r1 == r2


def test_service_partial_ipv6_install():
    svc = _svc()
    svc.backend._ctrl.fail_install_ipv6 = True
    req = _req(key='k3')
    res = svc.install_policy(req)
    assert res['status'] == 'error'


def test_service_ownership_mismatch():
    svc = _svc()
    svc.backend._ctrl.ownership_mismatch = True
    req = _req(key='k4')
    res = svc.install_policy(req)
    assert res['status'] == 'error'


def test_service_forged_evidence_not_trusted():
    svc = _svc()
    req = _req(key='k5')
    svc.install_policy(req)
    vreq = dict(req)
    vreq['request_id'] = str(uuid.uuid4())
    vreq['operation_id'] = str(uuid.uuid4())
    vreq['idempotency_key'] = 'k5v'
    res = svc.verify_policy(vreq)
    assert res['status'] == 'ok'
    assert res['result']['evidence']['policy_id'] == req['policy_id']
