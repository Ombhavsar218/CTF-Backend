import uuid
import pytest

from broker.app.firewall_controller_contract import FirewallControllerRequestError, _validate_request
from broker.firewall_controller_service import FirewallControllerService
from broker.tests._helper_identity import authorized_backend


def _svc():
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend()
    )


def _req(pid="pv1", ver=1, digest="a" * 64, key=None):
    return {
        "request_id": str(uuid.uuid4()),
        "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid,
        "policy_version": ver,
        "compiled_rule_digest": digest,
        "compiled": {},
        "peer_uid": 1000,
        "peer_gid": 1000,
        "instance_id": "i1",
        "network_id": "n1",
    }


def test_contract_rejects_bool_and_negative_policy_version():
    for bad in (True, False, -1):
        req = _req(ver=bad)
        with pytest.raises(FirewallControllerRequestError):
            _validate_request(req)


def test_controller_rejects_bool_policy_version_on_install():
    svc = _svc()
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(_req(ver=True))
    with pytest.raises(FirewallControllerRequestError):
        svc.install_policy(_req(ver=False))
