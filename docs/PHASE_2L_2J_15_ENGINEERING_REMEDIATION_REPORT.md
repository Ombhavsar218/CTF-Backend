# Phase 2L.2J.15 — Engineering Remediation Report (Mock-Only)
## Canonical Policy Authority and Legacy Boundary Closure

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be` (git root: `E:/Flag-hunt/ctf-platform-be`)  
**Branch/commit (baseline):** `main...origin/main`, `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`  
**Phase:** 2L.2J.15  
**Date:** 2026-11-16  
**Scope:** Narrowly scoped mock-only remediation for canonical policy authority/validation boundaries, legacy compatibility boundary definition, contract/schema alignment analysis, response-authority checks, and targeted tests/docs. **CONDITIONAL / PARTIALLY COMPLETE**.  
**Authorization boundary:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

No destructive migrations, no database rewrites, no live firewall/Docker/transport/privileged operations, no host/system/cloud changes, and no UDS/SO_PEERCRED/capability/nftables/iptables/DOCKER-USER work were performed.

---

## 1. Executive result

- **Entry-point inventory completed (covered scope):** `docs/PHASE_2L_2J_15_ENTRY_POINT_INVENTORY.md` documents inspected broker/controller/helper/mock/legacy/manager policy-related entry points, canonical authority sources, binding/persistence/read-back/response behavior, and remaining gaps. Universal closure not claimed.
- **Canonical authority (reused, not duplicated):** continued use of `broker/firewall_controller_service/rule_schema_v1.py`, `controller_policy_bodies` canonical persistence, and trusted read-back APIs in controller service/store; no new schema or authority store introduced.
- **Demonstrated defect fixes (smallest safe):**
  - `broker/app/firewall_controller_contract.py::_validate_request`: tightened `compiled_rule_digest` validation from length>=16 to canonical **64-hex** (fail-closed).
  - `broker/firewall_controller_service/controller_service.py::_validate_caller_identifiers`: added canonical fail-closed validation for `request_id`, `operation_id`, and `idempotency_key` at service boundary (aligned with helper canonical ID form), in addition to existing policy/instance/network checks.
  - `broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py`: updated `test_controller_rejects_digest_with_trailing_newline` to accept earlier contract/request-boundary rejection while preserving no-side-effect assertion (security intent preserved; behavior now fails closed earlier).
- **Legacy compatibility boundary defined:** legacy no-rules behavior preserved in covered paths; legacy flat broker subsystem (`broker/app/firewall_policy.py`, `firewall_compiler.py`, `firewall_state.py`, membership) documented as **separate model** not silently interpreted/converted as schema-v1 canonical controller policy. No automatic conversion introduced.
- **Contract/schema alignment explained (not renamed):** helper envelope `SCHEMA_VERSION="2L.2G.3"` (exact-match, mock helper boundary), compiled-mirror protocol context `PROTOCOL_SCHEMA_VERSION="2L.2I.2"` (when applicable), canonical rule schema `RULE_SCHEMA_VERSION="rule-schema-v1"` represent distinct layers; incompatibilities rejected by existing/covered checks.
- **Response authority (covered checks):** trusted read-back/canonical enrichment and fail-closed behavior verified for corrupt canonical data, mismatched version/ownership binding, digest mismatch rejection, and canonical inspect derivation from trusted body in J.15 tests and existing suites. Error responses remain bounded in covered paths (full I-08 redesign out of scope).
- **Tests/docs/regressions:** added `broker/tests/test_firewall_controller_j15_canonical_authority.py` (**11 passed**). Focused relevant regressions **319 passed**. Full `broker/tests` **728 passed, 1 warning** (194.41s). Full `manager/tests` **30 passed, 1 warning** (1.96s). `manage.py check` **0 issues**. `py_compile` OK for changed files.

**Phase status:** **CONDITIONAL / PARTIALLY COMPLETE**. N-02/H-05/RR-01–RR-04/I-07 **not closed** (universal/end-to-end/legacy-envelope migration and complete coverage unproven).

---

## 2. Exact repository and Git baseline

- **Root:** `E:/Flag-hunt/ctf-platform-be`
- **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`
- **Branch/status:** `main` (`## main...origin/main`)
- **Pre-existing modified tracked files (26, preserved):** `.env.example`, `.gitignore`, `README.md`, `achievements/views.py`, `announcements/views.py`, `challenges/admin_urls.py`, `challenges/models.py`, `challenges/serializers.py`, `challenges/tests.py`, `challenges/urls.py`, `challenges/views.py`, `config/__init__.py`, `config/settings.py`, `config/urls.py`, `requirements.txt`, `submissions/serializers.py`, `submissions/stats.py`, `submissions/tests.py`, `submissions/urls.py`, `submissions/views.py`, `users/admin_views.py`, `users/management/commands/setup_groups.py`, `users/tests.py`, `users/throttling.py`, `users/urls.py`, `users/views.py`
- **Pre-existing untracked set:** preserved (incl. `broker/`, `docs/`, `manager/`, debug/out/package artifacts)
- No reset/clean/checkout/revert/staging/commits.

