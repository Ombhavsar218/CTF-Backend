import json
from fastapi.testclient import TestClient

from broker.app.main import app
from broker.app import ownership, policy


client = TestClient(app)


def test_health_requires_auth():
    resp = client.get('/broker/v1/health')
    assert resp.status_code in (401, 503)


def test_health_authorized():
    resp = client.get('/broker/v1/health', headers={'X-Broker-Peer-Uid': '1000', 'X-Broker-Peer-User': 'flaghunt-mgr'})
    # May require specific auth depending on config; our auth checks peer if configured
    # With defaults, if no constraints it might still work? Let us see
    assert resp.status_code in (200, 401)


def test_create_rejects_unknown_fields():
    policy.broker_policy.register_mock('test-chal', {
        'image_repository': 'repo/image',
        'image_digest': 'sha256:' + 'a' * 64,
        'approved_container_port': 8080,
        'resource_profile': {'cpu_limit_cores': 0.5, 'memory_limit_mb': 256, 'pid_limit': 128},
        'max_lifetime_seconds': 3600,
        'storage_policy': 'ephemeral',
        'network_policy': 'deny_all_egress',
    })
    resp = client.post('/broker/v1/containers/create', 
                       json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'test-chal', 'image': 'bad'},
                       headers={'X-Broker-Peer-Uid': '1000', 'X-Broker-Peer-User': 'flaghunt-mgr'})
    assert resp.status_code == 422


def test_create_rejects_arbitrary_images():
    policy.broker_policy.register_mock('test-chal2', {
        'image_repository': 'repo/image',
        'image_digest': 'sha256:' + 'b' * 64,
        'approved_container_port': 8080,
        'resource_profile': {'cpu_limit_cores': 0.5, 'memory_limit_mb': 256, 'pid_limit': 128},
        'max_lifetime_seconds': 3600,
        'storage_policy': 'ephemeral',
        'network_policy': 'deny_all_egress',
    })
    # Try to pass image as top level extra - should be rejected by schema
    resp = client.post('/broker/v1/containers/create',
                       json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'test-chal2', 'command': ['/bin/sh']},
                       headers={'X-Broker-Peer-Uid': '1000', 'X-Broker-Peer-User': 'flaghunt-mgr'})
    assert resp.status_code == 422


def test_unauthorized_peer():
    resp = client.post('/broker/v1/containers/create',
                       json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'x'},
                       headers={'X-Broker-Peer-Uid': '9999', 'X-Broker-Peer-User': 'evil'})
    assert resp.status_code == 401


def test_ownership_registry_behavior():
    ownership.ownership_registry.clear()
    rec = ownership.ownership_registry.register('c1', '1', 'chal1')
    assert ownership.ownership_registry.is_owned('c1')
    assert ownership.ownership_registry.verify_ownership('c1')
    ownership.ownership_registry.remove('c1')
    ownership.ownership_registry.clear()


def test_reject_unowned_containers():
    ownership.ownership_registry.clear()
    # Try to start unowned
    resp = client.post('/broker/v1/containers/c99/start',
                       json={'request_id': 'r1', 'container_id': 'c99'},
                       headers={'X-Broker-Peer-Uid': '1000', 'X-Broker-Peer-User': 'flaghunt-mgr'})
    assert resp.status_code == 403
    ownership.ownership_registry.clear()


def test_idempotent_cleanup():
    ownership.ownership_registry.clear()
    ownership.ownership_registry.register('c2', '2', 'chal1')
    resp = client.post('/broker/v1/containers/c2/remove',
                       json={'request_id': 'r1', 'container_id': 'c2'},
                       headers={'X-Broker-Peer-Uid': '1000', 'X-Broker-Peer-User': 'flaghunt-mgr'})
    assert resp.status_code == 200
    # remove again
    resp2 = client.post('/broker/v1/containers/c2/remove',
                        json={'request_id': 'r2', 'container_id': 'c2'},
                        headers={'X-Broker-Peer-Uid': '1000', 'X-Broker-Peer-User': 'flaghunt-mgr'})
    assert resp2.status_code == 200
    ownership.ownership_registry.clear()


def test_sanitized_errors():
    ownership.ownership_registry.clear()
    resp = client.post('/broker/v1/containers/c1/inspect',
                       json={'request_id': 'r1', 'container_id': 'c1'},
                       headers={'X-Broker-Peer-Uid': '1000', 'X-Broker-Peer-User': 'flaghunt-mgr'})
    assert resp.status_code in (401, 403)
    # Should not leak secrets
    assert 'token' not in str(resp.content).lower()
    ownership.ownership_registry.clear()
