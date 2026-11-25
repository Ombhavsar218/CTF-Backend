# Post-J.20 Stage 1B.15 — Security Test Evidence

All commands were executed from `E:\Flag-hunt\ctf-platform-be` on 2026-11-18 using the repository virtualenv. Raw stdout/stderr and exact exit/wall-time artifacts are under `docs/evidence/post_j20_stage_1b15/`. No suite was interrupted or stalled.

## 1. Evidence command convention

Pytest command prefix:

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' <targets> -q
```

Django command prefix:

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe' <manage.py args>
```

The `pytest-asyncio` unset-loop-scope deprecation and Pydantic v2 config deprecation appear as warnings in the captured pytest runs. They are environmental/pre-existing and did not affect exit status.

## 2. New suite: initial failures preserved

Command:

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' 'broker/tests/test_post_j20_stage_1b15_boundary_persistence_integrity.py' -q
```

Artifacts: `docs/evidence/post_j20_stage_1b15/initial_new_suite_stdout.txt`, `initial_new_suite_exit.txt`.

- Result: `5 failed, 16 passed, 1 warning in 7.82s`
- Exit: `1`
- Wall time: `16.76s`

Failures:

1. `test_service_rejects_mixed_canonical_rules_with_legacy_flat_fields` — service accepted canonical rules plus legacy top-level fields.
2. `test_service_rejects_legacy_compiled_rules_before_persistence` — service accepted legacy compiled rules; helper rejection happened after intent persistence.
3. `test_mock_adapter_rejects_legacy_compiled_rules_before_state_change` — mock adapter accepted legacy compiled rules.
4. `test_mock_adapter_rejects_mixed_canonical_and_legacy_fields` — mock adapter accepted mixed fields.
5. `test_reconciliation_does_not_downgrade_persisted_canonical_body` — test-design issue only: substring marker `canonical` matched the policy id `b15-reconcile-canonical`. The assertion was narrowed to exact legacy field names; the canonical body field assertion was not weakened.

## 3. New suite: corrective rerun

After the smallest contract-preserving boundary correction described in `POST_J20_STAGE_1B15_FINAL_VERIFICATION_REPORT.md` §3:

```powershell
& 'E:\Flag-hunt\ctf-platform-be\venv\Scripts\pytest.exe' 'broker/tests/test_post_j20_stage_1b15_boundary_persistence_integrity.py' -q
```

Artifacts: `docs/evidence/post_j20_stage_1b15/corrective_new_suite_stdout.txt`, `corrective_new_suite_exit.txt`.

- Result: `21 passed, 1 warning in 7.45s`
- Exit: `0`
- Wall time: `9.62s`

## 4. Regression evidence

| Label | Targets | Result | Exit | Wall seconds | Artifacts |
|---|---|---:|---:|---:|---|
| Canonical validation | `test_firewall_controller_rule_schema_v1.py`, `test_firewall_controller_rule_lifecycle_2j5.py`, `test_post_j20_stage_1b13_canonical_validation_sanitization.py`, `test_firewall_controller_identifier_validation_entrypoints.py`, `test_post_j20_stage_1a_canonical_authority.py` | 146 passed, 1 warning in 29.58s | 0 | 31.50 | `canonical_validation_stdout.txt`, `canonical_validation_exit.txt` |
| Legacy regressions | `test_firewall_policy.py`, `test_firewall_policy_hardening.py`, `test_firewall_lifecycle_integrity.py`, `test_broker_persistence.py`, `test_broker_recovery_and_audit.py`, `test_firewall_controller_contract.py` | 65 passed, 1 warning in 8.35s | 0 | 10.60 | `legacy_regressions_stdout.txt`, `legacy_regressions_exit.txt` |
| Persistence/integrity | `test_firewall_controller_j17_persistence_integrity.py`, `test_firewall_controller_persistence_failure_closure.py`, `test_firewall_controller_canonical_policy_persistence_2j6.py`, `test_post_j20_stage_1b14_persistence_reconciliation_residuals.py` | 56 passed, 1 warning in 29.80s | 0 | 31.53 | `persistence_integrity_stdout.txt`, `persistence_integrity_exit.txt` |
| Reconciliation/ownership/lifecycle | `test_firewall_controller_j18_reconciliation_contract.py`, `test_firewall_controller_j9_reconciliation_integrity.py`, `test_firewall_controller_j10_reconciliation_hardening.py`, `test_firewall_controller_canonical_lifecycle_integration_2j7.py`, `test_firewall_controller_ownership_binding_remediation.py`, `test_firewall_controller_lifecycle_idempotency.py`, `test_firewall_lifecycle_integrity.py` | 72 passed, 1 warning in 46.38s | 0 | 49.27 | `reconciliation_ownership_lifecycle_stdout.txt`, `reconciliation_ownership_lifecycle_exit.txt` |
| Idempotency/concurrency | `test_firewall_controller_concurrency_integrity.py`, `test_firewall_controller_deterministic_concurrency.py`, `test_firewall_controller_cross_process_concurrency.py`, `test_post_j20_stage_1b4_cross_table_concurrency.py`, `test_firewall_controller_j12_fault_injection_and_races.py`, `test_firewall_controller_j13_transaction_boundary_and_recovery.py`, `test_firewall_controller_revoke_recovery_and_idempotency_hardening.py`, `test_post_j20_stage_1b3_durable_crash_recovery.py`, `test_post_j20_stage_1b6_targeted_residual_gaps.py`, `test_post_j20_stage_1b1_durable_lifecycle_intent.py`, `test_post_j20_stage_1b2_atomic_persistence_boundaries.py` | 231 passed, 1 warning in 123.70s | 0 | 127.54 | `idempotency_concurrency_stdout.txt`, `idempotency_concurrency_exit.txt` |
| Full broker suite | `broker/tests` | 1005 passed, 1 warning in 365.57s | 0 | 367.37 | `full_broker_suite_stdout.txt`, `full_broker_suite_exit.txt` |

## 5. Django evidence

| Command | Result | Exit | Wall seconds | Artifacts |
|---|---|---:|---:|---|
| `manage.py test instances.tests.test_manager_client -v 1` | `Ran 33 tests in 0.113s`, `OK`, no issues | 0 | 31.29 | `django_manager_client_stdout.txt`, `django_manager_client_exit.txt` |
| `manage.py check` | `System check identified no issues (0 silenced).` | 0 | 1.97 | `django_manage_check_stdout.txt`, `django_manage_check_exit.txt` |

## 6. New test coverage map

`broker/tests/test_post_j20_stage_1b15_boundary_persistence_integrity.py` contains 21 deterministic tests:

- Mixed/legacy rejection at service and adapter: tests at lines 141, 158, 177, 195.
- Schema-v1 mirror and helper contract negatives: lines 205, 216.
- Validator-invocation negatives: line 232.
- Legacy no-rules compatibility and no conversion: lines 262, 299.
- Canonical body persistence/no downgrade: lines 281, 319.
- Digest/ownership/evidence/append-only/CAS/FK/migration integrity: lines 336, 352, 368, 384, 400, 426, 444, 466, 487, 527.

## 7. Repository state

Baseline snapshot: `post_j20_stage_1b15_initial_git_state.txt` and `post_j20_stage_1b15_initial_file_hashes.txt`.

Final state (`post_j20_stage_1b15_final_git_state.txt`):

- HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`
- Branch: `main`
- Modified tracked: 26
- Untracked entries: 279
- Staged: 0

