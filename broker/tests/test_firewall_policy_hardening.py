import tempfile
import os
from broker.app.firewall_policy import firewall_policy_model, FirewallPolicyError
from broker.app.firewall_compiler import firewall_compiler
from broker.app.network_ownership import PersistentNetworkOwnershipStore
from broker.app.ownership_store_persistent import PersistentOwnershipStore


def test_arbitrary_caller_network_id_rejected():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4',
                                                [{'network_id': 'evil', 'ip': '10.0.0.5', 'port': 80}],
                                                network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_network_instance_mismatch():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        try:
            import json
            conn = net_store.db._get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE network_ownership SET subnet_info=? WHERE network_id=?", (json.dumps({'subnet': '10.0.0.0/24'}), nid))
            conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            firewall_policy_model.create_policy('i2', 'broker', 'egress', 'ipv4',
                                                [{'network_id': nid, 'ip': '10.0.0.5', 'port': 80}],
                                                network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_ipv4_mapped_ipv6_rejected():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        try:
            import json
            conn = net_store.db._get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE network_ownership SET subnet_info=? WHERE network_id=?", (json.dumps({'subnet': '10.0.0.0/24'}), nid))
            conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4',
                                                [{'network_id': nid, 'ip': '::ffff:192.168.1.1', 'port': 80}],
                                                network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_unrestricted_cidr_rejected():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        try:
            import json
            conn = net_store.db._get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE network_ownership SET subnet_info=? WHERE network_id=?", (json.dumps({'subnet': '10.0.0.0/24'}), nid))
            conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4',
                                                [{'network_id': nid, 'subnet': '0.0.0.0/0', 'port': 80}],
                                                network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv6',
                                                [{'network_id': nid, 'subnet': '::/0', 'port': 80}],
                                                network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_ip_version_mismatch():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        try:
            import json
            conn = net_store.db._get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE network_ownership SET subnet_info=? WHERE network_id=?", (json.dumps({'subnet': '10.0.0.0/24'}), nid))
            conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4',
                                                [{'network_id': nid, 'ip': '2001:db8::1', 'port': 80}],
                                                network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_both_rejected():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        try:
            import json
            conn = net_store.db._get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE network_ownership SET subnet_info=? WHERE network_id=?", (json.dumps({'subnet': '10.0.0.0/24'}), nid))
            conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'both',
                                                [{'network_id': nid, 'ip': '10.0.0.5', 'port': 80}],
                                                network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_unverified_policy_to_compiler_rejected():
    from broker.app.firewall_policy import FirewallPolicy, FirewallPolicyTarget
    p = FirewallPolicy('p1', 'i1', 'broker', 'egress', 'ipv4',
                       [FirewallPolicyTarget('n1', 'i1', ip='10.0.0.5', port=80, verified=False)],
                       ownership_verified=False)
    try:
        firewall_compiler.compile(p)
        assert False
    except Exception:
        pass


def test_proxy_source_rejected():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        try:
            import json
            conn = net_store.db._get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE network_ownership SET subnet_info=? WHERE network_id=?", (json.dumps({'subnet': '10.0.0.0/24'}), nid))
            conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            firewall_policy_model.create_policy('i1', 'proxy', 'egress', 'ipv4',
                                                [{'network_id': nid, 'ip': '10.0.0.5', 'port': 80}],
                                                network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_valid_challenge_network_private_ip_works():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        try:
            import json
            conn = net_store.db._get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE network_ownership SET subnet_info=? WHERE network_id=?", (json.dumps({'subnet': '172.18.0.0/16'}), nid))
            conn.commit()
            conn.close()
        except Exception:
            pass
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4',
                                                [{'network_id': nid, 'ip': '172.18.0.5', 'port': 53}],
                                                network_store=net_store, container_store=cont_store)
        compiled = firewall_compiler.compile(p)
        assert compiled['rule_count'] == 1
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass
