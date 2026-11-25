# Phase 2L.2J.18 — Reconciliation Contract Matrix (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be` | **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | **Date:** 2026-11-16

Evidence basis: inspected `broker/firewall_controller_service/controller_service.py` (`reconcile_pending_operations`), `broker/firewall_controller_service/request_validator.py`, `broker/app/firewall_controller_contract.py` (`_validate_request`), ownership-store APIs, and existing J.9–J.17/J.18 tests. Mock-only; no host/runtime claims.

## 1. Actual public/internal contract

| Aspect | Actual behavior (inspected) | Evidence/gaps |
|---|---|---|
| Entry points | `FirewallControllerService.reconcile_pending_operations(req)`; `MockControllerTransport.reconcile_pending_operations`; mock backend dispatch; controller interfaces declare method. No dedicated broker HTTP route or manager-facing reconcile route found in inspected code. | Code inspection; route search. |
| Request validation | `auth.authorize(req,'reconcile_pending_operations')` then `validator.validate(req)` (`_validate_request`) requires `request_id, operation_id, idempotency_key, policy_id, policy_version, compiled_rule_digest` (64-hex). Service also validates canonical caller IDs and optional identifiers. | Contract/validator/service code, identifier tests. |
| Per-policy vs full-inventory | **Per-policy contract is the validated public path.** Implementation contains `list_ownerships()` scan when `policy_id/policy_version` absent, but standard validator/contract requires those fields, making full-scan unreachable through validated public contract. `_validate_caller_identifiers(..., require_policy=False)` comment acknowledges full-scan mode intent but not publicly exposed by current contract. | Code inspection. **Full-inventory API not implemented/exposed as additive validated contract in J.18.** |
| Required identifiers | `request_id`, `operation_id`, `idempotency_key`, `policy_id`, `policy_version`, `compiled_rule_digest`; optional `instance_id`, `network_id`, `address_family`/families as applicable and must match authoritative ownership when present. | Contract/service/tests. |
| Ownership/policy-version binding | Authoritative ownership loaded by `(policy_id, policy_version)`; caller metadata validated against persisted record (`_validate_ownership_binding`); identity unchanged checks in mutating/recovery paths. | Service code, J.8–J.17 suites. |
| Inventory accounting (covered per-policy) | Targeted record receives explicit outcome via `result.reconciled`, `result.uncertain`, or `result.errors`; persistence failures produce error bucket and overall `RECONCILIATION_PERSISTENCE_FAILURE`. No ownership case returns explicit uncertain `no_ownership_no_adoption`. Pending idempotency records scoped to policy appended as uncertain (`pending_no_auto_replay`). | J.9/J.10/J.18 tests. |
| Silent-skip behavior | Unknown persisted state -> explicit uncertain `corrupt_ownership_state`. Known but unhandled state -> explicit uncertain `unhandled_lifecycle_state:{state}`. VERIFYING explicitly uncertain. Missing/invalid evidence/canonical body/bindings/backend uncertainty produce explicit uncertain reasons in covered paths. **Orphan lifecycle history rows without ownership and other non-ownership-table records are not scanned by per-policy ownership-targeted reconciliation** (limitation of current contract). | Code inspection/tests. |
| Idempotency interaction | Reconcile is an authorized/validated operation; pending idempotency records are reported as uncertain (no auto-replay). Service-level idempotency handling applies to operation requests per existing model; no full idempotency redesign in J.18. | Code, J.8+ behavior. |
| Authorization/resource limits | Authz required (`reconcile_pending_operations` operation). No pagination/bounded-scan contract for full inventory because full inventory not exposed. | Code inspection. |

## 2. Full-inventory API decision (J.18)

| Consideration | Assessment |
|---|---|
| Existing requirement for full scan | No validated public contract/API currently exposes full-inventory reconciliation; per-policy contract is established and tested. |
| Safe implementability with current models | `list_ownerships()` exists internally, but safe public exposure requires additive schema/contract, strict validation, authorization/ownership semantics, bounded pagination/snapshot, deterministic complete-vs-partial signaling, and concurrency/deletion/orphan handling. |
| Pagination/bounded processing | Not defined in current contract. |
| Concurrent changes/snapshot semantics | Not defined for full scan. |
| Deleted/stale/orphaned records representation | Ownership-table scan would omit orphan history without ownership; complete cross-table inventory semantics undefined. |
| Authorization/resource limits | Not specified for full scan. |
| Decision | **Deferred (not justified/safe as additive change in J.18).** Preserve per-policy contract; document limitation precisely. No new list-all endpoint added. |

## 3. Per-policy explicit outcome semantics (covered)

| Condition | Typical outcome bucket/reason |
|---|---|
| No ownership for target | `uncertain`: `no_ownership_no_adoption` |
| Corrupt ownership record/binding | `uncertain`: `corrupt_ownership_record` |
| Invalid canonical policy body / digest mismatch | `uncertain`: `invalid_canonical_policy_body` / `canonical_policy_digest_mismatch` (+ reconciliation status updates where possible) |
| Unknown/unsupported persisted state | `uncertain`: `corrupt_ownership_state` |
| VERIFYING | `uncertain`: `verifying_state_uncertain` |
| VERIFIED with valid evidence | `reconciled`: `promoted_to_active` (if CAS/identity checks pass) |
| VERIFIED without valid evidence | `uncertain`: `verified_without_valid_evidence` |
| ACTIVE, backend consistent | `reconciled`: `active_ok` |
| ACTIVE, backend mismatch/unavailable | `uncertain`: `active_backend_mismatch_or_unavailable` |
| REQUESTED/INSTALLING/VALIDATING, backend unavailable | `uncertain`: `backend_readback_unavailable` |
| REQUESTED/INSTALLING/VALIDATING, backend installed | `reconciled`: `marked_needs_verification` (no false ACTIVE without verification evidence) |
| REQUESTED/INSTALLING/VALIDATING, backend missing | `reconciled`: `marked_failed_backend_missing` (fail closed) |
| REQUESTED/INSTALLING/VALIDATING, unknown backend state | `uncertain`: `unknown_backend_state:*` |
| REVOKING, backend missing/revoked with valid evidence path | `reconciled`: `revoke_confirmed` / `revoke_already_confirmed` |
| REVOKING, backend still present | `uncertain`: `partial_revoke_backend_still_present` |
| REVOKING, backend readback unavailable | `uncertain`: `backend_readback_unavailable_during_revoke` |
| REVOKED, valid evidence | `reconciled`: `already_revoked` |
| REVOKED, missing/invalid evidence | `uncertain`: `revoked_without_valid_evidence` |
| FAILED/CLEANUP_PENDING/ORPHANED | `reconciled`: `no_auto_change_terminalish` |
| Known but unhandled state (future/defensive) | `uncertain`: `unhandled_lifecycle_state:*` |
| Persistence failure during processing | `errors`: `PERSISTENCE_FAILURE` and overall error `RECONCILIATION_PERSISTENCE_FAILURE` |
| Pending idempotency (scoped) | `uncertain`: `pending_no_auto_replay` |

**No false ACTIVE/VERIFIED promotion** is permitted by design in covered paths; evidence/canonical-body/ownership/CAS/backend-readback checks gate transitions.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
