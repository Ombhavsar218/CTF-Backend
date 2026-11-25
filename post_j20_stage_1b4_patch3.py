"""CRLF-preserving canonical-body race fix for Stage 1B.4."""
from __future__ import annotations

import io
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    'broker', 'firewall_controller_service', 'ownership_store.py')

OLD = """    def ensure_canonical_policy_body(self, rec: Dict[str, Any]) -> str | None:
        \"\"\"Idempotently ensure canonical policy body exists and matches; return body id or None if absent/not applicable.\"\"\"
        try:
            existing = self.get_canonical_policy_body(str(rec.get('policy_id') or ''), rec.get('policy_version'))
        except Exception:
            existing = None
        if existing:
            # Validate existing record matches requested bindings/digest; fail closed on mismatch/corruption.
            self.read_trusted_canonical_policy_body(
                str(rec.get('policy_id') or ''),
                rec.get('policy_version'),
                expected_owner_id=str((rec.get('owner_id') or rec.get('instance_id') or '')) or None,
                expected_ownership_record_id=str(rec.get('ownership_record_id') or '') or None,
                expected_compiled_rule_digest=str(rec.get('compiled_rule_digest') or '') or None,
            )
            # Also ensure rules match if provided
            if rec.get('rules') is not None:
                norm = validate_and_normalize_rules(rec.get('rules'), required_families=rec.get('required_families'))
                if schema_compiled_rule_digest(norm) != existing.get('compiled_rule_digest'):
                    raise BrokerDBError('Canonical policy body digest mismatch')
            return existing.get('policy_body_id')
        return self.store_canonical_policy_body(rec)
"""

NEW = """    def _validate_existing_canonical_policy_body(self, rec: Dict[str, Any], existing: Dict[str, Any]) -> str:
        \"\"\"Validate a persisted canonical body against requested bindings; fail closed.\"\"\"
        self.read_trusted_canonical_policy_body(
            str(rec.get('policy_id') or ''),
            rec.get('policy_version'),
            expected_owner_id=str((rec.get('owner_id') or rec.get('instance_id') or '')) or None,
            expected_ownership_record_id=str(rec.get('ownership_record_id') or '') or None,
            expected_compiled_rule_digest=str(rec.get('compiled_rule_digest') or '') or None,
        )
        if rec.get('rules') is not None:
            norm = validate_and_normalize_rules(rec.get('rules'), required_families=rec.get('required_families'))
            if schema_compiled_rule_digest(norm) != existing.get('compiled_rule_digest'):
                raise BrokerDBError('Canonical policy body digest mismatch')
        return existing.get('policy_body_id')

    def ensure_canonical_policy_body(self, rec: Dict[str, Any]) -> str | None:
        \"\"\"Idempotently ensure canonical policy body exists and matches; return body id or None if absent/not applicable.

        Stage 1B.4: a concurrent writer may win the single-body UNIQUE race after
        this caller observed absence. Resolve that specific idempotent conflict by
        validating the durable winner, instead of reporting a persistence failure.
        Genuine storage failures and mismatches still raise BrokerDBError.
        \"\"\"
        pid = str(rec.get('policy_id') or '')
        pver = rec.get('policy_version')
        try:
            existing = self.get_canonical_policy_body(pid, pver)
        except Exception:
            existing = None
        if existing:
            return self._validate_existing_canonical_policy_body(rec, existing)
        try:
            return self.store_canonical_policy_body(rec)
        except BrokerDBError as e:
            msg = str(e)
            if 'UNIQUE constraint failed' not in msg or 'controller_policy_bodies' not in msg:
                raise
            winner = self.get_canonical_policy_body(pid, pver)
            if not winner:
                raise
            return self._validate_existing_canonical_policy_body(rec, winner)
"""

with io.open(PATH, 'r', encoding='utf-8', newline='') as f:
    text = f.read()
old_c = OLD.replace('\n', '\r\n')
new_c = NEW.replace('\n', '\r\n')
assert text.count(old_c) == 1, text.count(old_c)
with io.open(PATH, 'w', encoding='utf-8', newline='') as f:
    f.write(text.replace(old_c, new_c))
print('patched canonical body ensure')