## 3. Complete entry-point inventory

See **`docs/PHASE_2L_2J_15_ENTRY_POINT_INVENTORY.md`** for the inspected inventory (canonical components, broker/controller/helper/transport/mock/app entry points, persistence/read-back/lifecycle paths, legacy subsystem boundary, manager-facing paths, contract/schema version alignment, and remaining gaps). Inventory is evidence-based for inspected paths; universal coverage not claimed.

## 4. Canonical authority flow (covered paths)

- **Rule validation/normalization:** `rule_schema_v1.validate_install_policy_rules` / `validate_and_normalize_rules` (8-field schema-v1, deterministic normalization, conflict/ambiguity/range/CIDR checks as implemented).
- **Digest authority:** `compiled_rule_digest` recomputed from normalized canonical rules; mismatches rejected fail-closed in covered install/validation paths. Canonical policy digest handling per implemented alias/compatibility logic.
- **Persistence/read-back:** schema-v1 rule-bearing installs persist canonical bodies via `ownership_store.ensure_canonical_policy_body` (binding/validation); trusted reads via `read_trusted_canonical_policy_body` revalidate, recompute digest, and enforce ownership/version/digest/schema bindings.
- **Service operations:** install/inspect/verify/reconcile/remove-stale use authoritative ownership records and trusted canonical read-back where bodies exist; inspect enriches responses from validated canonical data; invalid/corrupt/mismatched canonical state fails closed in covered paths.
- **No untrusted-caller authority:** caller-supplied digests/ownership metadata are checked against authoritative/validated state, not accepted as source of truth.

## 5. Legacy compatibility boundary

- **Supported/preserved (covered):** legacy no-rules behavior in controller flows where canonical schema-v1 body is not required/applicable.
- **Separate legacy subsystem (explicit, not canonical):** `broker/app/firewall_policy.py`, `firewall_compiler.py`, `firewall_state.py`, `firewall_membership.py` implement flat legacy policy/compilation/state/membership domain with its own validation and digest semantics. This subsystem is **not** schema-v1 canonical controller authority and must not be silently converted/interpreted as schema-v1.
- **No automatic conversion:** none introduced. Unsupported/ambiguous representations rejected in covered schema-v1/canonical paths; exhaustive legacy adapter/rejection matrix incomplete.

## 6. Contract/schema version analysis

| Layer/version | Location | Meaning | Enforcement |
|---|---|---|---|
| Helper envelope `2L.2G.3` | `helper_contract.py` | Mock helper request/response envelope schema (exact match) | Required/matched; unsupported rejected |
| Protocol/compiled-mirror context `2L.2I.2` | `rule_schema_v1.py` | Schema-v1 compiled mirror semantics when explicitly declared | Applied when mirror indicates schema-v1 form; legacy compiled shapes not forcibly reinterpreted |
| Canonical rule schema `rule-schema-v1` | `rule_schema_v1.py`, ownership store | 8-field normalized canonical firewall rules and persisted canonical bodies | Validated/trusted-read-back enforced in covered paths |

Versions represent distinct layers and are intentionally not unified/renamed in J.15.

## 7. Response-authority findings

- **Covered positive evidence:** inspect returns canonical policy payload derived from trusted read-back when present (`test_canonical_inspect_response_derived_from_trusted_body_when_present`); corrupt canonical JSON fails closed on inspect/reconcile in J.15/J.12/J.13/J.7 cases; digest/version/ownership-binding mismatches fail closed in covered tests.
- **Bounded errors:** covered canonical/read-back failures mapped to bounded fail-closed errors (no raw internal record disclosure claimed beyond covered behavior); full I-08 sanitization redesign out of scope.
- **Remaining gaps:** universal response derivation/authority consistency across all surfaces and all legacy/canonical conflict permutations not proven.

## 8. Exact files changed and production-source modifications

| File | Change | Production source? |
|---|---|---|
| `broker/app/firewall_controller_contract.py` | Tightened `compiled_rule_digest` to canonical 64-hex validation | **Yes** (small, demonstrated hardening) |
| `broker/firewall_controller_service/controller_service.py` | Added canonical validation for `request_id`, `operation_id`, `idempotency_key` in `_validate_caller_identifiers` | **Yes** (small, demonstrated hardening) |
| `broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py` | Adjusted `test_controller_rejects_digest_with_trailing_newline` to expect earlier fail-closed boundary rejection (no side effects preserved) | **No** (test adjustment for stricter safe behavior) |
| `broker/tests/test_firewall_controller_j15_canonical_authority.py` | Added J.15 focused tests (11) | **No** |
| `docs/PHASE_2L_2J_15_ENTRY_POINT_INVENTORY.md` | Added | No |
| `docs/PHASE_2L_2J_15_ENGINEERING_REMEDIATION_REPORT.md` | Added | No |
| `docs/PHASE_2L_2J_15_INDEPENDENT_VERIFICATION.md` | Added | No |
| `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` | Updated (evidence-justified) | No |
| `docs/PHASE_2L_2J_14_GATE_EVIDENCE_MATRIX.md` | Updated (evidence-justified) | No |
| `docs/PHASE_2L_2J_14_REMEDIATION_ROADMAP.md` | Updated (evidence-justified) | No |

