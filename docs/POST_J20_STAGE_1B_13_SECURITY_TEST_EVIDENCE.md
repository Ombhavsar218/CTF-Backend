# Post-J.20 Stage 1B.13 — Security Test Evidence

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.**

Repository: `E:\Flag-hunt\ctf-platform-be` | HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`  
Date: 2026-11-18

## 1. Execution environment

- Python/pytest: `E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe`
- Django checks: `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe manage.py ...`
- Working directory: `E:\Flag-hunt\ctf-platform-be`
- Each run's complete stdout/stderr is in `post_j20_stage_1b13_*.stdout.txt`; command, actual exit code and wrapper timing are in the matching `.exit.txt`.
- Initial failures and corrective reruns were preserved separately. No historical failure file was overwritten with a passing result.

Distinctive sentinel strings used by the new suite:

- `SENTINEL_BACKEND_1B13_LEAK`
- `SENTINEL_SCHEMA_1B13_LEAK`
- `SENTINEL_PERSIST_1B13_LEAK`
- `SENTINEL_CANON_1B13_LEAK`

## 2. New Stage 1B.13 suite

Command:

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' broker/tests/test_post_j20_stage_1b13_canonical_validation_sanitization.py -q
```

| Phase | Evidence | Result | Exit | Wrapper seconds |
|---|---|---:|---:|---:|
| Initial execution, before corrective source changes | `post_j20_stage_1b13_new_suite.initial_failure.*` | **3 failed, 25 passed, 1 warning in 15.67s** | 1 | 15.67 (pytest summary) |
| Corrective rerun, 28 tests | `post_j20_stage_1b13_new_suite.rerun.*` | **28 passed, 1 warning in 9.00s** | 0 | 14.8994265 |
| Final expanded suite, including explicit replay-leak test | `post_j20_stage_1b13_new_suite.final.*` | **29 passed, 1 warning in 8.78s** | 0 | 12.4292331 |

Initial failures were:

- `test_service_backend_exception_does_not_leak_sentinel`
- `test_persistence_failure_is_not_reported_as_request_validation`
- `test_idempotency_conflict_class_preserved`

Coverage includes:

- nine noncanonical identifier cases plus optional-identifier rejection, with counting store/backend assertions proving no ownership lookup, lifecycle persistence or backend dispatch;
- policy digest/version binding mismatch before mutation;
- malformed aliases (`rules` non-list, non-hex digest, negative/string/boolean `policy_version`);
- schema sentinel non-leakage at service, app-controller and request-validator boundaries;
- backend exception sentinel non-leakage with explicit `FirewallControllerBackendError("Backend operation failed")`;
- persistence sentinel non-leakage with persistence-class preservation;
- canonical category mapping for ownership/integrity/persistence with `SENTINEL_CANON_1B13_LEAK` absent;
- bounded first response, bounded replayed response and bounded persisted `response_json` for a leaky backend response;
- app-controller health identifier rejection and bounded messages;
- preserved contract validation, idempotency conflict class, legacy no-rules install and Stage 1B.6 reconciliation persistence classification.

## 3. Canonical validation and sanitization regressions

| Scope | Command summary | Evidence | Result | Exit | Wrapper seconds |
|---|---|---|---:|---:|---:|
| Canonical validation bundle | selected canonical/schema/identifier/entry-point suites | `post_j20_stage_1b13_canonical_validation.*` | **142 passed, 1 warning in 41.96s** | 0 | 46.3136269 |
| Stage 1B.3 durable crash recovery | `test_post_j20_stage_1b3_durable_crash_recovery.py` | `post_j20_stage_1b13_1b3_rerun.*` | **24 passed, 1 warning in 27.84s** | 0 | 32.7796761 |
| Stage 1B.6–1B.7 residual regressions | selected residual/targeted suites | `post_j20_stage_1b13_residual_regressions.*` | **90 passed, 1 warning in 74.95s** | 0 | 76.7982351 |
| Reconciliation/persistence | selected J.9/J.10/J.13/J.17/J.18/persistence suites | `post_j20_stage_1b13_reconciliation_persistence.*` | **140 passed, 1 warning in 89.11s** | 0 | 90.9094156 |
| Corrected affected suites | targeted rerun after sanitization-contract alignment | `post_j20_stage_1b13_targeted_fixes_rerun.*` | **165 passed, 1 warning in 60.62s** | 0 | 62.2333054 |

Preserved failures for the residual-regression sequence:

- `post_j20_stage_1b13_residual_regressions.initial_failure.*` — **29 failed, 61 passed, 1 warning in 82.36s**, EXIT=1, 85.5365867s wrapper.
- `post_j20_stage_1b13_residual_regressions.intermediate_failure.*` — **3 failed, 87 passed, 1 warning in 77.60s**, EXIT=1, 82.7357079s wrapper.
- Final file: `post_j20_stage_1b13_residual_regressions.*` — 90 passed, EXIT=0.

No assertion was deleted or skipped. Assertions that previously required raw internal text were replaced with assertions that the raw text is absent while class/code/status/no-side-effect guarantees remain.

## 4. Focused combined regression set

