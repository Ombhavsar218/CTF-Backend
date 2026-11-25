from broker.app.firewall_controller_contract import _validate_request
from .errors import FirewallControllerRequestError
from .error_sanitization import INVALID_REQUEST_MESSAGE


class RequestValidator:
    def validate(self, req: dict):
        try:
            return _validate_request(req)
        except Exception as e:
            if isinstance(e, FirewallControllerRequestError):
                # Preserve bounded request-validation errors from the contract layer.
                raise
            # Never expose raw internal/schema/backend exception text.
            raise FirewallControllerRequestError(INVALID_REQUEST_MESSAGE)
