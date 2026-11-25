# Post-J.20 Stage 1B.13 — Canonical Validation Implementation

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.**

Repository: `E:\Flag-hunt\ctf-platform-be` | HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`  
Milestone: Stage 1B.13 (2026-11-18), narrowly scoped **mock-only** implementation of universal canonical validation and bounded outward error handling across the existing mock controller boundaries.

## 1. Scope and constraints

This stage implements only the mock-only remediation justified by Stage 1B.12:

- canonical identifier validation at controller entry points;
- request identity, policy, ownership and canonical-policy binding validation before lookup, mutation, persistence and backend dispatch;
- malformed input / alias rejection and explicit fail-closed behavior;
- centralized outward-facing error mapping with bounded messages;
- preservation of established exception classes, error codes and status semantics;
- storage-failure classification without converting persistence failures into validation errors.

It did **not** add a parallel validation framework, a second state machine, a duplicate authority source, host/runtime work, Docker/socket access, UDS/`SO_PEERCRED`, privileged-helper changes, Linux capabilities, nftables/iptables/DOCKER-USER changes, host firewall changes, live-backend operations, cloud deployment, Stage 1C, gate closure, or residual-risk acceptance.

## 2. Implementation inventory

### 2.1 Central outward-error helper (new)

`broker/firewall_controller_service/error_sanitization.py:22-92` defines bounded public messages (`Invalid request`, `Invalid identifier`, `Invalid canonical policy`, `Persistence failure`, `Backend failure`, `Unauthorized`), bounded message helpers, exception-to-public-error constructors, log-safe exception summaries (`error_type` only), and typed persistence/canonical-integrity classification helpers. Raw exception text is never used as an outward message.

### 2.2 Service boundary — validation before side effects

| Source location | Implemented control |
|---|---|
| `controller_service.py:231-246` | `_validate_caller_identifiers` enforces canonical `request_id`, `operation_id`, `idempotency_key`, `policy_id`, and optional `instance_id` / `network_id`. Reconciliation full-scan mode validates identifiers that are supplied without requiring a policy ID. |
| `controller_service.py:866-891` | Authorization and contract validation still precede all other work; canonical identifier validation runs immediately afterward, before digest calculation, idempotency lookup and authoritative ownership lookup. |
| `controller_service.py:896-912` | Schema-v1 validation/normalization runs before ownership/idempotency side effects. `RuleSchemaError` is mapped to `FirewallControllerRequestError("Invalid request")`; digest mismatch is also fail-closed. |
| `controller_service.py:919-928` | Same-key/different-payload conflict is rejected before ownership resolution, preserving `FirewallControllerIdempotencyError`. |
| `controller_service.py:930-953` | Authoritative ownership is resolved and bound before replay. A late same-key conflict is still classified as idempotency conflict, not disclosure. |
| `controller_service.py:1245-1255` | Canonical policy-body persistence and trusted read-back pre-checks occur before the operation-ledger transition and backend dispatch. |
| `controller_service.py:1257-1275` | `IN_PROGRESS` is committed before backend dispatch. A concurrent same-key worker that already completed is now handled by replaying the authoritative completed response instead of surfacing a raced ledger conflict; no second backend call is permitted. |
| `controller_service.py:537-577` | Cached replay is accepted only when the stored digest, authoritative ownership record, resource key and recorded ownership identity snapshot all match. |
| `controller_service.py:474-535` | Canonical read failures are fail-closed: ownership → `PermissionError`, integrity → bounded request error, storage → bounded persistence error. |
| `controller_service.py:1782-1830` | Reconciliation validates canonical bodies before lifecycle decisions and classifies read/storage failures as persistence failures, not as invalid canonical policy bodies. |

### 2.3 Service boundary — bounded outward responses

| Source location | Implemented control |
|---|---|
| `controller_service.py:256-287` | `_safe_backend_error_code` allows only a bounded code shape; `_sanitize_outbound_response` bounds error messages by category while preserving `status`, `result` and `error_code`. |
| `controller_service.py:289-313` | Install-failure persistence details carry only a bounded backend error code and bounded write-state booleans; raw storage/backend text is not retained in outward details. |
| `controller_service.py:1277-1307` | All backend dispatch exceptions are mapped to the existing `FirewallControllerBackendError("Backend operation failed")`; health and operation dispatch both use this mapping. |
| `controller_service.py:1523-1559` | Responses are sanitized **before** idempotency completion/persistence. Cached responses are sanitized again on conflict replay, so raw backend text cannot reappear from durable replay. |
| `controller_service.py:1561-1623` | The outer `_call` classifier bounds persistence, backend, request, idempotency, authorization, permission and unknown exceptions while preserving public classes/codes. `BrokerDBError` remains a storage failure; canonical ownership/integrity categories are mapped without raw text. Unknown internal exceptions become `FirewallControllerBackendError("Backend operation failed")`. |
| `request_validator.py:1-15` | The former raw `str(e)` wrapping was replaced by a fixed bounded `INVALID_REQUEST_MESSAGE`; bounded contract `FirewallControllerRequestError`s pass through unchanged. |

### 2.4 Mock app-controller boundary

`broker/app/firewall_controller.py:47-58` applies the canonical identifier pattern to request correlation, idempotency, policy and optional instance/network identifiers. `health_check` (`:60-70`) bounds generic failures; `install_policy` (`:72-90`) bounds schema/digest failures while retaining the lazy schema import needed to avoid the known import-order cycle. Inspect, verify, revoke, remove-stale and reconcile entry points (`:120-189`) call the same identifier validation before state mutation or replay.

## 3. Before/after coverage

| Stage 1B.12 gap | Before | After (source-backed) |
|---|---|---|
| Raw request-validation wrapping | `RequestValidator` wrapped arbitrary `str(e)` into `FirewallControllerRequestError`. | `request_validator.py:7-15` emits only `Invalid request` for non-contract exceptions; contract errors pass through unchanged. |
| Raw schema errors | Rule-schema internals could reach outward errors at service/mock boundaries. | `controller_service.py:896-912` and `firewall_controller.py:75-88` map all schema/digest failures to bounded `Invalid request`. |
| Raw backend exceptions | Backend exception text could escape from dispatch. | `controller_service.py:1281-1282`, `:1304-1307` and `:1622-1623` map to `FirewallControllerBackendError("Backend operation failed")`. |
| Raw cached response errors | Error responses were persisted/replayed as returned by the backend. | `controller_service.py:1524`, `:1554` and `:1274` sanitize before persistence and on every replay path. |
| Storage misclassification | Raw DB text could surface or be confused with validation/uncertainty. | `error_sanitization.py:75-83`, `controller_service.py:1579-1587`, `:1801-1813` keep `BrokerDBError`/persistence classification and bound text. |
| Canonical binding | Reads/replays could rely on caller metadata or uncategorized store errors. | Ownership binding, replay identity snapshot, digest/resource checks and typed canonical error categories are enforced as listed in §2.2. |

## 4. Validation-order proof

The new sentinel suite uses counting store/backend wrappers. For invalid identifiers, aliases and malformed inputs it asserts:

- `inner_store.list_ownerships() == []`;
- `inner_store.get_lifecycle_history() == []`;
- `backend.calls == []`.

These assertions establish that rejection occurs before ownership lookup, mutation, lifecycle persistence, idempotency persistence and backend dispatch in the covered paths.

## 5. Compatibility preservation

- Public exception classes are retained: `FirewallControllerRequestError`, `FirewallControllerIdempotencyError`, `FirewallControllerAuthError`, `FirewallControllerPersistenceError`, `FirewallControllerBackendError`, `PermissionError` and `BrokerDBError`.
- Stable codes are retained (`REQUEST_INVALID`, `PERSISTENCE_FAILURE`, `INSTALL_FAILED`, `RECONCILIATION_PERSISTENCE_FAILURE`, idempotency conflict semantics).
- Legacy no-rules installs remain supported (`test_legacy_no_rules_install_still_supported`).
- Existing Stage 1B.6 canonical read-failure and reconciliation-persistence contracts remain asserted.
- Where injected internal `RuntimeError`s formerly escaped, they now map to the pre-existing public `FirewallControllerBackendError`; affected tests were aligned to assert the public contract, not weakened.

## 6. Changed files

Source:

- `broker/firewall_controller_service/error_sanitization.py` (new)
- `broker/firewall_controller_service/controller_service.py`
- `broker/firewall_controller_service/request_validator.py`
- `broker/app/firewall_controller.py`

Tests:

- `broker/tests/test_post_j20_stage_1b13_canonical_validation_sanitization.py` (new)
- `broker/tests/test_post_j20_stage_1b6_targeted_residual_gaps.py`
- `broker/tests/test_post_j20_stage_1b3_durable_crash_recovery.py`
- `broker/tests/test_firewall_controller_residual_risk_remediation.py`
- `broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py`

Documentation:

- this file and the three companion Stage 1B.13 reports;
- `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` (evidence reference only).

## 7. Residual limitations

This is a mock-boundary implementation and evidence package only. It does not prove universal host/protocol closure, kernel-authenticated peer identity, transport hardening, Docker/runtime isolation, privileged-helper capability confinement, host firewall state, live-backend contract conformity, DB migration/stress behavior, or formal acceptance. T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED; SR-10, SR-06 and I-09 remain pending authority decisions. No gate was closed and no risk was accepted.

## 8. Evidence

See `docs/POST_J20_STAGE_1B_13_ERROR_SANITIZATION_ASSESSMENT.md`, `docs/POST_J20_STAGE_1B_13_SECURITY_TEST_EVIDENCE.md` and `docs/POST_J20_STAGE_1B_13_FINAL_VERIFICATION_REPORT.md`.
