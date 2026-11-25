"""Pre-change reproduction harness for Stage 1B.4 (mock-only, evidence artifact).

Run against unmodified source to observe defects. No source is imported from host,
Docker, or privileged paths; only disposable SQLite + in-process mock backends.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid

from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend
from broker.tests.test_post_j20_stage_1b3_durable_crash_recovery import (
    _install_active,
    _op_req,
    _store,
    _svc,
)

_role = threading.local()
a_revoking = threading.Event()
a_done = threading.Event()
b_started = threading.Event()
b_release = threading.Event()
r1_done = threading.Event()
a_pre_complete = threading.Event()
a_release = threading.Event()
b_pre_complete = threading.Event()
b_release_complete = threading.Event()


class RoleStore(ControllerOwnershipStore):
    def update_ownership_state(self, *args, **kwargs):
        result = super().update_ownership_state(*args, **kwargs)
        new_state = args[1] if len(args) > 1 else kwargs.get('new_state')
        if new_state == 'REVOKING' and getattr(_role, 'who', None) == 'A':
            a_revoking.set()
        return result

    def complete_idempotency_record(self, *args, **kwargs):
        who = getattr(_role, 'who', None)
        if who == 'A':
            a_pre_complete.set()
            a_release.wait(10)
        if who == 'B':
            b_pre_complete.set()
            b_release_complete.wait(10)
        result = super().complete_idempotency_record(*args, **kwargs)
        if who == 'A':
            a_done.set()
        return result

    def update_reconciliation_status(self, oid, status):
        if getattr(_role, 'who', None) == 'R1' and status == 'ok':
            r1_done.wait(10)
        return super().update_reconciliation_status(oid, status)


class DualReadbackBackend:
    """A sees missing; B blocks then reports a transient readback error."""

    def __init__(self, inner):
        self.inner = inner

    def inspect_policy(self, req):
        if getattr(_role, 'who', None) == 'B':
            b_started.set()
            raise RuntimeError('transient mock readback error')
        resp = dict(self.inner.inspect_policy(req))
        resp['result'] = {'status': 'missing'}
        return resp

    def __getattr__(self, name):
        return getattr(self.inner, name)


def repro_terminal_overwrite():
    for ev in (a_pre_complete, a_release, b_pre_complete, b_release_complete, a_done, b_started):
        ev.clear()
    store = RoleStore(db_path=os.path.join(tempfile.mkdtemp(), 'r1.db'))
    backend = authorized_backend()
    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=DualReadbackBackend(backend),
    )
    pid = 'b4-terminal'
    digest = _install_active(store, svc, pid)
    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    store.update_ownership_state(oid, 'REVOKING', 'ACTIVE', rec['lifecycle_version'])
    key = 'b4-revoke-key'
    req_digest = svc._req_digest(_op_req(pid, digest, key=key), 'revoke_policy')
    store.create_idempotency_record(
        key, 'revoke_policy', req_digest, resource_key=f'{pid}:1',
        ownership_record_id=oid, operation_outcome='UNCERTAIN',
    )
    store.complete_idempotency_record(
        key, 'revoke_policy',
        json.dumps({'status': 'error', 'error_code': 'REVOKE_UNCONFIRMED', 'result': {'revocation_confirmed': False}}),
        lifecycle_state='ACTIVE', ownership_record_id=oid, operation_outcome='UNCERTAIN',
    )

    outcomes = {}

    def run(who):
        _role.who = who
        try:
            req = _op_req(pid, digest, key=key)
            outcomes[who] = svc.revoke_policy(req).get('status')
        except Exception as e:
            outcomes[who] = f'{type(e).__name__}:{e}'

    ta = threading.Thread(target=run, args=('A',))
    tb = threading.Thread(target=run, args=('B',))
    ta.start(); tb.start()
    assert a_pre_complete.wait(10), 'A did not reach completion'
    assert b_pre_complete.wait(10), 'B did not reach completion'
    # A confirms revocation and writes a successful terminal outcome first.
    a_release.set()
    assert a_done.wait(10), 'A completion did not finish'
    # B's stale readback error then completes afterwards.
    b_release_complete.set()
    ta.join(10); tb.join(10)
    idem = store.get_idempotency_record(key, 'revoke_policy')
    final = store.get_by_policy(pid, 1)
    print('REPRO 1 terminal-overwrite:')
    print('  thread outcomes:', outcomes)
    print('  ownership state:', final.get('installation_state'))
    print('  idempotency status/outcome:', idem.get('status'), idem.get('operation_outcome'))
    print('  cached response status:', json.loads(idem.get('response_json') or '{}').get('status'))
    return idem


def repro_stale_reconciliation():
    r1_done.clear()
    store = RoleStore(db_path=os.path.join(tempfile.mkdtemp(), 'r2.db'))
    backend = authorized_backend()
    svc = FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=backend,
    )
    pid = 'b4-reconcile'
    digest = _install_active(store, svc, pid)
    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    store.update_reconciliation_status(oid, 'uncertain')

    errors = []

    def run_r1():
        _role.who = 'R1'
        try:
            svc.reconcile_pending_operations(_op_req(pid, digest))
        except Exception as e:
            errors.append(f'{type(e).__name__}:{e}')

    t1 = threading.Thread(target=run_r1)
    t1.start()
    # Give R1 time to reach its deliberately delayed status write.
    import time
    time.sleep(0.4)
    _role.who = 'MAIN'
    svc.revoke_policy(_op_req(pid, digest))
    r1_done.set()
    t1.join(10)
    final = store.get_by_policy(pid, 1)
    print('REPRO 2 stale-reconciliation:')
    print('  errors:', errors)
    print('  ownership state:', final.get('installation_state'))
    print('  reconciliation_status:', final.get('reconciliation_status'))
    return final


if __name__ == '__main__':
    repro_terminal_overwrite()
    repro_stale_reconciliation()
