import tempfile
import os
import threading
from unittest.mock import MagicMock

import pytest

from broker.app.docker_adapter import BrokerDockerAdapter, BrokerDockerError, BrokerDockerNetworkError
from broker.app.network_ownership import PersistentNetworkOwnershipStore


def test_network_adapter_fail_closed_for_all_operations():
    adapter = BrokerDockerAdapter()
    ops = [
        lambda: adapter.create_network({'network_id': 'n', 'name': 'n'}),
        lambda: adapter.inspect_network('n'),
        lambda: adapter.verify_network_ownership('n'),
        lambda: adapter.connect_container_to_network('n', 'c'),
        lambda: adapter.disconnect_container_from_network('n', 'c'),
        lambda: adapter.remove_network('n'),
        lambda: adapter.network_exists('n'),
        lambda: adapter.health_check_network('n'),
    ]
    for op in ops:
        with pytest.raises((BrokerDockerError, BrokerDockerNetworkError)):
            op()


def test_docker_client_injection_cannot_activate_network_operations():
    docker_client = MagicMock()
    with pytest.raises(BrokerDockerError):
        BrokerDockerAdapter(docker_client=docker_client)
    assert not docker_client.mock_calls
    for attr in ('networks', 'containers', 'api'):
        if hasattr(docker_client, attr):
            assert not getattr(docker_client, attr).mock_calls


def test_network_ownership_persistence_unrelated_behavior_preserved():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        assert net_store.exists(nid)
        assert net_store.get(nid).instance_id == 'i1'
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
        for s in ('', '-wal', '-shm'):
            try:
                os.unlink(path + s)
            except Exception:
                pass


def test_network_concurrent_creation_idempotent_unrelated_behavior_preserved():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        nid = net_store.generate_network_id()
        results = []
        def create():
            try:
                net_store.record_creation(nid, 'i1', 'c1')
                results.append('ok')
            except Exception:
                results.append('err')
        threads = [threading.Thread(target=create) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results.count('ok') == 1
        assert results.count('err') == 4
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
        for s in ('', '-wal', '-shm'):
            try:
                os.unlink(path + s)
            except Exception:
                pass
