# Phase 2L.2J.7 — Engineering Remediation Report (Mock-Only)
## Canonical Policy Lifecycle Integration, Trusted Read-Back Enforcement and Reconciliation Integrity

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be` (git root: `E:/Flag-hunt/ctf-platform-be`)  
**Branch/commit (baseline):** `main...origin/main`, `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (`b365584 New: Challenges backend`)  
**Phase:** 2L.2J.7  
**Date:** 2026-11-15  
**Scope:** Mock-only incremental integration of trusted canonical policy-body read-back into applicable controller inspection/verification/reconciliation service paths, with fail-closed handling, bounded error mapping, and focused lifecycle tests. **Partially complete** relative to full requested J.7 workstreams.  
**Authorization boundary:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

No real Docker daemon/socket access, no real container/network operations, no UDS, no `SO_PEERCRED`, no privileged helper, no Linux capabilities/`CAP_NET_ADMIN`, no nftables/iptables/`DOCKER-USER`, no real host firewall/systemd/host-permission changes, no real Linux host validation, no cloud/production deployment, and no real firewall operations were implemented or executed.

---

## 1. Executive result

Phase 2L.2J.7 integrated the existing J.6 canonical policy-body persistence/read-back primitives into key controller service lifecycle paths (inspect, verify, reconcile, and install persistence flow) without introducing a second canonical persistence implementation. For schema-v1 policies where a persisted canonical body exists, the service now performs trusted read-back validation (including ownership/binding/digest/schema checks via store APIs) and fails closed with bounded errors on invalid/corrupt/mismatched records in those paths.

**Outcome:** **CONDITIONAL / PARTIALLY COMPLETE** (mock-only). J.7 closes important lifecycle integration gaps identified after J.6 but does not complete all requested workstreams (full legacy/canonical compatibility enforcement across all legacy broker models, universal service-boundary authorization hardening beyond existing mechanisms, full persistence/migration/constraint hardening, comprehensive adversarial matrix/HV-EC evidence, and all gate closures). T-11, T-13, T-27 remain `OPEN — ACCEPTANCE REQUIRED`. No host-validation readiness claimed.

---

## 2. Initial Git baseline

- **Git root:** `E:/Flag-hunt/ctf-platform-be` (`git rev-parse --show-toplevel`)
- **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`
- **Status:** `## main...origin/main`; 26 pre-existing modified tracked files; pre-existing untracked files/directories present (including `broker/`, `docs/`, `manager/`, debug/out files, etc.).
- **Preservation:** no `git reset`, `git clean`, `git checkout --`, broad revert, staging, or commit performed. Pre-existing user changes/untracked files preserved.

---

## 3. Source architecture inspected

Inspected (actual implementation/docs, at minimum): `broker/firewall_controller_service/ownership_store.py`, `controller_service.py`, `rule_schema_v1.py`, `helper_contract.py`, `mock_backend.py`; `broker/app/firewall_controller.py`, `firewall_state.py`, `firewall_policy.py`, `firewall_compiler.py`, `db.py`, `firewall_controller_contract.py`; existing controller ownership/evidence/lifecycle/idempotency/revoke/helper/auth tests; `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md`; J.3–J.6 engineering/independent verification reports. J.6 store APIs and method signatures were verified in source (`store_canonical_policy_body`, `ensure_canonical_policy_body`, `get_canonical_policy_body`, `read_trusted_canonical_policy_body`).

**J.6 baseline (verified):** additive `controller_policy_bodies` table and trusted read-back/recompute/ownership-binding validation in store; controller install persisted canonical bodies for schema-v1 rule-bearing requests; inspect/verify/reconcile did not yet consistently require trusted canonical body validation or fail closed on corrupt persisted canonical records.

---

## 4. Actual implementation changes

### 4.1 Modified files
- `broker/firewall_controller_service/controller_service.py`

### 4.2 Added files
- `broker/tests/test_firewall_controller_canonical_lifecycle_integration_2j7.py`

### 4.3 `controller_service.py` changes (mock-only)

