# Phase 2L.2G.2.1 — Independent Cross-Process Crash-Recovery Validation (Mock-Only)

## Decision
**CONDITIONAL** — Cross-process concurrency and several crash-recovery behaviors were demonstrated within the tested mock scope (Windows `spawn`, isolated temp SQLite DBs, test-only file-backed mock backend state). Important scenarios remain **environment-limited or instrumentation-limited** (deterministic actual process termination at specific intra-service boundaries requires service hooks; mock backend is not a real firewall backend).  
**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

## Scope and constraints
- Local-only, mock-backend validation. No real UDS/SO_PEERCRED, no privileged helper/capabilities, no Docker/firewall/systemd/network/host permission/cloud changes, no live runtime provisioning.
- **No production logic modified** for this phase. Test-only infrastructure added: file-backed mock backend state and subprocess workers in `broker/tests/test_firewall_controller_cross_process_crash_recovery.py` to enable shared mock-backend state across processes without changing production code.
- Deterministic synchronization used where feasible (file-based signal markers/events). Arbitrary sleeps were not used as proof of reaching a boundary (polling waits for deterministic signal tokens written by the test backend at hook points).
- SQLite persistence is shared across processes via temp DB files. Mock backend state is shared across processes via temp JSON state file (test-only).

## 1. Inspected artifacts
- `broker/firewall_controller_service/controller_service.py`
- `broker/firewall_controller_service/ownership_store.py`
- `broker/firewall_controller_service/mock_backend.py`
- `broker/firewall_controller_service/transport.py`
- `broker/firewall_controller_service/mock_transport.py`
- `broker/tests/test_firewall_controller_persistent_recovery_integration.py`
- `broker/tests/test_firewall_controller_cross_process_concurrency.py`
- `docs/PHASE_2L_2G_2_PERSISTENT_OWNERSHIP_AND_RECOVERY_INTEGRATION.md`

## 2. Actual process termination validation
Tests use isolated subprocesses (`multiprocessing` spawn / `ProcessPoolExecutor`) and temporary databases/backend state files.

| Boundary (required) | Method | Actual OS process termination? | Result / Evidence |
|---|---|---:|---|
| After intent persistence but before backend execution (side effects) | Worker uses injectable test backend that signals `blocked_at:install_entry` on backend entry (service has already persisted install intent before calling backend), then parent `terminate()`s/kills process; fresh process reconciles | **Yes** (deterministic signal observed before termination) | `test_xproc_crash_after_intent_before_backend_side_effects` **PASS**. Exit code recorded as non-`None` (terminated/killed). Persisted ownership/idempotency survive; recovery does **not** promote to `ACTIVE`; backend install side effect not adopted as ACTIVE/unsafe. |
| During backend execution | Test backend signals mutation/block (`install_state_mutated`, `blocked_at:install_after_mutation`) and process is terminated during backend execution | **Yes** (deterministic signals observed) | `test_xproc_crash_during_backend_execution` **PASS**. Fresh-process recovery remains non-`ACTIVE` and fail-closed/consistent. |
| After backend modification but before response persistence | **Not deterministically triggered** with actual process termination without in-service hooks (backend returns to service; crash must occur before idempotency completion/response persistence inside `controller_service._call`) | **No (instrumentation-limited)** | State corresponding to this boundary validated in-process via 2G.2 recovery tests (`test_recovery_backend_completed_but_response_lost`) and by recovery semantics (inspect backend state, do not promote to `ACTIVE` without evidence). Cross-process actual-boundary termination **not demonstrated**. |
| After response persistence but before evidence persistence | **Not deterministically triggered** without hooks in verify/evidence flow | **No (instrumentation-limited)** | Validated in-process/state-simulation (`test_recovery_backend_completed_but_evidence_not_persisted`); cross-process actual-boundary termination **not demonstrated**. |
| After evidence persistence but before `ACTIVE` promotion | **Not deterministically triggered** without hooks between evidence store and lifecycle promotion | **No (instrumentation-limited)** | Validated in-process/state-simulation (`test_recovery_evidence_persisted_but_promotion_incomplete`); cross-process actual-boundary termination **not demonstrated**. |

## 3. Fresh-process recovery
Validated in cross-process tests (separate worker/recovery processes using same temp SQLite DB and shared test-only mock backend state):
- Persisted ownership preserved across processes and service recreation (`test_xproc_fresh_process_recovery_preserves_persistence`, 2G.2 tests).
- Lifecycle state remains consistent and **non-`ACTIVE`** without valid persisted evidence.
- Idempotency records survive across processes (existing cross-process idempotency/crash-recovery tests and 2G.2 persistence tests).
- Duplicate operations do not produce duplicate backend effects in tested scope (idempotent replay / conflict handling).
- Unknown backend objects are **never automatically adopted** (`test_xproc_no_adoption_of_unknown_backend_objects`).
- Uncertain operations remain non-`ACTIVE` (multiple tests).
- Evidence is independently checked before `ACTIVE` promotion (reconcile logic + 2G.2 recovery tests).

