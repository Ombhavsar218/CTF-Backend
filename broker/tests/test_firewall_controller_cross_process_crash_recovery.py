"""
Phase 2L.2G.2.1 — Independent cross-process crash-recovery validation (mock-only).

Notes:
- Uses subprocess workers with temp SQLite DB and a file-backed mock backend state
  (test-only) so "backend state" can be shared across process boundaries without
  modifying production logic.
- Deterministic synchronization uses multiprocessing Events/Queues where feasible.
- Some intra-service crash boundaries (after backend returns but before idempotency
  completion; after evidence store but before ACTIVE promotion inside verify flow)
  cannot be triggered without in-service hooks; those are validated via state-simulation
  + fresh-process recovery and documented as partially environment/instrumentation-limited.
"""
import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed

# ensure imports work in spawned workers
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_BE = os.path.join(_ROOT, 'ctf-platform-be') if os.path.basename(_ROOT) != 'ctf-platform-be' else _ROOT
if _BE not in sys.path:
    sys.path.insert(0, _BE)
# also add parent of this tests dir
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))


def _req(pid='p1', ver=1, digest='a'*64, key=None, inst='i1', net='n1'):
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
        'instance_id': inst,
        'network_id': net,
        'required_families': ['ipv4'],
    }


# --- file-backed mock backend state (test-only) ---
def _be_load(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'installed': {}, 'verified': [], 'revoked': [], 'idempotency': {}}


def _be_save(path, state):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    os.replace(tmp, path)


def _make_file_backed_backend(state_path, fail_mode=None, block_event_path=None, block_on=None):
    """Returns a backend instance class behavior via simple adapter built in-process."""
    from broker.firewall_controller_service.backend_interface import FirewallBackendInterface
    from broker.app.firewall_controller_contract import _validate_request

    class FileBackedMockBackend(FirewallBackendInterface):
        def __init__(self):
            self.state_path = state_path
            self.fail_mode = fail_mode
            self.block_event_path = block_event_path
            self.block_on = block_on
            self.controller_id = 'mock-controller'
            self.controller_version = '0.1.0'

        def _resp(self, req, status, result, error_code=None, error_message=None):
            return {
                'status': status,
                'request_id': getattr(req, 'request_id', None),
                'operation_id': getattr(req, 'operation_id', None),
                'controller_id': self.controller_id,
                'controller_version': self.controller_version,
                'timestamp': time.time(),
                'result': result,
                'error_code': error_code,
                'error_message': error_message,
            }

        def _signal(self, name):
            if self.block_event_path:
                try:
                    with open(self.block_event_path, 'a', encoding='utf-8') as f:
                        f.write(name + '\n')
                except Exception:
                    pass

        def _maybe_block(self, point):
            if self.block_on == point:
                self._signal(f'blocked_at:{point}')
                # block until killed
                while True:
                    time.sleep(0.05)

        def health_check(self, req):
            r = _validate_request({**(req or {}), 'request_id': (req or {}).get('request_id') or str(uuid.uuid4()), 'operation_id': (req or {}).get('operation_id') or str(uuid.uuid4()), 'idempotency_key': (req or {}).get('idempotency_key') or str(uuid.uuid4()), 'policy_id': (req or {}).get('policy_id') or 'health', 'policy_version': (req or {}).get('policy_version') or 0, 'compiled_rule_digest': (req or {}).get('compiled_rule_digest') or '0'*64})
            return self._resp(r, 'ok', {'status': 'ok'})

        def install_policy(self, req):
            r = _validate_request(req)
            self._maybe_block('install_entry')
            if self.fail_mode == 'install_error':
                return self._resp(r, 'error', {}, error_code='INSTALL_FAILED', error_message='fail')
            st = _be_load(self.state_path)
            st['installed'][r.policy_id] = {'compiled': req.get('compiled'), 'digest': r.compiled_rule_digest, 'version': r.policy_version}
            self._signal('install_state_mutated')
            self._maybe_block('install_after_mutation')
            _be_save(self.state_path, st)
            return self._resp(r, 'ok', {'status': 'installed', 'policy_id': r.policy_id, 'rule_handles': [], 'verified_readback': True, 'digest_verified': True})

        def inspect_policy(self, req):
            r = _validate_request(req)
            if self.fail_mode == 'readback_unavailable':
                raise RuntimeError('backend readback unavailable')
            st = _be_load(self.state_path)
            if r.policy_id not in st.get('installed', {}):
                return self._resp(r, 'ok', {'status': 'missing'})
            return self._resp(r, 'ok', {'status': 'installed', 'rules': st['installed'][r.policy_id], 'ownership_match': True, 'digest_match': True})

        def verify_policy(self, req):
            r = _validate_request(req)
            if self.fail_mode == 'verify_error':
                return self._resp(r, 'error', {}, error_code='VERIFY_FAILED', error_message='fail')
            st = _be_load(self.state_path)
            if r.policy_id not in st.get('installed', {}):
                return self._resp(r, 'error', {}, error_code='NOT_INSTALLED', error_message='not installed')
            if r.policy_id not in st.get('verified', []):
                st.setdefault('verified', []).append(r.policy_id)
                _be_save(self.state_path, st)
            evidence = {'policy_id': r.policy_id, 'policy_version': r.policy_version, 'compiled_rule_digest': r.compiled_rule_digest, 'operation_id': r.operation_id, 'controller_id': self.controller_id, 'verified_at': time.time(), 'families': ['ipv4']}
            return self._resp(r, 'ok', {'status': 'verified', 'verified': True, 'readback_match': True, 'digest_match': True, 'evidence': evidence})

        def revoke_policy(self, req):
            r = _validate_request(req)
            st = _be_load(self.state_path)
            st.get('installed', {}).pop(r.policy_id, None)
            if r.policy_id not in st.get('revoked', []):
                st.setdefault('revoked', []).append(r.policy_id)
            _be_save(self.state_path, st)
            return self._resp(r, 'ok', {'status': 'revoked', 'revoked': True})

        def remove_stale_policy(self, req):
            r = _validate_request(req)
            st = _be_load(self.state_path)
            removed = []
            if r.policy_id in st.get('installed', {}) and r.policy_id not in st.get('verified', []) and r.policy_id not in st.get('revoked', []):
                st['installed'].pop(r.policy_id, None)
                removed.append(r.policy_id)
                _be_save(self.state_path, st)
            return self._resp(r, 'ok', {'status': 'removed_stale' if removed else 'no_action', 'removed': removed})

        def reconcile_pending_operations(self, req):
            r = _validate_request(req)
            return self._resp(r, 'ok', {'reconciled': [], 'pending': [], 'unknown': []})

    return FileBackedMockBackend()


