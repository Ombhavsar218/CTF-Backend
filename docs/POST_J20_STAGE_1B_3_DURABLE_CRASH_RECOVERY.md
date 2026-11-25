# Post-J.20 Stage 1B.3 — Durable Crash Recovery and Reconciliation (Mock-Only)

**Status:** engineering evidence only — scope VERIFIED, gates unchanged.

Mandatory status remains **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**. This document records
deterministic mock-only evidence; it is not gate acceptance.

Baseline: Stage 1A.5 VERIFIED (scoped), Stage 1B.0 VERIFIED (assessment), Stage 1B.1
preserved, Stage 1B.2 VERIFIED (scoped; full broker suite 889 passed, exit 0).

---

## Phase 1 — Recovery inventory (recorded before source modification)

### Durable records available after restart

All records below live in the single existing SQLite controller store
(`ControllerOwnershipStore`); no parallel ledger is introduced.

| Record | Writes relevant to recovery |
| --- | --- |
| `controller_idempotency` | One row per `(idempotency_key, operation_type)`. `status` `PENDING` → `COMPLETED`; `request_digest`, `resource_key`, `ownership_record_id`, `response_json`, `recovery_meta_json`; Stage 1B.1 `operation_outcome` / `outcome_updated_at` (`INTENT_RECORDED`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED`, `UNCERTAIN`). Informational only. |
| `controller_ownership` | `installation_state`, `lifecycle_version` (CAS), `reconciliation_status`, ownership identity/digest binding. |
| `controller_lifecycle_history` | Append-only `prev_state`/`new_state`/`operation_id`/`request_id`/`transition_reason`. |
| `controller_evidence` | Append-only, bound to ownership identity/digest; `verification_result` is `verified` or `revoked`. |
| `controller_audit` | Append-only events (best-effort for some paths). |
| `controller_policy_bodies` | Canonical schema-v1 body; read back via `read_trusted_canonical_policy_body` with digest re-computation. |

Terminology used below:

- **Ownership identity** = `ownership_record_id`, `policy_id`, `policy_version`, `instance_id`,
  `network_id`, canonical digest and address family, as enforced by
  `_validate_ownership_binding` / `_assert_ownership_identity_unchanged`.
- **Backend effect** = mock helper/executor state mutation. It is never inside an SQLite
  transaction; the controller cannot atomically commit it with DB records.
- **Intent alone is never proof of backend execution.** Only trusted backend read-back plus
  matching durable evidence can support promotion to `ACTIVE` or `REVOKED`.

---

### 1. `install_policy`

Durable write sequence (in order; `A` = grouped by `atomic_write`):

1. `create_idempotency_record(...)` → ledger `PENDING` / `INTENT_RECORDED` (own transaction).
2. If no ownership row: `A1 = create_ownership(REQUESTED) + audit(ownership_intent_persisted) + history(None→REQUESTED)`.
3. `A2 = update_ownership_state(REQUESTED→VALIDATING) + history(install_revalidate)` (also on the concurrent-creation retry path).
4. `_ensure_canonical_policy_body_persisted(...)` → canonical body row (schema-v1 only).
5. `_mark_operation_in_progress(...)` → `INTENT_RECORDED → IN_PROGRESS` (CAS).
6. **Backend effect:** `backend.install_policy(...)`.
7. On `ok`: `A3 = update_ownership_state(→INSTALLING) + history(install_backend_ok / install_revalidated_backend_ok)`.
   On non-`ok`: `FAILED` state write and history write are deliberately separate (R.01 granular reporting).
8. `complete_idempotency_record(...)` → `COMPLETED` + response + terminal outcome. **Final durable write.**

| Crash point | Last durable state | Backend effect? | Records available | Provable after restart | Must remain UNCERTAIN |
| --- | --- | --- | --- | --- | --- |
| After (1) | Ledger `PENDING`/`INTENT_RECORDED` | No | Ledger only | Intent recorded; no ownership yet | Whether install would be applied |
| After (2) | Ownership `REQUESTED` + history + ledger intent | No | Ledger, ownership, history | Ownership intent durable; family/digest bound | Backend execution |
| After (3) | Ownership `VALIDATING` + history | No | + history | Validation intent durable | Backend execution |
| After (4) | Canonical body persisted | No | + policy body | Body trusted via read-back | Backend execution |
| After (5) | Ledger `IN_PROGRESS` | No | Ledger outcome | Execution started; no backend call proven | Backend execution |
| After (6) | Still `VALIDATING`/`INSTALLING` pre-transition | **May have occurred** | Ledger + ownership; no verification evidence | Backend read-back can prove installed/missing | Success, until read-back + verification evidence |
| After (7) | Ownership `INSTALLING` + history | May have occurred | + history | Backend effect preceded state promotion | `ACTIVE` (never promoted by install) |
| After (7, failure) | Ownership `FAILED`, maybe history missing | Backend reported failure | Ledger, state, maybe history | Failure state durable | Whether backend partially applied |
| After (8) | `COMPLETED` + response | As above | Full ledger | Cached response replayable | Nothing for completed path |

Recovery contract: same-key retry of a `PENDING` non-revoke ledger is rejected as
`Idempotency operation pending` (no duplicate backend call). Reconcile sees `REQUESTED`/
`VALIDATING`/`INSTALLING`; a trusted read-back of `installed` may move the state to
`INSTALLING` and set `needs_verification`, never `ACTIVE`. A `missing` read-back may move
the state to `FAILED`. Unavailable/inconsistent read-back is `uncertain`.

---

### 2. `verify_policy`

Durable write sequence:

1. Ledger intent `PENDING` / `INTENT_RECORDED`.
2. Ownership re-validate; canonical read-back pre-check (read only).
3. `_mark_operation_in_progress(...)` → `IN_PROGRESS`.
4. **Backend effect:** `backend.verify_policy(...)`.
5. `_store_verification_evidence(...)` → append-only `verified` evidence row (own transaction).
6. Best-effort `audit(evidence_stored)`.
7. If current state is not already `VERIFYING`: standalone `update_ownership_state(...→VERIFYING)` (no history row); outside grouped writes.
8. `A = update_ownership_state(VERIFYING→VERIFIED) + history(evidence_verified)`.
9. `A = update_ownership_state(VERIFIED→ACTIVE) + history(activated_with_evidence)`.
10. `complete_idempotency_record(...)` → `COMPLETED` + `SUCCEEDED`. **Final durable write.**

| Crash point | Last durable state | Backend effect? | Records available | Provable after restart | Must remain UNCERTAIN |
| --- | --- | --- | --- | --- | --- |
| After (1)/(3) | Ledger `INTENT_RECORDED`/`IN_PROGRESS` | No | Ledger | Execution intent only | Verification/activation |
| After (4) | State pre-`VERIFYING`; no evidence | **May have occurred** | Ledger + ownership | Backend read-back may show installed | Verification success; no promotion |
| After (5) | Valid `verified` evidence row | Yes (verification call) | + evidence bound to ownership/digest | Verification evidence is durable | Whether promotion is complete |
| After (7) | State `VERIFYING`, evidence durable | Yes | + evidence | Evidence-backed verification exists | Whether `VERIFIED`/`ACTIVE` was reached |
| After (8) | State `VERIFIED` + history | Yes | + history | Reconcile promotes `VERIFIED → ACTIVE` on evidence | No false `ACTIVE` without evidence |
| After (9) | State `ACTIVE` + history | Yes | Full state | Durable verified/active state | Nothing |
| After (10) | Ledger `COMPLETED` | Yes | Full ledger | Cached response | Nothing |

Recovery contract: `VERIFIED` + valid evidence is the only existing automatic route to
`ACTIVE`; `VERIFYING` without evidence stays `uncertain`. Evidence is always persisted
before lifecycle promotion. Stage 1B.2 deliberately kept `VERIFYING`, canonical body
persistence and backend effects out of grouped transactions.

---

### 3. `revoke_policy`

Durable write sequence:

1. Ledger intent `PENDING` / `INTENT_RECORDED`.
2. `A = update_ownership_state(→REVOKING) + history(revoke_initiated)` (unless already `REVOKED`/`REVOKING`).
3. For retry/`REVOKING`: trusted `_read_back_revoke` before any backend call. `missing`/`revoked` ⇒ pre-confirmed (no backend call); `installed`/`present` ⇒ deliberate reissue with a **fresh helper-side idempotency key**; unknown/error ⇒ `REVOKE_UNCONFIRMED`.
4. `_mark_operation_in_progress(...)` → `IN_PROGRESS`.
5. **Backend effect:** `backend.revoke_policy(...)`.
6. On `ok`: `_complete_revoke` re-reads backend; if confirmed, stores `revoked` evidence if absent, then `A = update_ownership_state(REVOKING→REVOKED) + history(revoke_completed_with_evidence)`.
   On non-`ok`/uncertain: stay `REVOKING`, append audit only.
7. `complete_idempotency_record(...)` → `COMPLETED` + `SUCCEEDED` or `UNCERTAIN`. **Final durable write.**

| Crash point | Last durable state | Backend effect? | Records available | Provable after restart | Must remain UNCERTAIN |
| --- | --- | --- | --- | --- | --- |
| After (1) | Ledger intent | No | Ledger | Intent only | Backend state |
| After (2) | `REVOKING` + history | No | + history | Revocation initiated | Backend effect |
| After (3, still present) | `REVOKING` | No new effect | Read-back result | Previous attempt not applied | Reissue outcome |
| After (5) | Still `REVOKING`; no evidence | **May have occurred** | Ledger + ownership | Read-back can prove revoked/missing/present | Revocation completion until confirmed |
| After (6, evidence) | `REVOKING` + `revoked` evidence | Yes | + evidence | Evidence durable before promotion | Final promotion until state changes |
| After (6, promoted) | `REVOKED` + history + evidence | Yes | Full ownership state | Terminal revocation proven by state **and** evidence | Nothing |
| After (7) | Ledger `COMPLETED` | Yes | Full ledger | Cached response replayed | Nothing |

Recovery contract: a terminal `REVOKED` state without matching evidence is never accepted
as proof; an uncertain/inconsistent read-back never triggers a duplicate backend call and
is reported as `REVOKE_UNCONFIRMED` / `uncertain`.

---

### 4. `inspect_policy`

Durable write sequence: ledger intent → ownership validation → canonical read-back pre-check →
`IN_PROGRESS` → **backend read effect** → optional canonical response enrichment →
`complete_idempotency_record`. No ownership lifecycle writes.

| Crash point | Last durable state | Backend effect? | Provable | Must remain UNCERTAIN |
| --- | --- | --- | --- | --- |
| After intent / `IN_PROGRESS` | Ledger `PENDING` | No | Intent/execution marker only | Inspection result |
| After backend call, before completion | Ledger `PENDING`/`IN_PROGRESS` | Read-only mock call may have occurred | Nothing beyond ledger | Result, until read/retry |
| After completion | Ledger `COMPLETED` | Read-only | Cached response replayable | Nothing |

Recovery contract: retry of a `PENDING` non-revoke ledger is rejected without a second
backend call; reconcile reports the pending row as `pending_no_auto_replay` with its
durable `operation_outcome`. No ownership promotion is possible on this path.

---

### 5. `remove_stale_policy`

Write shape is identical to `inspect_policy`: ledger intent → `IN_PROGRESS` → backend
`remove_stale_policy` effect → completion. No ownership lifecycle writes.

| Crash point | Last durable state | Backend effect? | Provable | Must remain UNCERTAIN |
| --- | --- | --- | --- | --- |
| After intent / `IN_PROGRESS` | Ledger `PENDING` | No | Intent/execution marker only | Whether stale removal was applied |
| After backend call, before completion | Ledger `PENDING`/`IN_PROGRESS` | **May have occurred** | Ledger only | Backend effect; no safe automatic replay |
| After completion | Ledger `COMPLETED` | As above | Cached response replayable | Nothing |

Recovery contract: pending row stays uncertain (`pending_no_auto_replay`); no duplicate
backend removal is issued; no ownership state is inferred from an intent record.

---

### 6. `reconcile_pending_operations`

Reconcile is the restart entry point, not a source of backend intent. Per target it may
write `reconciliation_status`, lifecycle CAS + history groups, and `revoked` evidence
before promotion; it validates ownership binding, canonical policy bodies and evidence
before any transition. Pending idempotency rows are only *reported* as uncertain — they
are never auto-replayed.

| Crash point | Last durable state | Backend effect? | Provable after restart | Must remain UNCERTAIN |
| --- | --- | --- | --- | --- |
| Mid-scan, before any write | Unchanged | Only `inspect_policy` read-backs | Previously committed intent preserved | Targets not yet examined |
| After `reconciliation_status` write | Status `uncertain`/`needs_verification`/`failed` | Read-backs only | Status marker is durable | Backend truth if read-back was unavailable |
| After lifecycle CAS + history | Advanced state (`INSTALLING`, `FAILED`, `ACTIVE`, `REVOKED`) | Read-backs only | State + history + evidence (where required) | Nothing for completed transition |
| After evidence, before promotion | `REVOKING` + `revoked` evidence (or `VERIFYING` + `verified` evidence) | Read-backs only | Evidence durable | Final promotion |
| During idempotency reporting | No write (report only) | Read-backs only | Pending rows are explicitly uncertain | Backend effect of those rows |

Recovery contract: bounded, fail-closed, repeatable. Each repeated invocation re-reads
authoritative state; CAS guards prevent conflicting ownership records; no state is
promoted without evidence and trusted read-back.

---

### Deferred exclusions carried in from Stage 1B.2 (assessment)

| Exclusion | Assessment for 1B.3 |
| --- | --- |
| Evidence before `REVOKED` promotion | Already enforced in `_complete_revoke` and reconcile. Stage 1B.3 adds crash tests for the between-evidence-and-promotion window; no semantic change. |
| Idempotency completion as final durable write | Already enforced. Do not move completion earlier; do not let a missing completion record trigger a duplicate backend effect. |
| Install-failure persistence reporting | Deliberately granular (`state_persisted` / `history_persisted` / `ownership_state_changed`) for R.01. Do not group into one transaction; cover crash between the two writes in tests. |
| `VERIFYING` transition | Assessed: a `VERIFYING` state **with** valid durable evidence plus trusted backend read-back is no longer an uncertain operation; a `VERIFYING` state **without** evidence must stay uncertain. Recovery improvement limited to the evidence-backed case. |
| Canonical policy-body persistence | Already validated on every trusted read-back. Do not group with lifecycle promotion; cover crash-after-body-persistence in tests. |

---

## Phase 2 — Recovery implementation

Only two evidence-supported improvements were made. No new ledger, no new lifecycle
state, no schema/migration, and no change to the public API.

### 2.1 Evidence-backed recovery of an interrupted `VERIFYING` state

`controller_service.py` now exposes `_find_valid_verification_evidence(rec, oid, family)`,
which applies the *same* binding rules already used by the `VERIFIED` reconciliation
branch (verification result, ownership record id, canonical digest, policy identity,
instance/network and address family). Genuine storage failures propagate as
`BrokerDBError`; there is no conversion to a backend-uncertainty outcome. The existing
`VERIFIED` branch was refactored to use this helper with identical semantics.

`reconcile_pending_operations` now treats `VERIFYING` as recoverable **only when both**:

1. a valid, ownership-bound `verified` evidence row is durably present, and
2. trusted backend read-back reports `installed` (no `backend_error`).

It then performs the same two CAS-guarded, history-recording `atomic_write()` groups as
`verify_policy`: `VERIFYING → VERIFIED` (`reconcile_verifying_evidence_verified`) and
`VERIFIED → ACTIVE` (`reconcile_verifying_activated_with_evidence`). Ownership identity
is re-asserted before each group. If the second group fails, the first remains committed
and a subsequent reconcile completes it through the pre-existing `VERIFIED` branch.
If the state advanced concurrently, the result is `verifying_state_changed`. Any
storage failure is reported as `RECONCILIATION_PERSISTENCE_FAILURE`.

With no evidence, mismatched evidence, or unavailable/inconsistent read-back the result
remains the original `verifying_state_uncertain` with `reconciliation_status='uncertain'`.
This preserves the J.9/J.18 contracts (verified by regressions) while closing the
"evidence durable, promotion incomplete" window.

State transitions are unchanged for: `INSTALLING + evidence` (still
`needs_verification`; explicit verify required), `VERIFIED` (existing evidence-backed
promotion), `REVOKING`/`REVOKED` (evidence required before promotion), install failure
(granular state/history writes), canonical body persistence, and idempotency completion.

### 2.2 Persistence classification for the reconciliation ledger scan

`get_pending_idempotency()` can fail; it is now called inside a guarded block so a
storage failure is recorded through `mark_persistence_failure()` and produces the
existing structured `RECONCILIATION_PERSISTENCE_FAILURE` response. Pending rows are
still only *reported* (`pending_no_auto_replay`) with their durable `operation_outcome`;
the ledger is never mutated by reconciliation and is never auto-replayed.

### 2.3 Deliberately rejected change

An initial version also converted a failed *initial authoritative ownership read* into
a structured reconciliation error. The F-02 regression
`test_reconcile_ownership_lookup_failure_is_not_treated_as_absence` requires raw
`BrokerDBError` propagation. That behavior was restored without weakening the test;
the new test now documents the preserved contract. No existing assertion was changed.

---

## Phase 3 — Deterministic crash tests

`broker/tests/test_post_j20_stage_1b3_durable_crash_recovery.py` — **24 passed**.

### 3.1 In-process fault injection (16 tests)

Covers: intent-only crash; ownership-intent group rollback with surviving ledger intent;
durable backend effect followed by crash with no duplicate effect and no fabricated
`ACTIVE`; evidence persisted before promotion with evidence-backed recovery;
`VERIFYING` without evidence / with mismatched evidence / with unavailable read-back
all remaining uncertain; bounded repeated recovery with no duplicate evidence or
history; `VERIFIED` history crash recovered by reconcile; crash before idempotency
completion with same-key retry rejected and no second backend effect; ledger-scan
storage failure classification; preserved raw storage-failure propagation on the
initial read; granular install-failure reporting (`failure_state_persisted=True`,
`lifecycle_history_persisted=False`); revoke evidence-before-promotion recovery with
one backend effect; conflicting duplicate distinct from pending/uncertain; and
corrupt canonical body preventing promotion.

### 3.2 Real spawned-process kills (8 tests)

Workers use `multiprocessing.get_context('spawn')` with a disposable SQLite DB and a
file-backed **mock** backend. `_CrashStore` calls `os._exit(9)` at named durable
boundaries (ledger intent, committed `atomic_write()` group, evidence commit,
immediately before idempotency completion). `_KillAfterBackendSave` kills **after** the
mock backend state has been flushed to disk, closing the prior instrumentation gap
where the `install_state_mutated` marker preceded `_be_save`.

Real-process coverage:

- kill after idempotency intent — `PENDING`, no ownership, no backend effect;
- kill after the ownership `REQUESTED` group — committed intent, history, no backend effect;
- kill after a **durably saved** backend effect — `needs_verification`, never `ACTIVE`,
  repeated reconcile stable, backend effect not repeated;
- kill after verification evidence commit — evidence survives, no false promotion;
- kill after the `VERIFIED` history group — fresh reconcile promotes `ACTIVE`, repeat adds
  no history;
- kill before idempotency completion — no fabricated response, pending row reported;
- unavailable read-back in a fresh process — uncertain, state unchanged;
- kill during revoke evidence persistence — fresh reconcile promotes `REVOKED` once,
  repeated reconcile adds no history.

Assertions check no false `ACTIVE`/`REVOKED`, no fabricated success, no duplicate
backend effect, no conflicting ownership records, no lost committed intent, stable
idempotency behavior, explicit uncertainty, and bounded/repeatable recovery. Existing
assertions were not weakened.

---

## Phase 4 — Regression evidence

| Run | Result | Evidence |
| --- | --- | --- |
| New Stage 1B.3 suite | **24 passed, 1 warning, 23.65s, exit 0** | `post_j20_stage_1b3_new_suite.stdout.txt` / `.exit.txt` |
| Early Stage 1B.1/1B.2/J.9/J.18 check | **56 passed, exit 0** | `post_j20_stage_1b3_early_regression.*` |
| Refix verification after F-02 contract restoration | **25 passed, exit 0** | `post_j20_stage_1b3_refix.*` |
| Required targeted suites (1B.1, 1B.2, J.8, J.9, J.10, J.12, J.13, J.17, cross-process/crash-boundary, persistent recovery, revoke recovery, persistence-failure closure, revoke remediation, residual risk) | **376 passed, 1 warning, 270.06s, exit 0** | `post_j20_stage_1b3_targeted.stdout.txt` / `.exit.txt` / `.elapsed.txt` |
| Full broker suite | **913 passed, 0 failed, 0 errors, 1 warning, 421.26s (0:07:01), actual exit 0** | `post_j20_stage_1b3_broker_full.stdout.txt` / `.stderr.txt` / `.exit.txt` / `.elapsed.txt` |

Stage 1B.2 baseline was **889 passed, exit 0**; delta is **+24 tests**, with no tests
removed, skipped, or weakened. Warnings remain the pre-existing `PytestDeprecationWarning`
and `PydanticDeprecatedSince20`. The full-suite stderr capture contains only the
pytest-asyncio configuration warning emitted by the harness.

One targeted-run failure was investigated and fixed by restoring the pre-existing F-02
raw-`BrokerDBError` propagation contract (no assertion weakening); the complete targeted
and full suites were then re-run green.

---

## Idempotency and backend-effect guarantees

- No backend effect is ever repeated merely because completion persistence is missing.
  A `PENDING` non-revoke ledger still yields `FirewallControllerIdempotencyError`; revoke
  recovery still requires trusted read-back before any reissue.
- Intent records alone never prove backend execution. `ACTIVE` requires durable
  verification evidence; `REVOKED` requires durable revocation evidence and read-back.
- Operation identity and digest correlation remain on the single existing
  `controller_idempotency` ledger; reconciliation only reads and reports it.
- SQLite transactions remain database-only. Mock backend state is never claimed to
  participate in a SQLite transaction; no end-to-end atomicity is asserted.
- Genuine storage failures remain distinct from uncertain backend outcomes
  (`BrokerDBError` / `PERSISTENCE_FAILURE` / `RECONCILIATION_PERSISTENCE_FAILURE` vs
  `REVOKE_UNCONFIRMED` / `uncertain`).

## Remaining limitations and risks

- `INSTALLING` with durable verification evidence is still reported as
  `needs_verification` and requires an explicit `verify_policy` to promote. This is a
  conservative choice: evidence-backed promotion was implemented only for the explicit
  `VERIFYING` recovery window.
- Backend read-back in the mock is a test seam; it cannot prove real host firewall
  truth. RR-05/RR-06/M-06/M-01 remain only partially mitigated and **OPEN**.
- The F-02 raw-error propagation contract on initial ownership lookup is intentionally
  unchanged; callers must still classify `BrokerDBError` distinctly.
- Install-failure state and history writes remain deliberately separate for R.01
  reporting; a crash between them is detectable but not repaired.
- No gate closure is claimed. T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**;
  **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**. Stage 1B.4+ was not started.
