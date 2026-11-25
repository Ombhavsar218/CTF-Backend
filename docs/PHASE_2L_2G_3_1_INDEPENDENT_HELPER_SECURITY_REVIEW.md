# Phase 2L.2G.3.1 — Independent Privileged Helper Security Review (Read-Only)

## Decision
**CONDITIONAL** — The Phase 2L.2G.3 helper contract and mock integration establish a useful typed boundary (fixed enum, strict field/type/bound validation, explicit mock authorization primitives, idempotency/conflict handling, audit, no-shell mock execution, controller integration without an alternate bypass path in tested scope). However, important security/design gaps remain before real transport or host-lab implementation: authenticated peer identity is not independently propagated per request across the controller→helper boundary in current mock wiring (adapter relies on executor-configured mock identity/provider, with a compatibility default `uid/gid 1000` allowlist), schema/version/ownership semantics need hardening for production, real UDS/SO_PEERCRED/process isolation/capability enforcement are unimplemented, and mock defaults must be prevented from becoming implicit production trust.  
**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

## 1. Executive summary
- **Reviewed (read-only):** `helper_contract.py`, `helper_authorization.py`, `mock_helper_executor.py`, `mock_backend.py`, `controller_service.py`, `ownership_store.py`, `test_firewall_controller_helper_contract.py`, 2G.3/2F.4/2F.6 docs. Existing controller auth/lifecycle/persistence/recovery context considered from prior phases and inspected modules.
- **Strengths:** fixed `HelperOperation` enum; unknown operation/unknown field rejection; caller-supplied auth/identity claim fields rejected by contract; bounded request/response/timeout/compiled-entry limits; basic CIDR/protocol/port validation; mock helper authorization is fail-closed for missing identity and empty allowlists; executor performs authorization before execution and preserves operation ID correlation; idempotency replay/conflict detection present; uncertain/failure injection supports fail-closed controller integration tests; evidence-gated `ACTIVE` remains in controller service.
- **Primary concerns:** mock compatibility adapter (`MockFirewallBackend`) configures a static mock identity/allowlist (`1000/1000`) by default and never passes a per-request authenticated identity to `execute_method`; adapter strips forbidden identity-claim fields (necessary for compatibility/safety) but the real helper must receive identity only from an authenticated transport channel, not from request JSON or implicit defaults. Schema accepts `schema_version` defaulting behavior and permissive ownership fallback; `compiled` payload is only shallowly bounded. Real helper process isolation, fixed binary, capability set, UDS/SO_PEERCRED, and host controls are design-only.

## 2. Architecture and trust-boundary findings
- **Controller/helper separation (conceptual):** controller service owns transport-facing auth, validation, authoritative ownership/lifecycle/idempotency/evidence, and delegates backend side effects through `FirewallBackendInterface`. `MockFirewallBackend` routes to `MockHelperExecutor` (no alternate bypass path added in inspected controller delegation path).
- **Adapter sanitization:** `MockFirewallBackend._prep` strips `FORBIDDEN_AUTH_CLAIM_FIELDS | {peer_uid, peer_gid}` before calling executor. This prevents request JSON from carrying those fields to the helper mock; it is compatible with controller-internal flows but means the adapter is responsible for boundary hygiene. Direct `validate_helper_request`/`MockHelperExecutor` calls remain strict.
- **No real process isolation:** mock executor runs in-process and delegates to `MockFirewallController` state. **Mock does not prove real process isolation, privilege separation, IPC integrity, or crash containment.**
- **Test compatibility exposure:** `MockFirewallBackend`/executor expose `_ctrl` and injection surfaces for existing tests. Acceptable in mock/test modules; production helper interfaces must not expose mutable state/injection controls.

## 3. Identity and authorization review
- **Distinct identities:** design distinguishes controller identity and helper/executor identity fields; authorization providers are separate types. In mock scope they share process context.
- **Request JSON cannot establish identity (contract level):** `FORBIDDEN_AUTH_CLAIM_FIELDS` are rejected first in `validate_helper_request` with `UNAUTHORIZED_CLAIM`. `MockHelperAuthorizationProvider.authorize` does not read identity from request JSON.
- **Mock identity not production identity (intent stated, enforcement gap):** `MockHelperPeerIdentity`/`MockHelperIdentityProvider` are explicitly named mock and documented as not SO_PEERCRED. **However**, `MockFirewallBackend` defaults to `MockHelperPeerIdentity(uid=1000,gid=1000,source='mock-controller-compat')` with allowlists `{1000}` when unconfigured — an implicit trusted mock default for compatibility. `MockHelperExecutor` defaults to empty allowlists when no auth/identity is provided (fail-closed), which is good, but the common backend adapter path uses the permissive mock default.
- **Missing identity / empty allowlists:** enforced fail-closed by `MockHelperAuthorizationProvider` (tested). **Conditional gap:** any production wiring must ensure no code path can instantiate permissive mock providers/identities outside explicit test configuration.
- **Authorization before execution:** executor calls `self.auth.authorize(...)` before `validate_helper_request` and before delegated execution/injection side effects. This satisfies “authorization occurs before executor operations” at the executor API; malformed-but-authorized requests fail validation after auth (acceptable). Ordering should be documented; consider validating structural bounds before expensive handling in real IPC.
- **Per-request authenticated identity propagation:** `MockFirewallBackend` calls `execute_method(..., self._prep(req))` **without** an `identity` argument. Authorization therefore depends on executor-configured `identity_provider`/state. The current mock transport authenticates peers at controller ingress, but that authenticated identity is **not independently passed** to the helper boundary per request in the adapter wiring. For a real helper, identity must come from authenticated IPC (e.g., SO_PEERCRED on UDS) and be bound to the specific request/connection; the controller must not be able to launder arbitrary requests as “authorized” except by being an explicitly authorized peer.
- **No alternate execution path:** controller service continues to use backend interface; no direct host-firewall bypass observed. Future real-helper integration must preserve this invariant.

