# Post-J.20 Stage 1B.1 — Durable Lifecycle Intent and Operation Ledger (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Branch:** `main`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged)  
**Milestone:** Stage 1B.1 (first incremental persistence-integrity implementation slice)  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**  
**Baseline preserved:** Stage 1A.5 VERIFIED (scoped); Stage 1B.0 VERIFIED (assessment/planning only). Full broker baseline 854 passed / 0 failed / 0 errors / 0 skipped / actual exit 0.

---

## Design (recorded before implementation)

This section records the proposed schema/API changes and transaction boundaries *before* source edits, per the milestone requirement. Results are appended after implementation.

### 1. Reuse decision (no competing model)

Inspection of the existing durable records (`controller_idempotency`, `controller_lifecycle_history`, `controller_ownership`, `controller_evidence`, `controller_policy_bodies`) established:

- Every controller operation carries a required `idempotency_key` (`firewall_controller_contract._validate_request` required-fields list) and a stored `request_digest` bound to security-relevant payload/identity.
- `controller_idempotency` already provides a stable **operation identity** (`PRIMARY KEY (idempotency_key, operation_type)`), is written **before** any backend side effect, and is updated **after** the operation outcome is assembled.
- `controller_lifecycle_history` is append-only and already records ownership FSM transitions; `controller_ownership.installation_state` is the authoritative FSM with `lifecycle_version` CAS.

**Decision:** extend the existing `controller_idempotency` record with additive operation-outcome columns rather than create a second ledger table (which would duplicate operation identity) or alter the ownership FSM (which would create a competing state machine). Operation outcomes are an **informational parallel dimension** on the existing operation record; they do **not** replace or drive ownership lifecycle states.

### 2. Operation outcome semantics (not ownership states)

| Outcome | Meaning | Durable at |
|---|---|---|
| `INTENT_RECORDED` | Operation intent and request binding durably persisted | `create_idempotency_record` (before backend) |
| `IN_PROGRESS` | Operation entered execution phase; backend may be running/ran | CAS update immediately before backend dispatch |
| `SUCCEEDED` | Backend outcome confirmed and durable state/evidence committed | `complete_idempotency_record` on ok response |
| `FAILED` | Definite backend/operation failure with known outcome | `complete_idempotency_record` on error response |
| `UNCERTAIN` | Backend effect may have occurred but cannot be confirmed (e.g. unconfirmed revoke) | `complete_idempotency_record` on unconfirmed outcome, or recovery classification of interrupted IN_PROGRESS/INTENT_RECORDED records |

Terminal outcomes (`SUCCEEDED`, `FAILED`, `UNCERTAIN`) are written atomically with `status='COMPLETED'` in a single transaction. Interrupted operations remain `INTENT_RECORDED`/`IN_PROGRESS` and are **classified as UNCERTAIN by reconciliation**; no automatic promotion to ACTIVE/REVOKED and no fabricated success after restart.

### 3. Proposed schema changes (additive)

`controller_idempotency` gains:
- `operation_outcome TEXT` — one of the five values above; `NULL` for legacy rows written before this milestone.
- `outcome_updated_at TIMESTAMP` — last outcome transition time.

Implementation approach:
- Include both columns in the `CREATE TABLE IF NOT EXISTS controller_idempotency` definition (fresh DBs).
- Add an idempotent additive migration inside the existing `_init_schema()` (under the Stage 1A.5 `_init_guard()`): `PRAGMA table_info(controller_idempotency)` → `ALTER TABLE ... ADD COLUMN` only when missing (existing DBs). No column drop/rename, no backfill of legacy rows (they are already COMPLETED/PENDING and remain safe).

Append-only triggers, FKs, uniqueness, and CAS semantics on other tables are unchanged.

### 4. Proposed store API changes (additive, backward-compatible)

`ControllerOwnershipStore`:
- `OPERATION_OUTCOMES` constant (validated set).
- `create_idempotency_record(..., operation_outcome='INTENT_RECORDED')` — INSERT includes outcome + timestamp; existing callers need no change.
- **New** `update_operation_outcome(idempotency_key, operation_type, outcome, *, expected_outcomes=None) -> bool` — CAS-guarded UPDATE on its own connection/`BEGIN IMMEDIATE`; raises `BrokerDBError` on genuine storage failure; returns `False` when the guard does not match (concurrent/duplicate ledger state). Guard permits `operation_outcome IS NULL` for legacy PENDING rows.
- `complete_idempotency_record(..., operation_outcome=None)` — optional additive parameter; when provided, sets outcome + timestamp in the **same** transaction as `status='COMPLETED'`. Default `None` preserves existing behavior exactly.

