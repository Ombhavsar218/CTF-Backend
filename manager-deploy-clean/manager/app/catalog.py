from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ResourceProfile:
    cpu_limit_cores: float
    memory_limit_mb: int
    pid_limit: int
    max_lifetime_seconds: int
    network_egress_denied: bool = True
    allowed_ports: tuple = ()


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    image_ref: str  # fully qualified with digest
    digest_pinned: bool
    verified_runnable: bool
    description: str
    resource_profile: ResourceProfile


# Empty by design - no verified runnable images yet
CATALOG: Dict[str, CatalogEntry] = {}


MAX_CPU_CORES = 1.0
MAX_MEMORY_MB = 512
MAX_PID_LIMIT = 256
MAX_LIFETIME_SECONDS = 3600


def get_entry(entry_id: str) -> Optional[CatalogEntry]:
    return CATALOG.get(entry_id)


def is_verified_runnable(entry_id: str) -> bool:
    entry = get_entry(entry_id)
    if not entry:
        return False
    return entry.verified_runnable and entry.digest_pinned


def validate_policy_limits(cpu_cores: float, memory_mb: int, pid_limit: int, lifetime_seconds: int) -> None:
    if cpu_cores > MAX_CPU_CORES:
        raise ValueError("CPU limit exceeds allowed maximum")
    if memory_mb > MAX_MEMORY_MB:
        raise ValueError("Memory limit exceeds allowed maximum")
    if pid_limit > MAX_PID_LIMIT:
        raise ValueError("PID limit exceeds allowed maximum")
    if lifetime_seconds > MAX_LIFETIME_SECONDS:
        raise ValueError("Lifetime exceeds allowed maximum")
    if cpu_cores < 0.1 or memory_mb < 64 or pid_limit < 32 or lifetime_seconds < 60:
        raise ValueError("Resource limits below minimum")
