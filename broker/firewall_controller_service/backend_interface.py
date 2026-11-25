from abc import ABC, abstractmethod
from typing import Dict, Any


class FirewallBackendInterface(ABC):
    @abstractmethod
    def health_check(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def install_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def inspect_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def verify_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def revoke_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def remove_stale_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def reconcile_pending_operations(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError
