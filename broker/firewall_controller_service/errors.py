from broker.app.firewall_controller_contract import (
    FirewallControllerError,
    FirewallControllerRequestError,
    FirewallControllerIdempotencyError,
)


class FirewallControllerAuthError(FirewallControllerError):
    def __init__(self, message: str = "Unauthorized", details=None):
        super().__init__(error_code="UNAUTHORIZED", message=message, details=details)


class FirewallControllerBackendError(FirewallControllerError):
    def __init__(self, message: str = "Backend error", details=None):
        super().__init__(error_code="BACKEND_ERROR", message=message, details=details)


class FirewallControllerPersistenceError(FirewallControllerError):
    """Sanitized persistence failure that must not be mistaken for backend failure."""

    def __init__(self, message: str = "Persistence failure", details=None):
        super().__init__(error_code="PERSISTENCE_FAILURE", message=message, details=details)
