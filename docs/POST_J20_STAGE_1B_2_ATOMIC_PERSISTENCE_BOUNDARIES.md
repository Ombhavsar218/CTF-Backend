# Post-J.20 Stage 1B.2 — Atomic Persistence Boundaries (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Branch:** `main`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged — no commit)  
**Milestone:** Stage 1B.2 (narrowly scoped atomic persistence boundaries)  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**  
**Baselines preserved:** Stage 1A.5 **VERIFIED (scoped)**; Stage 1B.0 **VERIFIED (assessment/planning only)**; Stage 1B.1 **870 passed / 0 failed / 0 errors / 1 warning / actual exit 0**.

**Scope:** RR-05 (lifecycle operation atomicity), M-06 (durable consistency / evidence integrity), M-01 (transaction boundaries / state-transition correctness), in **mock-only** scope. No gate closure, gate-status change, or acceptance is claimed.

> **Backend/DB boundary:** a *DB transaction boundary* groups SQLite writes only. Mock backend calls (`install_policy`, `verify_policy`, `revoke_policy`, `inspect_policy`) and their in-memory effects are **never** inside an SQLite transaction. This implementation does not claim end-to-end atomicity across backend effects and database state.

---

## 1. Pre-modification write-sequence map (recorded before edits)

The following was mapped from `broker/firewall_controller_service/controller_service.py` and `broker/firewall_controller_service/ownership_store.py` before any Stage 1B.2 source edit. `Tx` marks writes already in one `BEGIN IMMEDIATE`/`commit`; `|backend|` marks a mock backend effect that breaks DB atomicity.

### 1.1 Fresh install (no prior ownership)
1. `create_idempotency_record(..., operation_outcome='INTENT_RECORDED')` — `Tx A` (before backend).
2. `create_ownership(...)` — `Tx B`.
3. `record_audit('ownership_intent_persisted')` — `Tx C`.
4. `record_lifecycle_transition(None → REQUESTED)` — `Tx D`.
5. `_mark_operation_in_progress(...)` — `Tx E` (CAS, before backend).
6. `|backend| install_policy`.
7. `update_ownership_state(REQUESTED → INSTALLING)` — `Tx F`.
8. `record_lifecycle_transition(REQUESTED → INSTALLING)` — `Tx G`.
9. `complete_idempotency_record(..., SUCCEEDED)` — `Tx H`.

**Gap:** a failure/crash between steps 2–4 or 7–8 left partial DB state (ownership without history, state without history).

### 1.2 Install revalidation / existing ownership
1. `update_ownership_state(prev → VALIDATING)` — own `Tx`.
2. `record_lifecycle_transition(prev → VALIDATING)` — own `Tx`.
3. `|backend| install_policy`.
4. `update_ownership_state(cur → INSTALLING)` + `record_lifecycle_transition(cur → INSTALLING)` — two `Tx`s.

### 1.3 Install failure (backend returned definite error)
1. `update_ownership_state(prev → FAILED)` — own `Tx`; sets `state_persisted`.
2. `record_lifecycle_transition(prev → FAILED, 'error')` — own `Tx`; sets `history_persisted`.
3. `complete_idempotency_record(..., FAILED)` — own `Tx`.

This path intentionally reports the two persistence outcomes **separately** in `FirewallControllerPersistenceError.details` (`failure_state_persisted`, `lifecycle_history_persisted`, `reason`), including the `ownership_state_changed` CAS-race classification. It is therefore **not** a grouping candidate.

### 1.4 Verify
1. `update_ownership_state(cur → VERIFYING)` — own `Tx` (state-only, no history row in the current design).
2. `|backend| verify_policy`.
3. `store_evidence(...)` — own `Tx`.
4. `record_audit('evidence_stored')` — own `Tx` (best-effort).
5. `update_ownership_state(VERIFYING → VERIFIED)` — own `Tx`.
6. `record_lifecycle_transition(VERIFYING → VERIFIED)` — own `Tx`.
7. `update_ownership_state(VERIFIED → ACTIVE)` — own `Tx`.
8. `record_lifecycle_transition(VERIFIED → ACTIVE)` — own `Tx`.
9. `complete_idempotency_record(..., SUCCEEDED)` — own `Tx`.

### 1.5 Revoke
1. `update_ownership_state(cur → REVOKING)` — own `Tx`.
2. `record_lifecycle_transition(cur → REVOKING)` — own `Tx`.
3. `|backend| revoke_policy`.
4. `|backend| inspect_policy` read-back (may be unavailable → `UNCERTAIN`).
5. `store_evidence(revoked)` — own `Tx`.
6. `update_ownership_state(REVOKING → REVOKED)` — own `Tx`.
7. `record_lifecycle_transition(REVOKING → REVOKED)` — own `Tx`.
8. `complete_idempotency_record(..., SUCCEEDED)` — own `Tx`.

