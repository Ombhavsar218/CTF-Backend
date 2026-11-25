import hmac
from typing import Any, Dict, Optional


class BrokerAuthorizationError(Exception):
    pass


class BrokerAuthorizer:
    def __init__(self, authorized_manager_user: str = "flaghunt-mgr",
                 authorized_manager_uid: int = -1,
                 authorized_manager_gid: int = -1,
                 broker_token: str = ""):
        self.authorized_manager_user = authorized_manager_user
        self.authorized_manager_uid = authorized_manager_uid
        self.authorized_manager_gid = authorized_manager_gid
        self.broker_token = broker_token

    def verify_peer(self, peer_info: Optional[Dict[str, Any]] = None) -> bool:
        """
        Verify Unix peer credentials. Must not rely solely on bearer token.
        """
        if not peer_info:
            raise BrokerAuthorizationError("Unauthorized peer")
        # Must have credentials
        if peer_info.get("uid") is None and peer_info.get("gid") is None:
            raise BrokerAuthorizationError("Unauthorized peer")
        # Check UID/GID if configured
        if self.authorized_manager_uid >= 0:
            uid = peer_info.get("uid")
            if uid != self.authorized_manager_uid:
                raise BrokerAuthorizationError("Unauthorized peer")
        if self.authorized_manager_gid >= 0:
            gid = peer_info.get("gid")
            if gid != self.authorized_manager_gid:
                raise BrokerAuthorizationError("Unauthorized peer")
        user = peer_info.get("user") or peer_info.get("username")
        if user and self.authorized_manager_user:
            if user != self.authorized_manager_user:
                raise BrokerAuthorizationError("Unauthorized peer")
        return True

    def verify_token(self, token: str = "") -> bool:
        if not self.broker_token:
            return True
        try:
            if hmac.compare_digest(token or "", self.broker_token):
                return True
        except Exception:
            pass
        raise BrokerAuthorizationError("Unauthorized")


authorizer = BrokerAuthorizer()