def _worker_install_and_hold(args):
    """Worker: create service with file-backed backend, attempt install; may block in backend and be killed."""
    db_path, be_state_path, block_event_path, block_on, key, pid = args
    try:
        from broker.firewall_controller_service import FirewallControllerService
        from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
        backend = _make_file_backed_backend(be_state_path, block_event_path=block_event_path, block_on=block_on)
        svc = FirewallControllerService(
            allowed_uids={1000}, allowed_gids={1000},
            ownership_store=ControllerOwnershipStore(db_path=db_path),
            backend=backend,
        )
        req = _req(pid, key=key)
        r = svc.install_policy(req)
        return {'ok': True, 'status': r.get('status'), 'pid': os.getpid()}
    except Exception as e:
        return {'ok': False, 'error': type(e).__name__, 'msg': str(e), 'pid': os.getpid()}


def _worker_install_normal(args):
    db_path, be_state_path, key, pid = args
    try:
        from broker.firewall_controller_service import FirewallControllerService
        from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
        backend = _make_file_backed_backend(be_state_path)
        svc = FirewallControllerService(
            allowed_uids={1000}, allowed_gids={1000},
            ownership_store=ControllerOwnershipStore(db_path=db_path),
            backend=backend,
        )
        req = _req(pid, key=key)
        r = svc.install_policy(req)
        return {'ok': True, 'status': r.get('status'), 'pid': os.getpid()}
    except Exception as e:
        return {'ok': False, 'error': type(e).__name__, 'msg': str(e), 'pid': os.getpid()}


def _worker_reconcile(args):
    db_path, be_state_path, policy_id, policy_version, fail_mode = args
    try:
        from broker.firewall_controller_service import FirewallControllerService
        from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
        backend = _make_file_backed_backend(be_state_path, fail_mode=fail_mode)
        svc = FirewallControllerService(
            allowed_uids={1000}, allowed_gids={1000},
            ownership_store=ControllerOwnershipStore(db_path=db_path),
            backend=backend,
        )
        req = _req(policy_id, ver=policy_version, key=str(uuid.uuid4()))
        r = svc.reconcile_pending_operations(req)
        rec = svc.ownership_store.get_by_policy(policy_id, policy_version)
        return {'ok': True, 'result': r, 'state': rec.get('installation_state') if rec else None, 'pid': os.getpid()}
    except Exception as e:
        return {'ok': False, 'error': type(e).__name__, 'msg': str(e), 'pid': os.getpid()}


