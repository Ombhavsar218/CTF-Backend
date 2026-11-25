"""Strict typed contract between unprivileged controller and future privileged helper (mock-only integration).

No shell/command execution, no host state changes. Rejects unknown fields and invalid values (fail closed).

Schema version is mandatory and must exactly match SCHEMA_VERSION. Timeout enforcement is intentionally
declared as a future transport/process-layer responsibility; this module only validates the requested bound.
"""
from __future__ import annotations

import ipaddress
import json
import re
from enum import Enum
from typing import Any, Dict, Optional, Set

SCHEMA_VERSION = "2L.2G.3"
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MIN_TIMEOUT_MS = 1
MAX_TIMEOUT_MS = 120_000
MAX_RULE_ENTRIES = 256
MAX_PORT = 65535
MAX_COMPILED_DEPTH = 6
MAX_COMPILED_STRING = 4096
ALLOWED_FAMILIES = {"ipv4", "ipv6"}
ALLOWED_PROTOCOLS = {"tcp", "udp", "icmp", "icmpv6", "any"}

# Exact supported digest format (SHA-256 hex). Do not silently accept short/truncated
# digests, surrounding whitespace, or a trailing newline (`$` matches before "\n").
_DIGEST_RE = re.compile(r"\A[a-fA-F0-9]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")

# Data-only compiled policy shape (mock scope). The real helper must treat this as data, never execute it.
COMPILED_ALLOWED_KEYS = {"rules", "entries", "rule_handles", "policy", "metadata", "families", "digest"}
_FORBIDDEN_COMPILED_TOKENS = (
    ";", "`", "$(", "${", "|", "&&", "||", ">", "<", "\n", "\r", "\x00",
    "/bin/", "sh -c", "eval(", "exec(", "nft ", "iptables ", "ufw ",
)

# Timeout enforcement is NOT performed here; real transport/process layer must enforce deadlines.
TIMEOUT_ENFORCEMENT_LAYER = "future transport/process layer"


class HelperOperation(str, Enum):
    HEALTH_CHECK = "HEALTH_CHECK"
    INSTALL_POLICY = "INSTALL_POLICY"
    INSPECT_POLICY = "INSPECT_POLICY"
    VERIFY_POLICY = "VERIFY_POLICY"
    REVOKE_POLICY = "REVOKE_POLICY"
    REMOVE_OWNED_POLICY = "REMOVE_OWNED_POLICY"
    RECONCILE_OWNED_POLICY = "RECONCILE_OWNED_POLICY"


METHOD_TO_OPERATION = {
    "health_check": HelperOperation.HEALTH_CHECK,
    "install_policy": HelperOperation.INSTALL_POLICY,
    "inspect_policy": HelperOperation.INSPECT_POLICY,
    "verify_policy": HelperOperation.VERIFY_POLICY,
    "revoke_policy": HelperOperation.REVOKE_POLICY,
    "remove_stale_policy": HelperOperation.REMOVE_OWNED_POLICY,
    "reconcile_pending_operations": HelperOperation.RECONCILE_OWNED_POLICY,
}

# Fields allowed in controller->helper requests (superset for compatibility; unknown fields rejected).
# Identity/auth-claim fields from callers are NOT trusted for authorization; helper auth uses transport/mock identity.
COMMON_ALLOWED: Set[str] = {
    "schema_version", "operation", "request_id", "operation_id", "idempotency_key",
    "policy_id", "policy_version", "compiled_rule_digest", "canonical_policy_digest",
    "ownership_reference", "ownership_record_id", "instance_id", "network_id",
    "address_family", "required_families", "ip_cidr", "source_cidr", "destination_cidr",
    "protocol", "port", "ports", "compiled", "rules", "timeout_ms", "expected_ownership_identity",
}
# Fields that must never establish identity/authorization at helper boundary.
FORBIDDEN_AUTH_CLAIM_FIELDS = {
    "peer_uid", "peer_gid", "uid", "gid", "pid", "caller_uid", "caller_gid",
    "caller_trusted", "verified", "trusted", "auth_identity", "x_identity",
    "source_identity", "controller_verified", "authorized", "is_admin",
}


class HelperContractError(ValueError):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _bounded_json_size(obj: Any, max_bytes: int, label: str):
    try:
        raw = json.dumps(obj, sort_keys=True).encode("utf-8")
    except Exception:
        raise HelperContractError("INVALID_REQUEST", f"{label} is not serializable")
    if len(raw) > max_bytes:
        raise HelperContractError("REQUEST_TOO_LARGE", f"{label} exceeds bound", {"max_bytes": max_bytes})


def _validate_id(value: Any, name: str):
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise HelperContractError("INVALID_REQUEST", f"Invalid {name}")


def _validate_digest(value: Any, name: str = "digest"):
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise HelperContractError("INVALID_REQUEST", f"Invalid {name} (expected 64 hex chars)")


def _validate_cidr(value: Any, family_hint: Optional[str] = None):
    if value is None:
        return
    if not isinstance(value, str) or len(value) > 64:
        raise HelperContractError("INVALID_REQUEST", "Invalid CIDR")
    try:
        net = ipaddress.ip_network(value, strict=False)
    except Exception:
        raise HelperContractError("INVALID_REQUEST", "Invalid CIDR")
    if family_hint == "ipv4" and net.version != 4:
        raise HelperContractError("INVALID_REQUEST", "CIDR family mismatch")
    if family_hint == "ipv6" and net.version != 6:
        raise HelperContractError("INVALID_REQUEST", "CIDR family mismatch")


def _validate_protocol_port(protocol: Any = None, port: Any = None, ports: Any = None):
    if protocol is not None:
        if not isinstance(protocol, str) or protocol.lower() not in ALLOWED_PROTOCOLS:
            raise HelperContractError("INVALID_REQUEST", "Invalid protocol")
    def check_port(p):
        if not isinstance(p, int) or p < 0 or p > MAX_PORT:
            raise HelperContractError("INVALID_REQUEST", "Invalid port")
    if port is not None:
        check_port(port)
    if ports is not None:
        if not isinstance(ports, list) or len(ports) > 64:
            raise HelperContractError("INVALID_REQUEST", "Invalid ports")
        for p in ports:
            check_port(p)


