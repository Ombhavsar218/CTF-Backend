# Phase 2L.2J.17 — Engineering Remediation Report (Persistence Integrity and Recovery Determinism, Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Branch:** `main...origin/main` | **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged)  
**Date:** 2026-11-16  
**Scope:** J.17 only (mock-only). No live infrastructure, no host validation, no privileged operations, no destructive migrations.

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

## 1. Objective

Address remaining mock-only persistence-integrity and recovery weaknesses from J.14/J.3–J.16: inventory persistent entities, add smallest safe compatibility-preserving integrity improvements for demonstrated defects, document multi-table transaction behavior, extend deterministic/test-only fault-injection and recovery/concurrency coverage, and preserve J.3–J.16 controls.

## 2. Baseline established and preserved

- Repo root `E:\Flag-hunt\ctf-platform-be`, HEAD `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` on `main...origin/main` (unchanged).
- Pre-existing 26 modified tracked files and pre-existing untracked files/directories preserved (including `broker/`, `docs/`, existing J.15/J.16 implementation/test/doc artifacts).
- No `git reset`/`git clean`/`git checkout --`/broad revert/staging/commits performed.
- Inspected schema/init/transaction boundaries in `broker/firewall_controller_service/ownership_store.py`, service usage in `controller_service.py`, DB layer `broker/app/db.py`, and existing J.12/J.13/fault-injection/recovery tests.

## 3. Workstream A — Persistence integrity inventory

- Created `docs/PHASE_2L_2J_17_PERSISTENCE_INTEGRITY_MATRIX.md` covering `controller_ownership`, `controller_lifecycle_history`, `controller_evidence`, `controller_idempotency`, `controller_audit`, and `controller_policy_bodies` with PK/FK/unique/required/nullable/CHECK/index/mutability/append-only expectations, transaction boundaries, recovery behavior, tests, and remaining gaps.
- Distinguished actual implementation defects/weaknesses from missing evidence and compatibility-constrained gaps (e.g. append-only not DB-enforced pre-J.17, inconsistent per-connection FK enforcement in store paths, missing DB CHECK/FK/digest constraints, multi-table non-atomic sequences, incomplete hookable boundary matrix).

## 4. Workstream B — Additive database integrity improvements (compatibility-preserving)

**File:** `broker/firewall_controller_service/ownership_store.py` (smallest safe changes)

- **Append-only DB enforcement (demonstrated integrity weakness):** added additive `CREATE TRIGGER IF NOT EXISTS` guards in `_init_schema` to block `UPDATE`/`DELETE` on `controller_lifecycle_history`, `controller_evidence`, and `controller_audit` (`append-only record`). Applied on fresh init and existing-schema reopen without data rewrite/destruction.
  - Security property: prevents direct in-place mutation/deletion of historical/evidence/audit records through normal SQLite operations in covered environments; strengthens M-06/RR-06 evidence-integrity aspects (not full immutability guarantee against schema/admin bypass).
- **FK enforcement consistency for store-managed connections (demonstrated gap):** added `_get_conn_fk()` (sets `PRAGMA foreign_keys=ON` per connection) and `_execute_fk()`; switched transactional and key write paths (`create_ownership`, `store_evidence`, `update_ownership_state`, `create_idempotency_record`, `complete_idempotency_record`, `store_canonical_policy_body`, `record_lifecycle_transition`, `record_audit`, `update_reconciliation_status`) to use FK-enforcing connections/helpers while preserving existing error contracts where applicable.
  - Security property: ensures FK constraints (notably `controller_policy_bodies -> controller_ownership`) are enforced for store-managed operations; reduces silent referential-integrity bypass risk in covered paths.
- **No destructive migrations:** no table rebuilds, no data rewrites/resets/deletes, no legacy-record conversion. Existing-schema reopen and fresh temporary DB behavior tested.

## 5. Workstream C — Lifecycle history and evidence integrity

- Append-only behavior now DB-enforced for lifecycle history, evidence, and audit via triggers (additive). J.17 tests verify direct UPDATE/DELETE attempts fail and records remain intact.
- Conflicting/duplicate evidence insertion and tamper/mismatch scenarios tested to ensure no false ACTIVE/VERIFIED promotion in covered paths; recovery/reconcile remains fail-closed where required.
- Remaining: no FKs/CHECKs/transition-validity constraints for history/evidence/audit tables, multi-table atomicity incomplete, possible schema/admin bypass outside covered trigger protections (documented, not claimed closed).

## 6. Workstream D — Multi-table transaction integrity

- Documented per-operation transaction boundaries in `docs/PHASE_2L_2J_17_PERSISTENCE_INTEGRITY_MATRIX.md`: ownership/state/idempotency/evidence/canonical-body/history/audit operations are largely executed in separate transactions (per-method BEGIN IMMEDIATE/commit or single-statement executes), so cross-table partial states are possible.
- No broad transaction redesign performed (no demonstrated need justifying risky redesign). J.17 tests verify partial/uncertain states remain recoverable and fail closed (no false ACTIVE/VERIFIED) in covered scenarios.
- No claim of full atomicity across all lifecycle operations.