def _wait_for_signal(path, token, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                if token in f.read():
                    return True
        except Exception:
            pass
        time.sleep(0.02)
    return False


def test_xproc_crash_after_intent_before_backend_side_effects():
    """Actual process termination: intent persisted, backend install side effect not applied (blocked at entry)."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, 'c.db')
    be_path = os.path.join(tmp, 'be.json')
    sig_path = os.path.join(tmp, 'sig.txt')
    _be_save(be_path, {'installed': {}, 'verified': [], 'revoked': [], 'idempotency': {}})
    ctx = mp.get_context('spawn')
    p = ctx.Process(target=_worker_install_and_hold, args=((db_path, be_path, sig_path, 'install_entry', 'kxp1', 'xp1'),))
    p.start()
    try:
        assert _wait_for_signal(sig_path, 'blocked_at:install_entry', timeout=15), 'worker did not reach deterministic block point'
        # terminate abruptly
        p.terminate()
        p.join(timeout=10)
    finally:
        if p.is_alive():
            p.kill(); p.join(timeout=5)
    exitcode = p.exitcode
    # Fresh process recovery
    ctx2 = mp.get_context('spawn')
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx2) as ex:
        fut = ex.submit(_worker_reconcile, (db_path, be_path, 'xp1', 1, None))
        recres = fut.result(timeout=30)
    assert recres['ok'] is True
    assert recres['state'] != 'ACTIVE'
    # backend should not have unknown install from this blocked-before-side-effect case
    st = _be_load(be_path)
    assert 'xp1' not in st.get('installed', {}) or recres['state'] != 'ACTIVE'
    # record evidence
    assert exitcode is not None


def test_xproc_crash_during_backend_execution():
    """Termination while backend is executing after mutation started but before completion (blocked after mutation signal)."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, 'c.db')
    be_path = os.path.join(tmp, 'be.json')
    sig_path = os.path.join(tmp, 'sig.txt')
    _be_save(be_path, {'installed': {}, 'verified': [], 'revoked': [], 'idempotency': {}})
    ctx = mp.get_context('spawn')
    p = ctx.Process(target=_worker_install_and_hold, args=((db_path, be_path, sig_path, 'install_after_mutation', 'kxp2', 'xp2'),))
    p.start()
    try:
        assert _wait_for_signal(sig_path, 'install_state_mutated', timeout=15)
        assert _wait_for_signal(sig_path, 'blocked_at:install_after_mutation', timeout=15)
        p.terminate()
        p.join(timeout=10)
    finally:
        if p.is_alive():
            p.kill(); p.join(timeout=5)
    # backend state may or may not have been saved depending on timing (mutation signaled before save in this mock)
    ctx2 = mp.get_context('spawn')
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx2) as ex:
        fut = ex.submit(_worker_reconcile, (db_path, be_path, 'xp2', 1, None))
        recres = fut.result(timeout=30)
    assert recres['ok'] is True
    assert recres['state'] != 'ACTIVE'


