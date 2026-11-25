from dataclasses import dataclass
from typing import Any, Dict, Optional


class BrokerDockerError(Exception):
    pass


class BrokerDockerNotFoundError(BrokerDockerError):
    pass


class BrokerDockerNotOwnedError(BrokerDockerError):
    pass


class BrokerDockerNetworkError(BrokerDockerError):
    pass


@dataclass
class DockerNetworkInfo:
    network_id: str
    name: str
    owned: bool
    driver: str = "bridge"
    internal: bool = True
    attached_containers: list = None


@dataclass
class DockerContainerInfo:
    container_id: str
    status: str
    owned: bool
    labels: Dict[str, str]


class DockerAdapterBase:
    def create_container(self, validated_spec: Any, instance_id: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

    def start_container(self, container_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def inspect_container(self, container_id: str) -> DockerContainerInfo:
        raise NotImplementedError

    def stop_container(self, container_id: str, timeout: int = 10) -> Dict[str, Any]:
        raise NotImplementedError

    def remove_container(self, container_id: str, force: bool = False) -> Dict[str, Any]:
        raise NotImplementedError

    def health_check_container(self, container_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    # Network operations (intentionally unavailable in mock-only architecture)
    def create_network(self, network_spec: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def inspect_network(self, network_id: str) -> DockerNetworkInfo:
        raise NotImplementedError

    def verify_network_ownership(self, network_id: str) -> bool:
        raise NotImplementedError

    def connect_container_to_network(self, network_id: str, container_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def disconnect_container_from_network(self, network_id: str, container_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def remove_network(self, network_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def network_exists(self, network_id: str) -> bool:
        raise NotImplementedError

    def health_check_network(self, network_id: str) -> Dict[str, Any]:
        raise NotImplementedError


_UNAVAILABLE_MSG = "Docker runtime unavailable"


class BrokerDockerAdapter(DockerAdapterBase):
    """Explicitly unavailable broker Docker adapter.

    Security boundary (Phase 2L.2J.2, mock-only): the broker must not create,
    store, retain, or use a Docker client and must not provide operational
    container or network control. All operations fail closed.
    """

    def __init__(self, docker_client=None, ownership_registry=None, network_ownership_registry=None):
        # Never accept, store, or retain a Docker client/API handle.
        # Caller-supplied clients must not enable operations.
        self._client = None
        self._api = None
        self._ownership = ownership_registry
        self._network_ownership = network_ownership_registry
        if docker_client is not None:
            raise BrokerDockerError(_UNAVAILABLE_MSG)

    def _ensure_client(self):
        raise BrokerDockerError(_UNAVAILABLE_MSG)

    def _unavailable(self, *args, **kwargs):
        raise BrokerDockerError(_UNAVAILABLE_MSG)

    # Container operations
    def create_container(self, validated_spec: Any, instance_id: str, **kwargs) -> Dict[str, Any]:
        raise BrokerDockerError(_UNAVAILABLE_MSG)

    def start_container(self, container_id: str) -> Dict[str, Any]:
        raise BrokerDockerError(_UNAVAILABLE_MSG)

    def inspect_container(self, container_id: str) -> DockerContainerInfo:
        raise BrokerDockerError(_UNAVAILABLE_MSG)

    def stop_container(self, container_id: str, timeout: int = 10) -> Dict[str, Any]:
        raise BrokerDockerError(_UNAVAILABLE_MSG)

    def remove_container(self, container_id: str, force: bool = False) -> Dict[str, Any]:
        raise BrokerDockerError(_UNAVAILABLE_MSG)

    def health_check_container(self, container_id: str) -> Dict[str, Any]:
        raise BrokerDockerError(_UNAVAILABLE_MSG)

    # Network operations
    def create_network(self, network_spec: Dict[str, Any]) -> Dict[str, Any]:
        raise BrokerDockerNetworkError(_UNAVAILABLE_MSG)

    def inspect_network(self, network_id: str) -> DockerNetworkInfo:
        raise BrokerDockerNetworkError(_UNAVAILABLE_MSG)

    def verify_network_ownership(self, network_id: str) -> bool:
        raise BrokerDockerNetworkError(_UNAVAILABLE_MSG)

    def connect_container_to_network(self, network_id: str, container_id: str) -> Dict[str, Any]:
        raise BrokerDockerNetworkError(_UNAVAILABLE_MSG)

    def disconnect_container_from_network(self, network_id: str, container_id: str) -> Dict[str, Any]:
        raise BrokerDockerNetworkError(_UNAVAILABLE_MSG)

    def remove_network(self, network_id: str) -> Dict[str, Any]:
        raise BrokerDockerNetworkError(_UNAVAILABLE_MSG)

    def network_exists(self, network_id: str) -> bool:
        raise BrokerDockerNetworkError(_UNAVAILABLE_MSG)

    def health_check_network(self, network_id: str) -> Dict[str, Any]:
        raise BrokerDockerNetworkError(_UNAVAILABLE_MSG)


# BrokerDockerAdapter implementation replaced above as explicitly unavailable.
# (Legacy operational implementation removed in Phase 2L.2J.2 mock-only remediation.)
