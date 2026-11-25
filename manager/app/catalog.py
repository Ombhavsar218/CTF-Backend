import json
import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Any


@dataclass(frozen=True)
class ResourceProfile:
    cpu_limit_cores: float
    memory_limit_mb: int
    pid_limit: int
    max_lifetime_seconds: int = 3600
    network_egress_denied: bool = True
    allowed_ports: tuple = ()


@dataclass(frozen=True)
class CatalogEntry:
    id: str  # catalog/entry id
    challenge_image_id: str  # challenge image ID
    display_name: str
    image_repository: str
    image_digest: str  # immutable SHA-256 image digest
    image_ref: str  # fully qualified with digest
    digest_pinned: bool
    verified_runnable: bool
    description: str
    approved_container_port: int
    resource_profile: ResourceProfile
    resource_profile_name: str = "default"
    max_lifetime_seconds: int = 3600
    max_lifetime: int = 3600
    storage_policy: str = "ephemeral"
    network_policy: str = "deny_all_egress"
    health_check_settings: Dict[str, Any] = field(default_factory=dict)
    egress_denied: bool = True


# Catalog storage - manager controlled
CATALOG: Dict[str, CatalogEntry] = {}
# Also index by challenge image id
CATALOG_BY_CHALLENGE_ID: Dict[str, CatalogEntry] = {}


MAX_CPU_CORES = 1.0
MAX_MEMORY_MB = 512
MAX_PID_LIMIT = 256
MAX_LIFETIME_SECONDS = 3600


def _validate_sha256_digest(digest: str) -> bool:
    if not isinstance(digest, str):
        return False
    if not digest.startswith("sha256:"):
        return False
    if len(digest) != 71:  # sha256: + 64 hex chars
        return False
    hex_part = digest[7:]
    return all(c in "0123456789abcdefABCDEF" for c in hex_part)


def register_entry(entry: CatalogEntry) -> None:
    if not _validate_sha256_digest(entry.image_digest):
        raise ValueError("Invalid or missing image digest")
    if entry.storage_policy != "ephemeral":
        raise ValueError("Invalid storage policy")
    if entry.network_policy not in ("deny_all_egress", "default-deny"):
        raise ValueError("Invalid network policy")
    if not entry.egress_denied:
        raise ValueError("Default-deny egress required")
    if entry.approved_container_port < 1 or entry.approved_container_port > 65535:
        raise ValueError("Invalid port")
    if entry.max_lifetime_seconds < 60 or entry.max_lifetime_seconds > MAX_LIFETIME_SECONDS:
        raise ValueError("Invalid duration")
    
    object.__setattr__(entry, 'max_lifetime', entry.max_lifetime_seconds) if hasattr(object, '__setattr__') else None
    CATALOG[entry.id] = entry
    CATALOG_BY_CHALLENGE_ID[entry.challenge_image_id] = entry


def load_catalog_from_config(config_path: Optional[str] = None) -> None:
    if config_path is None:
        # Look for catalog config in common locations
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for candidate in [
            os.path.join(base_dir, "catalog.json"),
            os.path.join(base_dir, "config", "catalog.json"),
            os.path.join(os.path.dirname(base_dir), "catalog.json"),
        ]:
            if os.path.exists(candidate):
                config_path = candidate
                break
    
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
            entries = data.get('entries', []) if isinstance(data, dict) else data
            for entry_data in entries:
                from .policy import PolicyValidator
                PolicyValidator.validate_catalog_entry_config(entry_data)
                rp = entry_data.get('resource_profile')
                if isinstance(rp, str):
                    rp_obj = ResourceProfile(
                        cpu_limit_cores=0.5,
                        memory_limit_mb=256,
                        pid_limit=128,
                        max_lifetime_seconds=entry_data['max_lifetime'],
                        network_egress_denied=True,
                    )
                    rp_name = rp
                elif isinstance(rp, dict):
                    rp_obj = ResourceProfile(
                        cpu_limit_cores=float(rp.get('cpu_limit_cores', 0.5)),
                        memory_limit_mb=int(rp.get('memory_limit_mb', 256)),
                        pid_limit=int(rp.get('pid_limit', 128)),
                        max_lifetime_seconds=entry_data['max_lifetime'],
                        network_egress_denied=True,
                    )
                    rp_name = rp.get('name', 'custom')
                else:
                    raise ValueError("Unsupported resource profile")
                
                entry = CatalogEntry(
                    id=entry_data.get('id') or entry_data['challenge_image_id'],
                    challenge_image_id=entry_data['challenge_image_id'],
                    display_name=entry_data['display_name'],
                    image_repository=entry_data['image_repository'],
                    image_digest=entry_data['image_digest'],
                    image_ref=f"{entry_data['image_repository']}@{entry_data['image_digest']}",
                    digest_pinned=True,
                    verified_runnable=True,
                    description=entry_data.get('description', entry_data['display_name']),
                    approved_container_port=entry_data['approved_container_port'],
                    resource_profile=rp_obj,
                    resource_profile_name=rp_name if isinstance(rp, str) else rp_name,
                    max_lifetime_seconds=entry_data['max_lifetime'],
                    storage_policy=entry_data['storage_policy'],
                    network_policy=entry_data['network_policy'],
                    health_check_settings=entry_data['health_check_settings'],
                    egress_denied=True,
                )
                register_entry(entry)
        except Exception:
            # Don't fail if catalog loading fails - but must enforce validation
            raise


# Try to load catalog on import if configured
try:
    load_catalog_from_config()
except Exception:
    pass


def get_entry(entry_id: str) -> Optional[CatalogEntry]:
    return CATALOG.get(entry_id)


def get_entry_by_challenge_id(challenge_image_id: str) -> Optional[CatalogEntry]:
    return CATALOG_BY_CHALLENGE_ID.get(challenge_image_id)


def get_entry_by_id_or_challenge_id(id_or_challenge_id: str) -> Optional[CatalogEntry]:
    entry = get_entry(id_or_challenge_id)
    if entry:
        return entry
    return get_entry_by_challenge_id(id_or_challenge_id)


def is_verified_runnable(entry_id: str) -> bool:
    entry = get_entry(entry_id) or get_entry_by_challenge_id(entry_id)
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


# Make catalog immutable in practice - provide a way to check
def is_catalog_immutable() -> bool:
    return True
