# Phase 2L.2G.3.2 — Helper Identity Propagation and Contract Hardening

## Decision
**PASS — mock-only remediation.**

The C1/H1/H2 findings and the in-scope medium findings (M1–M4) from
`docs/PHASE_2L_2G_3_1_INDEPENDENT_HELPER_SECURITY_REVIEW.md` are remediated in the
local mock-only helper boundary and covered by focused tests. No real transport,
privileged helper process, capability change, or firewall mutation was implemented or
activated.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

Overall helper/live readiness remains **CONDITIONAL**: H3 (real helper process/IPC/
capability boundary) and the Section 7 host/deployment controls are unresolved by
design and must be addressed in a separately approved real-transport/real-helper
proposal validated on the intended Linux host.

## 1. Original review findings addressed

| ID | Finding | 2L.2G.3.2 disposition |
|---|---|---|
| C1 | Authenticated identity was not independently propagated per request; adapter relied on executor/provider-configured identity and a `uid/gid 1000` compatibility default. | **Remediated in mock scope.** Adapter obtains identity per request from an explicitly injected provider and passes it separately to the executor. No request JSON path establishes identity. Real kernel-authenticated peer identity (UDS/SO_PEERCRED or approved equivalent) remains unresolved and unimplemented. |
| H1 | Implicit trusted mock defaults (`1000/1000`) in the adapter. | **Remediated.** `MockFirewallBackend`/`MockHelperExecutor` no longer create a mock identity or permissive allowlist. Missing provider/allowlists fail closed. Tests opt in explicitly via `broker/tests/_helper_identity.py`. |
| H2 | `schema_version` optional/defaulted and not exact-matched. | **Remediated.** `schema_version` is mandatory, typed, non-empty, and must exactly equal `SCHEMA_VERSION`; missing/null/empty/wrong-type/unsupported/alias forms are rejected. |
| H3 | Real helper process/IPC/capability boundary unimplemented. | **Unresolved by design (out of mock scope).** Documented as remaining real-transport/host-lab work. Not simulated as proof. |
| M1 | Permissive ownership-reference fallback to `instance_id`/`policy_id`. | **Remediated in mock scope.** Contract requires an explicit `ownership_reference`/`ownership_record_id`; fallback removed. Controller injects the persisted `ownership_record_id` from broker-owned state and refuses helper operations without it. Caller-supplied references are overwritten. |
| M2 | `compiled` payload opaque/shallowly bounded. | **Hardened in mock scope.** Strict data-only shape: allowed key set, bounded depth/size, unsupported value types rejected, and executable/expression-like tokens (`;`, backticks, `$(`, pipes, redirection, newlines, shell/binary/tool invocation markers) rejected. Real compiler/helper must still treat policy as data and enforce its own semantic/canonicalization boundary. |
| M3 | Digest format lenient (16–128 hex). | **Remediated.** Exact 64-character hexadecimal (SHA-256) format required for non-health operations. |
| M4 | `timeout_ms` validated but not enforced by the mock executor. | **Explicitly scoped.** Contract validates the declared bound; wall-clock enforcement is declared as a future transport/process-layer responsibility (`TIMEOUT_ENFORCEMENT_LAYER`). An injected timeout is returned as a structured non-success result and never as success. |
| L1 | Authorization before schema validation. | **Documented residual (low).** Ordering retained; real IPC should perform cheap framing/size/version checks before expensive handling. |
| L2 | Mock/test compatibility internals exposed. | **Documented residual (low).** `_ctrl`/injection surfaces remain mock/test-only and are not part of a production helper interface. |

## 2. Changes made

### 2.1 Helper contract — `broker/firewall_controller_service/helper_contract.py`
- Removed implicit schema defaults. `schema_version` is required and must exactly match
  `SCHEMA_VERSION`; unsupported values return `UNSUPPORTED_SCHEMA_VERSION`.
- Added operation-conflict rejection (`OPERATION_MISMATCH`) when a supplied `operation`
  field disagrees with the dispatched operation.
- Tightened digest validation to exactly 64 hexadecimal characters (`_DIGEST_RE`).
- Removed permissive ownership fallback; non-health operations require an explicit
  `ownership_reference` or `ownership_record_id` in valid identifier format.
- Added strict data-only compiled-policy validation:
  - allowed key set `COMPILED_ALLOWED_KEYS`,
  - bounded nesting depth/string length,
  - supported value types only,
  - rejection of executable/expression-like content.
