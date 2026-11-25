from .config import ControllerConfig
from .authorization import MockAuthorizationProvider
from .authorization_strict import StrictAuthorizationProvider
from .request_validator import RequestValidator
from .mock_backend import MockFirewallBackend
from .ownership import ControllerOwnershipAbstraction
from .audit import MockAuditSink
from .errors import (
    FirewallControllerAuthError,
    FirewallControllerBackendError,
    FirewallControllerIdempotencyError,
    FirewallControllerPersistenceError,
)
from broker.app.firewall_controller_contract import FirewallControllerRequestError
from .ownership_store import (
    BrokerDBCanonicalBodyConflict,
    BrokerDBCanonicalError,
    BrokerDBIdempotencyConflict,
    ControllerOwnershipStore,
)
from broker.app.db import BrokerDBError
from .error_sanitization import (
    INVALID_CANONICAL_POLICY_MESSAGE,
    INVALID_REQUEST_MESSAGE,
    PERSISTENCE_FAILURE_MESSAGE,
    is_persistence_exception,
    sanitize_backend_message,
)
from .rule_schema_v1 import RuleSchemaError, validate_install_policy_rules


def _resource_key_matches_policy(resource_key, policy_id) -> bool:
    """Exact policy-identity match for idempotency resource keys.

    Resource keys use ``<policy_id>:<policy_version>``. Comparing with a raw
    prefix lets ``p1`` match ``p10:1``; the policy identity is therefore compared
    as a whole segment instead.
    """
    key = str(resource_key or "")
    pid = str(policy_id or "")
    if not key or not pid:
        return False
    head, separator, _tail = key.partition(":")
    return head == pid if separator else key == pid


import hashlib
import json
import math
import re
import time
import uuid


