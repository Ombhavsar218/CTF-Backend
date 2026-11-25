import json
import os
from datetime import datetime
from typing import Optional

from .db import BrokerDB, BrokerDBError
from .ownership import OwnershipRecord


class PersistentOwnershipStore:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.environ.get('BROKER_DB_PATH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'broker.db')
            db_path = os.path.normpath(db_path)
        self.db = BrokerDB(db_path)

    def record_creation(self, container_id: str, instance_id: str, challenge_image_id: str,
                        labels=None, owner_identity: str = "flaghunt-manager",
                        image_digest: str = "", request_id: str = "", idempotency_key_hash: str = "") -> OwnershipRecord:
        labels = labels or {}
        conn = self.db._get_conn()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            # Check if exists
            cur.execute('SELECT container_id FROM ownership WHERE container_id = ? AND lifecycle_state = "active"', (container_id,))
            if cur.fetchone():
                conn.rollback()
                raise PermissionError("Container already exists")
            cur.execute('''INSERT INTO ownership (container_id, owner_identity, challenge_id, image_digest, labels_json, request_id, idempotency_key_hash, lifecycle_state)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'active')''',
                        (container_id, owner_identity, challenge_image_id, image_digest, json.dumps(labels), request_id, idempotency_key_hash))
            cur.execute('INSERT INTO ownership_history (container_id, event, details_json) VALUES (?, ?, ?)',
                        (container_id, 'created', json.dumps({'instance_id': instance_id})))
            conn.commit()
        except PermissionError:
            raise
        except Exception as e:
            conn.rollback()
            raise BrokerDBError(f"Failed to record ownership: {e}")
        finally:
            conn.close()
        return OwnershipRecord(container_id=container_id, instance_id=str(instance_id), challenge_image_id=challenge_image_id, owner=owner_identity, managed=True, labels=labels)

    def verify(self, container_id: str, owner: str = "flaghunt-manager") -> OwnershipRecord:
        rows = self.db.query('SELECT * FROM ownership WHERE container_id = ?', (container_id,))
        if not rows:
            raise PermissionError("Container not owned by this manager")
        row = rows[0]
        if row['lifecycle_state'] != 'active':
            raise PermissionError("Container not owned by this manager")
        if row['owner_identity'] != owner:
            raise PermissionError("Container not owned by this manager")
        labels = {}
        try:
            if row['labels_json']:
                labels = json.loads(row['labels_json'])
        except Exception:
            labels = {}
        return OwnershipRecord(container_id=container_id, instance_id=labels.get('flaghunt.manager.instance_id', ''), challenge_image_id=row['challenge_id'] or '', owner=row['owner_identity'], managed=True, labels=labels)

    def exists(self, container_id: str) -> bool:
        try:
            rows = self.db.query('SELECT lifecycle_state FROM ownership WHERE container_id = ?', (container_id,))
            if not rows:
                return False
            return rows[0]['lifecycle_state'] == 'active'
        except Exception:
            return False

    def get(self, container_id: str):
        try:
            rows = self.db.query('SELECT * FROM ownership WHERE container_id = ?', (container_id,))
            if not rows:
                return None
            row = rows[0]
            labels = {}
            try:
                if row['labels_json']:
                    labels = json.loads(row['labels_json'])
            except Exception:
                labels = {}
            return OwnershipRecord(container_id=container_id, instance_id=labels.get('flaghunt.manager.instance_id', ''), challenge_image_id=row['challenge_id'] or '', owner=row['owner_identity'], managed=(row['lifecycle_state'] == 'active'), labels=labels)
        except Exception:
            return None

    def remove(self, container_id: str, owner: str = "flaghunt-manager") -> bool:
        conn = self.db._get_conn()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('SELECT owner_identity, lifecycle_state FROM ownership WHERE container_id = ?', (container_id,))
            row = cur.fetchone()
            if not row:
                conn.commit()
                return False  # idempotent
            if row['owner_identity'] != owner:
                conn.rollback()
                raise PermissionError("Container not owned by this manager")
            if row['lifecycle_state'] != 'active':
                conn.commit()
                return False
            cur.execute("UPDATE ownership SET lifecycle_state = 'removed', removed_at = CURRENT_TIMESTAMP WHERE container_id = ?", (container_id,))
            cur.execute('INSERT INTO ownership_history (container_id, event) VALUES (?, ?)', (container_id, 'removed'))
            conn.commit()
            return True
        except PermissionError:
            raise
        except Exception as e:
            conn.rollback()
            raise BrokerDBError(f"Failed to remove ownership: {e}")
        finally:
            conn.close()


def create_persistent_store(db_path: str | None = None):
    try:
        return PersistentOwnershipStore(db_path)
    except Exception:
        raise
