# Post-J.20 Stage 1A — Entry-Point Coverage Matrix (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (`main`)  
**Baseline (unchanged):** 26 modified tracked files, 369 untracked entries before Stage 1A file additions (planning docs present; preserved)  
**Date:** 2026-11-17  
**Scope:** N-02, H-05, I-07, RR-01–RR-04 (canonical policy authority/legacy boundary/authorization & validation in covered mock-only paths)

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

## 1. Method

- Inspected J.20 readiness/remediation/gate artifacts, canonical schema/helpers, controller service/store, helper contract, broker app contract/validators/controllers, legacy flat-rule subsystem (`broker/app/firewall_policy.py`, `firewall_compiler.py`, `firewall_state.py`), broker routes, and existing J.3–J.18+ firewall controller tests.
- Searched for manager-facing rule-bearing firewall controller paths (`manager/app`, `manager/**`) — none identified.
- Determined gaps from source evidence; implemented only smallest safe additive fail-closed fixes in covered mock-only paths.

## 2. Rule-bearing / canonical policy operations (controller service)

| Operation/path | Canonical schema-v1 enforcement (when rules/body present) | Trusted canonical persistence/read-back authority | Ownership/policy-version/digest binding | Identifier/validation notes | Coverage status |
|---|---|---|---|---|---|
| `install_policy` (`FirewallControllerService._call`) | `validate_install_policy_rules` on install ingress when rules present; rewrites normalized rules/families/digests; fail-closed on `RuleSchemaError` | Persists canonical body via `ensure_canonical_policy_body` when schema-v1 rules present; legacy no-rules path does not create schema-v1 body | Authoritative ownership resolved/bound; caller metadata compared only; first-install intent persisted with validated fields | Auth, request contract, canonical caller identifiers validated before ownership/idempotency side effects; bounded canonical error sanitization | **Covered (mock-only, evidenced by prior + Stage 1A regressions)** |
| `verify_policy` | Relies on authoritative ownership + stored/request digests; canonical body required/validated before evidence/lifecycle promotion when present | Trusted read-back required when canonical body exists; request digest checked against trusted body digest | Authoritative ownership revalidated post-backend; CAS/lifecycle transitions enforced | Canonical IDs/contract validated | **Covered** |
| `inspect_policy` | N/A (read) | Trusted read-back required when canonical body exists; response `canonical_policy` derived from trusted persisted body when present (no untrusted fabrication on canonical path) | Authoritative ownership/binding enforced | Canonical IDs/contract validated | **Covered** |
| `revoke_policy` (+ recovery/completion) | N/A | Evidence/CAS/read-back based completion; canonical body presence checked in reconcile contexts where applicable | Authoritative ownership/CAS/evidence required; no false REVOKED without evidence | Canonical IDs/contract validated | **Covered** |
| `remove_stale_policy` | N/A | Trusted canonical read-back pre-check when body exists (`required=False`) | Authoritative ownership required | Canonical IDs/contract validated | **Covered** |
| `reconcile_pending_operations` | N/A | Trusted canonical read-back/validation required when canonical body exists; fail-closed uncertain on corrupt/invalid/mismatch; no adoption of unknown backend rules without ownership | Targeted reconcile binds caller metadata to authoritative ownership; per-record ownership validation in scans; CAS/evidence checks | Canonical IDs/contract validated; full-scan policy_id-optional semantics preserved with supplied-ID validation | **Covered (per-policy contract, mock-only)** |
| `health_check` | N/A | N/A | Contract fields required; no ownership authority granted | Auth + request contract + canonical caller identifiers validated in service path | **Covered (service path)** |

## 3. Other entry points / boundaries

