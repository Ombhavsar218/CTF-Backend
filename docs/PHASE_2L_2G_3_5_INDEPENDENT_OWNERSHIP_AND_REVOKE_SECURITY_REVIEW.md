# Phase 2L.2G.3.5 — Independent Ownership and Revoke Security Review

**Scope:** local mock-only controller / helper-boundary review  
**Date:** 2026-11-07  
**Reviewed remediation:** `docs/PHASE_2L_2G_3_4_OWNERSHIP_BINDING_AND_REVOKE_LIFECYCLE_REMEDIATION.md`  
**Base findings:** `docs/PHASE_2L_2G_3_3_INDEPENDENT_IDENTITY_REMEDIATION_REVIEW.md`

> **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
>
> This review covers controller and mock-code behavior only. It does not authorize or validate a
> real transport, UDS/`SO_PEERCRED`, privileged helper, capabilities, firewall backend, routing/NAT,
> conntrack, systemd/host hardening, provisioning, or production/cloud database changes.

## 1. Decision

| Decision layer | Result |
|---|---|
| Local mock-only 2L.2G.3.4 remediation | **CONDITIONAL** |
| Real transport / privileged helper / live firewall readiness | **NOT READY — NOT AUTHORIZED** |

The ownership-binding, authorization-ordering, storage-error, helper-allowlist, and normal revoke
lifecycle changes are substantively present and the complete test suite passes. I am not returning
an unconditional PASS because independent inspection and read-only adversarial probes found
unresolved recovery/integrity gaps in the mock implementation:

1. a same-key retry after an uncertain/failed revoke returns the cached error instead of performing
   the required read-back retry;
2. reconciliation converts some persistence failures into `status: ok` with an `uncertain` entry
   instead of propagating `BrokerDBError`, and silently ignores an unknown persisted lifecycle state;
3. several ownership/evidence/idempotency binding checks omit fields or trust an already-terminal
   `REVOKED` record without re-checking evidence.

These are not privilege-escalation findings in the inspected mock scope, but they are material to
the stated “retries converge”, “fail closed”, and “no unverified promotion” acceptance criteria.
They must be closed, or explicitly accepted as mock-only limitations, before this phase can be called
PASS.

No source or test file was modified during this review. The only file created is this review report.

## 2. Review method and constraints

- Read the controller service, ownership store, helper authorization, helper contract, mock backend,
  mock helper executor, request validator, and relevant persistence/schema code directly.
- Read the three 2L.2G.3.4 remediation test modules, the identity-propagation and helper-contract
  tests, and controller persistence/recovery tests.
- Ran the required regression, persistence/recovery, full Broker, Django manager-client, and Django
  system-check commands without modifying tests.
- Ran additional read-only inline Python probes against temporary SQLite databases. No repository
  files were written by those probes.
- No real helper, transport, firewall, host, routing, systemd, provisioning, or production database
  was touched.

## 3. Test execution

All commands were run from `E:\Flag-hunt\ctf-platform-be` with
`.\venv\Scripts\python.exe` on Windows. PowerShell can return a non-zero process status when pytest
writes warnings to stderr; the pytest summary is authoritative.

