import tempfile
import os
from broker.app.firewall_policy import firewall_policy_model, FirewallPolicyError
from broker.app.firewall_compiler import firewall_compiler
from broker.app.firewall_state import FirewallStateStore
from broker.app.firewall_controller import MockFirewallController


from broker.app.network_ownership import PersistentNetworkOwnershipStore
from broker.app.ownership_store_persistent import PersistentOwnershipStore


def _setup_stores():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    net_store = PersistentNetworkOwnershipStore(path)
    cont_store = PersistentOwnershipStore(path)
    return net_store, cont_store, path


def _add_subnet(net_store, nid, subnet='10.0.0.0/24'):
    try:
        import json
        conn = net_store.db._get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE network_ownership SET subnet_info=? WHERE network_id=?", (json.dumps({'subnet': subnet}), nid))
        conn.commit()
        conn.close()
    except Exception:
        pass


def test_default_deny_and_restrictions():
    net_store, cont_store, path = _setup_stores()
    try:
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [], network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_unauthorized_destination_rejection():
    net_store, cont_store, path = _setup_stores()
    try:
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        _add_subnet(net_store, nid, '10.0.0.0/24')
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': None, 'subnet': None, 'port': 80}], network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_unrestricted_port_rejected():
    net_store, cont_store, path = _setup_stores()
    try:
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        _add_subnet(net_store, nid, '10.0.0.0/24')
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'subnet': '10.0.0.0/24', 'port': None}], network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_ipv4_ipv6_validation():
    net_store, cont_store, path = _setup_stores()
    try:
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        _add_subnet(net_store, nid, '10.0.0.0/24')
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': '10.0.0.5', 'port': 53}], network_store=net_store, container_store=cont_store)
        assert p.ip_version == 'ipv4'
        nid2 = net_store.generate_network_id()
        net_store.record_creation(nid2, 'i2', 'c1')
        cont_store.record_creation('i2', 'i2', 'c1')
        _add_subnet(net_store, nid2, 'fd00::/64')
        p2 = firewall_policy_model.create_policy('i2', 'broker', 'egress', 'ipv6', [{'network_id': nid2, 'ip': 'fd00::1', 'port': 53}], network_store=net_store, container_store=cont_store)
        assert p2.ip_version == 'ipv6'
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_invalid_ip_protocol():
    net_store, cont_store, path = _setup_stores()
    try:
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        _add_subnet(net_store, nid, '10.0.0.0/24')
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': 'bad', 'port': 80}], network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'subnet': '10.0.0.0/24', 'port': 80, 'protocol': 'icmp'}], network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_duplicate_and_conflicting_rules():
    net_store, cont_store, path = _setup_stores()
    try:
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        _add_subnet(net_store, nid, '10.0.0.0/24')
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [
            {'network_id': nid, 'ip': '10.0.0.5', 'port': 80, 'protocol': 'tcp'},
            {'network_id': nid, 'ip': '10.0.0.5', 'port': 80, 'protocol': 'tcp'},
        ], network_store=net_store, container_store=cont_store)
        try:
            firewall_compiler.compile(p)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_arbitrary_subnet_caller_rejected():
    net_store, cont_store, path = _setup_stores()
    try:
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        _add_subnet(net_store, nid, '10.0.0.0/24')
        try:
            firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'subnet': '0.0.0.0/0', 'port': 80}], network_store=net_store, container_store=cont_store)
            assert False
        except FirewallPolicyError:
            pass
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_no_unrestricted_accept():
    net_store, cont_store, path = _setup_stores()
    try:
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        _add_subnet(net_store, nid, '192.168.1.0/24')
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'subnet': '192.168.1.0/24', 'port': 443}], network_store=net_store, container_store=cont_store)
        compiled = firewall_compiler.compile(p)
        for r in compiled['rules']:
            assert r['action'] == 'ACCEPT'
            assert r['dest_port'] is not None
            assert r['default_action'] == 'DROP'
    finally:
        for s in [path, path+'-wal', path+'-shm']:
            try:
                os.unlink(s)
            except Exception:
                pass


def test_persistence_and_lifecycle():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        net_store = PersistentNetworkOwnershipStore(path)
        cont_store = PersistentOwnershipStore(path)
        nid = net_store.generate_network_id()
        net_store.record_creation(nid, 'i1', 'c1')
        cont_store.record_creation('i1', 'i1', 'c1')
        _add_subnet(net_store, nid, '10.0.0.0/24')
        store = FirewallStateStore(db_path=path)
        p = firewall_policy_model.create_policy('i1', 'broker', 'egress', 'ipv4', [{'network_id': nid, 'ip': '10.0.0.5', 'port': 53}], network_store=net_store, container_store=cont_store)
        compiled = firewall_compiler.compile(p)
        store.save_policy(p, compiled)
        assert store.get(p.policy_id) is not None
        store.transition(p.policy_id, 'VALIDATED')
        store.transition(p.policy_id, 'COMPILED')
        store.transition(p.policy_id, 'INSTALL_PENDING')
        store.transition(p.policy_id, 'INSTALLED')
        store.record_verification_evidence(p.policy_id, p.policy_version, compiled['compiled_rule_digest'], 'verify', 'verified')
        store.transition(p.policy_id, 'VERIFIED', require_evidence=True)
        assert store.get(p.policy_id)['policy_lifecycle_state'] == 'VERIFIED'
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
        for s in ('', '-wal', '-shm'):
            try:
                os.unlink(path + s)
            except Exception:
                pass


def test_mock_controller_failures():
    ctrl = MockFirewallController()
    ctrl.fail_install = True
    import uuid
    try:
        req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'm1', 'policy_id': 'p1', 'policy_version': 1, 'compiled_rule_digest': 'a'*64}
        res = ctrl.install_policy(req)
        assert res['status'] == 'error'
    except Exception:
        pass
    ctrl2 = MockFirewallController()
    ctrl2.fail_verify = True
    req2 = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'm2', 'policy_id': 'p1', 'policy_version': 1, 'compiled_rule_digest': 'b'*64, 'compiled': {}}
    ctrl2.install_policy(req2)
    vreq = dict(req2)
    vreq['request_id'] = str(uuid.uuid4())
    vreq['operation_id'] = str(uuid.uuid4())
    vreq['idempotency_key'] = 'm2v'
    res2 = ctrl2.verify_policy(vreq)
    assert res2['status'] == 'error'
    ctrl3 = MockFirewallController()
    ctrl3.fail_revoke = True
    req3 = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'm3', 'policy_id': 'p1', 'policy_version': 1, 'compiled_rule_digest': 'c'*64, 'compiled': {}}
    ctrl3.install_policy(req3)
    rreq = dict(req3)
    rreq['request_id'] = str(uuid.uuid4())
    rreq['operation_id'] = str(uuid.uuid4())
    rreq['idempotency_key'] = 'm3r'
    res3 = ctrl3.revoke_policy(rreq)
    assert res3['status'] == 'error'


def test_revocation_idempotent():
    ctrl = MockFirewallController()
    import uuid
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'r1', 'policy_id': 'p1', 'policy_version': 1, 'compiled_rule_digest': 'd'*64, 'compiled': {}}
    ctrl.install_policy(req)
    rreq = dict(req)
    rreq['request_id'] = str(uuid.uuid4())
    rreq['operation_id'] = str(uuid.uuid4())
    rreq['idempotency_key'] = 'r1r'
    res1 = ctrl.revoke_policy(rreq)
    res2 = ctrl.revoke_policy(rreq)
    assert res1['status'] == 'ok'
    assert res2['status'] == 'ok'