def _validate_compiled(value: Any, depth: int = 0):
    if depth > MAX_COMPILED_DEPTH:
        raise HelperContractError("INVALID_REQUEST", "Compiled policy nesting too deep")
    if isinstance(value, dict):
        unknown = set(value.keys()) - COMPILED_ALLOWED_KEYS
        if unknown:
            raise HelperContractError("INVALID_REQUEST", "Unexpected compiled policy field", {"fields": sorted(map(str, unknown))})
        for k, v in value.items():
            _validate_compiled(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _validate_compiled(v, depth + 1)
    elif isinstance(value, str):
        if len(value) > MAX_COMPILED_STRING:
            raise HelperContractError("INVALID_REQUEST", "Compiled policy string too long")
        low = value.lower()
        for token in _FORBIDDEN_COMPILED_TOKENS:
            if token in low:
                raise HelperContractError("INVALID_REQUEST", "Compiled policy contains executable/expression-like content")
    elif value is None or isinstance(value, (bool, int, float)):
        return
    else:
        raise HelperContractError("INVALID_REQUEST", "Unsupported compiled policy value type")


def validate_helper_request(req: Dict[str, Any], operation: HelperOperation) -> Dict[str, Any]:
    if not isinstance(req, dict):
        raise HelperContractError("INVALID_REQUEST", "Request must be an object")
    if not isinstance(operation, HelperOperation):
        raise HelperContractError("INVALID_REQUEST", "Invalid operation")
    _bounded_json_size(req, MAX_REQUEST_BYTES, "request")
    # Reject explicit auth/identity claims in JSON first (cannot establish identity)
    present_forbidden = [k for k in FORBIDDEN_AUTH_CLAIM_FIELDS if k in req]
    if present_forbidden:
        raise HelperContractError("UNAUTHORIZED_CLAIM", "Caller-supplied identity/authorization claims rejected", {"fields": sorted(present_forbidden)})
    unknown = set(req.keys()) - COMMON_ALLOWED
    # Reject unknown fields (strict). Allow nothing else.
    if unknown:
        raise HelperContractError("INVALID_REQUEST", "Unknown request fields", {"fields": sorted(unknown)})

    # Mandatory exact schema version (no implicit default, no alias fields).
    if "schema_version" not in req:
        raise HelperContractError("INVALID_REQUEST", "Missing schema_version")
    schema_version = req.get("schema_version")
    if not isinstance(schema_version, str) or schema_version == "":
        raise HelperContractError("INVALID_REQUEST", "Invalid schema_version")
    if schema_version != SCHEMA_VERSION:
        raise HelperContractError("UNSUPPORTED_SCHEMA_VERSION", "Unsupported schema_version", {"supported": SCHEMA_VERSION})

    # Explicit operation, if supplied, must not conflict with the dispatched operation.
    if "operation" in req and req.get("operation") != operation.value:
        raise HelperContractError("OPERATION_MISMATCH", "Operation field conflicts with dispatched operation")

    timeout_ms = req.get("timeout_ms")
    if timeout_ms is not None:
        if not isinstance(timeout_ms, int) or timeout_ms < MIN_TIMEOUT_MS or timeout_ms > MAX_TIMEOUT_MS:
            raise HelperContractError("INVALID_REQUEST", "Invalid timeout_ms")

    # Common required identifiers
    for field in ("request_id", "operation_id", "idempotency_key"):
        _validate_id(req.get(field), field)

    if operation != HelperOperation.HEALTH_CHECK:
        _validate_id(req.get("policy_id"), "policy_id")
        pv = req.get("policy_version")
        if not isinstance(pv, int) or pv < 0:
            raise HelperContractError("INVALID_REQUEST", "Invalid policy_version")
        digest = req.get("compiled_rule_digest") or req.get("canonical_policy_digest")
        _validate_digest(digest, "compiled_rule_digest/canonical_policy_digest")
        # Authoritative ownership reference is mandatory; do not fall back to instance/policy IDs.
        ownership_ref = req.get("ownership_reference") or req.get("ownership_record_id")
        if not isinstance(ownership_ref, str) or not ownership_ref.strip():
            raise HelperContractError("INVALID_REQUEST", "Missing authoritative ownership reference")
        _validate_id(ownership_ref, "ownership_reference")
        # instance_id/network_id are optional at the helper boundary; when present
        # and non-empty they use the same canonical identifier rule as the controller.
        for field in ("instance_id", "network_id"):
            value = req.get(field)
            if value not in (None, ""):
                _validate_id(value, field)
        fam = req.get("address_family")
        families = req.get("required_families")
        if fam is not None and (not isinstance(fam, str) or fam.lower() not in ALLOWED_FAMILIES):
            raise HelperContractError("INVALID_REQUEST", "Invalid address_family")
        if families is not None:
            if not isinstance(families, list) or not families:
                raise HelperContractError("INVALID_REQUEST", "Invalid required_families")
            for f in families:
                if not isinstance(f, str) or f.lower() not in ALLOWED_FAMILIES:
                    raise HelperContractError("INVALID_REQUEST", "Invalid required_families")
        family_hint = (fam or (families[0] if families else None))
        if isinstance(family_hint, str):
            family_hint = family_hint.lower()
        for cidr_field in ("ip_cidr", "source_cidr", "destination_cidr"):
            if cidr_field in req:
                _validate_cidr(req.get(cidr_field), family_hint if family_hint in ALLOWED_FAMILIES else None)
        _validate_protocol_port(req.get("protocol"), req.get("port"), req.get("ports"))
        rules = req.get("rules")
        if rules is not None:
            # Canonical rule-schema-v1 boundary validation at helper ingress (mock-only).
            try:
                from .rule_schema_v1 import validate_install_policy_rules
                validate_install_policy_rules(req)
            except Exception as e:
                code = getattr(e, "code", "INVALID_RULE")
                msg = getattr(e, "message", str(e)) or "Invalid rules"
                raise HelperContractError(code, msg)
        compiled = req.get("compiled")
        if compiled is not None:
            if not isinstance(compiled, dict):
                raise HelperContractError("INVALID_REQUEST", "compiled must be an object")
            _bounded_json_size(compiled, MAX_REQUEST_BYTES // 2, "compiled")
            _validate_compiled(compiled)
            for k in ("rules", "entries"):
                v = compiled.get(k)
                if isinstance(v, list) and len(v) > MAX_RULE_ENTRIES:
                    raise HelperContractError("INVALID_REQUEST", "Too many compiled rule entries")

    return req


def validate_helper_response(resp: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(resp, dict):
        raise HelperContractError("INVALID_RESPONSE", "Response must be an object")
    _bounded_json_size(resp, MAX_RESPONSE_BYTES, "response")
    if resp.get("schema_version") != SCHEMA_VERSION:
        raise HelperContractError("INVALID_RESPONSE", "Invalid response schema_version", {"supported": SCHEMA_VERSION})
    return resp
