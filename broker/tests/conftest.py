"""Shared test fixtures.

The broker now defaults to persistent SQLite ownership/audit storage. Unit and
route tests must not touch real persistent state implicitly, so this fixture
explicitly injects an in-memory ownership store built on the shared test
registry, plus a no-op audit logger and a fake Docker adapter.

Tests that exercise the persistent dependency architecture or failure recovery
override these dependencies themselves.
"""

import os
import tempfile

import pytest
from unittest.mock import MagicMock

# Isolate all persistent stores from the repository before any broker module is
# imported. Tests must never write into the checked-in broker/data directory.
_TEST_STORAGE = tempfile.mkdtemp(prefix='flaghunt-broker-test-storage-')
os.environ.setdefault('BROKER_DB_PATH', os.path.join(_TEST_STORAGE, 'broker.db'))
os.environ.setdefault('BROKER_AUDIT_DB_PATH', os.path.join(_TEST_STORAGE, 'broker_audit.db'))
os.environ.setdefault('BROKER_RECOVERY_DB_PATH', os.path.join(_TEST_STORAGE, 'broker_recovery.db'))
# Firewall controller ownership/audit default store (ControllerOwnershipStore) must also be isolated.
os.environ['FIREWALL_CONTROLLER_DB_PATH'] = os.path.join(_TEST_STORAGE, 'firewall_controller.db')

from broker.app import ownership
from broker.app.main import app
from broker.app.dependencies import get_ownership_store, get_audit_logger, get_adapter
from broker.app.ownership_store import InMemoryOwnershipStore


class FakeAdapter:
    """Minimal in-memory Docker adapter double. No Docker access."""

    def __init__(self):
        self._counter = 0
        self.removed = []
        self.removal_should_fail = False

    def create_container(self, validated_spec, instance_id, **kwargs):
        self._counter += 1
        return {"container_id": f"fake-{self._counter}"}

    def start_container(self, container_id):
        return {"status": "started"}

    def inspect_container(self, container_id):
        info = MagicMock()
        info.status = "running"
        info.labels = {"flaghunt.manager.owner": "flaghunt-manager"}
        return info

    def stop_container(self, container_id, timeout=10):
        return {"status": "stopped"}

    def remove_container(self, container_id, force=False):
        if self.removal_should_fail:
            from broker.app.docker_adapter import BrokerDockerError
            raise BrokerDockerError("Container removal failure")
        self.removed.append(container_id)
        return {"status": "removed"}

    def health_check_container(self, container_id):
        return {"healthy": True, "status": "running"}


@pytest.fixture(autouse=True)
def broker_test_dependencies():
    ownership.ownership_registry.clear()
    store = InMemoryOwnershipStore(ownership.ownership_registry)
    fake_adapter = FakeAdapter()
    app.dependency_overrides[get_ownership_store] = lambda: store
    app.dependency_overrides[get_audit_logger] = lambda: None
    app.dependency_overrides[get_adapter] = lambda: fake_adapter
    try:
        yield {"store": store, "adapter": fake_adapter}
    finally:
        ownership.ownership_registry.clear()
        app.dependency_overrides.clear()
