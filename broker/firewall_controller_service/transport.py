from typing import Protocol, Any, Dict
from .peer_identity import PeerIdentity


class TransportResponse(Dict[str, Any]):
    pass


class ControllerTransport(Protocol):
    def health_check(self, req: Dict[str, Any], peer: PeerIdentity) -> TransportResponse:
        ...

    def install_policy(self, req: Dict[str, Any], peer: PeerIdentity) -> TransportResponse:
        ...

    def inspect_policy(self, req: Dict[str, Any], peer: PeerIdentity) -> TransportResponse:
        ...

    def verify_policy(self, req: Dict[str, Any], peer: PeerIdentity) -> TransportResponse:
        ...

    def revoke_policy(self, req: Dict[str, Any], peer: PeerIdentity) -> TransportResponse:
        ...

    def remove_stale_policy(self, req: Dict[str, Any], peer: PeerIdentity) -> TransportResponse:
        ...

    def reconcile_pending_operations(self, req: Dict[str, Any], peer: PeerIdentity) -> TransportResponse:
        ...
