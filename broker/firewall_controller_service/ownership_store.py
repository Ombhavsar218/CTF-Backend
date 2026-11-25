import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Dict, Any, Optional, Tuple
from broker.app.db import BrokerDB, BrokerDBError
from .rule_schema_v1 import (
    RULE_SCHEMA_VERSION,
    compiled_rule_digest as schema_compiled_rule_digest,
    validate_and_normalize_rules,
)


class BrokerDBCanonicalError(BrokerDBError):
    """Structured canonical-policy error with a stable security category."""

    OWNERSHIP = 'ownership'
    INTEGRITY = 'integrity'
    PERSISTENCE = 'persistence'

    def __init__(self, message: str, category: str = PERSISTENCE):
        super().__init__(message)
        self.category = category


class BrokerDBIdempotencyConflict(BrokerDBError):
    """Targeted duplicate-key conflict for ``controller_idempotency`` inserts."""

    def __init__(self, idempotency_key: str, operation_type: str):
        super().__init__(f'Idempotency record already exists: {idempotency_key}:{operation_type}')
        self.idempotency_key = idempotency_key
        self.operation_type = operation_type


class BrokerDBCanonicalBodyConflict(BrokerDBError):
    """Targeted single-body UNIQUE conflict for ``controller_policy_bodies`` inserts."""

    def __init__(self, policy_id: str, policy_version: int):
        super().__init__(f'Canonical policy body already exists: {policy_id}:{policy_version}')
        self.policy_id = policy_id
        self.policy_version = policy_version


