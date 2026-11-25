# Phase 2L.2G.3.3 — Independent Identity Remediation Review (Read-Only)

## Decision

**CONDITIONAL**

The 2L.2G.3.2 identity remediation is substantively present and verified in the inspected mock scope:

- explicit per-request identity propagation is implemented,
- implicit trusted UID/GID defaults are removed from production-reachable adapter/executor construction,
- missing identity and identity-provider failure fail closed,
- request JSON cannot establish identity,
- exact schema-version, digest, compiled-data, and explicit-ownership-reference validation are enforced,
- authorization occurs before normal helper execution.

However, the review identified two **Medium** issues that prevent unconditional acceptance even within mock scope:

1. ownership binding is incomplete: `instance_id`, `network_id`, and the request digest are not re-derived from the persisted ownership record for all helper operations and evidence;
2. the successful revoke path raises after the backend side effect and leaves ownership stuck in `REVOKING`.

Four **Low** authorization/robustness issues and several informational findings are also recorded. The real transport/helper boundary (H3) remains unresolved by design.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

## 1. Scope and limitations

- **Reviewed:** local source, tests, and documentation only, in read-only mode.
- **Environment:** Windows host, repository virtual environment, mock-only execution.
- **Not reviewed/not validated:** real Unix domain sockets, `SO_PEERCRED`, real privileged helper binary, real capability enforcement, real firewall backends, production database, cloud, or host-lab behavior.
- **Source modifications:** none.
- **Test modifications:** none.
- **Created:** this review document only.
- The workspace is not a git repository, so historical attribution of pre-existing defects could not be confirmed from version control. Findings are against the current tree.
- Passing tests are not treated as proof of the claims they do not exercise. The identified ownership-binding and revoke-success gaps are not covered by the current suite.

## 2. Verified identity call path

### 2.1 Normal controller -> adapter -> executor path

```
FirewallControllerService._call(operation, req)
  -> StrictAuthorizationProvider.authorize(req, operation)          # controller auth
  -> RequestValidator.validate(req)
  -> ownership/evidence/lifecycle enforcement
  -> backend_req = dict(req)
     backend_req["ownership_reference"] = persisted ownership_record_id
     backend_req["ownership_record_id"] = persisted ownership_record_id
  -> backend.<operation>(backend_req)                                # MockFirewallBackend

MockFirewallBackend._dispatch(method, req)
  -> identity = self._identity_provider.get_identity()               # per request
     (provider missing or raises -> None)
  -> req = _prep(req)
       - strips peer_uid, peer_gid and FORBIDDEN_AUTH_CLAIM_FIELDS
       - forces req["schema_version"] = SCHEMA_VERSION
  -> executor.execute_method(method, req, identity=identity)

MockHelperExecutor.execute_method(method, req, identity)
  -> METHOD_TO_OPERATION lookup (unknown -> structured error, no execution)
  -> execute(operation, req, identity=identity)

MockHelperExecutor.execute(operation, req, identity)
  -> auth.authorize(identity, operation, request=req)                # before validation/execution
       - identity None/invalid -> FirewallControllerAuthError
       - empty UID/GID allowlists -> deny
       - unlisted UID/GID -> deny
       - disallowed operation -> deny
  -> validate_helper_request(req, operation)
  -> deterministic injection (timeout/uncertain/failure) if configured
  -> helper idempotency check
  -> self._ctrl.<method>(req)
  -> validate_helper_response(resp)
```

### 2.2 Identity properties confirmed

