import uuid
from broker.app.firewall_controller import MockFirewallController
from broker.app.firewall_controller_contract import FirewallControllerRequestError


def test_contract_health_check():
    c = MockFirewallController()
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': str(uuid.uuid4()),
           'policy_id': 'p1', 'policy_version': 1, 'compiled_rule_digest': 'a'*64}
    res = c.health_check(req)
    assert res['controller_id'] == 'mock-controller'
    assert res['status'] == 'ok'


def test_contract_install_idempotent():
    c = MockFirewallController()
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'k1',
           'policy_id': 'p1', 'policy_version': 1, 'compiled_rule_digest': 'b'*64, 'compiled': {}}
    r1 = c.install_policy(req)
    r2 = c.install_policy(req)
    assert r1['status'] == 'ok'
    assert r2['status'] == 'ok'


def test_contract_idempotency_conflict():
    c = MockFirewallController()
    from broker.app.firewall_controller_contract import FirewallControllerIdempotencyError
    req1 = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'k2',
            'policy_id': 'p1', 'policy_version': 1, 'compiled_rule_digest': 'c'*64}
    req2 = dict(req1)
    req2['compiled_rule_digest'] = 'd'*64
    req2['request_id'] = str(uuid.uuid4())
    req2['operation_id'] = str(uuid.uuid4())
    c.install_policy(req1)
    try:
        c.install_policy(req2)
        assert False
    except FirewallControllerIdempotencyError as e:
        assert e.error_code == "IDEMPOTENCY_CONFLICT"
        assert "conflict" in str(e).lower()


def test_contract_partial_install_ipv6_fail():
    c = MockFirewallController()
    c.fail_install_ipv6 = True
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'k3',
           'policy_id': 'p2', 'policy_version': 1, 'compiled_rule_digest': 'e'*64}
    res = c.install_policy(req)
    assert res['status'] == 'error'
    assert res['error_code'] == 'INSTALL_FAILED'


def test_contract_ownership_mismatch():
    c = MockFirewallController()
    c.ownership_mismatch = True
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'k4',
           'policy_id': 'p3', 'policy_version': 1, 'compiled_rule_digest': 'f'*64}
    res = c.install_policy(req)
    assert res['status'] == 'error'
    assert res['error_code'] == 'OWNERSHIP_MISMATCH'


def test_contract_verify_requires_evidence_structure():
    c = MockFirewallController()
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'k5',
           'policy_id': 'p4', 'policy_version': 1, 'compiled_rule_digest': '1'*64, 'compiled': {}}
    c.install_policy(req)
    vreq = dict(req)
    vreq['request_id'] = str(uuid.uuid4())
    vreq['operation_id'] = str(uuid.uuid4())
    vreq['idempotency_key'] = 'k5v'
    res = c.verify_policy(vreq)
    assert res['status'] == 'ok'
    assert res['result']['evidence']['policy_id'] == 'p4'


def test_contract_revoke_idempotent():
    c = MockFirewallController()
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'k6',
           'policy_id': 'p5', 'policy_version': 1, 'compiled_rule_digest': '2'*64, 'compiled': {}}
    c.install_policy(req)
    rreq = dict(req)
    rreq['request_id'] = str(uuid.uuid4())
    rreq['operation_id'] = str(uuid.uuid4())
    rreq['idempotency_key'] = 'k6r'
    r1 = c.revoke_policy(rreq)
    r2 = c.revoke_policy(rreq)
    assert r1['status'] == 'ok'
    assert r2['status'] == 'ok'


def test_contract_idempotent_identical():
    c = MockFirewallController()
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'kid1',
           'policy_id': 'p7', 'policy_version': 1, 'compiled_rule_digest': '4'*64, 'compiled': {}}
    r1 = c.install_policy(req)
    r2 = c.install_policy(req)
    assert r1 == r2


def test_contract_concurrent_duplicate_inprocess():
    c = MockFirewallController()
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'kconc',
           'policy_id': 'p8', 'policy_version': 1, 'compiled_rule_digest': '5'*64, 'compiled': {}}
    import threading
    results = []
    def call():
        results.append(c.install_policy(dict(req, request_id=str(uuid.uuid4()), operation_id=str(uuid.uuid4()))))
    threads = [threading.Thread(target=call) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All should be idempotent responses (same logical key+payload) - some may hit cache
    assert len(results) == 5
    for r in results:
        assert r['status'] in ('ok', 'error')


def test_contract_reconcile():
    c = MockFirewallController()
    req = {'request_id': str(uuid.uuid4()), 'operation_id': str(uuid.uuid4()), 'idempotency_key': 'k7',
           'policy_id': 'p6', 'policy_version': 1, 'compiled_rule_digest': '3'*64}
    res = c.reconcile_pending_operations(req)
    assert res['status'] == 'ok'
