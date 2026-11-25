# Phase 2L.2G.2.3 — Persistence Failure and Recovery Closure (Test-Only, Mock-Only)

## Decision
**PASS** — Remaining targeted persistence failure and recovery cases were sufficiently validated within the tested mock scope (deterministic test-only fault injection, isolated temp SQLite DBs, mock backend, fresh-process recovery). Some injections are method-boundary proxies (no production hooks / no BrokerDB-internal transaction fault hooks), and true mid-SQL-connection failure inside a live transaction was not simulated; these limitations are documented. No concrete production correctness/security defect was discovered.  
**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

## 1. Files inspected and created

### Inspected
- `broker/firewall_controller_service/controller_service.py`
- `broker/firewall_controller_service/ownership_store.py`
- `broker/firewall_controller_service/mock_backend.py`
- `broker/tests/test_firewall_controller_crash_boundary_instrumentation.py`
- `broker/tests/test_firewall_controller_persistent_recovery_integration.py`
- `docs/PHASE_2L_2G_2_2_TARGETED_CRASH_BOUNDARY_AND_RECOVERY_VALIDATION.md`

### Created / modified (test/docs only)
- `broker/tests/test_firewall_controller_persistence_failure_closure.py` (created/extended; 19 tests)
- `docs/PHASE_2L_2G_2_3_PERSISTENCE_FAILURE_AND_RECOVERY_CLOSURE.md` (created)

### Production logic
- **None modified.** No hooks added to production files.

## 2. Fault-injection methodology
- **Test-only injectable store wrapper (`FaultStore`)**: wraps `ControllerOwnershipStore` and deterministically raises `BrokerDBError` (or configured exception, e.g. “database is locked”) on configured method calls (`True`, Nth call, or fail-after thresholds). Used to proxy: failure before lifecycle-related method execution/transaction begins (method boundary), failure during lifecycle update/evidence/history/idempotency completion paths, SQLite locked/busy, DB unavailable after backend modification, and reconciliation-write failures.
- **`CountingBackend`**: test-only wrapper around `MockFirewallBackend` to observe backend operation counts (`install/verify/revoke/inspect`) in-process.
- **Direct SQLite corruption (isolated temp DBs)**: controlled `UPDATE` statements to corrupt lifecycle history states, ownership lifecycle version, idempotency status/digest/response JSON, evidence digest/result fields, and ownership-to-policy relationship fields (instance/network) — no production DBs touched.
- **Fresh-process recovery**: `multiprocessing` `spawn` subprocess workers create fresh `FirewallControllerService`/`ControllerOwnershipStore`/`MockFirewallBackend` instances against the same isolated temp SQLite DB and run reconciliation.
- **Determinism**: no arbitrary sleeps used as proof of ordering; subprocess results/timeouts used for completion. Isolated temporary SQLite DBs per test.

## 3. SQLite lifecycle failure results

| Scenario | Test | Observed result | Safety invariants |
|---|---|---|---|
| Failure before lifecycle transaction begins (method-boundary proxy) | `test_fail_before_lifecycle_transaction_begins_no_false_success` | Exception raised; no false success | **No `ACTIVE`**; no unsafe record promotion |
| Failure during lifecycle update (install path) | `test_fail_during_lifecycle_update_no_false_success`, `test_fail_during_lifecycle_update_transition` | Exception raised; state inspected | **No false success, no `ACTIVE`** |
| Failure while persisting lifecycle history | `test_fail_while_persisting_lifecycle_history` | Exception during verify flow | **No unsafe `ACTIVE` promotion** (fail-closed in tested path) |
| Failure while persisting evidence | `test_fail_while_persisting_evidence_no_active_promotion`, `test_recovery_after_failed_evidence_persistence_fresh_process` | Evidence not persisted / exception; fresh recovery run | **No `ACTIVE` without valid persisted evidence** |
| Failure during `ACTIVE` promotion (targeted Nth update) | `test_fail_during_active_promotion_no_unsafe_state`, `test_fail_during_active_promotion_targeted` | Exception/no false success; if `ACTIVE` observed, evidence present (safety guard) | **No unsafe false success**; evidence required for safe `ACTIVE` |
| SQLite locked/busy response | `test_sqlite_locked_busy_response_fails_closed` | `BrokerDBError('database is locked')` injected | **Fail closed**, no `ACTIVE` |
| Database unavailable after backend modification | `test_db_unavailable_after_backend_modification` | Post-backend idempotency completion failed; backend install called; retry handled safely | **Backend install count observed (`>=1`)**; **no false safe `ACTIVE`**; retry/idempotency pending handled without unsafe promotion; no duplicate unsafe re-execution evidenced in scope |

**Notes:** “Before transaction begins” and “during transaction/update” are proxied at store method boundaries (deterministic, test-only). True BrokerDB/SQLite internal transaction fault points were not injected.

## 4. Reconciliation database-failure results

| Scenario | Test | Observed result | Safety invariants |
|---|---|---|---|
| DB unavailable before reconciliation (bad path/init/access proxy) | `test_db_unavailable_before_reconciliation` | Init/access fails closed or operations error safely | **Fail closed** |
| DB unavailable/failing during reconciliation writes | `test_db_unavailable_during_reconciliation_operation` | Reconciliation errors/fails closed; state remains safe; DB “available again” via fresh process retry | **No auto-adoption, no ownership reassignment, no unsafe `ACTIVE`, no duplicate unsafe backend side effects** |
| DB available again, fresh controller process retries | `test_db_unavailable_during_reconciliation_operation`, `test_recovery_after_failed_reconciliation_write_fresh_process`, `test_repeated_db_unavailability_recovery_attempt` | Fresh-process reconciliation completes | Persisted/backend state remains **reconcilable and fail-closed** (e.g., backend missing → non-`ACTIVE`/failed handling) |