- Response validation now requires the exact schema version.
- Added `TIMEOUT_ENFORCEMENT_LAYER` to explicitly document that deadline enforcement
  belongs to the future transport/process layer.

### 2.2 Helper authorization — `broker/firewall_controller_service/helper_authorization.py`
- Authorization is strictly per-request: the caller must supply the already-authenticated
  identity for that operation. There is no provider fallback inside the authorizer.
- Missing/invalid identity, empty UID/GID allowlists, unlisted UID/GID, or disallowed
  operation all fail closed with `FirewallControllerAuthError`.
- `MockHelperPeerIdentity`/`MockHelperIdentityProvider` remain explicitly mock-only and are
  documented as NOT kernel-authenticated peer identity.

### 2.3 Mock executor — `broker/firewall_controller_service/mock_helper_executor.py`
- Removed the constructor `identity` argument and implicit identity/allowlist defaults.
- Every `execute`/`execute_method` call routes through the same authorization provider
  with the identity supplied for that specific request.
- Authorization remains before validation and before any delegated mock execution.
- No shell/subprocess/host-state execution path was added.

### 2.4 Adapter — `broker/firewall_controller_service/mock_backend.py`
- `MockFirewallBackend(executor=None, identity_provider=None, helper_auth=None)`:
  - obtains identity from the injected provider **per request** via `get_identity()`,
  - provider absence or provider exception yields `None` and therefore fail-closed denial,
  - no implicit UID/GID identity or permissive allowlist,
  - strips caller identity/auth-claim fields before helper validation,
  - stamps the exact supported `schema_version` as the helper-protocol speaker.

### 2.5 Controller — `broker/firewall_controller_service/controller_service.py`
- Before invoking the backend, the controller builds a separate helper request and injects
  `ownership_reference`/`ownership_record_id` from the persisted broker-owned ownership
  record (or the newly persisted install intent). Caller-supplied ownership values are
  overwritten.
- If no authoritative ownership record exists for a non-health helper operation, the
  controller fails closed before backend execution.
- Removed the `peer_uid`/`peer_gid` `1000` defaults from the reconciliation inspect request;
  identity is now sourced only through the adapter's explicit provider.

### 2.6 Test isolation / explicit test wiring
- Added `broker/tests/_helper_identity.py` with `authorized_backend(...)`, an explicit
  test-only opt-in to a mock identity plus allowlists.
- Updated existing tests to inject `authorized_backend()` instead of relying on implicit
  defaults.
- `broker/tests/conftest.py` now isolates `FIREWALL_CONTROLLER_DB_PATH` into the per-session
  temp storage so the default `ControllerOwnershipStore` never writes into checked-in
  `broker/data`.

## 3. Actual identity propagation path (mock scope)

```
controller service
  (strict controller auth already completed on the transport/controller request)
        │
        │ _call builds backend request from persisted ownership state
        ▼
MockFirewallBackend._dispatch(method, req)
        │
        │ identity = self._identity_provider.get_identity()   # per request
        │ req = _prep(req)  # strips peer_uid/gid + auth-claim fields, stamps schema_version
        ▼
MockHelperExecutor.execute_method(method, req, identity=<supplied identity>)
        │
        ▼
MockHelperExecutor.execute(operation, req, identity=<supplied identity>)
        │
        ▼
MockHelperAuthorizationProvider.authorize(identity, operation, request=req)
        │  - missing/invalid identity -> deny
        │  - empty allowlists -> deny
        │  - unlisted uid/gid -> deny
        │  - operation not allowed -> deny
        ▼
validate_helper_request(req, operation)  # schema version, digest, ownership, compiled, bounds
        ▼
delegated mock execution (no shell, no host state changes)
```

The identity is passed separately from the operation request and is never read from request
JSON. A provider may return a different identity per call, so each request is independently
authorized.

## 4. Explicit mock identity configuration

Production-reachable adapter/executor construction has **no** trusted identity defaults.
To make a mock operation succeed, tests/development wiring must explicitly provide:

```python
from broker.firewall_controller_service.helper_authorization import (
    MockHelperAuthorizationProvider, MockHelperIdentityProvider, MockHelperPeerIdentity,
)
from broker.firewall_controller_service.mock_backend import MockFirewallBackend

identity = MockHelperPeerIdentity(uid=1000, gid=1000, source="explicit-test-only")
provider = MockHelperIdentityProvider(identity)
auth = MockHelperAuthorizationProvider(allowed_uids={1000}, allowed_gids={1000})
backend = MockFirewallBackend(helper_auth=auth, identity_provider=provider)
```