- **Reused J.6 APIs only:** no new competing canonical policy-body persistence implementation added.
- **Added `_sanitize_canonical_policy_error(...)`:** maps ownership/binding failures to `PermissionError('Authoritative ownership required')` (preserving indistinguishable ownership-denial semantics for covered cases), maps corruption/digest/schema/missing-required-fields failures to bounded `FirewallControllerRequestError('Invalid canonical policy record')`, maps DB failures to bounded persistence failure; avoids leaking raw DB/internal details in these paths.
- **Added service-level trusted read-back helper `_read_trusted_canonical_policy_body(...)`:** loads canonical body by `(policy_id, policy_version)`, returns `None` if absent and not required (legacy/no-canonical-body compatibility), requires body when `required=True`, and validates via `ownership_store.read_trusted_canonical_policy_body(...)` with expected owner/ownership-record and digest bindings; audits bounded `canonical_policy_readback_failed` and fails closed via sanitizer.
- **Install path:** retained J.6 canonical body persistence for schema-v1 rule-bearing installs (`_ensure_canonical_policy_body_persisted`).
- **Inspect/verify/remove-stale pre-check:** for `inspect_policy`, `remove_stale_policy`, `verify_policy`, performs trusted canonical read-back when a persisted body exists (required=False pre-check, fail-closed on invalid present body).
- **Verify path hardening:** on backend verification success and before evidence storage/lifecycle promotion, if canonical read-back was applicable, revalidates required trusted body against current ownership/request context and rejects request-digest mismatch vs trusted compiled digest; prevents activation flow from proceeding on invalid canonical body in this path.
- **Inspect response enrichment (when canonical body valid):** on successful inspect with validated canonical body, response `result.canonical_policy` is populated from trusted persisted/validated data (schema/id/version/digests/families/rules) and `digest_match` constrained by trusted compiled digest; does not trust raw DB records directly in response construction for this enrichment.
- **Reconcile hardening:** for each record considered, if a canonical policy body exists, reconciliation now requires trusted read-back validation (owner/ownership-record/compiled digest bindings, schema-v1) before making lifecycle decisions; on invalid/missing/contradictory canonical body or digest mismatch marks reconciliation status `uncertain` and records `invalid_canonical_policy_body`/`canonical_policy_digest_mismatch` reasons (no false ACTIVE/REVOKED promotion from this validation failure path).

### 4.4 Not implemented / intentionally deferred in J.7

- Full integration of trusted canonical read-back into all possible legacy read-back/inspect surfaces outside controller service paths (e.g. broker legacy `firewall_state`/`firewall_compiler`/legacy DB policy records remain separate model; app-level mock state/controller not universally refactored to canonical-body authority).
- Explicit, complete legacy/canonical compatibility matrix enforcement in code for every case requested (documented partially below; no destructive migrations or automatic legacy-to-canonical conversion).
- Universal I-07/RR-01–RR-04, I-08/RR-07, I-09 closure across all entry points; no new DB/app constraints/migrations for RR-05/RR-06 beyond existing J.6 additive table.
- Full comprehensive adversarial matrix, cross-process fault injection coverage for all J.7 cases, and HV-EC host-validation evidence.
- Any real transport/privileged/helper/Docker/host/firewall integration.

---

## 5. Trusted read-back integration matrix

| Path / operation | Trusted canonical read-back used | Required when body exists | Fail-closed on invalid/missing-when-required | Notes |
|---|---|---:|---:|---|
| `install_policy` (schema-v1 rules present) | Persistence via J.6 `ensure_canonical_policy_body` | Yes (for schema-v1 install body) | Yes (store/service) | Canonical body persisted; legacy no-rules installs remain compatible |
| `inspect_policy` (service) | `_read_trusted_canonical_policy_body` pre-check + post-dispatch validation/enrichment when body exists | Effectively yes if body exists | Yes (bounded sanitized errors) | Response enriched from trusted validated body when successful; legacy records without body follow existing behavior |
| `verify_policy` (service) | Pre-check + required revalidation before evidence/lifecycle promotion when applicable | Yes if canonical body applicable/exists in this flow | Yes | Prevents promotion on invalid canonical body in covered path |
| `remove_stale_policy` (service) | Pre-check when body exists | Yes if body exists | Yes | Uses same pre-check path; deeper stale-removal semantics unchanged except fail-closed on invalid body |
| `reconcile_pending_operations` | Direct store trusted read-back per record when body exists | Yes if body exists | Yes (marks uncertain, no false success) | Skips/promotes only after validation where applicable; legacy records without body continue through existing reconciliation logic |
| Legacy broker `firewall_state`/`firewall_policy`/`firewall_compiler` | No | N/A | N/A | Separate legacy model preserved; not reinterpreted as schema-v1 |

---

## 6. Inspection results

