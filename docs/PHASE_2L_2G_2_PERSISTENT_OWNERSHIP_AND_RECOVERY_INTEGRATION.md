# Phase 2L.2G.2 — Persistent Ownership and Recovery Integration (Mock-Only)

## Decision
**CONDITIONAL** — Persistent ownership, lifecycle, idempotency and mock recovery are validated within the tested scope for the implemented scenarios, with important recovery/operational gaps remaining (no real crash/process termination validation, no real backend/firewall reconciliation, limited recovery automation semantics).  
**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

## 1. Existing architecture inspected
Inspected and integrated with existing components (no competing stores/state machines/idempotency registries introduced):
- `broker/firewall_controller_service/controller_service.py`
- `broker/firewall_controller_service/ownership_store.py`
- `broker/firewall_controller_service/ownership.py` (abstraction present; authoritative persistence remains in `ControllerOwnershipStore`)
- `broker/firewall_controller_service/audit.py`
- `broker/firewall_controller_service/backend_interface.py`
- `broker/firewall_controller_service/mock_backend.py`
- `broker/app/firewall_controller.py` (mock backend implementation)
- Phase 2L.2G.1 transport modules/tests:
  - `broker/firewall_controller_service/transport.py`
  - `broker/firewall_controller_service/mock_transport.py`
  - `broker/firewall_controller_service/peer_identity.py`
  - `broker/tests/test_firewall_controller_transport_mock.py`
- Relevant lifecycle/idempotency/concurrency/active enforcement tests under `broker/tests/`

## 2. Authoritative persistence stores
Authoritative persistent state (SQLite via `ControllerOwnershipStore`, WAL mode) in `broker/data/firewall_controller.db` by default (overridable via `FIREWALL_CONTROLLER_DB_PATH`; tests use isolated temp DBs):
- `controller_ownership`: ownership, policy/version, instance/network, canonical digest, lifecycle state, `lifecycle_version` (CAS), reconciliation metadata.
- `controller_lifecycle_history`: append-only lifecycle transitions with operation/request context.
- `controller_idempotency`: durable idempotency records `(idempotency_key, operation_type)` with request digest, status (`PENDING`/`COMPLETED`), response JSON, resource binding metadata.
- `controller_evidence`: persisted verification evidence bound to ownership/policy/instance/network/digest/controller/request context.
- `controller_audit`: audit events.

No new competing ownership/lifecycle/idempotency registries were added.

## 3. Files created and modified
### Created
- `broker/tests/test_firewall_controller_persistent_recovery_integration.py`
- `docs/PHASE_2L_2G_2_PERSISTENT_OWNERSHIP_AND_RECOVERY_INTEGRATION.md`

### Modified
- `broker/firewall_controller_service/ownership_store.py`
  - Added query/helpers for recovery/integration: `get_evidence_by_ownership`, `get_evidence_by_policy`, `get_pending_idempotency`, `list_ownerships`, `update_reconciliation_status`.
  - Normalized row-to-dict returns for consistency with existing usage/tests.
- `broker/firewall_controller_service/controller_service.py`
  - Persisted install intent before backend side effects for fresh installs (creates ownership in `REQUESTED`, records intent, then calls backend; transitions to `INSTALLING` on backend success; fails closed on backend failure where applicable).
  - Improved lifecycle/CAS usage in install/revoke paths and row/dict handling.
  - Added durable concurrent idempotency wait-for-completion behavior for identical pending requests (prevents unsafe re-execution while allowing idempotent completion reuse within tested scope).
  - Implemented mock-only `reconcile_pending_operations` that inspects persisted ownership/idempotency/evidence and **actual mock-backend state** (`backend.inspect_policy`) before deciding. Fails closed on auth/validation, backend read-back uncertainty, missing ownership, and never promotes to `ACTIVE` without valid persisted evidence. Never auto-adopts unknown backend rules.
