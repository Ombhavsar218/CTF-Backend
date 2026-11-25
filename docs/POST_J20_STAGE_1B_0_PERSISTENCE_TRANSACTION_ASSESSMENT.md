# Post-J.20 Stage 1B.0 — Persistence and Transaction Integrity Assessment (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Branch:** `main`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged)  
**Milestone:** Stage 1B.0 (assessment/planning only; **no source changes**)  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

## 1. Baseline and preservation

| Item | Evidence |
|---|---|
| Stage 1A.5 | **VERIFIED (scoped)** per `docs/POST_J20_STAGE_1A_5_FRESH_DB_INITIALIZATION_REMEDIATION.md` (preserved). Cross-process fresh-DB schema init serialized via per-DB init lock in `broker/app/db.py` (`BrokerDB._init_guard`, guarded base `_init_schema`) and `broker/firewall_controller_service/ownership_store.py` (guarded controller `_init_schema`). |
| Full broker suite (1A.5) | **854 passed, 0 failed, 0 errors, 0 skipped, 1 warning, 322.62s (0:05:22), actual exit 0** (`post_j20_stage_1a5_broker_full.*`, preserved). |
| Git state (assessment time) | 26 pre-existing modified tracked files preserved; untracked artifacts preserved (including Stage 1A.1–1A.5 docs/tests/captures). No reset/clean/revert/staging/commit performed. |
| Scope boundary | Mock-only source-backed assessment/planning for **RR-05, RR-06, M-06, M-01**. No implementation, no gate closures, no Docker/live integration, no host/privileged/transport/runtime operations. |

**Primary source evidence (inspected):**
- `broker/firewall_controller_service/controller_service.py` (1653 lines): auth/validation, idempotency, ownership binding, lifecycle dispatch, install/verify/revoke flows, `reconcile_pending_operations`, canonical read-back/evidence/revoke helpers.
- `broker/firewall_controller_service/ownership_store.py`: schema/tables/indexes/triggers, connection/transaction primitives, CRUD/CAS/evidence/idempotency/canonical-body methods.
- `broker/app/db.py`: connection, init lock, base schema init, execute/query wrappers.
- Existing tests (representative): `test_firewall_controller_j13_transaction_boundary_and_recovery.py`, `test_firewall_controller_j17_persistence_integrity.py`, `test_firewall_controller_j8_hardening.py`, `test_firewall_controller_j9_reconciliation_integrity.py`, `test_firewall_controller_cross_process_crash_recovery.py`, `test_firewall_controller_persistence_failure_closure.py`, `test_firewall_controller_revoke_recovery_and_idempotency_hardening.py`, `test_firewall_controller_canonical_*`, `test_firewall_controller_j12_fault_injection_and_races.py`, etc.

## 2. Lifecycle operation inventory

| Operation (entry) | Core purpose | Primary service path | Persistence writes (by table/method, indicative) | Backend/external side effects |
|---|---|---|---|---|
| `health_check` | Liveness/health response | `_call("health_check")` → `backend.health_check` | Idempotency create/complete only when `idempotency_key` supplied (after validation/auth/ownership checks as applicable) | Backend health call |
| `install_policy` | Persist intent, validate/canonicalize, invoke backend install, advance install-phase state, persist canonical body | `_call("install_policy")` | `create_idempotency_record` (PENDING); `create_ownership` (REQUESTED intent) or revalidate existing; `record_audit` (intent); `record_lifecycle_transition` (REQUESTED/VALIDATING/INSTALLING as applicable); `update_ownership_state` (CAS, VALIDATING/INSTALLING/FAILED paths); `ensure_canonical_policy_body` → `store_canonical_policy_body`/read-trusted checks; on completion `complete_idempotency_record` (+ in-memory cache) | `backend.install_policy` (after intent/state/canonical persistence steps in covered path) |
| `verify_policy` | Confirm backend install, persist verification evidence, promote VERIFYING→VERIFIED→ACTIVE | `_call("verify_policy")` | Idempotency create/complete; `store_evidence` (verified); `record_audit` (evidence_stored, best-effort in some paths); `update_ownership_state` (VERIFYING, VERIFIED, ACTIVE, CAS/version-checked); `record_lifecycle_transition` (each promotion) | `backend.verify_policy`; trusted canonical read-back checks when canonical body exists |
| `revoke_policy` | Move to REVOKING, confirm backend removal/read-back, persist revocation evidence, promote to REVOKED | `_call("revoke_policy")`, `_complete_revoke`, `_store_revocation_evidence`, `_has_revocation_evidence` | Idempotency create/complete/recovery handling; `update_ownership_state` (REVOKING/REVOKED, CAS-aware); `record_lifecycle_transition`; `store_evidence` (revoked) via direct/recovery/reconcile helpers; `record_audit` (e.g. `revoke_backend_not_confirmed`) | `backend.revoke_policy` (when not already done/preconfirmed/uncertain), `backend.inspect_policy` read-backs (`_read_back_revoke`) |
| `inspect_policy` | Read authoritative ownership/canonical state and backend state | `_call("inspect_policy")` | Idempotency create/complete; reads trusted canonical body when present (no lifecycle mutation intended) | `backend.inspect_policy` |
| `remove_stale_policy` | Stale-policy removal/cleanup path (ownership-authorized) | `_call("remove_stale_policy")` | Idempotency create/complete; ownership/canonical pre-checks (no additional lifecycle mutation observed in inspected dispatch beyond common flow) | `backend.remove_stale_policy` |
| `reconcile_pending_operations` | Per-policy or scan reconciliation; fail-closed recovery/promotion decisions from persisted ownership/evidence/canonical body/backend read-back | `reconcile_pending_operations` | `record_audit` (e.g. unknown state, revoked-without-evidence), `update_ownership_state`, `record_lifecycle_transition`, `update_reconciliation_status`, `store_evidence` (revocation evidence in REVOKING→REVOKED recovery when missing), read/validate canonical bodies/evidence; reports pending idempotency as uncertain (no auto-replay) | `backend.inspect_policy` read-backs per target; no adoption of unknown backend rules |

**Lifecycle states (service FSM):** `REQUESTED, VALIDATING, INSTALLING, VERIFYING, VERIFIED, ACTIVE, REVOKING, CLEANUP_PENDING, FAILED, REVOKED, ORPHANED` with explicit allowed transitions (`controller_service.py` `LIFECYCLE_TRANSITIONS`, `_check_lifecycle_transition`).

## 3. Persistence write map

| Store/table | Key fields / purpose | Written by (store methods) | Durability/constraints (observed) |
|---|---|---|---|
| `controller_ownership` | `ownership_record_id` PK, unique `(policy_id, policy_version)`, authoritative binding (`instance_id`, `network_id`, digest/family), `installation_state`, `lifecycle_version` (CAS), reconciliation/status timestamps | `create_ownership`, `update_ownership_state` (CAS), `update_reconciliation_status` | Per-method transactions (`BEGIN IMMEDIATE` in create/update-state; `_execute_fk` autocommit transaction for reconciliation status); lifecycle version increment on state update |
| `controller_lifecycle_history` | Append-only transition/event history (`prev/new_state`, operation/request, reason/result/error/timestamp) | `record_lifecycle_transition` (`_execute_fk` insert) | Append-only triggers `BEFORE UPDATE/DELETE ... RAISE(ABORT, 'append-only record')` (J.17 hardening) |
| `controller_evidence` | Verification/revocation evidence records bound to ownership/policy/version/instance/network/digest/family/result | `store_evidence` | Insert-only semantics; append-only triggers block update/delete; evidence validity checked by service/reconcile logic (binding + result-specific) |
| `controller_audit` | Audit/event trail (`event_type`, request/operation/policy/ownership, details JSON) | `record_audit` (`_execute_fk`) | Append-only triggers; failures surfaced as `BrokerDBError('Audit persistence failed')` in store (callers vary: some treat audit as best-effort) |
| `controller_idempotency` | PK `(idempotency_key, operation_type)`, `request_digest`, status PENDING→COMPLETED, `response_json`, recovery/ownership metadata | `create_idempotency_record`, `complete_idempotency_record`; read via `get_idempotency_record`/`get_pending_idempotency` | Separate transactions per create/complete; uniqueness collision used for conflict/pending classification; pending records treated as uncertain/no auto-replay in reconciliation |
| `controller_policy_bodies` | Canonical schema-v1 rules/digests/bindings, FK to `controller_ownership` | `store_canonical_policy_body`, `ensure_canonical_policy_body`; trusted read via `read_trusted_canonical_policy_body`/`get_canonical_policy_body` | Validated/bound insert in transaction with ownership checks; unique `(policy_id, policy_version)`; FK enforced on FK-enabled connections |

