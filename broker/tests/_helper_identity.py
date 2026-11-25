"""Explicit test-only mock helper identity wiring.

The mock helper boundary no longer supplies an implicit UID/GID identity. Tests that
exercise a successful controller->adapter->helper path must opt in explicitly here.
This is a test seam only and is NOT kernel-authenticated peer identity.
"""
from __future__ import annotations

from broker.firewall_controller_service.helper_authorization import (
    MockHelperAuthorizationProvider,
    MockHelperIdentityProvider,
    MockHelperPeerIdentity,
)
from broker.firewall_controller_service.helper_contract import HelperOperation
from broker.firewall_controller_service.mock_backend import MockFirewallBackend

DEFAULT_UID = 1000
DEFAULT_GID = 1000


def mock_identity(uid: int = DEFAULT_UID, gid: int = DEFAULT_GID) -> MockHelperPeerIdentity:
    return MockHelperPeerIdentity(uid=uid, gid=gid, source="test-mock-helper")


def identity_provider(uid: int = DEFAULT_UID, gid: int = DEFAULT_GID) -> MockHelperIdentityProvider:
    return MockHelperIdentityProvider(mock_identity(uid, gid))


def authorized_backend(
    uid: int = DEFAULT_UID,
    gid: int = DEFAULT_GID,
    executor=None,
    allowed_operations=None,
) -> MockFirewallBackend:
    """Build a mock backend with an explicitly injected identity and allowlists.

    The operation allowlist is explicit here. Tests that need least privilege pass a
    narrower set; omitting it opts into the full fixed enum for this test fixture only.
    The production mock authorization provider itself still fails closed when omitted.
    """
    provider = identity_provider(uid, gid)
    if executor is not None:
        return MockFirewallBackend(executor=executor, identity_provider=provider)
    auth = MockHelperAuthorizationProvider(
        allowed_uids={uid},
        allowed_gids={gid},
        allowed_operations=(
            set(allowed_operations)
            if allowed_operations is not None
            else set(HelperOperation)
        ),
    )
    return MockFirewallBackend(helper_auth=auth, identity_provider=provider)