Genuine persistence errors remain `BrokerDBError` (surfaced by the service as `FirewallControllerPersistenceError`); idempotency/CAS conflicts remain `FirewallControllerIdempotencyError`. These are never conflated.

### 5. Proposed service behavior changes

`FirewallControllerService`:
- On idempotency creation, outcome defaults to `INTENT_RECORDED`.
- `_mark_operation_in_progress(key, operation)` immediately before the backend dispatch block: CAS `INTENT_RECORDED → IN_PROGRESS` for fresh operations. Legitimate same-key recovery retries (notably revoke readback/reissue) re-enter from `IN_PROGRESS`/`FAILED`/`UNCERTAIN`; those are allowed because the existing idempotency/recovery path already owns convergence. A `SUCCEEDED` record is excluded (it replays and never reaches the backend). A genuine persistence failure **fails closed before the backend call** (`FirewallControllerPersistenceError`); a CAS no-match raises `FirewallControllerIdempotencyError`.
- Derive the terminal outcome from the response (`_derive_operation_outcome`) and persist it atomically with idempotency completion. Unconfirmed revoke (`REVOKE_UNCONFIRMED` / `revocation_confirmed=False`) maps to `UNCERTAIN`; definite error responses map to `FAILED`; ok responses map to `SUCCEEDED`.
- Reconciliation's pending-idempotency report adds an `operation_outcome` field while preserving the existing `reason='pending_no_auto_replay'` contract value (J.18 compatibility).
- All existing ownership FSM, evidence, canonical-body, CAS, and replay decisions are left unchanged; the ledger is informational and cannot promote state.

### 6. Transaction-boundary diagram (proposed → implemented)

```text
_call(operation)
  TX#A  create_idempotency_record(... operation_outcome='INTENT_RECORDED')   [own conn, BEGIN IMMEDIATE]
  TX#A2 update_operation_outcome(... IN_PROGRESS, expected=INTENT_RECORDED)  [own conn, BEGIN IMMEDIATE, CAS]
        ---- mock backend side effect (no DB tx) ----
        ---- trusted readback / evidence / ownership CAS transitions (existing, separate txs) ----
  TX#D  complete_idempotency_record(... status=COMPLETED, operation_outcome=SUCCEEDED|FAILED|UNCERTAIN)  [own conn, BEGIN IMMEDIATE]

Recovery:
  reconcile_pending_operations -> pending idempotency rows classified UNCERTAIN
                                  (operation_outcome reported; never auto-replayed/promoted)
```

**No end-to-end atomicity is claimed** across backend effects and DB writes; the ledger makes intermediate durable states explicit, discriminable, and fail-closed.

---

## Implementation and verification results

### A. Source changes (smallest additive slice, mock-only)

| File | Change |
|---|---|
| `broker/firewall_controller_service/ownership_store.py` | Added `operation_outcome TEXT` + `outcome_updated_at TIMESTAMP` columns to `controller_idempotency` (CREATE TABLE + guarded additive migration under Stage 1A.5 init lock). Added `OPERATION_OUTCOMES` / intent constants. Extended `create_idempotency_record(..., operation_outcome=None)` (defaults to `INTENT_RECORDED`). Added CAS-guarded `update_operation_outcome(...)` (separate tx; `BrokerDBError` for genuine storage failure, `False` for guard no-match). Extended `complete_idempotency_record(..., operation_outcome=None)` so terminal outcome is committed atomically with `status='COMPLETED'`. |
| `broker/firewall_controller_service/controller_service.py` | Added `_mark_operation_in_progress()` (CAS to `IN_PROGRESS` before backend dispatch; fresh operations from `INTENT_RECORDED`, recovery retries from `IN_PROGRESS`/`FAILED`/`UNCERTAIN`, never from `SUCCEEDED`; genuine persistence failure → `FirewallControllerPersistenceError` and **no backend call**; CAS no-match → `FirewallControllerIdempotencyError`). Added `_derive_operation_outcome()` (revoke non-ok/unconfirmed → `UNCERTAIN`; ok → `SUCCEEDED`; other errors → `FAILED`). Wired both into the existing `_call` dispatch and idempotency completion. Reconciliation pending-idempotency reports now include `operation_outcome` (existing `reason='pending_no_auto_replay'` preserved). |
| `broker/tests/test_post_j20_stage_1b1_durable_lifecycle_intent.py` | **New** 16 deterministic tests using disposable SQLite DBs and test-only fault injection (no source hooks, no sleeps as synchronization, no host/network/privileged operations). |

No existing public method was removed or had its default behavior changed. No ownership FSM transition, evidence, canonical-body, append-only, or replay decision was altered. No new table, no second ledger, no new operation identity namespace.

### B. Transaction boundaries actually implemented

