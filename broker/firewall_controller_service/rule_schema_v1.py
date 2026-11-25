"""Canonical firewall rule schema v1 (2H.1 §4.4.1) - local mock-only validation boundary.

This module implements deterministic validation, normalization, and digest helpers for
`rule-schema-v1`. It does not authorize real host firewall operations.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from typing import Any, Dict, Iterable, List, Tuple

RULE_SCHEMA_VERSION = "rule-schema-v1"
PROTOCOL_SCHEMA_VERSION = "2L.2I.2"
ALLOWED_FAMILIES = {"ipv4", "ipv6"}
ALLOWED_DIRECTIONS = {"ingress", "egress"}
ALLOWED_PROTOCOLS = {"tcp", "udp"}
ALLOWED_ACTIONS = {"accept", "drop"}
REQUIRED_RULE_FIELDS = {
    "family",
    "direction",
    "protocol",
    "source_cidr",
    "destination_cidr",
    "port_start",
    "port_end",
    "action",
}
MAX_RULES = 256
MAX_COMPILED_DEPTH = 6
MAX_COMPILED_STRING = 4096
# Exact keys used by the legacy flat-rule/compiler representation. They are not
# part of the canonical schema-v1 request or compiled-data contract. Detecting
# them prevents an ambiguous mixed representation from reaching persistence.
LEGACY_FLAT_RULE_MARKERS = frozenset({
    "ip_version", "source_component", "targets", "dest_ip", "dest_subnet",
    "dest_port", "default_action", "rule_count", "canonical",
})
_DIGEST_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_IPv4_RE = re.compile(r"\A(?:0|[1-9]\d{0,2})(?:\.(?:0|[1-9]\d{0,2})){3}\Z")
_HEX_UPPER_RE = re.compile(r"[A-F]")

_IPV4_SPECIAL_PREFIXES = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
)
_IPV6_SPECIAL_PREFIXES = (
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("2001:db8::/32"),
)


class RuleSchemaError(ValueError):
    def __init__(self, code: str, message: str, details: Dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _reject_unknown_fields(obj: Dict[str, Any], allowed: set[str], code: str = "UNKNOWN_FIELD"):
    unknown = sorted(k for k in obj.keys() if k not in allowed)
    if unknown:
        raise RuleSchemaError(code, "Unknown fields", {"fields": unknown})


def _ensure_json_safe_canonical(value: Any, depth: int = 0):
    if depth > 64:
        raise RuleSchemaError("INVALID_RULE", "Rule nesting too deep")
    if value is None:
        raise RuleSchemaError("INVALID_RULE", "Null values are not allowed")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise RuleSchemaError("INVALID_RULE", "Float values are not allowed")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_ensure_json_safe_canonical(v, depth + 1) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise RuleSchemaError("INVALID_RULE", "Non-string object keys are not allowed")
            if k in out:
                raise RuleSchemaError("DUPLICATE_FIELD", "Duplicate object keys are not allowed")
            out[k] = _ensure_json_safe_canonical(v, depth + 1)
        return out
    raise RuleSchemaError("INVALID_RULE", "Unsupported value type")


def canonical_json_dumps(value: Any) -> str:
    canonical = _ensure_json_safe_canonical(value)
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_special_or_forbidden(net: ipaddress._BaseNetwork) -> bool:
    if net.prefixlen == 0:
        return True
    addr = net.network_address
    if net.version == 4:
        if addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
            return True
        for blocked in _IPV4_SPECIAL_PREFIXES:
            if net.subnet_of(blocked):
                return True
        return False
    else:
        if addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
            return True
        if addr.ipv4_mapped is not None:
            return True
        for blocked in _IPV6_SPECIAL_PREFIXES:
            if net.subnet_of(blocked):
                return True
        return False


def _normalize_cidr(value: Any, family: str, field: str) -> str:
    if not isinstance(value, str):
        raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
    if len(value) > 128 or any(c.isspace() for c in value):
        raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
    if family == "ipv4":
        # strict dotted decimal + prefix; reject leading zero components like 01
        if "/" not in value:
            raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
        ip_part, prefix_part = value.rsplit("/", 1)
        if not _IPv4_RE.fullmatch(ip_part) or not prefix_part.isdigit():
            raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
        prefix = int(prefix_part)
        if prefix < 0 or prefix > 32:
            raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
        try:
            net = ipaddress.IPv4Network(value, strict=True)
        except Exception:
            raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
        if _is_special_or_forbidden(net):
            raise RuleSchemaError("INVALID_RULE", f"Forbidden CIDR in {field}")
        return str(net)
    elif family == "ipv6":
        if "/" not in value:
            raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
        if "[" in value or "]" in value or "%" in value or _HEX_UPPER_RE.search(value):
            raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
        ip_part, prefix_part = value.rsplit("/", 1)
        if not prefix_part.isdigit():
            raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
        prefix = int(prefix_part)
        if prefix < 0 or prefix > 128:
            raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
        try:
            addr = ipaddress.IPv6Address(ip_part)
            net = ipaddress.IPv6Network(value, strict=True)
        except Exception:
            raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
        # RFC5952 canonical text check
        canonical = str(net)
        if canonical != value:
            # allow only exact canonical compressed lowercase form
            raise RuleSchemaError("INVALID_RULE", f"Non-canonical IPv6 CIDR in {field}")
        if _is_special_or_forbidden(net):
            raise RuleSchemaError("INVALID_RULE", f"Forbidden CIDR in {field}")
        return canonical
    else:
        raise RuleSchemaError("INVALID_RULE", "Invalid family")


def _validate_port(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
    if value < 1 or value > 65535:
        raise RuleSchemaError("INVALID_RULE", f"Invalid {field}")
    return value


def validate_and_normalize_rule(rule: Any, index: int = 0) -> Dict[str, Any]:
    if not isinstance(rule, dict):
        raise RuleSchemaError("INVALID_RULE", "Rule must be an object", {"index": index})
    _reject_unknown_fields(rule, REQUIRED_RULE_FIELDS, "UNKNOWN_FIELD")

    missing = sorted(REQUIRED_RULE_FIELDS - set(rule.keys()))
    if missing:
        raise RuleSchemaError("INVALID_RULE", "Missing rule fields", {"fields": missing, "index": index})

    family = rule.get("family")
    if not isinstance(family, str) or family not in ALLOWED_FAMILIES:
        raise RuleSchemaError("INVALID_RULE", "Invalid family", {"index": index})

    direction = rule.get("direction")
    if not isinstance(direction, str) or direction not in ALLOWED_DIRECTIONS:
        raise RuleSchemaError("INVALID_RULE", "Invalid direction", {"index": index})

    protocol = rule.get("protocol")
    if not isinstance(protocol, str):
        raise RuleSchemaError("INVALID_RULE", "Invalid protocol", {"index": index})
    if protocol in ("icmp", "icmpv6"):
        raise RuleSchemaError("UNSUPPORTED_RULE", "ICMP/ICMPv6 are not supported in rule-schema-v1", {"index": index})
    if protocol not in ALLOWED_PROTOCOLS:
        raise RuleSchemaError("UNSUPPORTED_RULE", "Unsupported protocol", {"index": index, "protocol": protocol})

    action = rule.get("action")
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        raise RuleSchemaError("INVALID_RULE", "Invalid action", {"index": index})

    source_cidr = _normalize_cidr(rule.get("source_cidr"), family, "source_cidr")
    destination_cidr = _normalize_cidr(rule.get("destination_cidr"), family, "destination_cidr")

    port_start = _validate_port(rule.get("port_start"), "port_start")
    port_end = _validate_port(rule.get("port_end"), "port_end")
    if port_end < port_start:
        raise RuleSchemaError("INVALID_RULE", "port_end must be >= port_start", {"index": index})
    if action == "accept" and port_start == 1 and port_end == 65535:
        raise RuleSchemaError("INVALID_RULE", "Full 1..65535 accept range is rejected", {"index": index})

    normalized = {
        "family": family,
        "direction": direction,
        "protocol": protocol,
        "source_cidr": source_cidr,
        "destination_cidr": destination_cidr,
        "port_start": port_start,
        "port_end": port_end,
        "action": action,
    }
    return normalized


def _rule_match_key(rule: Dict[str, Any]) -> Tuple:
    return (
        rule["family"], rule["direction"], rule["protocol"],
        rule["source_cidr"], rule["destination_cidr"],
        rule["port_start"], rule["port_end"],
    )


def validate_and_normalize_rules(rules: Any, required_families: Any = None) -> List[Dict[str, Any]]:
    if not isinstance(rules, list):
        raise RuleSchemaError("INVALID_RULE", "rules must be an array")
    if len(rules) == 0:
        raise RuleSchemaError("INVALID_RULE", "rules must be non-empty")
    if len(rules) > MAX_RULES:
        raise RuleSchemaError("INVALID_RULE", "Too many rules", {"max": MAX_RULES})

    normalized: List[Dict[str, Any]] = []
    seen_exact = set()
    for idx, rule in enumerate(rules):
        nr = validate_and_normalize_rule(rule, idx)
        exact = canonical_json_dumps(nr)
        if exact in seen_exact:
            raise RuleSchemaError("INVALID_RULE", "Identical duplicate rules are rejected", {"index": idx})
        seen_exact.add(exact)
        normalized.append(nr)

    # ambiguity: same match key but different action
    by_match: Dict[Tuple, str] = {}
    for idx, nr in enumerate(normalized):
        mk = _rule_match_key(nr)
        if mk in by_match and by_match[mk] != nr["action"]:
            raise RuleSchemaError("AMBIGUOUS_RULE", "Conflicting overlapping rules", {"index": idx})
        by_match[mk] = nr["action"]

    if required_families is not None:
        if not isinstance(required_families, list) or not required_families:
            raise RuleSchemaError("INVALID_RULE", "required_families must be a non-empty array")
        rf_norm = []
        seen_rf = set()
        for f in required_families:
            if not isinstance(f, str) or f not in ALLOWED_FAMILIES:
                raise RuleSchemaError("INVALID_RULE", "Invalid required_families")
            if f in seen_rf:
                raise RuleSchemaError("INVALID_RULE", "Duplicate required_families")
            seen_rf.add(f)
            rf_norm.append(f)
        # preserve sorted uniqueness expectation in many systems? spec states "sorted, duplicate-free"
        if rf_norm != sorted(rf_norm):
            raise RuleSchemaError("INVALID_RULE", "required_families must be sorted and duplicate-free")
        present = {r["family"] for r in normalized}
        for f in rf_norm:
            if f not in present:
                raise RuleSchemaError("INVALID_RULE", "required_families entry missing matching rule", {"family": f})
        for r in normalized:
            if r["family"] not in seen_rf:
                raise RuleSchemaError("INVALID_RULE", "Rule family not in required_families", {"family": r["family"]})

    return normalized


def compiled_rule_digest(rules: List[Dict[str, Any]]) -> str:
    return _sha256_hex(canonical_json_dumps(rules))


def canonical_policy_digest(
    policy_id: str,
    policy_version: int,
    ownership_reference: str,
    required_families: List[str],
    rules: List[Dict[str, Any]],
    instance_id: str | None = None,
    network_id: str | None = None,
) -> str:
    obj = {
        "instance_id": instance_id or "",
        "network_id": network_id or "",
        "ownership_reference": ownership_reference,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "required_families": list(required_families),
        "rules": rules,
    }
    return _sha256_hex(canonical_json_dumps(obj))


def validate_compiled_mirror(compiled: Any, normalized_rules: List[Dict[str, Any]], protocol_schema_version: str = PROTOCOL_SCHEMA_VERSION):
    if compiled is None:
        return
    if not isinstance(compiled, dict):
        raise RuleSchemaError("INVALID_RULE", "compiled must be an object")
    # An empty ``compiled`` object is the one explicit legacy/no-mirror marker and
    # remains compatible. Any other representation must satisfy the schema-v1
    # mirror contract; representation shape can no longer bypass validation.
    if compiled == {}:
        return
    _reject_unknown_fields(compiled, {"schema_version", "rules"}, "UNKNOWN_FIELD")
    if compiled.get("schema_version") != protocol_schema_version:
        raise RuleSchemaError("INVALID_RULE", "Invalid compiled.schema_version")
    if "rules" not in compiled:
        raise RuleSchemaError("INVALID_RULE", "compiled.rules is required")
    c_rules = compiled.get("rules")
    if not isinstance(c_rules, list):
        raise RuleSchemaError("INVALID_RULE", "compiled.rules must be an array")
    # data-only bounds
    def _check_depth(v: Any, depth: int = 0):
        if depth > MAX_COMPILED_DEPTH:
            raise RuleSchemaError("INVALID_RULE", "compiled nesting too deep")
        if isinstance(v, str) and len(v) > MAX_COMPILED_STRING:
            raise RuleSchemaError("INVALID_RULE", "compiled string too long")
        if isinstance(v, list):
            for x in v:
                _check_depth(x, depth + 1)
        elif isinstance(v, dict):
            for x in v.values():
                _check_depth(x, depth + 1)
    _check_depth(c_rules)
    # canonical byte-for-byte comparison of rule set
    try:
        if canonical_json_dumps(c_rules) != canonical_json_dumps(normalized_rules):
            raise RuleSchemaError("INVALID_RULE", "compiled.rules must match canonical rules")
    except RuleSchemaError:
        raise
    except Exception:
        raise RuleSchemaError("INVALID_RULE", "compiled.rules is invalid")


def _contains_legacy_flat_rule_markers(value: Any) -> bool:
    """Detect legacy markers at any nesting depth (bounded by total node count).

    The previous depth-limited recursion let a deeply nested legacy compiled
    representation bypass the canonical boundary. An iterative walk with a node
    budget detects markers regardless of depth and fails closed on oversized
    structures instead of silently returning "no marker".
    """
    stack = [value]
    inspected = 0
    max_nodes = 10000
    while stack:
        current = stack.pop()
        inspected += 1
        if inspected > max_nodes:
            raise RuleSchemaError("INVALID_RULE", "compiled structure too large for marker scan")
        if isinstance(current, dict):
            if any(key in LEGACY_FLAT_RULE_MARKERS for key in current.keys()):
                return True
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return False


def validate_no_mixed_rule_representations(req: Dict[str, Any]) -> None:
    """Reject legacy flat-rule fields at the canonical install boundary.

    A no-rules request with an empty ``compiled`` object remains compatible;
    only exact legacy representation markers are rejected. This aligns the
    controller and mock-adapter ingress validators with the strict
    controller-to-helper compiled-data contract.
    """
    if not isinstance(req, dict):
        raise RuleSchemaError("INVALID_REQUEST", "Request must be an object")
    if any(key in LEGACY_FLAT_RULE_MARKERS for key in req.keys()):
        raise RuleSchemaError(
            "AMBIGUOUS_RULE",
            "Legacy flat-rule fields cannot be combined with canonical requests",
        )
    if _contains_legacy_flat_rule_markers(req.get("compiled")):
        raise RuleSchemaError(
            "AMBIGUOUS_RULE",
            "Legacy flat compiled rules are not valid at the canonical boundary",
        )


def validate_install_policy_rules(req: Dict[str, Any], ownership_rec: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
    """Validate and normalize rule-schema-v1 inputs on install requests.

    Returns normalized info dict when rules are present; None when not applicable.
    Fails closed on malformed/ambiguous rule input.
    """
    if not isinstance(req, dict):
        raise RuleSchemaError("INVALID_REQUEST", "Request must be an object")
    validate_no_mixed_rule_representations(req)
    rules = req.get("rules")
    if rules is None:
        # also reject explicit schema-v1 compiled mirror without rules context
        compiled = req.get("compiled")
        if isinstance(compiled, dict) and compiled.get("schema_version") == PROTOCOL_SCHEMA_VERSION and "rules" in compiled:
            raise RuleSchemaError("INVALID_RULE", "compiled.rules requires top-level rules")
        return None

    required_families = req.get("required_families")
    normalized_rules = validate_and_normalize_rules(rules, required_families=required_families)

    # R16-03: ownership scope is never inferred from arbitrary ownership fields or
    # from a policy payload. Only an explicit, canonical ``owned_network_cidrs``
    # list is an authoritative mock-only scope assertion. Other CIDR-scope-like
    # keys are rejected as unsupported claims rather than silently ignored.
    if ownership_rec and isinstance(ownership_rec, dict):
        scope_keys = (
            "network_cidr", "owned_network_cidr", "challenge_network_cidr",
            "subnet", "network_subnet", "network_cidrs",
        )
        explicit_scope = ownership_rec.get("owned_network_cidrs")
        if explicit_scope is None:
            claimed = [key for key in scope_keys if ownership_rec.get(key) not in (None, "", [], {})]
            if claimed:
                raise RuleSchemaError(
                    "UNSUPPORTED_OWNERSHIP_SCOPE",
                    "Unsupported ownership CIDR claim: provide an explicit owned_network_cidrs scope",
                    {"fields": sorted(claimed)},
                )
        else:
            if not isinstance(explicit_scope, list) or not explicit_scope or len(explicit_scope) > 16:
                raise RuleSchemaError(
                    "UNSUPPORTED_OWNERSHIP_SCOPE", "owned_network_cidrs must be a non-empty list"
                )
            owned_nets = []
            for value in explicit_scope:
                if not isinstance(value, str):
                    raise RuleSchemaError("UNSUPPORTED_OWNERSHIP_SCOPE", "owned_network_cidrs entries must be strings")
                try:
                    owned_nets.append(ipaddress.ip_network(value, strict=True))
                except ValueError:
                    raise RuleSchemaError(
                        "UNSUPPORTED_OWNERSHIP_SCOPE", "owned_network_cidrs entries must be canonical CIDRs"
                    )
            for nr in normalized_rules:
                s = ipaddress.ip_network(nr["source_cidr"], strict=False)
                d = ipaddress.ip_network(nr["destination_cidr"], strict=False)
                if not any(s.subnet_of(n) for n in owned_nets if n.version == s.version):
                    raise RuleSchemaError("INVALID_RULE", "source_cidr outside owned challenge network")
                if not any(d.subnet_of(n) for n in owned_nets if n.version == d.version):
                    raise RuleSchemaError("INVALID_RULE", "destination_cidr outside owned challenge network")

    compiled = req.get("compiled")
    validate_compiled_mirror(compiled, normalized_rules)

    crd = compiled_rule_digest(normalized_rules)
    provided_crd = req.get("compiled_rule_digest")
    if provided_crd is not None:
        if not isinstance(provided_crd, str) or not _DIGEST_RE.fullmatch(provided_crd):
            raise RuleSchemaError("INVALID_DIGEST", "Invalid compiled_rule_digest")
        if provided_crd != crd:
            raise RuleSchemaError("INVALID_DIGEST", "compiled_rule_digest does not match canonical rules")

    # canonical_policy_digest validation when ownership context available
    provided_cpd = req.get("canonical_policy_digest")
    rf_sorted = sorted({r["family"] for r in normalized_rules}) if required_families is None else list(required_families)
    if provided_cpd is not None:
        if not isinstance(provided_cpd, str) or not _DIGEST_RE.fullmatch(provided_cpd):
            raise RuleSchemaError("INVALID_DIGEST", "Invalid canonical_policy_digest")
        ownership_ref = req.get("ownership_reference") or req.get("ownership_record_id") or (ownership_rec or {}).get("ownership_record_id") or ""
        expected_cpd = canonical_policy_digest(
            str(req.get("policy_id") or ""),
            int(req.get("policy_version") or 0) if isinstance(req.get("policy_version"), int) and not isinstance(req.get("policy_version"), bool) else 0,
            str(ownership_ref),
            rf_sorted,
            normalized_rules,
            instance_id=req.get("instance_id") or (ownership_rec or {}).get("instance_id"),
            network_id=req.get("network_id") or (ownership_rec or {}).get("network_id"),
        )
        # R16-04: canonical_policy_digest is a binding over the complete canonical
        # policy (identity, version, metadata, families and rules). A compiled-rules
        # only digest is never an acceptable substitute.
        if provided_cpd != expected_cpd:
            raise RuleSchemaError("INVALID_DIGEST", "canonical_policy_digest does not match canonical policy")

    return {
        "rules": normalized_rules,
        "required_families": rf_sorted,
        "compiled_rule_digest": crd,
        "canonical_policy_digest": provided_cpd,
    }
