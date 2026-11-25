import multiprocessing
import os
import sys
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _req(pid='p1', ver=1, digest='a'*64, key=None):
    return {
        'request_id': str(uuid.uuid4()),
        'operation_id': str(uuid.uuid4()),
        'idempotency_key': key or str(uuid.uuid4()),
        'policy_id': pid,
        'policy_version': ver,
        'compiled_rule_digest': digest,
        'compiled': {},
        'peer_uid': 1000,
        'peer_gid': 1000,
        'instance_id': 'i1',
        'network_id': 'n1',
    }


def _worker_install(args):
    try:
        from broker.firewall_controller_service import FirewallControllerService
        from broker.tests._helper_identity import authorized_backend
        pid, key = args
        svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
        req = _req('pcp1', key=key)
        r = svc.install_policy(req)
        return ('ok', r.get('status'), os.getpid())
    except Exception as e:
        return ('err', type(e).__name__, os.getpid())


def test_cross_process_identical():
    ctx = multiprocessing.get_context('spawn')
    key = 'kcp1'
    with ProcessPoolExecutor(max_workers=3, mp_context=ctx) as ex:
        futs = [ex.submit(_worker_install, (i, key)) for i in range(3)]
        results = [f.result(timeout=30) for f in as_completed(futs)]
    
    errors = [r for r in results if r[0] == 'err']
    assert len(errors) == 0
    statuses = [r[1] for r in results if r[0] == 'ok']
    assert all(s == 'ok' for s in statuses)


def _worker_conflict(args):
    try:
        from broker.firewall_controller_service import FirewallControllerService
        from broker.tests._helper_identity import authorized_backend
        pid, key, bad = args
        svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
        req = _req(f'pcp2{pid}', key=key)
        if bad:
            req['compiled_rule_digest'] = 'b' * 64
            req['request_id'] = str(uuid.uuid4())
            req['operation_id'] = str(uuid.uuid4())
        r = svc.install_policy(req)
        return ('ok', r.get('status'), os.getpid())
    except Exception as e:
        return ('err', type(e).__name__, os.getpid())


def test_cross_process_conflicting():
    ctx = multiprocessing.get_context('spawn')
    key = 'kcp2'
    with ProcessPoolExecutor(max_workers=2, mp_context=ctx) as ex:
        futs = [ex.submit(_worker_conflict, (0, key, False)), ex.submit(_worker_conflict, (1, key, True))]
        results = [f.result(timeout=30) for f in as_completed(futs)]
    
    errors = [r for r in results if r[0] == 'err']
    assert len(errors) >= 1


def _worker_persist(args):
    try:
        from broker.firewall_controller_service import FirewallControllerService
        from broker.tests._helper_identity import authorized_backend
        pid, key = args
        svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
        req = _req(f'pcp3{pid}', key=key)
        r = svc.install_policy(req)
        # exit after persistence
        return ('persisted', r.get('status'), os.getpid())
    except Exception as e:
        return ('err', type(e).__name__, os.getpid())


def _worker_replay(args):
    try:
        from broker.firewall_controller_service import FirewallControllerService
        from broker.tests._helper_identity import authorized_backend
        pid, key = args
        svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
        req = _req(f'pcp3{pid}', key=key)
        r = svc.install_policy(req)
        return ('replayed', r.get('status'), os.getpid())
    except Exception as e:
        return ('err', type(e).__name__, os.getpid())


def test_cross_process_crash_recovery():
    ctx = multiprocessing.get_context('spawn')
    key = 'kcp3'
    # First process persists
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        fut = ex.submit(_worker_persist, (0, key))
        res1 = fut.result(timeout=30)
    assert res1[0] == 'persisted'
    # Second fresh process replays
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        fut = ex.submit(_worker_replay, (0, key))
        res2 = fut.result(timeout=30)
    # Should replay or be ok
    assert res2[0] in ('replayed', 'err')
    if res2[0] == 'replayed':
        assert res2[1] == 'ok'
    elif res2[0] == 'err':
        assert res2[1] in ('FirewallControllerIdempotencyError',)
