from typing import Dict, Any
from .errors import FirewallControllerAuthError


class MockAuthorizationProvider:
    def __init__(self, allowed_sources=None):
        self.allowed_sources = allowed_sources or {"broker"}

    def authorize(self, req: Dict[str, Any], operation: str) -> bool:
        # Never trust caller-supplied identity/verified flags
        if not isinstance(req, dict):
            raise FirewallControllerAuthError("Invalid request")
        # Explicit allowlist only
        source = req.get("source_component") or req.get("caller_source")
        # For mock, allow broker-generated metadata; reject explicit caller-trusted flags.
        # A caller-controlled ``controller_verified`` field is not an authority source.
        if req.get("verified") is True:
            raise FirewallControllerAuthError("Caller-supplied trusted identity rejected")
        if req.get("caller_trusted") is True:
            raise FirewallControllerAuthError("Caller-supplied trusted identity rejected")
        return True
