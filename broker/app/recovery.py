import json
import os
from typing import Dict, Any, Optional

from .db import BrokerDB, BrokerDBError


class OrphanRecord:
    def __init__(self, container_id: str, instance_id: str, challenge_image_id: str, reason: str, request_id: str = "", cleanup_status: str = "unconfirmed"):
        self.container_id = container_id
        self.instance_id = instance_id
        self.challenge_image_id = challenge_image_id
        self.reason = reason
        self.request_id = request_id
        self.cleanup_status = cleanup_status


class OrphanRegistry:
    def __init__(self, db_path: Optional[str] = None):
        self._orphans: Dict[str, OrphanRecord] = {}
        if db_path is None:
            db_path = os.environ.get('BROKER_RECOVERY_DB_PATH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'broker_recovery.db')
            db_path = os.path.normpath(db_path)
        # Fail closed: an orphan registry that cannot persist is not safe to
        # operate, because unresolved records could be silently lost on restart.
        self.db = BrokerDB(db_path)

    def mark_orphan(self, container_id: str, instance_id: str, challenge_image_id: str, reason: str, request_id: str = "") -> OrphanRecord:
        if container_id in self._orphans:
            return self._orphans[container_id]
        rec = OrphanRecord(container_id=container_id, instance_id=instance_id, challenge_image_id=challenge_image_id, reason=reason, request_id=request_id)
        self._orphans[container_id] = rec
        db_error = None
        try:
            conn = self.db._get_conn()
            try:
                cur = conn.cursor()
                cur.execute('BEGIN IMMEDIATE')
                cur.execute('INSERT OR IGNORE INTO orphan_recovery (container_id, instance_id, challenge_id, request_id, reason, cleanup_status) VALUES (?, ?, ?, ?, ?, "unconfirmed")',
                            (container_id, str(instance_id), challenge_image_id, request_id, reason))
                conn.commit()
            except Exception as e:
                db_error = e
                conn.rollback()
            finally:
                conn.close()
        except Exception as e:
            db_error = e
        if db_error is not None:
            # Keep the in-process record (callers still see an unresolved
            # orphan) but surface the durability failure instead of hiding it.
            raise BrokerDBError(f"Orphan persistence failed: {db_error}")
        return rec

    def get(self, container_id: str):
        if container_id in self._orphans:
            return self._orphans[container_id]
        if self.db:
            try:
                rows = self.db.query('SELECT * FROM orphan_recovery WHERE container_id = ?', (container_id,))
                if rows:
                    row = rows[0]
                    rec = OrphanRecord(container_id=row['container_id'], instance_id=row['instance_id'] or '', challenge_image_id=row['challenge_id'] or '', reason=row['reason'] or '', request_id=row['request_id'] or '', cleanup_status=row['cleanup_status'] or 'unconfirmed')
                    self._orphans[container_id] = rec
                    return rec
            except Exception:
                pass
        return None

    def is_orphan(self, container_id: str) -> bool:
        return self.get(container_id) is not None

    def confirm_cleanup(self, container_id: str):
        if self.db:
            try:
                conn = self.db._get_conn()
                try:
                    cur = conn.cursor()
                    cur.execute("UPDATE orphan_recovery SET cleanup_status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP WHERE container_id = ?", (container_id,))
                    conn.commit()
                except Exception:
                    conn.rollback()
                finally:
                    conn.close()
            except Exception:
                pass
        if container_id in self._orphans:
            self._orphans[container_id].cleanup_status = 'confirmed'

    def pending(self):
        """Return unresolved orphan records (durable, restart-safe)."""
        results = []
        seen = set()
        if self.db:
            try:
                rows = self.db.query("SELECT * FROM orphan_recovery WHERE cleanup_status != 'confirmed'")
                for row in rows:
                    rec = OrphanRecord(
                        container_id=row['container_id'],
                        instance_id=row['instance_id'] or '',
                        challenge_image_id=row['challenge_id'] or '',
                        reason=row['reason'] or '',
                        request_id=row['request_id'] or '',
                        cleanup_status=row['cleanup_status'] or 'unconfirmed',
                    )
                    results.append(rec)
                    seen.add(rec.container_id)
            except Exception:
                pass
        for cid, rec in self._orphans.items():
            if cid not in seen and rec.cleanup_status != 'confirmed':
                results.append(rec)
        return results

    def reconcile(self, container_id: str, remover) -> bool:
        """Controlled reconciliation for a single orphan.

        Trust boundary: only containers that already exist in the durable orphan
        registry may be reconciled. An arbitrary/untrusted external container ID
        is refused before any removal callback is invoked. Cleanup is only marked
        confirmed after the remover reports positive success.
        """
        record = self.get(container_id)
        if record is None:
            raise PermissionError("Unknown orphan container")
        if record.cleanup_status == 'confirmed':
            return True
        try:
            remover(container_id)
        except Exception:
            return False
        self.confirm_cleanup(container_id)
        return True

    def clear(self):
        self._orphans.clear()


orphan_registry = OrphanRegistry()