| Requirement | Result |
|---|---|
| Every helper execution path requires an explicit identity argument | **Verified.** `execute` requires `identity`; `execute_method` delegates with `identity`; the adapter always supplies `self._identity()`. |
| No constructor/provider fallback supplies implicit identity | **Verified.** `MockHelperExecutor.__init__` no longer accepts `identity`; `MockHelperAuthorizationProvider` no longer accepts `identity_provider`; `MockFirewallBackend` requires an injected provider. |
| Missing identity and provider failure fail closed | **Verified.** Missing identity raises in the authorizer; provider absence returns `None`; provider exception is caught and returns `None`, which the authorizer denies. |
| Every operation independently authorized with that request's identity | **Verified.** Provider is consulted once per dispatch; a sequence provider returning authorized-then-unauthorized yields success then denial. |
| Reconciliation/recovery cannot bypass helper authorization | **Verified in mock scope.** `reconcile_pending_operations` authorizes/validates the top-level request, then calls `backend.inspect_policy(...)` directly; the adapter still applies provider identity and helper authorization per inspect. No executor call bypasses `authorize`. |
| No compatibility adapter restores UID/GID defaults | **Verified.** No `1000/1000` defaults in production-reachable modules. The only defaults are in `broker/tests/_helper_identity.py`, explicitly test-only. |
| Request JSON cannot establish or override identity | **Verified.** Adapter strips identity/auth-claim fields; direct contract validation rejects them with `UNAUTHORIZED_CLAIM`. |
| Identity cannot leak between sequential requests | **Verified.** Identity is fetched and passed synchronously per dispatch; sequence test confirms independent authorization. |

**Concurrency note:** the adapter keeps no per-request identity state; the fetched identity is a local argument passed directly into `execute_method`. The default `MockHelperIdentityProvider` is immutable. A custom stateful test provider could race if shared across threads, but that is a test-fixture concern, not production-reachable identity state.

**Validation-order note:** helper authorization runs before contract validation. This is fail-closed (unauthorized callers cannot probe schema behavior), but it retains the pre-existing 2L.2G.3.1 L1 residual: a real IPC layer should perform cheap framing/size/version checks before expensive handling.

### 2.3 Search results

- `MockHelperExecutor(...)` construction appears only in `broker/firewall_controller_service/` and tests. No constructor call supplies a default identity.
- `MockFirewallBackend(...)` construction appears in `broker/firewall_controller_service/` and tests. The only production-reachable construction is `FirewallControllerService.backend = backend or MockFirewallBackend()`; with no provider/auth it is fail-closed.
- `.execute_method(...)` call sites are the adapter and tests; tests pass explicit identities or intentionally pass `None` to assert denial.
- Hard-coded `1000/1000` remains only in test fixtures and test data, not in production-reachable helper construction.

## 3. Findings

### ID-01 — Medium — Ownership binding is incomplete for helper requests and evidence

**Affected files/functions**
- `broker/firewall_controller_service/controller_service.py`, `FirewallControllerService._call`
  - backend request construction (`backend_req = dict(req)`; only `ownership_reference`/`ownership_record_id` are overwritten)
  - verify evidence construction (`instance_id`, `network_id`, `address_family` taken from the caller request when present)
  - inspect/revoke/remove ownership checks (presence only; no digest/instance/network equality check)
- `broker/firewall_controller_service/helper_contract.py`, `validate_helper_request`
  - validates ownership-reference format but does not bind it to policy/instance/network/digest
- `broker/app/firewall_controller.py`, `MockFirewallController.inspect_policy`/`revoke_policy`
  - mock backend acts by `policy_id` and does not compare the caller digest to stored state

**Attack/failure scenario**
An authorized controller caller installs policy `P` version `1` with instance `i1`, network `n1`, digest `A`. The persisted ownership record is correct. The same authorized caller then:
- verifies with `instance_id="evil-instance"` and `network_id="evil-network"`; the controller stores evidence with those caller values rather than the persisted ownership values;
- inspects or revokes with digest `B` (a different valid 64-hex value); the controller does not compare `B` to the persisted `A` and forwards `B` to the helper.

In the mock, inspect/revoke act by `policy_id`, so the mock does not apply the wrong rule. In a real helper that keys or records by digest/instance/network, this could cause operation against mismatched metadata or misleading audit/evidence.

**Security impact**
- Weakens the ownership binding claimed for M1: only `policy_id`/`policy_version` bind the operation; digest/instance/network do not.
- Evidence and audit can be misattributed to a different instance/network/family.
- No privilege escalation was observed in mock scope (the caller must already be authorized for the policy/version), but the integrity guarantee is incomplete.

**Evidence**
- Code inspection: `backend_req` only overwrites ownership reference; verify evidence uses `req.get('instance_id') or existing.get(...)` and `req.get('network_id') or existing.get(...)`.
- Read-only probe with a temp DB: after a normal install, verify with caller `instance_id="evil-instance"` / `network_id="evil-network"` stored evidence with those exact values.
- Read-only probe: inspect with caller digest `c*64` while persisted digest was `a*64` returned `status: ok` and the mock's stored digest `a*64`; no controller-level mismatch rejection occurred.
- Revoke with a mismatched digest reached the same lifecycle path as a matching digest (see ID-02), demonstrating the digest was not rejected before backend invocation.

**Required remediation**
- In the controller, overwrite `instance_id`, `network_id`, and `compiled_rule_digest` in `backend_req` from the persisted ownership record for every non-health operation.
- Store verify evidence using persisted ownership values, not caller values.
- Reject caller digest/instance/network mismatches for inspect, verify, revoke, and remove with a fail-closed error.
- Add focused tests for verify/inspect/revoke/remove ownership-field binding (the current ownership-reference test covers install only).

**Real transport/host validation required?** No. This is controller-level and can be fixed and tested in mock scope.

### ID-02 — Medium — Successful revoke raises after the backend side effect and leaves ownership in `REVOKING`

**Affected files/functions**
- `broker/firewall_controller_service/controller_service.py`, `FirewallControllerService._call`
  - pre-backend revoke transition: `ACTIVE -> REVOKING`
  - post-backend revoke block: re-reads ownership (now `REVOKING`) and calls `_check_lifecycle_transition(cur, 'REVOKING')`
- `_check_lifecycle_transition`
  - transition table does not allow `REVOKING -> REVOKING`

**Attack/failure scenario**
A normal lifecycle `install -> verify (ACTIVE) -> revoke` is attempted. The backend revoke succeeds (mock removes the policy). The controller then re-reads the ownership record, sees `REVOKING`, and calls `_check_lifecycle_transition('REVOKING', 'REVOKING')`, which raises `PermissionError`. The request returns an error even though the privileged side effect already occurred, and the record remains `REVOKING`.

A retry with a new idempotency key again fails at the same transition. `REVOKING` does not allow `VALIDATING` or `REVOKING`, so reinstall/cleanup progression is blocked.

**Security impact**
- Not a privilege escalation.
- Integrity/availability defect: false failure after a completed privileged action; uncertain/stuck lifecycle state; undermines idempotency and recovery expectations.
- The backend has already revoked, while the controller cannot record `REVOKED`.

**Evidence**
- Read-only probe with a temp DB: `install -> ok`, `verify -> ok`, `revoke (matching digest) -> PermissionError: Invalid lifecycle transition REVOKING -> REVOKING`; persisted state remained `REVOKING`.
- The same outcome occurred with a mismatched digest, confirming the failure occurs after backend invocation.
- The current test suite does not exercise a successful revoke end-to-end; 292 tests pass despite this.

**Required remediation**
- Do not re-apply the `REVOKING` transition after the backend returns success. If the record is already `REVOKING`, only transition it to `REVOKED` (or the appropriate cleanup state) once.
- Persist the revoke result idempotently and make retries converge.
- Add a successful revoke lifecycle test and a retry test.
- Audit whether this defect pre-dates 2L.2G.3.2; it is not caused by the identity changes inspected, but it is a real controller lifecycle defect and should be fixed before any live integration.

**Real transport/host validation required?** No. Controller-level.

### ID-03 — Low — Idempotency replay returns a cached response before authorization

