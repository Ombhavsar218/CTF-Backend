# Phase 2L.2G.3 — Privileged Helper Contract and Mock Integration (Mock-Only)

## Decision
**PASS** — Strict helper contract and mock integration validated within the local mock scope (typed enum operations, schema validation rejecting unknown fields/types/bounds, helper-side mock authorization fail-closed, idempotency/conflict handling, sanitized audit, deterministic failure/timeout/uncertain injection, structured errors, controller->helper boundary via narrow adapter, no shell/host-state changes). Real privileged helper process, UDS/SO_PEERCRED, capabilities, and host firewall operations remain unimplemented/unauthorized.  
**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

## 1. Architecture inspected
- `broker/firewall_controller_service/controller_service.py` — unprivileged controller logic; strict auth, request validation, authoritative SQLite ownership/lifecycle/idempotency/evidence/audit, intent-before-backend install flow, evidence-gated `ACTIVE`, fail-closed reconciliation, backend delegation via `FirewallBackendInterface`.
- `broker/firewall_controller_service/ownership_store.py` — authoritative persistence (no competing store added).
- `broker/firewall_controller_service/backend_interface.py` — backend operation interface (controller -> backend/helper boundary).
- `broker/firewall_controller_service/mock_backend.py` — updated to a narrow adapter routing through `MockHelperExecutor` while preserving legacy compatibility (`_ctrl` state/failure flags) for existing mock tests.
- Phase 2L.2G.1 transport/peer identity (`peer_identity.py`, `transport.py`, `mock_transport.py`) — mock transport injects transport-verified peer context; real SO_PEERCRED not implemented.
- Phase 2L.2G.2/2G.2.1/2G.2.2/2G.2.3 persistence/recovery validation evidence and reports.
- `docs/PHASE_2L_2F_4_PRIVILEGE_BOUNDARY_AND_CAPABILITY_ARCHITECTURE.md`, `docs/PHASE_2L_2F_6_CRITICAL_INTEGRATION_DESIGN_DECISIONS.md` — boundary/capability/recovery design inputs.

**Reuse:** existing authoritative persistence (`ControllerOwnershipStore`), controller authorization/lifecycle logic, and backend interface patterns. **No competing stores or lifecycle state machines introduced.**

## 2. Helper trust boundary
- **Unprivileged controller** performs transport peer auth (mock/strict in current scope), request validation, ownership/lifecycle/evidence/idempotency persistence, and decides when backend/helper side effects may occur.
- **Helper boundary (mocked)** is invoked only through the backend/helper interface adapter (`MockFirewallBackend` -> `MockHelperExecutor`). No alternate privileged execution path added.
- **Request JSON cannot establish identity** at the helper boundary. Controller->helper adapter strips transport/controller-internal context and forbidden auth-claim fields (`FORBIDDEN_AUTH_CLAIM_FIELDS` + `peer_uid/gid`) before executor validation/execution. Direct executor/contract APIs remain strict and reject forbidden auth/identity claims.
- Helper responses are structured; executor enforces bounded response validation. Uncertain/error outcomes do not bypass controller ownership/authorization/lifecycle gates.

## 3. Operation enum and schemas
Implemented in `broker/firewall_controller_service/helper_contract.py`.

| Enum | Backend method mapping | Notes |
|---|---|---|
| `HEALTH_CHECK` | `health_check` | Lighter required-field set |
| `INSTALL_POLICY` | `install_policy` | Typed/policy/ownership/digest/family checks |
| `INSPECT_POLICY` | `inspect_policy` | Read/inspect boundary |
| `VERIFY_POLICY` | `verify_policy` | Verification/evidence path (controller still gates `ACTIVE` on persisted evidence) |
| `REVOKE_POLICY` | `revoke_policy` | Revocation |
| `REMOVE_OWNED_POLICY` | `remove_stale_policy` | Minimum required owned-removal op |
| `RECONCILE_OWNED_POLICY` | `reconcile_pending_operations` | Conservative reconciliation boundary |

