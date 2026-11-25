from fastapi import Header, HTTPException, Request, status
from typing import Optional

from .authorization import authorizer, BrokerAuthorizationError
from .audit import audit_logger


async def require_broker_auth(request: Request,
                              x_broker_peer_uid: Optional[str] = Header(default=None),
                              x_broker_peer_gid: Optional[str] = Header(default=None),
                              x_broker_peer_user: Optional[str] = Header(default=None),
                              x_broker_token: Optional[str] = Header(default=None)):
    """Resolve broker peer identity at a deliberately MOCK/TEST-ONLY contract.

    ``X-Broker-Peer-*`` headers are a test-transport abstraction only. They are
    accepted solely when no trusted transport identity is attached to the request.
    They are never kernel-authenticated identity and no SO_PEERCRED/UDS claim is
    made here. When an authenticated transport supplies peer credentials, those
    credentials are the only identity source; conflicting headers are ignored and
    audited by event type (never by value).
    """
    header_peer = {}
    try:
        if x_broker_peer_uid is not None:
            header_peer["uid"] = int(x_broker_peer_uid)
        if x_broker_peer_gid is not None:
            header_peer["gid"] = int(x_broker_peer_gid)
        if x_broker_peer_user is not None:
            header_peer["user"] = x_broker_peer_user
    except Exception:
        audit_logger.log("broker.authz.denied", {"path": str(request.url.path)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    real_peer = getattr(request.state, "peer_credentials", None)
    if real_peer is not None:
        if isinstance(real_peer, dict):
            trusted_peer = dict(real_peer)
        else:
            trusted_peer = dict(getattr(real_peer, 'to_dict', lambda: {})())
        conflicting_fields = sorted(
            key for key, value in header_peer.items()
            if key in trusted_peer and trusted_peer[key] != value
        )
        if conflicting_fields:
            audit_logger.log(
                "broker.identity.header_conflict_ignored",
                {"path": str(request.url.path), "fields": conflicting_fields},
            )
        peer_info = trusted_peer
    else:
        peer_info = header_peer

    try:
        authorizer.verify_peer(peer_info)
        if x_broker_token is not None:
            authorizer.verify_token(x_broker_token)
    except BrokerAuthorizationError:
        audit_logger.log("broker.authz.denied", {"path": str(request.url.path)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    except Exception:
        audit_logger.log("broker.authz.denied", {"path": str(request.url.path)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    return True
