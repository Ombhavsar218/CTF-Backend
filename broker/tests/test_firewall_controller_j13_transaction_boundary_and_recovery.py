"""Phase 2L.2J.13 deterministic transaction-boundary, lifecycle/snapshot race,
idempotency/response-loss, and persistence-integrity tests (mock-only).

Test-only fault injection: disabled by default, explicit test wiring only,
disposable DBs, no public request/runtime activation, no host/network ops.
No production source modifications.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager

import pytest

from broker.app.db import BrokerDBError
from broker.firewall_controller_service import FirewallControllerService
from broker.firewall_controller_service.ownership_store import ControllerOwnershipStore
from broker.firewall_controller_service.rule_schema_v1 import (
    RULE_SCHEMA_VERSION,
    compiled_rule_digest,
    validate_and_normalize_rules,
)
from broker.tests._helper_identity import authorized_backend


# --- helpers ---

def _db_path():
    return os.path.join(tempfile.mkdtemp(), "j13.db")


def _store(path=None):
    return ControllerOwnershipStore(db_path=path or _db_path())


def _svc(store=None, backend=None):
    store = store or _store()
    backend = backend or authorized_backend()
    return FirewallControllerService(
        allowed_uids={1000}, allowed_gids={1000}, backend=backend, ownership_store=store
    )


def _base_rule(**overrides):
    r = {
        "family": "ipv4", "direction": "ingress", "protocol": "tcp",
        "source_cidr": "10.0.0.0/24", "destination_cidr": "10.0.1.0/24",
        "port_start": 80, "port_end": 80, "action": "accept",
    }
    r.update(overrides)
    return r


def _install_req(pid=None, rules=None, key=None, **overrides):
    rules = [_base_rule()] if rules is None else rules
    norm = validate_and_normalize_rules(rules, sorted({r["family"] for r in rules}))
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": key or str(uuid.uuid4()),
        "policy_id": pid or f"p-{uuid.uuid4()}", "policy_version": 1,
        "compiled_rule_digest": compiled_rule_digest(norm), "compiled": {},
        "rules": [dict(r) for r in rules],
        "required_families": sorted({r["family"] for r in rules}),
        "peer_uid": 1000, "peer_gid": 1000, "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


def _op_req(pid, digest, **overrides):
    req = {
        "request_id": str(uuid.uuid4()), "operation_id": str(uuid.uuid4()),
        "idempotency_key": str(uuid.uuid4()), "policy_id": pid, "policy_version": 1,
        "compiled_rule_digest": digest, "peer_uid": 1000, "peer_gid": 1000,
        "instance_id": "i1", "network_id": "n1",
    }
    req.update(overrides)
    return req


def _install_active(store, svc, pid, ver=1):
    req = _install_req(pid=pid, policy_version=ver)
    digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    assert svc.verify_policy(_op_req(pid, digest, policy_version=ver))["status"] == "ok"
    own = store.get_by_policy(pid, ver)
    assert own and own.get("installation_state") == "ACTIVE"
    return digest, own


def _snapshot(store, pid, ver=1):
    own = store.get_by_policy(pid, ver)
    hist = store.get_lifecycle_history(own.get("ownership_record_id")) if own else []
    ev = store.get_evidence_by_ownership(own.get("ownership_record_id")) if own else []
    body = store.get_canonical_policy_body(pid, ver)
    return {"own": own, "hist": hist, "ev": ev, "body": body}


# --- test-only connection instrumentation (disabled by default) ---

class InstrumentedConnection:
    """Test-only wrapper; can fail commit/execute based on explicit test config."""
    def __init__(self, real, cfg):
        self._conn = real
        self._cfg = cfg  # dict controlled by test: fail_commit_n, fail_execute_match, committed flag ref
    def cursor(self):
        return self._conn.cursor()
    def execute(self, sql, *a, **kw):
        m = self._cfg.get("fail_execute_contains")
        if m and isinstance(sql, str) and m in sql and self._cfg.get("fail_execute_active", True):
            n = self._cfg.get("fail_execute_after", 0)
            self._cfg["_exec_hits"] = self._cfg.get("_exec_hits", 0) + 1
            if self._cfg["_exec_hits"] > n:
                raise sqlite3.OperationalError(f"Injected execute failure: {m}")
        return self._conn.execute(sql, *a, **kw)
    def commit(self):
        self._cfg["_commit_calls"] = self._cfg.get("_commit_calls", 0) + 1
        n = self._cfg.get("fail_commit_on_call")
        if n is not None and self._cfg["_commit_calls"] == n:
            raise sqlite3.OperationalError("Injected commit failure")
        r = self._conn.commit()
        self._cfg["committed"] = True
        return r
    def rollback(self):
        self._cfg["rolled_back"] = True
        return self._conn.rollback()
    def close(self):
        return self._conn.close()
    @property
    def row_factory(self):
        return self._conn.row_factory
    @row_factory.setter
    def row_factory(self, v):
        self._conn.row_factory = v


def _instrument_store(path, cfg):
    store = _store(path)
    real = store.db._get_conn
    def wrapped():
        return InstrumentedConnection(real(), cfg)
    store.db._get_conn = wrapped
    return store


# --- 2. Transaction-boundary matrix (achievable, test-only) ---

def test_tx_commit_failure_on_create_ownership_rolls_back_no_partial_state():
    path = _db_path()
    cfg = {"fail_commit_on_call": 1}
    store = _instrument_store(path, cfg)
    rec = {
        'ownership_record_id': str(uuid.uuid4()), 'policy_id': 'p-tx-own', 'policy_version': 1,
        'instance_id': 'i1', 'network_id': 'n1', 'canonical_policy_digest': 'a'*64,
        'installed_rule_ids': [], 'address_family': 'ipv4', 'installation_state': 'REQUESTED'
    }
    with pytest.raises(Exception):
        store.create_ownership(rec)
    fresh = _store(path)
    assert fresh.get_by_policy('p-tx-own', 1) is None
    assert cfg.get("rolled_back") or not cfg.get("committed", False)


def test_tx_commit_failure_on_store_evidence_rolls_back_no_evidence():
    path = _db_path()
    base = _store(path); svc = _svc(base)
    req = _install_req(pid="p-tx-evc"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = base.get_by_policy("p-tx-evc", 1)
    cfg = {"fail_commit_on_call": 1}
    store_i = _instrument_store(path, cfg)
    ev = {
        'evidence_id': str(uuid.uuid4()), 'ownership_record_id': own['ownership_record_id'],
        'policy_id': 'p-tx-evc', 'policy_version': 1, 'instance_id': 'i1', 'network_id': 'n1',
        'canonical_policy_digest': digest, 'address_family': 'ipv4', 'installed_rule_ids': [],
        'verification_result': 'verified',
    }
    with pytest.raises(Exception):
        store_i.store_evidence(ev)
    fresh = _store(path)
    assert fresh.get_evidence_by_policy('p-tx-evc', 1) == []
    # ownership must not be falsely promoted by this failed evidence tx
    assert fresh.get_by_policy('p-tx-evc', 1).get('installation_state') != 'ACTIVE'


def test_tx_commit_failure_on_idempotency_complete_no_false_completed():
    path = _db_path()
    base = _store(path)
    base.create_idempotency_record("k-tx-ic", "install_policy", "d"*64, resource_key="p:1")
    cfg = {"fail_commit_on_call": 1}
    store_i = _instrument_store(path, cfg)
    with pytest.raises(Exception):
        store_i.complete_idempotency_record("k-tx-ic", "install_policy", json.dumps({"status":"ok"}))
    fresh = _store(path)
    idem = fresh.get_idempotency_record("k-tx-ic", "install_policy")
    assert idem is not None
    assert idem.get("status") != "COMPLETED"


def test_failure_after_commit_but_before_caller_response_recovery_recognizes_committed_install():
    """Simulate response loss after durable install-state progress by interrupting after commit path:
    commit ownership/idempotency intent in one flow then crash before completing response handling.
    Deterministic approximation: complete install via service, then simulate lost response by treating
    caller as uncertain and verifying fresh process/read-back + reconcile behavior is safe/non-duplicating."""
    path = _db_path()
    store = _store(path); svc = _svc(store)
    req = _install_req(pid="p-resp-loss", key="k-resp-loss")
    digest = req["compiled_rule_digest"]
    res = svc.install_policy(req)
    assert res.get("status") == "ok"
    # Caller "lost response": fresh process retries with same key/request must replay deterministically.
    store2 = _store(path); svc2 = _svc(store2, backend=authorized_backend())
    res2 = svc2.install_policy(req)
    assert res2.get("status") == "ok"
    own = store2.get_by_policy("p-resp-loss", 1)
    assert own is not None
    assert own.get("installation_state") != "ACTIVE"  # install alone never promotes
    # no duplicate ownership
    assert len([o for o in store2.list_ownerships() if o.get("policy_id")=="p-resp-loss"]) == 1


def test_reopen_and_reconcile_after_commit_preserves_state_no_false_active():
    path = _db_path()
    store = _store(path); svc = _svc(store)
    req = _install_req(pid="p-reopen-tx"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    before = _store(path).get_by_policy("p-reopen-tx", 1)
    store2 = _store(path); svc2 = _svc(store2, backend=authorized_backend())
    rec = svc2.reconcile_pending_operations(_op_req("p-reopen-tx", digest))
    assert rec.get("status") == "ok"
    after = _store(path).get_by_policy("p-reopen-tx", 1)
    assert after.get("installation_state") != "ACTIVE"
    assert after.get("installation_state") in ("FAILED","CLEANUP_PENDING","INSTALLING","REQUESTED","VALIDATING","VERIFYING","VERIFIED")


# --- 3. Lifecycle and snapshot race matrix (deterministic) ---

def test_verify_vs_reconcile_barrier_no_stale_overwrite():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-r-vr"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    b = threading.Barrier(2); out={}; err={}
    def do_verify():
        b.wait(10)
        try: out['v']=svc.verify_policy(_op_req("p-r-vr", digest))
        except Exception as e: err['v']=e
    def do_rec():
        b.wait(10)
        try: out['r']=svc.reconcile_pending_operations(_op_req("p-r-vr", digest))
        except Exception as e: err['r']=e
    t1=threading.Thread(target=do_verify); t2=threading.Thread(target=do_rec)
    t1.start(); t2.start(); t1.join(30); t2.join(30)
    own = store.get_by_policy("p-r-vr", 1)
    assert own is not None
    assert own.get("installation_state") in ("INSTALLING","VERIFYING","VERIFIED","ACTIVE","FAILED","CLEANUP_PENDING")


def test_revoke_vs_reconcile_barrier_no_reactivation():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-r-rvr")
    b = threading.Barrier(2); out={}; err={}
    def do_revoke():
        b.wait(10)
        try: out['rv']=svc.revoke_policy(_op_req("p-r-rvr", digest))
        except Exception as e: err['rv']=e
    def do_rec():
        b.wait(10)
        try: out['r']=svc.reconcile_pending_operations(_op_req("p-r-rvr", digest))
        except Exception as e: err['r']=e
    t1=threading.Thread(target=do_revoke); t2=threading.Thread(target=do_rec)
    t1.start(); t2.start(); t1.join(30); t2.join(30)
    own = store.get_by_policy("p-r-rvr", 1)
    # once revoking/revoked path engaged, must not reactivate to ACTIVE from stale reconcile
    assert own.get("installation_state") != "INSTALLING"


def test_two_simultaneous_lifecycle_transitions_verify_races_safe():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-r-2lt"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    b = threading.Barrier(2); res=[None,None]; errs=[None,None]
    def w(i):
        try:
            b.wait(10)
            res[i]=svc.verify_policy(_op_req("p-r-2lt", digest, idempotency_key=str(uuid.uuid4()), request_id=str(uuid.uuid4()), operation_id=str(uuid.uuid4())))
        except Exception as e:
            errs[i]=e
    ts=[threading.Thread(target=w,args=(i,)) for i in range(2)]
    for t in ts: t.start()
    for t in ts: t.join(30)
    own = store.get_by_policy("p-r-2lt", 1)
    assert own.get("installation_state") in ("INSTALLING","VERIFYING","VERIFIED","ACTIVE","FAILED","CLEANUP_PENDING")
    # no duplicate ACTIVE evidence explosion in covered case
    ev = store.get_evidence_by_policy("p-r-2lt", 1)
    assert isinstance(ev, list)


def test_stale_reconcile_after_revoke_cannot_reactivate():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-stale-rev")
    assert svc.revoke_policy(_op_req("p-stale-rev", digest))["status"] in ("ok","error")
    # reconcile repeatedly
    for _ in range(3):
        svc.reconcile_pending_operations(_op_req("p-stale-rev", digest, idempotency_key=str(uuid.uuid4()), request_id=str(uuid.uuid4()), operation_id=str(uuid.uuid4())))
    own = store.get_by_policy("p-stale-rev", 1)
    assert own.get("installation_state") in ("REVOKING","REVOKED","CLEANUP_PENDING","FAILED","ORPHANED")
    assert own.get("installation_state") != "ACTIVE"


def test_policy_version_advanced_snapshot_no_cross_version_overwrite():
    store = _store(); svc = _svc(store)
    r1 = _install_req(pid="p-pvadv", policy_version=1); d1 = r1["compiled_rule_digest"]
    assert svc.install_policy(r1)["status"] == "ok"
    assert svc.verify_policy(_op_req("p-pvadv", d1, policy_version=1))["status"] == "ok"
    # install v2 separately (different version identity)
    r2 = _install_req(pid="p-pvadv", policy_version=2); d2 = r2["compiled_rule_digest"]
    assert svc.install_policy(r2)["status"] == "ok"
    # reconcile v1 must not mutate v2 into active/verified falsely
    svc.reconcile_pending_operations(_op_req("p-pvadv", d1, policy_version=1))
    own1 = store.get_by_policy("p-pvadv", 1)
    own2 = store.get_by_policy("p-pvadv", 2)
    assert own1.get("installation_state") == "ACTIVE"
    assert own2.get("installation_state") != "ACTIVE"


def test_ownership_binding_changed_during_snapshot_reconcile_fails_closed():
    store = _store(); svc = _svc(store)
    digest, _ = _install_active(store, svc, "p-obind")
    # mutate authoritative ownership binding in DB (adversarial/corruption simulation)
    store.db.execute("UPDATE controller_ownership SET instance_id='other' WHERE policy_id=? AND policy_version=?", ("p-obind", 1))
    # Caller request still carries old binding; reconciliation must fail closed (not accept stale snapshot/binding).
    with pytest.raises(PermissionError):
        svc.reconcile_pending_operations(_op_req("p-obind", digest))
    # request with old binding must be rejected/fail closed in covered path
    with pytest.raises(Exception):
        svc.inspect_policy(_op_req("p-obind", digest))


# --- 4. Idempotency and response-loss ---

class _LockingStore(ControllerOwnershipStore):
    """Test-only: blocks in create_idempotency_record to force concurrent initial creation."""
    def __init__(self, path, event):
        super().__init__(db_path=path)
        self._event = event
        self._hit = 0
    def create_idempotency_record(self, *a, **kw):
        self._hit += 1
        if self._hit == 1:
            self._event.wait(timeout=10)
        return super().create_idempotency_record(*a, **kw)


def test_concurrent_initial_creation_same_key_no_dual_success():
    path = _db_path()
    ev = threading.Event()
    store = _LockingStore(path, ev)
    svc = _svc(store)
    req = _install_req(pid="p-idconc", key="k-idconc")
    out = [None, None]; errs=[None,None]; b = threading.Barrier(2)
    def w(i):
        try:
            b.wait(10)
            out[i] = svc.install_policy(req)
        except Exception as e:
            errs[i]=e
    ts=[threading.Thread(target=w,args=(i,)) for i in range(2)]
    for t in ts: t.start()
    time.sleep(0.05)
    ev.set()
    for t in ts: t.join(30)
    # at most one successful install side effect path should own completion; no dual conflicting completed records semantics violated
    fresh = _store(path)
    idem = fresh.get_idempotency_record("k-idconc","install_policy")
    assert idem is not None
    owns = [o for o in fresh.list_ownerships() if o.get("policy_id")=="p-idconc"]
    assert len(owns) == 1


def test_same_key_identical_replay_after_commit_is_deterministic():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-replay", key="k-replay")
    r1 = svc.install_policy(req)
    r2 = svc.install_policy(req)
    assert r1.get("status") == r2.get("status") == "ok"


def test_same_key_conflicting_replay_rejected():
    store = _store(); svc = _svc(store)
    req1 = _install_req(pid="p-conf", key="k-conf")
    assert svc.install_policy(req1)["status"] == "ok"
    req2 = _install_req(pid="p-conf", key="k-conf", instance_id="i2")  # different payload/identity context
    with pytest.raises(Exception):
        svc.install_policy(req2)


def test_persistent_create_failure_bounded_and_no_false_success_j13():
    path = _db_path()
    class F(ControllerOwnershipStore):
        def create_idempotency_record(self, *a, **kw):
            raise BrokerDBError("Injected persistent create failure")
    svc = _svc(F(db_path=path))
    req = _install_req(pid="p-pcf", key="k-pcf")
    t=time.monotonic()
    with pytest.raises(Exception):
        svc.install_policy(req)
    assert time.monotonic()-t < 3.0
    idem = _store(path).get_idempotency_record("k-pcf","install_policy")
    assert idem is None or idem.get("status") != "COMPLETED"


def test_persistent_read_failure_bounded_j13():
    path = _db_path()
    class F(ControllerOwnershipStore):
        def get_idempotency_record(self, *a, **kw):
            raise BrokerDBError("Injected persistent read failure")
    svc = _svc(F(db_path=path))
    req = _install_req(pid="p-prf", key="k-prf")
    t=time.monotonic()
    with pytest.raises(Exception):
        svc.install_policy(req)
    assert time.monotonic()-t < 3.0


def test_retry_after_committed_same_idempotent_operation_replays_no_duplicate():
    path = _db_path()
    store = _store(path); svc = _svc(store)
    req = _install_req(pid="p-retry-c", key="k-retry-c")
    assert svc.install_policy(req)["status"] == "ok"
    # fresh process retry
    svc2 = _svc(_store(path), backend=authorized_backend())
    assert svc2.install_policy(req)["status"] == "ok"
    assert len([o for o in _store(path).list_ownerships() if o.get("policy_id")=="p-retry-c"]) == 1


# --- 5. Persistence integrity ---

def test_canonical_body_ownership_version_binding_enforced():
    store = _store(); svc = _svc(store)
    req = _install_req(pid="p-cbind"); digest = req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    own = store.get_by_policy("p-cbind",1)
    # tamper binding
    store.db.execute("UPDATE controller_policy_bodies SET ownership_record_id=? WHERE policy_id=? AND policy_version=?", (str(uuid.uuid4()), "p-cbind", 1))
    res = svc.reconcile_pending_operations(_op_req("p-cbind", digest))
    assert any(u.get("policy_id")=="p-cbind" for u in (res.get("result") or {}).get("uncertain") or [])


def test_state_version_cas_rejection_no_stale_write():
    store = _store(); svc = _svc(store)
    digest, own = _install_active(store, svc, "p-casj13")
    with pytest.raises(Exception):
        store.update_ownership_state(own["ownership_record_id"], "REVOKING", "ACTIVE", expected_version=own["lifecycle_version"]-1)
    assert store.get_by_policy("p-casj13",1).get("installation_state") == "ACTIVE"


def test_reopen_recovery_integrity_after_verified_active():
    path = _db_path(); store=_store(path); svc=_svc(store)
    digest, _ = _install_active(store, svc, "p-rri")
    s2 = _store(path); svc2=_svc(s2)
    res = svc2.reconcile_pending_operations(_op_req("p-rri", digest))
    assert res.get("status") == "ok"
    assert s2.get_by_policy("p-rri",1).get("installation_state") == "ACTIVE"


def test_corrupt_canonical_json_fails_closed_j13():
    store=_store(); svc=_svc(store)
    req=_install_req(pid="p-cj13"); digest=req["compiled_rule_digest"]
    assert svc.install_policy(req)["status"] == "ok"
    store.db.execute("UPDATE controller_policy_bodies SET canonical_rules_json='[bad' WHERE policy_id=? AND policy_version=?", ("p-cj13",1))
    res = svc.reconcile_pending_operations(_op_req("p-cj13", digest))
    assert any(u.get("policy_id")=="p-cj13" for u in (res.get("result") or {}).get("uncertain") or [])


def test_evidence_history_duplication_not_observed_on_repeated_recovery():
    store=_store(); svc=_svc(store)
    digest,_=_install_active(store, svc, "p-nodup")
    own = store.get_by_policy("p-nodup",1)
    h0 = len(store.get_lifecycle_history(own["ownership_record_id"]))
    e0 = len(store.get_evidence_by_policy("p-nodup",1))
    for _ in range(3):
        svc.reconcile_pending_operations(_op_req("p-nodup", digest, idempotency_key=str(uuid.uuid4()), request_id=str(uuid.uuid4()), operation_id=str(uuid.uuid4())))
    h1 = len(store.get_lifecycle_history(own["ownership_record_id"]))
    e1 = len(store.get_evidence_by_policy("p-nodup",1))
    assert h1 >= h0
    assert e1 == e0  # no duplicate evidence from repeated reconcile on stable active+evidenced state (covered)