**Schema/validation (fail closed):** `schema_version` (`2L.2G.3`), `request_id`, `operation_id`, `idempotency_key` (bounded ID format), `policy_id`/`policy_version`/`compiled_rule_digest` (or canonical), ownership reference, address family/families, optional CIDR/protocol/port fields validated (`ipaddress`, approved protocols, bounded ports), bounded request/response JSON sizes, bounded `timeout_ms`, bounded compiled-rule entry counts. **Unknown fields rejected.** **Caller-supplied identity/authorization claims rejected** (`peer_uid/gid`, `caller_trusted`, `verified`, `trusted`, `auth_identity`, `x_identity`, `source_identity`, `controller_verified`, `authorized`, `is_admin`, etc.). Invalid types/values rejected. No arbitrary shell/executable/script/iptables/nft expression fields in schema.

## 4. Authorization model
Implemented in `broker/firewall_controller_service/helper_authorization.py`.

- `MockHelperPeerIdentity` / `MockHelperIdentityProvider` are **explicitly named mock** identity sources (**not real peer auth, not SO_PEERCRED**).
- `MockHelperAuthorizationProvider`: requires authenticated mock identity from provider/argument; **missing identity fails closed**; **empty UID/GID allowlists fail closed**; explicit per-operation allowlist (all `HelperOperation` values by default in mock when configured, configurable); UID/GID membership checked; **request JSON cannot establish identity**.
- `MockFirewallBackend` default adapter config uses an explicit mock identity/allowlist (`uid/gid 1000`) for backward-compatible mock wiring; direct executor/contract tests exercise strict fail-closed cases (missing identity, unauthorized identity, empty allowlists).

## 5. Capability analysis (documented only; no capabilities applied)
| Area | Analysis | Status |
|---|---|---|
| `CAP_NET_ADMIN` | Likely required for real nftables/iptables mutating operations on Linux; **not sufficient alone** as a complete security boundary (must combine with fixed enum ops, typed schema, peer auth, no shell, filesystem restrictions, systemd hardening, audit). | **CONDITIONAL** (exact set unvalidated on target host) |
| Read-only firewall inspection | May require `CAP_NET_ADMIN` or appropriate read APIs depending on backend/kernel/tooling; prefer least privilege and consider separate read-only/inspect helper if justified. | **CONDITIONAL** |
| Separate install/inspect helpers | Justified if it materially reduces capability exposure and operational complexity remains acceptable. | **CONDITIONAL** |
| Minimal capability set / dedicated helper executable | Prefer dedicated helper binary, bounded capability set, no shell, fixed operation enum, strict validation, idempotency/audit/timeouts. | **CONDITIONAL** |

**No sudo/capability/systemd/permission changes made.** Exact capability set remains **CONDITIONAL** until validated on the intended Linux host.

## 6. Mock executor implementation
Implemented in `broker/firewall_controller_service/mock_helper_executor.py`.

- Accepts only approved `HelperOperation` enum / mapped methods; rejects unknown operations.
- Uses typed request validation (`helper_contract`) and mock helper authorization.
- **Deterministic injections (mock/test-only):** `inject_failures`, `inject_timeout`, `inject_uncertain`.
- **Idempotency:** in-memory executor idempotency keyed by operation + idempotency key + policy/version/digest; detects conflicting payloads; replay returns prior response. **No competing durable store** (authoritative durable idempotency remains in `ControllerOwnershipStore` / controller service).
- **Sanitized audit events** (`helper_*` events; no secrets/tokens logged).
- **Structured errors/responses**, bounded response validation, operation ID correlation preserved from request.
- **No shell commands, no host firewall/system changes.** Mock state delegated to existing `MockFirewallController` for behavioral compatibility.