1. `TX#A` — `create_idempotency_record`: INSERT `PENDING` + `INTENT_RECORDED` + `outcome_updated_at` (own connection, `BEGIN IMMEDIATE`), before any ownership transition or backend call.
2. `TX#A2` — `update_operation_outcome(... IN_PROGRESS, expected=INTENT_RECORDED)`: own connection, `BEGIN IMMEDIATE`, CAS-guarded. **Before** the mock backend side effect. Failure here fails closed.
3. Mock backend side effect (outside DB transaction).
4. Existing separate transactions: trusted read-back, evidence, canonical body, ownership CAS transitions, lifecycle history, audit.
5. `TX#D` — `complete_idempotency_record(... status='COMPLETED', operation_outcome=SUCCEEDED|FAILED|UNCERTAIN)`: own connection, `BEGIN IMMEDIATE`, terminal outcome + completion in one transaction.

Recovery: `reconcile_pending_operations` reports still-PENDING idempotency rows as `uncertain` with the recorded `operation_outcome` and never auto-replays or promotes them.

**No end-to-end atomicity is claimed** across backend effects and DB writes. The ledger makes intermediate durable states explicit and discriminable; it does not merge two independent transactional domains.

### C. Outcome classification (informational, never drives FSM)

- `INTENT_RECORDED` — persisted with the idempotency record before backend execution; observed after a crash before `IN_PROGRESS`.
- `IN_PROGRESS` — set immediately before backend dispatch; an interrupted operation remains here. Recovery classifies it `UNCERTAIN` (no fabricated success, no ACTIVE/REVOKED promotion).
- `SUCCEEDED` — written only with a `COMPLETED` idempotency record on an ok response, after durable state/evidence writes.
- `FAILED` — written with `COMPLETED` on a definite non-revoke error response.
- `UNCERTAIN` — written for revoke non-ok/unconfirmed responses; also the recovery classification for any interrupted `INTENT_RECORDED`/`IN_PROGRESS` record.

### D. Verification evidence (raw captures preserved)

| Scope | Command | Result | Evidence files |
|---|---|---|---|
| New Stage 1B.1 suite | `.\venv\Scripts\python.exe -m pytest broker/tests/test_post_j20_stage_1b1_durable_lifecycle_intent.py -q` | **16 passed, 0 failed, 0 errors**, exit `0` | `post_j20_stage_1b1_tests.stdout.txt`, `post_j20_stage_1b1_tests.exit.txt` |
| Focused regression (J.13, J.17, cross-process crash recovery, J.18, persistence-failure closure, J.9, J.12) | `.\venv\Scripts\python.exe -m pytest <7 files> -q` | **103 passed, 0 failed, 0 errors**, exit `0` | `post_j20_stage_1b1_focused_regression.stdout.txt`, `post_j20_stage_1b1_focused_regression.exit.txt` |
| Revoke recovery/idempotency hardening + new suite | `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py broker/tests/test_post_j20_stage_1b1_durable_lifecycle_intent.py -q` | **111 passed, 0 failed, 0 errors**, exit `0` | `post_j20_stage_1b1_revoke_recovery.stdout.txt`, `post_j20_stage_1b1_revoke_recovery.exit.txt` |
| Full broker suite | `.\venv\Scripts\python.exe -m pytest broker/tests -q` | **870 passed, 0 failed, 0 errors, 1 warning, 255.21s (0:04:15), actual exit 0** | `post_j20_stage_1b1_broker_full.stdout.txt`, `post_j20_stage_1b1_broker_full.exit.txt` |

Known pre-existing warnings only: `PytestDeprecationWarning: asyncio_default_fixture_loop_scope unset`, `PydanticDeprecatedSince20`. No skips, no weakened assertions, no arbitrary sleeps used for synchronization in production or tests.

### E. Deterministic fault-injection coverage

