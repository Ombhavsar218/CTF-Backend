import tempfile
import os
from unittest.mock import MagicMock

import pytest

from broker.app.docker_adapter import BrokerDockerAdapter, BrokerDockerError, BrokerDockerNetworkError
from broker.app.network_ownership import PersistentNetworkOwnershipStore


def test_network_operations_fail_closed_no_client():
    adapter = BrokerDockerAdapter()
    with pytest.raises(BrokerDockerNetworkError):
        adapter.create_network({'network_id': 'n1', 'name': 'n1'})
    with pytest.raises(BrokerDockerNetworkError):
        adapter.inspect_network('n1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.remove_network('n1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.connect_container_to_network('n1', 'c1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.disconnect_container_from_network('n1', 'c1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.network_exists('n1')
    with pytest.raises(BrokerDockerNetworkError):
        adapter.health_check_network('n1')


def test_injected_docker_client_cannot_enable_network_operations():
    docker_client = MagicMock()
    with pytest.raises(BrokerDockerError):
        BrokerDockerAdapter(docker_client=docker_client)
    assert not docker_client.mock_calls
    if hasattr(docker_client, 'networks'):
        assert not docker_client.networks.mock_calls
    if hasattr(docker_client, 'api'):
        assert not docker_client.api.mock_calls


def test_network_ownership_persistent_restart_unrelated_behavior_preserved():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        s1 = PersistentNetworkOwnershipStore(path)
        nid = s1.generate_network_id()
        s1.record_creation(nid, 'i1', 'c1')
        s2 = PersistentNetworkOwnershipStore(path)
        assert s2.exists(nid)
        rec = s2.get(nid)
        assert rec.instance_id == 'i1'
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


def test_network_orphan_persistence_and_reconcile_unrelated_behavior_preserved():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        from broker.app.network_recovery import NetworkOrphanRegistry
        reg = NetworkOrphanRegistry(db_path=path)
        reg.mark_orphan('n1', instance_id='i1', challenge_id='c1', reason='removal_failed')
        reg2 = NetworkOrphanRegistry(db_path=path)
        assert reg2.is_orphan('n1')
        called = []
        def remover(nid):
            called.append(nid)
        assert reg2.reconcile('n1', remover) is True
        assert called == ['n1']
        assert reg2.get('n1').cleanup_status == 'confirmed'
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


def test_network_orphan_duplicate_prevented_unrelated_behavior_preserved():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        from broker.app.network_recovery import NetworkOrphanRegistry
        reg = NetworkOrphanRegistry(db_path=path)
        reg.mark_orphan('nd', instance_id='i1', challenge_id='c1', reason='x')
        reg.mark_orphan('nd', instance_id='i1', challenge_id='c1', reason='y')
        rows = reg.db.query('SELECT * FROM network_orphan_recovery WHERE network_id = ?', ('nd',))
        assert len(rows) == 1
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