## 4. Schema and operation review
- **Fixed enum / unknown op rejection:** `HelperOperation` fixed; `execute_method` returns structured `OPERATION_NOT_ALLOWED` for unknown methods. Good.
- **Unknown field rejection:** strict allowlist (`COMMON_ALLOWED`) after forbidden-claim check. Good, but `COMMON_ALLOWED` is a broad superset for compatibility (includes `compiled`, CIDR/protocol/port/family fields) — real helper schemas should be operation-specific and minimal.
- **Schema version enforcement:** `schema_version` defaults to `SCHEMA_VERSION` if absent and is only length-checked; it is **not required to equal** the supported version. **Gap:** production should require explicit supported schema version (or strict negotiation) and reject unsupported versions fail-closed.
- **Size/time bounds:** request/response JSON bounded; `timeout_ms` bounded; compiled payload half-bound and shallow rule-count check. `timeout_ms` is validated but **not enforced** by mock executor execution path (only injection flag). Real helper must enforce wall-clock/operation timeouts.
- **IP/CIDR/protocol/port:** uses `ipaddress.ip_network(strict=False)` with family hints; protocol allowlist and port ranges bounded. Adequate baseline; real backend must still treat compiled/policy data as data, never executable instructions.
- **Ownership/policy references/digest:** required for non-health ops; digest regex allows 16–128 hex chars (lenient vs 64-char SHA-256). Ownership reference accepts fallback to `instance_id` or `policy_id` if explicit ownership fields absent — **permissive** and could weaken binding; helper/controller should prefer authoritative ownership record references from controller-owned state.
- **Parameter injection/operation confusion:** no shell/command/path fields; enum dispatch is explicit. Residual risk: `compiled` is opaque structured data (bounded but not semantically validated by contract) — safe only if real helper treats it as data with a strict compiler/interpreter boundary and never evaluates expressions. Operation-specific schemas should further constrain fields (e.g., health vs install).

## 5. Privilege-boundary findings
- **Fixed executable/deployment assumptions:** not implemented (mock). Required for production: fixed binary path, dedicated uid/gid, no user-writable executable/config path, controlled startup.
- **No shell/arbitrary command/script/firewall expression:** mock executor has no shell/subprocess execution path (structural test added). Contract has no command fields. Real helper must preserve this invariant.
- **No caller-selected paths / unrestricted filesystem / arbitrary capability requests:** not representable in current schema; real implementation must enforce.
- **Malformed/oversized requests:** bounded and rejected in tested cases. Real IPC framing must also enforce max message size before full parse/allocation.
- **Compromise impact:** real helper compromise would have helper privileges (potentially `CAP_NET_ADMIN`/firewall mutation scope) — mitigated only by process separation, minimal caps, strict op enum, idempotency/ownership checks, and audit. Mock cannot assess this.
- **Replay/duplicate/conflict:** in-memory executor idempotency + controller durable idempotency tested. Lost-response/timeout recovery needs real transport semantics and reconciliation; controller already treats uncertain outcomes conservatively.

## 6. Persistence and recovery findings
- **Operation ID correlation:** executor preserves caller `operation_id` and includes IDs in responses/audit. Good.
- **Durable idempotency/ownership/evidence:** authoritative in `ControllerOwnershipStore`/controller service (no competing store). Mock executor idempotency is boundary-local/in-memory only — acceptable for mock, insufficient alone for real helper durability across restarts.
- **Uncertain outcomes / ACTIVE promotion:** controller integration test shows uncertain helper outcome does not promote to `ACTIVE`; controller service retains evidence-gated `ACTIVE` behavior. Prior 2G.2.x phases validated conservative recovery. **No path identified in inspected mock integration that promotes uncertain operations to `ACTIVE`**, but real helper lost-ack/partial-apply scenarios require host-lab and read-back evidence validation.
- **SQLite/helper side-effect consistency:** no atomicity; fail-closed reconciliation required (already designed/partially validated). Real helper must provide deterministic operation IDs, idempotency, and inspectable evidence.

## 7. Capability and deployment gaps
Unresolved (must not be finalized without target-host validation):
- Exact `CAP_NET_ADMIN` necessity/scope for nftables/iptables/netlink operations; whether read-only inspection can use lesser privileges or separate helper.
- Separate mutating vs inspection helpers/binaries.
- Dedicated service accounts, group model, and ownership of DB/socket/helper state.
- Fixed helper binary path, package/deployment integrity, and startup/shutdown supervision.
- UDS path, directory permissions, socket mode (`0660` or stricter as appropriate), `SO_PEERCRED`/equivalent peer auth, and unsupported-platform fail-closed behavior.
- `NoNewPrivileges`, `CapabilityBoundingSet`, `ProtectSystem`, `PrivateTmp`, syscall filtering, and related systemd hardening.
- Docker/nftables/iptables ordering, IPv4/IPv6 symmetry, conntrack revocation semantics.

## 8. Findings by severity

| Severity | ID | Finding |
|---|---|---|
| **Critical** | C1 | **Real authenticated identity not independently propagated to helper boundary per request.** Adapter invokes executor without per-request authenticated transport identity; mock wiring relies on executor/provider-configured identity (compat default `uid/gid 1000`). A real helper must bind authorization to kernel-authenticated IPC peer identity (UDS+`SO_PEERCRED` or approved equivalent) and fail closed. |
| **High** | H1 | **Implicit mock trusted defaults in adapter.** `MockFirewallBackend` default mock identity/allowlists (`1000/1000`) can mask misconfiguration and must never be reachable in production paths; production build/config must reject mock providers/compat defaults. |
| **High** | H2 | **Schema version not strictly required/matched.** Missing `schema_version` is accepted/defaulted; unsupported versions not explicitly rejected. Real helper must enforce explicit supported version negotiation/fail-closed. |
| **High** | H3 | **Real helper process/IPC/capability boundary unimplemented.** No fixed binary, no UDS/SO_PEERCRED, no privilege drop/capability bounding, no host firewall backend. Mock integration does not validate these controls. |
| **Medium** | M1 | **Ownership reference validation is permissive.** Fallback to `instance_id`/`policy_id` may weaken authoritative ownership binding; require explicit controller-authoritative ownership reference where applicable. |
| **Medium** | M2 | **`compiled` payload is opaque and only shallowly bounded.** Necessary for current design, but real helper must treat as data only with strict semantic validation/canonicalization and never execute expressions/commands. |
| **Medium** | M3 | **Digest format lenient (16–128 hex).** Accepts non-canonical lengths; tighten to expected digest format/length for approved algorithm(s). |
| **Medium** | M4 | **`timeout_ms` not enforced by mock executor.** Contract validates bounds; real helper/transport must enforce deadlines and return structured timeout/uncertain outcomes. |
| **Low** | L1 | **Auth-before-validate ordering.** Authorization runs before schema validation in executor. Acceptable with bounds, but real IPC should apply cheap framing/size/version checks early to reduce abuse surface. |
| **Low** | L2 | **Test compatibility internals exposed.** `_ctrl`, injection flags, and mutable executor state are accessible on mock classes; keep isolated from production helper interfaces. |
| **Informational** | I1 | **Adapter strips forbidden fields** (including `peer_uid/gid`) before helper validation; direct contract/executor APIs remain strict. Good compatibility tradeoff if documented and if real identity is sourced from transport. |
| **Informational** | I2 | **No alternate backend bypass path observed** in controller service delegation. Preserve invariant in future work. |
| **Informational** | I3 | **Controller durable idempotency remains authoritative**; executor idempotency is in-memory/mock-local only. |

## 9. Required remediation and validation
1. **Real transport identity (C1):** Implement UDS + kernel-authenticated peer identity (`SO_PEERCRED` on supported Linux), fail closed on unsupported platforms. Pass authenticated identity per request/connection to helper authorization; do not accept request JSON identity.
2. **Eliminate implicit mock trust (H1):** Guard mock identity/provider/compat defaults behind explicit test-only configuration; production composition must fail closed if mock auth helpers are selected without explicit non-production approval markers.
3. **Strict schema versioning (H2):** Require and validate supported `schema_version`; reject missing/unknown versions.
4. **Harden schema semantics (M1–M3):** Make operation-specific schemas minimal; require authoritative ownership binding; tighten digest format; validate/canonicalize compiled policy data in the real compiler/helper boundary.
5. **Enforce timeouts/cancellation (M4):** Apply transport and helper execution deadlines; map timeout/lost response to uncertain/non-`ACTIVE` outcomes.
6. **Real helper deployment controls (H3, Section 7):** Fixed binary, dedicated account, minimal capabilities, systemd hardening, socket permissions, audit, no shell, read-back evidence.
7. **Validation before live consideration:** host-lab tests for UDS/SO_PEERCRED, capability behavior, nftables/iptables/Docker ordering, IPv4/IPv6, conntrack, idempotency/reconciliation under real process crashes and lost responses.

## 10. Implementation readiness decision
**CONDITIONAL** — The helper architecture and mock contract are sufficiently developed to inform a **separately approved real-transport/real-helper implementation proposal**, provided C1/H1/H2/H3 and the host/capability controls are explicitly scoped, mock defaults are isolated from production, and no live firewall integration is attempted. This is **not** approval for real transport activation, privileged helper deployment, capability grants, or firewall changes.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