| Entry point | Behavior (inspected) | Stage 1A action | Coverage status |
|---|---|---|---|
| `broker/app/firewall_controller_contract._validate_request` + `RequestValidator` | Enforces required fields, policy_version type/range, 64-hex `compiled_rule_digest`; **does not enforce canonical ID regex** for request/operation/idempotency/policy IDs (historical behavior; service enforces in covered paths) | **Not changed** (to preserve existing exception semantics/compatibility evidenced by `identifier_validation_entrypoints` expectations) | **Partially covered** (contract-level canonical ID format remains service-enforced in covered service paths) |
| `broker/app/firewall_controller.MockFirewallController` (app-layer mock controller) | Separate in-memory controller; schema-v1 rule validation on install when rules present; contract validation and idempotency semantics local to mock | **Hardened (additive):** canonical ID format validation added for request/operation/idempotency/policy and optional instance/network when provided on health/install/inspect/verify/revoke/remove-stale/reconcile; fail-closed with `FirewallControllerRequestError` before side effects in covered paths | **Improved (covered mock entry point)** |
| `broker/firewall_controller_service/helper_contract.py` | Strict schema version/operation, rejects unknown fields and caller-supplied auth claims, validates IDs/digests/ownership refs/CIDR/ports/compiled/rules (schema-v1 when present) | No change | **Covered (existing)** |
| `broker/app/routes.py` (broker HTTP API) | Container lifecycle endpoints only; no firewall controller rule-bearing policy operations exposed | No change | **Not applicable / no firewall entry point** |
| Manager-facing firewall controller paths (`manager/app`, clients) | No rule-bearing firewall controller install/inspect/verify/revoke/reconcile paths identified | No change | **Not identified** |

## 4. Legacy flat-rule subsystem (separate domain)

| Component | Inspected behavior | Canonical equivalence / adapter status | Classification |
|---|---|---|---|
| `broker/app/firewall_policy.py` (`FirewallPolicyModel`) | Flat target model (ip/subnet/port/protocol, direction, ipv4/ipv6), ownership/membership verification, different validation semantics | Different schema/fields/semantics from `rule-schema-v1`; no proven canonical equivalence | **Not automatically convertible; requires explicit validated adapter/migration design if ever unified** |
| `broker/app/firewall_compiler.py` (`FirewallRuleCompiler`) | Flat rule compilation and SHA-256 digest over legacy canonical serialization | Different digest domain from schema-v1 compiled/canonical policy digests | **Must not be silently reinterpreted as schema-v1 authority** |
| `broker/app/firewall_state.py` (`FirewallStateStore`) | Legacy broker DB policy/evidence lifecycle and digest verification | Separate persistence/lifecycle model | **Separate/quarantined domain relative to controller schema-v1 authority** |
| Controller service legacy no-rules requests | Accepted by existing behavior; no schema-v1 canonical body required/persisted; must not be silently treated as schema-v1 canonical policy | Compatibility path preserved where evidenced; no silent conversion | **Preserved compatibility (non-schema-v1), not canonical schema-v1 authority** |

Stage 1A confirmed no inspected silent conversion from legacy flat-rule subsystem to schema-v1 canonical controller bodies (`test_legacy_flat_rule_subsystem_not_silently_converted_to_schema_v1`).

## 5. Entry points covered vs uncovered (summary)

- **Covered/improved in Stage 1A scope:** `FirewallControllerService` canonical install/inspect/verify/revoke/remove-stale/reconcile paths (existing evidence + focused regressions), `MockFirewallController` app-layer mock entry points (canonical ID hardening), helper contract ingress (existing), legacy no-rules compatibility behavior (existing), no-silent-conversion boundary for legacy flat-rule domain (test/documented).
- **Uncovered / not universally proven:** canonical ID format enforcement at app-layer `RequestValidator/_validate_request` boundary (exception/type semantics preserved; service enforcement relied upon), all hypothetical/unused public routes for controller operations (none identified), end-to-end manager-facing rule-bearing controller transport (not identified), universal alias/ambiguous-field rejection across every possible future entry point, DB-constraint/migration-level enforcement, live transport/host boundaries (out of scope/unauthorized).

**No claim of universal enforcement.**