Existing Stage 1B.1 recovery contracts explicitly require evidence durability to **precede** the `REVOKED` promotion, and idempotency completion to be the **last** write. Both separations were preserved.

### 1.6 Reconcile
Per-policy inventory with `|backend| inspect_policy` between DB steps; candidate grouped pairs were `VERIFIED → ACTIVE` + history, interrupted install → `INSTALLING` + history, backend-missing → `FAILED` + history, and `REVOKING → REVOKED` + history. Evidence creation and idempotency completion remain outside those groups.

### 1.7 Canonical policy body
`store_canonical_policy_body` / `ensure_canonical_policy_body` use their own guarded insert transaction on install and are read back on inspect/verify/reconcile. They were left unchanged: no second persistence abstraction, no cross-table grouping with lifecycle writes.

---

## 2. Implementation (narrow, additive)

### 2.1 Store-level helper — `ControllerOwnershipStore.atomic_write()`

Added in `broker/firewall_controller_service/ownership_store.py`:

- A `@contextmanager` that opens one `BEGIN IMMEDIATE`, yields a connection shim, then commits once; any exception (including commit failure) rolls the whole group back and closes the connection.
- `_get_conn_fk()` joins the active group on the same thread. Public write methods are therefore reused unchanged (no duplicate write implementations, no competing persistence layer).
- `_GroupedConnection` defers `commit()`/`close()` to the group owner and keeps `rollback()` live; `_GroupedCursor` suppresses redundant `BEGIN` statements issued by the participating methods. Everything else is delegated unchanged.
- `threading.local()` state; re-entrant use on the same thread joins the outer group. Concurrency isolation, FK enforcement (`PRAGMA foreign_keys=ON`), CAS `lifecycle_version`, uniqueness, and SQLite append-only triggers remain untouched.
- Persistence errors stay `BrokerDBError`; CAS conflicts stay `PermissionError` (re-raised unchanged, so existing classification is preserved).

`atomic_write()` is a **database-only** boundary. It never wraps or suppresses a backend effect.

### 2.2 Service-level grouped call sites (13 boundaries)

Added `with self.ownership_store.atomic_write():` around already-existing persistence calls in `broker/firewall_controller_service/controller_service.py`. Calls remain on `self.ownership_store`, so all existing test-only store wrappers/instrumentation continue to observe and inject into each participating method.

| # | Location | Grouped writes |
|---:|---|---|
| 1 | revoke completion helper | `update_ownership_state(REVOKING → REVOKED)` + history |
| 2 | install revalidate (primary) | `update_ownership_state(prev → VALIDATING)` + history |
| 3 | fresh install intent | `create_ownership` + `record_audit(ownership_intent_persisted)` + `record_lifecycle_transition(None → REQUESTED)` |
| 4 | install revalidate (concurrent-create branch) | state + history |
| 5 | revoke initiate | `update_ownership_state(cur → REVOKING)` + history |
| 6 | install success (intent path) | state + history → `INSTALLING` |
| 7 | install success (revalidated path) | state + history → `INSTALLING` |
| 8 | verify | state + history → `VERIFIED` |
| 9 | verify | state + history → `ACTIVE` |
| 10 | reconcile | state + history → `ACTIVE` |
| 11 | reconcile | state + history → `INSTALLING` |
| 12 | reconcile | state + history → `FAILED` |
| 13 | reconcile | state + history → `REVOKED` |

### 2.3 Deliberate exclusions (established contracts preserved)

- **Evidence creation** is never grouped with the `REVOKED` promotion or with idempotency completion (Stage 1B.1 / J.13 / J.17 recovery contracts depend on evidence being durable before promotion and on promotion being durable before completion).
- **Idempotency completion** remains the final, separate transaction; outcomes remain informational and never drive the ownership FSM.
- **Install-failure `FAILED` transition + history** remain separate because the R.01 residual-risk contract requires granular `failure_state_persisted` / `lifecycle_history_persisted` reporting and the `ownership_state_changed` CAS-race classification. Grouping this path was attempted and reverted; no assertion was weakened.
- **Verify `→ VERIFYING`** remains a separate state-only write; it is a pre-existing non-terminal precondition and has no history row to group with.
- **Canonical policy body persistence** is unchanged.
- No broad refactor, no second ledger, no new FSM, no migration, no schema change.

---

## 3. Deterministic fault-injection evidence

Added `broker/tests/test_post_j20_stage_1b2_atomic_persistence_boundaries.py` (**19 tests**, deterministic, disposable SQLite DB, in-memory mock backend; no Docker/host/network/privileged operations). Faults are injected through a store subclass so every participating public method remains observable.

Coverage:

| Boundary | Injected fault | Verified result |
|---|---|---|
| before transaction start | `fail_before_group` | fail closed; no ownership/backend effect; committed intent survives |
| ownership persistence | `fail_ownership` path via intent group | no ownership/audit/history; retry from committed intent succeeds |
| lifecycle history | `fail_history_on_new_state` for `REQUESTED`, `INSTALLING`, `VERIFIED`, `ACTIVE`, `REVOKING`, `REVOKED` | state change and history roll back together; no false `ACTIVE`/`REVOKED`; evidence stays separate |
| audit | `fail_audit` in intent group | ownership + history + audit all roll back |
| evidence | `fail_evidence` on verify / revoke | no evidence, no promotion, correct non-`SUCCEEDED` classification; retry does not duplicate backend effect |
| idempotency completion | `fail_idem_complete` | grouped state/evidence/history remain committed; record stays non-`COMPLETED`; retry completes without a second backend effect |
| commit | armed one-shot commit failure at intent group, install-success group, revoke-completion group | whole group rolls back; earlier committed intent/evidence remain available |

Additional invariants asserted: append-only UPDATE/DELETE and FK violations still raise `sqlite3.IntegrityError`; `PRAGMA foreign_keys` remains on; nested `atomic_write` joins the outer transaction; concurrent identical CAS transitions yield exactly one success, one `PermissionError`, and one history row.

Retry classification note: non-revoke operations with a `PENDING` record are correctly rejected as `FirewallControllerIdempotencyError` (no silent replay), so recovery tests use a fresh idempotency key; revoke recovery reuses the same key through the established Stage 1B.1 path.

---

## 4. Test results (actual captured runs)

| Run | Command | Result | Evidence |
|---|---|---|---|
| New Stage 1B.2 suite | `python -m pytest broker/tests/test_post_j20_stage_1b2_atomic_persistence_boundaries.py -q` | **19 passed, 0 failed, 1 warning, 14.94s, exit 0** | `post_j20_stage_1b2_new_suite.stdout.txt`, `.exit.txt` |
| Focused regression set | Stage 1B.1 + revoke recovery/idempotency + J.13 + J.17 + cross-process + persistence-failure closure + Stage 1B.2 | **199 passed, 0 failed, 1 warning, 88.04s, exit 0** | `post_j20_stage_1b2_focused.stdout.txt`, `.exit.txt` |
| Required targeted suites | Stage 1B.1, Stage 1B.2, J.8, J.9, J.10, J.12, J.13, J.17, cross-process crash recovery | **123 passed, 0 failed, 1 warning, 109.87s, exit 0** | `post_j20_stage_1b2_targeted.stdout.txt`, `.exit.txt` |
| Residual-risk / R.01 regression | `test_firewall_controller_residual_risk_remediation.py` + Stage 1B.2 | **88 passed, 0 failed, 1 warning, 39.52s, exit 0** | `post_j20_stage_1b2_residual.stdout.txt`, `.exit.txt` |
| **Full broker suite** | `.\venv\Scripts\python.exe -m pytest broker/tests -q` | **889 passed, 0 failed, 0 errors, 1 warning, 322.58s (0:05:22), actual exit 0** | `post_j20_stage_1b2_broker_full.stdout.txt`, `.exit.txt`, `.elapsed.txt` |

Baseline comparison: Stage 1B.1 full suite **870 passed** → Stage 1B.2 **889 passed** (+19 new tests, no tests removed or skipped). Warnings remain the pre-existing `PytestDeprecationWarning` and `PydanticDeprecatedSince20`; no assertion weakened or deleted.

An initial full-suite attempt exposed two R.01 regressions caused by grouping the install-failure path; that grouping was reverted (no test change), and the final full suite above is clean.

---

## 5. Status / authority

- **No gate was closed or reclassified.** T-11, T-13, T-27 remain **OPEN — ACCEPTANCE REQUIRED**.
- Mandatory status is unchanged: **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
- No Docker, daemon/socket/SDK/container, UDS/`SO_PEERCRED`, privileged helper, Linux firewall, nftables/iptables, `CAP_NET_ADMIN`, host permission/service/deployment, cloud, or live firewall operation occurred.
- No `git reset`, `git clean`, revert, stage, or commit was performed. All pre-existing modified/untracked work (Stage 1B.1 and earlier) is preserved. HEAD remains `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`.
- Stage 1B.3 and later milestones were **not** started.

Files changed for this milestone:

- `broker/firewall_controller_service/ownership_store.py` — `atomic_write()` helper + connection/cursor shims (additive).
- `broker/firewall_controller_service/controller_service.py` — 13 narrow `atomic_write()` boundaries.
- `broker/tests/test_post_j20_stage_1b2_atomic_persistence_boundaries.py` — new 19-test fault-injection suite.
- `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` — evidence-only ledger entry (this document's results; no status change).
