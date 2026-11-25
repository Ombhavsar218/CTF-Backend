import logging
from typing import Any, Dict

from .base import RuntimeAdapter, RuntimeContainerInfo, RuntimeError


logger = logging.getLogger(__name__)

MANAGER_LABEL_PREFIX = "flaghunt.manager"
MANAGER_LABEL_OWNER = f"{MANAGER_LABEL_PREFIX}.owner"
MANAGER_LABEL_INSTANCE = f"{MANAGER_LABEL_PREFIX}.instance_id"
MANAGER_LABEL_CHALLENGE = f"{MANAGER_LABEL_PREFIX}.challenge_image_id"
MANAGER_LABEL_MANAGED = f"{MANAGER_LABEL_PREFIX}.managed"

_UNAVAILABLE_MSG = "Docker runtime unavailable"


class DockerRuntimeAdapter(RuntimeAdapter):
    """Explicitly unavailable manager runtime Docker adapter.

    Security boundary (Phase 2L.2J.2, mock-only): the manager must not create,
    store, retain, or use a Docker client and must not provide operational
    container/runtime control. All operations fail closed.
    """

    def __init__(self, docker_client=None):
        # Never accept, store, or retain a Docker client/API handle.
        self._client = None
        self._api = None
        if docker_client is not None:
            raise RuntimeError(_UNAVAILABLE_MSG)

    def _ensure_client(self):
        raise RuntimeError(_UNAVAILABLE_MSG)

    def create_container(self, validated_spec: Any, instance_id: str, **kwargs) -> Dict[str, Any]:
        raise RuntimeError(_UNAVAILABLE_MSG)

    def start_container(self, container_id: str) -> Dict[str, Any]:
        raise RuntimeError(_UNAVAILABLE_MSG)

    def inspect_container(self, container_id: str) -> RuntimeContainerInfo:
        raise RuntimeError(_UNAVAILABLE_MSG)

    def stop_container(self, container_id: str, timeout: int = 10) -> Dict[str, Any]:
        raise RuntimeError(_UNAVAILABLE_MSG)

    def remove_container(self, container_id: str, force: bool = False) -> Dict[str, Any]:
        raise RuntimeError(_UNAVAILABLE_MSG)

    def health_check_container(self, container_id: str) -> Dict[str, Any]:
        raise RuntimeError(_UNAVAILABLE_MSG)
