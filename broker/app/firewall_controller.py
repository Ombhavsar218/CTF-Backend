import uuid
import time
import re
from typing import Dict, Any

from .firewall_controller_contract import (
    FirewallController,
    _validate_request,
    ControllerResponse,
    FirewallControllerRequestError,
    FirewallControllerIdempotencyError,
)

_ID_RE = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")


class MockFirewallController(FirewallController):
    def __init__(self):
        self.installed = {}
        self.verified = set()
        self.revoked = set()
        self.fail_install = False
        self.fail_verify = False
        self.fail_revoke = False
        self.fail_install_ipv6 = False
        self.fail_install_ipv4 = False
        self.readback_mismatch = False
        self.ownership_mismatch = False
        self._idempotency = {}
        self._operations = {}
        self.controller_id = "mock-controller"
        self.controller_version = "0.1.0"

    def _resp(self, req, status, result, error_code=None, error_message=None):
        return {
            "status": status,
            "request_id": getattr(req, 'request_id', None),
            "operation_id": getattr(req, 'operation_id', None),
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "timestamp": time.time(),
            "result": result,
            "error_code": error_code,
            "error_message": error_message,
        }

    @staticmethod
    def _validate_canonical_identifiers(req: Dict[str, Any]):
        for field in ('request_id', 'operation_id', 'idempotency_key', 'policy_id'):
            val = (req or {}).get(field)
            if not isinstance(val, str) or not _ID_RE.fullmatch(val):
                raise FirewallControllerRequestError(f"Invalid {field}")
        for field in ('instance_id', 'network_id'):
            if field in (req or {}):
                val = req.get(field)
                if val is not None and val != '':
                    if not isinstance(val, str) or not _ID_RE.fullmatch(val):
                        raise FirewallControllerRequestError(f"Invalid {field}")

    def health_check(self, req: Dict[str, Any] = None) -> Dict[str, Any]:
        if req is None:
            return {"status": "ok", "controller": "mock", "controller_id": self.controller_id, "controller_version": self.controller_version}
        try:
            r = _validate_request({**req, 'request_id': req.get('request_id') or str(uuid.uuid4()), 'operation_id': req.get('operation_id') or str(uuid.uuid4()), 'idempotency_key': req.get('idempotency_key') or str(uuid.uuid4()), 'policy_id': req.get('policy_id') or 'health', 'policy_version': req.get('policy_version') or 0, 'compiled_rule_digest': req.get('compiled_rule_digest') or '0'*64})
            self._validate_canonical_identifiers(req)
            return self._resp(r, "ok", {"status": "ok", "families_supported": ["ipv4", "ipv6"]})
        except FirewallControllerRequestError:
            raise
        except Exception:
            raise FirewallControllerRequestError('Invalid request')

    def install_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        # Canonical schema-v1 rule validation/normalization at mock backend/state boundary when rules are present.
        # Lazy import avoids an import-order-sensitive cycle with firewall_controller_service.mock_backend.
        if isinstance(req, dict):
            from broker.firewall_controller_service.rule_schema_v1 import RuleSchemaError, validate_install_policy_rules
            try:
                rules_info = validate_install_policy_rules(req)
            except RuleSchemaError:
                # Never expose raw schema validation internals in outward errors.
                raise FirewallControllerRequestError('Invalid request')
            if rules_info:
                req = dict(req)
                req['rules'] = rules_info['rules']
                if 'compiled_rule_digest' not in req or req.get('compiled_rule_digest') in (None, ''):
                    req['compiled_rule_digest'] = rules_info['compiled_rule_digest']
                elif req.get('compiled_rule_digest') != rules_info['compiled_rule_digest']:
                    raise FirewallControllerRequestError('Invalid request')
                if rules_info.get('canonical_policy_digest') and not req.get('canonical_policy_digest'):
                    req['canonical_policy_digest'] = rules_info['canonical_policy_digest']
        try:
            r = _validate_request(req)
            self._validate_canonical_identifiers(req)
        except FirewallControllerRequestError as e:
            raise
        key = (r.idempotency_key, r.policy_id, r.policy_version)
        if key in self._idempotency:
            existing = self._idempotency[key]
            if existing.get('digest') != r.compiled_rule_digest:
                raise FirewallControllerIdempotencyError("Idempotency key conflict for different payload")
            return existing['response']
        if self.ownership_mismatch:
            res = self._resp(r, "error", {}, error_code="OWNERSHIP_MISMATCH", error_message="Ownership mismatch")
            self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
            return res
        if self.fail_install or self.fail_install_ipv4 or self.fail_install_ipv6:
            res = self._resp(r, "error", {"partial": {"ipv4": not self.fail_install_ipv4, "ipv6": not self.fail_install_ipv6}}, error_code="INSTALL_FAILED", error_message="Installation failed")
            self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
            return res
        self.installed[r.policy_id] = {
            "compiled": req.get('compiled'),
            "digest": r.compiled_rule_digest,
            "version": r.policy_version,
            "rules": req.get('rules'),
        }
        res = self._resp(r, "ok", {"status": "installed", "policy_id": r.policy_id, "rule_handles": [], "verified_readback": True, "digest_verified": True})
        self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
        return res

    def inspect_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        r = _validate_request(req)
        self._validate_canonical_identifiers(req)
        if r.policy_id not in self.installed:
            return self._resp(r, "ok", {"status": "missing"})
        return self._resp(r, "ok", {"status": "installed", "rules": self.installed[r.policy_id], "ownership_match": True, "digest_match": True})

    def verify_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        r = _validate_request(req)
        self._validate_canonical_identifiers(req)
        key = (r.idempotency_key, r.policy_id, r.policy_version)
        if key in self._idempotency:
            existing = self._idempotency[key]
            if existing.get('digest') != r.compiled_rule_digest:
                raise FirewallControllerIdempotencyError("Idempotency key conflict for different payload")
            return existing['response']
        if self.fail_verify:
            res = self._resp(r, "error", {}, error_code="VERIFY_FAILED", error_message="Verification failed")
            self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
            return res
        if r.policy_id not in self.installed:
            res = self._resp(r, "error", {}, error_code="NOT_INSTALLED", error_message="Policy not installed")
            self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
            return res
        if self.readback_mismatch:
            res = self._resp(r, "error", {}, error_code="READBACK_MISMATCH", error_message="Readback mismatch")
            self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
            return res
        self.verified.add(r.policy_id)
        evidence = {"policy_id": r.policy_id, "policy_version": r.policy_version, "compiled_rule_digest": r.compiled_rule_digest, "operation_id": r.operation_id, "controller_id": self.controller_id, "verified_at": time.time(), "families": r.required_families}
        res = self._resp(r, "ok", {"status": "verified", "verified": True, "readback_match": True, "digest_match": True, "evidence": evidence})
        self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
        return res

    def revoke_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        r = _validate_request(req)
        self._validate_canonical_identifiers(req)
        key = (r.idempotency_key, r.policy_id, r.policy_version)
        if key in self._idempotency:
            existing = self._idempotency[key]
            if existing.get('digest') != r.compiled_rule_digest:
                raise FirewallControllerIdempotencyError("Idempotency key conflict for different payload")
            return existing['response']
        if self.fail_revoke:
            res = self._resp(r, "error", {"partial": []}, error_code="REVOKE_FAILED", error_message="Revocation failed")
            self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
            return res
        if r.policy_id in self.revoked:
            res = self._resp(r, "ok", {"status": "revoked", "revoked": True})
            self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
            return res
        self.revoked.add(r.policy_id)
        self.installed.pop(r.policy_id, None)
        self.verified.discard(r.policy_id)
        res = self._resp(r, "ok", {"status": "revoked", "revoked": True})
        self._idempotency[key] = {'digest': r.compiled_rule_digest, 'response': res}
        return res

    def remove_stale_policy(self, req: Dict[str, Any]) -> Dict[str, Any]:
        r = _validate_request(req)
        self._validate_canonical_identifiers(req)
        if r.policy_id in self.installed and r.policy_id not in self.verified and r.policy_id not in self.revoked:
            self.installed.pop(r.policy_id, None)
            return self._resp(r, "ok", {"status": "removed_stale", "removed": [r.policy_id]})
        return self._resp(r, "ok", {"status": "no_action", "removed": []})

    def reconcile_pending_operations(self, req: Dict[str, Any]) -> Dict[str, Any]:
        r = _validate_request(req)
        self._validate_canonical_identifiers(req)
        return self._resp(r, "ok", {"reconciled": [], "pending": [], "unknown": []})


mock_firewall_controller = MockFirewallController()
