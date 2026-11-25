from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from broker.app.main import app
from broker.app import dependencies, policy
from broker.app.docker_adapter import (
    BrokerDockerAdapter,
    BrokerDockerError,
    BrokerDockerNetworkError,
)
from broker.app.routes import get_adapter


client = TestClient(app)


def _register_policy():
    policy.broker_policy.register_mock('chal-test', {
        'image_repository': 'registry.example.com/test/chal',
        'image_digest': 'sha256:' + 'a' * 64,
        'approved_container_port': 8080,
        'resource_profile': {'cpu_limit_cores': 0.5, 'memory_limit_mb': 256, 'pid_limit': 128},
        'max_lifetime_seconds': 3600,
        'storage_policy': 'ephemeral',
        'network_policy': 'deny_all_egress',
    })


def _auth_headers():
    return {'X-Broker-Peer-Uid': '1000', 'X-Broker-Peer-User': 'flaghunt-mgr'}


def test_broker_dependencies_do_not_create_docker_clients():
    adapter = dependencies.get_adapter()
    assert isinstance(adapter, BrokerDockerAdapter)
    assert getattr(adapter, '_client', 'sentinel') is None
    assert getattr(adapter, '_api', 'sentinel') is None


def test_broker_adapter_rejects_injected_docker_client():
    fake_client = MagicMock()
    with pytest.raises(BrokerDockerError):
        BrokerDockerAdapter(docker_client=fake_client)
    fake_client.containers.create.assert_not_called()


def test_broker_adapter_container_operations_fail_closed_without_client():
    adapter = BrokerDockerAdapter()
    with pytest.raises(BrokerDockerError):
        adapter.create_container(MagicMock(), instance_id='1')
    with pytest.raises(BrokerDockerError):
        adapter.start_container('c1')
    with pytest.raises(BrokerDockerError):
        adapter.inspect_container('c1')
    with pytest.raises(BrokerDockerError):
        adapter.stop_container('c1')
    with pytest.raises(BrokerDockerError):
        adapter.remove_container('c1')
    with pytest.raises(BrokerDockerError):
        adapter.health_check_container('c1')


def test_broker_adapter_network_operations_fail_closed_without_client():
    adapter = BrokerDockerAdapter()
    with pytest.raises(BrokerDockerNetworkError):
        adapter.create_network({'name': 'n1'})
    with pytest.raises(BrokerDockerNetworkError):
        adapter.inspect_network('n1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.verify_network_ownership('n1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.connect_container_to_network('n1', 'c1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.disconnect_container_from_network('n1', 'c1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.remove_network('n1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.network_exists('n1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.health_check_network('n1')


def test_injecting_fake_docker_client_cannot_enable_forbidden_operations():
    fake_client = MagicMock()
    try:
        BrokerDockerAdapter(docker_client=fake_client)
        assert False, "adapter must reject injected docker client"
    except BrokerDockerError:
        pass
    # No docker API methods should be invoked during rejected construction/use path.
    assert not fake_client.mock_calls
    if hasattr(fake_client, 'containers'):
        assert not fake_client.containers.mock_calls
    if hasattr(fake_client, 'api'):
        assert not fake_client.api.mock_calls


def test_broker_routes_cannot_access_docker_operations_create():
    _register_policy()
    app.dependency_overrides = {}
    resp = client.post('/broker/v1/containers/create',
                       json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'chal-test'},
                       headers=_auth_headers())
    assert resp.status_code == 500
    assert resp.json().get('detail') == 'Internal error'


def test_broker_routes_cannot_access_docker_operations_lifecycle():
    app.dependency_overrides = {}
    for path, body in [
        ('/broker/v1/containers/c1/start', {'request_id': 'r1', 'container_id': 'c1'}),
        ('/broker/v1/containers/c1/inspect', {'request_id': 'r1', 'container_id': 'c1'}),
        ('/broker/v1/containers/c1/stop', {'request_id': 'r1', 'container_id': 'c1', 'timeout': 1}),
        ('/broker/v1/containers/c1/health', {'request_id': 'r1', 'container_id': 'c1'}),
    ]:
        resp = client.post(path, json=body, headers=_auth_headers())
        # Unowned/not-found in ownership store -> 403; if store verification path differs,
        # adapter must still fail closed and never perform docker operations.
        assert resp.status_code in (403, 500)
    # remove of unknown container is idempotent no-op at route/store level; must not use docker
    resp = client.post('/broker/v1/containers/unknown/remove', json={'request_id': 'r1', 'container_id': 'unknown', 'force': False}, headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json().get('status') == 'removed'


def test_dependency_override_cannot_enable_docker_ops_via_client_injection():
    _register_policy()
    fake_client = MagicMock()
    # Adapter must reject injected docker clients; no dependency path can activate them.
    with pytest.raises(BrokerDockerError):
        BrokerDockerAdapter(docker_client=fake_client)
    assert not fake_client.mock_calls
    if hasattr(fake_client, 'containers'):
        assert not fake_client.containers.mock_calls
    if hasattr(fake_client, 'api'):
        assert not fake_client.api.mock_calls
    # Default dependency-provided adapter remains unavailable and fail-closed.
    app.dependency_overrides = {}
    resp = client.post('/broker/v1/containers/create',
                       json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'chal-test'},
                       headers=_auth_headers())
    assert resp.status_code == 500
    assert not fake_client.mock_calls


def test_no_fallback_docker_operation_attempted_on_default_path():
    _register_policy()
    app.dependency_overrides = {}
    # No docker module/client is imported or invoked by adapter; repeated calls remain unavailable.
    for _ in range(2):
        resp = client.post('/broker/v1/containers/create',
                           json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'chal-test'},
                           headers=_auth_headers())
        assert resp.status_code == 500
    adapter = dependencies.get_adapter()
    with pytest.raises(BrokerDockerError):
        adapter.create_container(MagicMock(), instance_id='1')


def test_existing_broker_authorization_behavior_remains_intact():
    app.dependency_overrides = {}
    resp = client.get('/broker/v1/health')
    assert resp.status_code in (401, 403)
    resp = client.get('/broker/v1/health', headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json().get('status') == 'ok'


def test_existing_unrelated_broker_functionality_preserved_policy_rejection():
    # Unknown challenge should fail policy validation (422), not as docker availability issue.
    app.dependency_overrides = {}
    resp = client.post('/broker/v1/containers/create',
                       json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'unknown-chal'},
                       headers=_auth_headers())
    assert resp.status_code == 422
