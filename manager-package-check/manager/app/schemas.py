from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import catalog


class ProvisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    request_id: str
    instance_id: int
    challenge_id: int
    idempotency_key: str
    catalog_id: str = Field(min_length=1, max_length=64)

    @field_validator('catalog_id')
    @classmethod
    def validate_catalog_id(cls, v: str) -> str:
        entry = catalog.get_entry(v)
        if not entry:
            raise ValueError('Unknown catalog identifier')
        if not catalog.is_verified_runnable(v):
            raise ValueError('Catalog entry not verified runnable')
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

