import os
import sqlite3
import sys
from contextlib import contextmanager
from typing import Any, Optional


class BrokerDBError(Exception):
    pass


class BrokerDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_db_dir()
        self._init_schema()

    def _ensure_db_dir(self):
        try:
            d = os.path.dirname(os.path.abspath(self.db_path))
            if d:
                existed = os.path.isdir(d)
                os.makedirs(d, mode=0o750, exist_ok=True)
                # Only tighten permissions on a directory we created. Never
                # chmod a pre-existing (possibly shared) parent directory.
                if not existed:
                    try:
                        os.chmod(d, 0o750)
                    except Exception:
                        pass
        except Exception as e:
            raise BrokerDBError(f"DB directory error: {e}")

    def _secure_files(self):
        """Best-effort hardening of the DB file and SQLite sidecar files.

        Note: chmod is a no-op / limited on Windows. On POSIX this restricts the
        main DB and any WAL/SHM files to owner+group read/write.
        """
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            try:
                if os.path.exists(path):
                    os.chmod(path, 0o640)
            except Exception:
                # Never fail the operation because a sidecar could not be chmod'ed;
                # callers must still treat filesystem perms as deployment-owned.
                pass

    def _get_conn(self):
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            raise BrokerDBError(f"DB unavailable: {e}")

    @contextmanager
    def _init_guard(self):
        """Serialize schema initialization across processes for this DB path.

        Concurrent first-time DDL on a fresh SQLite database can fail with transient
        lock/schema-unavailable errors across spawned processes. Initialization is
        idempotent (IF NOT EXISTS), so a cross-process file lock makes it safe without
        changing schema/API semantics. Lock acquisition/filesystem failures are surfaced
        as storage/init errors (fail closed), not as idempotency/classification outcomes.
        """
        lock_path = self.db_path + '.initlock'
        try:
            lock_dir = os.path.dirname(os.path.abspath(lock_path))
            if lock_dir and not os.path.isdir(lock_dir):
                os.makedirs(lock_dir, mode=0o750, exist_ok=True)
            f = open(lock_path, 'a+b')
        except Exception as e:
            raise BrokerDBError(f"DB init lock unavailable: {e}")
        try:
            try:
                if sys.platform.startswith('win'):
                    import msvcrt
                    try:
                        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                    except OSError as e:
                        raise BrokerDBError(f"DB init lock failed: {e}")
                else:
                    import fcntl
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    except OSError as e:
                        raise BrokerDBError(f"DB init lock failed: {e}")
            except BrokerDBError:
                raise
            except Exception as e:
                raise BrokerDBError(f"DB init lock failed: {e}")
            try:
                yield
            finally:
                try:
                    if sys.platform.startswith('win'):
                        import msvcrt
                        try:
                            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                        except Exception:
                            pass
                    else:
                        import fcntl
                        try:
                            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        except Exception:
                            pass
                except Exception:
                    pass
        finally:
            try:
                f.close()
            except Exception:
                pass

    def _init_schema(self):
        with self._init_guard():
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute('PRAGMA journal_mode=WAL;')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS ownership (
                        container_id TEXT PRIMARY KEY,
                        owner_identity TEXT NOT NULL,
                        challenge_id TEXT,
                        image_digest TEXT,
                        labels_json TEXT,
                        request_id TEXT,
                        idempotency_key_hash TEXT,
                        lifecycle_state TEXT NOT NULL DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        removed_at TIMESTAMP,
                        cleanup_confirmed INTEGER DEFAULT 0
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS ownership_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        container_id TEXT NOT NULL,
                        event TEXT NOT NULL,
                        details_json TEXT,
                        event_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        request_id TEXT,
                        idempotency_key_hash TEXT,
                        peer_uid INTEGER,
                        peer_gid INTEGER,
                        operation TEXT NOT NULL,
                        challenge_id TEXT,
                        container_id TEXT,
                        result TEXT NOT NULL,
                        error_category TEXT
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS orphan_recovery (
                        container_id TEXT PRIMARY KEY,
                        instance_id TEXT,
                        challenge_id TEXT,
                        request_id TEXT,
                        reason TEXT NOT NULL,
                        cleanup_status TEXT NOT NULL DEFAULT 'unconfirmed',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        confirmed_at TIMESTAMP
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS network_ownership (
                        network_id TEXT PRIMARY KEY,
                        broker_network_id TEXT UNIQUE,
                        instance_id TEXT NOT NULL,
                        challenge_id TEXT,
                        owner_identity TEXT NOT NULL,
                        lifecycle_state TEXT NOT NULL DEFAULT 'active',
                        network_name TEXT,
                        subnet_info TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        removed_at TIMESTAMP,
                        cleanup_status TEXT NOT NULL DEFAULT 'confirmed',
                        cleanup_confirmed INTEGER DEFAULT 1
                    )
                ''')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_network_ownership_state ON network_ownership(lifecycle_state)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_network_ownership_instance ON network_ownership(instance_id)')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS network_orphan_recovery (
                        network_id TEXT PRIMARY KEY,
                        broker_network_id TEXT,
                        instance_id TEXT,
                        challenge_id TEXT,
                        reason TEXT NOT NULL,
                        cleanup_status TEXT NOT NULL DEFAULT 'unconfirmed',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        confirmed_at TIMESTAMP
                    )
                ''')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_network_orphan_status ON network_orphan_recovery(cleanup_status)')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS firewall_policies (
                        policy_id TEXT PRIMARY KEY,
                        policy_version INTEGER NOT NULL DEFAULT 1,
                        instance_id TEXT NOT NULL,
                        network_ownership_id TEXT,
                        challenge_id TEXT,
                        compiled_rule_digest TEXT,
                        compiled_rules_json TEXT,
                        policy_lifecycle_state TEXT NOT NULL DEFAULT 'DRAFT',
                        source_component TEXT,
                        direction TEXT,
                        ip_version TEXT,
                        state TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        verification_timestamp TIMESTAMP,
                        revocation_status TEXT DEFAULT 'none',
                        revoked_at TIMESTAMP
                    )
                ''')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_firewall_policy_instance ON firewall_policies(instance_id)')
                cur.execute('CREATE INDEX IF NOT EXISTS idx_firewall_policy_state ON firewall_policies(policy_lifecycle_state)')
                cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_firewall_policy_unique ON firewall_policies(instance_id, policy_version)')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS firewall_verification_evidence (
                        evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        policy_id TEXT NOT NULL,
                        policy_version INTEGER NOT NULL,
                        compiled_rule_digest TEXT NOT NULL,
                        controller_operation TEXT NOT NULL,
                        controller_result TEXT NOT NULL,
                        verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(policy_id, policy_version, compiled_rule_digest)
                    )
                ''')
                cur.execute('INSERT OR IGNORE INTO schema_version (version) VALUES (1)')
                conn.commit()
                self._secure_files()
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise BrokerDBError(f"Schema init failed: {e}")
            finally:
                conn.close()

    def execute(self, sql: str, params: tuple = ()):
        conn = None
        try:
            conn = self._get_conn()
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
                self._secure_files()

    def query(self, sql: str, params: tuple = ()):
        conn = None
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            return rows
        except BrokerDBError:
            raise
        except Exception as e:
            raise BrokerDBError(f"DB error: {e}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
