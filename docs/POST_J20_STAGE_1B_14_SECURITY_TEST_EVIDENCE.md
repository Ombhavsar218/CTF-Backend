# Post-J.20 Stage 1B.14 — Security Test Evidence

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.**

Repository: `E:\Flag-hunt\ctf-platform-be` | HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`  
Milestone: Stage 1B.14 (2026-11-18), deterministic mock-only fault injection. All commands ran from the repository root. All stdout/stderr and exit/timing artifacts are preserved as untracked `post_j20_stage_1b14_*.stdout.txt` / `.exit.txt` files. The `pytest-asyncio` configuration warning is pre-existing and unrelated; exit codes below are authoritative.

## 1. Sentinel strings

| Sentinel | Purpose |
|---|---|
| `SENTINEL_1B14_RAW_READ_ERROR` | Raw nested canonical-read/internal fault must not leak. |
| `SENTINEL_1B14_RAW_PERSIST_ERROR` | Raw persistence-category fault must remain bounded. |
| `SENTINEL_1B14_RAW_AUDIT_ERROR` | Raw audit persistence fault must not leak through reconciliation results. |
| `SENTINEL_1B14_RAW_HISTORY_ERROR` | Raw lifecycle-history fault must not leave a false `ACTIVE` state. |

## 2. Failure chronology (preserved, not rewritten)

### 2.1 New-suite initial run

Command:

```powershell
$sw=[System.Diagnostics.Stopwatch]::StartNew(); & 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' 'broker/tests/test_post_j20_stage_1b14_persistence_reconciliation_residuals.py' -q 2>&1 | Tee-Object -FilePath 'post_j20_stage_1b14_new_suite.initial.stdout.txt'; $code=$LASTEXITCODE; $sw.Stop(); "---EXIT:$code---`nSECONDS:$($sw.Elapsed.TotalSeconds)" | Set-Content -Encoding UTF8 'post_j20_stage_1b14_new_suite.initial.exit.txt'
```

Result: `8 failed, 3 passed, 1 warning in 9.55s`; `---EXIT:1---`; `SECONDS:13.5370011`.  
Artifacts: `post_j20_stage_1b14_new_suite.initial.stdout.txt`, `.exit.txt`.  
This exposed the ungated status fallbacks, failed-branch success reporting, status/audit split write and missing `VERIFYING` history.

### 2.2 New-suite corrected-design initial run

Same command with `initial2` artifact names. Result: `9 failed, 2 passed, 1 warning in 8.11s`; `---EXIT:1---`; `SECONDS:10.0063056`.  
Artifacts: `post_j20_stage_1b14_new_suite.initial2.stdout.txt`, `.exit.txt`.  
Why rerun: the first classification tests passed via the outer generic backend handler rather than the canonical sanitizer, and the repeat-audit expectation was over-specified. Tests were re-anchored before source corrections; no assertion was weakened.

### 2.3 New-suite intermediate corrective run

Same command with `final` artifact names before the last two corrections. Result: `3 failed, 8 passed, 1 warning in 7.07s`; `---EXIT:1---`; `SECONDS:8.9395745`.  
Preserved as: `post_j20_stage_1b14_new_suite.intermediate1.stdout.txt`, `.exit.txt`.  
Outstanding causes: first-stage `get_canonical_policy_body()` fault was not routed through the sanitizer, and the no-guard test constructed the service with the guarded inner store.

### 2.4 Stage 1B.6–1B.13 regression initial failure

Command:

```powershell
$files=@('broker/tests/test_post_j20_stage_1b1_durable_lifecycle_intent.py','broker/tests/test_post_j20_stage_1b2_atomic_persistence_boundaries.py','broker/tests/test_post_j20_stage_1b3_durable_crash_recovery.py','broker/tests/test_post_j20_stage_1b4_cross_table_concurrency.py','broker/tests/test_post_j20_stage_1b6_targeted_residual_gaps.py','broker/tests/test_post_j20_stage_1b13_canonical_validation_sanitization.py'); & 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' @files -q
```

Result: `2 failed, 117 passed, 1 warning in 80.38s (0:01:20)`; `---EXIT:1---`; `SECONDS:82.3235949`.  
Artifacts: `post_j20_stage_1b14_stage_1b6_to_1b13_regressions.initial_failure.stdout.txt`, `.exit.txt`.  
Failures:

- `test_xproc_crash_after_verified_history_before_active_recovers` expected `VERIFIED` after grouped write `#1`; the newly journaled `VERIFYING` step is now grouped write `#1`, so the crash anchor was moved to grouped write `#2` (`VERIFIED`) with assertions unchanged.
- `test_stale_reconciliation_decision_cannot_overwrite_newer_state` blocked inside the new status+audit transaction, causing SQLite lock contention in the concurrent revoke. The barrier was moved to before transaction acquisition; stale-guard assertions unchanged.

## 3. Final commands and completed results

### 3.1 New Stage 1B.14 suite

Command: same as §2.1 with `final` artifact names.

