"""Helper-side authorization boundary (mock-only).

Authenticated peer identity must originate from the future transport layer or an explicitly
injected mock identity provider. Request JSON can never establish identity.

The authorization provider is strictly per-request: it requires the caller to supply the
already-authenticated identity for *this* operation. There is no implicit/default identity,
no fallback to a provider stored inside the authorizer, and empty allowlists fail closed.

Real deployment MUST obtain the identity from kernel-authenticated IPC peer credentials
(for example UDS with SO_PEERCRED) or an independently approved equivalent. The mock
identity below is a test seam only and proves nothing about real peer authentication.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set

from .errors import FirewallControllerAuthError
from .helper_contract import HelperOperation


@dataclass(frozen=True)
class MockHelperPeerIdentity:
    """Explicitly named mock identity record (NOT real peer auth, NOT SO_PEERCRED)."""
    uid: int
    gid: int
    source: str = "mock-helper-transport"
    pid: Optional[int] = None


class HelperAuthorizationProvider:
    def authorize(
        self,
        identity: Optional[MockHelperPeerIdentity],
        operation: HelperOperation,
        request: Optional[Dict] = None,
    ) -> bool:
        raise NotImplementedError


class MockHelperAuthorizationProvider(HelperAuthorizationProvider):
    """Mock helper authorization with explicit per-request identity.

    Every allowlist is fail-closed: omitted or empty UID/GID/operation sets authorize
    nothing. Callers must explicitly enumerate the helper operations they need.
    """

    def __init__(
        self,
        allowed_uids: Optional[Set[int]] = None,
        allowed_gids: Optional[Set[int]] = None,
        allowed_operations: Optional[Set[HelperOperation]] = None,
    ):
        self.allowed_uids = set() if allowed_uids is None else set(allowed_uids)
        self.allowed_gids = set() if allowed_gids is None else set(allowed_gids)
        self.allowed_operations = set() if allowed_operations is None else set(allowed_operations)

    def authorize(
        self,
        identity: Optional[MockHelperPeerIdentity],
        operation: HelperOperation,
        request: Optional[Dict] = None,
    ) -> bool:
        # Identity must be supplied for this specific request. Never derive from request JSON.
        if identity is None:
            raise FirewallControllerAuthError("Missing helper peer identity")
        if not isinstance(identity, MockHelperPeerIdentity):
            raise FirewallControllerAuthError("Invalid helper peer identity")
        try:
            uid = int(identity.uid)
            gid = int(identity.gid)
        except Exception:
            raise FirewallControllerAuthError("Invalid helper peer identity")
        # Empty allowlists fail closed
        if len(self.allowed_uids) == 0:
            raise FirewallControllerAuthError("No authorized helper UIDs")
        if len(self.allowed_gids) == 0:
            raise FirewallControllerAuthError("No authorized helper GIDs")
        if operation not in self.allowed_operations:
            raise FirewallControllerAuthError("Helper operation not allowed")
        if uid not in self.allowed_uids:
            raise FirewallControllerAuthError("Unauthorized helper UID")
        if gid not in self.allowed_gids:
            raise FirewallControllerAuthError("Unauthorized helper GID")
        return True


class MockHelperIdentityProvider:
    """Explicitly named mock identity provider used by the controller->helper adapter.

    It returns the identity for the current mock request. It does NOT implement
    SO_PEERCRED or any real peer authentication and must never be wired into a
    production deployment. A provider may return a different identity on each call
    so that each request is authorized independently.
    """

    def __init__(self, identity: Optional[MockHelperPeerIdentity] = None):
        self._identity = identity

    def get_identity(self) -> Optional[MockHelperPeerIdentity]:
        return self._identity
