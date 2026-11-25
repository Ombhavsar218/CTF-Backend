import uuid
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict


class FirewallControllerError(Exception):
    def __init__(self, error_code: str = "CONTROLLER_ERROR", message: str = "Controller error", details: Dict[str, Any] = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


class FirewallControllerRequestError(FirewallControllerError):
    def __init__(self, message: str = "Invalid request", details: Dict[str, Any] = None):
        super().__init__(error_code="REQUEST_INVALID", message=message, details=details)


class FirewallControllerIdempotencyError(FirewallControllerError):
    def __init__(self, message: str = "Idempotency key conflict", details: Dict[str, Any] = None):
        super().__init__(error_code="IDEMPOTENCY_CONFLICT", message=message, details=details)


@dataclass
class ControllerRequest:
    request_id: str
    operation_id: str
    idempotency_key: str
    policy_id: str
    policy_version: int
    compiled_rule_digest: str
    instance_id: Optional[str] = None
    network_id: Optional[str] = None
    expected_ownership_identity: Optional[str] = None
    required_families: Optional[List[str]] = None


@dataclass
class ControllerResponse:
    status: str
    request_id: str
    operation_id: str
    controller_id: str
    controller_version: str
    timestamp: float
    result: Dict[str, Any]
    error_code: Optional[str] = None
    error_message: Optional[str] = None


def _validate_request(req: Dict[str, Any]) -> ControllerRequest:
    required = ['request_id', 'operation_id', 'idempotency_key', 'policy_id', 'policy_version', 'compiled_rule_digest']
    for r in required:
        if r not in req or req[r] is None or req[r] == '':
            raise FirewallControllerRequestError(f"Missing {r}")
    pv = req['policy_version']
    if not isinstance(pv, int) or isinstance(pv, bool) or pv < 0:
        raise FirewallControllerRequestError("Invalid policy_version")
    digest = req.get('compiled_rule_digest')
    if not isinstance(digest, str) or not __import__('re').fullmatch(r'\A[a-fA-F0-9]{64}\Z', digest):
        raise FirewallControllerRequestError("Invalid compiled_rule_digest")
    return ControllerRequest(
        request_id=str(req['request_id']),
        operation_id=str(req['operation_id']),
        idempotency_key=str(req['idempotency_key']),
        policy_id=str(req['policy_id']),
        policy_version=int(req['policy_version']),
        compiled_rule_digest=str(req['compiled_rule_digest']),
        instance_id=req.get('instance_id'),
        network_id=req.get('network_id'),
        expected_ownership_identity=req.get('expected_ownership_identity'),
        required_families=req.get('required_families') or ['ipv4'],
    )


class FirewallController:
    def health_check(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def install_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def inspect_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def verify_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def revoke_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def remove_stale_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def reconcile_pending_operations(self, req: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError
