# Phase 2L.2J.15 — Policy Entry-Point Inventory (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be` | **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (`main`) | **Date:** 2026-11-16

This inventory covers policy-related entry points that accept, construct, transform, persist, read, or return policy/canonical-rule data in the inspected mock-only firewall-controller and related broker/manager paths. It is evidence-based against actual source; universal closure is **not claimed** beyond documented covered paths.

## 1. Canonical schema-v1 authority components (reused)

| Component | File | Role |
|---|---|---|
| `rule_schema_v1` | `broker/firewall_controller_service/rule_schema_v1.py` | Canonical `RULE_SCHEMA_VERSION="rule-schema-v1"` (2H.1 §4.4.1) validation/normalization, `compiled_rule_digest`, `canonical_policy_digest`, compiled-mirror validation (`PROTOCOL_SCHEMA_VERSION="2L.2I.2"` context), `validate_install_policy_rules` |
| Canonical persistence/read-back | `broker/firewall_controller_service/ownership_store.py` | `controller_policy_bodies` table, `store_canonical_policy_body`, `ensure_canonical_policy_body`, `get_canonical_policy_body`, `read_trusted_canonical_policy_body` (revalidate/recompute/bind/digest checks) |
| Service integration | `broker/firewall_controller_service/controller_service.py` | Install-path schema-v1 validation/persistence, trusted read-back for inspect/verify/reconcile/remove-stale (where body exists), canonical inspect enrichment, fail-closed sanitization |

## 2. Broker/controller request & validation entry points

| Entry point | File / symbol | Input representation | Validation performed | Canonical authority used | Ownership/version/digest binding | Persistence/read-back | Response source | Error behavior | Relevant tests | Remaining gaps |
|---|---|---|---|---|---|---|---|---|---|---|
| Broker contract request validation | `broker/app/firewall_controller_contract.py` `_validate_request`, `ControllerRequest` | Dict with required ids, `policy_id`, `policy_version`, `compiled_rule_digest`, optional instance/network/families/ownership | Required non-empty fields, `policy_version` int/bool-negative rejected, digest length >=16 (weak vs canonical 64-hex) | None directly (transport/contract layer) | Not authoritative | None | N/A | `FirewallControllerRequestError` | `test_firewall_controller_contract.py`, policy-version/id suites | Canonical 64-hex digest and canonical request/operation/idempotency ID format not enforced here; broader envelope fields not covered |
| Request validator | `broker/firewall_controller_service/request_validator.py` `RequestValidator.validate` | Dict request | Delegates to `_validate_request` | None | None | None | N/A | Wraps as `FirewallControllerRequestError` | contract/id suites | Same as contract; no canonical ID pattern enforcement |
| Controller service dispatch | `broker/firewall_controller_service/controller_service.py` `_call`, public methods | Dict request + peer-injected identity in strict/mock transport paths | Auth (`StrictAuthorizationProvider`/mock), validator, canonical caller identifier validation (policy/instance/network), install schema-v1 rule validation when `rules` present, digest/idempotency/ownership binding checks | `rule_schema_v1` on install when rules present; trusted canonical read-back when body exists | Authoritative ownership record required for non-install/non-health operations; digest/family/instance/network/ownership-ref/version checked | Ownership/evidence/history/idempotency/canonical body via `ownership_store` | Service-constructed responses; inspect may enrich from trusted canonical body | Bounded fail-closed errors/sanitization in covered paths; `PermissionError`/controller errors | J.3–J.13 suites, helper/identity/identifier/contract tests | Universal entry-point/field coverage not inventoried/proven; request/operation/idempotency IDs not canonically pattern-validated at service boundary in all cases |
| Helper contract (mock boundary) | `broker/firewall_controller_service/helper_contract.py` `validate_helper_request/response` | Helper envelope dict, `SCHEMA_VERSION="2L.2G.3"` (exact match required) | Strict unknown-field rejection, forbidden auth-claim rejection, mandatory schema/IDs, 64-hex digest, ownership ref, canonical ID pattern, timeout bounds, compiled data-only checks, schema-v1 rule validation when `rules` present | `rule_schema_v1.validate_install_policy_rules` when rules present | Requires authoritative ownership reference/digest/family context for non-health | None | Validated response envelope | `HelperContractError` codes (incl. `UNSUPPORTED_SCHEMA_VERSION`) | `test_firewall_controller_helper_contract.py`, identity propagation tests | Envelope version `2L.2G.3` intentionally distinct from rule `rule-schema-v1`/protocol `2L.2I.2` (see alignment analysis); full 2L.2I.2 migration out of scope |
| Mock helper executor/backend | `broker/firewall_controller_service/mock_helper_executor.py`, `mock_backend.py`, `backend_interface.py` | Helper-shaped requests | Helper contract validation, identity/auth checks per implementation | Helper contract/rule-schema-v1 via validation | Depends on request; mock-only | Mock | Mock results | Contract/auth errors | helper/identity/contract tests | Mock-only; real helper unimplemented |
| Mock firewall controller state (broker app) | `broker/app/firewall_controller.py` `MockFirewallController` | Contract-style dict requests | `_validate_request`, schema-v1 rule validation/normalization on install when rules present, idempotency/digest conflict checks | `rule_schema_v1` on install rules | Limited mock ownership model | In-memory installed/verified/revoked/idempotency maps | Mock responses | `FirewallControllerRequestError`/idempotency errors | J.5 lifecycle tests, contract tests | Mock-only state; not canonical ownership/evidence store authority |
| Transport/mock transport | `broker/firewall_controller_service/transport.py`, `mock_transport.py`, `peer_identity.py` | Request + `PeerIdentity` | Injects peer uid/gid into request; no caller-trusted identity | N/A | N/A | N/A | Service responses | Auth errors on missing peer | identity/transport-related tests | Real `SO_PEERCRED`/UDS transport not implemented |

## 3. Canonical persistence, read-back, and lifecycle paths

| Path | File / methods | Canonical authority / behavior | Remaining gaps |
|---|---|---|---|
| Install | `controller_service._call` install branches, `_ensure_canonical_policy_body_persisted` | Schema-v1 validate/normalize, digest checks, ownership intent/creation, canonical body persistence for schema-v1 rule-bearing requests, lifecycle transitions/CAS | Multi-step flow not single-transaction atomic; legacy no-rules preserved (no canonical body required) |
| Inspect | `inspect_policy` / `_call` | Requires authoritative ownership; trusted canonical read-back when body exists; response enriched with validated canonical policy data only on success; fail-closed on invalid/corrupt/mismatch | Universal response derivation across all representations not fully proven |
| Verify | `verify_policy` / `_call` | Trusted canonical read-back required when body applies before evidence/promotion; digest consistency checked; evidence + CAS transitions to VERIFIED/ACTIVE | Same atomicity/coverage caveats |
| Revoke / remove-stale | `revoke_policy`, `remove_stale_policy`, reconcile helpers | Ownership/identity checks, read-back confirmation/evidence rules, fail-closed uncertain handling | Exhaustive matrices incomplete (RR-05) |
| Reconciliation | `reconcile_pending_operations` | Ownership validation, trusted canonical read-back when body exists, backend read-back, uncertain classification, no-silent-skip for key states, no auto-replay pending idempotency | Per-policy contract covered; full-scan/all-eligible and exhaustive evidence/fault correctness unproven |
| Store | `ownership_store.py` | Transactional per-method operations, uniqueness/CAS/indexes, canonical body binding/validation on read/write | DB-enforced append-only/immutability and digest CHECK constraints/migrations absent (RR-06/M-06); multi-table/service atomicity not guaranteed |

## 4. Legacy broker policy subsystem (separate from schema-v1 controller canonical authority)

| Component | File | Representation | Behavior | Boundary classification |
|---|---|---|---|---|
| Legacy flat firewall policy model | `broker/app/firewall_policy.py` (`FirewallPolicy`, `FirewallPolicyTarget`, `FirewallPolicyModel`) | Flat targets (ip/subnet/port/protocol/direction/ip_version), ownership/membership verified against network/container stores | Validates targets/protocols/CIDRs/ports/membership; rejects proxy source, unrestricted destinations/ports | **Legacy, separate model** — not `rule-schema-v1`; not silently interpreted as schema-v1 canonical controller policy |
| Legacy firewall compiler | `broker/app/firewall_compiler.py` (`FirewallRuleCompiler`) | Compiles legacy `FirewallPolicy` to flat rule dicts + SHA-256 digest over canonical JSON serialization | Requires ownership-verified policy/targets; deterministic ordering/digest | **Legacy compiler/digest domain** distinct from controller schema-v1 rule digest/canonical body |
| Legacy firewall state store | `broker/app/firewall_state.py` (`FirewallStateStore`) | Persists legacy compiled policies/evidence in `firewall_policies`/verification tables (broker DB) | Lifecycle transitions, digest recompute/verify, evidence checks | **Legacy persistence/state machine** — separate from controller `controller_ownership`/`controller_policy_bodies` authority |
| Membership verifier | `broker/app/firewall_membership.py` | Network/container ownership and subnet/IP containment checks | Fail-closed on missing/inconsistent metadata | Legacy support component |

**Explicit boundary:** legacy no-rules behavior in controller paths remains supported where already implemented (no schema-v1 canonical body required). Legacy flat-rule subsystem (`firewall_policy/compiler/state`) is an independent pre-existing domain and **MUST NOT** be automatically converted to or treated as schema-v1 canonical controller policy without an explicit, validated compatibility contract (none implemented). No silent reinterpretation observed in inspected controller schema-v1 paths.

## 5. Manager-facing policy-related paths

| Entry point | File | Behavior | Gaps |
|---|---|---|---|
| Manager API routes | `manager/app/routes.py`, `main.py` | Health/catalog/provision/inspect/stop/cleanup endpoints; bearer auth dependency; runtime operations return unavailable in inspected paths | No firewall-controller policy schema-v1 request/response authority path inspected as active; universal response/error sanitization not audited end-to-end |
| Manager auth/runtime | `manager/app/auth.py`, `runtime/*` | Token auth, runtime adapter fail-closed | Out of J.15 canonical-policy closure scope except boundary awareness |

## 6. Contract/schema version alignment (analysis)

| Version | Where defined | Meaning | Compatibility/behavior |
|---|---|---|---|
| `SCHEMA_VERSION="2L.2G.3"` | `broker/firewall_controller_service/helper_contract.py` | **Helper/controller-envelope schema** for mock helper boundary (strict required exact match; request/response validated) | Intentional envelope version for current mock helper contract; incompatible/unsupported values rejected (`UNSUPPORTED_SCHEMA_VERSION`/invalid). Not renamed in J.15. |
| `PROTOCOL_SCHEMA_VERSION="2L.2I.2"` | `broker/firewall_controller_service/rule_schema_v1.py` | Protocol context for compiled-mirror schema-v1 semantics when explicitly provided | Used only when compiled mirror claims schema-v1 form; legacy/mock compiled shapes without schema-v1 mirror markers not forced into this form |
| `RULE_SCHEMA_VERSION="rule-schema-v1"` | `rule_schema_v1.py`, enforced in ownership store canonical body handling | Canonical firewall rule schema for 8-field normalized rules and trusted canonical policy bodies | Authoritative for schema-v1 rule-bearing controller operations where applicable; trusted read-back requires schema-v1 when enforced |

**Conclusion:** multiple schema/version identifiers represent different layers (helper envelope vs compiled-mirror protocol vs canonical rule schema). They are not interchangeable. J.15 does not rename them; alignment is documented and existing exact-match rejection behavior is preserved.

## 7. Summary of demonstrated gaps (J.15 focus)

- Service/contract validation gaps in covered boundaries: `compiled_rule_digest` accepted as length>=16 in broker contract validator but canonical paths require 64-hex; `request_id`/`operation_id`/`idempotency_key` not canonically pattern-validated at controller service boundary despite helper enforcing canonical ID form (risk of inconsistent acceptance/DB binding values across layers).
- Universal canonical authority/response derivation and legacy envelope migration remain incomplete (out of full closure).
- Legacy subsystem explicitly separate; no silent schema-v1 conversion found.

(Inventory to be read alongside J.15 engineering/verification reports and gate updates.)