class FirewallControllerService:
    """Unprivileged controller service (mock-only helper integration).

    Ownership is always resolved from controller persistence. Caller-supplied ownership
    metadata is only compared against the authoritative record; it is never used as the
    source of truth. Every non-health helper operation receives ownership fields derived
    from that record.
    """

    _DIGEST_RE = re.compile(r"\A[a-fA-F0-9]{64}\Z")
    # Canonical identifier format shared with helper_contract._ID_RE. The helper
    # re-validates at its boundary; this copy keeps controller pre-persistence
    # validation exact without changing the helper module's public contract.
    _ID_RE = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")
    _ALLOWED_FAMILIES = {"ipv4", "ipv6"}
    _IDEMPOTENCY_DIGEST_CORRUPT_MESSAGE = (
        "Corrupt idempotency record: stored request digest is missing or invalid"
    )

    # Explicit lifecycle state machine. A successful revoke may only move
    # REVOKING -> REVOKED; a retry while already REVOKING must not transition again.
    LIFECYCLE_TRANSITIONS = {
        'REQUESTED': {'VALIDATING', 'INSTALLING', 'FAILED'},
        'VALIDATING': {'INSTALLING', 'FAILED'},
        'INSTALLING': {'VERIFYING', 'VALIDATING', 'CLEANUP_PENDING', 'FAILED'},
        'VERIFYING': {'VERIFIED', 'CLEANUP_PENDING', 'FAILED'},
        'VERIFIED': {'ACTIVE', 'REVOKING', 'FAILED'},
        'ACTIVE': {'REVOKING'},
        'REVOKING': {'REVOKED', 'CLEANUP_PENDING'},
        'CLEANUP_PENDING': {'REVOKING', 'REVOKED', 'ORPHANED', 'FAILED'},
        'FAILED': {'CLEANUP_PENDING', 'ORPHANED'},
        'REVOKED': set(),
        'ORPHANED': {'CLEANUP_PENDING'},
    }

    def __init__(self, config: ControllerConfig = None, auth=None, validator=None, backend=None, ownership=None, audit=None, ownership_store=None, strict_auth: bool = True, allowed_uids=None, allowed_gids=None, allowed_operations=None):
        self.config = config or ControllerConfig()
        # Explicit auth injection is honored for controlled testability. Implicit/implicit-default
        # construction must not silently select a non-strict identity model (I-09).
        if auth is not None:
            self.auth = auth
        elif strict_auth:
            self.auth = StrictAuthorizationProvider(
                allowed_uids if allowed_uids is not None else set(),
                allowed_gids if allowed_gids is not None else set(),
                allowed_operations=allowed_operations,
            )
        else:
            raise FirewallControllerAuthError(
                "Non-strict authorization requires an explicit test-only authorization provider"
            )
        self.validator = validator or RequestValidator()
        self.backend = backend or MockFirewallBackend()
        self.ownership = ownership or ControllerOwnershipAbstraction()
        self.audit = audit or MockAuditSink()
        self.ownership_store = ownership_store or ControllerOwnershipStore()
        self._idempotency = {}
        self.controller_identity = self.config.controller_id

    # ------------------------------------------------------------------
    # Ownership binding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_record(rec):
        if rec is not None and not isinstance(rec, dict) and hasattr(rec, 'keys'):
            return dict(rec)
        return rec

    @classmethod
    def _record_family(cls, rec):
        """Authoritative address family with the established ipv4 default."""
        rec = cls._normalize_record(rec)
        return str((rec or {}).get('address_family') or 'ipv4').lower()

    @classmethod
    def _ownership_identity(cls, rec):
        rec = cls._normalize_record(rec)
        if not rec:
            return None
        return (
            rec.get('ownership_record_id'),
            str(rec.get('policy_id')),
            str(rec.get('policy_version')),
            str(rec.get('instance_id') or ''),
            str(rec.get('network_id') or ''),
            rec.get('canonical_policy_digest'),
            cls._record_family(rec),
        )

    @classmethod
    def _canonicalize(cls, value, depth=0):
        """Canonical, type-preserving JSON value for security-relevant digesting.

        Ambiguous or unsupported representations are rejected instead of being
        silently coerced (e.g. non-string dict keys, NaN/Infinity, tuples/sets,
        bytes, objects).
        """
        if depth > 64:
            raise ValueError('payload nesting too deep')
        if value is None or isinstance(value, (bool, str, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError('non-finite numeric value')
            return value
        if isinstance(value, list):
            return [cls._canonicalize(v, depth + 1) for v in value]
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if not isinstance(k, str):
                    raise ValueError('non-string object key')
                if k in out:
                    raise ValueError('duplicate object key')
                out[k] = cls._canonicalize(v, depth + 1)
            return out
        raise ValueError('unsupported payload value type')

    # Security-relevant fields bound into the idempotency request digest.
    _DIGEST_FIELDS = (
        'policy_id', 'policy_version', 'compiled_rule_digest', 'canonical_policy_digest',
        'compiled', 'rules', 'instance_id', 'network_id', 'address_family', 'required_families',
        'ownership_reference', 'ownership_record_id', 'expected_ownership_identity',
        'ip_cidr', 'source_cidr', 'destination_cidr', 'protocol', 'port', 'ports',
        'peer_uid', 'peer_gid',
    )

    def _req_digest(self, req: dict, operation: str = None):
        """Canonical digest of the security-relevant request payload and identity.

        The digest covers the complete compiled body, operation, ownership identity,
        address family, and authenticated requester identity. It is computed with
        deterministic canonical serialization; unsupported/ambiguous values fail
        closed rather than being stringified. Hashing guarantees payload identity
        only; it does not by itself prove that a compiled policy is safe.
        """
        payload = {'operation': operation}
        for field in self._DIGEST_FIELDS:
            payload[field] = (req or {}).get(field)
        try:
            canonical = self._canonicalize(payload)
            raw = json.dumps(
                canonical, sort_keys=True, separators=(',', ':'),
                ensure_ascii=True, allow_nan=False,
            )
        except Exception:
            raise FirewallControllerRequestError('Idempotency payload is unsupported or noncanonical')
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def _check_lifecycle_transition(self, current_state: str, next_state: str):
        allowed = self.LIFECYCLE_TRANSITIONS
        if current_state in allowed and next_state in allowed[current_state]:
            return True
        raise PermissionError(f'Invalid lifecycle transition {current_state} -> {next_state}')

    def _requested_family(self, req: dict) -> str:
        fam = req.get('address_family')
        if fam is not None:
            if not isinstance(fam, str) or fam.lower() not in self._ALLOWED_FAMILIES:
                raise PermissionError('Invalid address_family')
            return fam.lower()
        families = req.get('required_families')
        if families is not None:
            if not isinstance(families, list) or not families:
                raise PermissionError('Invalid required_families')
            first = families[0]
            if not isinstance(first, str) or first.lower() not in self._ALLOWED_FAMILIES:
                raise PermissionError('Invalid required_families')
            return first.lower()
        return 'ipv4'

    @classmethod
    def _validate_identifier(cls, field: str, value):
        """Reject non-string, empty, overlong, or malformed canonical identifiers."""
        if not isinstance(value, str) or not cls._ID_RE.fullmatch(value):
            raise PermissionError(f'Invalid {field}')

    @classmethod
    def _validate_optional_identifier(cls, field: str, req: dict):
        """Validate an optional identifier when explicitly supplied.

        The live contract treats omitted/``None`` instance/network identifiers as
        optional. Explicit values (including an empty string) must still be canonical.
        """
        if field not in req:
            return
        value = req.get(field)
        if value is None:
            return
        cls._validate_identifier(field, value)

    @classmethod
    def _validate_caller_identifiers(cls, req: dict, require_policy: bool = True):
        """Reject malformed caller identifiers before store lookups or persistence.

        ``require_policy=False`` is used only for reconciliation's documented
        full-scan mode: identifiers that are actually supplied are still
        validated, but an omitted policy ID does not by itself require a
        policy-specific lookup.
        """
        # Canonical request correlation/idempotency identifiers must be well-formed
        # at the service boundary (fail closed), consistent with helper contract.
        for field in ('request_id', 'operation_id', 'idempotency_key'):
            cls._validate_identifier(field, req.get(field))
        if require_policy or req.get('policy_id') is not None:
            cls._validate_identifier('policy_id', req.get('policy_id'))
        cls._validate_optional_identifier('instance_id', req)
        cls._validate_optional_identifier('network_id', req)

    @classmethod
    def _validate_authoritative_optional_identifier(cls, field: str, rec: dict):
        value = rec.get(field)
        if value in (None, ''):
            return
        if not isinstance(value, str) or not cls._ID_RE.fullmatch(value):
            raise PermissionError(f'Corrupt authoritative ownership {field}')

    @staticmethod
    def _safe_backend_error_code(res: dict) -> str:
        raw = (res or {}).get('error_code')
        if isinstance(raw, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", raw):
            return raw
        return "BACKEND_ERROR"

    @classmethod
    def _sanitize_outbound_response(cls, res):
        """Bound outward error messages without changing status/result/error codes."""
        if not isinstance(res, dict):
            return res
        if res.get('status') != 'error':
            return res
        out = dict(res)
        code = out.get('error_code') if isinstance(out.get('error_code'), str) else None
        if code == 'REQUEST_INVALID':
            out['error_message'] = INVALID_REQUEST_MESSAGE
        elif code == 'PERSISTENCE_FAILURE':
            out['error_message'] = PERSISTENCE_FAILURE_MESSAGE
        elif code in ('UNAUTHORIZED', 'FORBIDDEN'):
            out['error_message'] = 'Unauthorized'
        elif code == 'IDEMPOTENCY_CONFLICT':
            # preserve bounded conflict message if already safe; avoid leaking raw backend text
            msg = out.get('error_message')
            if not isinstance(msg, str) or msg not in ('Idempotency key conflict', 'Idempotency key conflict for different payload'):
                out['error_message'] = 'Idempotency conflict'
        else:
            # backend/other outward errors must not leak raw backend/internal messages
            if 'error_message' in out:
                out['error_message'] = sanitize_backend_message(out.get('error_message'))
        return out

    def _raise_install_failure_persistence_error(
        self, req: dict, res: dict, *, state_persisted: bool,
        history_persisted: bool, reason: str,
    ):
        """Fail closed when a failed install cannot be durably recorded.

        The backend failure context is reduced to a bounded error code. Raw
        persistence exceptions and backend error messages are never exposed.
        """
        details = {
            'operation': 'install_policy',
            'backend_error_code': self._safe_backend_error_code(res),
            'failure_state_persisted': bool(state_persisted),
            'lifecycle_history_persisted': bool(history_persisted),
            'reason': reason,
        }
        try:
            self.audit.log("install_failure_persistence_failed", req, details)
        except Exception:
            # Audit must not be a prerequisite for denying/failing closed.
            pass
        raise FirewallControllerPersistenceError(
            "Install failure could not be fully persisted",
            details=details,
        ) from None

    def _validated_stored_idempotency_digest(self, idem: dict, operation: str, req: dict) -> str:
        """Return a valid stored request digest or raise a sanitized integrity error."""
        stored_digest = idem.get('request_digest')
        if not isinstance(stored_digest, str) or not self._DIGEST_RE.fullmatch(stored_digest):
            try:
                self.audit.log(
                    "idempotency_digest_corrupt",
                    req,
                    {
                        'operation': operation,
                        'idempotency_key': idem.get('idempotency_key'),
                        'reason': 'stored_request_digest_invalid',
                        'stored_digest_present': stored_digest is not None,
                        'stored_digest_type': type(stored_digest).__name__,
                    },
                )
            except Exception:
                # Denial must not depend on audit availability.
                pass
            raise FirewallControllerIdempotencyError(
                self._IDEMPOTENCY_DIGEST_CORRUPT_MESSAGE,
                details={'reason': 'stored_request_digest_invalid'},
            )
        return stored_digest

    def _assert_ownership_identity_unchanged(self, initial, current):
        if initial is not None and self._ownership_identity(initial) != self._ownership_identity(current):
            raise PermissionError('Authoritative ownership changed during operation')

    def _validate_ownership_binding(self, operation: str, req: dict, rec):
        """Validate caller metadata against authoritative ownership.

        Returns the normalized authoritative record (or None for a first install).
        Never trusts caller-supplied ownership identifiers as the source of truth.
        """
        if operation == 'health_check':
            return rec

        if rec is None:
            if operation != 'install_policy':
                raise PermissionError('Authoritative ownership required')
            # Validate identifiers before any ownership/idempotency persistence.
            self._validate_identifier('policy_id', req.get('policy_id'))
            pv = req.get('policy_version')
            if not isinstance(pv, int) or isinstance(pv, bool) or pv < 0:
                raise PermissionError('Invalid policy version')
            self._validate_optional_identifier('instance_id', req)
            self._validate_optional_identifier('network_id', req)
            digest = req.get('compiled_rule_digest')
            if not isinstance(digest, str) or not self._DIGEST_RE.fullmatch(digest):
                raise PermissionError('Invalid policy digest')
            self._requested_family(req)
            return None

        rec = self._normalize_record(rec)
        oid = rec.get('ownership_record_id')
        if not isinstance(oid, str) or not oid:
            raise PermissionError('Corrupt authoritative ownership record')

        # A caller-supplied ownership identifier must match the persisted record.
        for supplied in (req.get('ownership_reference'), req.get('ownership_record_id')):
            if supplied not in (None, '') and str(supplied) != oid:
                raise PermissionError('Ownership reference mismatch')

        self._validate_identifier('policy_id', req.get('policy_id'))
        self._validate_identifier('authoritative policy_id', rec.get('policy_id'))
        if req.get('policy_id') != rec.get('policy_id'):
            raise PermissionError('Ownership policy mismatch')
        pv = req.get('policy_version')
        if not isinstance(pv, int) or isinstance(pv, bool) or pv < 0:
            raise PermissionError('Invalid policy version')
        supplied_version = pv
        rec_pv = rec.get('policy_version')
        if not isinstance(rec_pv, int) or isinstance(rec_pv, bool):
            raise PermissionError('Corrupt authoritative ownership policy version')
        if supplied_version != rec_pv:
            raise PermissionError('Ownership policy version mismatch')

        for field in ('instance_id', 'network_id'):
            self._validate_optional_identifier(field, req)
            self._validate_authoritative_optional_identifier(field, rec)
            supplied = req.get(field)
            if supplied is not None:
                if supplied != (rec.get(field) or ''):
                    raise PermissionError(f'{field} does not match authoritative ownership')

        supplied_digest = req.get('compiled_rule_digest') or req.get('canonical_policy_digest')
        expected_digest = rec.get('canonical_policy_digest')
        if not isinstance(supplied_digest, str) or not self._DIGEST_RE.fullmatch(supplied_digest):
            raise PermissionError('Invalid policy digest')
        if not isinstance(expected_digest, str) or not self._DIGEST_RE.fullmatch(expected_digest):
            raise PermissionError('Corrupt authoritative ownership digest')
        if supplied_digest != expected_digest:
            raise PermissionError('Policy digest does not match authoritative ownership')

        raw_family = rec.get('address_family')
        if raw_family not in (None, ''):
            if not isinstance(raw_family, str) or raw_family.lower() not in self._ALLOWED_FAMILIES:
                raise PermissionError('Corrupt authoritative ownership address family')
        expected_family = self._record_family(rec)
        supplied_family = req.get('address_family')
        if supplied_family not in (None, ''):
            if not isinstance(supplied_family, str) or supplied_family.lower() != expected_family:
                raise PermissionError('Address family does not match authoritative ownership')
        families = req.get('required_families')
        if families is not None:
            if not isinstance(families, list) or not families:
                raise PermissionError('Invalid required_families')
            if not isinstance(families[0], str) or families[0].lower() != expected_family:
                raise PermissionError('Required family does not match authoritative ownership')
        return rec

    def _authoritative_request(self, req: dict, rec) -> dict:
        """Build a helper request whose ownership fields come only from persistence."""
        r = dict(req)
        if rec is None:
            return r
        rec = self._normalize_record(rec)
        oid = rec.get('ownership_record_id')
        digest = rec.get('canonical_policy_digest')
        family = self._record_family(rec)
        r['ownership_reference'] = oid
        r['ownership_record_id'] = oid
        r['policy_id'] = rec.get('policy_id')
        r['policy_version'] = rec.get('policy_version')
        r['compiled_rule_digest'] = digest
        # R16-04: do not synthesize a canonical policy digest from the compiled
        # rules digest at the helper boundary. Only a caller-supplied complete
        # canonical digest is forwarded for strict validation; the legacy internal
        # ownership alias is never presented as a canonical policy digest here.
        if isinstance(req.get('canonical_policy_digest'), str):
            r['canonical_policy_digest'] = req['canonical_policy_digest']
        else:
            r.pop('canonical_policy_digest', None)
        r['instance_id'] = rec.get('instance_id') or ''
        r['network_id'] = rec.get('network_id') or ''
        r['address_family'] = family
        r['required_families'] = [family]
        return r

    def _ensure_canonical_policy_body_persisted(self, req: dict, ownership_rec: dict):
        """Persist trusted canonical schema-v1 policy body for install requests when present.

        Additive mock-only durability: fails closed on mismatch/corruption/persistence errors.
        No-op for legacy requests without schema-v1 rules.
        """
        if not isinstance(req, dict) or req.get('rules') is None:
            return None
        if not ownership_rec:
            raise PermissionError('Ownership required for canonical policy body persistence')
        rec = {
            'policy_id': ownership_rec.get('policy_id') or req.get('policy_id'),
            'policy_version': ownership_rec.get('policy_version') or req.get('policy_version'),
            'ownership_record_id': ownership_rec.get('ownership_record_id'),
            'schema_version': 'rule-schema-v1',
            'rules': req.get('rules'),
            'required_families': req.get('required_families'),
            'compiled_rule_digest': req.get('compiled_rule_digest'),
            'canonical_policy_digest': ownership_rec.get('canonical_policy_digest') or req.get('canonical_policy_digest') or req.get('compiled_rule_digest'),
            'controller_identity': self.controller_identity,
            'request_id': req.get('request_id'),
            'operation_id': req.get('operation_id'),
            'instance_id': ownership_rec.get('instance_id'),
        }
        return self.ownership_store.ensure_canonical_policy_body(rec)

    def _sanitize_canonical_policy_error(self, exc: Exception, operation: str = None):
        """Map store/DB canonical-policy errors to bounded fail-closed service errors.

        Preserves ownership-indistinguishable denial semantics where applicable and avoids
        leaking raw DB/internal details.
        """
        if isinstance(exc, PermissionError):
            raise exc
        # Stage 1B.6: canonical ownership/integrity categories are carried by a
        # structured exception. This replaces message-substring classification so
        # changes in driver text cannot silently change the public security response.
        if isinstance(exc, BrokerDBCanonicalError):
            if exc.category == BrokerDBCanonicalError.OWNERSHIP:
                # Do not disclose foreign policy existence or ownership details.
                raise PermissionError('Authoritative ownership required') from None
            if exc.category == BrokerDBCanonicalError.INTEGRITY:
                raise FirewallControllerRequestError('Invalid canonical policy record') from None
            raise FirewallControllerPersistenceError('Canonical policy persistence failure') from None
        # Stage 1B.14: persistence-category faults can arrive without the outer DB
        # wrapper (for example a service-level persistence error raised by a nested
        # trusted read). Unknown internal faults are backend failures, never caller
        # validation failures. Both remain bounded and fail closed.
        if is_persistence_exception(exc):
            raise FirewallControllerPersistenceError('Canonical policy persistence failure') from None
        raise FirewallControllerBackendError("Backend operation failed") from None

    def _read_trusted_canonical_policy_body(self, req: dict, ownership_rec: dict, *, operation: str = None, required: bool = False):
        """Service-level trusted canonical read-back path.

        Returns (ownership, body_info) when a canonical body exists and validates.
        Returns None when no canonical body exists and required is False (legacy/no-rules path).
        Fails closed with bounded errors when body is present but invalid, or when required and missing.
        """
        ownership_rec = self._normalize_record(ownership_rec)
        if not ownership_rec:
            raise PermissionError('Authoritative ownership required')
        pid = ownership_rec.get('policy_id')
        pver = ownership_rec.get('policy_version')
        try:
            body = self.ownership_store.get_canonical_policy_body(pid, pver)
        except Exception as e:
            # Stage 1B.14: a failed read is never absence. Unknown read faults are
            # bounded/backend failures; persistence-category faults stay persistence.
            self._sanitize_canonical_policy_error(e, operation)
        if body is None:
            if required:
                raise PermissionError('Authoritative ownership required')
            return None
        try:
            return self.ownership_store.read_trusted_canonical_policy_body(
                pid,
                pver,
                expected_owner_id=str(ownership_rec.get('instance_id') or ''),
                expected_ownership_record_id=str(ownership_rec.get('ownership_record_id') or ''),
                expected_digest=str(req.get('compiled_rule_digest') or req.get('canonical_policy_digest') or ''),
                expected_compiled_rule_digest=str(req.get('compiled_rule_digest') or ''),
                require_schema_v1=True,
            )
        except Exception as e:
            try:
                self.audit.log('canonical_policy_readback_failed', req or {}, {
                    'operation': operation,
                    'policy_id': pid,
                    'policy_version': pver,
                }, ownership_rec.get('ownership_record_id'))
            except Exception:
                pass
            self._sanitize_canonical_policy_error(e, operation)

    def _validate_replay(self, operation: str, req: dict, idem_record=None):
        """Validate that a cached response is still bound to current authority.

        Replay is rejected unless the authenticated request digest, current
        authoritative ownership, stored ownership record ID, and (when recorded)
        the full ownership identity snapshot all match.
        """
        if operation == 'health_check':
            return
        fresh = self._normalize_record(self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version')))
        if not fresh:
            raise PermissionError('Authoritative ownership required for idempotent replay')
        self._validate_ownership_binding(operation, req, fresh)

        if idem_record is None:
            return
        idem_record = self._normalize_record(idem_record)

        stored_oid = idem_record.get('ownership_record_id')
        fresh_oid = fresh.get('ownership_record_id')
        if not stored_oid or str(stored_oid) != str(fresh_oid):
            raise PermissionError('Idempotency replay ownership record binding mismatch')

        stored_resource = idem_record.get('resource_key')
        if stored_resource and str(stored_resource) != f"{fresh.get('policy_id')}:{fresh.get('policy_version')}":
            raise PermissionError('Idempotency replay resource binding mismatch')

        raw_meta = idem_record.get('recovery_meta_json')
        if raw_meta:
            try:
                meta = json.loads(raw_meta)
            except Exception:
                raise PermissionError('Corrupt idempotency replay metadata')
            stored_identity = meta.get('ownership_identity') if isinstance(meta, dict) else None
            if stored_identity is not None:
                try:
                    stored_identity = tuple(stored_identity)
                except Exception:
                    raise PermissionError('Corrupt idempotency replay identity')
                if stored_identity != self._ownership_identity(fresh):
                    raise PermissionError('Idempotency replay ownership identity changed')

    def _store_verification_evidence(self, req: dict, rec: dict, res: dict) -> str:
        evidence_id = str(uuid.uuid4())
        self.ownership_store.store_evidence({
            'evidence_id': evidence_id,
            'ownership_record_id': rec.get('ownership_record_id'),
            'policy_id': rec.get('policy_id'),
            'policy_version': rec.get('policy_version'),
            'instance_id': rec.get('instance_id') or '',
            'network_id': rec.get('network_id') or '',
            'canonical_policy_digest': rec.get('canonical_policy_digest'),
            'address_family': rec.get('address_family') or 'ipv4',
            'installed_rule_ids': res.get('result', {}).get('rule_handles') or res.get('result', {}).get('evidence', {}).get('rule_ids') or [],
            'controller_identity': self.controller_identity,
            'controller_transaction_id': req.get('operation_id'),
            'request_id': req.get('request_id'),
            'verification_result': 'verified',
        })
        return evidence_id

    def _store_revocation_evidence(self, req: dict, rec: dict) -> str:
        evidence_id = str(uuid.uuid4())
        self.ownership_store.store_evidence({
            'evidence_id': evidence_id,
            'ownership_record_id': rec.get('ownership_record_id'),
            'policy_id': rec.get('policy_id'),
            'policy_version': rec.get('policy_version'),
            'instance_id': rec.get('instance_id') or '',
            'network_id': rec.get('network_id') or '',
            'canonical_policy_digest': rec.get('canonical_policy_digest'),
            'address_family': rec.get('address_family') or 'ipv4',
            'installed_rule_ids': [],
            'controller_identity': self.controller_identity,
            'controller_transaction_id': req.get('operation_id'),
            'request_id': req.get('request_id'),
            'verification_result': 'revoked',
        })
        return evidence_id

    def _has_revocation_evidence(self, rec: dict) -> bool:
        rec = self._normalize_record(rec)
        rows = self.ownership_store.get_evidence_by_policy(rec.get('policy_id'), rec.get('policy_version'))
        family = self._record_family(rec)
        for ev in rows:
            if (ev.get('verification_result') == 'revoked'
                    and ev.get('ownership_record_id') == rec.get('ownership_record_id')
                    and ev.get('canonical_policy_digest') == rec.get('canonical_policy_digest')
                    and str(ev.get('policy_id')) == str(rec.get('policy_id'))
                    and str(ev.get('policy_version')) == str(rec.get('policy_version'))
                    and str(ev.get('instance_id') or '') == str(rec.get('instance_id') or '')
                    and str(ev.get('network_id') or '') == str(rec.get('network_id') or '')
                    and str(ev.get('address_family') or 'ipv4').lower() == family):
                return True
        return False

    def _find_valid_verification_evidence(self, rec: dict, oid: str = None, family: str = None):
        """Return authoritative verification evidence bound to this ownership record.

        The binding rules are identical to the existing VERIFIED reconciliation path:
        result, ownership record id, canonical digest, policy identity and address
        family must all match. Storage failures propagate as BrokerDBError so they
        remain distinguishable from an uncertain backend outcome.
        """
        rec = self._normalize_record(rec)
        pid = rec.get('policy_id')
        pver = rec.get('policy_version')
        oid = oid or rec.get('ownership_record_id')
        family = family or self._record_family(rec)
        rows = self.ownership_store.get_evidence_by_policy(pid, pver)
        for ev in rows:
            if (ev.get('verification_result') == 'verified'
                    and ev.get('ownership_record_id') == oid
                    and ev.get('canonical_policy_digest') == rec.get('canonical_policy_digest')
                    and str(ev.get('policy_id')) == str(pid)
                    and str(ev.get('policy_version')) == str(pver)
                    and str(ev.get('instance_id') or '') == str(rec.get('instance_id') or '')
                    and str(ev.get('network_id') or '') == str(rec.get('network_id') or '')
                    and str(ev.get('address_family') or 'ipv4').lower() == family):
                return ev
        return None

    def _read_back_revoke(self, req: dict, rec: dict):
        readback_req = self._authoritative_request(req, rec)
        readback_req['request_id'] = str(uuid.uuid4())
        readback_req['operation_id'] = str(uuid.uuid4())
        readback_req['idempotency_key'] = str(uuid.uuid4())
        try:
            insp = self.backend.inspect_policy(readback_req)
        except Exception as e:
            return False, None, f'readback_error:{type(e).__name__}'
        if not isinstance(insp, dict):
            return False, None, 'invalid_readback_response'
        if insp.get('status') != 'ok':
            code = insp.get('error_code') if isinstance(insp.get('error_code'), str) else None
            return False, None, (code if code and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", code) else 'readback_not_ok')
        result = insp.get('result')
        state = result.get('status') if isinstance(result, dict) else result
        if state in ('missing', 'revoked'):
            return True, state, None
        if state is None:
            return False, None, 'unknown_backend_state'
        if str(state).lower() in ('installed', 'present', 'active', 'ok'):
            return False, state, 'backend_still_present'
        return False, state, 'unknown_backend_state'

    def _revoked_response(self, req: dict, rec: dict) -> dict:
        return {
            'status': 'ok',
            'request_id': req.get('request_id'),
            'operation_id': req.get('operation_id'),
            'controller_id': self.controller_identity,
            'controller_version': self.config.controller_version,
            'timestamp': time.time(),
            'result': {
                'status': 'revoked',
                'revoked': True,
                'already_revoked': True,
                'ownership_record_id': rec.get('ownership_record_id') if rec else None,
            },
        }

    def _revoke_unconfirmed_response(self, res: dict, req: dict, reason: str) -> dict:
        out = dict(res or {})
        out.setdefault('request_id', req.get('request_id'))
        out.setdefault('operation_id', req.get('operation_id'))
        out['status'] = 'error'
        out['error_code'] = 'REVOKE_UNCONFIRMED'
        out['error_message'] = 'Backend revocation could not be confirmed'
        result = out.get('result') if isinstance(out.get('result'), dict) else {}
        result = dict(result)
        result['revocation_confirmed'] = False
        result['readback_reason'] = reason
        out['result'] = result
        return out

    def _complete_revoke(self, req: dict, rec: dict, res: dict) -> dict:
        """Confirm backend state, persist evidence, then promote REVOKING -> REVOKED."""
        confirmed, backend_state, reason = self._read_back_revoke(req, rec)
        if not confirmed:
            return self._revoke_unconfirmed_response(res, req, reason or 'revocation_not_confirmed')

        latest = self._normalize_record(self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version')))
        if not latest:
            raise PermissionError('Authoritative ownership required for revocation completion')
        latest = self._validate_ownership_binding('revoke_policy', req, latest)
        if self._ownership_identity(latest) != self._ownership_identity(rec):
            raise PermissionError('Authoritative ownership changed during revocation')

        if latest.get('installation_state') == 'REVOKED':
            # A terminal record is only accepted as proof when authoritative
            # revocation evidence for the same ownership identity is present.
            if not self._has_revocation_evidence(latest):
                raise PermissionError('Revocation evidence missing for terminal REVOKED ownership')
            return res
        if latest.get('installation_state') != 'REVOKING':
            raise PermissionError('Unexpected lifecycle state during revocation completion')

        if not self._has_revocation_evidence(latest):
            self._store_revocation_evidence(req, latest)

        try:
            self._check_lifecycle_transition('REVOKING', 'REVOKED')
            with self.ownership_store.atomic_write():
                self.ownership_store.update_ownership_state(
                    latest.get('ownership_record_id'), 'REVOKED', 'REVOKING',
                    latest.get('lifecycle_version')
                )
                self.ownership_store.record_lifecycle_transition(
                    latest.get('ownership_record_id'), req.get('policy_id'), req.get('policy_version'),
                    'REVOKING', 'REVOKED', req.get('operation_id'), req.get('request_id'),
                    'revoke_completed_with_evidence', 'ok'
                )
        except PermissionError:
            # A concurrent revocation may already have completed. Re-read and accept
            # only an authoritative REVOKED state; otherwise fail closed.
            final = self._normalize_record(self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version')))
            if not final or final.get('installation_state') != 'REVOKED':
                raise
            if not self._has_revocation_evidence(final):
                raise PermissionError('Revocation evidence missing for terminal REVOKED ownership')
        return res

    # ------------------------------------------------------------------
    # Durable operation-outcome ledger (Stage 1B.1, mock-only)
    # ------------------------------------------------------------------

    def _mark_operation_in_progress(self, key: str, operation: str):
        """Mark the operation as executing before the backend side effect.

        A fresh operation transitions INTENT_RECORDED -> IN_PROGRESS. A legitimate
        same-key recovery retry (notably revoke readback/reissue) re-enters
        execution from IN_PROGRESS / UNCERTAIN / FAILED; those are allowed because
        the existing idempotency/recovery path already owns convergence. Only a
        SUCCEEDED record is excluded (it replays and never reaches the backend).

        Fails closed on genuine persistence failure (no backend call) and on a CAS
        no-match (unexpected competing ledger state).
        """
        if not key:
            return
        try:
            updated = self.ownership_store.update_operation_outcome(
                key, operation, 'IN_PROGRESS',
                expected_outcomes=('INTENT_RECORDED', 'IN_PROGRESS', 'FAILED', 'UNCERTAIN'),
            )
        except BrokerDBError:
            raise FirewallControllerPersistenceError(
                'Operation ledger persistence failure',
                details={'operation': operation, 'phase': 'in_progress'},
            ) from None
        except Exception:
            # Unknown store-layer failure: still fail closed as a persistence error.
            raise FirewallControllerPersistenceError(
                'Operation ledger persistence failure',
                details={'operation': operation, 'phase': 'in_progress'},
            ) from None
        if not updated:
            raise FirewallControllerIdempotencyError(
                'Operation ledger state conflict',
                details={'operation': operation, 'phase': 'in_progress'},
            )

    @staticmethod
    def _derive_operation_outcome(operation: str, res: dict) -> str:
        """Map a completed operation response to a terminal outcome (informational).

        The outcome never drives ownership FSM promotion. Unconfirmed revocations are
        explicitly UNCERTAIN; other definite error responses are FAILED.
        """
        status = res.get('status') if isinstance(res, dict) else None
        if operation == 'revoke_policy':
            # A non-ok revoke response is inherently ambiguous: the backend may
            # still have applied the removal before the error/timeout. Likewise an
            # ok response that explicitly denies confirmation is UNCERTAIN.
            if status != 'ok':
                return 'UNCERTAIN'
            result = res.get('result') if isinstance(res, dict) and isinstance(res.get('result'), dict) else {}
            if result.get('revocation_confirmed') is False:
                return 'UNCERTAIN'
            return 'SUCCEEDED'
        if status == 'ok':
            return 'SUCCEEDED'
        return 'FAILED'

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    @staticmethod
    def _response_is_uncertain(res) -> bool:
        """True when a cached revoke outcome requires backend recovery inspection."""
        if not isinstance(res, dict):
            return True
        if res.get('status') != 'ok':
            return True
        result = res.get('result')
        if isinstance(result, dict) and result.get('revocation_confirmed') is False:
            return True
        return False

    def _idempotency_replay_decision(self, operation: str, req: dict, request_digest: str, idem_record):
        """Classify an existing idempotency record.

        Returns (action, response) where action is one of:
          - ``return``: disclose the cached response;
          - ``recover``: do not disclose a cached uncertain revoke error; run the
            read-back recovery path instead (same idempotency key);
          - ``pending``: the record is still pending.
        """
        idem = self._normalize_record(idem_record)
        if not idem:
            return ('none', None)
        stored_digest = self._validated_stored_idempotency_digest(idem, operation, req)
        if stored_digest != request_digest:
            raise FirewallControllerIdempotencyError("Idempotency key conflict for different payload")
        if idem.get('status') == 'COMPLETED' and idem.get('response_json'):
            try:
                cached = json.loads(idem['response_json'])
            except Exception:
                raise FirewallControllerIdempotencyError("Corrupt cached idempotency response")
            if operation == 'revoke_policy' and self._response_is_uncertain(cached):
                # Never let a cached uncertain/error outcome prevent recovery inspection.
                self._validate_replay(operation, req, idem)
                return ('recover', None)
            self._validate_replay(operation, req, idem)
            return ('return', cached)
        return ('pending', None)

    def _call(self, operation: str, req: dict):
        req = dict(req or {})
        self.audit.log("request_received", req, {"operation": operation})

        # Authorization and request validation always precede idempotency replay.
        try:
            self.auth.authorize(req, operation)
        except FirewallControllerAuthError:
            self.audit.log("authorization_failed", req, {"operation": operation})
            raise
        self.audit.log("authorization_passed", req, {"operation": operation})
        try:
            self.validator.validate(req)
        except Exception:
            self.audit.log("validation_failed", req, {"operation": operation})
            raise
        self.audit.log("validation_passed", req, {"operation": operation})

        try:
            # Canonical caller identifiers must be rejected before any ownership
            # lookup or ownership/idempotency persistence. This also prevents
            # unsupported SQL binding values from reaching the store layer.
            # Health checks are included: the legacy contract requires the same
            # policy/version/digest fields, and a supplied idempotency key can
            # otherwise persist malformed identifier data.
            self._validate_caller_identifiers(req)

            # Canonical rule-schema-v1 validation/normalization boundary for rules entering
            # the controller (install path). Invalid/ambiguous/legacy-incompatible rule
            # inputs fail closed before ownership/idempotency side effects.
            if operation == 'install_policy':
                try:
                    rules_info = validate_install_policy_rules(req)
                except RuleSchemaError as e:
                    self.audit.log("rule_schema_validation_failed", req, {"operation": operation, "code": getattr(e, 'code', None)})
                    # Never expose raw schema validation internals in outward errors.
                    raise FirewallControllerRequestError(INVALID_REQUEST_MESSAGE) from e
                if rules_info:
                    req['rules'] = rules_info['rules']
                    req['required_families'] = sorted(rules_info.get('required_families') or [])
                    if 'compiled_rule_digest' not in req or req.get('compiled_rule_digest') in (None, ''):
                        req['compiled_rule_digest'] = rules_info['compiled_rule_digest']
                    elif req.get('compiled_rule_digest') != rules_info['compiled_rule_digest']:
                        raise FirewallControllerRequestError(INVALID_REQUEST_MESSAGE)
                    if rules_info.get('canonical_policy_digest') and not req.get('canonical_policy_digest'):
                        req['canonical_policy_digest'] = rules_info['canonical_policy_digest']

            # Authorization has already succeeded. Reject a same-key/different-payload
            # conflict before ownership resolution; this is not a cached response and
            # preserves the established idempotency-conflict error contract.
            key = req.get('idempotency_key')
            request_digest = self._req_digest(req, operation)
            pre_idem = None
            if key:
                pre_idem = self._normalize_record(
                    self.ownership_store.get_idempotency_record(key, operation)
                )
                if pre_idem:
                    stored_digest = self._validated_stored_idempotency_digest(
                        pre_idem, operation, req
                    )
                    if stored_digest != request_digest:
                        raise FirewallControllerIdempotencyError("Idempotency key conflict for different payload")

            # Resolve and validate authoritative ownership BEFORE any replay/cached response.
            ownership_rec = self._normalize_record(
                self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
            )
            try:
                ownership_rec = self._validate_ownership_binding(operation, req, ownership_rec)
            except PermissionError:
                # A concurrent same-key request may have committed its idempotency
                # record after our initial pre-check but before its ownership row.
                # Re-check to preserve the idempotency-conflict contract without
                # creating side effects or disclosing any cached response.
                if key:
                    late_idem = self._normalize_record(
                        self.ownership_store.get_idempotency_record(key, operation)
                    )
                    if late_idem:
                        late_digest = self._validated_stored_idempotency_digest(
                            late_idem, operation, req
                        )
                        if late_digest != request_digest:
                            raise FirewallControllerIdempotencyError(
                                "Idempotency key conflict for different payload"
                            ) from None
                raise

            # Durable idempotency (authoritative), after auth/validation/ownership checks.
            if key:
                revoke_recovery = False
                if pre_idem:
                    action, cached = self._idempotency_replay_decision(
                        operation, req, request_digest, pre_idem
                    )
                    if action == 'return':
                        return cached
                    if action == 'recover':
                        revoke_recovery = True
                    else:
                        # pending - for concurrent identical requests, wait briefly and retry
                        last_pending = pre_idem
                        _idem_deadline = time.monotonic() + 0.75
                        _idem_attempts = 0
                        while _idem_attempts < 50 and time.monotonic() < _idem_deadline:
                            _idem_attempts += 1
                            time.sleep(0.01)
                            idem_d2 = self._normalize_record(
                                self.ownership_store.get_idempotency_record(key, operation)
                            )
                            if not idem_d2:
                                break
                            last_pending = idem_d2
                            action2, cached2 = self._idempotency_replay_decision(
                                operation, req, request_digest, idem_d2
                            )
                            if action2 == 'return':
                                return cached2
                            if action2 == 'recover':
                                revoke_recovery = True
                                break
                        if not revoke_recovery:
                            if operation == 'revoke_policy':
                                # A leftover PENDING record from a failed attempt is
                                # recoverable: re-read the backend under lifecycle CAS.
                                self._validate_replay(operation, req, last_pending)
                                revoke_recovery = True
                            else:
                                raise FirewallControllerIdempotencyError("Idempotency operation pending")
                else:
                    try:
                        self.ownership_store.create_idempotency_record(
                            key, operation, request_digest,
                            resource_key=f"{req.get('policy_id')}:{req.get('policy_version')}",
                            ownership_record_id=(ownership_rec or {}).get('ownership_record_id'),
                        )
                    except Exception as create_exc:
                        # Check if it was created by a concurrent call. Re-fetch can be
                        # transiently affected by SQLite lock contention under cross-process
                        # races; retry briefly before failing to preserve deterministic
                        # conflict/pending classification.
                        # Stage 1B.14: the store raises a typed conflict only for the
                        # targeted idempotency PRIMARY KEY collision. Generic DB
                        # failures are also re-fetched because SQLite lock contention
                        # can hide a concurrent winner; the typed flag only widens
                        # the transient retry window. Any record found afterwards is
                        # still validated by the authoritative replay decision below,
                        # so no generic failure is itself promoted to a duplicate.
                        unique_collision = isinstance(create_exc, BrokerDBIdempotencyConflict)
                        idem2 = None
                        last_fetch_exc = create_exc
                        _idem_deadline = time.monotonic() + 0.75
                        _idem_attempts = 0
                        while _idem_attempts < 50 and time.monotonic() < _idem_deadline:
                            _idem_attempts += 1
                            try:
                                idem2 = self._normalize_record(
                                    self.ownership_store.get_idempotency_record(key, operation)
                                )
                                last_fetch_exc = None
                            except Exception as fetch_exc:
                                last_fetch_exc = fetch_exc
                                time.sleep(0.01)
                                continue
                            if idem2:
                                break
                            time.sleep(0.01)
                        # A uniqueness collision proves the record exists; continue bounded
                        # classification reads so we never leak a storage/create error in place
                        # of a deterministic conflict/pending classification.
                        if not idem2 and unique_collision:
                            _idem_hard_deadline = time.monotonic() + 1.0
                            while not idem2 and time.monotonic() < _idem_hard_deadline:
                                try:
                                    idem2 = self._normalize_record(
                                        self.ownership_store.get_idempotency_record(key, operation)
                                    )
                                    last_fetch_exc = None
                                except Exception as fetch_exc:
                                    last_fetch_exc = fetch_exc
                                if idem2:
                                    break
                                time.sleep(0.01)
                        if not idem2:
                            if last_fetch_exc is not None:
                                raise last_fetch_exc
                            raise create_exc
                        action2, cached2 = self._idempotency_replay_decision(
                            operation, req, request_digest, idem2
                        )
                        if action2 == 'return':
                            return cached2
                        if action2 == 'recover':
                            revoke_recovery = True
                        else:
                            last_pending = idem2
                            _idem_deadline = time.monotonic() + 0.75
                            _idem_attempts = 0
                            while _idem_attempts < 50 and time.monotonic() < _idem_deadline:
                                _idem_attempts += 1
                                time.sleep(0.01)
                                try:
                                    idem2_d2 = self._normalize_record(
                                        self.ownership_store.get_idempotency_record(key, operation)
                                    )
                                except Exception:
                                    continue
                                if not idem2_d2:
                                    break
                                last_pending = idem2_d2
                                action3, cached3 = self._idempotency_replay_decision(
                                    operation, req, request_digest, idem2_d2
                                )
                                if action3 == 'return':
                                    return cached3
                                if action3 == 'recover':
                                    revoke_recovery = True
                                    break
                            if not revoke_recovery:
                                if operation == 'revoke_policy':
                                    self._validate_replay(operation, req, last_pending)
                                    revoke_recovery = True
                                else:
                                    raise FirewallControllerIdempotencyError("Idempotency operation pending")

            intent_ownership_id = None
            revoke_already_done = False
            revoke_initiated = False
            revoke_preconfirmed = False
            revoke_precheck_uncertain = None
            revoke_reissue = False
            initial_ownership_rec = ownership_rec

            if operation == 'install_policy':
                if ownership_rec:
                    prev = ownership_rec.get('installation_state') or 'REQUESTED'
                    self._check_lifecycle_transition(prev, 'VALIDATING')
                    with self.ownership_store.atomic_write():
                        self.ownership_store.update_ownership_state(
                            ownership_rec.get('ownership_record_id'), 'VALIDATING', prev,
                            ownership_rec.get('lifecycle_version')
                        )
                        self.ownership_store.record_lifecycle_transition(
                            ownership_rec.get('ownership_record_id'), req.get('policy_id'), req.get('policy_version'),
                            prev, 'VALIDATING', req.get('operation_id'), req.get('request_id'),
                            'install_revalidate', 'ok'
                        )
                    ownership_rec = self._normalize_record(
                        self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                    ) or ownership_rec
                    self._assert_ownership_identity_unchanged(initial_ownership_rec, ownership_rec)
                    ownership_rec = self._validate_ownership_binding(operation, req, ownership_rec)
                else:
                    # Persist intent before backend side effects. Caller metadata was validated
                    # above and becomes authoritative only for this first creation.
                    intent_ownership_id = str(uuid.uuid4())
                    try:
                        with self.ownership_store.atomic_write():
                            self.ownership_store.create_ownership({
                                'ownership_record_id': intent_ownership_id,
                                'policy_id': req.get('policy_id'),
                                'policy_version': req.get('policy_version'),
                                'instance_id': req.get('instance_id') or '',
                                'network_id': req.get('network_id') or '',
                                'canonical_policy_digest': req.get('compiled_rule_digest'),
                                'installed_rule_ids': [],
                                'address_family': self._requested_family(req),
                                'installation_state': 'REQUESTED',
                            })
                            self.ownership_store.record_audit(
                                'ownership_intent_persisted', req,
                                {'ownership_record_id': intent_ownership_id}, intent_ownership_id
                            )
                            self.ownership_store.record_lifecycle_transition(
                                intent_ownership_id, req.get('policy_id'), req.get('policy_version'),
                                None, 'REQUESTED', req.get('operation_id'), req.get('request_id'),
                                'install_intent_persisted', 'ok'
                            )
                        ownership_rec = self._normalize_record(
                            self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                        )
                        if not ownership_rec:
                            raise PermissionError('Authoritative ownership required after intent persistence')
                    except PermissionError:
                        # Another concurrent/duplicate request created it; re-read and validate.
                        ownership_rec = self._normalize_record(
                            self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                        )
                        if not ownership_rec:
                            raise
                        ownership_rec = self._validate_ownership_binding(operation, req, ownership_rec)
                        prev = ownership_rec.get('installation_state') or 'REQUESTED'
                        self._check_lifecycle_transition(prev, 'VALIDATING')
                        with self.ownership_store.atomic_write():
                            self.ownership_store.update_ownership_state(
                                ownership_rec.get('ownership_record_id'), 'VALIDATING', prev,
                                ownership_rec.get('lifecycle_version')
                            )
                            self.ownership_store.record_lifecycle_transition(
                                ownership_rec.get('ownership_record_id'), req.get('policy_id'), req.get('policy_version'),
                                prev, 'VALIDATING', req.get('operation_id'), req.get('request_id'),
                                'install_revalidate', 'ok'
                            )
                        ownership_rec = self._normalize_record(
                            self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                        ) or ownership_rec
                        self._assert_ownership_identity_unchanged(initial_ownership_rec, ownership_rec)
                        ownership_rec = self._validate_ownership_binding(operation, req, ownership_rec)
                        intent_ownership_id = None

            if operation == 'revoke_policy':
                if not ownership_rec:
                    raise PermissionError('Ownership required for revocation')
                cur_state = ownership_rec.get('installation_state') or 'ACTIVE'
                if cur_state == 'REVOKED':
                    revoke_already_done = True
                elif cur_state == 'REVOKING':
                    # Retry/recovery path: do not attempt REVOKING -> REVOKING.
                    ownership_rec = self._normalize_record(
                        self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                    ) or ownership_rec
                    self._assert_ownership_identity_unchanged(initial_ownership_rec, ownership_rec)
                    ownership_rec = self._validate_ownership_binding('revoke_policy', req, ownership_rec)
                else:
                    try:
                        self._check_lifecycle_transition(cur_state, 'REVOKING')
                        with self.ownership_store.atomic_write():
                            self.ownership_store.update_ownership_state(
                                ownership_rec.get('ownership_record_id'), 'REVOKING', cur_state,
                                ownership_rec.get('lifecycle_version')
                            )
                            self.ownership_store.record_lifecycle_transition(
                                ownership_rec.get('ownership_record_id'), req.get('policy_id'), req.get('policy_version'),
                                cur_state, 'REVOKING', req.get('operation_id'), req.get('request_id'),
                                'revoke_initiated', 'ok'
                            )
                        revoke_initiated = True
                    except PermissionError:
                        # Concurrent revocation may have moved the record first.
                        latest = self._normalize_record(
                            self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                        )
                        if latest and latest.get('installation_state') in ('REVOKING', 'REVOKED'):
                            ownership_rec = latest
                            revoke_already_done = latest.get('installation_state') == 'REVOKED'
                        else:
                            raise
                    ownership_rec = self._normalize_record(
                        self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                    ) or ownership_rec
                    self._assert_ownership_identity_unchanged(initial_ownership_rec, ownership_rec)
                    ownership_rec = self._validate_ownership_binding('revoke_policy', req, ownership_rec)

            if operation == 'revoke_policy' and not revoke_already_done and not revoke_initiated:
                # Retry/recovery path. Read back first so an already-applied backend
                # revocation is not re-issued; only call the backend when it is still
                # present. Unknown read-back state fails closed without a duplicate
                # side effect.
                confirmed, backend_state, reason = self._read_back_revoke(req, ownership_rec)
                if confirmed:
                    revoke_preconfirmed = True
                elif reason == 'backend_still_present':
                    # Read-back proved the previous attempt did not apply. This is a
                    # deliberate new retry attempt at the backend boundary, so use a
                    # fresh helper idempotency key; the durable controller-level
                    # idempotency key remains unchanged.
                    revoke_reissue = True
                else:
                    revoke_precheck_uncertain = reason or 'revocation_state_unknown'

            if operation in ('inspect_policy', 'remove_stale_policy', 'verify_policy') and not ownership_rec:
                raise PermissionError('Authoritative ownership required')
            if operation in ('inspect_policy', 'remove_stale_policy', 'verify_policy'):
                fresh = self._normalize_record(
                    self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                )
                if not fresh:
                    raise PermissionError('Authoritative ownership required')
                self._assert_ownership_identity_unchanged(initial_ownership_rec, fresh)
                ownership_rec = self._validate_ownership_binding(operation, req, fresh)

            # Durable canonical policy-body persistence for schema-v1 install requests.
            if operation == 'install_policy':
                self._ensure_canonical_policy_body_persisted(req, ownership_rec)

            # Trusted canonical read-back pre-check for operations that must fail closed
            # when a persisted schema-v1 canonical body exists but is invalid/inconsistent.
            canonical_readback = None
            if operation in ('inspect_policy', 'remove_stale_policy', 'verify_policy'):
                canonical_readback = self._read_trusted_canonical_policy_body(
                    req, ownership_rec, operation=operation, required=False
                )

            # Operation ledger: record IN_PROGRESS before any backend side effect.
            # A persistence failure here prevents the backend call (fail closed).
            if key:
                try:
                    self._mark_operation_in_progress(key, operation)
                except FirewallControllerIdempotencyError:
                    # A concurrent same-key worker can complete the operation after
                    # our pre-check and before this CAS. Never surface that raced
                    # conflict or proceed to the backend: replay the authoritative
                    # completed response when one exists, otherwise fail closed.
                    latest = self._normalize_record(
                        self.ownership_store.get_idempotency_record(key, operation)
                    )
                    action, cached = self._idempotency_replay_decision(
                        operation, req, request_digest, latest
                    )
                    if action == 'return':
                        return self._sanitize_outbound_response(cached)
                    raise

            # Dispatch: all non-health helper requests use ownership fields from persistence.
            if operation == 'health_check':
                try:
                    res = self.backend.health_check(req)
                except Exception:
                    raise FirewallControllerBackendError("Backend operation failed") from None
            elif revoke_already_done:
                # A persisted terminal REVOKED state is not by itself proof: require
                # matching authoritative revocation evidence before reporting success.
                if not self._has_revocation_evidence(ownership_rec):
                    raise PermissionError('Revocation evidence missing for terminal REVOKED ownership')
                res = self._revoked_response(req, ownership_rec)
            elif operation == 'revoke_policy' and revoke_preconfirmed:
                res = self._revoked_response(req, ownership_rec)
                res['result']['already_revoked'] = False
                res['result']['readback_confirmed'] = True
            elif operation == 'revoke_policy' and revoke_precheck_uncertain:
                res = self._revoke_unconfirmed_response(
                    {'status': 'error', 'request_id': req.get('request_id'), 'operation_id': req.get('operation_id')},
                    req,
                    revoke_precheck_uncertain,
                )
            else:
                backend_req = self._authoritative_request(req, ownership_rec)
                if operation == 'revoke_policy' and revoke_reissue:
                    backend_req['idempotency_key'] = str(uuid.uuid4())
                method = getattr(self.backend, operation)
                try:
                    res = method(backend_req)
                except Exception:
                    raise FirewallControllerBackendError("Backend operation failed") from None

            if operation == 'install_policy' and res.get('status') == 'ok':
                ownership_rec2 = self._normalize_record(
                    self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                )
                if ownership_rec2:
                    self._assert_ownership_identity_unchanged(ownership_rec, ownership_rec2)
                if ownership_rec2 and intent_ownership_id and ownership_rec2.get('ownership_record_id') == intent_ownership_id:
                    cur = ownership_rec2.get('installation_state') or 'REQUESTED'
                    self._check_lifecycle_transition(cur, 'INSTALLING')
                    with self.ownership_store.atomic_write():
                        self.ownership_store.update_ownership_state(
                            intent_ownership_id, 'INSTALLING', cur,
                            ownership_rec2.get('lifecycle_version')
                        )
                        self.ownership_store.record_lifecycle_transition(
                            intent_ownership_id, req.get('policy_id'), req.get('policy_version'),
                            cur, 'INSTALLING', req.get('operation_id'), req.get('request_id'),
                            'install_backend_ok', 'ok'
                        )
                elif ownership_rec2:
                    cur = ownership_rec2.get('installation_state') or 'VALIDATING'
                    if cur == 'VALIDATING':
                        self._check_lifecycle_transition(cur, 'INSTALLING')
                        with self.ownership_store.atomic_write():
                            self.ownership_store.update_ownership_state(
                                ownership_rec2.get('ownership_record_id'), 'INSTALLING', cur,
                                ownership_rec2.get('lifecycle_version')
                            )
                            self.ownership_store.record_lifecycle_transition(
                                ownership_rec2.get('ownership_record_id'), req.get('policy_id'), req.get('policy_version'),
                                cur, 'INSTALLING', req.get('operation_id'), req.get('request_id'),
                                'install_revalidated_backend_ok', 'ok'
                            )
                else:
                    raise PermissionError('Authoritative ownership required after install')
            elif operation == 'install_policy' and res.get('status') != 'ok':
                try:
                    target = self._normalize_record(
                        self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                    )
                except BrokerDBError:
                    self._raise_install_failure_persistence_error(
                        req, res, state_persisted=False,
                        history_persisted=False,
                        reason='persistence_unavailable',
                    )
                if not target:
                    self._raise_install_failure_persistence_error(
                        req, res, state_persisted=False,
                        history_persisted=False,
                        reason='ownership_missing',
                    )
                self._assert_ownership_identity_unchanged(ownership_rec, target)
                if target.get('installation_state') in ('REQUESTED', 'VALIDATING', 'INSTALLING'):
                    prev = target.get('installation_state')
                    ver = target.get('lifecycle_version') or 0
                    state_persisted = False
                    history_persisted = False
                    try:
                        self._check_lifecycle_transition(prev, 'FAILED')
                        self.ownership_store.update_ownership_state(
                            target.get('ownership_record_id'), 'FAILED', prev, ver
                        )
                        state_persisted = True
                        self.ownership_store.record_lifecycle_transition(
                            target.get('ownership_record_id'), req.get('policy_id'), req.get('policy_version'),
                            prev, 'FAILED', req.get('operation_id'), req.get('request_id'),
                            'install_backend_failed', 'error'
                        )
                        history_persisted = True
                    except PermissionError:
                        # CAS/state race: never overwrite an advanced/uncertain state.
                        self._raise_install_failure_persistence_error(
                            req, res, state_persisted=state_persisted,
                            history_persisted=history_persisted,
                            reason='ownership_state_changed',
                        )
                    except BrokerDBError:
                        self._raise_install_failure_persistence_error(
                            req, res, state_persisted=state_persisted,
                            history_persisted=history_persisted,
                            reason='persistence_unavailable',
                        )
                    except Exception:
                        # Unknown persistence-layer failure: fail closed without
                        # exposing raw exception details.
                        self._raise_install_failure_persistence_error(
                            req, res, state_persisted=state_persisted,
                            history_persisted=history_persisted,
                            reason='persistence_failure',
                        )
                else:
                    # The record advanced concurrently. Do not downgrade it, and do
                    # not claim the failed installation state was persisted.
                    self._raise_install_failure_persistence_error(
                        req, res, state_persisted=False,
                        history_persisted=False,
                        reason='ownership_state_not_failable',
                    )

            if operation == 'verify_policy':
                if res.get('status') != 'ok':
                    raise PermissionError('Verification failed')
                existing = self._normalize_record(
                    self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                )
                if not existing:
                    raise PermissionError('Ownership required for verification')
                # Re-validate after backend execution: authoritative state may have changed.
                self._assert_ownership_identity_unchanged(ownership_rec, existing)
                existing = self._validate_ownership_binding('verify_policy', req, existing)
                # If canonical schema-v1 policy body is persisted, it must be trusted/valid
                # before evidence storage or lifecycle promotion. Fail closed on corruption/mismatch.
                if canonical_readback is not None:
                    _own_rb, body_rb = self._read_trusted_canonical_policy_body(
                        req, existing, operation='verify_policy', required=True
                    )
                    # Ensure request/backend evidence context matches trusted canonical digests.
                    req_digest = req.get('compiled_rule_digest') or req.get('canonical_policy_digest')
                    if req_digest and str(req_digest) != str(body_rb.get('compiled_rule_digest')):
                        raise FirewallControllerRequestError('Invalid canonical policy record')
                evidence_id = self._store_verification_evidence(req, existing, res)
                try:
                    self.ownership_store.record_audit(
                        'evidence_stored', req, {'evidence_id': evidence_id},
                        existing.get('ownership_record_id')
                    )
                except Exception:
                    pass
                cur = existing.get('installation_state') or 'VERIFYING'
                ver = existing.get('lifecycle_version') or 0
                if cur != 'VERIFYING':
                    self._check_lifecycle_transition(cur, 'VERIFYING')
                    # Stage 1B.14: journal the intermediate VERIFYING establishment
                    # atomically with its CAS update, like other lifecycle promotions.
                    # A failure here rolls back before VERIFIED/ACTIVE promotion.
                    with self.ownership_store.atomic_write():
                        self.ownership_store.update_ownership_state(
                            existing.get('ownership_record_id'), 'VERIFYING', cur, ver
                        )
                        self.ownership_store.record_lifecycle_transition(
                            existing.get('ownership_record_id'),
                            req.get('policy_id'), req.get('policy_version'),
                            cur, 'VERIFYING', req.get('operation_id'), req.get('request_id'),
                            'verification_evidence_persisted', 'ok'
                        )
                    existing_new = self._normalize_record(
                        self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                    ) or existing
                    existing = existing_new
                    ver = existing.get('lifecycle_version') or ver
                self._check_lifecycle_transition('VERIFYING', 'VERIFIED')
                with self.ownership_store.atomic_write():
                    self.ownership_store.update_ownership_state(
                        existing.get('ownership_record_id'), 'VERIFIED', 'VERIFYING',
                        existing.get('lifecycle_version') or ver
                    )
                    self.ownership_store.record_lifecycle_transition(
                        existing.get('ownership_record_id'), req.get('policy_id'), req.get('policy_version'),
                        'VERIFYING', 'VERIFIED', req.get('operation_id'), req.get('request_id'),
                        'evidence_verified', 'ok'
                    )
                existing_new = self._normalize_record(
                    self.ownership_store.get_by_policy(req.get('policy_id'), req.get('policy_version'))
                ) or existing
                existing = existing_new
                self._check_lifecycle_transition('VERIFIED', 'ACTIVE')
                with self.ownership_store.atomic_write():
                    self.ownership_store.update_ownership_state(
                        existing.get('ownership_record_id'), 'ACTIVE', 'VERIFIED',
                        existing.get('lifecycle_version')
                    )
                    self.ownership_store.record_lifecycle_transition(
                        existing.get('ownership_record_id'), req.get('policy_id'), req.get('policy_version'),
                        'VERIFIED', 'ACTIVE', req.get('operation_id'), req.get('request_id'),
                        'activated_with_evidence', 'ok'
                    )

            if operation == 'revoke_policy':
                if revoke_already_done:
                    # Already authoritatively REVOKED; preserve idempotent success only
                    # when matching revocation evidence exists.
                    if not self._has_revocation_evidence(ownership_rec):
                        raise PermissionError('Revocation evidence missing for terminal REVOKED ownership')
                    res = self._revoked_response(req, ownership_rec)
                elif res.get('status') == 'ok':
                    res = self._complete_revoke(req, ownership_rec, res)
                else:
                    # Backend failure/timeout/uncertainty: remain REVOKING, never false REVOKED.
                    try:
                        _reason_code = res.get('error_code') if isinstance(res.get('error_code'), str) else None
                        self.ownership_store.record_audit(
                            'revoke_backend_not_confirmed', req,
                            {
                                'state': 'REVOKING',
                                'reason': (_reason_code if _reason_code and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", _reason_code) else 'backend_error'),
                            },
                            ownership_rec.get('ownership_record_id'),
                        )
                    except Exception:
                        pass

            # For inspect, when a persisted canonical schema-v1 body exists it must be
            # validated via trusted read-back and the response must not be treated as healthy
            # solely due to backend/in-memory status. Fail closed on invalid/corrupt records.
            if operation == 'inspect_policy' and isinstance(res, dict):
                if canonical_readback is not None and res.get('status') == 'ok':
                    _own_rb, body_rb = self._read_trusted_canonical_policy_body(
                        req, ownership_rec, operation='inspect_policy', required=True
                    )
                    result = res.get('result') if isinstance(res.get('result'), dict) else {}
                    result = dict(result)
                    result['canonical_policy'] = {
                        'schema_version': body_rb.get('schema_version'),
                        'policy_id': body_rb.get('policy_id'),
                        'policy_version': body_rb.get('policy_version'),
                        'compiled_rule_digest': body_rb.get('compiled_rule_digest'),
                        'canonical_policy_digest': body_rb.get('canonical_policy_digest'),
                        'required_families': body_rb.get('required_families'),
                        'rules': body_rb.get('rules'),
                    }
                    result['digest_match'] = bool(result.get('digest_match', True)) and str(req.get('compiled_rule_digest') or '') in ('', str(body_rb.get('compiled_rule_digest')))
                    res['result'] = result

            self.audit.log(f"{operation}_completed", req, {"status": res.get("status")})
            res = self._sanitize_outbound_response(res)
            if key:
                ownership_identity = (
                    self._ownership_identity(ownership_rec) if ownership_rec else None
                )
                final_outcome = self._derive_operation_outcome(operation, res)
                completed = self.ownership_store.complete_idempotency_record(
                    key, operation, json.dumps(res),
                    ownership_record_id=(ownership_rec or {}).get('ownership_record_id'),
                    recovery_meta=(
                        {'ownership_identity': list(ownership_identity)}
                        if ownership_identity is not None else None
                    ),
                    operation_outcome=final_outcome,
                    expected_outcomes=('IN_PROGRESS',),
                )
                if not completed:
                    # Stage 1B.4: a concurrent worker already wrote a terminal
                    # outcome. Never overwrite it with this worker's stale result;
                    # replay the authoritative record instead.
                    latest = self._normalize_record(
                        self.ownership_store.get_idempotency_record(key, operation)
                    )
                    action, cached = self._idempotency_replay_decision(
                        operation, req, request_digest, latest
                    )
                    if action != 'return':
                        raise FirewallControllerIdempotencyError(
                            'Operation ledger state conflict'
                        )
                    cached = self._sanitize_outbound_response(cached)
                    self._idempotency[(key, operation)] = {
                        'digest': request_digest, 'response': cached,
                    }
                    return cached
                self._idempotency[(key, operation)] = {'digest': request_digest, 'response': res}
            return res
        except Exception as e:
            self.audit.log(f"{operation}_failed", req, {"error": type(e).__name__})
            # Bound outward leakage from raw internal/storage exceptions while
            # preserving established controller exception classes/semantics.
            if isinstance(e, FirewallControllerPersistenceError):
                # Preserve bounded structured details and established bounded messages.
                details = getattr(e, 'details', None)
                msg = getattr(e, 'message', None) or PERSISTENCE_FAILURE_MESSAGE
                allowed_persist = {
                    PERSISTENCE_FAILURE_MESSAGE,
                    'Install failure could not be fully persisted',
                    'Canonical policy persistence failure',
                }
                if msg not in allowed_persist:
                    msg = PERSISTENCE_FAILURE_MESSAGE
                raise FirewallControllerPersistenceError(msg, details=details) from None
            if isinstance(e, FirewallControllerBackendError):
                raise FirewallControllerBackendError("Backend operation failed") from None
            if isinstance(e, BrokerDBError):
                # Preserve storage-failure exception classification (no conversion to
                # validation errors) while bounding outward leakage of raw DB text.
                if isinstance(e, BrokerDBCanonicalError):
                    if getattr(e, 'category', None) == BrokerDBCanonicalError.OWNERSHIP:
                        raise PermissionError('Authoritative ownership required') from None
                    if getattr(e, 'category', None) == BrokerDBCanonicalError.INTEGRITY:
                        raise FirewallControllerRequestError(INVALID_CANONICAL_POLICY_MESSAGE) from None
                raise BrokerDBError(PERSISTENCE_FAILURE_MESSAGE) from None
            # Preserve known controller/contract exception classes; avoid leaking raw internals.
            if isinstance(e, FirewallControllerRequestError):
                msg = getattr(e, 'message', None) or INVALID_REQUEST_MESSAGE
                allowed_request_msgs = {
                    'Invalid request',
                    'Invalid policy_id', 'Invalid instance_id', 'Invalid network_id',
                    'Invalid request_id', 'Invalid operation_id', 'Invalid idempotency_key',
                    'Invalid policy_version', 'Invalid compiled_rule_digest',
                    'Invalid canonical_policy_digest', 'Invalid canonical policy',
                    'Invalid canonical policy record', 'Invalid required_families',
                    'Missing required_families', 'Address family mismatch',
                }
                if not isinstance(msg, str) or msg not in allowed_request_msgs:
                    msg = INVALID_REQUEST_MESSAGE
                raise FirewallControllerRequestError(msg) from None
            if isinstance(e, FirewallControllerAuthError):
                raise
            if isinstance(e, FirewallControllerIdempotencyError):
                msg = getattr(e, 'message', None) or 'Idempotency conflict'
                allowed = {
                    'Idempotency key conflict',
                    'Idempotency key conflict for different payload',
                    'Operation ledger state conflict',
                    'Corrupt idempotency state',
                    self._IDEMPOTENCY_DIGEST_CORRUPT_MESSAGE,
                }
                if not isinstance(msg, str) or msg not in allowed:
                    msg = 'Idempotency conflict'
                raise FirewallControllerIdempotencyError(msg, details=getattr(e, 'details', None)) from None
            if isinstance(e, PermissionError):
                msg = str(e) if str(e) else 'Unauthorized'
                if len(msg) > 256 or '\n' in msg or '\r' in msg:
                    msg = 'Unauthorized'
                raise PermissionError(msg) from None
            # Unknown/internal exceptions must not leak raw text.
            raise FirewallControllerBackendError("Backend operation failed") from None

    def health_check(self, req=None):
        return self._call("health_check", req or {})

    def install_policy(self, req):
        return self._call("install_policy", req)

    def inspect_policy(self, req):
        return self._call("inspect_policy", req)

    def verify_policy(self, req):
        return self._call("verify_policy", req)

    def revoke_policy(self, req):
        return self._call("revoke_policy", req)

    def remove_stale_policy(self, req):
        return self._call("remove_stale_policy", req)

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def _set_reconciliation_status(self, rec, oid, status, *, allowed_states=None,
                                   inspect_req=None):
        """Write a reconciliation decision with an explicit source-state contract.

        Stage 1B.6: every structured reconciliation decision re-reads authoritative
        ownership, verifies identity/policy binding and allowed source state, then
        writes under the lifecycle-version CAS. A stale or ambiguous source is a
        conflict (``False``), never a newer-state overwrite. Forged evidence or a
        mismatched policy/operation identity is also a conflict.

        Stage 1B.14: the additive compatibility fallbacks are removed. A caller
        without an explicit allowed-source-state contract, or a store without the
        guard context manager, is a conflict (``False``), never an unguarded write.
        The status decision and its security audit are one DB-only transaction, so
        an audit failure cannot leave a committed decision without its audit trail.
        """
        guard = getattr(self.ownership_store, 'reconciliation_version_guard', None)
        if guard is None or not allowed_states:
            return False

        pid = rec.get('policy_id')
        pver = rec.get('policy_version')
        try:
            fresh = self._normalize_record(self.ownership_store.get_by_policy(pid, pver)) or rec
            self._assert_ownership_identity_unchanged(rec, fresh)
            if fresh.get('installation_state') not in set(allowed_states):
                return False
            if inspect_req is not None:
                # Bind the decision to the operation/policy identity that produced it.
                self._validate_ownership_binding(
                    'reconcile_pending_operations', inspect_req, fresh
                )
            with self.ownership_store.atomic_write():
                with guard(fresh.get('lifecycle_version')):
                    written = bool(self.ownership_store.update_reconciliation_status(oid, status))
                    if written and inspect_req is not None:
                        self.ownership_store.record_audit(
                            f'reconcile_status_{status}', inspect_req,
                            {
                                'status': status,
                                'from_state': fresh.get('installation_state'),
                                'policy_id': pid,
                                'policy_version': pver,
                            },
                            oid,
                        )
            return written
        except PermissionError:
            # Stale worker, identity change or binding mismatch: conflict, not failure.
            return False

    def reconcile_pending_operations(self, req):
        req = dict(req or {})
        # Authorize/validate - fail closed.
        self.auth.authorize(req, 'reconcile_pending_operations')
        self.validator.validate(req)
        policy_id = req.get('policy_id')
        policy_version = req.get('policy_version')
        # Reuse the shared canonical validator. The full-scan branch may omit
        # policy_id, but any identifier that is present must still be valid.
        self._validate_caller_identifiers(req, require_policy=policy_id is not None)
        results = {'reconciled': [], 'uncertain': [], 'errors': [], 'adopted': []}
        targets = []
        # A failed authoritative ownership read still propagates as BrokerDBError
        # (F-02 contract): it is never treated as absence or as backend uncertainty.
        if policy_id is not None and policy_version is not None:
            rec = self._normalize_record(self.ownership_store.get_by_policy(policy_id, policy_version))
            if rec:
                # Caller-supplied reconciliation metadata must match persistence.
                rec = self._validate_ownership_binding('reconcile_pending_operations', req, rec)
                targets.append(rec)
            else:
                # No ownership - never adopt unknown backend rules.
                results['uncertain'].append({'policy_id': policy_id, 'policy_version': policy_version, 'reason': 'no_ownership_no_adoption'})
                return {'status': 'ok', 'result': results}
        else:
            for r in self.ownership_store.list_ownerships():
                targets.append(self._normalize_record(r))

        persistence_failed = False

        def mark_persistence_failure(target_pid):
            nonlocal persistence_failed
            persistence_failed = True
            results['errors'].append({'policy_id': target_pid, 'error_code': 'PERSISTENCE_FAILURE'})

        known_states = set(self.LIFECYCLE_TRANSITIONS)

        for rec in targets:
            pid = rec.get('policy_id')
            pver = rec.get('policy_version')
            oid = rec.get('ownership_record_id')
            state = rec.get('installation_state')
            digest = rec.get('canonical_policy_digest')
            family = self._record_family(rec)

            # Validate the persisted record itself before using it to drive any action.
            try:
                self._validate_ownership_binding('inspect_policy', {
                    'policy_id': pid,
                    'policy_version': pver,
                    'compiled_rule_digest': digest,
                    'instance_id': rec.get('instance_id'),
                    'network_id': rec.get('network_id'),
                    'ownership_reference': oid,
                    'address_family': family,
                }, rec)
            except PermissionError:
                results['uncertain'].append({'policy_id': pid, 'reason': 'corrupt_ownership_record'})
                continue

            # Operation/policy identity used for every reconciliation decision in
            # this iteration, including canonical-body and unknown-state branches.
            inspect_req = {
                'request_id': str(uuid.uuid4()),
                'operation_id': str(uuid.uuid4()),
                'idempotency_key': str(uuid.uuid4()),
                'policy_id': pid,
                'policy_version': pver,
                'compiled_rule_digest': digest,
                'compiled': {},
                'instance_id': rec.get('instance_id'),
                'network_id': rec.get('network_id'),
                'address_family': family,
                'required_families': [family],
                'ownership_reference': oid,
                'ownership_record_id': oid,
            }

            # If a canonical schema-v1 policy body exists, it must be trusted/valid before
            # reconciliation makes lifecycle decisions. Fail closed on corruption/mismatch.
            canonical_body_info = None
            try:
                existing_body = self.ownership_store.get_canonical_policy_body(pid, pver)
            except BrokerDBError:
                mark_persistence_failure(pid)
                continue
            if existing_body is not None:
                try:
                    _own_rb, canonical_body_info = self.ownership_store.read_trusted_canonical_policy_body(
                        pid,
                        pver,
                        expected_owner_id=str(rec.get('instance_id') or ''),
                        expected_ownership_record_id=str(oid or ''),
                        expected_compiled_rule_digest=str(digest or ''),
                        expected_digest=str(digest or ''),
                        require_schema_v1=True,
                    )
                except Exception as e:
                    # Distinguish persistence/storage failures from integrity/validation
                    # failures (SR-08 residual). Storage failures must not be reported as
                    # invalid canonical bodies, but reconciliation remains fail-closed.
                    if is_persistence_exception(e):
                        try:
                            self._set_reconciliation_status(
                                rec, oid, 'uncertain', allowed_states=(state,), inspect_req=inspect_req
                            )
                        except BrokerDBError:
                            pass
                        mark_persistence_failure(pid)
                        continue
                    try:
                        self._set_reconciliation_status(
                            rec, oid, 'uncertain', allowed_states=(state,), inspect_req=inspect_req
                        )
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                    results['uncertain'].append({'policy_id': pid, 'reason': 'invalid_canonical_policy_body'})
                    continue
                if canonical_body_info and str(canonical_body_info.get('compiled_rule_digest') or '') != str(digest or ''):
                    try:
                        self._set_reconciliation_status(
                            rec, oid, 'uncertain', allowed_states=(state,), inspect_req=inspect_req
                        )
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                    results['uncertain'].append({'policy_id': pid, 'reason': 'canonical_policy_digest_mismatch'})
                    continue

            # Unsupported persisted lifecycle states fail closed. They are never
            # adopted, guessed, or rewritten; unrelated valid records are still
            # processed.
            if state not in known_states:
                try:
                    self.ownership_store.record_audit(
                        'reconcile_unknown_lifecycle_state', inspect_req,
                        {'reason': 'corrupt_ownership_state'}, oid,
                    )
                except BrokerDBError:
                    mark_persistence_failure(pid)
                try:
                    self._set_reconciliation_status(
                        rec, oid, 'uncertain', allowed_states=(state,), inspect_req=inspect_req
                    )
                except BrokerDBError:
                    mark_persistence_failure(pid)
                results['uncertain'].append({'policy_id': pid, 'reason': 'corrupt_ownership_state'})
                continue

            backend_state = None
            backend_error = None
            try:
                insp = self.backend.inspect_policy(inspect_req)
                if isinstance(insp, dict) and insp.get('status') == 'ok':
                    backend_state = (insp.get('result') or {}).get('status') or insp.get('result')
                elif isinstance(insp, dict):
                    backend_state = (insp.get('result') or {}).get('status') if isinstance(insp.get('result'), dict) else None
                    backend_error = self._safe_backend_error_code(insp)
            except Exception:
                backend_error = 'BACKEND_ERROR'

            # Evidence-persisted but promotion incomplete.
            if state == 'VERIFIED':
                try:
                    valid_evidence = self._find_valid_verification_evidence(rec, oid, family)
                except BrokerDBError:
                    mark_persistence_failure(pid)
                    continue
                if valid_evidence:
                    try:
                        current = self._normalize_record(self.ownership_store.get_by_policy(pid, pver)) or rec
                        self._assert_ownership_identity_unchanged(rec, current)
                        ver = current.get('lifecycle_version') or 0
                        self._check_lifecycle_transition('VERIFIED', 'ACTIVE')
                        with self.ownership_store.atomic_write():
                            self.ownership_store.update_ownership_state(oid, 'ACTIVE', 'VERIFIED', ver)
                            self.ownership_store.record_lifecycle_transition(
                                oid, pid, pver, 'VERIFIED', 'ACTIVE',
                                inspect_req['operation_id'], inspect_req['request_id'],
                                'reconcile_promote_active', 'ok'
                            )
                        # R16-02: a successful lifecycle promotion must not leave the
                        # reconciliation decision stale. The guarded write and its audit
                        # are one DB-only transaction; any failure stays fail-closed.
                        try:
                            status_written = self._set_reconciliation_status(
                                rec, oid, 'ok', allowed_states=('ACTIVE',), inspect_req=inspect_req
                            )
                        except BrokerDBError:
                            mark_persistence_failure(pid)
                            continue
                        if not status_written:
                            results['uncertain'].append({'policy_id': pid, 'reason': 'reconciliation_state_changed'})
                            continue
                        results['reconciled'].append({'policy_id': pid, 'action': 'promoted_to_active'})
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                    except PermissionError:
                        results['uncertain'].append({'policy_id': pid, 'reason': 'ownership_identity_changed'})
                    except Exception as e:
                        results['uncertain'].append({'policy_id': pid, 'reason': f'reconcile_failed:{type(e).__name__}'})
                else:
                    results['uncertain'].append({'policy_id': pid, 'reason': 'verified_without_valid_evidence'})
                continue

            if state == 'ACTIVE':
                # Verify backend still consistent if possible; fail closed on uncertainty.
                if backend_error or backend_state != 'installed':
                    try:
                        self._set_reconciliation_status(
                            rec, oid, 'uncertain', allowed_states=('ACTIVE',), inspect_req=inspect_req
                        )
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    results['uncertain'].append({'policy_id': pid, 'reason': 'active_backend_mismatch_or_unavailable'})
                else:
                    try:
                        status_written = self._set_reconciliation_status(
                            rec, oid, 'ok', allowed_states=('ACTIVE',), inspect_req=inspect_req
                        )
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    if status_written:
                        results['reconciled'].append({'policy_id': pid, 'action': 'active_ok'})
                    else:
                        results['uncertain'].append({'policy_id': pid, 'reason': 'reconciliation_state_changed'})
                continue

            # Uncertain/interrupted install states.
            if state in ('REQUESTED', 'INSTALLING', 'VALIDATING'):
                if backend_error:
                    results['uncertain'].append({'policy_id': pid, 'reason': 'backend_readback_unavailable'})
                    try:
                        self._set_reconciliation_status(
                            rec, oid, 'uncertain', allowed_states=(state,), inspect_req=inspect_req
                        )
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                    continue
                if backend_state == 'installed':
                    # Backend completed but response lost / uncertain; do NOT promote to ACTIVE without verification evidence.
                    try:
                        cur = self._normalize_record(self.ownership_store.get_by_policy(pid, pver)) or rec
                        self._assert_ownership_identity_unchanged(rec, cur)
                        if cur.get('installation_state') in ('REQUESTED', 'VALIDATING'):
                            self._check_lifecycle_transition(cur.get('installation_state'), 'INSTALLING')
                            with self.ownership_store.atomic_write():
                                self.ownership_store.update_ownership_state(oid, 'INSTALLING', cur.get('installation_state'), cur.get('lifecycle_version'))
                                self.ownership_store.record_lifecycle_transition(
                                    oid, pid, pver, cur.get('installation_state'), 'INSTALLING',
                                    inspect_req['operation_id'], inspect_req['request_id'],
                                    'reconcile_backend_installed', 'ok'
                                )
                        status_written = self._set_reconciliation_status(
                            cur, oid, 'needs_verification',
                            allowed_states=('INSTALLING',), inspect_req=inspect_req,
                        )
                        if not status_written:
                            results['uncertain'].append({
                                'policy_id': pid, 'reason': 'reconciliation_state_changed'
                            })
                            continue
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    except PermissionError:
                        results['uncertain'].append({'policy_id': pid, 'reason': 'ownership_identity_or_state_changed'})
                        continue
                    except Exception as e:
                        results['uncertain'].append({'policy_id': pid, 'reason': f'reconcile_failed:{type(e).__name__}'})
                        continue
                    results['reconciled'].append({'policy_id': pid, 'action': 'marked_needs_verification'})
                    continue
                if backend_state == 'missing':
                    # Crash before backend execution or backend not applied; fail closed - mark failed/cleanup pending, do not auto-retry.
                    try:
                        cur = self._normalize_record(self.ownership_store.get_by_policy(pid, pver)) or rec
                        self._assert_ownership_identity_unchanged(rec, cur)
                        prev = cur.get('installation_state')
                        if prev in ('REQUESTED', 'INSTALLING', 'VALIDATING'):
                            self._check_lifecycle_transition(prev, 'FAILED')
                            with self.ownership_store.atomic_write():
                                self.ownership_store.update_ownership_state(oid, 'FAILED', prev, cur.get('lifecycle_version'))
                                self.ownership_store.record_lifecycle_transition(
                                    oid, pid, pver, prev, 'FAILED',
                                    inspect_req['operation_id'], inspect_req['request_id'],
                                    'reconcile_backend_missing_mark_failed', 'ok'
                                )
                            status_written = self._set_reconciliation_status(
                                cur, oid, 'failed', allowed_states=('FAILED',), inspect_req=inspect_req,
                            )
                            if not status_written:
                                results['uncertain'].append({
                                    'policy_id': pid, 'reason': 'reconciliation_state_changed'
                                })
                                continue
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    except PermissionError:
                        results['uncertain'].append({'policy_id': pid, 'reason': 'ownership_identity_or_state_changed'})
                        continue
                    except Exception as e:
                        results['uncertain'].append({'policy_id': pid, 'reason': f'reconcile_failed:{type(e).__name__}'})
                        continue
                    results['reconciled'].append({'policy_id': pid, 'action': 'marked_failed_backend_missing'})
                    continue
                results['uncertain'].append({'policy_id': pid, 'reason': f'unknown_backend_state:{backend_state}'})
                continue

            if state == 'REVOKING':
                if backend_error:
                    results['uncertain'].append({'policy_id': pid, 'reason': 'backend_readback_unavailable_during_revoke'})
                    continue
                if backend_state in ('missing', 'revoked'):
                    try:
                        cur = self._normalize_record(self.ownership_store.get_by_policy(pid, pver)) or rec
                        self._assert_ownership_identity_unchanged(rec, cur)
                        if cur.get('installation_state') == 'REVOKED':
                            if self._has_revocation_evidence(cur):
                                results['reconciled'].append({'policy_id': pid, 'action': 'revoke_already_confirmed'})
                            else:
                                results['uncertain'].append({'policy_id': pid, 'reason': 'revoked_without_valid_evidence'})
                            continue
                        if cur.get('installation_state') != 'REVOKING':
                            results['uncertain'].append({'policy_id': pid, 'reason': 'revoke_state_changed'})
                            continue
                        # Evidence must be persisted before final promotion.
                        if not self._has_revocation_evidence(cur):
                            self._store_revocation_evidence(inspect_req, cur)
                        self._check_lifecycle_transition('REVOKING', 'REVOKED')
                        with self.ownership_store.atomic_write():
                            self.ownership_store.update_ownership_state(
                                oid, 'REVOKED', 'REVOKING', cur.get('lifecycle_version')
                            )
                            self.ownership_store.record_lifecycle_transition(
                                oid, pid, pver, 'REVOKING', 'REVOKED',
                                inspect_req['operation_id'], inspect_req['request_id'],
                                'reconcile_revoke_confirmed', 'ok'
                            )
                        # R16-02: persist the reconciliation decision for this promotion.
                        try:
                            status_written = self._set_reconciliation_status(
                                cur, oid, 'ok', allowed_states=('REVOKED',), inspect_req=inspect_req
                            )
                        except BrokerDBError:
                            mark_persistence_failure(pid)
                            continue
                        if not status_written:
                            results['uncertain'].append({'policy_id': pid, 'reason': 'reconciliation_state_changed'})
                            continue
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    except PermissionError:
                        results['uncertain'].append({'policy_id': pid, 'reason': 'revoke_state_or_identity_changed'})
                        continue
                    except Exception as e:
                        results['uncertain'].append({'policy_id': pid, 'reason': f'partial_revoke:{type(e).__name__}'})
                        continue
                    results['reconciled'].append({'policy_id': pid, 'action': 'revoke_confirmed'})
                else:
                    results['uncertain'].append({'policy_id': pid, 'reason': 'partial_revoke_backend_still_present'})
                continue

            if state == 'REVOKED':
                # A terminal state is accepted only with matching revocation evidence.
                try:
                    has_evidence = self._has_revocation_evidence(rec)
                except BrokerDBError:
                    mark_persistence_failure(pid)
                    continue
                if not has_evidence:
                    try:
                        self.ownership_store.record_audit(
                            'reconcile_revoked_without_evidence', inspect_req,
                            {'reason': 'revoked_without_valid_evidence'}, oid,
                        )
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                    results['uncertain'].append({'policy_id': pid, 'reason': 'revoked_without_valid_evidence'})
                else:
                    results['reconciled'].append({'policy_id': pid, 'action': 'already_revoked'})
                continue

            if state == 'VERIFYING':
                # Stage 1B.3: VERIFYING is recoverable only when BOTH authoritative
                # verification evidence and a trusted backend read-back are available.
                # The evidence was persisted before the interrupted promotion, so this
                # is not an inference from intent. Without either signal the operation
                # stays explicitly uncertain (existing J.9/J.18 contract).
                if backend_error or backend_state != 'installed':
                    try:
                        self._set_reconciliation_status(
                            rec, oid, 'uncertain', allowed_states=('VERIFYING',), inspect_req=inspect_req
                        )
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    results['uncertain'].append({'policy_id': pid, 'reason': 'verifying_state_uncertain'})
                    continue
                try:
                    valid_evidence = self._find_valid_verification_evidence(rec, oid, family)
                except BrokerDBError:
                    mark_persistence_failure(pid)
                    continue
                if not valid_evidence:
                    try:
                        self._set_reconciliation_status(
                            rec, oid, 'uncertain', allowed_states=('VERIFYING',), inspect_req=inspect_req
                        )
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    results['uncertain'].append({'policy_id': pid, 'reason': 'verifying_state_uncertain'})
                    continue
                try:
                    verifying = self._normalize_record(self.ownership_store.get_by_policy(pid, pver)) or rec
                    self._assert_ownership_identity_unchanged(rec, verifying)
                    if verifying.get('installation_state') != 'VERIFYING':
                        results['uncertain'].append({'policy_id': pid, 'reason': 'verifying_state_changed'})
                        continue
                    ver = verifying.get('lifecycle_version') or 0
                    self._check_lifecycle_transition('VERIFYING', 'VERIFIED')
                    with self.ownership_store.atomic_write():
                        self.ownership_store.update_ownership_state(oid, 'VERIFIED', 'VERIFYING', ver)
                        self.ownership_store.record_lifecycle_transition(
                            oid, pid, pver, 'VERIFYING', 'VERIFIED',
                            inspect_req['operation_id'], inspect_req['request_id'],
                            'reconcile_verifying_evidence_verified', 'ok'
                        )
                    verified = self._normalize_record(self.ownership_store.get_by_policy(pid, pver)) or verifying
                    self._assert_ownership_identity_unchanged(rec, verified)
                    self._check_lifecycle_transition('VERIFIED', 'ACTIVE')
                    with self.ownership_store.atomic_write():
                        self.ownership_store.update_ownership_state(
                            oid, 'ACTIVE', 'VERIFIED', verified.get('lifecycle_version')
                        )
                        self.ownership_store.record_lifecycle_transition(
                            oid, pid, pver, 'VERIFIED', 'ACTIVE',
                            inspect_req['operation_id'], inspect_req['request_id'],
                            'reconcile_verifying_activated_with_evidence', 'ok'
                        )
                    # R16-02: the final ACTIVE promotion also needs a guarded
                    # reconciliation decision; a conflict is never a clean recovery.
                    try:
                        status_written = self._set_reconciliation_status(
                            rec, oid, 'ok', allowed_states=('ACTIVE',), inspect_req=inspect_req
                        )
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    if not status_written:
                        results['uncertain'].append({'policy_id': pid, 'reason': 'reconciliation_state_changed'})
                        continue
                except BrokerDBError:
                    mark_persistence_failure(pid)
                    continue
                except PermissionError:
                    results['uncertain'].append({'policy_id': pid, 'reason': 'ownership_identity_or_state_changed'})
                    continue
                except Exception as e:
                    results['uncertain'].append({'policy_id': pid, 'reason': f'reconcile_failed:{type(e).__name__}'})
                    continue
                results['reconciled'].append({'policy_id': pid, 'action': 'verifying_recovered_with_evidence'})
                continue

            if state in ('FAILED', 'CLEANUP_PENDING', 'ORPHANED'):
                results['reconciled'].append({'policy_id': pid, 'action': 'no_auto_change_terminalish'})
                continue

            # Any other known but unhandled state must not be silently skipped.
            try:
                self._set_reconciliation_status(
                    rec, oid, 'uncertain', allowed_states=(state,), inspect_req=inspect_req
                )
            except BrokerDBError:
                mark_persistence_failure(pid)
                continue
            results['uncertain'].append({'policy_id': pid, 'reason': f'unhandled_lifecycle_state:{state}'})

        # Mark pending idempotency as uncertain (do not auto-replay).
        try:
            pending_idempotency = self.ownership_store.get_pending_idempotency()
        except BrokerDBError:
            # The ledger scan is itself subject to storage failure; classify it as
            # persistence failure rather than letting a raw DB error escape or
            # mislabeling it as an uncertain backend outcome.
            mark_persistence_failure(policy_id)
        else:
            for idem in pending_idempotency:
                if policy_id and idem.get('resource_key') and not _resource_key_matches_policy(idem.get('resource_key'), policy_id):
                    continue
                # Stage 1B.1: report the durable operation outcome for discrimination.
                # Legacy rows with no recorded outcome are treated as INTENT_RECORDED.
                ledger_outcome = idem.get('operation_outcome') or 'INTENT_RECORDED'
                results['uncertain'].append({
                    'idempotency_key': idem.get('idempotency_key'),
                    'operation': idem.get('operation_type'),
                    'operation_outcome': ledger_outcome,
                    'reason': 'pending_no_auto_replay',
                })

        if persistence_failed:
            return {
                'status': 'error',
                'error_code': 'RECONCILIATION_PERSISTENCE_FAILURE',
                'error_message': 'Persistence failure during reconciliation',
                'result': results,
            }
        return {'status': 'ok', 'result': results}
