"""CRLF-preserving controller patch for Stage 1B.4 (idempotent evidence artifact)."""
from __future__ import annotations

import io
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    'broker', 'firewall_controller_service', 'controller_service.py')


def apply(text, old, new):
    old_c = old.replace('\n', '\r\n')
    new_c = new.replace('\n', '\r\n')
    count = text.count(old_c)
    if count == 1:
        print('applied', repr(old[:60]))
        return text.replace(old_c, new_c)
    if count == 0 and text.count(new_c) >= 1:
        print('already applied', repr(old[:60]))
        return text
    raise AssertionError((old[:80], count))


with io.open(PATH, 'r', encoding='utf-8', newline='') as f:
    text = f.read()

replacements = [
    ("""                final_outcome = self._derive_operation_outcome(operation, res)
                self.ownership_store.complete_idempotency_record(
                    key, operation, json.dumps(res),
                    ownership_record_id=(ownership_rec or {}).get('ownership_record_id'),
                    recovery_meta=(
                        {'ownership_identity': list(ownership_identity)}
                        if ownership_identity is not None else None
                    ),
                    operation_outcome=final_outcome,
                )
                self._idempotency[(key, operation)] = {'digest': request_digest, 'response': res}
            return res""",
     """                final_outcome = self._derive_operation_outcome(operation, res)
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
                    self._idempotency[(key, operation)] = {
                        'digest': request_digest, 'response': cached,
                    }
                    return cached
                self._idempotency[(key, operation)] = {'digest': request_digest, 'response': res}
            return res"""),
    ("""    def reconcile_pending_operations(self, req):""",
     """    def _set_reconciliation_status(self, rec, oid, status):
        \"\"\"Write a reconciliation decision fenced by the observed lifecycle version.

        Compatibility: a test-only store without the additive guard context manager
        falls back to the original unguarded write.
        \"\"\"
        guard = getattr(self.ownership_store, 'reconciliation_version_guard', None)
        if guard is None:
            return bool(self.ownership_store.update_reconciliation_status(oid, status))
        with guard(rec.get('lifecycle_version')):
            return bool(self.ownership_store.update_reconciliation_status(oid, status))

    def reconcile_pending_operations(self, req):"""),
    ("""                    try:
                        self.ownership_store.update_reconciliation_status(oid, 'uncertain')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                    results['uncertain'].append({'policy_id': pid, 'reason': 'invalid_canonical_policy_body'})""",
     """                    try:
                        self._set_reconciliation_status(rec, oid, 'uncertain')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                    results['uncertain'].append({'policy_id': pid, 'reason': 'invalid_canonical_policy_body'})"""),
    ("""                    try:
                        self.ownership_store.update_reconciliation_status(oid, 'uncertain')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                    results['uncertain'].append({'policy_id': pid, 'reason': 'canonical_policy_digest_mismatch'})""",
     """                    try:
                        self._set_reconciliation_status(rec, oid, 'uncertain')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                    results['uncertain'].append({'policy_id': pid, 'reason': 'canonical_policy_digest_mismatch'})"""),
    ("""                try:
                    self.ownership_store.update_reconciliation_status(oid, 'uncertain')
                except BrokerDBError:
                    mark_persistence_failure(pid)
                results['uncertain'].append({'policy_id': pid, 'reason': 'corrupt_ownership_state'})""",
     """                try:
                    self._set_reconciliation_status(rec, oid, 'uncertain')
                except BrokerDBError:
                    mark_persistence_failure(pid)
                results['uncertain'].append({'policy_id': pid, 'reason': 'corrupt_ownership_state'})"""),
    ("""            if state == 'ACTIVE':
                # Verify backend still consistent if possible; fail closed on uncertainty.
                if backend_error or backend_state != 'installed':
                    try:
                        self.ownership_store.update_reconciliation_status(oid, 'uncertain')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    results['uncertain'].append({'policy_id': pid, 'reason': 'active_backend_mismatch_or_unavailable'})
                else:
                    try:
                        self.ownership_store.update_reconciliation_status(oid, 'ok')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    results['reconciled'].append({'policy_id': pid, 'action': 'active_ok'})
                continue""",
     """            if state == 'ACTIVE':
                # Verify backend still consistent if possible; fail closed on uncertainty.
                if backend_error or backend_state != 'installed':
                    try:
                        self._set_reconciliation_status(rec, oid, 'uncertain')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    results['uncertain'].append({'policy_id': pid, 'reason': 'active_backend_mismatch_or_unavailable'})
                else:
                    try:
                        status_written = self._set_reconciliation_status(rec, oid, 'ok')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    if status_written:
                        results['reconciled'].append({'policy_id': pid, 'action': 'active_ok'})
                    else:
                        results['uncertain'].append({'policy_id': pid, 'reason': 'reconciliation_state_changed'})
                continue"""),
    ("""                    results['uncertain'].append({'policy_id': pid, 'reason': 'backend_readback_unavailable'})
                    try:
                        self.ownership_store.update_reconciliation_status(oid, 'uncertain')""",
     """                    results['uncertain'].append({'policy_id': pid, 'reason': 'backend_readback_unavailable'})
                    try:
                        self._set_reconciliation_status(rec, oid, 'uncertain')"""),
    ("""                if backend_error or backend_state != 'installed':
                    try:
                        self.ownership_store.update_reconciliation_status(oid, 'uncertain')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    results['uncertain'].append({'policy_id': pid, 'reason': 'verifying_state_uncertain'})""",
     """                if backend_error or backend_state != 'installed':
                    try:
                        self._set_reconciliation_status(rec, oid, 'uncertain')
                    except BrokerDBError:
                        mark_persistence_failure(pid)
                        continue
                    results['uncertain'].append({'policy_id': pid, 'reason': 'verifying_state_uncertain'})"""),
    ("""                if not valid_evidence:
                    try:
                        self.ownership_store.update_reconciliation_status(oid, 'uncertain')""",
     """                if not valid_evidence:
                    try:
                        self._set_reconciliation_status(rec, oid, 'uncertain')"""),
    ("""            try:
                self.ownership_store.update_reconciliation_status(oid, 'uncertain')
            except BrokerDBError:
                mark_persistence_failure(pid)
                continue
            results['uncertain'].append({'policy_id': pid, 'reason': f'unhandled_lifecycle_state:{state}'})""",
     """            try:
                self._set_reconciliation_status(rec, oid, 'uncertain')
            except BrokerDBError:
                mark_persistence_failure(pid)
                continue
            results['uncertain'].append({'policy_id': pid, 'reason': f'unhandled_lifecycle_state:{state}'})"""),
]

for old, new in replacements:
    text = apply(text, old, new)

with io.open(PATH, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('patched controller')
