from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class OwnershipRecord:
    container_id: str
    instance_id: str
    challenge_image_id: str
    owner: str = "flaghunt-manager"
    managed: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    labels: Dict[str, str] = field(default_factory=dict)


class OwnershipRegistry:
    """
    In-memory ownership registry for this phase.
    NOT persistent - must be replaced before production.
    """

    def __init__(self):
        self._records: Dict[str, OwnershipRecord] = {}
        self._instance_to_container: Dict[str, str] = {}

    def register(self, container_id: str, instance_id: str, challenge_image_id: str, labels: Optional[Dict[str, str]] = None) -> OwnershipRecord:
        record = OwnershipRecord(
            container_id=container_id,
            instance_id=str(instance_id),
            challenge_image_id=challenge_image_id,
            labels=labels or {},
        )
        self._records[container_id] = record
        self._instance_to_container[str(instance_id)] = container_id
        return record

    def get(self, container_id: str) -> Optional[OwnershipRecord]:
        return self._records.get(container_id)

    def is_owned(self, container_id: str, owner: str = "flaghunt-manager") -> bool:
        rec = self.get(container_id)
        if not rec:
            return False
        return rec.managed and rec.owner == owner

    def verify_ownership(self, container_id: str, owner: str = "flaghunt-manager") -> OwnershipRecord:
        rec = self.get(container_id)
        if not rec or not rec.managed or rec.owner != owner:
            raise PermissionError("Container not owned by this manager")
        return rec

    def remove(self, container_id: str, owner: str = "flaghunt-manager") -> bool:
        rec = self.get(container_id)
        if not rec:
            return False  # idempotent
        if rec.owner != owner:
            raise PermissionError("Container not owned by this manager")
        self._records.pop(container_id, None)
        # remove instance mapping if points to this container
        for k, v in list(self._instance_to_container.items()):
            if v == container_id:
                self._instance_to_container.pop(k, None)
        return True

    def clear(self):
        self._records.clear()
        self._instance_to_container.clear()


ownership_registry = OwnershipRegistry()