**Affected files/functions**
- `broker/firewall_controller_service/controller_service.py`, `FirewallControllerService._call`
  - durable idempotency lookup/replay block executes before `self.auth.authorize(req, operation)`.

**Attack/failure scenario**
An authorized peer performs an operation with idempotency key `K`. A different peer that is **not** in the UID/GID allowlist submits the same key and payload (including the same `peer_uid`/`peer_gid` fields, which are not part of the request digest). Because the completed idempotency record is found first, `_call` returns the cached response without running controller authorization.

**Security impact**
- Authorization-ordering gap for the replay path; no privileged execution occurs.
- Requires knowledge of the idempotency key, but keys may be exposed in logs/audit/traces.
- Potential disclosure of response metadata (status, rule handles, evidence identifiers).
- Pre-existing behavior; not introduced by the identity propagation change, but it conflicts with the review criterion “authorization before execution/replay.”

**Evidence**
- Read-only probe: authorized install with key `K` returned `ok`; an unauthorized peer (UID 9999, allowlist `{1000}`) submitting the same key/payload returned the cached `ok` instead of being rejected.

**Required remediation**
- Authorize and validate before exposing an idempotency replay, or bind the idempotency record to the authenticated identity and verify it before replay.
- Add a test asserting an unauthorized peer cannot obtain a cached response.

**Real transport/host validation required?** No.

### ID-04 — Low — Ownership lookup failures are swallowed and reported as “not found”

**Affected files/functions**
- `broker/firewall_controller_service/ownership_store.py`, `ControllerOwnershipStore.get_by_policy`
  - catches all exceptions and returns `None`.

**Failure scenario**
A database/storage failure during `get_by_policy` is indistinguishable from “no ownership record.” Most callers then fail closed (`PermissionError` or a failed create), but `reconcile_pending_operations` treats it as `no_ownership_no_adoption` and returns `status: ok` with an `uncertain` entry rather than surfacing a storage error.

**Security impact**
- No privileged action or adoption occurs, so it is fail-closed for security.
- Operational masking: a storage outage can be misclassified as an absent ownership record, reducing visibility and potentially delaying recovery.

**Evidence**
- Read-only probe: replacing `store.db.query` with a raising function caused `get_by_policy('x', 1)` to return `None`.
- Code inspection confirms the broad `except Exception: return None`.

**Required remediation**
- Distinguish “not found” (empty result) from “lookup failed” (raise a typed storage error), and have callers fail closed with an explicit error result.
- Keep the no-auto-adoption behavior.

**Real transport/host validation required?** No.

### ID-05 — Low — Helper operation allowlist defaults to all operations

**Affected files/functions**
- `broker/firewall_controller_service/helper_authorization.py`, `MockHelperAuthorizationProvider.__init__`
  - `allowed_operations` defaults to the full `HelperOperation` enum when not supplied.

**Failure scenario**
Wiring supplies explicit UID/GID allowlists but omits the operation allowlist; the helper then permits every operation, including install/revoke, for that identity. This is a least-privilege gap, not an identity bypass.

**Security impact**
- Broader helper authority than intended if operation policy is forgotten.
- Mock-only at present, but the pattern should not be carried into the real helper.

**Evidence**
- Code inspection: `set(allowed_operations) if allowed_operations is not None else set(HelperOperation)`.
- Test fixture `authorized_backend(..., allowed_operations=None)` therefore grants all operations.

**Required remediation**
- Default to empty/deny, or make the operation allowlist mandatory in any production-reachable construction.
- Keep test opt-in explicit.

**Real transport/host validation required?** No for the mock fix; real helper must enforce its own explicit operation policy.

### ID-06 — Low — Compiled-policy “data-only” validation is heuristic, not a parser boundary

**Affected files/functions**
- `broker/firewall_controller_service/helper_contract.py`, `_validate_compiled`
  - global allowed-key set at every depth; token blocklist; depth/size/type bounds.

