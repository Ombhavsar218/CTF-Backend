# Post-J.20 Stage 1B.13 — Error Sanitization Assessment

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.**

Repository: `E:\Flag-hunt\ctf-platform-be` | HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`  
Milestone: Stage 1B.13 (2026-11-18), mock-only assessment of bounded outward errors across existing controller boundaries.

## 1. Assessment question

Can internal validation, schema, backend and persistence failures cross the mock controller boundary without exposing raw `str(e)`, raw backend messages or raw schema-validation text, while preserving exception classes, error codes, status semantics and storage-failure classification?

**Scoped answer: yes for the covered mock boundaries.** This is not a claim about host, transport, live-backend or formal-acceptance closure.

## 2. Centralization design

`broker/firewall_controller_service/error_sanitization.py` is the single bounded-message/category module:

- `:22-28` fixed public messages;
- `:31-55` bounded message helpers that never read exception text;
- `:58-60` internal log-safe summary (`error_type` only);
- `:63-72` constructors preserving public exception classes;
- `:75-92` persistence versus canonical-integrity classification.

`controller_service.py:256-287` contains the controller-local response sanitizer that applies those constants to outward `error` responses by error-code category. This is not a parallel validation framework: it operates only on already-produced controller responses and delegates message constants/classification to the central module. `broker/app/firewall_controller.py` uses fixed bounded strings directly at its mock boundary to avoid re-introducing the documented import-order cycle (`firewall_controller.py:74-76`).

## 3. Outward mapping contract

| Internal cause | Public exception / response | Stable code / status | Outward text | Internal diagnostics |
|---|---|---|---|---|
| Contract/request validation | `FirewallControllerRequestError` | `REQUEST_INVALID` | `Invalid request` or an explicitly bounded field message | Event name/type only; no raw schema text |
| Schema-v1 rule validation | `FirewallControllerRequestError` | `REQUEST_INVALID` | `Invalid request` | `rule_schema_validation_failed` with `code`; no raw exception text (`controller_service.py:896-902`) |
| Identifier alias/malformed input | `FirewallControllerRequestError` | `REQUEST_INVALID` | `Invalid <field>` / `Invalid request` | No raw value retained in outward object |
| Authorization/ownership denial | `FirewallControllerAuthError` / `PermissionError` | Established denial semantics | Unchanged bounded denial | Audit event/operation only |
| Same-key/different-payload or corrupt ledger | `FirewallControllerIdempotencyError` | Idempotency conflict class/messages | Allow-list at `controller_service.py:1607-1615` | Bounded `details`; no raw DB/driver text |
| Backend exception or leaky response | `FirewallControllerBackendError` / error response | Backend error status/code preserved | `Backend operation failed` / `Backend failure` | Exception type in audit; raw text discarded |
| Canonical ownership category | `PermissionError` | Denial status | `Authoritative ownership required` | Typed category only |
| Canonical integrity category | `FirewallControllerRequestError` | `REQUEST_INVALID` | `Invalid canonical policy` / `Invalid canonical policy record` | Typed category only |
| Storage failure (`BrokerDBError`, canonical persistence category, persistence exception) | `BrokerDBError` or `FirewallControllerPersistenceError` | `PERSISTENCE_FAILURE` where applicable | `Persistence failure`, or pre-existing bounded persistence messages | Structured bounded `details`; raw DB text removed |
| Unknown internal exception | `FirewallControllerBackendError` | Backend error class | `Backend operation failed` | Type-only audit summary |

The allow-lists at `controller_service.py:1569-1615` deliberately preserve established bounded messages while rejecting any message not in the published set. `PermissionError` is bounded by length and line-break checks (`:1617-1621`).

## 4. No-leak path analysis

### 4.1 Request/schema

- `request_validator.py:7-15` no longer wraps arbitrary `str(e)`.
- `controller_service.py:896-912` logs only the schema error code and raises a fixed message.
- `firewall_controller.py:75-88` maps both `RuleSchemaError` and digest mismatch to `Invalid request`.

Sentinel tests: `SENTINEL_SCHEMA_1B13_LEAK` is asserted absent from exception objects, `message`, `details`, and app-controller failures.

### 4.2 Backend

- Dispatch exceptions are swallowed with `from None` and replaced by `FirewallControllerBackendError("Backend operation failed")` (`controller_service.py:1281-1282`, `:1304-1307`, `:1622-1623`).
- Backend-supplied error responses are bounded by `_sanitize_outbound_response` (`:283-287`).
- Sanitization happens before idempotency completion (`:1524`) and again on cached replay (`:1274`, `:1554`).

Sentinel tests: `SENTINEL_BACKEND_1B13_LEAK` is asserted absent from raised exceptions, args, messages, details, first responses, replayed responses and the persisted `response_json`.

### 4.3 Persistence

- `BrokerDBError` remains `BrokerDBError` or `FirewallControllerPersistenceError`; it is never converted to a request-validation error (`controller_service.py:1579-1587`).
- Canonical read storage failures in reconciliation set `PERSISTENCE_FAILURE` via `mark_persistence_failure` (`:1734-1737`, `:1782-1813`).
- Install-failure persistence details include only a bounded backend error code and write-state booleans (`:289-313`).

Sentinel tests: `SENTINEL_PERSIST_1B13_LEAK` is asserted absent from exception objects/args/messages/details and reconciliation responses.

### 4.4 Canonical categories

`SENTINEL_CANON_1B13_LEAK` is asserted absent while ownership, integrity and persistence categories remain distinguishable by public exception class/code (`test_canonical_sanitization_preserves_categories_without_leakage`).

## 5. Assertion changes assessed

The following existing assertions were changed solely to match the new outward-sanitization contract:

- `test_post_j20_stage_1b6_targeted_residual_gaps.py:166-174`: now asserts that the injected raw storage phrase is absent while the failure remains `BrokerDBError` and no backend call occurs. It no longer requires raw storage detail outward.
- `test_post_j20_stage_1b3_durable_crash_recovery.py:302-308`, `:354-363`: injected internal `RuntimeError`s are now expected to surface as bounded `FirewallControllerBackendError`.
- `test_firewall_controller_residual_risk_remediation.py:264-272`: replayed errors still preserve `status` and `error_code`, but raw backend text is asserted absent.
- `test_firewall_controller_revoke_recovery_and_idempotency_hardening.py:203`, `:305`: lost-response backend failures now assert the existing public backend-error class.

These are contract-alignment changes, not weakened assertions: status, error class/code, no-side-effect and no-false-success assertions remain, and new no-leak assertions were added. No test was skipped or removed.

## 6. Concurrency stabilization

Full-suite verification exposed a same-key revoke race where a worker could reach the `IN_PROGRESS` CAS after a concurrent worker had already completed it. `controller_service.py:1257-1275` now re-reads the authoritative idempotency record and replays a completed response instead of returning a ledger conflict. Non-replayable states still fail closed, and no backend call is made after the conflict. Evidence: `post_j20_stage_1b13_concurrency_repeat.*` (5/5 isolated passes) and `post_j20_stage_1b13_concurrency_fix.*` (compile exit 0, 5/5 passes).

## 7. Residual assessment

- Sanitization coverage is source-proven for the existing mock controller, request validator and service boundaries enumerated in Stage 1B.12.
- Host/runtime transport, kernel identity, Docker authority, privileged helper, live backend, migrations/constraints and production error handling are outside this stage.
- The assessment does not close SR-06, SR-10, I-09, T-11, T-13 or T-27 and does not convert conditional readiness into formal acceptance.
- Passing mock tests are not host or production security proof.

## 8. Conclusion

Stage 1B.13 achieves its narrow mock-only engineering objective: raw validation, schema, backend and persistence details are replaced by bounded outward messages; exception classes, codes and status semantics are preserved; storage failures retain storage classification; and detailed diagnostics remain internal. Final decision: **scoped implementation and verification complete**, with all security gates and authority decisions unchanged.

See `docs/POST_J20_STAGE_1B_13_SECURITY_TEST_EVIDENCE.md` and `docs/POST_J20_STAGE_1B_13_FINAL_VERIFICATION_REPORT.md` for execution evidence and final state.