**Schema/init/integrity controls:** `BrokerDB` + store init use per-DB init lock (1A.5), `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON` on relevant connections, uniqueness/indexes, append-only triggers for history/evidence/audit, CAS on ownership state updates, request/identifier validation and trusted canonical read-back fail-closed in covered paths.

## 4. Transaction-boundary diagram

```text
Caller/API
  -> FirewallControllerService._call(operation)
       [auth + request/schema validation + canonical-id checks]  (no durable write intended)
       [pre-idempotency conflict checks / ownership read+binding]
       [optional idempotency PENDING create] ------------------- TX#A (store.create_idempotency_record; own conn, BEGIN IMMEDIATE, commit/rollback)
       [install intent / transitions] --------------------------- TX#B.. (create_ownership / update_ownership_state / record_lifecycle_transition / record_audit / ensure_canonical_policy_body; EACH is separate conn+tx)
       [backend side effect: install/verify/revoke/inspect/remove_stale/read-back]  (outside DB tx)
       [post-backend state/evidence/history updates] ----------- TX#C.. (store_evidence, update_ownership_state, record_lifecycle_transition, audit; separate txs)
       [complete idempotency response] ------------------------- TX#D (store.complete_idempotency_record)

Reconciliation (per target record / scan)
  [read ownership/canonical/evidence] -> [backend inspect read-back] (outside DB tx)
  -> [conditional CAS state/history/recon-status/evidence/audit writes]  (multiple separate txs/method calls)
  -> [scan pending idempotency; classify uncertain/no auto-replay] (read/report)

Legend: TX boundaries are per store method/connection today (not a single atomic unit spanning backend effects and multi-table lifecycle outcome).
```

## 5. Crash-window matrix

| Phase / window | Example operations | Durable state possible at crash | Recovery/observation behavior (source-backed) | Risk classification |
|---|---|---|---|---|
| After idempotency PENDING create, before intent/ownership/state effects | install/revoke/verify paths | PENDING idempotency record exists; ownership/state may be unchanged | Replay handling distinguishes completed vs pending/conflict; reconcile reports pending idempotency as uncertain/no auto-replay; revoke has recovery/read-back handling in covered paths | **Uncertain outcome window** (bounded by fail-closed handling; not auto-promoted) |
| After intent ownership (REQUESTED) persisted, before backend call completes/response observed | install | Ownership REQUESTED (+ history/audit in parts) may exist without confirmed backend install | Reconcile inspects backend: missing+uncertain states can be marked FAILED/needs-verification per state/read-back; no adoption of unknown backend objects | **Recoverable/uncertain** if read-back unavailable; fail-closed bias |
| After backend install succeeds, before durable INSTALLING/VERIFYING/ACTIVE promotion or before response/idempotency completion | install/verify | Backend may be installed; DB may lag (REQUESTED/INSTALLING/VALIDATING/VERIFYING/partial) or idempotency may remain PENDING | Reconcile: backend installed in uncertain install states => needs_verification (no promotion to ACTIVE without evidence); VERIFYING treated uncertain/fail-closed in covered logic; repeated recovery must not falsely activate | **Uncertain but safety-biased** (no false ACTIVE without evidence in covered paths) |
| Between evidence persistence and lifecycle promotion, or between VERIFYING→VERIFIED→ACTIVE steps | verify | Evidence row may exist while state not fully promoted; or promotions split across separate txs | CAS/version checks and explicit transitions; reconcile can promote VERIFIED→ACTIVE only with valid matching evidence/bindings; VERIFYING without promotable proof remains uncertain | **Partial-progress window** (RR-05/M-01 relevant) |
| During revoke: REVOKING persisted, backend/read-back/evidence/final REVOKED split across steps | revoke/reconcile | REVOKING may persist without confirmed removal or without revocation evidence/final REVOKED | Reconcile/read-back confirms backend missing/revoked before promotion; requires/persists revocation evidence; terminal REVOKED accepted only with matching evidence; unknown read-back => uncertain | **Uncertain/recoverable with fail-closed evidence gate** |
| After state/history commit but before idempotency completion/response return | install/verify/revoke | Durable lifecycle/evidence progress may exist while caller lacks completed response | Idempotency replay/recovery/reconcile derive from persisted state/evidence/read-back; no fabricated success response from missing completion alone | **Caller-uncertainty / replay window** |
| Persistence failure mid-sequence (single-method tx rollback or inter-step failure) | all mutating ops | Method-local tx rolls back; prior committed txs may remain (multi-tx operation) | Store/service raise fail-closed persistence/permission/request errors in covered paths; install-failure persistence guarded (`_raise_install_failure_persistence_error`); reconcile reports `RECONCILIATION_PERSISTENCE_FAILURE` on persistence errors | **Atomicity gap across operations** (RR-05/M-01/M-06) |

