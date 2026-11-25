from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any, Dict, Optional


class BrokerRequestBase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1)
    idempotency_key: Optional[str] = None


class CreateContainerRequest(BrokerRequestBase):
    instance_id: str = Field(min_length=1)
    challenge_image_id: str = Field(min_length=1)
    # No arbitrary images/tags/commands/entrypoints/host config/mounts/devices/networks/env/options
    resource_profile: Optional[Dict[str, Any]] = None
    approved_container_port: Optional[int] = None


class StartContainerRequest(BrokerRequestBase):
    container_id: str = Field(min_length=1)


class InspectContainerRequest(BrokerRequestBase):
    container_id: str = Field(min_length=1)


class StopContainerRequest(BrokerRequestBase):
    container_id: str = Field(min_length=1)
    timeout: int = Field(default=10, ge=1, le=60)


class RemoveContainerRequest(BrokerRequestBase):
    container_id: str = Field(min_length=1)
    force: bool = False


class HealthCheckRequest(BrokerRequestBase):
    container_id: str = Field(min_length=1)


class PeerInfo(BaseModel):
    model_config = ConfigDict(extra='forbid')
    uid: Optional[int] = None
    gid: Optional[int] = None
    user: Optional[str] = None
    pid: Optional[int] = None
    comm: Optional[str] = None