| Command | Result |
|---|---|
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_ownership_binding_remediation.py -q` | **24 passed**, 1 warning, 13.97s |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_revoke_lifecycle_remediation.py -q` | **14 passed**, 1 warning, 13.21s |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_remediation_authorization_storage_allowlists.py -q` | **20 passed**, 1 warning, 5.15s |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_helper_identity_propagation.py -q` | **56 passed**, 1 warning, 0.53s |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_helper_contract.py -q` | **24 passed**, 1 warning, 1.05s |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_persistent_recovery_integration.py broker/tests/test_firewall_controller_persistence_failure_closure.py -q` | **40 passed**, 1 warning, 12.62s |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_crash_boundary_instrumentation.py broker/tests/test_firewall_controller_cross_process_crash_recovery.py broker/tests/test_firewall_controller_cross_process_concurrency.py -q` | **20 passed**, 1 warning, 13.34s |
| `.\venv\Scripts\python.exe -m pytest broker/tests -q` | **350 passed**, 1 warning, 64.83s |
| `.\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client` | **Ran 33 tests — OK**, 0.016s |
| `.\venv\Scripts\python.exe manage.py check` | **System check identified no issues (0 silenced).** |

The counted warning in each pytest run is the pre-existing Pydantic class-based-config
deprecation. A separate `pytest_asyncio` loop-scope deprecation is emitted on stderr before the
pytest summary and is not counted in the summary.

All required commands were run. No command is reported as run that was not actually executed.

### 3.1 Read-only adversarial probes

These probes used temporary databases and inline Python only; no test or source files were changed.

| Probe | Observed result |
|---|---|
| Install → verify → revoke with backend failure; retry with the **same** idempotency key after clearing the failure | First revoke: error `REVOKE_FAILED`, state `REVOKING`. Same-key retry: error `REVOKE_FAILED`, state still `REVOKING`; backend read-back was not attempted. New-key retry: `ok`, state `REVOKED`. |
| Reconcile a `REVOKING` record while revocation-evidence persistence raises `BrokerDBError` | `status: ok`; `uncertain` entry `partial_revoke: injected evidence write failure`; state remains `REVOKING`. The storage error is caught rather than propagated. |
| Reconcile a valid ownership record whose persisted state is `BOGUS_STATE` | `status: ok`; `reconciled`, `uncertain`, and `errors` all empty; state remains `BOGUS_STATE`. |
| Revoke a record already persisted as `REVOKED` with no evidence row | `status: ok`, `already_revoked: true`, evidence list empty. |
| Install with key `K` and `compiled: {}`; repeat key `K` with a different `compiled` body | Both calls report `ok`; the second is served from cache; stored backend body remains the first body. |
| Verify with a key whose request omits optional `instance_id`/`network_id`; mutate the authoritative instance; replay the same request | Replay returns the original cached `ok` response even though authoritative ownership changed. |
| `_DIGEST_RE.match('a'*64 + '\n')` | Returns `True`; the “exact 64 hex” regex accepts a trailing newline. |

## 4. Finding-by-finding assessment

### ID-01 — Authoritative ownership binding

**Assessment: substantially implemented; CONDITIONAL due to residual binding gaps.**

Verified implementation:

- `_call` resolves ownership by `policy_id` + `policy_version` before dispatch and rejects missing
  ownership for inspect, verify, revoke, remove, and reconciliation
  (`controller_service.py`, `_call` / `_validate_ownership_binding`).
- `_validate_ownership_binding` compares caller-supplied ownership reference/record ID, policy,
  version, instance, network, digest, address family, and required family against persistence.
- `_authoritative_request` rewrites ownership-bearing helper fields from the persisted record:
  ownership ID/reference, policy/version, canonical digest, instance, network, family, and required
  families.
- Verification and revocation evidence is built from the persisted record, not from caller or
  backend metadata.
- Read methods in `ControllerOwnershipStore` propagate `BrokerDBError`; genuine absence remains
  `None`/empty, as confirmed by the 20-test authorization/storage/allowlist module.
- New tests cover spoofed instance/network/ownership reference, mismatched digests for all four
  operations, missing/wrong-version/unrelated ownership, and ownership changes during execution.

Residual issues:

- **F-04:** `address_family` is validated during request binding but is absent from
  `_ownership_identity` and from the evidence matching predicates. A concurrent or externally
  introduced family change is therefore not detected by the “identity unchanged” comparison, and
  evidence from another family can satisfy the revocation evidence gate.
- **F-09:** `_validate_replay` validates the fresh record but does not compare the idempotency
  record’s stored `ownership_record_id` to the fresh record. If the caller omits optional
  instance/network fields, a cached response can be returned after authoritative ownership changed.
- The first install necessarily uses caller-supplied instance/network/digest as the initial
  authority. That is acceptable only as mock scope; the real broker must provide provenance and
  authorization for first-install ownership. `expected_ownership_identity` is passed through by
  `_authoritative_request` and is not part of the binding; the real helper must not treat it as
  authoritative.

**Disposition:** Core ID-01 remediation is present and tested; F-04/F-09 are low-severity residual
binding gaps.

### ID-02 — Revoke lifecycle ordering and recovery

**Assessment: normal lifecycle is implemented; CONDITIONAL due to retry and terminal-state gaps.**

Verified normal sequence in `_complete_revoke`:

- persist `REVOKING` with lifecycle CAS before the backend call;
- call backend revoke;
- perform an authoritative backend read-back and require `missing` or `revoked`;
- persist revocation evidence for the same ownership record/digest/instance/network;
- re-read the ownership record, revalidate ownership, require `REVOKING`, then CAS
  `REVOKING -> REVOKED`;
- never apply `REVOKING -> REVOKING`.

The revoke lifecycle module verifies successful revoke, no duplicate `REVOKING` history, mismatched
digest rejection, read-back failure (`REVOKE_UNCONFIRMED`), new-key retry, evidence/lifecycle
persistence failure, restart reconciliation, and concurrent revoke convergence. All 14 tests pass.

Residual issues:

- **F-01 (material):** A same-key retry after a backend failure, timeout, uncertain result, or
  unconfirmed read-back receives the completed idempotency record and returns the cached error
  without re-reading the backend. The new-key path does read back and converges; the same-key path
  does not. This conflicts with the stated retry/read-back and “retries converge” criteria unless
  the intended contract explicitly requires a new key for retry.
- **F-06 (low):** An ownership record already in `REVOKED` returns `already_revoked` success without
  requiring revocation evidence. Normal code writes evidence before `REVOKED`, but a corrupt,
  migrated, or externally modified record is trusted as terminal. The same applies to reconciliation
  of a `REVOKED` record.
- **F-04 (low):** The revocation evidence gate omits `address_family` from the comparison set.
- **F-02 (material, recovery visibility):** In reconciliation, a `BrokerDBError` raised while
  storing revocation evidence or updating ownership state is caught by the broad
  `except Exception` and reported as `status: ok` / `uncertain`. The state remains `REVOKING` (good
  fail-closed state preservation), but the storage failure does not propagate and is misclassified.

**Disposition:** The original successful-revoke defect is fixed. ID-02 is not unconditionally
accepted because same-key retry recovery and the terminal-state/evidence gate remain incomplete.

### ID-03 — Authorization and ownership validation before replay

**Assessment: implemented for the tested identity/digest paths; CONDITIONAL due to payload binding
and record-binding gaps.**

Verified implementation:

- `_call` performs `auth.authorize` and request validation before idempotency lookup.
- The same-key/different-digest conflict is rejected before ownership resolution.
- Authoritative ownership is resolved and validated before a cached response is returned.
- `_req_digest` includes `peer_uid` and `peer_gid`; the tests confirm an unauthorized identity and
  a different authorized identity cannot retrieve another identity’s cached success.
- `_validate_replay` re-fetches current ownership and revalidates against the request.
- Concurrent identical request handling uses a pending-record wait and fail-closed pending error.

Residual issues:

- **F-05 (low):** `_req_digest` covers only `policy_id`, `policy_version`, `compiled_rule_digest`,
  `instance_id`, `network_id`, and requester UID/GID. It excludes the `compiled` body,
  `address_family`, required families, and other request fields. A same-key request with a different
  `compiled` body is accepted as identical and receives the cached success. No second execution
  occurs, so this is a false-success/contract-integrity issue, not execution of a different policy.
  It is only fully safe if `compiled_rule_digest` is guaranteed to be a canonical digest of
  `compiled`; the controller does not compute or verify that relationship (ID-13 remains a
  real-boundary gate).
- **F-09 (low):** Replay does not compare the idempotency record’s ownership record ID, and a
  replay request that omits optional ownership fields can pass current validation after the
  authoritative instance/network changed. The probe described in §3.1 confirms the stale cached
  success.
- **F-01 (material):** The same-key cached-response behavior also prevents retry convergence for
  uncertain revoke failures, as described under ID-02.
- In the direct mock service, `peer_uid`/`peer_gid` are caller-supplied request fields; the mock
  transport injects them. This is not kernel-authenticated identity. Replay is bound to the request’s
  peer fields, not to a real transport identity.

**Disposition:** The original “replay before authorization” defect is fixed. The remaining issues
are payload/record-binding and same-key retry semantics.

### ID-04 — Genuine absence versus storage failure

**Assessment: read-path remediation is implemented; CONDITIONAL due to reconciliation error
masking and corrupt-state handling.**

Verified implementation:

- `ControllerOwnershipStore._query_dicts` calls `self.db.query` without converting exceptions to
  absence.
- `get_by_policy`, `get_idempotency_record`, lifecycle/evidence listings, pending-idempotency
  listing, and ownership listing propagate storage errors.
- `get_by_policy` returns `None` only for an empty result.
- Controller ownership/idempotency read failures propagate; tests inject `BrokerDBError` and observe
  no fabricated ownership record or cached response.
- Reconciliation read failure propagates instead of being reported as “no ownership”.

Residual issues:

- **F-02 (material):** Reconciliation catches `BrokerDBError` from evidence persistence and state
  updates in its broad exception handlers and returns `status: ok` with an `uncertain` entry. The
  probe in §3.1 confirms this for revocation evidence persistence. State remains safe, but the
  storage failure is concealed from the caller.
- **F-03 (low):** A persisted lifecycle state outside the known state machine is silently ignored:
  reconciliation returns `status: ok` with empty `reconciled`, `uncertain`, and `errors` collections.
  This is corrupt semantic persistence and should be classified as uncertain/corrupt, not success.
- `update_reconciliation_status` failures in the `ACTIVE` path are caught and discarded
  (`except Exception: pass`) while the result is reported as `active_ok`. This is a lower-impact
  storage-write masking issue but follows the same pattern.
- A corrupt non-numeric persisted `policy_version` can raise an uncaught conversion error rather than
  a typed corrupt-record result. It still fails closed, but not with the intended classification.

**Disposition:** The original read-swallowing defect is fixed. ID-04 is not unconditional because
reconciliation write failures and unknown states are not consistently surfaced.

### ID-05 — Helper operation allowlists and authorization path

**Assessment: implemented for the helper boundary.**

Verified implementation:

- `MockHelperAuthorizationProvider` defaults omitted UID, GID, and operation sets to empty.
- Empty UID/GID/operation allowlists deny all operations.
- An operation not in the explicit allowlist is rejected.
- The mock executor authorizes before contract validation and before dispatch.
- `MockFirewallBackend` defaults to an executor with empty allowlists; tests explicitly opt in via
  `broker/tests/_helper_identity.py`.
- New tests cover missing/empty operation allowlists, only-configured-operation success, unknown
  `execute_method`, and explicit test-fixture configuration.
- The helper contract remains strict about operation enum values and request fields.

Additional observation (not part of the helper ID-05 fix):

- `StrictAuthorizationProvider` in `authorization_strict.py` uses
  `allowed_operations or {full default set}`. Passing an explicitly empty controller operation set
  therefore falls back to all operations, unlike the helper provider. If controller-level operation
  least privilege is in scope, this should also use an explicit `is None` check. No test currently
  exercises it.

Known informational behavior:

- `execute_method` with an unknown method returns `OPERATION_NOT_ALLOWED` before authorization; no
  operation executes. This is the previously documented ID-09 ordering issue.

**Disposition:** ID-05 is accepted for the helper mock boundary. The controller-side empty-operation
fallback is an additional least-privilege observation.

### ID-06 — Compiled-policy validation limitation

**Assessment: correctly documented as heuristic; no parser-level safety claimed.**

`helper_contract.py` describes bounded JSON-like data validation, allowed keys, depth/size limits,
type limits, and a forbidden-token blocklist. The remediation report explicitly says this is not a
parser or semantic proof and that the real helper must define and canonicalize a compiled-policy
schema and treat the payload strictly as data. The tests cover representative rejected shapes and
tokens, not parser equivalence. This is consistent with the required ID-06 disposition.

Separate low-severity format issue:

- **F-07:** `_DIGEST_RE = r"^[a-fA-F0-9]{64}$"` and `_ID_RE = r"^[A-Za-z0-9._:-]{1,128}$"` use
  `re.match` with `$`, which matches before a trailing newline. A digest such as `'a'*64 + '\n'`
  is accepted. This does not create a parser-level guarantee problem, but it contradicts the
  “exact” format comment and can cause downstream canonicalization disagreement. Use
  `fullmatch` or `\Z` if exact format is intended.

## 5. Additional findings

| ID | Severity | Finding | Impact | Required remediation |
|---|---|---|---|---|
| F-01 | Medium (mock recovery) | Same-key retry after an uncertain/failed revoke returns the completed error response without read-back; new-key retry converges. | An uncertain revoke can remain stuck from the caller’s perspective under the same key; no privileged escalation. | Either define and enforce “retry requires a new key” as the contract, or do not complete idempotency for uncertain outcomes and allow same-key retry to perform the read-back recovery path. Add a regression test. |
| F-02 | Medium (mock error visibility) | Reconciliation catches `BrokerDBError` from evidence/state writes and returns `status: ok` with `uncertain`. | Storage failure is misclassified; state stays safe but operational recovery is delayed and the ID-04 propagation claim is false for this path. | Re-raise `BrokerDBError` or return a top-level error classification while preserving `REVOKING`; add fault-injection reconciliation tests. |
| F-03 | Low | Unknown persisted lifecycle state is silently ignored by reconciliation. | Corrupt state produces `status: ok` with no result; no action, but no alert/classification. | Add an explicit `else` that records `uncertain/corrupt_ownership_state` or returns an error. |
| F-04 | Low | `address_family` is not in `_ownership_identity` or the revocation/verification evidence predicates. | Concurrent/corrupt family change can evade identity comparison; evidence from a different family can satisfy a gate. | Include family in identity comparison and evidence matching; add a family-mutation test. |
| F-05 | Low | Idempotency request digest excludes the compiled body and several request fields. | Same-key different-body request receives a cached success; no different execution occurs, but the response is misleading. | Bind the canonical compiled body and relevant fields, or require and verify a trusted canonical digest; document the residual. |
| F-06 | Low | Already-`REVOKED` records return success without requiring evidence; reconciliation also accepts them. | A corrupt/migrated terminal record is trusted without the stated evidence gate. | Require matching revocation evidence before `already_revoked` success, or classify a missing-evidence `REVOKED` record as uncertain/corrupt. |
| F-07 | Low | Digest/ID regexes with `$` accept a trailing newline. | “Exact” format is not exact; downstream canonicalization may disagree. | Use `fullmatch`/`\Z` for both controller and helper validators; add boundary tests. |
| F-08 | Low / informational | `StrictAuthorizationProvider` treats an explicitly empty controller operation allowlist as the full default set. | Controller operation least privilege is not fail-closed if an empty set is supplied. | Use `is None` for the default and preserve empty as deny; add a test if controller operation policy is in scope. |
| F-09 | Low | Idempotency replay does not compare the stored ownership record ID; replay with omitted optional fields can pass after ownership changes. | A stale cached success can be returned under the same peer identity. No helper execution occurs. | Compare idempotency `ownership_record_id` (and family/state as appropriate) to fresh ownership before replay; add a regression test. |

No critical or high-severity privilege-escalation finding was identified in the inspected mock
scope. F-01 and F-02 are the material conditions for this review.

## 6. Verified positive controls

- Authoritative ownership is loaded from persistence, not from caller metadata, for all non-health
  operations.
- Helper requests for install/inspect/verify/revoke/remove/reconciliation are stamped from the
  persisted ownership record.
- Evidence is built from persisted ownership values; backend verify output cannot spoof ownership
  fields in the tested path.
- Normal revoke requires backend read-back and persisted evidence before `REVOKED`.
- A backend revoke failure, timeout, uncertain outcome, or read-back failure never produces
  `REVOKED`.
- Lifecycle CAS rejects stale state/version transitions; concurrent revoke tests converge.
- Read-side `BrokerDBError` is propagated instead of being treated as absence.
- Missing/empty helper allowlists deny all operations; unknown helper methods are rejected.
- ID-06 is documented as a heuristic data validator, not a parser or execution-safety boundary.

## 7. Remaining real-boundary gates

The following remain outside this mock-only review and block live integration:

- real UDS/transport identity and kernel-authenticated `SO_PEERCRED` equivalent;
- privileged helper process model, capabilities, privilege separation, and supervision;
- real firewall backend read-back, digest provenance, and canonical compiled-policy parser;
- real conntrack/state cleanup and revocation semantics;
- systemd/unit/host permissions and provisioning;
- crash/restart behavior for a real helper process;
- lost-response, partial-apply, duplicate-side-effect, and cross-process recovery behavior;
- production/cloud database and migration changes.

**Final gate: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.**
