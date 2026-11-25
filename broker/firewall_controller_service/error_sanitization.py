"""Centralized outward-facing error sanitization for mock controller boundaries.

Maps internal exceptions/messages to bounded public-safe messages while preserving
exception classes and stable error codes/status semantics.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from broker.app.db import BrokerDBError
from broker.app.firewall_controller_contract import (
    FirewallControllerRequestError,
)

from .errors import (
    FirewallControllerAuthError,
    FirewallControllerBackendError,
    FirewallControllerPersistenceError,
)
from .ownership_store import BrokerDBCanonicalError

# Bounded public messages (no raw exception text, no schema/backend internals).
INVALID_REQUEST_MESSAGE = "Invalid request"
INVALID_IDENTIFIER_MESSAGE = "Invalid identifier"
INVALID_CANONICAL_POLICY_MESSAGE = "Invalid canonical policy"
PERSISTENCE_FAILURE_MESSAGE = "Persistence failure"
BACKEND_FAILURE_MESSAGE = "Backend failure"
AUTH_FAILURE_MESSAGE = "Unauthorized"


def bounded_message(default: str, max_len: int = 128) -> str:
    if not isinstance(default, str) or not default:
        return "Request failed"
    return default[:max_len]


def sanitize_request_message(exc: Optional[BaseException] = None, default: str = INVALID_REQUEST_MESSAGE) -> str:
    """Return a bounded validation/request message without raw internal details."""
    # Explicit request errors constructed by our code are allowed only when already
    # bounded and non-sensitive; callers should prefer passing a fixed message.
    return bounded_message(default)


def sanitize_schema_or_rule_message(exc: Optional[BaseException] = None) -> str:
    """Bound schema/rule validation failures (no raw RuleSchemaError text)."""
    return bounded_message(INVALID_REQUEST_MESSAGE)


def sanitize_backend_message(msg: Any = None, default: str = BACKEND_FAILURE_MESSAGE) -> str:
    """Bound backend-facing error text. Never echo backend/internal exception strings."""
    return bounded_message(default)


def sanitize_persistence_message(exc: Optional[BaseException] = None, default: str = PERSISTENCE_FAILURE_MESSAGE) -> str:
    return bounded_message(default)


def sanitize_exception_for_log(exc: BaseException) -> Dict[str, Any]:
    """Safe internal diagnostic summary (type only) for audit/evidence contexts."""
    return {"error_type": type(exc).__name__}


def as_request_error(exc: Optional[BaseException] = None, default: str = INVALID_REQUEST_MESSAGE) -> FirewallControllerRequestError:
    return FirewallControllerRequestError(sanitize_request_message(exc, default=default))


def as_persistence_error(exc: Optional[BaseException] = None, default: str = PERSISTENCE_FAILURE_MESSAGE) -> FirewallControllerPersistenceError:
    return FirewallControllerPersistenceError(sanitize_persistence_message(exc, default=default))


def as_backend_error(exc: Optional[BaseException] = None, default: str = BACKEND_FAILURE_MESSAGE) -> FirewallControllerBackendError:
    return FirewallControllerBackendError(sanitize_backend_message(exc, default=default))


def is_persistence_exception(exc: BaseException) -> bool:
    if isinstance(exc, FirewallControllerPersistenceError):
        return True
    if isinstance(exc, BrokerDBError):
        # BrokerDBCanonicalError carries categories; persistence-category is persistence.
        if isinstance(exc, BrokerDBCanonicalError):
            return getattr(exc, "category", None) == BrokerDBCanonicalError.PERSISTENCE
        return True
    return False


def is_canonical_integrity_or_validation_exception(exc: BaseException) -> bool:
    if isinstance(exc, BrokerDBCanonicalError):
        return getattr(exc, "category", None) in (
            BrokerDBCanonicalError.INTEGRITY,
            BrokerDBCanonicalError.OWNERSHIP,
        )
    return False