## 5. Corrupt-record results
All tested corrupt-record cases behaved **fail closed** (no silent repair, deletion, replacement, or adoption of corrupted authoritative ownership into unsafe `ACTIVE` state; no ownership reassignment/promotion to `ACTIVE` in tested outcomes).

| Record type | Test | Result | Recoverable automatically vs manual intervention |
|---|---|---|---|
| Lifecycle records (history states corrupted) | `test_corrupt_lifecycle_record_fail_closed` | **PASS** (non-`ACTIVE`, consistent handling) | **Manual intervention likely** for authoritative history repair; reconciliation must not auto-repair corrupted history. |
| Lifecycle version values | `test_corrupt_lifecycle_version_fail_closed` | **PASS** (non-`ACTIVE`) | **Manual intervention likely**; CAS/version semantics compromised. |
| Idempotency records (digest/status/response corrupted) | `test_corrupt_idempotency_record_fail_closed` | **PASS** (fail-closed exception/safe handling; non-`ACTIVE`) | **Manual intervention likely** for affected idempotency rows; do not auto-trust/replay corrupt completed payloads. |
| Evidence records (digest/result/fields corrupted) | `test_corrupt_evidence_record_fail_closed` | **PASS** (no unsafe reassignment; consistent handling) | **Manual intervention likely** to validate/restore evidence integrity; automatic promotion must depend on valid evidence semantics. |
| Ownership-to-policy relationships (instance/network corrupted) | `test_corrupt_ownership_policy_relationship_fail_closed` | **PASS** (non-`ACTIVE`) | **Manual intervention required**; relationship corruption is security-sensitive and must not be auto-reassigned. |
| Lifecycle history (corrupt entries) | Covered by `test_corrupt_lifecycle_record_fail_closed` | **PASS** | **Manual intervention likely**; history is audit/recovery context, not auto-repaired. |

## 6. Fresh-process recovery results

| Recovery after | Test | Fresh process? | Result |
|---|---:|---|---|
| Failed lifecycle transition (persistence error paths) | covered by lifecycle failure + reconciliation tests | Yes (selected) | **Non-`ACTIVE` / fail-closed** |
| Failed evidence persistence | `test_recovery_after_failed_evidence_persistence_fresh_process` | Yes | **Non-`ACTIVE` unless valid evidence exists** |
| Failed `ACTIVE` promotion (targeted) | `test_fail_during_active_promotion_targeted` + prior 2G.2.2 C simulation | N/A in-process / simulation | **No unsafe false success** |
| Failed reconciliation write | `test_recovery_after_failed_reconciliation_write_fresh_process` | Yes | **Reconcile succeeds safely, non-`ACTIVE`** |
| Repeated database unavailability | `test_repeated_db_unavailability_recovery_attempt` | Yes (final recovery) | **Idempotent/safe recovery, non-`ACTIVE`** |

## 7. Backend operation counts
- **In-process observed (test-only `CountingBackend`):** `test_db_unavailable_after_backend_modification` recorded **`install >= 1`** when DB failed after backend modification; retry path did not produce unsafe `ACTIVE` promotion. Reconciliation tests exercised backend `inspect` (count observed in-process in relevant cases).
- **Cross-process fresh reconciliation workers:** use fresh `MockFirewallBackend` instances (no shared counter across processes) — operation counts across process boundaries **not globally aggregated** without production/test interface changes. Safety validated via persisted ownership/lifecycle state, no unknown backend adoption, and no unsafe `ACTIVE` promotion.
- **No duplicate backend operation on retry / no unsafe continuation** was evidenced in tested scenarios; uncertain outcomes remained non-`ACTIVE`.

## 8. Exact test commands and results
Executed from `E:\Flag-hunt\ctf-platform-be` (venv). (Pytest exit code `1` shown by PowerShell wrapper is due to prior command pipeline behavior in this environment; pytest summaries below are authoritative.)

1. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_persistence_failure_closure.py -v`  
   **Result:** `19 passed, 1 warning in 10.83s`

2. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_persistence_failure_closure.py broker/tests/test_firewall_controller_crash_boundary_instrumentation.py broker/tests/test_firewall_controller_persistent_recovery_integration.py broker/tests/test_firewall_controller_cross_process_crash_recovery.py -v`  
   **Result:** `57 passed, 1 warning in 26.11s`

3. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests -v` (complete Broker suite)  
   **Result:** `212 passed, 1 warning in 58.50s`

4. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client`  
   **Result:** `Found 33 test(s). System check identified no issues (0 silenced).` **OK**

5. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe manage.py check`  
   **Result:** `System check identified no issues (0 silenced).`

## 9. Concrete defects, if any
- **None discovered.** No production remediation performed. Corrupt idempotency payloads can cause fail-closed exceptions when read (expected safe behavior given corrupt authoritative data); no unsafe promotion/duplication observed.

## 10. Remaining limitations and local mock closure decision
- **Proxy injections:** method-boundary fault injection (not BrokerDB/SQLite internal `BEGIN`/mid-transaction SQL failure hooks). True OS-level DB file disappearance mid-connection/transaction not simulated.
- **Cross-process backend counters:** not globally aggregated.
- **Corrupt-record taxonomy:** tested key corruptions; not exhaustive over every column/combination. Automatic recovery classification is conservative (fail closed; manual intervention for authoritative corruption).
- **Mock-only / Windows `spawn` / temp DBs:** not equivalent to real firewall backend semantics, UDS/SO_PEERCRED, privileged helper, conntrack, Docker/nftables, process supervision, or host-lab conditions.
- **Local mock closure:** within the tested mock scope, targeted persistence failure/recovery behaviors are **sufficiently validated** with fail-closed outcomes.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