## 7. Workstream E–G — Deterministic fault injection, idempotency/concurrency, recovery

- Extended test-only, disabled-by-default coverage in `broker/tests/test_firewall_controller_j17_persistence_integrity.py` (**20 tests**) using disposable DBs/store wrappers/connection instrumentation, direct adversarial DB states (where safe), barrier-based races, and reopen/retry/recovery simulations.
- Covered/added cases include: fresh DB and existing-schema reopen with additive protections preserved; append-only enforcement for history/evidence/audit; FK enforcement on store-managed policy-body writes; commit-failure rollback/no partial state (ownership create, state update), no false promotion; response-loss/uncertain-outcome reopen and repeated recovery fail-closed; same-key replay/conflict, concurrent install/create races, stale version/ownership-change/binding failures; corrupt/missing/mismatched canonical body and CAS stale-snapshot rejection with fail-closed recovery.
- Created `docs/PHASE_2L_2J_17_FAULT_INJECTION_MATRIX.md` mapping required injection points to achieved coverage and documented approximations/gaps (e.g. true post-commit/pre-response hook approximated, exhaustive intra-tx/hookable boundary and state matrices incomplete).
- Preserved J.10 retry limits/elapsed-time deadline behavior (no production logic change).

## 8. Compatibility fix for stronger integrity (test-only)

- Updated `broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py::test_revocation_evidence_requires_matching_family` to seed mismatched evidence via append-only-compatible insertion (instead of in-place UPDATE) preserving security intent.
- Updated `broker/tests/test_firewall_controller_persistence_failure_closure.py::test_corrupt_lifecycle_record_fail_closed` to simulate corrupt/conflicting lifecycle history via append-only-compatible insertion (instead of in-place UPDATE) preserving fail-closed intent.

## 9. Verification summary

- `py_compile`: OK for modified files (`broker/firewall_controller_service/ownership_store.py`, `broker/tests/test_firewall_controller_j17_persistence_integrity.py`, updated existing tests) — exit 0.
- J.17 tests: **20 passed, 1 warning** (8.54s, exit 0).
- Focused J.12/J.13/J.15/J.16/J.17: **112 passed, 1 warning** (61.58s, 0:01:01, exit 0).
- `test_firewall_controller_persistence_failure_closure.py` (includes append-only-compatible fix): **19 passed, 1 warning** (14.17s, exit 0).
- `manager/tests`: **30 passed, 1 warning** (0.99s, exit 0).
- `manage.py check`: **0 issues** (exit 0).
- Full `broker/tests` (observed run): **792 passed, 1 failed, 1 warning** in 311.23s (0:05:11), exit 1 — failing test `test_firewall_controller_persistence_failure_closure.py::test_corrupt_lifecycle_record_fail_closed` was executed from pre-fix state during that run and subsequently fixed/verified passing (**19 passed** file run). A final full-broker rerun was initiated to capture post-fix consolidated totals.

Warnings: `PytestDeprecationWarning` (`asyncio_default_fixture_loop_scope` unset), `PydanticDeprecatedSince20` (dependency).

## 10. Gate reassessment (evidence-justified, no closures)

| Gate | Disposition after J.17 | Justification |
|---|---|---|
| RR-06 | **Open / Partially improved (covered)** | Append-only triggers for history/evidence/audit and improved FK enforcement on store-managed connections add concrete integrity protections; J.17 tests evidence trigger/FK/reopen/corruption handling in covered paths. DB-enforced digest CHECKs/migrations, full FK/CHECK/NOT NULL coverage, exhaustive integrity matrix, and schema-level invalid-write/read prevention remain incomplete. |
| M-06 | **Open / Partially improved (covered)** | Stronger append-only/evidence-history protections and trusted read-back/recovery evidence in covered mock paths; full append-only/constraint/migration/per-family/partial-state/recovery closure unproven. |
| RR-05 | **Open / Partially improved (covered)** | Additional deterministic recovery/race/fault-injection/reopen/no-false-promotion evidence in covered cases; full-scan/exhaustive state-evidence matrix, deterministic intra-tx hooks, and host evidence incomplete. |
| M-01 | **Open / Partially resolved (unchanged in substance)** | Existing bounded idempotency behavior preserved and exercised; global scope/migration/universal closure evidence not added. |
| N-02, H-05, I-07, I-08, I-09, RR-07 | **Unchanged** | No J.17 evidence justifying closure or material status change beyond prior records. |
| T-11, T-13, T-27 | **OPEN — ACCEPTANCE REQUIRED** | Unchanged. |

## 11. Limitations / open items

- No destructive migrations, table rebuilds, or DB-enforced digest CHECK constraints added (compatibility/safety constraint).
- Multi-table atomicity not redesigned; partial states possible but tested fail-closed/recoverable in covered cases.
- Append-only enforcement is trigger-based in covered SQLite operations; schema/admin bypass outside covered controls not claimed prevented.
- Exhaustive transaction-boundary hook instrumentation, all interleavings/state matrices, and host/runtime evidence remain incomplete.
- RR-05/RR-06/M-01/M-06 not closed.

**J.17 complete (scoped, mock-only) with documented open items.**

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
