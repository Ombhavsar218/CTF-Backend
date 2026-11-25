import os
from typing import Dict, Any

from .db import BrokerDB, BrokerDBError


class NetworkOrphanRecord:
    def __init__(self, network_id: str, instance_id: str = "", challenge_id: str = "", reason: str = "", broker_network_id: str = "", cleanup_status: str = "unconfirmed"):
        self.network_id = network_id
        self.instance_id = instance_id
        self.challenge_id = challenge_id
        self.reason = reason
        self.broker_network_id = broker_network_id or network_id
        self.cleanup_status = cleanup_status


class NetworkOrphanRegistry:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.environ.get('BROKER_DB_PATH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'broker.db')
            db_path = os.path.normpath(db_path)
        self.db = BrokerDB(db_path)
        self._orphans: Dict[str, NetworkOrphanRecord] = {}

    def mark_orphan(self, network_id: str, instance_id: str = "", challenge_id: str = "", reason: str = "", broker_network_id: str = "") -> NetworkOrphanRecord:
        if network_id in self._orphans:
            return self._orphans[network_id]
        rec = NetworkOrphanRecord(network_id=network_id, instance_id=instance_id, challenge_id=challenge_id, reason=reason, broker_network_id=broker_network_id or network_id)
        self._orphans[network_id] = rec
        try:
            conn = self.db._get_conn()
            try:
                cur = conn.cursor()
                cur.execute('BEGIN IMMEDIATE')
                cur.execute('INSERT OR IGNORE INTO network_orphan_recovery (network_id, broker_network_id, instance_id, challenge_id, reason, cleanup_status) VALUES (?, ?, ?, ?, ?, "unconfirmed")',
                            (network_id, broker_network_id or network_id, str(instance_id), challenge_id, reason))
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise BrokerDBError(f"Network orphan persistence failed: {e}")
            finally:
                conn.close()
        except BrokerDBError:
            raise
        except Exception as e:
            raise BrokerDBError(f"Network orphan persistence failed: {e}")
        return rec

    def is_orphan(self, network_id: str) -> bool:
        return self.get(network_id) is not None

    def get(self, network_id: str):
        if network_id in self._orphans:
            return self._orphans[network_id]
        try:
            rows = self.db.query('SELECT * FROM network_orphan_recovery WHERE network_id = ?', (network_id,))
            if rows:
                row = rows[0]
                rec = NetworkOrphanRecord(network_id=row['network_id'], instance_id=row['instance_id'] or '',
                                          challenge_id=row['challenge_id'] or '', reason=row['reason'] or '',
                                          broker_network_id=row['broker_network_id'] or row['network_id'],
                                          cleanup_status=row['cleanup_status'] or 'unconfirmed')
                self._orphans[network_id] = rec
                return rec
        except Exception:
            pass
        return None

    def pending(self):
        results = []
        seen = set()
        try:
            rows = self.db.query("SELECT * FROM network_orphan_recovery WHERE cleanup_status != 'confirmed'")
            for row in rows:
                rec = NetworkOrphanRecord(network_id=row['network_id'], instance_id=row['instance_id'] or '',
                                          challenge_id=row['challenge_id'] or '', reason=row['reason'] or '',
                                          broker_network_id=row['broker_network_id'] or row['network_id'],
                                          cleanup_status=row['cleanup_status'] or 'unconfirmed')
                results.append(rec)
                seen.add(rec.network_id)
        except Exception:
            pass
        for nid, rec in self._orphans.items():
            if nid not in seen and rec.cleanup_status != 'confirmed':
                results.append(rec)
        return results

    def confirm_cleanup(self, network_id: str):
        try:
            conn = self.db._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("UPDATE network_orphan_recovery SET cleanup_status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP WHERE network_id = ?", (network_id,))
                conn.commit()
            except Exception:
                conn.rollback()
            finally:
                conn.close()
        except Exception:
            pass
        if network_id in self._orphans:
            self._orphans[network_id].cleanup_status = 'confirmed'

    def reconcile(self, network_id: str, remover) -> bool:
        record = self.get(network_id)
        if record is None:
            raise PermissionError("Unknown orphan network")
        if record.cleanup_status == 'confirmed':
            return True
        try:
            remover(network_id)
        except Exception:
            return False
        self.confirm_cleanup(network_id)
        return True

    def clear(self):
        self._orphans.clear()


network_orphan_registry = NetworkOrphanRegistry()