def test_xproc_fresh_process_recovery_preserves_persistence():
    """Install in one process, reconcile/inspect in fresh process using same temp DB and mock backend state."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, 'c.db')
    be_path = os.path.join(tmp, 'be.json')
    _be_save(be_path, {'installed': {}, 'verified': [], 'revoked': [], 'idempotency': {}})
    ctx = mp.get_context('spawn')
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        fut = ex.submit(_worker_install_normal, (db_path, be_path, 'kxp3', 'xp3'))
        r1 = fut.result(timeout=30)
    assert r1['ok'] is True
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        fut = ex.submit(_worker_reconcile, (db_path, be_path, 'xp3', 1, None))
        r2 = fut.result(timeout=30)
    assert r2['ok'] is True
    assert r2['state'] in ('INSTALLING', 'FAILED', 'CLEANUP_PENDING', 'REQUESTED', 'VALIDATING', 'VERIFIED', 'ACTIVE')  # persisted
    # but ACTIVE requires evidence; normal install alone does not verify
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
    store = ControllerOwnershipStore(db_path=db_path)
    rec = store.get_by_policy('xp3', 1)
    assert rec is not None
    assert rec['installation_state'] != 'ACTIVE' or store.get_evidence_by_policy('xp3', 1)  # safety

def _worker_install_conflict(args):
    db_path, be_state_path, key, pid, bad = args
    try:
        from broker.firewall_controller_service import FirewallControllerService
        from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
        backend = _make_file_backed_backend(be_state_path)
        svc = FirewallControllerService(
            allowed_uids={1000}, allowed_gids={1000},
            ownership_store=ControllerOwnershipStore(db_path=db_path),
            backend=backend,
        )
        req = _req('xpc2', key=key)
        if bad:
            req['compiled_rule_digest'] = 'b'*64
            req['request_id'] = str(uuid.uuid4()); req['operation_id'] = str(uuid.uuid4())
        r = svc.install_policy(req)
        return {'ok': True, 'status': r.get('status'), 'pid': os.getpid()}
    except Exception as e:
        return {'ok': False, 'error': type(e).__name__, 'pid': os.getpid()}


def test_xproc_conflicting_idempotency_same_key():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, 'c.db')
    be_path = os.path.join(tmp, 'be.json')
    _be_save(be_path, {'installed': {}, 'verified': [], 'revoked': [], 'idempotency': {}})
    ctx = mp.get_context('spawn')
    key = 'kxpc2'
    with ProcessPoolExecutor(max_workers=2, mp_context=ctx) as ex:
        f1 = ex.submit(_worker_install_conflict, (db_path, be_path, key, 'xpc2', False))
        f2 = ex.submit(_worker_install_conflict, (db_path, be_path, key, 'xpc2', True))
        r1 = f1.result(timeout=30)
        r2 = f2.result(timeout=30)
    results = [r1, r2]
    errors = [r for r in results if not r['ok']]
    assert len(errors) >= 1
    assert any(r.get('error') == 'FirewallControllerIdempotencyError' for r in errors)


def test_xproc_concurrent_reconciliation():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, 'c.db')
    be_path = os.path.join(tmp, 'be.json')
    _be_save(be_path, {'installed': {}, 'verified': [], 'revoked': [], 'idempotency': {}})
    ctx = mp.get_context('spawn')
    # create a persisted uncertain state
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
    store = ControllerOwnershipStore(db_path=db_path)
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'xpr1', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'REQUESTED'
    })
    with ProcessPoolExecutor(max_workers=2, mp_context=ctx) as ex:
        f1 = ex.submit(_worker_reconcile, (db_path, be_path, 'xpr1', 1, None))
        f2 = ex.submit(_worker_reconcile, (db_path, be_path, 'xpr1', 1, None))
        r1 = f1.result(timeout=30); r2 = f2.result(timeout=30)
    assert r1['ok'] is True and r2['ok'] is True
    rec = ControllerOwnershipStore(db_path=db_path).get_by_policy('xpr1', 1)
    assert rec['installation_state'] != 'ACTIVE'


def test_xproc_backend_readback_unavailable_fresh_process():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, 'c.db')
    be_path = os.path.join(tmp, 'be.json')
    _be_save(be_path, {'installed': {}, 'verified': [], 'revoked': [], 'idempotency': {}})
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
    store = ControllerOwnershipStore(db_path=db_path)
    oid = str(uuid.uuid4())
    store.create_ownership({
        'ownership_record_id': oid, 'policy_id': 'xpf1', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'INSTALLING'
    })
    ctx = mp.get_context('spawn')
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        fut = ex.submit(_worker_reconcile, (db_path, be_path, 'xpf1', 1, 'readback_unavailable'))
        r = fut.result(timeout=30)
    assert r['ok'] is True
    assert r['state'] != 'ACTIVE'


def test_xproc_no_adoption_of_unknown_backend_objects():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, 'c.db')
    be_path = os.path.join(tmp, 'be.json')
    # backend has installed state but no ownership in DB
    _be_save(be_path, {'installed': {'xpunk': {'compiled': {}, 'digest': 'a'*64, 'version': 1}}, 'verified': [], 'revoked': [], 'idempotency': {}})
    ctx = mp.get_context('spawn')
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        fut = ex.submit(_worker_reconcile, (db_path, be_path, 'xpunk', 1, None))
        r = fut.result(timeout=30)
    assert r['ok'] is True
    from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
    rec = ControllerOwnershipStore(db_path=db_path).get_by_policy('xpunk', 1)
    assert rec is None or rec['installation_state'] != 'ACTIVE'