```text
11 passed, 1 warning in 5.01s
---EXIT:0---
SECONDS:6.6767899
```

Artifacts: `post_j20_stage_1b14_new_suite.final.stdout.txt`, `.exit.txt`.

### 3.2 Focused persistence and reconciliation

Command:

```powershell
$files=@('broker/tests/test_firewall_controller_persistence_failure_closure.py','broker/tests/test_firewall_controller_j13_transaction_boundary_and_recovery.py','broker/tests/test_firewall_controller_j12_fault_injection_and_races.py','broker/tests/test_firewall_controller_j10_reconciliation_hardening.py','broker/tests/test_firewall_controller_j9_reconciliation_integrity.py','broker/tests/test_firewall_controller_j18_reconciliation_contract.py','broker/tests/test_broker_persistence.py','broker/tests/test_broker_recovery_and_audit.py'); & 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' @files -q
```

```text
113 passed, 1 warning in 45.16s
---EXIT:0---
SECONDS:46.7521045
```

Artifacts: `post_j20_stage_1b14_focused_persistence_reconciliation.stdout.txt`, `.exit.txt`.

### 3.3 Stage 1B.6–1B.13 relevant regressions (corrective rerun)

Command: same as §2.4 with final artifact names.

```text
119 passed, 1 warning in 72.37s (0:01:12)
---EXIT:0---
SECONDS:74.197322
```

Artifacts: `post_j20_stage_1b14_stage_1b6_to_1b13_regressions.stdout.txt`, `.exit.txt`.

### 3.4 Lifecycle, idempotency and concurrency

Command:

```powershell
$files=@('broker/tests/test_firewall_controller_lifecycle_idempotency.py','broker/tests/test_firewall_controller_deterministic_concurrency.py','broker/tests/test_firewall_controller_concurrency_integrity.py','broker/tests/test_firewall_controller_cross_process_concurrency.py','broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py','broker/tests/test_firewall_controller_residual_risk_remediation.py','broker/tests/test_firewall_controller_j11_adversarial_lifecycle.py','broker/tests/test_firewall_controller_j8_hardening.py','broker/tests/test_firewall_controller_j17_persistence_integrity.py'); & 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' @files -q
```

```text
235 passed, 1 warning in 101.67s (0:01:41)
---EXIT:0---
SECONDS:103.3541256
```

Artifacts: `post_j20_stage_1b14_lifecycle_idempotency_concurrency.stdout.txt`, `.exit.txt`.

### 3.5 Full broker suite

Command:

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' 'broker/tests' -q
```

```text
984 passed, 1 warning in 340.53s (0:05:40)
---EXIT:0---
SECONDS:342.1605578
```

Artifacts: `post_j20_stage_1b14_full_broker.stdout.txt`, `.exit.txt`. This is the authoritative full-suite result; no source/test change followed it before documentation and gate-register evidence references.

### 3.6 Django manager client

Command:

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe' 'manage.py' test 'instances.tests.test_manager_client' -v 1
```

```text
Ran 33 tests in 0.048s
OK
Found 33 test(s).
System check identified no issues (0 silenced).
---EXIT:0---
SECONDS:18.4690178
```

Artifacts: `post_j20_stage_1b14_django_manager_client.stdout.txt`, `.exit.txt`.

### 3.7 Django system check

Command:

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe' 'manage.py' check
```

```text
System check identified no issues (0 silenced).
---EXIT:0---
SECONDS:2.0753131
```

Artifacts: `post_j20_stage_1b14_django_check.stdout.txt`, `.exit.txt`.

## 4. Coverage mapping

| Requirement | New test | Result |
|---|---|---|
| Unknown canonical read stays bounded and is not caller validation | `test_unknown_canonical_read_failure_is_backend_error_and_bounded` | PASS |
| Persistence-category read fault remains persistence/bounded | `test_persistence_category_read_failure_stays_persistence_error_and_bounded` | PASS |
| Nested reconciliation read storage fault classified persistence, no adoption | `test_nested_reconciliation_read_storage_failure_is_persistence_not_invalid` | PASS |
| No-guard fallback cannot write | `test_missing_guard_context_fails_closed_without_status_write` | PASS |
| Missing allowed source states cannot write | `test_missing_allowed_states_fails_closed_without_status_write` | PASS |
| `needs_verification` CAS miss is uncertain | `test_needs_verification_status_conflict_is_uncertain_not_success` | PASS |
| `failed` CAS miss is uncertain | `test_failed_status_conflict_is_uncertain_not_success` | PASS |
| Status/audit atomic rollback | `test_status_and_audit_are_atomic_when_audit_fails` | PASS |
| VERIFYING history exists | `test_verifying_transition_is_journaled_with_state_history` | PASS |
| VERIFYING history fault blocks unsupported ACTIVE | `test_verifying_history_failure_does_not_produce_active_state` | PASS |
| Repeated reconcile preserves state/ownership | `test_repeated_reconcile_preserves_status_and_audit_idempotence` | PASS |

No test was skipped or removed to obtain these results. Initial failures and corrective reruns remain separate artifacts.