## 6. Existing guarantees and limitations

### Guarantees (evidenced in covered/mock paths)
- **Init safety (1A.5):** cross-process schema init serialized per DB via init lock; idempotent DDL.
- **Per-method transactional integrity:** key store writes use `BEGIN IMMEDIATE` + commit/rollback on own connections; FK enabled on FK connections; uniqueness/CAS checks enforced (ownership uniqueness, idempotency PK, policy-body uniqueness/FK/binding checks, ownership `lifecycle_version` CAS).
- **Append-only history/evidence/audit:** SQLite triggers prevent update/delete on lifecycle history, evidence, audit.
- **Idempotency semantics:** request-digest binding, conflict detection, pending/completed handling, replay validation, revoke recovery paths; pending records not auto-replayed (reconcile marks uncertain).
- **Canonical authority/binding:** trusted canonical policy-body validation/read-back (schema/rules/digest/ownership binding), fail-closed on corruption/mismatch in covered operations; no silent legacy-to-schema-v1 conversion.
- **Fail-closed recovery posture:** reconcile/verify/revoke paths avoid false ACTIVE/REVOKED success without required evidence/read-back confirmation in inspected logic; backend/read-back uncertainty => uncertain/no promotion.
- **Test evidence (representative):** crash/reopen/recovery/concurrency/fault-injection/transaction-boundary/integrity suites exist (e.g. J.8, J.9, J.10, J.12, J.13, J.17, cross-process crash recovery, revoke recovery/idempotency hardening, persistence failure closure, canonical lifecycle/persistence) with passing Stage 1A.5 full-suite baseline.

### Limitations / gaps
- **Non-atomic multi-step operations (RR-05/M-01):** lifecycle operations span multiple independent store transactions and backend side effects; no single DB transaction covers intent + canonical body + state/history/evidence + idempotency completion + backend outcome.
- **Split persistence domains:** ownership/lifecycle/evidence/audit/idempotency/canonical bodies are updated in separate calls/transactions; partial progress is possible on crashes/failures between commits.
- **Idempotency-completion vs lifecycle-outcome coupling:** completion persisted after operation outcome assembly; crash after durable lifecycle progress but before completion leaves recovery to state/evidence/read-back/replay logic rather than a single atomic intent ledger.
- **Audit durability coupling:** audit writes are often separate and sometimes best-effort relative to business outcome; failures may be surfaced differently by path.
- **Reconciliation is bounded/read-back-driven:** cannot prove backend truth when read-back unavailable; some states intentionally remain uncertain (safe, but not self-healing).
- **Coverage boundaries:** guarantees are mock-only/service-store scoped; not proof of real helper/transport/kernel/host/distributed behavior.

## 7. RR-05 / RR-06 / M-06 / M-01 traceability

| Gap | Assessment (source-backed) | Current controls | Residual risk |
|---|---|---|---|
| **RR-05 — lifecycle operation atomicity** | Install/verify/revoke execute sequences of independent txs (idempotency, ownership create/update, history, audit, canonical body, evidence, completion) interleaved with backend calls; no single all-or-nothing unit | Method-local tx rollback, CAS/version checks, FSM checks, fail-closed install-failure persistence handling, evidence-gated promotions | **Open:** partial multi-table progress/crash windows can leave recoverable-but-incomplete states; correctness relies on recovery/reconcile/idempotency rather than atomic commit |
| **RR-06 — crash recovery and reconciliation** | Reconcile derives actions from persisted ownership/evidence/canonical body and backend read-back; promotes/marks states conservatively; treats pending idempotency as uncertain/no auto-replay | VERIFIED/REVOKING/uncertain install handling, revocation evidence enforcement, no unknown-backend adoption, persistence-failure reporting, extensive J.8/J.9/J.10/J.13/J.17/cross-process tests | **Partially mitigated, open:** recovery safe/fail-closed in covered cases but dependent on read-back availability and cannot resolve all uncertain windows automatically |
| **M-06 — durable consistency and evidence integrity** | Evidence/history/audit append-only; canonical body validated/bound; evidence matched by ownership/policy/version/digest/identity/family before promotion/acceptance in covered paths | Triggers, FK/uniqueness, trusted canonical read-back, CAS, revocation-evidence requirements, replay validation | **Partially mitigated, open:** cross-table consistency across separate txs not guaranteed atomically; some audit/event durability semantics are path-dependent |
| **M-01 — transaction boundaries and state-transition correctness** | FSM and CAS enforced per transition; boundaries are per-method/per-write with backend calls outside tx; identity/binding revalidated in critical paths | `_check_lifecycle_transition`, `lifecycle_version` CAS, ownership identity/binding checks, pre/post revalidation in verify/revoke/install flows | **Partially mitigated, open:** correct local transitions but globally non-atomic sequences; stale/interleaved outcomes controlled by CAS/fail-closed logic rather than transactional isolation across the full operation |

