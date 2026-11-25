# Post-J.20 Stage 1A — Canonical Policy Authority and Legacy Boundary Implementation (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (`main`)  
**Stage:** Post-J.20 Stage 1A (mock-only remediation, evidence-backed, additive/fail-closed)  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

## 1. Objective

Address remaining mock-only canonical policy authority and legacy-boundary gaps prioritized in J.14–J.20 for:
- **N-02** — Canonical policy authority
- **H-05** — Canonical policy boundary
- **I-07** — Authorization and identity validation (covered scope)
- **RR-01–RR-04** — Request and lifecycle validation (covered scope)

This stage performed **no** Docker/host/transport/privileged-helper/firewall/live operations and did **not** start Docker integration.

## 2. Baseline and preservation

| Item | Value |
|---|---|
| Git root / branch / HEAD | `E:/Flag-hunt/ctf-platform-be`, `main`, `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged) |
| Modified tracked files (preserved) | 26 (unchanged; no tracked files modified by Stage 1A) |
| Untracked entries (pre-Stage 1A) | 369 (including J.20/planning docs; preserved) |
| Untracked entries added by Stage 1A | Source/test/doc artifacts listed below (additive only) |
| Git operations performed | `git` inspection only. **No** reset/clean/checkout/revert/add/commit |

## 3. Evidence inspected

- J.20 artifacts: `PHASE_2L_2J_20_IMPLEMENTATION_EVIDENCE_LEDGER.md`, `PHASE_2L_2J_20_FINAL_GATE_TRACEABILITY_MATRIX.md`, `PHASE_2L_2J_20_FINAL_TRUST_BOUNDARY_ASSESSMENT.md`, `PHASE_2L_2J_20_VERIFICATION_AND_LIMITATIONS.md`, `PHASE_2L_2J_20_REMAINING_RISKS_AND_AUTHORITY_REQUIREMENTS.md`, `PHASE_2L_2J_20_FINAL_READINESS_DECISION.md`
- `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md`, `docs/PHASE_2L_2J_14_REMEDIATION_ROADMAP.md`, `docs/PHASE_2L_2J_14_GATE_EVIDENCE_MATRIX.md`
- Source: `broker/firewall_controller_service/{rule_schema_v1.py,controller_service.py,ownership_store.py,helper_contract.py,request_validator.py,...}`, `broker/app/{firewall_controller_contract.py,firewall_controller.py,firewall_policy.py,firewall_compiler.py,firewall_state.py,routes.py,...}`
- Existing tests: J.3–J.19 controller suites (inventory and focused inspection), including `test_firewall_controller_j15_canonical_authority.py`, `test_firewall_controller_j16_authorization_identity.py`, `test_firewall_controller_j18_reconciliation_contract.py`, `test_firewall_controller_canonical_policy_persistence_2j6.py`, `test_firewall_controller_canonical_lifecycle_integration_2j7.py`, `test_firewall_controller_rule_schema_v1.py`, `test_firewall_controller_rule_lifecycle_2j5.py`, `test_firewall_controller_helper_contract.py`, `test_firewall_controller_identifier_validation_entrypoints.py`
- Repository map/exploration (read-only) for canonical paths, legacy subsystem, manager-facing paths, and prior test coverage.

## 4. Gaps identified (evidence-backed) and actions taken

| Gap | Evidence | Action (additive, fail-closed, mock-only) | Compatibility note |
|---|---|---|---|
| App-layer mock controller (`broker/app/firewall_controller.MockFirewallController`) accepted requests without canonical ID-format enforcement for request/operation/idempotency/policy and optional instance/network identifiers at that alternate entry point, despite service/helper canonical validation in covered paths | Source inspection: `_validate_request` enforces presence/digest/version but not ID regex; `MockFirewallController` methods called contract validation only. Existing `test_firewall_controller_identifier_validation_entrypoints.py` expects service-level `PermissionError` semantics from `RequestValidator/_call` path (not contract-level) | Added `_ID_RE` and `_validate_canonical_identifiers` in `MockFirewallController`; invoked on health/install/inspect/verify/revoke/remove_stale/reconcile after contract parse (using supplied request fields where defaults are generated) to fail closed with `FirewallControllerRequestError` before side effects in covered mock entry paths | Did **not** change `broker/app/firewall_controller_contract._validate_request` exception/validation semantics to avoid breaking established tests/callers (initial attempt caused 76 failures in `identifier_validation_entrypoints` due to `FirewallControllerRequestError` raised earlier vs expected `PermissionError`; reverted and preserved prior behavior) |
| Legacy flat-rule subsystem (`firewall_policy.py`, `firewall_compiler.py`, `firewall_state.py`) is a separate schema/digest/lifecycle domain relative to controller schema-v1 | Source inspection showed distinct models and no conversion path to controller canonical schema-v1 bodies/store | No code conversion implemented (none proven safe). Added explicit adversarial/documentation test asserting no silent schema-v1 body creation from legacy flat-rule artifacts and documented quarantine/adaptation requirements | Backward compatibility preserved for legacy domain; no silent reinterpretation introduced |
| Universal entry-point/alias/unknown-field/top-level authority closure | Service validates canonical IDs, schema-v1 rules/install ingress, ownership binding, trusted read-back in covered paths; helper rejects unknown/auth-claim fields; not every hypothetical boundary proven | Added focused Stage 1A adversarial tests for covered alternate entry point, tamper/reopen-recovery fail-closed, and legacy non-conversion; documented covered/uncovered boundaries in matrix | No claim of universal enforcement |

### Gaps assessed but not changed in code (evidence/compatibility constraints)
- **`rule_schema_v1.validate_install_policy_rules` alias acceptance (`canonical_policy_digest == compiled_rule_digest`) and `validate_compiled_mirror` legacy-shape leniency:** explicit compatibility behaviors present; removing/changing without full equivalence proof and migration plan risks breaking existing valid mock flows. Left unchanged and documented as legacy-compatibility boundary (not silent conversion).
- **Controller service legacy no-rules install requests:** preserved by design/evidence (no schema-v1 canonical body required/created); not treated as schema-v1 canonical authority.
- **App-layer contract canonical ID regex enforcement:** deferred to preserve existing exception semantics and prior test contracts; service-level enforcement remains in covered paths.

## 5. Canonical policy authority (observed/confirmed, covered paths)

- Single schema-v1 rule validation/normalization/digest helpers in `rule_schema_v1.py` used at controller install boundary, helper ingress (when rules present), mock/app controller install boundary (when rules present), and store persistence/read-back validation.
- Deterministic digests: `compiled_rule_digest` over canonical rules; canonical policy digest helpers/validation as implemented in covered paths.
- Ownership/policy-version binding enforced via authoritative store records/CAS checks in covered controller flows.
- Trusted persistence/read-back: canonical body stored/validated and read back with binding/digest/schema checks; inspect derives canonical response from trusted body when present; verify/reconcile fail closed on corrupt/invalid/mismatch in covered cases.
- No evidence of success response derived from untrusted canonical body when trusted read-back is required and fails.

## 6. Legacy boundary disposition (Stage 1A)

| Legacy operation/domain | Disposition | Rationale |
|---|---|---|
| Legacy flat-rule model/compiler/state (`broker/app/firewall_policy.py`, `firewall_compiler.py`, `firewall_state.py`) | **Quarantined as separate domain; do not auto-convert** | Schema/digest/lifecycle semantics differ from schema-v1; canonical equivalence not proven |
| Legacy controller install without schema-v1 `rules` | **Compatibility preserved (explicit non-canonical-body path)** | Existing behavior/evidence; no schema-v1 body persisted/required; must not be silently interpreted as schema-v1 authority |
| Legacy/mock compiled-shape and digest-alias handling in schema validation helpers | **Preserve with explicit compatibility behavior (documented)** | Removal requires proven equivalence/migration analysis; current behavior explicit, not silent reinterpretation in inspected paths |

## 7. Exact source files modified

- `broker/app/firewall_controller.py` — added canonical ID regex and fail-closed identifier validation for `MockFirewallController` covered entry points (health/install/inspect/verify/revoke/remove_stale/reconcile); no behavioral change for valid canonical requests.

## 8. Documentation created/updated

**Created:**
- `docs/POST_J20_STAGE_1A_CANONICAL_AUTHORITY_IMPLEMENTATION.md`
- `docs/POST_J20_STAGE_1A_ENTRY_POINT_COVERAGE_MATRIX.md`
- `docs/POST_J20_STAGE_1A_TEST_EVIDENCE.md`
- `broker/tests/test_post_j20_stage_1a_canonical_authority.py`

**Updated (evidence-justified, no closures):**
- `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` — Stage 1A evidence note/disposition refinement only (no gate closures)

## 9. Gate-by-gate reassessment (evidence-justified, no closures)

| Gate | Reassessment | Justification / limitation |
|---|---|---|
| N-02 | **Partially resolved (unchanged disposition, incremental evidence)** | Canonical authority/trusted read-back in covered paths reconfirmed; legacy flat-rule domain explicitly quarantined/documented as non-equivalent; no end-to-end envelope/legacy migration or universal authority closure |
| H-05 | **Partially resolved (unchanged disposition)** | Covered boundary behavior preserved/improved at app-layer mock controller entry point; full end-to-end contract/legacy-envelope alignment incomplete |
| I-07 | **Open / partially resolved in covered paths (incremental evidence)** | Added alternate mock entry-point canonical ID enforcement and adversarial tests; universal entry-point/alias/ambiguous-field closure unproven |
| RR-01–RR-04 | **Open / partially resolved in covered paths (incremental evidence)** | No regression in covered identifier/version/digest validations; MockFirewallController identifier validation improved; universal/DB/migration closure unproven |
| T-11, T-13, T-27 | **OPEN — ACCEPTANCE REQUIRED (unchanged)** | No acceptance evidence |

## 10. Limitations and next recommended work package

- **Not claimed:** universal enforcement, gate closure, production/host readiness, live integration authorization.
- **Uncovered/remaining:** app-layer contract canonical ID semantics alignment (if desired, requires compatibility/test-contract migration), universal alias/unknown-field rejection across all possible boundaries, DB-enforced digest/identifier constraints/migrations, exhaustive legacy-envelope migration/adapters, full reconciliation/integrity matrices, packaging/deployment/host/runtime evidence.
- **Pre-existing test environment note:** `broker/tests/test_firewall_controller_contract.py` failed collection during this run with `ImportError` (circular import in module import chain); observed before/independent of final Stage 1A source behavior and not introduced by reverted contract change.
- **Full broker suite:** execution was initiated in this stage; final result must be recorded from completed run artifact/output (see `POST_J20_STAGE_1A_TEST_EVIDENCE.md`).

**Recommended next (mock-only, separately scoped):** continue Stage 1 canonical/validation closure inventory (universal entry-point/alias/field and DB-constraint-safe additive work where justified), persistence-integrity/reconciliation evidence hardening (RR-05/RR-06/M-06/M-01 subsets), and sanitization/auth-isolation proof (I-08/I-09/RR-07) — without claiming closures and without live/host operations.
