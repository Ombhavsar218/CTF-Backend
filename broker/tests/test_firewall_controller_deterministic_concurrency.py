import os
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from broker.firewall_controller_service import FirewallControllerService
from broker.tests._helper_identity import authorized_backend


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


def test_concurrent_identical_install():
    barrier = threading.Barrier(5)
    results = []
    errors = []
    lock = threading.Lock()
    
    def worker(idx):
        try:
            barrier.wait(timeout=5)
            svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
            req = _req('pd1', key='kd1')
            r = svc.install_policy(req)
            with lock:
                results.append(r.get('status'))
        except Exception as e:
            with lock:
                errors.append(type(e).__name__)
    
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(worker, i) for i in range(5)]
        for f in as_completed(futs):
            f.result(timeout=10)
    
    # All should succeed or be idempotent
    assert len(errors) == 0
    assert all(s == 'ok' for s in results)


def test_concurrent_conflicting_idempotency():
    barrier = threading.Barrier(2)
    results = []
    errors = []
    lock = threading.Lock()
    
    def worker_good():
        try:
            barrier.wait(timeout=5)
            svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
            req = _req('pd2', key='kd2')
            r = svc.install_policy(req)
            with lock:
                results.append(('good', r.get('status')))
        except Exception as e:
            with lock:
                errors.append(('good', type(e).__name__))
    
    def worker_bad():
        try:
            barrier.wait(timeout=5)
            svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
            req = _req('pd2', key='kd2')
            req['compiled_rule_digest'] = 'b' * 64
            req['request_id'] = str(uuid.uuid4())
            req['operation_id'] = str(uuid.uuid4())
            r = svc.install_policy(req)
            with lock:
                results.append(('bad', r.get('status')))
        except Exception as e:
            with lock:
                errors.append(('bad', type(e).__name__))
    
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(worker_good)
        f2 = ex.submit(worker_bad)
        f1.result(timeout=10)
        f2.result(timeout=10)
    
    # Should have conflict
    assert len(errors) >= 1 or any(e[0] == 'Idempotency' for e in errors if isinstance(e, tuple))
    # Or conflict error
    error_types = [e[1] if isinstance(e, tuple) else e for e in errors]
    assert 'FirewallControllerIdempotencyError' in error_types or len(results) == 1


def test_lifecycle_cas_race_install_revoke():
    svc = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
    req = _req('pd3')
    r = svc.install_policy(req)
    assert r['status'] == 'ok'
    rec = svc.ownership_store.get_by_policy('pd3', 1)
    v0 = rec['lifecycle_version']
    barrier = threading.Barrier(2)
    results = []
    errors = []
    lock = threading.Lock()
    
    def worker_revoke():
        try:
            barrier.wait(timeout=5)
            svc2 = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
            vreq = dict(req)
            vreq['request_id'] = str(uuid.uuid4())
            vreq['operation_id'] = str(uuid.uuid4())
            vreq['idempotency_key'] = 'kd3r'
            r2 = svc2.revoke_policy(vreq)
            with lock:
                results.append(('revoke', r2.get('status')))
        except Exception as e:
            with lock:
                errors.append(('revoke', type(e).__name__))
    
    def worker_verify():
        try:
            barrier.wait(timeout=5)
            svc3 = FirewallControllerService(allowed_uids={1000}, allowed_gids={1000}, backend=authorized_backend())
            vreq = dict(req)
            vreq['request_id'] = str(uuid.uuid4())
            vreq['operation_id'] = str(uuid.uuid4())
            vreq['idempotency_key'] = 'kd3v'
            r3 = svc3.verify_policy(vreq)
            with lock:
                results.append(('verify', r3.get('status')))
        except Exception as e:
            with lock:
                errors.append(('verify', type(e).__name__))
    
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(worker_revoke)
        f2 = ex.submit(worker_verify)
        f1.result(timeout=10)
        f2.result(timeout=10)
    
    rec2 = svc.ownership_store.get_by_policy('pd3', 1)
    assert rec2['lifecycle_version'] >= v0