**Failure scenario**
The blocklist rejects common shell/expression markers, but it is not a semantic parser and can be bypassed by encoded/obfuscated content. Conversely, the global key allowlist applies to nested objects and can reject legitimate compiled-rule structures whose nested keys are not in `COMPILED_ALLOWED_KEYS`.

**Security impact**
- Defense-in-depth only. It must not be represented as proof that compiled policy cannot be interpreted as code.
- The real helper must treat compiled policy strictly as data and perform its own semantic validation/canonicalization.

**Evidence**
- Code inspection of `_validate_compiled` and `_FORBIDDEN_COMPILED_TOKENS`.
- Tests cover representative tokens and shapes, not parser equivalence.

**Required remediation**
- Define a real compiled-policy schema and canonicalizer for the real helper.
- Keep the blocklist as a secondary check, not the primary control.
- Relax or scope the nested-key allowlist to avoid false rejection of valid rule objects.

**Real transport/host validation required?** Yes for real enforcement; the mock-level heuristic is acceptable only as mock-scope defense-in-depth.

### ID-07 — Informational — Mock verify reports digest match without comparing stored state

**Affected files/functions**
- `broker/app/firewall_controller.py`, `MockFirewallController.verify_policy`
  - reports `digest_match: True` and verifies by `policy_id` presence only.

**Impact**
Mock fidelity issue: the controller’s post-verify digest check is the only digest guard for verify. The mock also adds the policy to `verified` before the controller’s post-check. This does not create a live vulnerability, but the mock should compare the stored digest to the requested digest for fidelity.

**Remediation**
Real backend read-back and digest comparison; optionally tighten the mock.

**Real transport/host validation required?** Yes for real read-back assurance.

### ID-08 — Informational — Default controller backend is the fail-closed mock

**Affected files/functions**
- `broker/firewall_controller_service/controller_service.py`, `FirewallControllerService.__init__`
  - `self.backend = backend or MockFirewallBackend()`.

**Impact**
Fail-closed (no provider/auth), so this is not implicit trust. However, production wiring must inject a real backend; relying on the default yields availability failure, not silently privileged behavior. Documented as a deployment gate.

**Remediation**
Require explicit backend injection in production configuration; add a startup assertion outside mock scope.

**Real transport/host validation required?** Yes for real backend selection.

### ID-09 — Informational — Unknown `execute_method` returns before authorization

**Affected files/functions**
- `broker/firewall_controller_service/mock_helper_executor.py`, `execute_method`
  - unknown method returns `OPERATION_NOT_ALLOWED` before identity authorization.

**Impact**
No execution occurs; minor operation-name enumeration. Acceptable in mock scope, but the real IPC boundary should reject unknown framing consistently and avoid distinguishing behavior unnecessarily.

**Remediation**
Optional: authorize/frame-check before returning operation errors.

**Real transport/host validation required?** No for mock.

### ID-10 — Informational — Timeout is validated but not enforced

**Affected files/functions**
- `helper_contract.py` (`MIN_TIMEOUT_MS`/`MAX_TIMEOUT_MS`, `TIMEOUT_ENFORCEMENT_LAYER`)
- `mock_helper_executor.py` (injected timeout returns a structured error)

**Impact**
Accurately documented: wall-clock deadline enforcement belongs to the future transport/process layer. Not a regression. A real transport must implement deadlines/cancellation and must not treat “validated” as “enforced.”

**Real transport/host validation required?** Yes.

### ID-11 — Informational — Helper does not bind the ownership reference to helper-owned durable records

**Affected files/functions**
- `helper_contract.py` validates only the reference format.
- `MockHelperExecutor` trusts the controller-supplied reference after validation.

**Impact**
In mock scope the controller is authoritative and injects the persisted ID, so this is acceptable. In a real helper, accepting an arbitrary well-formed reference would not prove the helper owns the policy. The real helper must bind the reference to its own durable ownership/operation records and enforce operation/policy consistency.

**Real transport/host validation required?** Yes.

