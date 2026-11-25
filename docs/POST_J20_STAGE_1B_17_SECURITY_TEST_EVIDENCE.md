# Post-J.20 Stage 1B.17 — Security Test Evidence (Mock-Only)

All runs executed in `E:\Flag-hunt\ctf-platform-be` using the repository-local `venv`. Exact command, stdout, stderr, exit and duration are preserved under `docs/evidence/post_j20_stage_1b17/`.

## Initial reproduction / corrective sequence (new suite)

| Run | Command (exact) | Result | Exit | Duration | Evidence files |
|---|---|---:|---:|---:|---|
| initial_new_suite | `<repo>\venv\Scripts\python.exe -m pytest broker/tests/test_post_j20_stage_1b17_remediation.py -q` | 23 failed, 4 passed | 1 | 10.19s | `initial_new_suite.{stdout,stderr,exit,meta}.txt` |
| initial_new_suite_repro | same as above (clean reproduction after test-harness fixes) | 23 failed, 4 passed | 1 | 7.07s | `initial_new_suite_repro.{stdout,stderr,exit,meta}.txt` |
| corrective_new_suite_1 | same as above (after first source corrections) | 7 failed, 20 passed | 1 | 7.07s | `corrective_new_suite_1.{stdout,stderr,exit,meta}.txt` |
| corrective_new_suite_2 | same as above (after further corrections) | 2 failed, 25 passed | 1 | 6.09s | `corrective_new_suite_2.{stdout,stderr,exit,meta}.txt` |
| corrective_new_suite_final | same as above (after test fixture alignment) | **27 passed, 1 warning** | 0 | 5.08s | `corrective_new_suite_final.{stdout,stderr,exit,meta}.txt` |

Notes:
- Initial failures are reproduced and preserved; no incomplete run is reported as passing.
- The two intermediate corrective failures were caused by service-internal alias behavior (R16-04) and test setup details (`_verifying_with_evidence` fixture and full-scan contract). Both were corrected before the final run; evidence retained.

## Focused regressions (final post-fix runs)

| Group | Command (exact, abbreviated path prefix `<repo>\venv\Scripts\python.exe -m pytest ... -q`) | Result | Exit | Duration | Evidence |
|---|---|---:|---:|---:|---|
| auth/authorization | `... -m pytest broker/tests/test_firewall_controller_j16_authorization_identity.py broker/tests/test_firewall_controller_helper_contract.py broker/tests/test_firewall_controller_helper_identity_propagation.py broker/tests/test_broker.py broker/tests/test_broker_integration_persistent.py broker/tests/test_broker_docker.py -q` | **152 passed, 1 warning** | 0 | 42.4s | `focused_auth_authorization.{stdout,stderr,exit,meta}.txt` |
| reconciliation/lifecycle | `... -m pytest broker/tests/test_firewall_controller_j18_reconciliation_contract.py broker/tests/test_firewall_controller_j10_reconciliation_hardening.py broker/tests/test_firewall_controller_j9_reconciliation_integrity.py broker/tests/test_post_j20_stage_1b14_persistence_reconciliation_residuals.py broker/tests/test_post_j20_stage_1b3_durable_crash_recovery.py broker/tests/test_post_j20_stage_1b2_atomic_persistence_boundaries.py -q` | **84 passed, 1 warning** | 0 | 85.71s | `focused_reconciliation_lifecycle.{stdout,stderr,exit,meta}.txt` |
| canonical integrity | `... -m pytest broker/tests/test_post_j20_stage_1b13_canonical_validation_sanitization.py broker/tests/test_post_j20_stage_1b15_boundary_persistence_integrity.py broker/tests/test_firewall_controller_rule_schema_v1.py broker/tests/test_post_j20_stage_1a_canonical_authority.py broker/tests/test_firewall_controller_j15_canonical_authority.py -q` | **83 passed, 1 warning** | 0 | 37.33s | `focused_canonical_integrity.{stdout,stderr,exit,meta}.txt` |
| idempotency/concurrency | `... -m pytest broker/tests/test_firewall_controller_concurrency_integrity.py broker/tests/test_firewall_controller_deterministic_concurrency.py broker/tests/test_post_j20_stage_1b4_cross_table_concurrency.py broker/tests/test_firewall_controller_j12_fault_injection_and_races.py -q` | **35 passed, 1 warning** | 0 | 43.33s | `focused_idempotency_concurrency.{stdout,stderr,exit,meta}.txt` |

Stage 1B.13–1B.16 coverage: the canonical validation (1B.13/1B.15), persistence/reconciliation (1B.14) and 1B.15 boundary suites are exercised in the focused groups above; Stage 1B.16 was review-only and has no executable suite.

## Full broker suite

| Run | Command | Result | Exit | Duration | Evidence |
|---|---|---:|---:|---:|---|
| full_broker_suite | `<repo>\venv\Scripts\python.exe -m pytest broker/tests -q` | **1032 passed, 1 warning (383.45s)** | 0 | 386.02s | `full_broker_suite.{stdout,stderr,exit,meta}.txt` |

## Django manager client and system check

| Run | Command | Result | Exit | Duration | Evidence |
|---|---|---:|---:|---:|---|
| django_manager_client | `<repo>\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client -v 1` | **Ran 33 tests — OK** | 0 | 18.2s | `django_manager_client.{stdout,stderr,exit,meta}.txt` |
| django_manage_check | `<repo>\venv\Scripts\python.exe manage.py check` | **System check identified no issues (0 silenced)** | 0 | 17.18s | `django_manage_check.{stdout,stderr,exit,meta}.txt` |

## stderr content

- pytest runs: stderr contains the pre-existing `pytest-asyncio` deprecation warning about `asyncio_default_fixture_loop_scope` only. No test failure output is hidden there.
- `django_manager_client`: stderr contains Django's standard "Creating test database..." progress output; stdout contains `Ran 33 tests` / `OK`.
- `django_manage_check`: stderr empty.

All artifacts are raw captures from the runner scripts `post_j20_stage_1b17_run.ps1` and `post_j20_stage_1b17_run_cmd.ps1` (artifacts added at repo root, mock-only harness).