Tests use `broker/tests/_helper_identity.py::authorized_backend(...)` for the same explicit
seam. This mock identity proves nothing about real peer authentication and must never be
wired into production.

## 5. Fail-closed behavior verified

- No identity provider configured → denied.
- Identity provider raises/unavailable → denied.
- Empty UID/GID allowlists → denied.
- Unlisted UID/GID → denied.
- Identity supplied only in request JSON → cannot grant authorization; fields are stripped at
  the adapter and rejected by direct contract validation.
- Identity changes between requests → each request is authorized independently.
- Unauthorized operation → rejected before backend execution; mock state remains untouched.
- Missing authoritative ownership reference → controller fails closed before backend call.
- Uncertain/timeout outcomes remain non-success and cannot promote to `ACTIVE` without
  persisted evidence.

## 6. Schema-version enforcement

Mandatory and exact; rejected cases covered by tests:

- missing field,
- `None`,
- empty string,
- wrong type (integer),
- unsupported versions (including case/old-version variants),
- alias field (`schemaVersion`).

The adapter stamps the exact supported version, and the contract validates both requests and
responses against it. Caller-supplied values are not trusted.

## 7. Tests and results

All commands run from `E:\Flag-hunt\ctf-platform-be` using the repository virtual
environment on Windows (mock-only; no privileged operations).

| Command | Result |
|---|---|
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_helper_identity_propagation.py -q -p no:randomly` | **56 passed**, 1 warning |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_helper_contract.py -q -p no:randomly` | **24 passed**, 1 warning |
| `.\venv\Scripts\python.exe -m pytest broker/tests -q` | **292 passed**, 1 warning in 58.57s |
| `.\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client` | **Ran 33 tests — OK** |
| `.\venv\Scripts\python.exe manage.py check` | **System check identified no issues (0 silenced).** |

The single warning is the pre-existing `pydantic` class-based config deprecation warning; it
is unrelated to this phase.

New focused coverage (`test_firewall_controller_helper_identity_propagation.py`, 56 tests)
includes: implicit-default removal, provider-unavailable denial, empty/unlisted allowlists,
request-JSON identity spoofing (both directions), per-request identity changes, provider
call-per-request, authorization-before-execution, alternate-path (`execute_method`) parity,
mandatory/exact schema version, digest format, compiled-policy shape/injection/depth, explicit
ownership reference, timeout declaration, and controller injection of the persisted
ownership reference instead of a caller value.

## 8. Remaining real-transport and host-validation gaps (unresolved)

These are **not** implemented or proven by this phase:

1. **Real kernel-authenticated peer identity**: UDS + `SO_PEERCRED` (or independently approved
   equivalent), per-connection/per-request binding, unsupported-platform fail-closed behavior.
2. **Real helper process/binary**: fixed executable path, dedicated service account, privilege
   drop, minimal capability set, `NoNewPrivileges`, `CapabilityBoundingSet`, systemd/host
   hardening, socket path/permissions.
3. **Real IPC semantics**: framing/message-size limits before allocation, deadline/cancellation
   enforcement, lost-response and partial-apply semantics, process supervision/crash modes.
4. **Real backend/read-back evidence**: Docker/nftables/iptables ordering, IPv4/IPv6 symmetry,
   conntrack/revocation semantics, inspection evidence and timeouts.
5. **Real compiler/helper policy boundary**: semantic validation/canonicalization of compiled
   policy and guaranteed data-only interpretation (never expression/command evaluation).
6. **Helper-side durable ownership/idempotency**: the mock executor idempotency is in-memory
   only; the controller remains the authoritative durable store. Real helper durability across
   restarts must be designed and validated.
7. **SQLite/helper atomicity**: not claimed; conservative reconciliation remains required.

## 9. Strict prohibitions honored

This phase did **not** implement or activate Unix domain sockets, `SO_PEERCRED`, a real helper
process/executable, sudo, Linux capabilities, privileged service accounts, nftables/iptables/UFW/
Docker firewall rules, routing/NAT changes, systemd or host permission changes, live runtime
provisioning, cloud infrastructure, or production database changes. No unrelated application
features were modified.

---

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
