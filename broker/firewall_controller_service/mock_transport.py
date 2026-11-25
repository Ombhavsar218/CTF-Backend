from typing import Dict, Any
from .controller_service import FirewallControllerService
from .peer_identity import PeerIdentity
from .errors import FirewallControllerAuthError


class MockControllerTransport:
    def __init__(self, service: FirewallControllerService = None):
        self.service = service or FirewallControllerService()

    def _inject_peer(self, req: Dict[str, Any], peer: PeerIdentity) -> Dict[str, Any]:
        if not peer:
            raise FirewallControllerAuthError("Missing peer identity")
        r = dict(req or {})
        # Never trust caller-supplied identity
        r['peer_uid'] = int(peer.uid)
        r['peer_gid'] = int(peer.gid)
        return r

    def health_check(self, req: Dict[str, Any], peer: PeerIdentity):
        return self.service.health_check(self._inject_peer(req, peer))

    def install_policy(self, req: Dict[str, Any], peer: PeerIdentity):
        return self.service.install_policy(self._inject_peer(req, peer))

    def inspect_policy(self, req: Dict[str, Any], peer: PeerIdentity):
        return self.service.inspect_policy(self._inject_peer(req, peer))

    def verify_policy(self, req: Dict[str, Any], peer: PeerIdentity):
        return self.service.verify_policy(self._inject_peer(req, peer))

    def revoke_policy(self, req: Dict[str, Any], peer: PeerIdentity):
        return self.service.revoke_policy(self._inject_peer(req, peer))

    def remove_stale_policy(self, req: Dict[str, Any], peer: PeerIdentity):
        return self.service.remove_stale_policy(self._inject_peer(req, peer))

    def reconcile_pending_operations(self, req: Dict[str, Any], peer: PeerIdentity):
        return self.service.reconcile_pending_operations(self._inject_peer(req, peer))
