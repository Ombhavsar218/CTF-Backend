from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any, Dict, Optional

from . import catalog
from . import policy


class ProvisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    request_id: str
    instance_id: int
    challenge_id: int
    idempotency_key: str
    catalog_id: str = Field(min_length=1, max_length=64)
    # No arbitrary image names, tags, Docker commands, volume mounts, etc. allowed
    duration_seconds: Optional[int] = None
    resource_profile: Optional[Any] = None
    container_port: Optional[int] = None

    @field_validator('catalog_id')
    @classmethod
    def validate_catalog_id(cls, v: str) -> str:
        entry = catalog.get_entry_by_id_or_challenge_id(v)
        if not entry:
            raise ValueError('Unknown catalog identifier')
        if not catalog.is_verified_runnable(v) and not (entry.verified_runnable and entry.digest_pinned):
            raise ValueError('Catalog entry not verified runnable')
        # Additional policy validation
        try:
            policy.PolicyValidator.resolve_challenge_image_id(entry.challenge_image_id)
        except Exception as e:
            raise ValueError(str(e))
        return v


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    instance_id: int
    idempotency_key: str


class StopRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    instance_id: int
    idempotency_key: str


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    instance_id: int
    idempotency_key: str


class CatalogEntryResponse(BaseModel):
    id: str
    verified_runnable: bool
    has_digest: bool
    description: str
    # Extended fields
    challenge_image_id: Optional[str] = None
    display_name: Optional[str] = None
    image_repository: Optional[str] = None
    image_digest: Optional[str] = None
    approved_container_port: Optional[int] = None
    resource_profile: Optional[Dict[str, Any]] = None
    max_lifetime_seconds: Optional[int] = None
    storage_policy: Optional[str] = None
    network_policy: Optional[str] = None
    health_check_settings: Optional[Dict[str, Any]] = None


class CatalogResponse(BaseModel):
    entries: list[CatalogEntryResponse]
    max_cpu_cores: float
    max_memory_mb: int
    max_pid_limit: int
    max_lifetime_seconds: int
    network_egress_denied_by_default: bool


class HealthResponse(BaseModel):
    status: str
    version: str