class _GroupedCursor:
    """Cursor shim used only inside :meth:`ControllerOwnershipStore.atomic_write`.

    Public write methods issue their own ``BEGIN IMMEDIATE``. Inside a grouped
    transaction that statement belongs to the group owner, so it is suppressed;
    every other operation is delegated unchanged.
    """
    def __init__(self, real):
        self._real = real

    def execute(self, sql, *args, **kwargs):
        if isinstance(sql, str) and sql.strip().upper().startswith('BEGIN'):
            return self
        return self._real.execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        if isinstance(sql, str) and sql.strip().upper().startswith('BEGIN'):
            return self
        return self._real.executemany(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _GroupedConnection:
    """Connection shim used only inside :meth:`ControllerOwnershipStore.atomic_write`.

    ``commit`` and ``close`` are deliberately deferred to the group owner so a
    participating public write method cannot terminate the shared transaction.
    ``rollback`` stays live: a method-level rollback aborts the whole group,
    which is the fail-closed behavior we want.
    """
    def __init__(self, real):
        self._real = real

    def cursor(self):
        return _GroupedCursor(self._real.cursor())

    def execute(self, sql, *args, **kwargs):
        if isinstance(sql, str) and sql.strip().upper().startswith('BEGIN'):
            return _GroupedCursor(self._real.cursor())
        return self._real.execute(sql, *args, **kwargs)

    def commit(self):
        return None

    def rollback(self):
        return self._real.rollback()

    def close(self):
        return None

    @property
    def row_factory(self):
        return self._real.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._real.row_factory = value

    def __getattr__(self, name):
        return getattr(self._real, name)


class ControllerOwnershipStore:
    # Operation-level outcomes (Stage 1B.1). These are informational markers on the
    # existing idempotency/operation record, NOT replacements for ownership FSM states.
    OPERATION_OUTCOMES = frozenset({
        'INTENT_RECORDED', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED', 'UNCERTAIN',
    })
    INTENT_OUTCOME = 'INTENT_RECORDED'
    IN_PROGRESS_OUTCOME = 'IN_PROGRESS'
    NON_TERMINAL_OUTCOMES = frozenset({'INTENT_RECORDED', 'IN_PROGRESS'})

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.environ.get('FIREWALL_CONTROLLER_DB_PATH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'firewall_controller.db')
            db_path = os.path.normpath(db_path)
        self.db = BrokerDB(db_path)
        # Stage 1B.2: per-thread handle for an active grouped transaction.
        self._tx_state = threading.local()
        self._init_schema()

    def _init_schema(self):
        with self.db._init_guard():
            conn = self.db._get_conn()
            try:
                cur = conn.cursor()
                cur.execute('PRAGMA journal_mode=WAL;')
                cur.execute('PRAGMA foreign_keys=ON;')
                cur.execute('''CREATE TABLE IF NOT EXISTS controller_ownership (
                    ownership_record_id TEXT PRIMARY KEY,
                    policy_id TEXT NOT NULL,
                    policy_version INTEGER NOT NULL,
                    instance_id TEXT NOT NULL,
                    network_id TEXT NOT NULL,
                    canonical_policy_digest TEXT NOT NULL,
                    installed_rule_ids_json TEXT,
                    address_family TEXT,
                    installation_state TEXT NOT NULL DEFAULT 'REQUESTED',
                    lifecycle_version INTEGER NOT NULL DEFAULT 0,
                    verification_evidence_ref TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    revoked_at TIMESTAMP,
                    last_reconciliation_at TIMESTAMP,
                    reconciliation_status TEXT DEFAULT 'pending'
                )''')
                cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_ctrl_own_unique ON controller_ownership(policy_id, policy_version)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_ctrl_own_instance ON controller_ownership(instance_id)')
                cur.execute('''CREATE TABLE IF NOT EXISTS controller_lifecycle_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ownership_record_id TEXT,
                    policy_id TEXT,
                    policy_version INTEGER,
                    prev_state TEXT,
                    new_state TEXT NOT NULL,
                    operation_id TEXT,
                    request_id TEXT,
                    transition_reason TEXT,
                    result TEXT,
                    error_info TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_ctrl_lc_hist_own ON controller_lifecycle_history(ownership_record_id)')
                cur.execute('''CREATE TABLE IF NOT EXISTS controller_idempotency (
                    idempotency_key TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    resource_key TEXT,
                    ownership_record_id TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    lifecycle_state TEXT,
                    response_json TEXT,
                    recovery_meta_json TEXT,
                    operation_outcome TEXT,
                    outcome_updated_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    PRIMARY KEY (idempotency_key, operation_type)
                )''')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_ctrl_idem_status ON controller_idempotency(status)')
                # Additive migration for databases created before operation-outcome tracking
                # (Stage 1B.1). Runs under the Stage 1A.5 init guard. Legacy rows keep a NULL
                # outcome (they are already COMPLETED/PENDING and remain safe); no backfill.
                for _col, _decl in (('operation_outcome', 'TEXT'), ('outcome_updated_at', 'TIMESTAMP')):
                    _cols = {r[1] for r in cur.execute('PRAGMA table_info(controller_idempotency)').fetchall()}
                    if _col not in _cols:
                        cur.execute(f'ALTER TABLE controller_idempotency ADD COLUMN {_col} {_decl}')
                cur.execute('''CREATE TABLE IF NOT EXISTS controller_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    request_id TEXT,
                    operation_id TEXT,
                    policy_id TEXT,
                    ownership_record_id TEXT,
                    details_json TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
                cur.execute('''CREATE TABLE IF NOT EXISTS controller_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    ownership_record_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_version INTEGER NOT NULL,
                    instance_id TEXT NOT NULL,
                    network_id TEXT NOT NULL,
                    canonical_policy_digest TEXT NOT NULL,
                    address_family TEXT,
                    installed_rule_ids_json TEXT,
                    controller_identity TEXT,
                    controller_transaction_id TEXT,
                    request_id TEXT,
                    verification_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    verification_result TEXT NOT NULL
                )''')
                # Durable canonical schema-v1 policy body persistence (mock-only).
                # Additive and separate from ownership metadata to avoid breaking legacy flows.
                cur.execute('''CREATE TABLE IF NOT EXISTS controller_policy_bodies (
                    policy_body_id TEXT PRIMARY KEY,
                    ownership_record_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_version INTEGER NOT NULL,
                    schema_version TEXT NOT NULL,
                    canonical_rules_json TEXT NOT NULL,
                    required_families_json TEXT,
                    compiled_rule_digest TEXT NOT NULL,
                    canonical_policy_digest TEXT,
                    controller_identity TEXT,
                    request_id TEXT,
                    operation_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ownership_record_id) REFERENCES controller_ownership(ownership_record_id)
                )''')
                cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_ctrl_policy_body_unique ON controller_policy_bodies(policy_id, policy_version)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_ctrl_policy_body_owner ON controller_policy_bodies(ownership_record_id)')
                # Additive append-only protections (mock-only integrity hardening, J.17).
                # Prevent direct mutation/deletion of historical/evidence/audit records where supported.
                for trig, tbl in (
                    ('trg_ctrl_lc_hist_no_update', 'controller_lifecycle_history'),
                    ('trg_ctrl_lc_hist_no_delete', 'controller_lifecycle_history'),
                    ('trg_ctrl_evidence_no_update', 'controller_evidence'),
                    ('trg_ctrl_evidence_no_delete', 'controller_evidence'),
                    ('trg_ctrl_audit_no_update', 'controller_audit'),
                    ('trg_ctrl_audit_no_delete', 'controller_audit'),
                ):
                    action = 'UPDATE' if trig.endswith('_no_update') else 'DELETE'
                    cur.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {trig} BEFORE {action} ON {tbl} "
                        "BEGIN SELECT RAISE(ABORT, 'append-only record'); END"
                    )
                conn.commit()
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
                raise BrokerDBError(f"Schema init failed: {e}")
            finally:
                conn.close()

    def _get_conn_fk(self):
        # Stage 1B.2: a public write called inside ``atomic_write`` joins the
        # already-open transaction; its commit/close are deferred to the group.
        active = getattr(self._tx_state, 'conn', None)
        if active is not None:
            return active
        conn = self.db._get_conn()
        try:
            conn.execute('PRAGMA foreign_keys=ON;')
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            raise
        return conn

    @contextmanager
    def atomic_write(self):
        """Group multiple persistence calls into one SQLite transaction.

        Logically inseparable writes (e.g. a lifecycle state CAS and its history
        row) share a single ``BEGIN IMMEDIATE``/``commit``. Any participating
        write failure, including a commit failure, rolls back the entire group,
        so no partial subset is ever durably visible. Re-entrant use on the same
        thread joins the active transaction. Foreign-key enforcement and all
        existing uniqueness/CAS/append-only constraints remain in force.

        This is a *database-only* boundary. Mock backend effects and filesystem
        state are never inside an SQLite transaction.
        """
        active = getattr(self._tx_state, 'conn', None)
        if active is not None:
            yield active
            return
        real = self.db._get_conn()
        grouped = None
        try:
            real.execute('PRAGMA foreign_keys=ON;')
            real.execute('BEGIN IMMEDIATE')
            grouped = _GroupedConnection(real)
            self._tx_state.conn = grouped
            try:
                yield grouped
            finally:
                self._tx_state.conn = None
            real.commit()
        except (BrokerDBError, PermissionError):
            try:
                real.rollback()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                real.rollback()
            except Exception:
                pass
            raise BrokerDBError(f'Atomic persistence failed: {e}')
        finally:
            try:
                real.close()
            except Exception:
                pass

    def _execute_fk(self, sql: str, params: tuple = ()): 
        conn = None
        try:
            conn = self._get_conn_fk()
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            return cur
        except BrokerDBError:
            raise
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise BrokerDBError(f"DB error: {e}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                try:
                    self.db._secure_files()
                except Exception:
                    pass


    def _query_dicts(self, sql: str, params=()):
        """Run a read query and propagate storage failures.

        Genuine absence is represented by the caller (e.g. ``None`` or an empty list);
        database errors are never converted into ordinary absence.
        """
        rows = self.db.query(sql, params)
        result = []
        for row in rows:
            if hasattr(row, 'keys') and not isinstance(row, dict):
                result.append(dict(row))
            else:
                result.append(row)
        return result

    def create_ownership(self, rec: Dict[str, Any]) -> str:
        conn = self._get_conn_fk()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('SELECT ownership_record_id FROM controller_ownership WHERE policy_id=? AND policy_version=?', (rec['policy_id'], rec['policy_version']))
            if cur.fetchone():
                conn.rollback()
                raise PermissionError('Ownership exists for policy/version')
            cur.execute('''INSERT INTO controller_ownership (ownership_record_id, policy_id, policy_version, instance_id, network_id, canonical_policy_digest, installed_rule_ids_json, address_family, installation_state, lifecycle_version)
                VALUES (?,?,?,?,?,?,?,?,?,0)''', (rec['ownership_record_id'], rec['policy_id'], rec['policy_version'], rec['instance_id'], rec['network_id'], rec['canonical_policy_digest'], json.dumps(rec.get('installed_rule_ids') or []), rec.get('address_family'), rec.get('installation_state') or 'REQUESTED'))
            conn.commit()
            return rec['ownership_record_id']
        except PermissionError:
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBError(f'Failed to create ownership: {e}')
        finally:
            conn.close()

    def get_by_policy(self, policy_id: str, policy_version: int):
        rows = self._query_dicts(
            'SELECT * FROM controller_ownership WHERE policy_id=? AND policy_version=?',
            (policy_id, policy_version),
        )
        if not rows:
            return None
        return rows[0]

    def record_audit(self, event_type: str, req: Dict[str, Any] = None, details: Dict[str, Any] = None, ownership_record_id: str = None):
        try:
            self._execute_fk('INSERT INTO controller_audit (event_type, request_id, operation_id, policy_id, ownership_record_id, details_json) VALUES (?,?,?,?,?,?)',
                            (event_type, (req or {}).get('request_id'), (req or {}).get('operation_id'), (req or {}).get('policy_id'), ownership_record_id, json.dumps(details or {})))
        except BrokerDBError:
            raise BrokerDBError('Audit persistence failed')
        except Exception:
            raise BrokerDBError('Audit persistence failed')

    def store_evidence(self, ev: Dict[str, Any]) -> str:
        conn = self._get_conn_fk()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('''INSERT INTO controller_evidence (evidence_id, ownership_record_id, policy_id, policy_version, instance_id, network_id, canonical_policy_digest, address_family, installed_rule_ids_json, controller_identity, controller_transaction_id, request_id, verification_result)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (ev['evidence_id'], ev['ownership_record_id'], ev['policy_id'], ev['policy_version'], ev['instance_id'], ev['network_id'], ev['canonical_policy_digest'], ev.get('address_family'), json.dumps(ev.get('installed_rule_ids') or []), ev.get('controller_identity'), ev.get('controller_transaction_id'), ev.get('request_id'), ev.get('verification_result')))
            conn.commit()
            return ev['evidence_id']
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBError(f'Failed to store evidence: {e}')
        finally:
            conn.close()

    def update_ownership_state(self, ownership_record_id: str, new_state: str, prev_state: str = None, expected_version: int = None):
        conn = self._get_conn_fk()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            if expected_version is not None and prev_state is not None:
                cur.execute('UPDATE controller_ownership SET installation_state=?, lifecycle_version=lifecycle_version+1, updated_at=CURRENT_TIMESTAMP WHERE ownership_record_id=? AND installation_state=? AND lifecycle_version=?',
                            (new_state, ownership_record_id, prev_state, expected_version))
            elif expected_version is not None:
                cur.execute('UPDATE controller_ownership SET installation_state=?, lifecycle_version=lifecycle_version+1, updated_at=CURRENT_TIMESTAMP WHERE ownership_record_id=? AND lifecycle_version=?',
                            (new_state, ownership_record_id, expected_version))
            elif prev_state:
                cur.execute('UPDATE controller_ownership SET installation_state=?, lifecycle_version=lifecycle_version+1, updated_at=CURRENT_TIMESTAMP WHERE ownership_record_id=? AND installation_state=?',
                            (new_state, ownership_record_id, prev_state))
            else:
                cur.execute('UPDATE controller_ownership SET installation_state=?, lifecycle_version=lifecycle_version+1, updated_at=CURRENT_TIMESTAMP WHERE ownership_record_id=?',
                            (new_state, ownership_record_id))
            if cur.rowcount == 0:
                conn.rollback()
                raise PermissionError('LIFECYCLE_VERSION_CONFLICT')
            conn.commit()
        except PermissionError:
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBError(f'Failed to update ownership state: {e}')
        finally:
            conn.close()

    def record_lifecycle_transition(self, ownership_record_id: str = None, policy_id: str = None, policy_version: int = None,
                                     prev_state: str = None, new_state: str = None, operation_id: str = None,
                                     request_id: str = None, transition_reason: str = None, result: str = None, error_info: str = None):
        try:
            self._execute_fk('''INSERT INTO controller_lifecycle_history 
                (ownership_record_id, policy_id, policy_version, prev_state, new_state, operation_id, request_id, transition_reason, result, error_info)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (ownership_record_id, policy_id, policy_version, prev_state, new_state, operation_id, request_id, transition_reason, result, error_info))
        except BrokerDBError as e:
            raise BrokerDBError(f'Failed to record lifecycle transition: {e}')
        except Exception as e:
            raise BrokerDBError(f'Failed to record lifecycle transition: {e}')

    def create_idempotency_record(self, idempotency_key: str, operation_type: str, request_digest: str, resource_key: str = None,
                                  ownership_record_id: str = None, lifecycle_state: str = None,
                                  operation_outcome: str = None):
        """Persist operation intent before any backend side effect.

        ``operation_outcome`` defaults to the intent marker (backward-compatible with
        callers that do not supply it). Genuine persistence errors remain BrokerDBError;
        duplicate-key collisions are surfaced as BrokerDBError for caller classification.
        """
        outcome = operation_outcome if operation_outcome is not None else self.INTENT_OUTCOME
        if outcome not in self.OPERATION_OUTCOMES:
            raise BrokerDBError('Invalid operation outcome')
        conn = self._get_conn_fk()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            # Stage 1B.6: target the exact PRIMARY KEY conflict. Other integrity
            # failures (or generic storage failures) still raise BrokerDBError and
            # are never classified as an idempotent duplicate by message text.
            cur.execute('''INSERT INTO controller_idempotency
                (idempotency_key, operation_type, request_digest, resource_key, ownership_record_id, status, lifecycle_state, operation_outcome, outcome_updated_at)
                VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(idempotency_key, operation_type) DO NOTHING''',
                (idempotency_key, operation_type, request_digest, resource_key, ownership_record_id, 'PENDING', lifecycle_state, outcome))
            if cur.rowcount == 0:
                raise BrokerDBIdempotencyConflict(idempotency_key, operation_type)
            conn.commit()
        except (BrokerDBIdempotencyConflict, BrokerDBError):
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
            raise BrokerDBError(f'Failed to create idempotency record: {e}')
        finally:
            conn.close()

    def get_idempotency_record(self, idempotency_key: str, operation_type: str):
        rows = self._query_dicts(
            'SELECT * FROM controller_idempotency WHERE idempotency_key=? AND operation_type=?',
            (idempotency_key, operation_type),
        )
        if not rows:
            return None
        return rows[0]

    def update_operation_outcome(self, idempotency_key: str, operation_type: str, outcome: str,
                                 *, expected_outcomes=None) -> bool:
        """CAS-guarded operation-outcome transition on the existing operation record.

        Genuine storage failures are raised as BrokerDBError (persistence failure) and
        never converted into an idempotency conflict. ``False`` is returned only when
        the CAS guard does not match (concurrent/duplicate ledger state).
        """
        if outcome not in self.OPERATION_OUTCOMES:
            raise BrokerDBError('Invalid operation outcome')
        conn = self._get_conn_fk()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            # Placeholder order must follow the SQL: SET outcome, then key/type,
            # then the CAS guard placeholders.
            params = [outcome, idempotency_key, operation_type]
            guard = ''
            if expected_outcomes is not None:
                outs = tuple(expected_outcomes)
                if not outs:
                    conn.rollback()
                    return False
                placeholders = ','.join('?' for _ in outs)
                guard = f' AND (operation_outcome IN ({placeholders}) OR operation_outcome IS NULL)'
                params.extend(outs)
            cur.execute(
                'UPDATE controller_idempotency SET operation_outcome=?, outcome_updated_at=CURRENT_TIMESTAMP '
                'WHERE idempotency_key=? AND operation_type=?' + guard,
                tuple(params),
            )
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
            raise BrokerDBError(f'Failed to update operation outcome: {e}')
        finally:
            conn.close()

    def complete_idempotency_record(self, idempotency_key: str, operation_type: str, response_json: str,
                                    lifecycle_state: str = None, ownership_record_id: str = None,
                                    recovery_meta: Dict[str, Any] = None, operation_outcome: str = None,
                                    expected_outcomes=None) -> bool:
        """Complete the idempotency record.

        When ``operation_outcome`` is supplied it is persisted atomically with the
        COMPLETED status in the same transaction. Default ``None`` preserves legacy
        behavior exactly for existing callers.

        Stage 1B.4: ``expected_outcomes`` adds an optional CAS guard on the current
        informational operation outcome. A guard miss returns ``False`` (a conflict,
        never a persistence failure), so a stale worker cannot overwrite a newer
        terminal response/outcome. Genuine storage failures still raise BrokerDBError.
        """
        if operation_outcome is not None and operation_outcome not in self.OPERATION_OUTCOMES:
            raise BrokerDBError('Invalid operation outcome')
        conn = self._get_conn_fk()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            recovery_meta_json = json.dumps(recovery_meta) if recovery_meta is not None else None
            outcome_sql = ''
            params = [response_json, lifecycle_state, ownership_record_id, recovery_meta_json]
            if operation_outcome is not None:
                outcome_sql = ', operation_outcome=?, outcome_updated_at=CURRENT_TIMESTAMP'
                params.append(operation_outcome)
            params.extend([idempotency_key, operation_type])
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
            return updated
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBError(f'Failed to complete idempotency record: {e}')
        finally:
            conn.close()

    def get_lifecycle_history(self, ownership_record_id: str = None):
        if ownership_record_id:
            return self._query_dicts(
                'SELECT * FROM controller_lifecycle_history WHERE ownership_record_id=? ORDER BY history_id ASC',
                (ownership_record_id,),
            )
        return self._query_dicts('SELECT * FROM controller_lifecycle_history ORDER BY history_id DESC LIMIT 100')

    def get_evidence_by_ownership(self, ownership_record_id: str):
        return self._query_dicts(
            'SELECT * FROM controller_evidence WHERE ownership_record_id=? ORDER BY verification_timestamp DESC',
            (ownership_record_id,),
        )

    def get_evidence_by_policy(self, policy_id: str, policy_version: int):
        return self._query_dicts(
            'SELECT * FROM controller_evidence WHERE policy_id=? AND policy_version=? ORDER BY verification_timestamp DESC',
            (policy_id, policy_version),
        )

    def get_pending_idempotency(self):
        return self._query_dicts(
            "SELECT * FROM controller_idempotency WHERE status='PENDING' ORDER BY created_at ASC"
        )

    def list_ownerships(self):
        return self._query_dicts('SELECT * FROM controller_ownership ORDER BY created_at DESC')

    @contextmanager
    def reconciliation_version_guard(self, expected_version):
        """Bind the next reconciliation-status write to an observed lifecycle version.

        Stage 1B.4: reconciliation decisions derived from a stale ownership snapshot
        must not overwrite a decision written after a newer lifecycle transition.
        The guard is thread-local (like ``atomic_write``), so one store instance can
        safely serve multiple workers. The previous guard is restored on exit; no
        retry or timing behaviour is introduced.
        """
        previous = getattr(self._tx_state, 'recon_version', None)
        self._tx_state.recon_version = expected_version
        try:
            yield
        finally:
            self._tx_state.recon_version = previous

    def update_reconciliation_status(self, ownership_record_id: str, status: str) -> bool:
        """Persist a reconciliation decision; return False when a version guard misses.

        Unguarded legacy callers keep the original behaviour and receive ``True`` on a
        successful write. A guard miss is a conflict, not a persistence failure.
        """
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

    # ------------------------------------------------------------------
    # Canonical schema-v1 policy body persistence and trusted read-back
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_policy_version(policy_version: Any) -> int:
        if isinstance(policy_version, bool) or not isinstance(policy_version, int) or policy_version < 0:
            raise BrokerDBCanonicalError('Invalid policy_version for canonical policy body', BrokerDBCanonicalError.INTEGRITY)
        return policy_version

    def store_canonical_policy_body(self, rec: Dict[str, Any]) -> str:
        """Persist a validated canonical schema-v1 policy body (mock-only, additive).

        Expects normalized rules and matching digests/bindings. Fails closed on
        validation or persistence errors; does not silently overwrite records.
        """
        if not isinstance(rec, dict):
            raise BrokerDBCanonicalError('Invalid canonical policy body record', BrokerDBCanonicalError.INTEGRITY)
        policy_id = str(rec.get('policy_id') or '')
        policy_version = self._normalize_policy_version(rec.get('policy_version'))
        ownership_record_id = str(rec.get('ownership_record_id') or '')
        schema_version = rec.get('schema_version') or RULE_SCHEMA_VERSION
        if schema_version != RULE_SCHEMA_VERSION:
            raise BrokerDBCanonicalError('Unsupported canonical policy schema version', BrokerDBCanonicalError.INTEGRITY)
        if not policy_id or not ownership_record_id:
            raise BrokerDBCanonicalError('Missing canonical policy body binding', BrokerDBCanonicalError.INTEGRITY)
        rules = rec.get('rules')
        required_families = rec.get('required_families')
        try:
            normalized_rules = validate_and_normalize_rules(rules, required_families=required_families)
        except Exception as e:
            raise BrokerDBCanonicalError(f'Invalid canonical policy body: {getattr(e, "message", str(e))}', BrokerDBCanonicalError.INTEGRITY)
        expected_crd = schema_compiled_rule_digest(normalized_rules)
        provided_crd = rec.get('compiled_rule_digest')
        if provided_crd is not None and str(provided_crd) != expected_crd:
            raise BrokerDBCanonicalError('Canonical policy body digest mismatch', BrokerDBCanonicalError.INTEGRITY)
        canonical_rules_json = json.dumps(normalized_rules, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        required_families_json = json.dumps(sorted({r['family'] for r in normalized_rules})) if required_families is None else json.dumps(list(required_families))
        body_id = str(rec.get('policy_body_id') or f"pb-{policy_id}-{policy_version}")
        conn = self._get_conn_fk()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('SELECT ownership_record_id, policy_id, policy_version, canonical_policy_digest, instance_id, network_id FROM controller_ownership WHERE policy_id=? AND policy_version=?', (policy_id, policy_version))
            own = cur.fetchone()
            if not own:
                conn.rollback()
                raise BrokerDBCanonicalError('Ownership required for canonical policy body persistence', BrokerDBCanonicalError.OWNERSHIP)
            own = dict(own)
            if str(own.get('ownership_record_id')) != ownership_record_id:
                conn.rollback()
                raise BrokerDBCanonicalError('Ownership binding mismatch for canonical policy body', BrokerDBCanonicalError.OWNERSHIP)
            # Bind digest to authoritative ownership digest when present.
            own_digest = own.get('canonical_policy_digest')
            if own_digest and str(own_digest) != str(rec.get('canonical_policy_digest') or rec.get('compiled_rule_digest') or expected_crd):
                # Allow schema-v1 cases where ownership stores compiled rule digest as canonical alias.
                if str(own_digest) != expected_crd:
                    conn.rollback()
                    raise BrokerDBCanonicalError('Ownership digest mismatch for canonical policy body', BrokerDBCanonicalError.OWNERSHIP)
            # Stage 1B.6: target only the durable single-body UNIQUE index. A
            # PRIMARY KEY (policy_body_id) or FK/CHECK violation is a genuine
            # integrity failure and is not converted into an idempotent race.
            cur.execute('''INSERT INTO controller_policy_bodies
                (policy_body_id, ownership_record_id, policy_id, policy_version, schema_version,
                 canonical_rules_json, required_families_json, compiled_rule_digest, canonical_policy_digest,
                 controller_identity, request_id, operation_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(policy_id, policy_version) DO NOTHING''',
                (
                    body_id, ownership_record_id, policy_id, policy_version, schema_version,
                    canonical_rules_json, required_families_json, expected_crd,
                    str(rec.get('canonical_policy_digest') or own_digest or expected_crd),
                    rec.get('controller_identity'), rec.get('request_id'), rec.get('operation_id'),
                ))
            if cur.rowcount == 0:
                raise BrokerDBCanonicalBodyConflict(policy_id, policy_version)
            conn.commit()
            return body_id
        except (BrokerDBCanonicalBodyConflict, BrokerDBError):
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBCanonicalError(f'Failed to store canonical policy body: {e}', BrokerDBCanonicalError.PERSISTENCE)
        finally:
            conn.close()

    def _validate_existing_canonical_policy_body(self, rec: Dict[str, Any], existing: Dict[str, Any]) -> str:
        """Validate a persisted canonical body against requested bindings; fail closed."""
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
                raise BrokerDBCanonicalError('Canonical policy body digest mismatch', BrokerDBCanonicalError.INTEGRITY)
        return existing.get('policy_body_id')

    def ensure_canonical_policy_body(self, rec: Dict[str, Any]) -> str | None:
        """Idempotently ensure canonical policy body exists and matches; return body id or None if absent/not applicable.

        Stage 1B.4: a concurrent writer may win the single-body UNIQUE race after
        this caller observed absence. Resolve that specific idempotent conflict by
        validating the durable winner, instead of reporting a persistence failure.
        Genuine storage failures and mismatches still raise BrokerDBError.
        """
        pid = str(rec.get('policy_id') or '')
        pver = rec.get('policy_version')
        try:
            existing = self.get_canonical_policy_body(pid, pver)
        except BrokerDBError:
            # SR-08: a failed trusted read is never evidence of absence.
            raise
        except Exception as e:
            raise BrokerDBError(f'Canonical policy body pre-read failed: {e}') from e
        if existing:
            return self._validate_existing_canonical_policy_body(rec, existing)
        try:
            return self.store_canonical_policy_body(rec)
        except BrokerDBCanonicalBodyConflict:
            # SR-07: only the targeted single-body UNIQUE conflict is idempotent.
            # Resolve the durable winner, then validate it against this request.
            winner = self.get_canonical_policy_body(pid, pver)
            if not winner:
                raise BrokerDBError('Canonical policy body conflict winner not found')
            return self._validate_existing_canonical_policy_body(rec, winner)

    def get_canonical_policy_body(self, policy_id: str, policy_version: int):
        rows = self._query_dicts(
            'SELECT * FROM controller_policy_bodies WHERE policy_id=? AND policy_version=?',
            (policy_id, policy_version),
        )
        if not rows:
            return None
        return rows[0]

    def read_trusted_canonical_policy_body(
        self,
        policy_id: str,
        policy_version: Any,
        *,
        expected_owner_id: str | None = None,
        expected_ownership_record_id: str | None = None,
        expected_digest: str | None = None,
        expected_compiled_rule_digest: str | None = None,
        require_schema_v1: bool = True,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Trusted canonical read-back: load, bind, validate, and recompute digest.

        Returns (ownership_record, canonical_body_info). Fails closed on any
        corruption, mismatch, unsupported schema, or missing binding.
        """
        policy_version_i = self._normalize_policy_version(policy_version)
        ownership = self.get_by_policy(str(policy_id), policy_version_i)
        if not ownership:
            raise BrokerDBCanonicalError('Canonical policy body ownership not found', BrokerDBCanonicalError.OWNERSHIP)
        body = self.get_canonical_policy_body(str(policy_id), policy_version_i)
        if not body:
            raise BrokerDBCanonicalError('Canonical policy body not found', BrokerDBCanonicalError.INTEGRITY)
        if str(body.get('ownership_record_id') or '') != str(ownership.get('ownership_record_id') or ''):
            raise BrokerDBCanonicalError('Canonical policy body ownership binding mismatch', BrokerDBCanonicalError.OWNERSHIP)
        if expected_ownership_record_id and str(expected_ownership_record_id) != str(ownership.get('ownership_record_id') or ''):
            raise BrokerDBCanonicalError('Canonical policy body ownership record mismatch', BrokerDBCanonicalError.OWNERSHIP)
        if expected_owner_id and str(expected_owner_id) != str(ownership.get('instance_id') or ''):
            raise BrokerDBCanonicalError('Canonical policy body owner mismatch', BrokerDBCanonicalError.OWNERSHIP)
        schema_version = body.get('schema_version')
        if require_schema_v1 and schema_version != RULE_SCHEMA_VERSION:
            raise BrokerDBCanonicalError('Unsupported canonical policy schema version', BrokerDBCanonicalError.INTEGRITY)
        raw_rules = body.get('canonical_rules_json')
        if not isinstance(raw_rules, str) or raw_rules == '':
            raise BrokerDBCanonicalError('Missing canonical policy body', BrokerDBCanonicalError.INTEGRITY)
        try:
            parsed_rules = json.loads(raw_rules)
        except Exception:
            raise BrokerDBCanonicalError('Corrupt canonical policy body JSON', BrokerDBCanonicalError.INTEGRITY)
        try:
            rf = body.get('required_families_json')
            required_families = json.loads(rf) if isinstance(rf, str) and rf else None
        except Exception:
            raise BrokerDBCanonicalError('Corrupt canonical policy required_families', BrokerDBCanonicalError.INTEGRITY)
        try:
            normalized_rules = validate_and_normalize_rules(parsed_rules, required_families=required_families)
        except Exception as e:
            raise BrokerDBCanonicalError(f'Invalid canonical policy body: {getattr(e, "message", str(e))}', BrokerDBCanonicalError.INTEGRITY)
        recomputed_crd = schema_compiled_rule_digest(normalized_rules)
        stored_crd = body.get('compiled_rule_digest')
        if not isinstance(stored_crd, str) or stored_crd != recomputed_crd:
            raise BrokerDBCanonicalError('Canonical policy body digest mismatch', BrokerDBCanonicalError.INTEGRITY)
        own_digest = ownership.get('canonical_policy_digest')
        if own_digest and str(own_digest) not in (stored_crd, str(body.get('canonical_policy_digest') or stored_crd)):
            raise BrokerDBCanonicalError('Canonical policy body ownership digest mismatch', BrokerDBCanonicalError.OWNERSHIP)
        if expected_digest and str(expected_digest) not in (stored_crd, str(body.get('canonical_policy_digest') or stored_crd), str(own_digest or stored_crd)):
            raise BrokerDBCanonicalError('Canonical policy body digest mismatch', BrokerDBCanonicalError.INTEGRITY)
        if expected_compiled_rule_digest and str(expected_compiled_rule_digest) != stored_crd:
            raise BrokerDBCanonicalError('Canonical policy body compiled digest mismatch', BrokerDBCanonicalError.INTEGRITY)
        body_info = {
            'ownership_record_id': ownership.get('ownership_record_id'),
            'policy_id': str(policy_id),
            'policy_version': policy_version_i,
            'schema_version': schema_version,
            'rules': normalized_rules,
            'required_families': required_families or sorted({r['family'] for r in normalized_rules}),
            'compiled_rule_digest': stored_crd,
            'canonical_policy_digest': body.get('canonical_policy_digest') or own_digest or stored_crd,
        }
        return ownership, body_info
