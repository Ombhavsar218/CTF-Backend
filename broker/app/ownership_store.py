from abc import ABC, abstractmethod
from typing import Optional

from .ownership import OwnershipRecord, ownership_registry


class OwnershipStoreBase(ABC):
    @abstractmethod
    def record_creation(self, container_id: str, instance_id: str, challenge_image_id: str, labels=None) -> OwnershipRecord:
        raise NotImplementedError

    @abstractmethod
    def verify(self, container_id: str, owner: str = "flaghunt-manager") -> OwnershipRecord:
        raise NotImplementedError

    @abstractmethod
    def remove(self, container_id: str, owner: str = "flaghunt-manager") -> bool:
        raise NotImplementedError

    @abstractmethod
    def exists(self, container_id: str) -> bool:
        raise NotImplementedError


class InMemoryOwnershipStore(OwnershipStoreBase):
    def __init__(self, registry=None):
        self._reg = registry or ownership_registry

    def record_creation(self, container_id: str, instance_id: str, challenge_image_id: str, labels=None) -> OwnershipRecord:
        return self._reg.register(container_id, instance_id, challenge_image_id, labels=labels)

    def verify(self, container_id: str, owner: str = "flaghunt-manager") -> OwnershipRecord:
        return self._reg.verify_ownership(container_id, owner=owner)

    def remove(self, container_id: str, owner: str = "flaghunt-manager") -> bool:
        return self._reg.remove(container_id, owner=owner)

    def exists(self, container_id: str) -> bool:
        return self._reg.get(container_id) is not None


# Persistent interface placeholder - not connected to DB in this phase
class PersistentOwnershipStore(OwnershipStoreBase):
    def __init__(self):
        raise NotImplementedError("Persistent store not implemented in this phase")

    def record_creation(self, container_id: str, instance_id: str, challenge_image_id: str, labels=None) -> OwnershipRecord:
        raise NotImplementedError

    def verify(self, container_id: str, owner: str = "flaghunt-manager") -> OwnershipRecord:
        raise NotImplementedError

    def remove(self, container_id: str, owner: str = "flaghunt-manager") -> bool:
        raise NotImplementedError

    def exists(self, container_id: str) -> bool:
        raise NotImplementedError


ownership_store = InMemoryOwnershipStore()
