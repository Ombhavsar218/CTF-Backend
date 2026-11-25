# Post-J.20 Stage 1A — Test Evidence (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (`main`)  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

## 1. Baseline and environment checks

| Command | Result | Exit |
|---|---|---|
| `git rev-parse --show-toplevel` / `--show-current` / `rev-parse HEAD` | `E:/Flag-hunt/ctf-platform-be`, `main`, `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | 0 |
| `git diff --name-only` | 26 pre-existing modified tracked files (unchanged) | 0 |
| `manage.py check` | `System check identified no issues (0 silenced).` | 0 |
| `python -m py_compile broker/app/firewall_controller.py broker/app/firewall_controller_contract.py broker/tests/test_post_j20_stage_1a_canonical_authority.py` | success (during iterations/final checks) | 0 |

Warnings observed in pytest runs (pre-existing environment): `PytestDeprecationWarning` (`asyncio_default_fixture_loop_scope` unset), `PydanticDeprecatedSince20`.

## 2. Exact tests added

| File | Purpose |
|---|---|
| `broker/tests/test_post_j20_stage_1a_canonical_authority.py` | Stage 1A adversarial/coverage checks: `MockFirewallController` canonical ID rejection and no-side-effect behavior for malformed required/optional identifiers (alternate mock entry point), service rejection before store side effects, contract omitted-optional semantics, legacy flat-rule subsystem no silent conversion to schema-v1 controller body, tampered persisted canonical body fails closed on inspect and reconcile (no false success/reactivation) |

**New Stage 1A test cases (12):**
- `test_mock_controller_rejects_malformed_canonical_identifiers_no_side_effect[request_id-bad id]`
- `test_mock_controller_rejects_malformed_canonical_identifiers_no_side_effect[operation_id-bad/id]`
- `test_mock_controller_rejects_malformed_canonical_identifiers_no_side_effect[idempotency_key-bad\nkey]`
- `test_mock_controller_rejects_malformed_canonical_identifiers_no_side_effect[policy_id-bad/id]`
- `test_mock_controller_rejects_malformed_optional_instance_id_when_provided`
- `test_mock_controller_rejects_malformed_optional_network_id_when_provided`
- `test_request_validator_contract_boundary_still_accepts_canonical_ids_for_service_path`
- `test_service_rejects_malformed_identifier_before_store_side_effects`
- `test_contract_allows_omitted_optional_identifiers`
- `test_service_install_rejects_unknown_top_level_alias_field_no_side_effect`
- `test_legacy_flat_rule_subsystem_not_silently_converted_to_schema_v1`
- `test_reopen_recovery_with_invalid_persisted_canonical_body_fails_closed_no_false_success`

## 3. Initial failures and corrective reruns (preserved)

| Stage | Command / context | Result | Corrective action | Final result |
|---|---|---|---|---|
| Initial implementation attempt (contract hardening) | `pytest broker/tests/test_firewall_controller_identifier_validation_entrypoints.py ...` (focused batch) | **76 failed, 111 passed, 1 warning** (exit 1) — failures due to `broker.app.firewall_controller_contract._validate_request` raising `FirewallControllerRequestError` earlier for invalid IDs while existing tests expect `PermissionError` from service validation path | Reverted contract semantic change; moved canonical ID enforcement to `MockFirewallController` alternate entry point (additive, scoped) and updated Stage 1A tests to match preserved contracts/covered behavior | Regressions restored (see below) |
| Pre-existing collection issue (observed) | `pytest broker/tests/test_firewall_controller_contract.py -q` | **1 error during collection** (exit 2): `ImportError` circular import in `broker.app.firewall_controller`/service init chain | No code change applied to "fix" unrelated pre-existing collection behavior; preserved and reported | **Unresolved in this run (pre-existing/environment-specific observation)** |

## 4. Focused regressions and Stage 1A verification

| Command | Collected | Passed | Failed | Errors | Warnings | Duration | Exit |
|---|---:|---:|---:|---:|---:|---:|---:|
| `pytest broker/tests/test_firewall_controller_j15_canonical_authority.py broker/tests/test_firewall_controller_j16_authorization_identity.py broker/tests/test_firewall_controller_j18_reconciliation_contract.py broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py broker/tests/test_firewall_controller_canonical_lifecycle_integration_2j7.py broker/tests/test_firewall_controller_rule_schema_v1.py broker/tests/test_firewall_controller_rule_lifecycle_2j5.py broker/tests/test_firewall_controller_helper_contract.py broker/tests/test_firewall_controller_identifier_validation_entrypoints.py -q` | 213 | 213 | 0 | 0 | 1 | 53.61s | 0 |
| `pytest broker/tests/test_firewall_controller_identifier_validation_entrypoints.py broker/tests/test_post_j20_stage_1a_canonical_authority.py -q` | 99 | 99 | 0 | 0 | 1 | 29.19s | 0 |
| `pytest broker/tests/test_firewall_controller_j15_canonical_authority.py broker/tests/test_firewall_controller_j16_authorization_identity.py broker/tests/test_firewall_controller_j18_reconciliation_contract.py broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py broker/tests/test_firewall_controller_canonical_lifecycle_integration_2j7.py broker/tests/test_firewall_controller_rule_schema_v1.py broker/tests/test_firewall_controller_rule_lifecycle_2j5.py broker/tests/test_firewall_controller_helper_contract.py -q` | 126 | 126 | 0 | 0 | 1 | 41.94s | 0 |

## 5. Manager suite and Django checks

| Command | Collected | Passed | Failed | Errors | Warnings | Duration | Exit |
|---|---:|---:|---:|---:|---:|---:|---:|
| `pytest manager/tests -q` | 46 | 46 | 0 | 0 | 1 | 6.95s | 0 |
| `manage.py check` | n/a | n/a | n/a | n/a | 0 issues | n/a | 0 |

## 6. Full broker suite

| Command | Status | Evidence |
|---|---|---|
| `pytest broker/tests -q` (full suite rerun, initiated in Stage 1A) | **Incomplete at report generation** — execution observed progressing then terminated without pytest summary in captured outputs; rerun started in background but completion not captured before final report | `post_j20_stage_1a_broker_full.stdout.txt` / `post_j20_stage_1a_broker_full.stderr.txt` (rerun attempt) show progress dots and deprecation warning only, no final summary; no python process detected at last check. Prior pre-Stage-1A full broker baseline reported in J.19 was 837 passed (not reverified here). |

**Action required for closure-quality evidence:** rerun and capture `pytest broker/tests -q` to completion in the target environment and append exact counts/warnings/duration/exit code to this document.

## 7. Evidence interpretation

- Passing focused/manager/check results evidence behavior in covered mock-only paths only; they do not prove universal enforcement, gate closure, host/runtime correctness, or production readiness.
- Stage 1A added a scoped alternate-entry-point hardening in `MockFirewallController` with no focused regressions observed in covered suites.
- `test_firewall_controller_contract.py` collection error is reported as observed; not attributed to final Stage 1A source changes.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
