from typing import Dict, Any, Optional, Set
from .errors import FirewallControllerAuthError


class StrictAuthorizationProvider:
    def __init__(self, allowed_uids: Optional[Set[int]] = None, allowed_gids: Optional[Set[int]] = None, allowed_operations: Optional[Set[str]] = None):
        self.allowed_uids = allowed_uids if allowed_uids is not None else set()
        self.allowed_gids = allowed_gids if allowed_gids is not None else set()
        # ``None`` means "use the controller's fixed supported-operation default".
        # An explicitly supplied empty set is intentional and denies every operation;
        # it must never be broadened back to the default set.
        if allowed_operations is None:
            self.allowed_operations = {"health_check", "install_policy", "inspect_policy", "verify_policy", "revoke_policy", "remove_stale_policy", "reconcile_pending_operations"}
        else:
            self.allowed_operations = set(allowed_operations)

    def authorize(self, req: Dict[str, Any], operation: str) -> bool:
        if not isinstance(req, dict):
            raise FirewallControllerAuthError("Invalid request")
        # Never trust caller-supplied identity headers/flags. In particular, a
        # caller-controlled ``controller_verified`` field must not suppress the
        # strict rejection. Verified state is an internal contract, not request data.
        for bad in ["caller_trusted", "verified", "trusted", "auth_identity", "x_identity", "source_identity"]:
            if req.get(bad) is True:
                raise FirewallControllerAuthError("Caller-supplied trusted identity rejected")
        # Require explicit peer identity (future SO_PEERCRED) - fail closed if missing in strict mode
        peer_uid = req.get("peer_uid")
        peer_gid = req.get("peer_gid")
        if peer_uid is None or peer_gid is None:
            raise FirewallControllerAuthError("Missing peer identity")
        try:
            peer_uid = int(peer_uid)
            peer_gid = int(peer_gid)
        except Exception:
            raise FirewallControllerAuthError("Invalid peer identity")
        if operation not in self.allowed_operations:
            raise FirewallControllerAuthError("Operation not allowed")
        # Fail closed if allowlists are explicitly empty sets
        if isinstance(self.allowed_uids, set) and len(self.allowed_uids) == 0:
            raise FirewallControllerAuthError("No authorized UIDs")
        if isinstance(self.allowed_gids, set) and len(self.allowed_gids) == 0:
            raise FirewallControllerAuthError("No authorized GIDs")
        if peer_uid not in self.allowed_uids:
            raise FirewallControllerAuthError("Unauthorized UID")
        if peer_gid not in self.allowed_gids:
            raise FirewallControllerAuthError("Unauthorized GID")
        return True
