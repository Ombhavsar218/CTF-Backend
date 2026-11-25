# Post-J.20 Stage 1B.15 — Final Verification Report

**Mandatory status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.**

**T-11, T-13, T-27 remain OPEN — ACCEPTANCE REQUIRED.**

**Milestone decision: COMPLETE — SCOPED MOCK-ONLY VERIFICATION. Not gate closure, not acceptance, not production authorization, and not Stage 1C authorization.**

Date: 2026-11-18.

## 1. Scope and baseline

Stage 1B.15 independently verified the legacy flat-rule / canonical `rule-schema-v1` boundary and the persistence-integrity contracts that can be exercised without live or privileged facilities. Stage 1B.13/1B.14 evidence was treated as input, not as proof of universal boundary integrity.

Baseline captured before work:

- HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`
- Branch: `main`
- Modified tracked files: 26
- Untracked entries: 249
- Staged files: 0
- Hash snapshot: `post_j20_stage_1b15_initial_file_hashes.txt` (287 lines)
- State snapshot: `post_j20_stage_1b15_initial_git_state.txt`

No reset, clean, revert, stage, or commit was performed. All pre-existing modified and untracked files were preserved.

Strict mock-only boundary maintained: no Docker runtime/socket/SDK, UDS/`SO_PEERCRED`, privileged helper, kernel identity, capabilities, nftables, iptables, host firewall state, host permissions, cloud/production/live backend, or Stage 1C work was performed.

## 2. What was verified

1. **Legacy flat rules are not silently interpreted as canonical.** The legacy compiler/state subsystem has no canonical-body, schema-v1 validator, or controller-store reference. Legacy no-rules controller requests remain accepted and never create a canonical body.
2. **Canonical rules are not downgraded to legacy.** Persisted bodies contain only schema-v1 rule fields; trusted read-back and reconciliation return schema-v1 bodies and do not synthesize legacy fields.
3. **Ambiguous mixed representations fail closed.** A new exact-key guard rejects legacy flat-rule fields and legacy compiled-rule shapes at the canonical install boundary, before idempotency, ownership-body persistence, or backend dispatch.
4. **No validator bypass was found in covered ingress paths.** The service and mock adapter both invoke the canonical validator; the helper contract independently rejects the same legacy compiled shape.
5. **Trusted read-back is integrity-gated.** Digest tamper, body JSON corruption, ownership-binding tamper, schema-version mismatch, and ownership digest mismatch fail closed with bounded errors.
6. **Persistence bindings are application-enforced and partially DB-enforced.** Controller writes enable `PRAGMA foreign_keys=ON`; canonical-body ownership is FK-backed and validated; idempotency CAS and append-only triggers behave as specified in scoped tests.
7. **Legacy compatibility and API/exception contracts were preserved.** Legacy no-rules install/inspect/reconcile continues without a canonical body; outward request/idempotency/permission/persistence error classes and bounded messages remain unchanged.

## 3. Corrective change made

The initial test run exposed four confirmed boundary gaps and one over-broad test assertion:

- Confirmed gaps: mixed canonical+legacy top-level fields and legacy compiled-rule shapes were accepted by the service/mock-adapter validators; the service persisted intent before the helper contract rejected the legacy compiled shape.
- Test-design issue: a substring marker assertion matched the policy id `b15-reconcile-canonical`; the test was narrowed to exact legacy keys without weakening the body-field assertion.

Smallest contract-preserving source corrections:

- `broker/firewall_controller_service/rule_schema_v1.py:36-40` — exact legacy representation marker set.
- `broker/firewall_controller_service/rule_schema_v1.py:371-401` — recursive compiled-shape detection and `validate_no_mixed_rule_representations()`.
- `broker/firewall_controller_service/rule_schema_v1.py:413` — guard invoked from `validate_install_policy_rules()` before any rules/no-rules branch.
- `broker/app/firewall_controller.py:75-78` — mock adapter invokes the validator for every dict install request, not only when `rules` is present.

No persistence schema, gate/status, risk disposition, transport, host, or authorization behavior was changed.

## 4. Evidence summary

All suites completed; none were interrupted or stalled. Full commands, stdout, exit, and wall-time artifacts are in `docs/evidence/post_j20_stage_1b15/`.

| Suite | Result | Exit | Wall seconds |
|---|---:|---:|---:|
| Initial new suite (preserved failure) | 5 failed, 16 passed, 1 warning in 7.82s | 1 | 16.76 |
| Corrective new suite | 21 passed, 1 warning in 7.45s | 0 | 9.62 |
| Canonical validation regressions | 146 passed, 1 warning in 29.58s | 0 | 31.50 |
| Legacy regressions | 65 passed, 1 warning in 8.35s | 0 | 10.60 |
| Persistence/integrity regressions | 56 passed, 1 warning in 29.80s | 0 | 31.53 |
| Reconciliation/ownership/lifecycle regressions | 72 passed, 1 warning in 46.38s | 0 | 49.27 |
| Idempotency/concurrency regressions | 231 passed, 1 warning in 123.70s | 0 | 127.54 |
| Full broker suite | 1005 passed, 1 warning in 365.57s | 0 | 367.37 |
| Django manager-client | 33 tests, OK | 0 | 31.29 |
| `manage.py check` | no issues | 0 | 1.97 |

## 5. Deliverables

- `docs/POST_J20_STAGE_1B15_BOUNDARY_MATRIX.md`
- `docs/POST_J20_STAGE_1B15_SECURITY_TEST_EVIDENCE.md`
- `docs/POST_J20_STAGE_1B15_RESIDUAL_RISK_ASSESSMENT.md`
- `docs/POST_J20_STAGE_1B15_FINAL_VERIFICATION_REPORT.md`

The gate register received an evidence-only reference only; no gate status, risk disposition, or acceptance state was changed.

## 6. Final repository state

Final state (`post_j20_stage_1b15_final_git_state.txt`):

- HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged)
- Branch: `main`
- Modified tracked files: 26 (unchanged count; the three files modified in this milestone were already modified at baseline)
- Untracked entries: 279 (baseline 249)
- Staged files: 0 (unchanged)

Exact changed-file list: `post_j20_stage_1b15_changed_files.txt` (30 entries).

Exact files changed by this milestone are listed in `docs/POST_J20_STAGE_1B15_SECURITY_TEST_EVIDENCE.md`.

## 7. Decision

Scoped legacy/canonical boundary and persistence-integrity verification is **COMPLETE** for the mock-only paths enumerated in the boundary matrix. This does not close any gate, accept any residual, authorize live integration, or claim universal deployed/environmental closure. All mandatory status and authority conditions remain in force.