- `broker/tests/test_firewall_controller_deterministic_concurrency.py`
  - Adjusted `test_concurrent_identical_install` to use truly identical payloads (same policy/version/digest context) with the same idempotency key, aligning with secure idempotency semantics.
- `broker/tests/test_firewall_controller_cross_process_concurrency.py`
  - Adjusted `test_cross_process_identical` to use truly identical payloads with the same idempotency key.
- `broker/tests/test_firewall_controller_service_skeleton.py`
  - Updated for strict auth/peer identity and isolated temp DB usage (test compatibility with enforced security model).

## 4. Ownership integration
Validated (mock-only, isolated temp DBs):
- Ownership records survive controller-service recreation (same authoritative SQLite store).
- Ownership remains independent of firewall labels/comments and is tracked in controller persistence.
- Ownership cannot be silently reassigned: conflicting instance/network/digest context for existing policy/version is rejected (fail closed).
- Unauthorized inspect/revoke/removal paths require ownership/authz and fail closed when missing/unauthorized.
- Missing/conflicting/corrupt ownership/evidence context fails closed (e.g., verification with mismatched digest rejected; no ACTIVE promotion without evidence).

## 5. Lifecycle and CAS behavior
- Lifecycle transitions are enforced via the existing state machine with CAS/version checks (`installation_state` + `lifecycle_version`) in `ControllerOwnershipStore.update_ownership_state`.
- Intent is persisted before backend side effects for fresh installs (`REQUESTED` intent recorded before backend call). Existing ownership revalidation transitions are persisted before backend execution in the install path.
- `ACTIVE` requires the verify flow to persist backend-derived evidence and complete lifecycle promotion (`VERIFYING` → `VERIFIED` → `ACTIVE`) under the enforced flow. Recovery does not promote uncertain operations to `ACTIVE` without valid persisted evidence.
- Invalid transitions and stale CAS versions are rejected.
- **Not atomic across SQLite and backend side effects** (explicitly not claimed). Uncertain states are preserved/handled fail-closed and reconciled based on persisted + backend read-back state.

## 6. Idempotency behavior
- Durable SQLite-backed idempotency is authoritative (`(idempotency_key, operation_type)`, request digest binding).
- Identical requests with same key/context return persisted completed results (including across service recreation).
- Conflicting payloads using the same key are rejected (fail closed), including across service recreation.
- Concurrent identical requests do not create duplicate backend operations in tested scope; pending identical requests wait briefly for completion and reuse the persisted completed response (no unsafe blind replay).
- Failed/uncertain operations are not auto-replayed unsafely; reconciliation reports pending/uncertain states and retains fail-closed outcomes.
- Idempotency remains bound to request digest/resource context; transport injects authenticated peer identity and cannot override it.

## 7. Crash-recovery matrix and actual test evidence
Focused mock-backend recovery tests added in `test_firewall_controller_persistent_recovery_integration.py`. Scenarios use isolated temp DBs and simulate crashes/uncertainty by manipulating persisted state and/or mock backend state, then invoking reconciliation (which inspects mock-backend state).

| Scenario | Simulation (mock) | Expected safe behavior | Test | Result |
|---|---|---|---|---|
| 1. Crash before backend execution | `REQUESTED` intent + `PENDING` idempotency persisted; backend has no install state | No ACTIVE promotion; reconcile fails closed/marks safe non-active outcome; no auto-retry | `test_recovery_crash_before_backend_execution` | PASS |
| 2. Backend completed but response lost | Backend shows installed; ownership persisted as `REQUESTED`/uncertain | Inspect backend; do not promote to ACTIVE without verification evidence; mark needs verification/uncertain-safe | `test_recovery_backend_completed_but_response_lost` | PASS |
| 3. Backend completed but evidence not persisted | Backend indicates verified state; no persisted evidence in controller DB | Do not promote to ACTIVE without persisted evidence; fail closed/retain uncertainty | `test_recovery_backend_completed_but_evidence_not_persisted` | PASS |
| 4. Evidence persisted but lifecycle promotion incomplete | Persisted evidence exists; ownership stuck in `VERIFIED` | Reconcile may promote to `ACTIVE` only when state/evidence allow safe transition; otherwise remain safe | `test_recovery_evidence_persisted_but_promotion_incomplete` | PASS |
| 5. Ownership missing or inconsistent | Backend has state but no ownership record | Never auto-adopt unknown backend rules; fail closed | `test_recovery_ownership_missing_or_inconsistent` | PASS |
| 6. Duplicate recovery request | Reconcile invoked twice for same target | Idempotent/safe; no unsafe state promotion | `test_recovery_duplicate_recovery_request` | PASS |
| 7. Backend read-back unavailable | Backend inspect/readback path unavailable/errored | Retain uncertain state, fail closed, do not guess | `test_recovery_backend_readback_unavailable` | PASS |
| 8. Partial revoke or cleanup | Ownership in `REVOKING` while backend still present (partial) | Do not claim `REVOKED`; retain uncertain/cleanup-safe state; no unsafe auto-adoption | `test_recovery_partial_revoke_or_cleanup` | PASS |

Additional validated cases: persistence across service recreation (ownership/lifecycle/idempotency), CAS rejection, invalid transitions, no ACTIVE without evidence, idempotency conflict across recreation, transport auth/ownership enforcement using authoritative persistence.

## 8. Transport integration
Validated with `MockControllerTransport` (Phase 2L.2G.1 boundary retained, mock-only):
- Uses authoritative `FirewallControllerService`/`ControllerOwnershipStore` persistence.
- Injects authenticated `PeerIdentity` and **overwrites** caller-supplied peer fields; rejects missing identity.
- Preserves strict authorization and ownership checks; cannot bypass lifecycle validation or evidence requirements.
- Propagates controller/service responses and errors; correlation/request context remains in request/response flow as implemented.
- Fails closed on auth/ownership violations. No real socket transport added.

## 9. Exact test commands and results
Executed from `E:\Flag-hunt\ctf-platform-be` using the project venv:

1. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_persistent_recovery_integration.py -v`  
   **Result:** `21 passed, 1 warning in 6.69s` (exit code 1 due to PowerShell stderr/warning handling in captured output; pytest summary indicates pass)

2. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe -m pytest broker/tests -v`  
   **Result:** `176 passed, 1 warning in 50.32s`

3. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client`  
   **Result:** `Ran 33 tests ... OK` (`Found 33 test(s). System check identified no issues (0 silenced).`)

4. `E:\Flag-hunt\ctf-platform-be\venv\Scripts\python.exe manage.py check`  
   **Result:** `System check identified no issues (0 silenced).`

## 10. Remaining limitations and next prerequisites
- **Mock-only scope only.** Recovery/reconciliation is validated against mock backend behavior and simulated crash states, not real firewall/Docker/OS semantics.
- **No real process-crash termination validation** (Windows environment limitations noted previously); no full independent cross-process crash-recovery proof beyond existing constrained tests.
- Reconciliation logic is intentionally conservative/fail-closed and may leave manual reconciliation for complex/ambiguous states; it does not implement all production-grade compensating actions.
- SQLite + backend operations are **not atomic**; uncertain windows remain by design and require careful operational handling.
- No real UDS/SO_PEERCRED, no privileged helper, no capability/permission changes, no Docker/firewall/nftables/iptables/UFW/routing/NAT/network/systemd/cloud changes, no live runtime provisioning.
- **Next prerequisites (before any live firewall integration consideration):** host-lab validation of UDS/SO_PEERCRED transport, privilege boundary/helper model, real backend read-back semantics (Docker/nftables/IPv4/IPv6), conntrack/revocation behavior, and full crash-recovery under real process termination/failure modes.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**