## 8. Prioritized, incremental remediation plan (no implementation in this milestone)

1. **(P0) Define and document an explicit operation intent/outcome ledger contract (design/spec, additive)**  
   - Model phases: `intent_recorded`, `backend_effect_requested/observed`, `evidence_persisted`, `terminal_state_committed`, `response_completed`, `uncertain`.  
   - Map each lifecycle operation to required durable markers using existing tables where possible (avoid competing lifecycle model).  
   - Acceptance: written state/outcome matrix approved for RR-05/RR-06 implementation scope.

2. **(P1) Reduce critical multi-tx windows for verify/revoke completion paths (targeted, additive)**  
   - Evaluate grouping tightly-coupled same-domain writes into single transactions where safe (e.g. evidence insert + ownership CAS promotion + lifecycle history for a single transition step) via store-level composite methods, preserving append-only/CAS semantics.  
   - Keep backend side effects outside DB tx; ensure crash between backend confirmation and commit remains representable as uncertain/recoverable.  
   - Acceptance: targeted tests prove no false ACTIVE/REVOKED on injected commit failures at new boundaries; replay/reconcile remain deterministic.

3. **(P1) Strengthen install-path intent/progress atomicity**  
   - Minimize split between ownership intent, canonical body persistence, and initial state transitions where feasible; ensure canonical-body presence/absence is unambiguous for recovery.  
   - Acceptance: crash-injection matrix shows each window resolves to fail-closed/recoverable state without duplicate or false-active promotion.

4. **(P2) Idempotency completion coupling and recovery metadata**  
   - Make completion persistence and recovery metadata robust to post-commit/pre-response loss (already partially handled); formalize invariants so PENDING+durable terminal evidence/state cannot yield unsafe replay.  
   - Acceptance: deterministic replay/reconcile outcomes for committed-but-uncompleted response scenarios.

5. **(P3) Reconciliation hardening within read-back limits**  
   - Improve classification/reporting for unresolved partial-progress states (explicit uncertain reasons, bounded operator-safe signals) without auto-healing beyond evidence/read-back truth.  
   - Acceptance: expanded recovery/concurrency tests; no unsafe promotions.

6. **(P4) Audit/event consistency policy**  
   - Decide and enforce per-operation audit criticality (must-fail vs best-effort) consistently with fail-closed semantics; avoid audit side effects changing safety decisions except where required.

**Sequencing constraint:** implement incrementally per operation/path with regression gates after each slice; reuse existing schema/contracts (`controller_ownership`, `controller_idempotency`, `controller_evidence`, `controller_lifecycle_history`, `controller_policy_bodies`, `LIFECYCLE_TRANSITIONS`) and avoid competing lifecycle models.

## 9. Exact proposed files likely to change (implementation phases, if authorized)

| File | Likely changes (incremental) |
|---|---|
| `broker/firewall_controller_service/ownership_store.py` | Composite transactional helpers for coupled writes (evidence+state+history/CAS), optional intent/outcome marker support, stricter error propagation; preserve schema/triggers/constraints |
| `broker/firewall_controller_service/controller_service.py` | Reordered/adjusted sequencing to use composite store operations, explicit outcome handling around backend boundaries, reconciliation/refined recovery decisions aligned to intent/outcome contract |
| `broker/firewall_controller_service/rule_schema_v1.py` / `schemas.py` (only if required) | Additive metadata/validation support for durable intent markers (avoid breaking existing contracts) |
| `broker/tests/test_firewall_controller_j13_transaction_boundary_and_recovery.py` | Extend crash-window/commit-failure/replay assertions for new boundaries |
| `broker/tests/test_firewall_controller_j17_persistence_integrity.py` | Extend integrity/CAS/append-only/partial-progress coverage |
| `broker/tests/test_firewall_controller_j8_hardening.py`, `..._j9_reconciliation_integrity.py`, `..._j10_reconciliation_hardening.py` | Reconciliation/promotion/fail-closed regressions |
| `broker/tests/test_firewall_controller_cross_process_crash_recovery.py`, `..._j12_fault_injection_and_races.py`, `..._persistent_recovery_integration.py` | Cross-process crash/recovery/race coverage |
| `broker/tests/test_firewall_controller_persistence_failure_closure.py`, `test_firewall_controller_revoke_recovery_and_idempotency_hardening.py` | Persistence-failure and revoke/idempotency outcome regressions |
| New focused tests (e.g. `test_post_j20_stage_1b_*`) | Operation-specific atomicity/intent-ledger and crash-injection cases as needed |
| `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md`, `docs/PHASE_2L_2J_14_REMEDIATION_ROADMAP.md` (and phase evidence docs) | Evidence-backed status notes only when criteria met (no premature closure) |