## 4. Cross-process concurrency
Executed with independent processes and shared SQLite database (temp DBs in 2G.2.1 tests; existing cross-process tests use configured service defaults as implemented). All tests reported process IDs in worker results where applicable.

| Scenario | Test(s) | Observed |
|---|---|---|
| Identical concurrent requests | `test_cross_process_identical` (existing), deterministic concurrency tests in-process | **PASS**. Identical payloads with same idempotency key complete without unsafe duplicate backend effects; responses consistent in tested scope. |
| Conflicting requests using same idempotency key | `test_cross_process_conflicting` (existing), `test_xproc_conflicting_idempotency_same_key` | **PASS**. At least one conflict/error observed; `FirewallControllerIdempotencyError` for conflicting payload/same key. |
| Lifecycle CAS conflicts | Validated in-process via `ownership_store` CAS and lifecycle tests (`test_lifecycle_cas_conflict_rejected`, targeted integrity tests) | **CONDITIONAL (not independently demonstrated as cross-process race with deterministic CAS collision in 2G.2.1)**. SQLite CAS/version checks exist and are enforced; dedicated cross-process CAS collision race not added. |
| Concurrent reconciliation | `test_xproc_concurrent_reconciliation` | **PASS** (2 workers, same DB/policy). Both reconciliations succeeded (`ok=True`); final state remained non-`ACTIVE`. |
| Database locking and transaction behavior | Exercised indirectly by cross-process/concurrent tests (SQLite WAL/transactions in store) | **PASS within tested scope**. No corruption/unsafe promotion observed; explicit lock-contention metrics not captured. |

**Operation/process counts (from new 2G.2.1 cross-process runs):** 7 tests, 10 total with existing cross-process concurrency module in combined run; workers executed in spawned subprocesses and returned PIDs (recorded in test result payloads). No duplicate backend effects or `ACTIVE` promotion without evidence observed.

## 5. Failure behavior
| Failure mode | Validation | Result |
|---|---|---|
| SQLite unavailable | Not fully simulated as a controlled cross-process failure mode in 2G.2.1 (would require fault injection in store/DB layer); prior phases noted fail-closed intent | **CONDITIONAL** (not independently demonstrated here). |
| Mock backend unavailable / read-back unavailable | `test_xproc_backend_readback_unavailable_fresh_process` (fresh process, backend inspect raises) | **PASS**. Reconciliation fails closed; state not promoted to `ACTIVE`. |
| Corrupt persistence records | Not fully exercised (limited safe corruption injection without schema compromise) | **CONDITIONAL**. Missing/inconsistent ownership cases covered; arbitrary row corruption not comprehensively tested. |
| Recovery interrupted a second time | Not explicitly simulated as a second actual process termination mid-recovery | **CONDITIONAL**. Duplicate recovery is safe (`test_recovery_duplicate_recovery_request`, concurrent reconciliation). |
| Backend state inconsistent with persisted ownership / unknown backend objects | `test_xproc_no_adoption_of_unknown_backend_objects`, in-process recovery tests | **PASS**. No auto-adoption of unknown backend rules. |
| Evidence missing or invalid | `test_recovery_backend_completed_but_evidence_not_persisted`, `test_uncertain_not_promoted_to_active_without_evidence`, reconcile VERIFIED-without-evidence path | **PASS**. No `ACTIVE` promotion without valid persisted evidence. |

Authorization/ownership checks were preserved in service/transport paths; no failure scenario in tested scope bypassed authz or ownership enforcement.

## 6. Test commands and actual results
Executed from `E:\Flag-hunt\ctf-platform-be`:

1. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_cross_process_crash_recovery.py broker/tests/test_firewall_controller_cross_process_concurrency.py -v`  
   **Result:** `10 passed, 1 warning in 9.24s`

2. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests -v` (regression check, no production logic modified)  
   **Result:** `183 passed, 1 warning in 51.69s`

## 7. Defects discovered
- **No concrete production correctness or security defect discovered** during this validation phase. (Instrumentation limitations prevented triggering all required intra-service crash boundaries with actual process termination; this is a validation gap, not a confirmed defect.)

## 8. Remaining gaps / prerequisites
- Actual OS-process termination **not demonstrated** for: “after backend modification but before response persistence”, “after response persistence but before evidence persistence”, “after evidence persistence but before ACTIVE promotion” (requires deterministic in-service hooks; not added to avoid production logic changes).
- Cross-process **lifecycle CAS collision race**, explicit **SQLite fault injection**, comprehensive **corrupt-record** handling, and “**recovery interrupted a second time**” (actual kill mid-recovery) remain incomplete.
- Mock-only with test-backed shared backend state; not equivalent to real firewall/Docker/nftables behavior, real process supervision, or real host transport/privilege boundaries.
- **Next prerequisites:** add test-only instrumentation hooks (if approved) or run host-lab validation with real process supervision to cover remaining boundaries; validate UDS/SO_PEERCRED, privileged helper, real backend read-back, conntrack/revocation, and full failure modes.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**