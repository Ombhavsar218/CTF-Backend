"""Mock privileged-helper executor (no real privileged ops, no shell, no host state changes).

Validates strict contract, enforces mock helper authorization against a per-request identity,
supports deterministic failure injection, idempotency, and sanitized audit. Controller uses this
boundary via adapter; no bypass path added.

`timeout_ms` is validated by the contract but wall-clock enforcement is NOT implemented here.
Deadline/timeout enforcement belongs to the future real transport/process layer; until then an
injected timeout is surfaced as a structured non-success result and never as success.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from broker.app.firewall_controller import MockFirewallController

from .errors import FirewallControllerAuthError, FirewallControllerIdempotencyError
from .helper_authorization import MockHelperAuthorizationProvider, MockHelperPeerIdentity
from .helper_contract import (
    HelperContractError,
    HelperOperation,
    METHOD_TO_OPERATION,
    SCHEMA_VERSION,
    validate_helper_request,
    validate_helper_response,
)


class MockHelperExecutor:
    def __init__(
        self,
        auth: Optional[MockHelperAuthorizationProvider] = None,
        controller_id: str = "mock-helper-executor",
        controller_version: str = "0.1.0",
        state_controller: Optional[MockFirewallController] = None,
    ):
        self._ctrl = state_controller or MockFirewallController()
        self.controller_id = controller_id
        self.controller_version = controller_version
        self.audit_events = []
        self._idempotency: Dict[tuple, Dict[str, Any]] = {}
        # Deterministic failure injection (test-only mock)
        self.inject_failures: Dict[HelperOperation, str] = {}
        self.inject_timeout: set = set()
        self.inject_uncertain: set = set()
        # No implicit trusted identity and no default allowlists: fail closed unless the
        # caller explicitly supplies an authorization policy and a per-request identity.
        self.auth = auth or MockHelperAuthorizationProvider(allowed_uids=set(), allowed_gids=set())

    def _audit(self, event_type: str, req: Dict[str, Any], details: Dict[str, Any] = None):
        e = {
            "event_type": event_type,
            "timestamp": time.time(),
            "request_id": (req or {}).get("request_id"),
            "operation_id": (req or {}).get("operation_id"),
            "policy_id": (req or {}).get("policy_id"),
            "details": details or {},
        }
        # Never log secrets/tokens
        self.audit_events.append(e)
        return e

    def _error_resp(self, req: Dict[str, Any], code: str, message: str):
        return {
            "status": "error",
            "request_id": req.get("request_id"),
            "operation_id": req.get("operation_id"),
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "timestamp": time.time(),
            "result": {},
            "error_code": code,
            "error_message": message,
            "schema_version": SCHEMA_VERSION,
        }

    def _idem_key(self, op: HelperOperation, req: Dict[str, Any]):
        digest = req.get("compiled_rule_digest") or req.get("canonical_policy_digest") or ""
        return (op.value, req.get("idempotency_key"), req.get("policy_id"), req.get("policy_version"), digest)

    def execute(self, operation: HelperOperation, req: Dict[str, Any], identity: Optional[MockHelperPeerIdentity] = None) -> Dict[str, Any]:
        req = dict(req or {})
        # Correlate helper operation IDs with controller operation IDs (preserve caller-provided operation_id)
        if not req.get("operation_id"):
            req["operation_id"] = str(uuid.uuid4())
        self._audit("helper_request_received", req, {"operation": operation.value})
        # Identity is supplied separately for this specific request; never derived from request JSON.
        # A missing identity fails closed inside the authorization provider.
        try:
            self.auth.authorize(identity, operation, request=req)
        except FirewallControllerAuthError as e:
            self._audit("helper_authorization_failed", req, {"operation": operation.value, "error": e.error_code})
            raise
        self._audit("helper_authorization_passed", req, {"operation": operation.value})

        # Reject identity/auth claims in payload before schema pass? schema already rejects forbidden fields.
        try:
            validate_helper_request(req, operation)
        except HelperContractError as e:
            self._audit("helper_validation_failed", req, {"operation": operation.value, "code": e.code})
            return self._error_resp(req, e.code, e.message)

        if operation in self.inject_timeout:
            self._audit("helper_timeout_injected", req, {"operation": operation.value})
            return self._error_resp(req, "TIMEOUT", "Injected timeout")
        if operation in self.inject_uncertain:
            self._audit("helper_uncertain_injected", req, {"operation": operation.value})
            return self._error_resp(req, "UNCERTAIN", "Injected uncertain outcome")
        if operation in self.inject_failures:
            code = self.inject_failures[operation]
            self._audit("helper_failure_injected", req, {"operation": operation.value, "code": code})
            return self._error_resp(req, code, "Injected failure")

        idem = self._idem_key(operation, req)
        if idem in self._idempotency:
            prev = self._idempotency[idem]
            if prev.get("digest") != (req.get("compiled_rule_digest") or req.get("canonical_policy_digest")):
                self._audit("helper_idempotency_conflict", req, {"operation": operation.value})
                raise FirewallControllerIdempotencyError("Idempotency key conflict for different payload")
            self._audit("helper_idempotent_replay", req, {"operation": operation.value})
            return prev["response"]

        # Delegate to mock controller state for compatibility (no host state changes)
        try:
            method_name = None
            for m, op in METHOD_TO_OPERATION.items():
                if op == operation:
                    method_name = m
                    break
            if not method_name:
                return self._error_resp(req, "OPERATION_NOT_ALLOWED", "Unknown operation")
            resp = getattr(self._ctrl, method_name)(req)
            # Enrich/correlate IDs
            if isinstance(resp, dict):
                resp = dict(resp)
                resp.setdefault("request_id", req.get("request_id"))
                resp.setdefault("operation_id", req.get("operation_id"))
                resp["schema_version"] = SCHEMA_VERSION
            validate_helper_response(resp)
        except FirewallControllerIdempotencyError:
            self._audit("helper_idempotency_conflict", req, {"operation": operation.value})
            raise
        except Exception as e:
            # R16-07: keep the exception class name for internal diagnostics only.
            # The outward error must be bounded and must not disclose raw internal,
            # backend, schema or exception text to an untrusted caller.
            self._audit("helper_execution_failed", req, {"operation": operation.value, "error": type(e).__name__})
            return self._error_resp(
                req, "EXECUTION_ERROR", "Internal helper execution error; see internal audit"
            )

        # Only definitive successes are replayed. A failed/uncertain attempt has not
        # committed a side effect that may be reported as success; caching it would
        # permanently pin the mock helper to a transient failure and prevent the
        # controller's read-back-driven recovery from re-issuing the operation.
        if isinstance(resp, dict) and resp.get("status") == "ok":
            self._idempotency[idem] = {"digest": req.get("compiled_rule_digest") or req.get("canonical_policy_digest"), "response": resp}
        self._audit("helper_execution_completed", req, {"operation": operation.value, "status": resp.get("status") if isinstance(resp, dict) else None})
        return resp

    def execute_method(self, method_name: str, req: Dict[str, Any], identity: Optional[MockHelperPeerIdentity] = None) -> Dict[str, Any]:
        op = METHOD_TO_OPERATION.get(method_name)
        if op is None:
            return self._error_resp(dict(req or {}), "OPERATION_NOT_ALLOWED", "Unknown operation")
        return self.execute(op, req, identity=identity)
