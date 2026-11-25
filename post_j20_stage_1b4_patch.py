"""One-shot CRLF-preserving patch for Stage 1B.4 source fixes (evidence artifact)."""
from __future__ import annotations

import io
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def patch(rel, replacements):
    path = os.path.join(ROOT, rel)
    with io.open(path, 'r', encoding='utf-8', newline='') as f:
        text = f.read()
    for old, new in replacements:
        old_c = old.replace('\n', '\r\n')
        new_c = new.replace('\n', '\r\n')
        count = text.count(old_c)
        print(rel, 'count', count, repr(old[:60]))
        assert count == 1, (rel, old[:80], count)
        text = text.replace(old_c, new_c)
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    print('patched', rel)


store = os.path.join('broker', 'firewall_controller_service', 'ownership_store.py')
patch(store, [
    # Signature: derive the existing continuation indent so whitespace cannot drift.
    ("""operation_outcome: str = None):
        \"\"\"Complete the idempotency record.""",
     """operation_outcome: str = None,
                                    expected_outcomes=None) -> bool:
        \"\"\"Complete the idempotency record."""),
    ("""        COMPLETED status in the same transaction. Default ``None`` preserves legacy
        behavior exactly for existing callers.
        \"\"\"""",
     """        COMPLETED status in the same transaction. Default ``None`` preserves legacy
        behavior exactly for existing callers.

        Stage 1B.4: ``expected_outcomes`` adds an optional CAS guard on the current
        informational operation outcome. A guard miss returns ``False`` (a conflict,
        never a persistence failure), so a stale worker cannot overwrite a newer
        terminal response/outcome. Genuine storage failures still raise BrokerDBError.
        \"\"\""""),
    ("""            params.extend([idempotency_key, operation_type])
            cur.execute('''UPDATE controller_idempotency SET status='COMPLETED', response_json=?, lifecycle_state=?,
                ownership_record_id=COALESCE(?, ownership_record_id),
                recovery_meta_json=COALESCE(?, recovery_meta_json),
                completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP''' + outcome_sql +
                ' WHERE idempotency_key=? AND operation_type=?', tuple(params))
            conn.commit()""",
     """            params.extend([idempotency_key, operation_type])
            guard_sql = ''
            if expected_outcomes is not None:
                outs = tuple(expected_outcomes)
                if not outs:
                    conn.rollback()
                    return False
                placeholders = ','.join('?' for _ in outs)
                guard_sql = f' AND (operation_outcome IN ({placeholders}) OR operation_outcome IS NULL)'
                params.extend(outs)
            cur.execute('''UPDATE controller_idempotency SET status='COMPLETED', response_json=?, lifecycle_state=?,
                ownership_record_id=COALESCE(?, ownership_record_id),
                recovery_meta_json=COALESCE(?, recovery_meta_json),
                completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP''' + outcome_sql +
                ' WHERE idempotency_key=? AND operation_type=?' + guard_sql, tuple(params))
            updated = cur.rowcount > 0
            conn.commit()
            return updated"""),
    ("""    def update_reconciliation_status(self, ownership_record_id: str, status: str):
        try:
            self._execute_fk('UPDATE controller_ownership SET reconciliation_status=?, last_reconciliation_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE ownership_record_id=?',
                            (status, ownership_record_id))
        except BrokerDBError as e:
            raise BrokerDBError(f'Failed to update reconciliation status: {e}')
        except Exception as e:
            raise BrokerDBError(f'Failed to update reconciliation status: {e}')
""",
     """    @contextmanager
    def reconciliation_version_guard(self, expected_version):
        \"\"\"Bind the next reconciliation-status write to an observed lifecycle version.

        Stage 1B.4: reconciliation decisions derived from a stale ownership snapshot
        must not overwrite a decision written after a newer lifecycle transition.
        The guard is thread-local (like ``atomic_write``), so one store instance can
        safely serve multiple workers. The previous guard is restored on exit; no
        retry or timing behaviour is introduced.
        \"\"\"
        previous = getattr(self._tx_state, 'recon_version', None)
        self._tx_state.recon_version = expected_version
        try:
            yield
        finally:
            self._tx_state.recon_version = previous

    def update_reconciliation_status(self, ownership_record_id: str, status: str) -> bool:
        \"\"\"Persist a reconciliation decision; return False when a version guard misses.

        Unguarded legacy callers keep the original behaviour and receive ``True`` on a
        successful write. A guard miss is a conflict, not a persistence failure.
        \"\"\"
        expected_version = getattr(self._tx_state, 'recon_version', None)
        if expected_version is None:
            try:
                self._execute_fk('UPDATE controller_ownership SET reconciliation_status=?, last_reconciliation_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE ownership_record_id=?',
                                (status, ownership_record_id))
            except BrokerDBError as e:
                raise BrokerDBError(f'Failed to update reconciliation status: {e}')
            except Exception as e:
                raise BrokerDBError(f'Failed to update reconciliation status: {e}')
            return True
        conn = self._get_conn_fk()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('UPDATE controller_ownership SET reconciliation_status=?, last_reconciliation_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE ownership_record_id=? AND lifecycle_version=?',
                        (status, ownership_record_id, expected_version))
            updated = cur.rowcount > 0
            conn.commit()
            return updated
        except BrokerDBError:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBError(f'Failed to update reconciliation status: {e}')
        finally:
            conn.close()
"""),
])

svc = os.path.join('broker', 'firewall_controller_service', 'controller_service.py')
patch(svc, [
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
])