| Required scenario | Test |
|---|---|
| Intent durable across process restart | `test_intent_is_durable_before_backend_and_backend_not_called_on_ledger_failure`, `test_interruption_after_intent_does_not_fabricate_success_and_reconcile_is_uncertain` (fresh `ControllerOwnershipStore` on same DB path) |
| Duplicate operation identity deterministic | `test_duplicate_identity_and_conflicting_operations_deterministic` |
| Conflicting operations cannot both succeed | `test_duplicate_identity_and_conflicting_operations_deterministic` (different payload, same key → `FirewallControllerIdempotencyError`), `test_concurrent_same_key_only_one_backend_effect_and_one_ledger_record` (one backend effect / one ledger record) |
| Persistence failure before backend execution fails closed | `test_intent_is_durable_before_backend_and_backend_not_called_on_ledger_failure` (backend call count `0`) |
| Interruption after intent does not fabricate success | `test_interruption_after_intent_does_not_fabricate_success_and_reconcile_is_uncertain` |
| Interruption after backend execution is `UNCERTAIN` until verified | `test_interruption_after_backend_effect_is_uncertain_until_verified` (shared backend across simulated restart; no auto-ACTIVE; explicit verify required) |
| Bindings/evidence valid | `test_evidence_and_ownership_bindings_remain_valid_after_ledger_changes`, `test_successful_install_verify_revoke_records_terminal_outcomes` |
| Append-only protections enforced | `test_append_only_protections_still_enforced` (lifecycle history / evidence / audit) |
| Same-key revoke recovery re-entry (UNCERTAIN → IN_PROGRESS → SUCCEEDED) | `test_revoke_recovery_retry_reenters_in_progress_then_succeeds`, `test_firewall_controller_revoke_recovery_and_idempotency_hardening.py` (96 passed) |
| Crash-recovery/idempotency compatibility preserved | Focused regression suites (J.13, cross-process, J.18, J.12, J.9, persistence-failure closure), revoke recovery/idempotency hardening suite, full broker suite |

Additional schema/API tests: `test_fresh_schema_has_operation_outcome_columns`, `test_additive_migration_for_legacy_idempotency_table`, `test_create_idempotency_defaults_to_intent_and_rejects_invalid_outcome`, `test_update_operation_outcome_cas_guard_and_persistence_error_distinction`, `test_unconfirmed_revoke_is_uncertain_never_revoked`.

### E.2 Full-suite regression discoveries and fixes (evidence)

Two full-suite runs were needed before the final clean capture; both issues were in the new Stage 1B.1 slice only, and neither weakened an existing assertion:

1. **Run 1 — 9 failed, 860 passed, exit 1** (superseded capture). All failures in `test_firewall_controller_revoke_recovery_and_idempotency_hardening.py`. Root cause: the initial `IN_PROGRESS` CAS accepted only `INTENT_RECORDED`, but legitimate same-key revoke recovery retries re-enter from `IN_PROGRESS`/`UNCERTAIN`/`FAILED`. Fix: broaden the CAS to permit those non-`SUCCEEDED` sources while still excluding completed-success records. Re-verified: revoke recovery + new suite **111 passed, exit 0**.
2. **Run 2 — 1 failed, 868 passed, exit 1** (superseded capture). Failure in the new `test_concurrent_same_key_only_one_backend_effect_and_one_ledger_record`: the assertion required the losing identical-key caller to always receive the cached ok response, but under full-suite load it can receive the bounded `FirewallControllerIdempotencyError("Idempotency operation pending")` instead. Fix: accept both safe outcomes for the losing caller while keeping strict assertions on the real invariants — exactly one backend effect, one ownership record, one ledger record `COMPLETED`/`SUCCEEDED`, and no unexpected exception types. Verified stable **10/10** repeated isolated runs.

No existing assertion was weakened, skipped, or removed; no production behavior outside the ledger marker was changed. Final full-suite capture: `post_j20_stage_1b1_broker_full.stdout.txt` / `.exit.txt`.

### F. Traceability (evidence only — no closures)

- **RR-05 (lifecycle operation atomicity):** partially mitigated — durable intent and IN_PROGRESS markers exist before backend effects; terminal outcomes are atomic with idempotency completion. Cross-domain atomicity is explicitly not claimed. **Remains OPEN.**
- **RR-06 (crash recovery/reconciliation):** partially mitigated — interrupted operations now carry a durable, discriminable outcome and reconciliation surfaces it as `UNCERTAIN` with no auto-promotion. **Remains OPEN.**
- **M-06 (durable consistency/evidence integrity):** binding/evidence/append-only invariants preserved and newly covered by Stage 1B.1 tests. **Remains OPEN.**
- **M-01 (transaction boundaries/state-transition correctness):** inspected and documented; transitions remain evidence-gated; operation outcomes are informational only. **Remains OPEN.**

### G. Status — unchanged

- **Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED** (unchanged).
- **T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED** (unchanged; no acceptance evidence supplied).
- No gate VERIFIED CLOSED, no gate status changed. The security-gate register entry for this milestone is evidence-only.
- No Docker, daemon/socket/SDK/container, UDS/`SO_PEERCRED`, privileged helper, Linux firewall, nftables/iptables, `CAP_NET_ADMIN`, host permissions, services, deployment, cloud, or live firewall operations were used.
- Stage 1B.2 and later milestones were **not** started.

### H. Baseline preservation

At implementation start: branch `main`, HEAD `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`, 26 modified tracked files, 403 untracked files. All prior source changes, evidence captures, untracked files, and uncommitted work were preserved. No reset/clean/revert/stage/commit was performed.