### ID-12 — Informational — Identity values are coerced with `int()`

**Affected files/functions**
- `helper_authorization.py`, `MockHelperAuthorizationProvider.authorize`
  - `uid = int(identity.uid)`, `gid = int(identity.gid)`.

**Impact**
Mock identity values supplied as strings/floats can be accepted (e.g., `"1000"`, `1000.9`). The real transport must supply kernel-typed integer credentials and must not perform lossy coercion. Mock-only looseness.

**Real transport/host validation required?** Yes for real credentials.

### ID-13 — Informational — Digest algorithm is assumed by format, not independently verified

**Affected files/functions**
- `broker/firewall_controller_service/helper_contract.py`, `_validate_digest`
  - enforces exactly 64 hexadecimal characters but does not prove the value was computed with SHA-256.
- `broker/firewall_controller_service/controller_service.py`, `_req_digest`
  - controller-side request digest uses SHA-256.

**Impact**
The format is strict, but a caller can supply any 64-hex value. For install it becomes the persisted ownership digest; for verify the controller compares it to the persisted value; for inspect/revoke/remove it is not compared (ID-01). The real compiler/controller must compute and bind the digest; format validation alone is not algorithmic proof.

**Remediation**
Treat the digest as a controller/compiler-produced value for real deployment and bind it to persisted ownership for all operations (overlaps ID-01).

**Real transport/host validation required?** No for the controller-side binding; real compiler provenance requires the real compiler boundary.

### ID-14 — Informational — `compiled` is optional in the helper contract

**Affected files/functions**
- `broker/firewall_controller_service/helper_contract.py`, `validate_helper_request`
  - validates `compiled` only when present; does not require it for install/verify.

**Impact**
The mock executor treats `compiled` as opaque and can install with an empty/missing payload while still accepting a valid digest. This is acceptable for the mock, but a real helper must require and interpret the compiled payload (or explicitly support digest-only operations) and must not report success for an absent policy body.

**Remediation**
Define operation-specific required fields for the real helper and validate the compiled payload there.

**Real transport/host validation required?** Yes for real helper semantics.

## 4. Ownership, schema, and compiled-policy verification summary

| Area | Verified | Notes |
|---|---|---|
| Ownership reference sourced from persisted state | **Yes for install and all non-health adapter requests** | Controller overwrites caller `ownership_reference`/`ownership_record_id` with the persisted record ID. |
| Caller ownership ID cannot override authoritative value | **Yes** | Confirmed by test and code; only the injected value is used. |
| Missing/invalid ownership prevents helper execution | **Yes** | Controller raises before backend; contract also rejects missing/invalid reference. |
| Ownership lookup failures fail closed | **Partially** | Security actions fail closed; `get_by_policy` masks storage errors as not-found (ID-04). |
| Ownership reference bound to correct operation/policy | **Partially** | Policy/version binding is present; digest/instance/network binding is incomplete (ID-01). |
| Stale/unrelated ownership cannot authorize | **Not fully proven** | Unique policy/version prevents a second ownership record, but operation metadata can be caller-controlled (ID-01). |
| Durable idempotency/conflict intact | **Yes** | Request digest and durable records; replay-before-auth issue is ID-03. |
| Evidence-gated ACTIVE intact | **Yes** | Evidence stored before `VERIFIED -> ACTIVE`; tests pass. |
| Mandatory exact schema version | **Yes** | Missing/null/empty/wrong-type/unsupported/alias rejected; request and response validated. |
| Exact digest format | **Yes** | Exactly 64 hex characters; SHA-256 algorithm binding is assumed, not independently verifiable (ID-13). |
| Validation order | **Auth before contract validation** | Fail-closed for unauthorized callers; pre-existing L1 residual for cheap framing/size/version checks in a real IPC layer. |
| Compiled data-only constraints | **Yes within heuristic scope** | Allowed keys, depth/size/type bounds, token rejection; not a parser (ID-06). |
| IPv4/IPv6/CIDR/protocol/port validation | **Yes** | `ipaddress` family checks, allowed families/protocols, port bounds. |
| Timeout contract accuracy | **Yes** | Bounded validation; enforcement explicitly deferred. |
| Uncertain outcomes remain non-ACTIVE | **Yes** | Tests cover timeout/uncertain injection. |
| Restart reconciliation / no auto-adoption | **Yes** | Tests pass; storage-error masking noted (ID-04). |