- Service inspection now fails closed for persisted canonical bodies that are corrupt/mismatched/invalid in covered paths.
- Successful canonical inspection enriches response with trusted canonical policy metadata/rules/digests from validated read-back (not from unvalidated raw DB content).
- Legacy/no-canonical-body inspections remain supported per existing behavior.
- Not all requested adversarial inspection cases have dedicated tests yet; J.7 added focused corrupt/tampered/wrong-owner-context coverage.

## 7. Verification results

- Verification path revalidates trusted canonical body before evidence storage/lifecycle promotion when applicable.
- Invalid persisted canonical body prevents verification-driven promotion in covered path (no false ACTIVE/VERIFIED due to status-only/backend success in that case).
- Mock-only workflow preserved; no synthetic real-host evidence generated.
- Stale/missing evidence adversarial matrix not fully expanded in this phase.

## 8. Reconciliation and recovery results

- Reconciliation validates canonical body (when present) via trusted read-back before lifecycle decisions and marks `uncertain` on invalid canonical body/digest mismatch.
- Existing CAS/lifecycle/idempotency/revoke-recovery mechanisms preserved; no foreign-policy mutation introduced by J.7 changes.
- Uncertain operation outcomes remain fail-closed in covered canonical-body validation failures.
- Full-scan reconciliation, all contradictory partial-state cases, and comprehensive crash/fault-injection coverage remain incomplete (RR-05/open work).

## 9. Authorization results

- Existing authorization (`MockAuthorizationProvider`/strict provider integration) and ownership binding checks remain in place for service operations.
- J.7 added service-level validation using expected owner/ownership-record bindings in trusted read-back calls for inspect/verify/reconcile checks where applicable.
- Unauthorized/wrong-owner request rejected in focused J.7 test (ownership binding/authorization context). Full service-boundary hardening and exhaustive unauthenticated/cross-controller/indistinguishable-error audit across all endpoints not completed.
- No implicit UID/GID defaults introduced.

## 10. Legacy/canonical compatibility matrix (J.7)

| Case | J.7 handling | Owner validation | Canonical read-back | Conversion | Quarantine | Notes |
|---|---|---|---:|---:|---:|---|
| Canonical schema-v1 with valid persisted body | Accepted in covered service paths | Controller store + service | Yes | No | No | Trusted read-back required where applicable |
| Canonical schema-v1 with missing body (should exist) | Rejected/fail-closed when required | Service/store | N/A (missing) | No | No (fail-closed) | Reconcile marks uncertain when body expected/invalid in checked cases |
| Legacy controller install without rules | Accepted (compatibility) | Existing validators | No body expected | No | No | No canonical body persisted |
| Legacy controller record with ambiguous content | Not fully adjudicated in code | Deferred | No automatic | No | Recommended/fail canonical ops | Requires explicit design/adapter decision |
| Legacy broker firewall policy/state/compiler records | Separate legacy model preserved | Legacy components | No | No automatic | N/A | Not reinterpreted as schema-v1 |
| Unknown schema version (canonical body) | Rejected | Store trusted read-back | Attempted/failed closed | No | No | Existing J.6 behavior retained |
| Malformed/corrupt canonical record | Rejected/fail-closed | Store/service | Validation fails | No | No | J.7 integrates fail-closed in inspect/verify/reconcile |
| Existing record without canonical body | Legacy-compatible path | Existing | No | No | No | Covered in J.7 test |
| Unsupported helper envelope | Not changed by J.7 | Helper contract | N/A | No | Reject | Existing behavior preserved |
| Explicit validated legacy adapter | Not implemented | N/A | N/A | Not proven | N/A | Deferred; no unsafe automatic conversion |

---

## 11. Persistence and transaction safety

- No schema migration framework added; reused existing J.6 additive `controller_policy_bodies` table/APIs and transaction semantics in store.
- J.7 did not modify `ownership_store.py`; deterministic coverage for rollback/partial-write/concurrency beyond existing tests not expanded in this phase.
- No actual development DB reset/deletion performed.

## 12. Adversarial and fault-injection tests (J.7 added)

Added `broker/tests/test_firewall_controller_canonical_lifecycle_integration_2j7.py` (**6 passed**) covering:
- Inspect fail-closed on corrupt canonical body JSON
- Inspect fail-closed on tampered canonical body digest
- Verify fail-closed on corrupt canonical body with no activation/promotion
- Reconcile marks uncertain on invalid canonical body (tampered digest) with no false success promotion in checked result/state
- Wrong-owner/ownership-context request rejected for inspect (authorization/ownership binding)
- Legacy install without canonical body remains inspectable/reconcilable

