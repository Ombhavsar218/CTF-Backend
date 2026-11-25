from fastapi import Depends

from .ownership_store_persistent import PersistentOwnershipStore
from .audit_persistent import PersistentAuditLogger
from .network_ownership import PersistentNetworkOwnershipStore
from .docker_adapter import BrokerDockerAdapter
from .ownership import ownership_registry
from .config import settings


# Default persistent stores - fail closed if unavailable
try:
    _persistent_ownership = PersistentOwnershipStore(settings.broker_db_path)
except Exception as e:
    if settings.require_persistent_storage:
        raise
    from .ownership_store import InMemoryOwnershipStore
    _persistent_ownership = InMemoryOwnershipStore()

try:
    _persistent_network_ownership = PersistentNetworkOwnershipStore(settings.broker_db_path)
except Exception as e:
    if settings.require_persistent_storage:
        raise
    _persistent_network_ownership = None

try:
    _persistent_audit = PersistentAuditLogger(settings.broker_audit_db_path)
except Exception as e:
    if settings.require_persistent_storage:
        raise
    _persistent_audit = None


def get_ownership_store():
    return _persistent_ownership


def get_network_ownership_store():
    return _persistent_network_ownership


def get_audit_logger():
    return _persistent_audit


def get_adapter():
    return BrokerDockerAdapter(docker_client=None, ownership_registry=ownership_registry,
                               network_ownership_registry=_persistent_network_ownership)