## 7. Persistence and idempotency integration
- Controller `operation_id`/`idempotency_key` are carried/correlated in helper requests/responses (executor preserves request `operation_id`).
- **Durable idempotency remains in the existing authoritative store** (`controller_idempotency` via controller service). Mock executor idempotency is boundary-local and non-durable (mock convenience) — **not a competing authoritative registry**.
- Duplicate helper requests do not duplicate mock operations (executor replay + controller idempotency). Conflicting payloads rejected (`FirewallControllerIdempotencyError` / contract/idempotency checks).
- Uncertain helper outcomes return structured error/uncertain responses; controller/lifecycle integration tests confirm **no promotion to `ACTIVE`** from uncertain outcomes.
- **Evidence-gated `ACTIVE` promotion preserved**: install alone does not activate; verify with persisted evidence path can reach `ACTIVE` (controller service behavior unchanged).
- Helper errors do not bypass controller ownership/authorization checks (controller checks run in controller service; adapter sanitizes claims but does not grant authority).
- Recovery remains conservative/fail-closed as previously validated.
- **No atomicity claimed** between SQLite and helper execution.

## 8. Tests and actual results
Created: `broker/tests/test_firewall_controller_helper_contract.py` (**24 tests**).  
Minimal isolation fixes (test intent unchanged) to avoid shared default DB pollution during full-suite runs: `broker/tests/test_firewall_controller_active_integration.py`, `broker/tests/test_firewall_controller_security_remediation.py`.

Focused coverage includes: valid enum operations, unknown operation rejection, unknown schema fields, invalid request types, missing peer identity, unauthorized mock identity, empty allowlist fail-closed, caller-supplied identity rejection, invalid policy/address/protocol/port/CIDR/family values, request size limit, timeout behavior, idempotent replay, conflicting idempotency keys, partial execution failure, sanitized audit record creation, uncertain outcome not promoting `ACTIVE` (controller integration), evidence-gated `ACTIVE` promotion through helper-backed adapter, mock executor no shell/host-state attributes.

**Exact commands/results (`E:\Flag-hunt\ctf-platform-be`, venv):**
1. `pytest broker/tests/test_firewall_controller_helper_contract.py -v` → **24 passed, 1 warning** (`1.05s`)
2. `pytest broker/tests/test_firewall_controller_persistent_recovery_integration.py broker/tests/test_firewall_controller_persistence_failure_closure.py broker/tests/test_firewall_controller_service_skeleton.py -v` → **49 passed, 1 warning** (`21.18s`)
3. `pytest broker/tests -q` (complete Broker suite) → **236 passed, 1 warning in 65.51s (0:01:05)**
4. `manage.py test instances.tests.test_manager_client` → **33 tests OK**; system check 0 issues
5. `manage.py check` → **System check identified no issues (0 silenced).**

## 9. Security limitations
- Mock helper authorization/identity provider only; **no real UDS/SO_PEERCRED/peer authentication**.
- No real privileged helper binary/process; mock executor performs **no host firewall changes**.
- Adapter strips forbidden auth-claim fields at controller->helper boundary for compatibility/safety; direct API remains strict. This does not make request JSON an identity source.
- Controller service still carries `peer_uid/gid` in some internal request flows; strict controller auth and adapter sanitization mitigate, but full transport/privilege boundary requires host-lab implementation.
- Exact capabilities, systemd hardening, socket permissions, and Linux-only enforcement remain **CONDITIONAL**.
- SQLite + helper execution not atomic.

## 10. Next implementation prerequisites
1. Approve and implement real transport boundary (UDS + `SO_PEERCRED`/kernel-authenticated peer identity on supported Linux), fail-closed on unsupported platforms.
2. Define approved helper executable, fixed command interface (no shell), strict peer/operation auth, timeouts, and audit redaction.
3. Validate minimal capability set / helper split (install vs inspect) on intended host; apply via systemd/AppArmor/SELinux controls as appropriate (separate approved phase).
4. Implement real helper backend with read-back evidence, idempotency correlation, and conservative recovery; keep controller lifecycle/evidence gates authoritative.
5. Host-lab integration tests (Docker/nftables/iptables ordering, IPv4/IPv6, conntrack, revocation semantics, process supervision/crash modes) before any live firewall enablement.
6. Obtain explicit authorization before any live firewall integration.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
