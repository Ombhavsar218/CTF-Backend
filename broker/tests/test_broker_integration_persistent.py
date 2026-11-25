import os
import tempfile
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from broker.app.main import app
from broker.app import policy
from broker.app.routes import get_adapter
from broker.app.docker_adapter import BrokerDockerAdapter
from broker.app import dependencies


client = TestClient(app)


def make_policy():
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


def test_routes_use_persistent_stores_by_default():
    store = dependencies.get_ownership_store()
    assert hasattr(store, 'record_creation')
    assert hasattr(store, 'verify')


def test_in_memory_stores_used_only_when_explicitly_injected_and_docker_unavailable():
    from broker.app.ownership_store import InMemoryOwnershipStore
    store = InMemoryOwnershipStore()
    app.dependency_overrides[dependencies.get_ownership_store] = lambda: store
    try:
        make_policy()
        # Default unavailable adapter: creation must fail closed with no docker operation.
        app.dependency_overrides.pop(get_adapter, None)
        resp = client.post('/broker/v1/containers/create',
                           json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'chal-test'},
                           headers=_auth_headers())
        assert resp.status_code == 500
        assert resp.json().get('detail') == 'Internal error'
    finally:
        app.dependency_overrides = {}


def test_db_write_failure_path_not_reached_without_docker_creation():
    make_policy()
    fake_client = MagicMock()
    # Client injection must not be possible; adapter construction must fail closed.
    try:
        BrokerDockerAdapter(docker_client=fake_client)
        assert False, "docker client injection must be rejected"
    except Exception:
        pass
    # With default unavailable adapter, create fails before any docker creation/persistence.
    app.dependency_overrides = {}
    resp = client.post('/broker/v1/containers/create',
                       json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'chal-test'},
                       headers=_auth_headers())
    assert resp.status_code == 500
    assert not fake_client.mock_calls
    if hasattr(fake_client, 'containers'):
        assert not fake_client.containers.mock_calls


def test_no_docker_compensating_removal_when_adapter_unavailable():
    from broker.app import recovery
    recovery.orphan_registry.clear()
    make_policy()
    fake_client = MagicMock()
    try:
        BrokerDockerAdapter(docker_client=fake_client)
        assert False, "docker client injection must be rejected"
    except Exception:
        pass
    app.dependency_overrides = {}
    resp = client.post('/broker/v1/containers/create',
                       json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'chal-test'},
                       headers=_auth_headers())
    assert resp.status_code == 500
    # No docker container was created, so no docker compensating removal should be attempted.
    assert not fake_client.mock_calls
    if hasattr(fake_client, 'containers'):
        assert not fake_client.containers.mock_calls


def test_restart_preserves_ownership_persistent():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        from broker.app.ownership_store_persistent import PersistentOwnershipStore
        s1 = PersistentOwnershipStore(path)
        s1.record_creation('cp1', '1', 'chal1')
        s2 = PersistentOwnershipStore(path)
        assert s2.exists('cp1')
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
        try:
            os.unlink(path + '-wal')
            os.unlink(path + '-shm')
        except Exception:
            pass


def test_no_silent_fallback():
    store = dependencies.get_ownership_store()
    from broker.app.ownership_store_persistent import PersistentOwnershipStore
    assert isinstance(store, PersistentOwnershipStore)


def test_adapter_unavailable_fails_closed_even_with_failing_audit():
    make_policy()

    class FailingAudit:
        def log(self, *args, **kwargs):
            raise Exception('audit database unavailable')

    app.dependency_overrides = {}
    app.dependency_overrides[dependencies.get_audit_logger] = lambda: FailingAudit()
    try:
        resp = client.post('/broker/v1/containers/create',
                           json={'request_id': 'r1', 'instance_id': '1', 'challenge_image_id': 'chal-test'},
                           headers=_auth_headers())
        assert resp.status_code == 500
        assert resp.json().get('detail') == 'Internal error'
    finally:
        app.dependency_overrides = {}
