# Phase 2L.2G.2.2 — Targeted Crash-Boundary and Recovery Validation (Mock-Only)

## Decision
**CONDITIONAL** — Cross-process lifecycle CAS collision, interrupted reconciliation with actual subprocess termination at a deterministic boundary, and several SQLite/failure/corrupt-record fail-closed behaviors were demonstrated within the tested mock scope. Boundaries A/B/C **inside `controller_service._call`** were **not** validated with actual OS process termination because doing so requires in-service hooks; adding hooks would modify production logic, which was not permitted without a discovered defect. Those boundaries were validated via state-simulation + fresh-process recovery.  
**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

## 1. Files inspected, created and modified

### Inspected
- `broker/firewall_controller_service/controller_service.py`
- `broker/firewall_controller_service/ownership_store.py`
- `broker/firewall_controller_service/mock_backend.py`
- `broker/tests/test_firewall_controller_cross_process_crash_recovery.py`
- `broker/tests/test_firewall_controller_cross_process_concurrency.py`
- `broker/tests/test_firewall_controller_persistent_recovery_integration.py`
- `docs/PHASE_2L_2G_2_1_INDEPENDENT_CROSS_PROCESS_CRASH_RECOVERY_VALIDATION.md`

### Created
- `broker/tests/test_firewall_controller_crash_boundary_instrumentation.py`
- `docs/PHASE_2L_2G_2_2_TARGETED_CRASH_BOUNDARY_AND_RECOVERY_VALIDATION.md`

### Modified
- **None in production logic.** No unrelated files modified.

## 2. Instrumentation design and proof it is test-only
- **No hooks added to production files** (`controller_service.py`, `ownership_store.py`, mock backend production modules unchanged). This respects the constraint: production logic unchanged unless a concrete defect discovered.
- Test-only mechanisms:
  - **Injectable test backend** (`_make_backend` in the test module) implementing the backend interface; used via `FirewallControllerService(..., backend=...)`. Supports deterministic file-signal markers and blocking at injectable call points (e.g., `inspect_entry`, `install_entry/after_mutation`) to enable controlled subprocess termination. Disabled/absent in normal operation.
  - **Injectable ownership store** via `ownership_store=ControllerOwnershipStore(db_path=...)` (existing production API) using isolated temp SQLite DBs.
  - **Subprocess synchronization**: workers write deterministic signal tokens to temp files; parent polls for token presence before termination. No arbitrary sleeps used as proof of boundary reach (polling is for signal detection with timeout assertions).
  - **Process termination**: `multiprocessing` spawned processes terminated via `terminate()`/`kill()` after deterministic signal; exit codes captured.
- Hooks are local to test processes, not remotely triggerable, and not present in production code paths.

## 3. Three crash-boundary results

| Boundary | Actual subprocess termination at intra-service boundary? | Validation method | Fresh-process recovery result | Duplicate backend op / unsafe ACTIVE? |
|---|---:|---|---|---|
| **A. Backend modification completed, response not yet persisted** | **No (instrumentation-limited)** — boundary is between backend return and idempotency/response persistence inside `controller_service._call`; no production hooks added. | State-simulation: backend shows installed; ownership `REQUESTED`/uncertain + `PENDING` idempotency persisted; fresh process runs reconciliation. | `test_boundary_A_state_sim_fresh_process_recovery` **PASS**. Reconciled to safe non-`ACTIVE` state (needs verification/consistent handling). | **No** unsafe `ACTIVE`; no duplicate unsafe promotion observed. |
| **B. Response persisted, evidence not yet persisted** (verify-path interpretation) | **No (instrumentation-limited)** — precise intra-verify-flow boundary not killable without hooks. | State-simulation: backend/verify context present, ownership not `ACTIVE`, no persisted evidence; fresh process reconciles. | `test_boundary_B_state_sim_fresh_process_recovery` **PASS**. State remains non-`ACTIVE`; no promotion without persisted evidence. | **No**. |
| **C. Evidence persisted, ACTIVE promotion not yet completed** | **No (instrumentation-limited)** — boundary between evidence store and lifecycle promotion to `ACTIVE` inside service flow not killable without hooks. | State-simulation: valid persisted evidence exists; ownership `VERIFIED` (promotion incomplete); fresh process reconciles. | `test_boundary_C_state_sim_fresh_process_recovery` **PASS**. Promotion occurs **only** when valid evidence/state allow (safe transition) or remains safe/non-`ACTIVE`. | **No** unsafe promotion without evidence; evidence presence verified when promoted. |

**Additional actual termination evidence (2G.2.1 / 2G.2.2 context):** intent-before-backend-side-effects and backend-execution interruption were demonstrated with actual subprocess termination in 2G.2.1; interrupted reconciliation was demonstrated with actual subprocess termination at a deterministic backend-inspect boundary in 2G.2.2.

## 4. Cross-process lifecycle CAS results
`test_cross_process_lifecycle_cas_collision` (2 independent spawned processes, shared isolated SQLite DB, same ownership record, same expected `installation_state='INSTALLING'` and `lifecycle_version`):

| Process | Actual result | Notes |
|---|---|---|
| Worker A | `ok=True` (winner) | Transition committed; PID recorded in worker result |
| Worker B | `ok=False`, `PermissionError` / CAS conflict (`LIFECYCLE_VERSION_CONFLICT`) | Controlled conflict; PID recorded |

**Final DB state:** `installation_state='VERIFYING'` (or consistent expected winner state), `lifecycle_version` incremented by exactly 1 from expected version. Lifecycle history remained consistent (no corruption). **No duplicate evidence, no invalid `ACTIVE` promotion.**

## 5. Interrupted reconciliation results
| Test | Actual subprocess termination | Fresh-process recovery | Final state / safety |
|---|---:|---|---|
| `test_interrupted_reconciliation_then_fresh_recovery` | **Yes** — reconciliation worker blocked deterministically at injected `inspect_entry` (file signal observed), then `terminate()`/`kill()`; exit code captured (non-`None`) | **PASS** — fresh process reconciles successfully | Persisted ownership/lifecycle consistent; **non-`ACTIVE`**; uncertain ops not promoted; no unknown backend adoption |
| `test_repeated_interrupted_reconciliation` | **Yes** (up to 2 interruptions attempted with deterministic signals/timeouts) | **PASS** — final fresh reconciliation succeeds | Consistent, non-`ACTIVE`, fail-closed |

## 6. SQLite failure and corrupt-record results
All tested failures behaved **fail closed** (no silent repair/adoption/discard of authoritative ownership into unsafe `ACTIVE` state).

| Case | Test | Result |
|---|---|---|
| Database unavailable / invalid path (init/access) | `test_db_unavailable_during_reconcile_fails_closed` | **PASS** (fails closed / exception-safe) |
| Database write failure during lifecycle transition | Not deterministically injected without store hooks | **CONDITIONAL** (not demonstrated) |
| Database unavailable during reconciliation | Partially covered by invalid/unavailable DB handling patterns; dedicated mid-reconcile DB fault injection limited | **CONDITIONAL** |
| Corrupt ownership record (invalid state/digest values) | `test_corrupt_ownership_record_handling` | **PASS** — no `ACTIVE` promotion; fail closed |
| Corrupt lifecycle record | Not explicitly injected | **CONDITIONAL** |
| Corrupt idempotency record | Not explicitly injected | **CONDITIONAL** |
| Missing evidence record | `test_missing_evidence_record_fail_closed` | **PASS** — remains non-`ACTIVE` |
| Recovery attempted again after persistence failure / repeated interruption | `test_repeated_interrupted_reconciliation`, duplicate recovery tests in 2G.2 | **PASS** (safe/repeatable in tested cases) |
| Backend state inconsistent with persisted ownership | `test_backend_inconsistent_with_persisted_ownership` | **PASS** — fail closed/uncertain handling |

## 7. Actual process exit codes and backend operation counts
- **Exit codes:** captured in crash/interrupt tests (`exitcode is not None`; processes terminated via `terminate()`/`kill()` on Windows spawn). Worker PIDs recorded in result payloads for cross-process tests (CAS, reconciliation).
- **Backend operation counts:** not instrumented as global counters in production mock backend (no production changes). Test-only file-backed backend mutates shared state deterministically; validations assert **no unsafe `ACTIVE` promotion**, **no auto-adoption of unknown backend objects**, and consistent final persisted/backend state. No duplicate unsafe backend effects observed in tested scenarios.

## 8. Exact test commands and results
Executed from `E:\Flag-hunt\ctf-platform-be` (venv):

1. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_crash_boundary_instrumentation.py -v`  
   **Result:** `10 passed, 1 warning in 7.99s`

2. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_crash_boundary_instrumentation.py broker/tests/test_firewall_controller_cross_process_crash_recovery.py broker/tests/test_firewall_controller_cross_process_concurrency.py broker/tests/test_firewall_controller_persistent_recovery_integration.py -v`  
   **Result:** `41 passed, 1 warning in 24.24s`

3. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests -v` (complete Broker suite, no production logic modified)  
   **Result:** `193 passed, 1 warning in 60.10s (0:01:00)`

4. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client`  
   **Result:** `Found 33 test(s). System check identified no issues (0 silenced).` **OK**

5. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe manage.py check`  
   **Result:** `System check identified no issues (0 silenced).`

## 9. Concrete defects found
- **No concrete production correctness or security defect discovered.** No production remediation performed. (Validation gaps for A/B/C actual intra-service termination are due to no-production-hook constraint, not confirmed defects.)

## 10. Remaining validation gaps
- **Actual OS process termination not demonstrated** for A/B/C at the exact intra-service boundaries inside `controller_service._call` (requires production hooks; not added).
- Deterministic injection not completed for: DB write failure during lifecycle transition, DB unavailable mid-reconcile, corrupt lifecycle/idempotency records (comprehensive), and some “recovery after persistence failure” permutations.
- CAS demonstrated for ownership-state update collision; broader cross-process CAS coverage across all lifecycle paths/races not exhaustive.
- Backend operation counting not globally instrumented (would require production/test-backend interface changes beyond scope).
- Mock-only, Windows `spawn` behavior, temp-DB/test-backend state — not equivalent to real firewall/backend/process supervision/host-lab conditions.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**