Command (all 25 files):

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' @files -q
```

Files:

1. `broker/tests/test_post_j20_stage_1b13_canonical_validation_sanitization.py`
2. `broker/tests/test_post_j20_stage_1a_canonical_authority.py`
3. `broker/tests/test_firewall_controller_j15_canonical_authority.py`
4. `broker/tests/test_firewall_controller_rule_schema_v1.py`
5. `broker/tests/test_firewall_controller_canonical_lifecycle_integration_2j7.py`
6. `broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py`
7. `broker/tests/test_firewall_controller_identifier_validation_entrypoints.py`
8. `broker/tests/test_firewall_controller_contract.py`
9. `broker/tests/test_post_j20_stage_1b1_durable_lifecycle_intent.py`
10. `broker/tests/test_post_j20_stage_1b2_atomic_persistence_boundaries.py`
11. `broker/tests/test_post_j20_stage_1b3_durable_crash_recovery.py`
12. `broker/tests/test_post_j20_stage_1b4_cross_table_concurrency.py`
13. `broker/tests/test_post_j20_stage_1b6_targeted_residual_gaps.py`
14. `broker/tests/test_firewall_controller_j8_hardening.py`
15. `broker/tests/test_firewall_controller_j9_reconciliation_integrity.py`
16. `broker/tests/test_firewall_controller_j10_reconciliation_hardening.py`
17. `broker/tests/test_firewall_controller_j13_transaction_boundary_and_recovery.py`
18. `broker/tests/test_firewall_controller_j17_persistence_integrity.py`
19. `broker/tests/test_firewall_controller_j18_reconciliation_contract.py`
20. `broker/tests/test_firewall_controller_persistence_failure_closure.py`
21. `broker/tests/test_firewall_controller_persistent_recovery_integration.py`
22. `broker/tests/test_firewall_controller_crash_boundary_instrumentation.py`
23. `broker/tests/test_firewall_controller_cross_process_crash_recovery.py`
24. `broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py`
25. `broker/tests/test_firewall_controller_residual_risk_remediation.py`

| Phase | Evidence | Result | Exit | Wrapper seconds |
|---|---|---:|---:|---:|
| Before race stabilization | `post_j20_stage_1b13_focused_final.*` | **400 passed, 1 warning in 207.58s** | 0 | 209.6394571 |
| After race stabilization | `post_j20_stage_1b13_focused_final2.*` | **565 passed, 1 warning in 254.51s** | 0 | 256.1527368 |
| Final (after replay-leak test addition) | `post_j20_stage_1b13_focused_final3.*` | **566 passed, 1 warning in 244.05s** | 0 | 245.9637679 |

## 5. Full broker suite

Command:

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' broker/tests -q
```

| Phase | Evidence | Result | Exit | Wrapper seconds |
|---|---|---:|---:|---:|
| Initial failure before contract fixes | `post_j20_stage_1b13_full_broker.initial_failure.*` | **15 failed, 957 passed, 1 warning in 371.23s** | 1 | 373.4004667 |
| Later full-suite race failure | `post_j20_stage_1b13_full_broker.concurrent_failure.*` | **1 failed, 971 passed, 1 warning in 342.06s** | 1 | 343.9140819 |
| Final rerun after all fixes | `post_j20_stage_1b13_full_broker.final.*` | **973 passed, 1 warning in 350.57s** | 0 | 353.6547324 |

The initial 15 failures were in `test_firewall_controller_residual_risk_remediation.py` (install-failure sanitization, corrupt stored digest replay/audit/restart) and `test_firewall_controller_revoke_recovery_and_idempotency_hardening.py` (lost backend response). They were corrected by sanitizing before idempotency persistence, preserving the bounded digest-corruption message, and aligning injected-internal-exception expectations to the existing public backend-error class.

The later single failure was `test_concurrent_same_key_revoke_retries_converge`. It was diagnosed as a raced `IN_PROGRESS` CAS, corrected at `controller_service.py:1257-1275`, and verified by:

- `post_j20_stage_1b13_concurrency_repeat.*` — five isolated runs, exit codes `0,0,0,0,0`;
- `post_j20_stage_1b13_concurrency_fix.*` — `py_compile` exit 0 and five runs, exit codes `0,0,0,0,0`;
- final full broker suite — 973 passed, EXIT=0.

## 6. Django manager-client and system checks

| Check | Command | Evidence | Result | Exit | Wrapper seconds |
|---|---|---|---|---:|---:|
| Manager client | `& '...\venv\Scripts\python.exe' manage.py test instances.tests.test_manager_client -v 1` | `post_j20_stage_1b13_manager_client.*` | **Ran 33 tests in 0.037s — OK**; system check no issues | 0 | 13.2425402 |
| Django system check | `& '...\venv\Scripts\python.exe' manage.py check` | `post_j20_stage_1b13_django_check.*` | **System check identified no issues (0 silenced).** | 0 | not captured in `exit.txt` |

The manager client does not import the modified controller service directly; the checks were run for boundary regression coverage consistent with prior stages.

## 7. Evidence integrity statement

- All listed stdout files are complete captured outputs from the actual commands.
- All listed exit files preserve actual process exit codes; wrapper timings are measured wall-clock seconds and may exceed pytest's reported in-test duration.
- Initial and intermediate failures remain in separately named files and are not represented as final success.
- No test was skipped or removed to obtain the final result.
- Passing mock-only tests do not authorize live integration, gate closure, or residual-risk acceptance.
