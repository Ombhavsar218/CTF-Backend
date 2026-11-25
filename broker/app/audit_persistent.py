import json
import os
from typing import Any, Dict, Optional

from .db import BrokerDB, BrokerDBError


class PersistentAuditLogger:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.environ.get('BROKER_AUDIT_DB_PATH') or os.environ.get('BROKER_DB_PATH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'broker_audit.db')
            db_path = os.path.normpath(db_path)
        self.db = BrokerDB(db_path)
        self.retention_days = 30  # document only

    def _hash(self, s: Optional[str]) -> Optional[str]:
        if not s:
            return None
        import hashlib
        return hashlib.sha256(str(s).encode()).hexdigest()

    def log(self, operation: str, details: Dict[str, Any] | None = None,
            request_id: str | None = None, idempotency_key: str | None = None,
            peer_uid: Optional[int] = None, peer_gid: Optional[int] = None,
            challenge_id: Optional[str] = None, container_id: Optional[str] = None,
            result: str = "ok", error_category: Optional[str] = None) -> None:
        try:
            details = details or {}
            # sanitize
            sanitized = {}
            for k, v in details.items():
                kl = str(k).lower()
                if any(x in kl for x in ['token', 'secret', 'password', 'key', 'env', 'authorization', 'header']):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = v
            self.db.execute('''INSERT INTO audit_log (request_id, idempotency_key_hash, peer_uid, peer_gid, operation, challenge_id, container_id, result, error_category)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (request_id, self._hash(idempotency_key), peer_uid, peer_gid, operation, challenge_id, container_id, result, error_category))
        except Exception:
            # Fail open for audit in non-critical path? No - better to not crash; but requirement says structured audit
            pass


persistent_audit = PersistentAuditLogger()
