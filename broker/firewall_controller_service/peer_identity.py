from dataclasses import dataclass
from typing import Optional, Set


@dataclass(frozen=True)
class PeerIdentity:
    uid: int
    gid: int
    pid: Optional[int] = None
    comm: Optional[str] = None


class PeerIdentityProvider:
    def get_identity(self, context: dict = None) -> Optional[PeerIdentity]:
        raise NotImplementedError


class MockPeerIdentityProvider(PeerIdentityProvider):
    def __init__(self, identity: PeerIdentity = None):
        self._identity = identity

    def get_identity(self, context: dict = None) -> Optional[PeerIdentity]:
        if self._identity:
            return self._identity
        ctx = context or {}
        if ctx.get('peer_uid') is not None and ctx.get('peer_gid') is not None:
            return PeerIdentity(uid=int(ctx['peer_uid']), gid=int(ctx['peer_gid']))
        return None
