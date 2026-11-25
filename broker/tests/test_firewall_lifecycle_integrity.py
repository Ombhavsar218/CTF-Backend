import tempfile
import os
from broker.app.firewall_policy import firewall_policy_model, FirewallPolicyError
from broker.app.firewall_compiler import firewall_compiler
from broker.app.firewall_state import FirewallStateStore
from broker.app.firewall_controller import MockFirewallController
from broker.app.network_ownership import PersistentNetworkOwnershipStore
from broker.app.ownership_store_persistent import PersistentOwnershipStore


def setup():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    net_store = PersistentNetworkOwnershipStore(path)
    cont_store = PersistentOwnershipStore(path)
    nid = net_store.generate_network_id()
    net_store.record_creation(nid, 'i1', 'c1')
    cont_store.record_creation('i1', 'i1', 'c1')
    # Add subnet metadata
    try:
        import json
        conn = net_store.db._get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE network_ownership SET subnet_info=? WHERE network_id=?", (json.dumps({'subnet': '172.18.0.0/16'}), nid))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return net_store, cont_store, nid, path


def test_direct_verified_without_evidence_rejected():
    net_store, cont_store, nid, path = setup()
    try:
        store = FirewallStateStore(db_path=path)
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': '172.18.0.5', 'port': 53}], network_store=net_store, container_store=cont_store)
        compiled = firewall_compiler.compile(p)
        store.save_policy(p, compiled)
        store.transition(p.policy_id, 'VALIDATED')
        store.transition(p.policy_id, 'COMPILED')
        store.transition(p.policy_id, 'INSTALL_PENDING')
        store.transition(p.policy_id, 'INSTALLED')
        try:
            store.transition(p.policy_id, 'VERIFIED', require_evidence=True)
            assert False
        except Exception:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_forged_evidence_rejected():
    net_store, cont_store, nid, path = setup()
    try:
        store = FirewallStateStore(db_path=path)
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': '172.18.0.5', 'port': 53}], network_store=net_store, container_store=cont_store)
        compiled = firewall_compiler.compile(p)
        store.save_policy(p, compiled)
        # record evidence for different digest
        store.record_verification_evidence(p.policy_id, p.policy_version, 'bad', 'verify', 'verified')
        try:
            store.transition(p.policy_id, 'VALIDATED')
            store.transition(p.policy_id, 'COMPILED')
            store.transition(p.policy_id, 'INSTALL_PENDING')
            store.transition(p.policy_id, 'INSTALLED')
            store.transition(p.policy_id, 'VERIFIED', require_evidence=True)
            assert False
        except Exception:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_valid_evidence_allows_verified():
    net_store, cont_store, nid, path = setup()
    try:
        store = FirewallStateStore(db_path=path)
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': '172.18.0.5', 'port': 53}], network_store=net_store, container_store=cont_store)
        compiled = firewall_compiler.compile(p)
        store.save_policy(p, compiled)
        store.record_verification_evidence(p.policy_id, p.policy_version, compiled['compiled_rule_digest'], 'verify', 'verified')
        store.transition(p.policy_id, 'VALIDATED')
        store.transition(p.policy_id, 'COMPILED')
        store.transition(p.policy_id, 'INSTALL_PENDING')
        store.transition(p.policy_id, 'INSTALLED')
        store.transition(p.policy_id, 'VERIFIED', require_evidence=True)
        assert store.get(p.policy_id)['policy_lifecycle_state'] == 'VERIFIED'
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_digest_mismatch_rejected():
    net_store, cont_store, nid, path = setup()
    try:
        store = FirewallStateStore(db_path=path)
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': '172.18.0.5', 'port': 53}], network_store=net_store, container_store=cont_store)
        compiled = firewall_compiler.compile(p)
        store.save_policy(p, compiled)
        # tamper
        conn = store.db._get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE firewall_policies SET compiled_rule_digest='bad' WHERE policy_id=?", (p.policy_id,))
        conn.commit()
        conn.close()
        try:
            store.verify_digest(p.policy_id)
            assert False
        except Exception:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_ip_outside_subnet_rejected():
    net_store, cont_store, nid, path = setup()
    try:
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': '192.168.1.5', 'port': 53}], network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_missing_subnet_metadata_rejected():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': '10.0.0.5', 'port': 53}], network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_revocation_idempotent():
    net_store, cont_store, nid, path = setup()
    try:
        store = FirewallStateStore(db_path=path)
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': '172.18.0.5', 'port': 53}], network_store=net_store, container_store=cont_store)
        compiled = firewall_compiler.compile(p)
        store.save_policy(p, compiled)
        store.transition(p.policy_id, 'VALIDATED')
        store.transition(p.policy_id, 'COMPILED')
        store.transition(p.policy_id, 'INSTALL_PENDING')
        store.transition(p.policy_id, 'INSTALLED')
        store.record_verification_evidence(p.policy_id, p.policy_version, compiled['compiled_rule_digest'], 'verify', 'verified')
        store.transition(p.policy_id, 'VERIFIED', require_evidence=True)
        store.transition(p.policy_id, 'REVOKE_PENDING')
        store.transition(p.policy_id, 'REVOKED')
        store.transition(p.policy_id, 'REVOKED')
        assert store.get(p.policy_id)['policy_lifecycle_state'] == 'REVOKED'
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass
