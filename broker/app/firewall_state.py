import os
import json
import hashlib
from typing import Dict, Any, Optional, List

from .db import BrokerDB, BrokerDBError
from .firewall_policy import FirewallPolicy
from .firewall_compiler import firewall_compiler


class FirewallStateStore:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.environ.get('BROKER_DB_PATH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'broker.db')
            db_path = os.path.normpath(db_path)
        self.db = BrokerDB(db_path)

    def save_policy(self, policy: FirewallPolicy, compiled: Dict[str, Any]) -> str:
        conn = self.db._get_conn()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('SELECT policy_lifecycle_state, policy_version FROM firewall_policies WHERE policy_id = ?', (policy.policy_id,))
            row = cur.fetchone()
            if row and row['policy_lifecycle_state'] not in ('REVOKED',):
                conn.rollback()
                raise PermissionError("Policy exists")
            cur.execute('''INSERT OR REPLACE INTO firewall_policies
                (policy_id, policy_version, instance_id, network_ownership_id, challenge_id, compiled_rule_digest, compiled_rules_json,
                 policy_lifecycle_state, source_component, direction, ip_version, state, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (policy.policy_id, policy.policy_version, policy.instance_id, policy.network_ownership_id,
                 policy.challenge_id, compiled.get('compiled_rule_digest'), json.dumps(compiled.get('rules', [])),
                 policy.source_component, policy.direction, policy.ip_version, policy.state))
            conn.commit()
        except PermissionError:
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBError(f"Failed to save firewall policy: {e}")
        finally:
            conn.close()
        return policy.policy_id

    def get(self, policy_id: str):
        try:
            rows = self.db.query('SELECT * FROM firewall_policies WHERE policy_id = ?', (policy_id,))
            if not rows:
                return None
            return rows[0]
        except Exception:
            return None

    def recompute_digest(self, policy_id: str) -> str:
        row = self.get(policy_id)
        if not row:
            raise PermissionError("Unknown policy")
        rules = json.loads(row['compiled_rules_json'] or '[]')
        payload = firewall_compiler.canonical_serialize(rules)
        return hashlib.sha256(payload.encode()).hexdigest()

    def verify_digest(self, policy_id: str) -> bool:
        row = self.get(policy_id)
        if not row:
            raise PermissionError("Unknown policy")
        rules = json.loads(row['compiled_rules_json'] or '[]')
        payload = firewall_compiler.canonical_serialize(rules)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if digest != row['compiled_rule_digest']:
            raise PermissionError("Digest mismatch")
        return True

    def record_verification_evidence(self, policy_id: str, policy_version: int, compiled_digest: str, controller_operation: str, controller_result: str):
        conn = self.db._get_conn()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('INSERT OR REPLACE INTO firewall_verification_evidence (policy_id, policy_version, compiled_rule_digest, controller_operation, controller_result) VALUES (?, ?, ?, ?, ?)',
                        (policy_id, policy_version, compiled_digest, controller_operation, controller_result))
            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBError(f"Failed to record evidence: {e}")
        finally:
            conn.close()

    def has_valid_verification_evidence(self, policy_id: str, policy_version: int, compiled_digest: str) -> bool:
        try:
            rows = self.db.query('SELECT * FROM firewall_verification_evidence WHERE policy_id = ? AND policy_version = ? AND compiled_rule_digest = ? AND controller_result = "verified"',
                                 (policy_id, policy_version, compiled_digest))
            return len(rows) > 0
        except Exception:
            return False

    def transition(self, policy_id: str, new_state: str, owner_check: bool = True, controller_verified: bool = False, require_evidence: bool = False) -> bool:
        allowed = {
            'DRAFT': ['VALIDATED'],
            'VALIDATED': ['COMPILED'],
            'COMPILED': ['INSTALL_PENDING'],
            'INSTALL_PENDING': ['INSTALLED'],
            'INSTALLED': ['VERIFIED', 'REVOKE_PENDING'],
            'VERIFIED': ['REVOKE_PENDING'],
            'REVOKE_PENDING': ['REVOKED'],
            'REVOKED': ['REVOKED']
        }
        conn = self.db._get_conn()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute('SELECT policy_lifecycle_state, policy_version, compiled_rule_digest FROM firewall_policies WHERE policy_id = ?', (policy_id,))
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return False
            current = row['policy_lifecycle_state']
            if current == new_state:
                conn.commit()
                return True
            if new_state not in allowed.get(current, []):
                conn.rollback()
                raise PermissionError(f"Invalid transition {current}->{new_state}")
            if new_state == 'VERIFIED':
                if require_evidence:
                    if not self.has_valid_verification_evidence(policy_id, row['policy_version'], row['compiled_rule_digest']):
                        conn.rollback()
                        raise PermissionError("Positive controller verification required for VERIFIED state")
                elif not controller_verified:
                    conn.rollback()
                    raise PermissionError("Positive controller verification required for VERIFIED state")
                cur.execute("UPDATE firewall_policies SET policy_lifecycle_state=?, verification_timestamp=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE policy_id=?",
                            (new_state, policy_id))
            elif new_state == 'REVOKED':
                cur.execute("UPDATE firewall_policies SET policy_lifecycle_state=?, revocation_status='revoked', revoked_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE policy_id=?",
                            (new_state, policy_id))
            else:
                cur.execute("UPDATE firewall_policies SET policy_lifecycle_state=?, updated_at=CURRENT_TIMESTAMP WHERE policy_id=?",
                            (new_state, policy_id))
            conn.commit()
            return True
        except PermissionError:
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise BrokerDBError(f"Failed to transition: {e}")
        finally:
            conn.close()

    def list_by_instance(self, instance_id: str):
        try:
            return self.db.query("SELECT * FROM firewall_policies WHERE instance_id = ?", (str(instance_id),))
        except Exception:
            return []


firewall_state_store = FirewallStateStore()
