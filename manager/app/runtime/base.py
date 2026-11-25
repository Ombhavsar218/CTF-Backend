from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


class RuntimeError(Exception):
    pass


class RuntimeNotFoundError(RuntimeError):
    pass


class RuntimeNotOwnedError(RuntimeError):
    pass


@dataclass
class RuntimeContainerInfo:
    container_id: str
    status: str
    owned: bool
    labels: Dict[str, str]


class RuntimeAdapter(ABC):
    @abstractmethod
    def create_container(self, validated_spec: Any, instance_id: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def start_container(self, container_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def inspect_container(self, container_id: str) -> RuntimeContainerInfo:
        raise NotImplementedError

    @abstractmethod
    def stop_container(self, container_id: str, timeout: int = 10) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def remove_container(self, container_id: str, force: bool = False) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health_check_container(self, container_id: str) -> Dict[str, Any]:
        raise NotImplementedError
