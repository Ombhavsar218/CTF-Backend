import json
import os
import uuid
from typing import Any, Dict, Optional

from .db import BrokerDB, BrokerDBError


class NetworkOwnershipRecord:
    def __init__(self, network_id: str, instance_id: str, challenge_id: str = "", owner_identity: str = "flaghunt-manager",
                 lifecycle_state: str = "active", broker_network_id: str = "", network_name: str = "",
                 cleanup_status: str = "confirmed"):
        self.network_id = network_id
        self.instance_id = instance_id
        self.challenge_id = challenge_id
        self.owner_identity = owner_identity
        self.lifecycle_state = lifecycle_state
        self.broker_network_id = broker_network_id or network_id
        self.network_name = network_name
        self.cleanup_status = cleanup_status


class PersistentNetworkOwnershipStore:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.environ.get('BROKER_DB_PATH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'broker.db')
            db_path = os.path.normpath(db_path)
        self.db = BrokerDB(db_path)

    def generate_network_id(self) -> str:
        return f"net-{uuid.uuid4().hex}"

    def record_creation(self, network_id: str, instance_id: str, challenge_id: str = "",
                        owner_identity: str = "flaghunt-manager", network_name: str = "",
                        subnet_info: Optional[Dict[str, Any]] = None) -> NetworkOwnershipRecord:
        if not network_id:
            raise BrokerDBError("Network ID required")
        conn = self.db._get_conn()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('SELECT lifecycle_state FROM network_ownership WHERE network_id = ?', (network_id,))
            row = cur.fetchone()
            if row and row['lifecycle_state'] == 'active':
                conn.rollback()
                raise PermissionError("Network already exists")
            if row and row['lifecycle_state'] == 'removed':
                cur.execute("DELETE FROM network_ownership WHERE network_id = ?", (network_id,))
            cur.execute('''INSERT INTO network_ownership 
                (network_id, broker_network_id, instance_id, challenge_id, owner_identity, lifecycle_state, network_name, subnet_info, cleanup_status, cleanup_confirmed, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 'confirmed', 1, CURRENT_TIMESTAMP)''',
                (network_id, network_id, str(instance_id), challenge_id, owner_identity, network_name, json.dumps(subnet_info or {})))
            conn.commit()
        except PermissionError:
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBError(f"Failed to record network ownership: {e}")
        finally:
            conn.close()
        return NetworkOwnershipRecord(network_id=network_id, instance_id=instance_id, challenge_id=challenge_id,
                                      owner_identity=owner_identity, broker_network_id=network_id, network_name=network_name)

    def verify(self, network_id: str, owner: str = "flaghunt-manager") -> NetworkOwnershipRecord:
        rows = self.db.query('SELECT * FROM network_ownership WHERE network_id = ?', (network_id,))
        if not rows:
            raise PermissionError("Network not owned by this broker")
        row = rows[0]
        if row['lifecycle_state'] != 'active':
            raise PermissionError("Network not owned by this broker")
        if row['owner_identity'] != owner:
            raise PermissionError("Network not owned by this broker")
        return NetworkOwnershipRecord(network_id=row['network_id'], instance_id=row['instance_id'] or '',
                                      challenge_id=row['challenge_id'] or '', owner_identity=row['owner_identity'],
                                      lifecycle_state=row['lifecycle_state'], broker_network_id=row['broker_network_id'] or row['network_id'],
                                      network_name=row['network_name'] or '', cleanup_status=row['cleanup_status'] or 'confirmed')

    def exists(self, network_id: str) -> bool:
        try:
            rows = self.db.query('SELECT lifecycle_state FROM network_ownership WHERE network_id = ?', (network_id,))
            if not rows:
                return False
            return rows[0]['lifecycle_state'] == 'active'
        except Exception:
            return False

    def get(self, network_id: str):
        try:
            rows = self.db.query('SELECT * FROM network_ownership WHERE network_id = ?', (network_id,))
            if not rows:
                return None
            row = rows[0]
            return NetworkOwnershipRecord(network_id=row['network_id'], instance_id=row['instance_id'] or '',
                                          challenge_id=row['challenge_id'] or '', owner_identity=row['owner_identity'],
                                          lifecycle_state=row['lifecycle_state'], broker_network_id=row['broker_network_id'] or row['network_id'],
                                          network_name=row['network_name'] or '', cleanup_status=row['cleanup_status'] or 'confirmed')
        except Exception:
            return None

    def get_by_instance(self, instance_id: str):
        try:
            rows = self.db.query("SELECT * FROM network_ownership WHERE instance_id = ? AND lifecycle_state = 'active'", (str(instance_id),))
            results = []
            for row in rows:
                results.append(NetworkOwnershipRecord(network_id=row['network_id'], instance_id=row['instance_id'] or '',
                                                       challenge_id=row['challenge_id'] or '', owner_identity=row['owner_identity'],
                                                       lifecycle_state=row['lifecycle_state'], broker_network_id=row['broker_network_id'] or row['network_id'],
                                                       network_name=row['network_name'] or '', cleanup_status=row['cleanup_status'] or 'confirmed'))
            return results
        except Exception:
            return []

    def remove(self, network_id: str, owner: str = "flaghunt-manager") -> bool:
        conn = self.db._get_conn()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('SELECT owner_identity, lifecycle_state FROM network_ownership WHERE network_id = ?', (network_id,))
            row = cur.fetchone()
            if not row:
                conn.commit()
                return False
            if row['owner_identity'] != owner:
                conn.rollback()
                raise PermissionError("Network not owned by this broker")
            if row['lifecycle_state'] != 'active':
                conn.commit()
                return False
            cur.execute("UPDATE network_ownership SET lifecycle_state = 'removed', removed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE network_id = ?", (network_id,))
            conn.commit()
            return True
        except PermissionError:
            raise
        except Exception as e:
            conn.rollback()
            raise BrokerDBError(f"Failed to remove network ownership: {e}")
        finally:
            conn.close()