## 10. Regression strategy

- **Per-slice verification:** run focused new/updated tests for touched operation + directly related suites (J.8–J.10, J.12, J.13, J.17, cross-process crash/recovery, revoke recovery/idempotency, persistence failure closure, canonical persistence/lifecycle/integration).
- **Crash/fault injection:** inject commit/connection/execute failures at each newly defined boundary (store-level monkeypatch/fault hooks in tests) and assert rollback/no partial durable inconsistency/no false ACTIVE|REVOKED|success.
- **Concurrency/races:** in-process and cross-process same-key/same-policy/version races, CAS conflicts, stale snapshots, reopen-after-crash recovery.
- **Idempotency/replay:** same-key same-payload replay, same-key different-payload conflict, pending/non-completed recovery, completed-response replay determinism.
- **Reconciliation:** backend installed/missing/unavailable/ambiguous read-backs across all relevant states; evidence present/missing/mismatched/corrupt; repeated reconcile idempotence.
- **Canonical integrity:** trusted read-back required/absent/corrupt/mismatched bindings and digests fail closed.
- **Non-regression/full confidence:** targeted batches then full `broker/tests -q` and `manager/tests -q` (and `manage.py check` where appropriate) before claiming milestone evidence; preserve raw outputs/exit codes.

## 11. Dependencies and acceptance criteria

**Dependencies**
- Stage 1A.5 baseline preserved (init serialization, 854/0/0/0, exit 0).
- Existing schema/contracts and FSM (`LIFECYCLE_TRANSITIONS`, ownership/evidence/idempotency/canonical-body models) treated as authoritative unless separately justified.
- No gate closures without acceptance evidence; T-11/T-13/T-27 remain OPEN — ACCEPTANCE REQUIRED.
- Mock-only environment; no Docker/runtime/host/privileged/transport/live integration required or authorized.

**Acceptance criteria for future Stage 1B implementation slices (evidence-based)**
- **RR-05:** for each in-scope lifecycle operation, documented intent/outcome boundaries with tests proving no false success/ACTIVE/REVOKED on crash/failure at those boundaries and no unsafe partial commits across defined atomic groups.
- **RR-06:** deterministic, fail-closed recovery/reconciliation for covered crash windows (including reopen), with explicit uncertain outcomes when truth unavailable and no unsafe auto-promotion/adoption.
- **M-06:** durable cross-record consistency guarantees demonstrated for defined atomic groups; evidence/history/audit/canonical integrity preserved under fault/concurrency/reopen scenarios.
- **M-01:** transaction boundaries and FSM/CAS transitions explicitly mapped and enforced; stale/concurrent transitions cannot produce invalid promotions or ownership/canonical binding violations.
- **Regression:** all existing relevant suites and new slice tests pass; full broker (and manager, as applicable) green with captured outputs/exit codes; no unauthorized gate closure.

## 12. Assessment completeness and final decision

**Evidence completeness:** lifecycle operations, persistence writes, per-method transaction behavior, multi-tx/backend-interleaved flows, crash/recovery behavior, and existing protections/tests were traced from inspected source (`controller_service.py`, `ownership_store.py`, `broker/app/db.py`) and representative test suites; gaps and dependencies identified with incremental plan.

**Final decision:** **VERIFIED** — assessment evidence is complete for this planning milestone (source-backed inventory/map/diagram/crash matrix, guarantees/limitations, RR-05/RR-06/M-06/M-01 traceability, prioritized plan, proposed files, regression strategy, dependencies/acceptance criteria) within mock-only scope. **No source changes made. No gates closed. Stage 1B implementation not started.**

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**