Exact files changed by this milestone:

1. `broker/app/firewall_controller.py` (modified)
2. `broker/firewall_controller_service/rule_schema_v1.py` (modified)
3. `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` (modified, evidence-only)
4. `broker/tests/test_post_j20_stage_1b15_boundary_persistence_integrity.py` (new)
5. `docs/POST_J20_STAGE_1B15_BOUNDARY_MATRIX.md` (new)
6. `docs/POST_J20_STAGE_1B15_SECURITY_TEST_EVIDENCE.md` (new)
7. `docs/POST_J20_STAGE_1B15_RESIDUAL_RISK_ASSESSMENT.md` (new)
8. `docs/POST_J20_STAGE_1B15_FINAL_VERIFICATION_REPORT.md` (new)
9. `docs/evidence/post_j20_stage_1b15/initial_new_suite_stdout.txt` (new)
10. `docs/evidence/post_j20_stage_1b15/initial_new_suite_exit.txt` (new)
11. `docs/evidence/post_j20_stage_1b15/corrective_new_suite_stdout.txt` (new)
12. `docs/evidence/post_j20_stage_1b15/corrective_new_suite_exit.txt` (new)
13. `docs/evidence/post_j20_stage_1b15/canonical_validation_stdout.txt` (new)
14. `docs/evidence/post_j20_stage_1b15/canonical_validation_exit.txt` (new)
15. `docs/evidence/post_j20_stage_1b15/legacy_regressions_stdout.txt` (new)
16. `docs/evidence/post_j20_stage_1b15/legacy_regressions_exit.txt` (new)
17. `docs/evidence/post_j20_stage_1b15/persistence_integrity_stdout.txt` (new)
18. `docs/evidence/post_j20_stage_1b15/persistence_integrity_exit.txt` (new)
19. `docs/evidence/post_j20_stage_1b15/reconciliation_ownership_lifecycle_stdout.txt` (new)
20. `docs/evidence/post_j20_stage_1b15/reconciliation_ownership_lifecycle_exit.txt` (new)
21. `docs/evidence/post_j20_stage_1b15/idempotency_concurrency_stdout.txt` (new)
22. `docs/evidence/post_j20_stage_1b15/idempotency_concurrency_exit.txt` (new)
23. `docs/evidence/post_j20_stage_1b15/full_broker_suite_stdout.txt` (new)
24. `docs/evidence/post_j20_stage_1b15/full_broker_suite_exit.txt` (new)
25. `docs/evidence/post_j20_stage_1b15/django_manager_client_stdout.txt` (new)
26. `docs/evidence/post_j20_stage_1b15/django_manager_client_exit.txt` (new)
27. `docs/evidence/post_j20_stage_1b15/django_manage_check_stdout.txt` (new)
28. `docs/evidence/post_j20_stage_1b15/django_manage_check_exit.txt` (new)
29. `post_j20_stage_1b15_final_git_state.txt` (new)
30. `post_j20_stage_1b15_changed_files.txt` (new)

No reset, clean, revert, stage, or commit was performed.