## 9. Adversarial and regression test results

Environment: `.\venv\Scripts\python.exe`, Windows `win32`. Warnings: `PytestDeprecationWarning` (`asyncio_default_fixture_loop_scope` unset), `PydanticDeprecatedSince20`. PowerShell stderr warnings may yield shell exit code `1`; pytest summaries authoritative.

| # | Command | Collected | Passed | Failed | Skipped | Warnings | Duration | Result |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `py_compile broker/app/firewall_controller_contract.py broker/firewall_controller_service/controller_service.py broker/tests/test_firewall_controller_j15_canonical_authority.py` | n/a | n/a | 0 | n/a | 0 | n/a | OK |
| 2 | `pytest -q broker/tests/test_firewall_controller_j15_canonical_authority.py` | 11 | 11 | 0 | 0 | 1 | 2.53s | PASS |
| 3 | Focused relevant regressions (J.3–J.13 canonical/schema/lifecycle/idempotency/helper/identity/identifier/contract/active + J.15 + manager runtime adapter): `test_firewall_controller_rule_schema_v1.py test_firewall_controller_policy_version_hardening.py test_firewall_controller_rule_lifecycle_2j5.py test_firewall_controller_canonical_policy_persistence_2j6.py test_firewall_controller_canonical_lifecycle_integration_2j7.py test_firewall_controller_j8_hardening.py test_firewall_controller_j9_reconciliation_integrity.py test_firewall_controller_j10_reconciliation_hardening.py test_firewall_controller_j11_adversarial_lifecycle.py test_firewall_controller_j12_fault_injection_and_races.py test_firewall_controller_j13_transaction_boundary_and_recovery.py test_firewall_controller_j15_canonical_authority.py test_firewall_controller_helper_contract.py test_firewall_controller_helper_identity_propagation.py test_firewall_controller_identifier_validation_entrypoints.py test_firewall_controller_contract.py test_firewall_controller_active_enforcement.py test_firewall_controller_lifecycle_idempotency.py manager/tests/test_runtime_adapter.py` | 319 | 319 | 0 | 0 | 1 | 77.98s (0:01:17) | PASS |
| 4 | `pytest -q manager/tests` (full) | 30 | 30 | 0 | 0 | 1 | 1.96s | PASS |
| 5 | `manage.py check` | n/a | n/a | 0 issues | n/a | 0 | n/a | PASS |
| 6 | `pytest -q broker/tests` (full) | 728 | 728 | 0 | 0 | 1 | 194.41s (0:03:14) | PASS (pytest summary) |

No failures observed in final J.15 execution. A passing rerun does not erase any prior-history failure outside this evidence.

## 10. Independent verification and remaining gaps

- **Verified (covered):** inventory documented; canonical schema-v1/store/trusted-read-back reused; tighter digest/ID boundary validation enforced and tested; legacy boundary explicitly defined (no silent schema-v1 conversion); schema/version layers explained with behavioral checks; corrupt/mismatch/version/binding fail-closed and trusted canonical inspect derivation evidenced in covered paths; regressions preserved.
- **Remaining gaps (not closed):** end-to-end canonical envelope/legacy migration and universal authority/response consistency across all surfaces (N-02/H-05), complete RR-01–RR-04 canonical scoping/migration/DB constraints, universal I-07/I-08/I-09/RR-07 closure, full RR-05/RR-06/M-06/M-01 persistence/recovery/integrity matrices, N-04/T-11/T-13/T-27/host gates. Full I-08 sanitization redesign and J.16/J.17 scope items intentionally deferred.

## 11. Updated gate dispositions

See updated `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md`, `docs/PHASE_2L_2J_14_GATE_EVIDENCE_MATRIX.md`, and `docs/PHASE_2L_2J_14_REMEDIATION_ROADMAP.md` (evidence-justified only). N-02/H-05/RR-01–RR-04/I-07 remain **partially satisfied/open** (improved in covered paths; not closed).

## 12. Confirmation that no live or host-level operations occurred

No live or host-level operations occurred in J.15. No operational Docker, UDS/`SO_PEERCRED`, privileged helper, `CAP_NET_ADMIN`, nftables, iptables, `DOCKER-USER`, host firewall, systemd, host permission, Linux host validation, or cloud/production operations were implemented, invoked, tested, configured, or authorized.

---

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
