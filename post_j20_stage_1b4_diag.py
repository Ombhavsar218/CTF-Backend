"""Diagnostic for Stage 1B.4 harness issues (evidence artifact)."""
from __future__ import annotations

import threading

from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.tests._helper_identity import authorized_backend
from broker.tests.test_post_j20_stage_1b3_durable_crash_recovery import (
    _CountingBackend, _db_path, _install_active, _op_req, _state,
)


def svc(store, backend):
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000},
        ownership_store=store, backend=backend,
    )


def diag_install_revoke():
    class B:
        def __init__(self, inner):
            self.inner = inner
            self.release = {'install': threading.Event()}
            self.entered = {}
            self.calls = []

        def install_policy(self, req):
            self.entered.setdefault('install', threading.Event()).set()
            self.calls.append('install')
            self.release['install'].wait(10)
            return self.inner.install_policy(req)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    store = ControllerOwnershipStore(db_path=_db_path())
    be = B(authorized_backend())
    s = svc(store, be)
    pid = 'diag-ir'
    digest = _install_active(store, s, pid)
    out = {}

    def run(who, op, key):
        try:
            out[who] = ('ok', getattr(s, op)(_op_req(pid, digest, key=key)).get('status'))
        except Exception as e:
            out[who] = ('error', type(e).__name__, str(e))

    ti = threading.Thread(target=run, args=('install', 'install_policy', 'diag-ir-i'))
    tr = threading.Thread(target=run, args=('revoke', 'revoke_policy', 'diag-ir-r'))
    ti.start()
    print('entered install?', be.entered.get('install', threading.Event()).wait(3))
    tr.start()
    tr.join(10)
    be.release['install'].set()
    ti.join(10)
    print('DIAG install/revoke outcomes:', out)
    print('state:', _state(store, pid), 'calls:', be.calls)


def diag_reconcile_recovery():
    class Store(ControllerOwnershipStore):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.ready = threading.Event()
            self.release = threading.Event()

        def _trace(self, name, fn, *a, **kw):
            try:
                return fn(*a, **kw)
            except Exception as e:
                print('TRACE', name, type(e).__name__, str(e))
                raise

        def update_operation_outcome(self, *a, **kw):
            return self._trace('update_operation_outcome', super().update_operation_outcome, *a, **kw)

        def complete_idempotency_record(self, *a, **kw):
            return self._trace('complete_idempotency_record', super().complete_idempotency_record, *a, **kw)

        def store_evidence(self, *a, **kw):
            return self._trace('store_evidence', super().store_evidence, *a, **kw)

        def get_idempotency_record(self, *a, **kw):
            return self._trace('get_idempotency_record', super().get_idempotency_record, *a, **kw)

        def update_ownership_state(self, *a, **kw):
            if len(a) > 1 and a[1] == 'REVOKED':
                self.ready.set()
                self.release.wait(10)
            return self._trace('update_ownership_state', super().update_ownership_state, *a, **kw)

    store = Store(db_path=_db_path())
    be = authorized_backend()
    s = svc(store, be)
    pid = 'diag-rr'
    digest = _install_active(store, s, pid)
    rec = store.get_by_policy(pid, 1)
    oid = rec['ownership_record_id']
    store.update_ownership_state(oid, 'REVOKING', 'ACTIVE', rec['lifecycle_version'])
    key = pid + '-revoke'
    rd = s._req_digest(_op_req(pid, digest, key=key), 'revoke_policy')
    store.create_idempotency_record(key, 'revoke_policy', rd, resource_key=pid + ':1',
                                    ownership_record_id=oid, operation_outcome='UNCERTAIN')
    store.complete_idempotency_record(
        key, 'revoke_policy',
        '{"status":"error","error_code":"REVOKE_UNCONFIRMED","result":{"revocation_confirmed":false}}',
        lifecycle_state='REVOKING', ownership_record_id=oid, operation_outcome='UNCERTAIN')

    class RB:
        def __init__(self, inner):
            self.inner = inner
            self.revoke_calls = 0

        def inspect_policy(self, req):
            return {'status': 'ok', 'request_id': req.get('request_id'),
                    'operation_id': req.get('operation_id'),
                    'result': {'status': 'missing'}}

        def revoke_policy(self, req):
            self.revoke_calls += 1
            return self.inner.revoke_policy(req)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    be2 = RB(authorized_backend())
    s2 = svc(store, be2)
    out = {}

    def reconcile():
        try:
            out['reconcile'] = ('ok', s2.reconcile_pending_operations(_op_req(pid, digest)))
        except Exception as e:
            out['reconcile'] = ('error', type(e).__name__, str(e))

    def recover():
        try:
            out['recovery'] = ('ok', s2.revoke_policy(_op_req(pid, digest, key=key)).get('status'))
        except Exception as e:
            out['recovery'] = ('error', type(e).__name__, str(e))

    tr = threading.Thread(target=reconcile)
    tr.start()
    print('reconcile ready?', store.ready.wait(10))
    tc = threading.Thread(target=recover)
    tc.start()
    tc.join(10)
    store.release.set()
    tr.join(10)
    print('DIAG reconcile/recovery outcomes:', out)
    print('state:', _state(store, pid), 'revoke_calls:', be2.revoke_calls)


if __name__ == '__main__':
    diag_install_revoke()
    diag_reconcile_recovery()