## 5. Test execution results

All commands were executed from `E:\Flag-hunt\ctf-platform-be` using `.\venv\Scripts\python.exe` on Windows. No source or test files were modified.

| Command | Result |
|---|---|
| `pytest broker/tests/test_firewall_controller_helper_identity_propagation.py -q -p no:randomly` | **56 passed**, 1 warning in 0.43s |
| `pytest broker/tests/test_firewall_controller_helper_contract.py -q -p no:randomly` | **24 passed**, 1 warning in 0.77s |
| Relevant controller authorization/lifecycle/persistence/recovery subset (12 files: active enforcement, active integration, security remediation, skeleton, lifecycle idempotency, concurrency integrity, deterministic concurrency, targeted integrity, persistent recovery, persistence failure closure, transport mock, contract) | **89 passed**, 1 warning in 18.41s |
| `pytest broker/tests -q` | **292 passed**, 1 warning in 39.61s |
| `manage.py test instances.tests.test_manager_client` | **Ran 33 tests — OK** |
| `manage.py check` | **System check identified no issues (0 silenced).** |

The single warning in each pytest run is the pre-existing pydantic class-based-config deprecation warning. PowerShell reports a non-zero process exit because pytest writes warnings to stderr; the pytest summary confirms success.

**Coverage limitation:** the passing suite does not include a successful end-to-end revoke assertion, nor cross-operation ownership-field binding assertions. Therefore the 292/89 passing counts do not contradict ID-01/ID-02; they confirm the gaps are untested.

## 6. Remaining unresolved real-transport and host risks

These are not implemented or proven by this phase:

1. **Kernel-authenticated peer identity:** UDS + `SO_PEERCRED` (or independently approved equivalent), per-connection binding, unsupported-platform fail-closed behavior.
2. **Real helper process/binary:** fixed executable path, dedicated service account, privilege drop, minimal capabilities, `NoNewPrivileges`, `CapabilityBoundingSet`, systemd/host hardening, socket path/permissions.
3. **Real IPC semantics:** framing/message-size limits before allocation, deadline/cancellation enforcement, lost-response and partial-apply semantics, process supervision/crash modes.
4. **Real backend/read-back evidence:** Docker/nftables/iptables ordering, IPv4/IPv6 symmetry, conntrack/revocation semantics, inspection evidence and timeouts.
5. **Real compiler/helper policy boundary:** semantic validation/canonicalization and guaranteed data-only interpretation (never expression/command evaluation).
6. **Helper-side durable ownership/idempotency:** the mock executor idempotency is in-memory; the controller remains authoritative. Real helper durability across restarts must be designed and validated.
7. **Service identity separation:** real controller→helper authentication must identify the controller service, not the end user; the mock provider is a fixed test seam.
8. **SQLite/helper atomicity:** not claimed; conservative reconciliation remains required.

## 7. Explicit implementation gate

- **Do not proceed to real transport, privileged helper, capability changes, or live firewall integration** until:
  - ID-01 (ownership-field binding) is remediated and independently re-reviewed;
  - ID-02 (revoke success lifecycle) is remediated and covered by success/retry tests;
  - ID-03–ID-05 are fixed or explicitly accepted with rationale;
  - the real-transport items in Section 6 are addressed under a separately approved proposal and validated on the intended Linux host.
- The mock-only identity remediation may be treated as **conditionally acceptable** for continued local mock development, subject to the above.
- No live firewall integration, privileged execution, or host mutation is authorized by this review.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