Comprehensive requested adversarial/fault-injection matrix (schema/owner/version/controller substitution permutations, duplicate/conflicting records, partial writes/rollback/reopen/concurrency, unauthorized service-level read-back exhaustively, cross-owner isolation matrix, etc.) is **not complete**.

## 13. J.3–J.6 regression results and N-04

- **J.3 schema-v1:** preserved (focused schema tests passed).
- **J.4 policy-version hardening:** preserved (focused tests passed).
- **J.5 lifecycle/mock-boundary:** preserved (focused lifecycle tests passed).
- **J.6 canonical persistence/read-back:** preserved and extended in service paths (focused J.6 tests passed).
- **N-04:** `broker/app/docker_adapter.py` and `manager/app/runtime/docker_adapter.py` remain fail-closed/unavailable in source; `manager/tests/test_runtime_adapter.py` passed. **No operational Docker client/socket access/fallback introduced. N-04 not claimed closed** (no host/runtime proof, compatibility exports/boundary cleanup not fully evidenced as closed).

## 14. Exact test commands and results

Environment: `.\venv\Scripts\python.exe` (Windows). Common warnings observed: `PytestDeprecationWarning` (`asyncio_default_fixture_loop_scope` unset), `PydanticDeprecatedSince20` (class-based config). Exit code `1` shown by PowerShell in some captured runs is due to stderr warning output from `pytest`/Python; pytest summaries below are authoritative.

| Command | Collected | Passed | Failed | Skipped | Warnings | Duration | Exit/result |
|---|---:|---:|---:|---:|---:|---:|---|
| `py_compile` modified/added Python files (`controller_service.py`, J.7 test) | n/a | n/a | 0 | n/a | 0 | n/a | OK |
| `manage.py check` | n/a | n/a | 0 issues | n/a | 0 | n/a | OK |
| `pytest -q broker/tests/test_firewall_controller_canonical_lifecycle_integration_2j7.py` | 6 | 6 | 0 | 0 | 1 | 3.28s | PASS |
| Focused regressions (J.3/J.4/J.5/J.6/J.7, revoke+idempotency/lifecycle/helper/contract/identifier/active, manager runtime adapter) | 318 | 318 | 0 | 0 | 1 | 71.10s | PASS |
| `pytest -q broker/tests` (full) | 631 | 630 | 1 | 0 | 1 | 162.36s | 1 failed (`test_firewall_controller_cross_process_crash_recovery.py::test_xproc_conflicting_idempotency_same_key`) |
| Rerun failed cross-process test `...::test_xproc_conflicting_idempotency_same_key` | 1 | 1 | 0 | 0 | 1 | 0.91s | PASS on rerun (timing-sensitive/flaky; no J.7 idempotency logic changes) |
| `pytest -q manager/tests` (full) | 30 | 30 | 0 | 0 | 1 | 1.76s | PASS |

**Not executed:** real Docker/host/firewall/UDS/`SO_PEERCRED`/privileged helper/capability/iptables/nftables/systemd/cloud/live-host tests (not authorized).

## 15. Known limitations and remaining blockers

- N-02 remains **PARTIALLY IMPLEMENTED**: legacy broker models not unified/migrated; not all read-back/inspect surfaces are canonical-body authoritative; full envelope/legacy adapter/rejection/quarantine and adversarial coverage incomplete.
- RR-05 (full-scan reconciliation/partial-state hardening) remains **OPEN** beyond targeted checks added.
- RR-06/M-06 DB integrity constraints/migrations and comprehensive persistence safety evidence remain incomplete.
- I-07/RR-01–RR-04, I-08/RR-07, I-09 not universally closed.
- N-04 partially resolved only (fail-closed source, no host/runtime proof).
- Host-dependent gates/HV-EC and real integration remain **NOT READY**.
- T-11, T-13, T-27 remain **OPEN — ACCEPTANCE REQUIRED**.

## 16. Recommended next phase

1. Complete canonical read-back authority and fail-closed behavior across all remaining applicable inspect/verify/reconcile/read-back/response surfaces, including explicit legacy handling decisions (reject/quarantine/validated adapter) with tests.
2. Expand deterministic adversarial/fault-injection coverage and persistence/transaction safety tests on disposable DBs (no destructive ops on real DB).
3. Address RR-05/RR-06 and safe additive integrity constraints/migrations with evidence; continue I-07/I-08/I-09 hardening where mock-only feasible.
4. Reassess gate register with implementation evidence only; do not claim host/live readiness.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
