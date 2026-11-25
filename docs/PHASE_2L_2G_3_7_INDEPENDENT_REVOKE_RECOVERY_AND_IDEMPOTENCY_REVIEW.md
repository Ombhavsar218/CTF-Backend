# Phase 2L.2G.3.7 — Independent Revoke Recovery and Idempotency Security Review

**Scope:** local mock-only controller / persistence / authorization / helper-boundary review  
**Date:** 2026-11-07 (review; finalized 2026-11-09)  
**Reviewed remediation:** `docs/PHASE_2L_2G_3_6_REVOKE_RECOVERY_AND_IDEMPOTENCY_HARDENING.md`  
**Base review:** `docs/PHASE_2L_2G_3_5_INDEPENDENT_OWNERSHIP_AND_REVOKE_SECURITY_REVIEW.md`  
**Mode:** independent, read-only; no source or test modifications authorized or performed.

> **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
>
> This review covers controller, persistence, authorization, and mock-helper behavior only. It
> does not authorize or validate a real transport, UDS/`SO_PEERCRED`, privileged helper,
> sudo/capabilities, nftables/iptables/UFW/Docker firewall changes, routing/NAT/conntrack
> changes, systemd/host permission changes, live provisioning, or production/cloud database
> changes. No real host or firewall change was made.

---

## 1. Executive decision

| Decision layer | Result |
|---|---|
| Local mock-only 2L.2G.3.6 remediation of F-01 through F-09 | **PASS** |
| Live transport / privileged helper / live firewall readiness | **NOT READY — NOT AUTHORIZED** |

The material conditions from 2L.2G.3.5 are verified closed in mock scope:

- **F-01** — same-key uncertain revoke retry now performs read-back recovery, does not re-issue a
  destructive operation after a confirmed successful revoke, and re-issues only after read-back
  proves the backend still holds the policy.
- **F-02** — reconciliation no longer treats a per-record persistence write failure as an ordinary
  uncertain result or as success; it emits sanitized `PERSISTENCE_FAILURE` entries and a top-level
  `status: error` / `RECONCILIATION_PERSISTENCE_FAILURE`, while preserving unrelated records.
- **F-03 through F-09** — the original 3.5 defects are fixed for the mock boundaries inspected:
  unknown lifecycle values fail closed, family is bound into ownership/evidence/idempotency,
  the canonical digest is complete and type-preserving, `REVOKED` requires matching evidence,
  the identifier/digest regexes are exact, the explicit-empty operation allowlist denies all,
  and replay checks the stored ownership record ID, resource key, and ownership snapshot.

This is **not a zero-finding review**. Three new, non-material residuals were found and
reproduced in the mock:

| ID | Severity | Area | Summary |
|---|---|---|---|
| R-01 | Low | F-02 persistence propagation | The install-failure path at `controller_service.py:851-869` still swallows `BrokerDBError` raised by the `FAILED` transition/history write. |
| R-02 | Low | F-07 identifier validation | Controller/pre-persistence identifier validation is not strict: malformed `policy_id` is persisted before the helper rejects it, and malformed `instance_id`/`network_id` is accepted end-to-end. |
| R-03 | Low | F-09 replay binding | An empty/NULL stored `request_digest` skips the peer-identity digest comparison, allowing a cached response to be disclosed to a different authorized peer if the idempotency row is corrupt or migrated empty. |

These residuals do **not** reopen the original F-01–F-09 defects and do not produce a false
`ACTIVE`/`REVOKED` security state in the inspected mock paths. They should be scheduled before
live integration or before a future zero-finding implementation gate. If the governance standard
requires zero open Low findings for a PASS, the correct decision would be **CONDITIONAL**; under
the stated definition — PASS means the inspected mock-only remediation of F-01–F-09 is
satisfactory — the decision is **PASS with non-blocking residuals**.

**Explicit closure statement:** F-01, F-02 (the original reconciliation defect), F-03, F-04,
F-05, F-06, F-07 (the original regex/`$` defect), F-08, and F-09 (the original stored-ownership-ID
binding defect) are **verified closed in mock scope**. No original F-01–F-09 finding remains open.
The real-transport and live-host aspects of all nine **cannot be independently verified** and
remain blocked.

---

## 2. Scope, constraints, and independence

### 2.1 In scope

- `broker/firewall_controller_service/controller_service.py`
- `broker/firewall_controller_service/ownership_store.py`
- `broker/firewall_controller_service/authorization_strict.py`
- `broker/firewall_controller_service/authorization.py`
- `broker/firewall_controller_service/helper_contract.py`
- `broker/firewall_controller_service/helper_authorization.py`
- `broker/firewall_controller_service/mock_helper_executor.py`
- `broker/firewall_controller_service/mock_backend.py`
- `broker/firewall_controller_service/mock_transport.py`
- `broker/firewall_controller_service/peer_identity.py`
- `broker/app/firewall_controller_contract.py`
- `broker/app/firewall_controller.py`
- `broker/app/db.py`
- `broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py`
- Existing ownership-binding, revoke-lifecycle, persistence/recovery, crash-boundary,
  cross-process, helper-contract, helper-identity, and lifecycle-idempotency suites.
- `docs/PHASE_2L_2G_3_5_INDEPENDENT_OWNERSHIP_AND_REVOKE_SECURITY_REVIEW.md`
- `docs/PHASE_2L_2G_3_6_REVOKE_RECOVERY_AND_IDEMPOTENCY_HARDENING.md`

### 2.2 Explicitly out of scope / not authorized

- Real transport, UDS, `SO_PEERCRED`, or any kernel-authenticated peer credential mechanism.
- A real privileged helper, sudo, capabilities, process supervision, or real crash modes.
- Any nftables, iptables, UFW, Docker, routing, NAT, conntrack, or live firewall change.
- systemd/host permission changes, live provisioning, or production/cloud database changes.
- Any source or test modification. The only file created by this phase is this review document.

### 2.3 Independence

The review was performed against the actual implementation and existing tests, not against the
3.6 report's claims or test counts alone. The 3.6 report was used only to identify the claimed
guarantees and to check whether the implementation matches them. Passing tests were treated as
evidence of behavior, not as proof of completeness.

### 2.4 Mock threat assumptions

Findings are evaluated under these assumptions:

- The caller is an authorized broker identity (allowlisted UID/GID) but may send malformed or
  adversarial request data.
- The controller is the security boundary; the helper is a separate mock boundary and must not
  derive identity or authority from request JSON.
- The SQLite controller database is local persistence. Direct database corruption, migration,
  or external modification is a valid fail-closed test case where the review says so.
- A real backend, real helper, and real peer credentials are not present and cannot be proven by
  this review.

---

## 3. Actual call paths inspected

### 3.1 Main controller dispatch

`FirewallControllerService._call` (`controller_service.py:516-967`) executes in this order:

1. Copy the request, audit `request_received`.
2. Authorize (`StrictAuthorizationProvider.authorize` by default) before any replay or side effect.
3. Validate via `RequestValidator.validate`, which delegates to
   `broker/app/firewall_controller_contract._validate_request`.
4. Compute the canonical request digest with `_req_digest` (operation plus the 20 security-relevant
   fields at `controller_service.py:127-133`).
5. Look up the durable idempotency record and reject a same-key/different-digest conflict.
6. Resolve the authoritative ownership record with `get_by_policy` and validate the caller
   metadata through `_validate_ownership_binding`.
7. For a new key, create a `PENDING` idempotency record; for an existing key, classify it with
   `_idempotency_replay_decision`.
8. Persist first-install intent (`REQUESTED`) or revalidate an existing record before backend
   execution.
9. For revoke, handle `REVOKED`/`REVOKING` recovery, read-back, and confirmed re-issue.
10. Dispatch to the backend with ownership fields derived from persistence via
    `_authoritative_request`.
11. Apply lifecycle transitions with CAS (`update_ownership_state` checks `lifecycle_version`).
12. Complete the durable idempotency record with the response and ownership snapshot.

Authorization, validation, ownership resolution, and replay binding happen before a cached
response is disclosed. This ordering is correct in the inspected paths.

### 3.2 Idempotency replay decision

`_idempotency_replay_decision` (`controller_service.py:488-514`):

- Reads the stored `request_digest`.
- Raises `FirewallControllerIdempotencyError` when a non-empty stored digest differs from the
  current digest.
- Loads a `COMPLETED` `response_json`; malformed JSON is rejected.
- For a cached revoke response that is uncertain/error, returns `recover` after `_validate_replay`.
- For other cached success responses, returns `return` after `_validate_replay`.
- Returns `pending` for a `PENDING` record.

The empty-digest edge case is reported as **R-03**.

### 3.3 Replay binding

`_validate_replay` (`controller_service.py:277-317`):

1. Re-resolves the current authoritative ownership record.
2. Calls `_validate_ownership_binding` against the fresh record.
3. Requires the stored `ownership_record_id` to equal the fresh record ID.
4. Requires the stored `resource_key` (when present) to equal
   `policy_id:policy_version`.
5. When `recovery_meta_json` is present, parses it, requires the stored ownership-identity tuple
   to equal the fresh tuple, and rejects malformed metadata.

Older records without `recovery_meta_json` fall back to the request digest, stored ownership ID,
and resource key. That fallback is documented and acceptable for the mock, provided the stored
request digest is valid; the empty-digest case is **R-03**.

### 3.4 Same-key revoke recovery

The revoke path (`controller_service.py:722-816`, `_read_back_revoke` at `373-394`,
`_complete_revoke` at `426-470`):

- A retry in `REVOKING` does not transition `REVOKING -> REVOKING`; it re-reads and revalidates.
- `_read_back_revoke` builds a fresh read-back request from authoritative ownership and uses fresh
  request/operation/idempotency identifiers.
- Backend state `missing`/`revoked` → confirmed; the cached response is not blindly replayed.
- Backend state `installed`/`present` → `backend_still_present`; the controller re-issues with a
  **fresh helper idempotency key** while the controller-level key remains unchanged.
- Unknown read-back state or a backend exception → `REVOKE_UNCONFIRMED`, no duplicate destructive
  call, state stays `REVOKING`.
- `_complete_revoke` re-reads the latest record, revalidates binding and ownership identity,
  stores revocation evidence **before** the `REVOKING -> REVOKED` CAS, then records lifecycle
  history.
- If the CAS loses to a concurrent winner, the fallback accepts only a terminal `REVOKED` record
  with matching evidence. The fallback does not re-check the full identity tuple; this is
  informational **I-04** because it requires a concurrent direct database replacement, which the
  unique index and CAS normally prevent.

### 3.5 Reconciliation

`reconcile_pending_operations` (`controller_service.py:991-1299`):

- Authorizes and validates before reading ownership.
- Resolves a specific policy or enumerates ownership records.
- Validates each persisted record through `_validate_ownership_binding` before using it to drive
  an action.
- Unknown lifecycle values → `corrupt_ownership_state`, audit best-effort, mark reconciliation
  uncertain where possible, no rewrite or adoption.
- Backend read-back failure is surfaced as `uncertain`, not as absence.
- `VERIFIED` promotes to `ACTIVE` only with matching verification evidence.
- `ACTIVE` is reported `active_ok` only when the backend read-back says `installed`; otherwise
  uncertain.
- `REQUESTED`/`INSTALLING`/`VALIDATING` with backend `installed` → `INSTALLING`/needs
  verification, never `ACTIVE` without evidence; with backend `missing` → `FAILED`.
- `REVOKING` with backend absent/revoked → evidence before `REVOKED`; with backend present →
  `partial_revoke_backend_still_present`, no duplicate side effect.
- `REVOKED` without evidence → `revoked_without_valid_evidence`, no silent repair.
- Per-record persistence writes that raise `BrokerDBError` are converted to sanitized
  `PERSISTENCE_FAILURE` entries; the top-level result becomes `status: error` with
  `RECONCILIATION_PERSISTENCE_FAILURE`.
- Top-level ownership/idempotency read failures propagate as `BrokerDBError` and are not
  converted to absence.

### 3.6 Persistence layer

`ControllerOwnershipStore` (`ownership_store.py`):

- `create_ownership` uses `BEGIN IMMEDIATE` and a unique `(policy_id, policy_version)` index.
- `update_ownership_state` uses CAS on `installation_state` and `lifecycle_version` and raises
  `PermissionError('LIFECYCLE_VERSION_CONFLICT')` on a lost race; genuine database errors surface
  as `BrokerDBError`.
- `store_evidence` is transactional and raises `BrokerDBError` on failure.
- `record_lifecycle_transition` raises `BrokerDBError` on failure.
- `complete_idempotency_record` uses `COALESCE` so a missing ownership ID or recovery metadata
  does not erase an existing value.
- `_query_dicts` propagates database read failures; absence is represented only by `None` or an
  empty list.
- The idempotency schema has `request_digest TEXT NOT NULL` but **no** length/format `CHECK`
  constraint. This is relevant to **R-03**.

### 3.7 Helper boundary

`MockFirewallBackend` (`mock_backend.py:55-79`):

- `_prep` strips `peer_uid`, `peer_gid`, and every forbidden auth-claim field before the helper
  call, and stamps the exact `SCHEMA_VERSION`.
- `_dispatch` obtains the helper identity from an explicitly injected provider per request; there
  is no implicit default identity, and an unavailable provider returns `None` and fails closed.
- The default backend has empty helper allowlists and therefore denies all helper operations
  unless a test or deployment explicitly injects an authorization policy and identity provider.

`MockHelperExecutor` (`mock_helper_executor.py`):

- Authorizes the separate helper identity before contract validation and execution.
- `validate_helper_request` rejects forbidden auth claims, unknown fields, invalid schema
  versions, conflicting operation values, invalid identifiers, invalid digests, invalid
  CIDR/protocol/port values, oversized request/compiled payloads, and invalid compiled-policy
  shapes.
- The helper idempotency key includes operation, idempotency key, policy ID, policy version, and
  digest.
- Only definitive successful responses are cached; failure/uncertain/timeout responses are not
  cached. This is what permits the controller's confirmed re-issue to reach the backend again.
- `instance_id` and `network_id` are allowed fields but are **not** validated by `_validate_id`;
  this is part of **R-02**.

### 3.8 Authorization

`StrictAuthorizationProvider` (`authorization_strict.py`):

- `allowed_uids=None` / `allowed_gids=None` → empty set (deny all).
- `allowed_operations=None` → documented fixed supported-operation default.
- Explicit `set()` → deny all; it is never broadened back to the default.
- A partial or complete operation set is used exactly as supplied.
- Missing/non-numeric peer UID/GID, unauthorized UID/GID, and disallowed operations fail closed.
- The `caller_trusted`/`verified`/`trusted`/etc. rejection is bypassable when the caller also
  supplies `controller_verified=True`; the flag is not used for authorization, so this is
  informational **I-01**, not a privilege escalation in the inspected mock.

The legacy `MockAuthorizationProvider` is reachable only through `strict_auth=False`; no
repository caller or test uses that option. It is an explicit insecure legacy path and is
informational **I-09**.

### 3.9 Contract validator

`_validate_request` (`firewall_controller_contract.py:52-72`) requires the six core fields,
requires `policy_version` to be an integer, and requires `compiled_rule_digest` to have at least
16 characters. It does not enforce the 64-hex digest format, identifier formats, or the
`instance_id`/`network_id` character set. The controller service's strict ownership binding
rejects an invalid digest for every non-health operation, so this weak validator is not a
service-level digest bypass; it remains a defense-in-depth gap and is informational **I-07**.

---

## 4. Finding-by-finding assessment

### 4.1 F-01 — Same-key uncertain revoke retry

**3.5 defect:** A cached backend failure/timeout could prevent a same-key retry from recovering;
a retry might re-issue a destructive revoke after the backend had already applied it, or trust a
stale success.

**Implementation inspected:**

- `_response_is_uncertain` treats any non-`ok` revoke response, and any response whose result has
  `revocation_confirmed: false`, as uncertain.
- `_idempotency_replay_decision` returns `recover` for an uncertain cached revoke response and
  still calls `_validate_replay` before recovery.
- The `REVOKING` retry path re-reads the authoritative record, revalidates binding and identity,
  and does not transition `REVOKING -> REVOKING`.
- `_read_back_revoke` returns `confirmed` for `missing`/`revoked`, `backend_still_present` for
  `installed`/`present`/`active`/`ok`, and uncertainty for errors/unknown values.
- Confirmed absence stores evidence and promotes `REVOKING -> REVOKED`; confirmed presence
  re-issues with a fresh helper idempotency key; uncertainty returns `REVOKE_UNCONFIRMED` with no
  state change and no duplicate revoke.
- A cached revoke error is not blindly returned; the read-back decides.
- A leftover `PENDING` revoke idempotency record is recoverable after the existing wait loop via
  `_validate_replay` and the recovery path.

**Evidence:**

- New suite F-01 tests: backend failure then read-back recovery; lost response after backend
  success with no duplicate destructive call; read-back failure stays uncertain; lifecycle
  persistence failure after evidence; backend still present re-issues; persistent recovery;
  concurrent same-key revoke; terminal `REVOKED` with evidence.
- Read-only probe P3/P4 are not F-01; they are R-03/R-01.
- Required existing lifecycle/recovery and cross-process suites pass.

**Status: VERIFIED CLOSED in mock scope.**

**Residual:** No explicit cross-process same-key revoke recovery test was found; the durable store
and the same code path are used, and the existing cross-process crash tests pass, but this
specific restart scenario is not directly exercised. This is coverage note **I-06**.

**Real transport/host validation required for live claim:** Yes. Real backend read-back,
lost-response semantics, partial apply, conntrack, and helper retry behavior are not validated.

---

### 4.2 F-02 — Persistence failure is not an uncertain outcome

**3.5 defect:** Reconciliation swallowed `BrokerDBError` and returned `status: ok`, masking a
persistence failure as an ordinary uncertain/absent outcome.

**Implementation inspected:**

- Reconciliation wraps per-record security-state and reconciliation-status writes in
  `except BrokerDBError` handlers that call `mark_persistence_failure` and continue processing
  other records (`controller_service.py:1031-1276`).
- `mark_persistence_failure` appends a sanitized `{'policy_id': ..., 'error_code':
  'PERSISTENCE_FAILURE'}` entry and sets a flag; the top-level result becomes `status: error`
  with `error_code: RECONCILIATION_PERSISTENCE_FAILURE` (`controller_service.py:1014-1019,
  1288-1299`).
- Top-level ownership/idempotency reads are not caught; `BrokerDBError` propagates and is never
  converted to absence.
- Evidence is stored before `REVOKED` promotion; a failed evidence write prevents promotion.
- A failed lifecycle history write propagates in the normal revoke/verify paths and leaves the
  idempotency record `PENDING`, so a same-key retry can recover.
- Best-effort audit writes are swallowed only on audit-only paths.

**Evidence:**

- New suite F-02 tests: reconciliation evidence failure; lifecycle failure; reconciliation-status
  failure; top-level read failure returning sanitized error while preserving other records;
  retry after database restoration; idempotency response persistence failure not masked.
- Existing persistence-failure-closure suite passes.
- Read-only probe P4 found the install-failure residual **R-01**.

**Status: VERIFIED CLOSED for the original reconciliation defect.**

**Residual:** **R-01** — the install backend-failure path at `controller_service.py:851-869`
still uses `except Exception: pass` around the `FAILED` transition and lifecycle history write.
A `BrokerDBError` there is swallowed; the operation returns the backend error, the ownership
record stays `REQUESTED`, and the idempotency record is completed with the error. This does not
produce a false `ok` or a false `ACTIVE`/`REVOKED`, but it contradicts the 3.6 report's section 6
claim that every ownership state-update `BrokerDBError` propagates and that security-state writes
are not swallowed.

**Real transport/host validation required for live claim:** No to reproduce in the mock; real
database durability/locking behavior still needs validation before a live claim.

---

### 4.3 F-03 — Unknown lifecycle values fail closed

**3.5 defect:** An unknown lifecycle value could be treated as a valid state, guessed, or
rewritten.

**Implementation inspected:**

- `known_states = set(LIFECYCLE_TRANSITIONS)`; a state not in that set produces
  `corrupt_ownership_state`, is audited best-effort, is marked reconciliation-uncertain where
  possible, and is never rewritten or adopted (`controller_service.py:1062-1078`).
- Unrelated records continue through the loop.
- Unknown backend states are reported uncertain; no action is taken.
- A corrupt ownership binding is caught before any backend action and reported as
  `corrupt_ownership_record`.
- `REVOKED` without evidence and `VERIFIED` without evidence are not silently repaired.

**Evidence:**

- New suite F-03 tests: unknown lifecycle state not rewritten; mixed unknown/valid records;
  unknown backend state; no adoption.
- Existing persistence-failure and persistent-recovery tests pass.

**Status: VERIFIED CLOSED in mock scope.**

**Real transport/host validation required for live claim:** No for the mock state machine; a real
backend's inspection vocabulary must be mapped explicitly before live use.

---

### 4.4 F-04 — Family-inclusive ownership identity

**3.5 defect:** Address family was not consistently bound into ownership identity, evidence, or
idempotency, allowing an IPv4/IPv6 substitution.

**Implementation inspected:**

- `_ownership_identity` includes `ownership_record_id`, policy ID, policy version, instance ID,
  network ID, canonical digest, and the authoritative family (`controller_service.py:82-95`).
- `_validate_ownership_binding` compares the caller's `address_family` and first
  `required_families` value against the authoritative family, and rejects family mismatches
  (`controller_service.py:239-253`).
- `_authoritative_request` overwrites caller family fields with the authoritative family before
  backend dispatch (`controller_service.py:256-275`).
- `_store_verification_evidence` and `_store_revocation_evidence` persist the authoritative
  family.
- `_has_revocation_evidence` compares family.
- Reconciliation inspects and promotes using the authoritative family.
- The request digest includes `address_family` and `required_families`.

**Evidence:**

- New suite F-04 tests: cross-family spoof rejection for inspect, verify, revoke, and remove;
  required-family mismatch; persisted-family mutation; cross-family evidence rejected.
- Read-only probes did not find a cross-family bypass in the controller/helper path.

**Status: VERIFIED CLOSED in mock scope.**

**Residual (informational I-03):** On first install, family is taken from the caller or defaults to
`ipv4`; the controller does not infer family from the opaque `compiled` body. The compiled body is
a data blob whose safety and family semantics are compiler/real-backend responsibilities. This is
a provenance limitation, not a replay substitution in the inspected mock.

**Real transport/host validation required for live claim:** Yes. A real compiler/helper must
prove the family and parse the compiled payload.

---

### 4.5 F-05 — Complete canonical idempotency digest

**3.5 defect:** The digest did not cover the full compiled body, ownership identity, family,
CIDRs, protocols, ports, or peer identity, allowing same-key different-payload collisions.

**Implementation inspected:**

- `_DIGEST_FIELDS` includes policy ID/version, both digests, the full `compiled` body, instance,
  network, address family, required families, ownership reference/record ID, expected ownership
  identity, `ip_cidr`, source/destination CIDR, protocol, port, ports, and `peer_uid`/`peer_gid`
  (`controller_service.py:126-133`).
- `_canonicalize` is type-preserving: `None`, `bool`, `str`, `int`, finite `float`, recursively
  canonicalized lists, and string-keyed dicts. It rejects tuples, sets, bytes, arbitrary objects,
  non-string keys, non-finite floats, and depth beyond 64.
- Serialization is deterministic (`sort_keys=True`, compact separators, `ensure_ascii=True`,
  `allow_nan=False`).
- The digest includes `operation`; different operations use separate idempotency scopes.
- A same key with a different digest is rejected before ownership resolution or backend execution.
- The digest is explicitly documented as payload identity, not policy-safety proof.

**Evidence:**

- New suite F-05 tests: same body replays; changed compiled body conflicts; nested compiled change
  conflicts; six changed security fields conflict; different operation uses a separate scope;
  restart replay; unsupported types rejected.
- Required helper-contract and lifecycle-idempotency suites pass.

**Status: VERIFIED CLOSED in mock scope.**

**Residual (informational I-03):** The controller does not recompute a hash of `compiled` and
compare it to `compiled_rule_digest`; digest provenance remains compiler trust. The 3.6 report
explicitly documents this limitation.

**Real transport/host validation required for live claim:** Yes for policy-safety/parser proof;
no for the mock payload-identity guarantee.

---

### 4.6 F-06 — `REVOKED` evidence verification

**3.5 defect:** A terminal `REVOKED` state could be accepted without matching evidence, or
mismatched/stale evidence could satisfy the gate.

**Implementation inspected:**

- `_has_revocation_evidence` requires `verification_result == 'revoked'`, matching ownership
  record ID, policy ID, policy version, canonical digest, instance ID, network ID, and address
  family (`controller_service.py:357-371`).
- The gate is enforced in the already-`REVOKED` dispatch path, in `_complete_revoke` when a
  concurrent winner has already promoted the record, and in reconciliation for `REVOKED` and
  `REVOKING`.
- Missing/corrupt/mismatched evidence raises `PermissionError` or produces
  `revoked_without_valid_evidence`.
- Evidence is stored before `REVOKING -> REVOKED`; there is no silent repair or synthesis.
- A valid repeated revoke returns `already_revoked: true`.

**Evidence:**

- New suite F-06 tests: revoked without evidence rejected; mismatched digest rejected; wrong
  family rejected; valid evidence idempotent; reconciliation variants; no silent repair.
- Read-only probe P8 confirmed the gate accepts a matching evidence row even when its
  `controller_identity` is foreign (informational I-02).

**Status: VERIFIED CLOSED for the specified ownership/policy/version/digest/instance/network/
family gate.**

**Residual (informational I-02):** The evidence predicate does not bind `controller_identity`,
`controller_transaction_id`, a lifecycle version, or a cryptographic integrity tag. It is a
database-row trust predicate. This is acceptable for the mock but must be re-evaluated when
multiple controllers or a real durable helper are introduced.

**Real transport/host validation required for live claim:** Yes for multi-controller/helper
durability and evidence integrity.

---

### 4.7 F-07 — Strict identifier and digest validation

**3.5 defect:** `_DIGEST_RE`/`_ID_RE` used `re.match` with `$`, which matches before a trailing
newline; identifiers/digests were not exact.

**Implementation inspected:**

- `controller_service.py:29` uses `_DIGEST_RE = re.compile(r"\A[a-fA-F0-9]{64}\Z")` and
  `.fullmatch` in `_validate_ownership_binding`.
- `helper_contract.py:30-31` uses `\A...\Z` for both `_DIGEST_RE` and `_ID_RE` and `.fullmatch`.
- The helper applies `_validate_id` to `request_id`, `operation_id`, `idempotency_key`,
  `policy_id`, and `ownership_reference`; `_validate_digest` to the compiled/canonical digest.
- The helper rejects forbidden auth claims, unknown fields, invalid schema versions, conflicting
  operation values, invalid CIDRs/protocols/ports, and oversized/deep compiled payloads.
- Read-only probe P7 confirmed the controller digest regex rejects a trailing newline with both
  `.fullmatch` and `.match`.

**Evidence:**

- New suite F-07 tests: helper rejects non-exact digests; accepts exact digests; rejects non-exact
  identifiers for `request_id`/`operation_id`/`idempotency_key`; accepts 1/128-character
  identifiers; controller rejects a trailing-newline digest and a non-hex stored digest.
- Read-only probes P1, P2, and P6 found the controller/pre-persistence residual **R-02**.

**Status: VERIFIED CLOSED for the original regex/`$` defect.**

**Residual:** **R-02** — the report's statement that "controller and helper validators now use
`_DIGEST_RE` and `_ID_RE`" is not accurate for the controller: the controller defines only
`_DIGEST_RE` and does not apply `_ID_RE` to any identifier. `_validate_ownership_binding` checks
`instance_id`/`network_id` only as strings and does not validate `policy_id`, `request_id`,
`operation_id`, or `idempotency_key` formats. The helper rejects a malformed `policy_id` only
after the controller has persisted a `FAILED` ownership record. The helper does not validate
`instance_id`/`network_id` at all, so a newline in those fields is accepted end-to-end. This is a
Low data-integrity/validation gap, not a privilege escalation. The legacy `_validate_request`
length-only digest check is a separate informational defense-in-depth gap (**I-07**).

**Real transport/host validation required for live claim:** No to reproduce; a real backend's
identifier semantics must be validated before live use.

---

### 4.8 F-08 — Allowlist semantics

**3.5 defect:** An explicit empty operation allowlist was indistinguishable from an omitted
allowlist and could be broadened back to the default set.

**Implementation inspected:**

- `StrictAuthorizationProvider.__init__` distinguishes `None` (documented supported-operation
  default) from `set()` (deny all) and from partial/complete sets
  (`authorization_strict.py:6-15`).
- Empty UID/GID allowlists deny all.
- Missing/non-numeric/unauthorized peer identity and disallowed operations fail closed.
- The controller service passes `allowed_operations` through unchanged.
- The helper's `MockHelperAuthorizationProvider` has its own fail-closed semantics: omitted or
  empty UID/GID/operation sets authorize nothing.

**Evidence:**

- New suite F-08 tests: `None` uses the documented default; explicit empty denies every
  operation; partial and complete sets match; service explicit-empty and omitted cases deny/allow
  as specified.
- Existing security-remediation tests pass.

**Status: VERIFIED CLOSED in mock scope.**

**Residuals (informational):**

- **I-01:** A caller that supplies `caller_trusted=True` together with
  `controller_verified=True` passes the strict provider's flag check
  (`authorization_strict.py:21-23`). The flags are not used for authorization, so this is not a
  privilege escalation, but the intended "never trust caller-supplied flags" check is
  bypassable. The helper boundary already rejects `controller_verified` as a forbidden field.
- **I-09:** `strict_auth=False` selects the legacy `MockAuthorizationProvider`, which authorizes
  any request with a valid dictionary and does not require peer identity. No repository caller or
  test uses it; the option remains a footgun and should be removed or gated as test-only.

**Real transport/host validation required for live claim:** Yes for real UID/GID credential
sourcing; no for the mock allowlist semantics.

---

### 4.9 F-09 — Replay binding

**3.5 defect:** A cached response could be replayed without proving that it was bound to the
current authoritative ownership record and resource.

**Implementation inspected:**

- `_validate_replay` re-resolves fresh authority, validates caller ownership metadata, checks the
  stored ownership record ID, checks the stored resource key, and checks the ownership-identity
  snapshot when present (`controller_service.py:277-317`).
- The request digest includes the authenticated `peer_uid`/`peer_gid`.
- Authorization, validation, ownership resolution, and replay checks precede cached-response
  disclosure.
- A different peer identity produces a different digest and is rejected when the stored digest is
  valid.
- A replaced ownership record produces a different stored-vs-fresh record ID and is rejected.
- An in-place instance/network/family mutation is rejected by the fresh binding and/or snapshot.
- A concurrent replay/ownership change is rejected or returns a validated cached response; the
  new suite includes a deterministic concurrent test.

**Evidence:**

- New suite F-09 tests: same identity/same ownership returns the cached response; different
  identity rejected; ownership record replacement rejected; in-place instance change rejected;
  family change rejected; concurrent replay/ownership change never returns stale success.
- Read-only probe P3 found the empty-stored-digest residual **R-03**.

**Status: VERIFIED CLOSED for the original stored-ownership-ID/resource/snapshot binding
defect.**

**Residual:** **R-03** — `_idempotency_replay_decision` and the `_call` pre-check only compare
the digest when `stored_digest` is truthy (`controller_service.py:500-502, 546-548`). If a
corrupt or migrated idempotency row has `request_digest=''` (the schema has no format/length
`CHECK`), the digest comparison is skipped. `_validate_replay` still checks the fresh ownership
record, stored ownership ID, resource key, and snapshot, but the snapshot does not include peer
identity. A different authorized peer can therefore receive the cached response. This requires a
corrupt/migrated row, not a normal caller path. It is Low but concrete and should be fixed by
treating any missing/empty/malformed stored digest as corrupt and failing closed.

**Real transport/host validation required for live claim:** No to reproduce; database migration
and integrity guarantees need separate validation.

---

## 5. New findings

### R-01 — Install backend-failure path swallows persistence errors

- **Severity:** Low.
- **File/function:** `broker/firewall_controller_service/controller_service.py`,
  `FirewallControllerService._call`, install failure branch at lines 851-869.
- **Concrete scenario:**
  1. An authorized caller installs a policy with a valid request.
  2. The backend returns a non-`ok` install response (for example `INSTALL_FAILED`).
  3. The controller attempts to persist `REQUESTED`/`VALIDATING`/`INSTALLING -> FAILED`.
  4. `update_ownership_state` or `record_lifecycle_transition` raises `BrokerDBError` (for
     example a transient `database is locked`).
  5. `except Exception: pass` swallows the error.
  6. `complete_idempotency_record` then succeeds and stores the backend error as a `COMPLETED`
     idempotency response.
- **Impact:** The database failure is not distinguishable to the caller; the ownership record
  stays in `REQUESTED` while the idempotency record says `COMPLETED` with an error. A same-key
  retry returns the cached error instead of retrying the failed transition. Reconciliation can
  recover the record (`REQUESTED` + backend missing → `FAILED`), and no false `ACTIVE`/`REVOKED`
  is produced. This is a reliability/error-visibility issue, not a security-boundary bypass.
- **Evidence:** Read-only probe P4: injected `BrokerDBError` on the `FAILED` transition after
  `backend.ctrl.fail_install = True`; result was `status: error / INSTALL_FAILED`, ownership
  state `REQUESTED`, idempotency status `COMPLETED`, cached response status `error`.
- **Contradiction:** The 3.6 report section 6 says "Ownership create / state update / lifecycle
  history write | `BrokerDBError` propagates; lifecycle transition does not occur" and
  "security state writes are not swallowed." This path is a security state write that is
  swallowed.
- **Required remediation:** Catch only `PermissionError` for the CAS-lost-race case (and then
  re-read/validate as appropriate); let `BrokerDBError` propagate. If the `FAILED` transition
  cannot be persisted, leave the idempotency record `PENDING` (or otherwise non-completed) so a
  same-key retry/reconciliation can recover. Add a fault-injection test that fails only
  `update_ownership_state(..., 'FAILED', ...)` after a backend install failure.
- **Real transport/host validation required:** No to reproduce in the mock; real database
  locking/durability behavior remains a live-validation item.

### R-02 — Controller/pre-persistence identifier validation is not strict

- **Severity:** Low.
- **File/function:** `controller_service.py:_validate_ownership_binding` (lines 183-254),
  `_call` first-install persistence (lines 666-693);
  `broker/app/firewall_controller_contract.py:_validate_request` (lines 52-72);
  `broker/firewall_controller_service/helper_contract.py:validate_helper_request` (lines
  197-212).
- **Concrete scenario A:** An authorized caller sends `policy_id='victim\n'` with a valid digest.
  `_validate_request` accepts it (only presence is checked). `_validate_ownership_binding` checks
  the digest, instance/network types, and family, but not the `policy_id` format. The controller
  creates an ownership record in `REQUESTED`, then the helper contract rejects the malformed
  `policy_id` with `INVALID_REQUEST`. The controller marks the ownership `FAILED`; the malformed
  record persists.
- **Concrete scenario B:** An authorized caller sends `instance_id='i1\n'` or
  `network_id='n1\n'`. The controller accepts it as a string, the helper contract does not
  validate `instance_id`/`network_id` as identifiers, and the policy installs with the malformed
  value stored in ownership.
- **Concrete scenario C:** The legacy `_validate_request` accepts a 16-character or otherwise
  invalid `compiled_rule_digest` because it checks only `len(str(...)) >= 16`. The controller
  service's strict `_validate_ownership_binding` rejects it for non-health operations, so this
  is not a service-level digest bypass, but any direct user of the legacy validator or the mock
  controller can install with a weak digest.
- **Impact:** Data-integrity and log/identity confusion; a malformed `policy_id` can create
  `FAILED` ownership records before rejection; a malformed `instance_id`/`network_id` is accepted
  end-to-end in the mock. No privilege escalation was found.
- **Evidence:** Probes P1, P2, P6, P9:
  - P1: `policy_id='victim\n'` → install `error / INVALID_REQUEST`; ownership created with state
    `FAILED`.
  - P2: `instance_id='i1\n'` → install `ok`; ownership state `INSTALLING`; stored instance ID
    `'i1\n'`.
  - P6: direct `MockFirewallController.install_policy` with a 16-character digest → `ok`;
    policy installed.
  - P9: the same 16-character digest through `FirewallControllerService` → `PermissionError:
    Invalid policy digest`; no ownership row. The service digest gate is therefore intact; the
    remaining R-02 gaps are malformed identifier formats (P1/P2), not the digest on first install.
- **Contradiction:** The 3.6 report's F-07 section says "Controller and helper validators now use
  `_DIGEST_RE` and `_ID_RE`." The controller has no `_ID_RE` usage. The detailed following
  sentence is accurate for the helper but not for the controller.
- **Required remediation:** Apply `_ID_RE.fullmatch` to `policy_id`, `request_id`,
  `operation_id`, `idempotency_key`, `ownership_reference`, `ownership_record_id`,
  `instance_id`, and `network_id` at the controller boundary before any ownership/idempotency
  persistence. Apply the same validation to `instance_id`/`network_id` in the helper contract.
  Update `_validate_request` to use the strict digest/identifier validators, or explicitly
  demote it to a non-security transport-shape check and ensure no path relies on it as the
  security boundary. Add regression tests for all malformed identifier fields.
- **Real transport/host validation required:** No to reproduce; real backend identifier
  semantics need validation before live use.

### R-03 — Empty stored request digest skips peer-identity replay binding

- **Severity:** Low.
- **File/function:** `controller_service.py:_idempotency_replay_decision` (lines 488-514) and
  `_call` pre-check (lines 540-548); `ownership_store.py` schema (lines 56-70).
- **Concrete scenario:**
  1. An authorized peer (UID/GID 1000) performs an `inspect_policy` request with idempotency key
     `K`; the response is cached and bound to the ownership record.
  2. The idempotency row is corrupted, migrated, or externally modified so
     `request_digest=''` (the column is `TEXT NOT NULL` but has no length/format `CHECK`).
  3. A different authorized peer (UID/GID 2000) sends the same request/key with the same
     policy/version/instance/network/digest/family but a different `peer_uid`/`peer_gid`.
  4. `_idempotency_replay_decision` sees a falsy `stored_digest` and skips the digest comparison;
     `_validate_replay` checks the ownership record, stored ownership ID, resource key, and
     snapshot, but the snapshot does not include peer identity.
  5. The cached response is returned to the different peer.
- **Impact:** The authenticated-peer binding is bypassed and a cached policy inspection response
  is disclosed to a different authorized peer. Both peers are authorized for the operation, and
  the trigger requires a corrupt/migrated row, so this is Low. It becomes more significant if
  idempotency rows are migrated, imported, or manually repaired without validation.
- **Evidence:** Probe P3: after setting `request_digest=''` on a completed `inspect_policy`
  record, the different-peer replay returned `status: ok` and was equal to the first response.
- **Required remediation:** Treat a missing, empty, or non-64-hex stored `request_digest` as a
  corrupt idempotency record and fail closed (raise
  `FirewallControllerIdempotencyError`/`PermissionError`) before disclosing any cached response.
  Add a database `CHECK` constraint or migration validation for the digest format. Add a
  regression test that mutates the digest empty/NULL and replays with a different peer.
- **Real transport/host validation required:** No to reproduce; database migration and
  integrity guarantees need separate validation.

---

## 6. Informational limitations and observations

### I-01 — Strict auth flag check is bypassable with caller-supplied `controller_verified`

`authorization_strict.py:21-23` rejects `caller_trusted`/`verified` only when
`controller_verified` is not `True`. A caller can supply both flags and pass the check. The flags
are not used for authorization, so there is no privilege escalation; the intended defense-in-depth
check is incomplete. The helper boundary already rejects `controller_verified` as a forbidden
field. Recommendation: reject all caller-supplied auth/verification flags unconditionally, or
remove the exemption. Evidence: probe P5 (`caller_trusted+controller_verified` authorized `True`;
`caller_trusted` alone raised `FirewallControllerAuthError`).

### I-02 — Revocation evidence is database-row trust, not integrity-bound

`_has_revocation_evidence` checks the ownership/policy/version/digest/instance/network/family
fields but not `controller_identity`, `controller_transaction_id`, a lifecycle version, or a
cryptographic tag. A matching evidence row with a foreign `controller_identity` satisfies the
gate. This requires direct database write and is acceptable for the single-controller mock, but a
multi-controller or real-helper deployment must define evidence integrity and controller binding.
Evidence: probe P8 (foreign-identity evidence accepted with `already_revoked: True`).

### I-03 — First-install family and digest provenance are caller/compiler trust

The controller derives family from the caller or defaults to `ipv4` on first install, and it does
not infer family or safety from the opaque `compiled` body. The digest binds the supplied digest
but does not prove the compiler produced it from a safe policy. This is explicitly documented in
the 3.6 report's "Digest provenance" and "compiled remains optional" limitations. A real
compiler/helper must supply and validate family and the compiled payload; no live policy-safety
claim is made.

### I-04 — `_complete_revoke` concurrent fallback does not re-check the identity tuple

In the `except PermissionError` branch (`controller_service.py:462-469`), the controller re-reads
the final record and accepts a `REVOKED` record with matching evidence, but does not compare the
final ownership-identity tuple with the `latest` record it was completing. The CAS and the unique
`(policy_id, policy_version)` index normally prevent a concurrent replacement, and the fallback
only accepts a terminal `REVOKED` with evidence. A direct database delete/recreate or external
replacement is required to exploit the gap. Recommendation: assert
`_ownership_identity(final) == _ownership_identity(latest)` before accepting the fallback.

### I-05 — Reconciliation `REVOKED` branch uses the target snapshot and does not mark status

The `state == 'REVOKED'` branch (`controller_service.py:1258-1276`) checks evidence against the
loop's `rec` rather than re-reading `cur` and calling `_assert_ownership_identity_unchanged`.
It also does not update `reconciliation_status` when evidence is missing (the unknown-state
branch does). A concurrent mutation during the backend inspect could produce a stale result; the
next reconciliation pass would catch it. This is a Low/observability concurrency note, not a
state-corruption path in the inspected mock.

### I-06 — Regression coverage gaps

The committed suite does not directly exercise:

- cross-process/restart same-key **revoke** recovery (install restart replay is covered);
- each F-05 CIDR/protocol/port field individually (the canonical payload includes them);
- helper `policy_id`/`ownership_reference` non-exact identifier cases (the helper code validates
  them, but the test list covers only `request_id`/`operation_id`/`idempotency_key`);
- an empty/NULL stored idempotency digest replay (R-03);
- the install backend-failure + `FAILED` transition `BrokerDBError` path (R-01);
- malformed controller `policy_id`/`instance_id`/`network_id` persistence (R-02).

The implementation paths exist and the required suites pass, but these edges are not
regression-protected.

### I-07 — Legacy contract validator remains weak

`_validate_request` accepts a 16-character/invalid digest and does not validate identifier
formats. The controller service's strict ownership binding prevents a digest bypass for every
non-health operation, and the helper contract is strict, so this is not a service-level bypass.
It should still be tightened or explicitly documented as a non-security transport-shape check.
Evidence: probe P6 shows the legacy validator/direct mock controller accepts a 16-character
digest; probe P9 shows the service rejects it before ownership creation with
`PermissionError: Invalid policy digest` and creates no ownership row.

### I-08 — Raw `BrokerDBError` messages include underlying database text

`ControllerOwnershipStore` wraps many exceptions as `BrokerDBError(f'Failed to ...: {e}')`, which
can include SQLite error text and paths. The controller `_call` re-raises these exceptions; the
mock transport does not sanitize them. No committed route rendering path was found in this review,
but a real transport/error mapper must convert storage errors to sanitized codes and keep
diagnostics internal. The reconciliation path already returns a sanitized
`PERSISTENCE_FAILURE` code. This is an informational live-integration item.

### I-09 — `strict_auth=False` legacy provider is a footgun

`FirewallControllerService(strict_auth=False)` selects `MockAuthorizationProvider`, which
authorizes any valid dictionary and does not require peer identity. No repository caller or test
uses it; the default is `strict_auth=True`. Recommendation: remove the option or gate it behind an
explicit test-only flag so a production wiring mistake cannot silently disable strict
authorization.

---

## 7. Failure-state and recovery analysis

| State/event | Observed behavior | Security assessment |
|---|---|---|
| Revoke backend failure/timeout | State stays `REVOKING`; cached error is uncertain; same-key retry reads back | Correct; no false `REVOKED` |
| Revoke applied, response lost | Read-back sees `missing`/`revoked`; evidence stored; no duplicate destructive call | Correct |
| Revoke read-back failure/unknown | `REVOKE_UNCONFIRMED`; state stays `REVOKING`; no backend re-issue | Correct fail-closed |
| Backend still present on retry | Read-back proves presence; re-issue with fresh helper idempotency key; controller key unchanged | Correct; documented |
| Lifecycle CAS lost to concurrent winner | Re-read; accept only terminal `REVOKED` with evidence; otherwise fail closed | Correct in normal paths; I-04 fallback identity note |
| Evidence write fails | No `REVOKED`/`ACTIVE` promotion; error propagates (normal paths) | Correct |
| Lifecycle history write fails | Error propagates; idempotency remains recoverable (normal paths) | Correct; R-01 install-failure exception |
| Idempotency completion fails | Error propagates; durable record remains `PENDING`; same-key retry recovers (revoke) | Correct |
| Reconciliation per-record write fails | Sanitized `PERSISTENCE_FAILURE`; top-level `status: error`; other records continue | Correct for the original F-02 defect |
| Reconciliation top-level read fails | `BrokerDBError` propagates; not treated as absence | Correct |
| Unknown lifecycle value | `corrupt_ownership_state`; no rewrite/adoption; uncertain where possible | Correct |
| `REVOKED` without evidence | `PermissionError` or `revoked_without_valid_evidence`; no repair | Correct |
| `VERIFIED` without evidence | Not promoted; `verified_without_valid_evidence` | Correct |
| `REVOKING` with backend present | `partial_revoke_backend_still_present`; no duplicate | Correct |
| Backend `installed` during install uncertainty | `INSTALLING`/needs verification, never `ACTIVE` without evidence | Correct |
| Backend `missing` during install uncertainty | `FAILED`; no auto-retry | Correct |
| Install backend failure + `FAILED` DB write failure | `except Exception: pass`; state `REQUESTED`; idempotency `COMPLETED` with error | **R-01** |
| Empty stored request digest + different peer | Digest comparison skipped; cached response disclosed | **R-03** |
| Malformed `policy_id`/`instance_id` | Persisted before/without strict controller ID validation | **R-02** |

---

## 8. Test results

All commands were run from `E:\Flag-hunt\ctf-platform-be` with the repository virtual environment.
No source or test file was modified.

### 8.1 New 2G.3.6 hardening suite

```powershell
.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py -q
```

**Result:** `96 passed, 1 warning in 41.53s`.

### 8.2 Required existing remediation, lifecycle, persistence, contract, and identity suites

```powershell
.\venv\Scripts\python.exe -m pytest `
  broker/tests/test_firewall_controller_ownership_binding_remediation.py `
  broker/tests/test_firewall_controller_revoke_lifecycle_remediation.py `
  broker/tests/test_firewall_controller_remediation_authorization_storage_allowlists.py `
  broker/tests/test_firewall_controller_persistent_recovery_integration.py `
  broker/tests/test_firewall_controller_persistence_failure_closure.py `
  broker/tests/test_firewall_controller_crash_boundary_instrumentation.py `
  broker/tests/test_firewall_controller_helper_contract.py `
  broker/tests/test_firewall_controller_helper_identity_propagation.py `
  broker/tests/test_firewall_controller_lifecycle_idempotency.py -q
```

**Result:** `193 passed, 1 warning in 64.14s (0:01:04)`.

### 8.3 Cross-process and crash-recovery suites

```powershell
.\venv\Scripts\python.exe -m pytest `
  broker/tests/test_firewall_controller_cross_process_crash_recovery.py `
  broker/tests/test_firewall_controller_cross_process_concurrency.py -q
```

**Result:** `10 passed, 1 warning in 8.93s`.

### 8.4 Full controller suite

```powershell
$files = Get-ChildItem broker/tests/test_firewall_controller*.py | ForEach-Object { $_.FullName }
.\venv\Scripts\python.exe -m pytest $files -q
```

**Result:** `343 passed, 1 warning in 124.57s (0:02:04)`.

### 8.5 Full Broker suite

```powershell
.\venv\Scripts\python.exe -m pytest broker/tests -q
```

**Result:** `446 passed, 1 warning in 151.18s (0:02:31)`.

### 8.6 Django manager-client tests

```powershell
.\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client
```

**Result:** `Ran 33 tests in 0.126s` — `OK`; `Found 33 test(s)`; system check identified no issues.

### 8.7 Django system check

```powershell
.\venv\Scripts\python.exe manage.py check
```

**Result:** `System check identified no issues (0 silenced).`

### 8.8 Warnings and failure distinction

- `PydanticDeprecatedSince20`: class-based `config` is deprecated. One per pytest run;
  pre-existing and unrelated to this phase.
- `PytestDeprecationWarning`: `asyncio_default_fixture_loop_scope` is unset. This is emitted to
  stderr; PowerShell may render it as a native-command error record or a nonzero wrapper exit
  code even when pytest reports zero failures. The authoritative pytest summary is
  `96/193/10/343/446 passed`, all with `0 failed`.
- No test failures, skips, xfails, or xpasses were observed in the required runs.
- The manager-client command and `manage.py check` both exited successfully.

### 8.9 Tests not executed / not independently verified

The following were not executed because they are outside the authorized mock-only scope:

- real transport, UDS, `SO_PEERCRED`, or any kernel-authenticated peer identity;
- real privileged helper, sudo, capabilities, supervision, or real crash modes;
- real nftables/iptables/UFW/Docker read-back, rule-handle semantics, conntrack, or partial-apply
  behavior;
- routing/NAT/conntrack changes;
- systemd/host permission changes, live provisioning, or production/cloud database changes.

Additionally, the coverage gaps in **I-06** mean the following mock edges are not directly
regression-tested even though the implementation paths exist: cross-process same-key revoke
recovery, individual F-05 CIDR/protocol/port fields, helper `policy_id`/`ownership_reference`
non-exact identifiers, empty stored digest replay, the install-failure DB-swallow path, and
malformed controller ID persistence.

---

## 9. Read-only adversarial probes

These probes were run as inline Python against temporary SQLite databases under the system temp
directory. They did not modify repository files, did not use a real transport, and did not make
host/firewall changes. They are evidence for the new findings, not committed tests.

| Probe | Scenario | Observed result | Finding |
|---|---|---|---|
| P1 | `policy_id='victim\n'`, valid digest | Install `error / INVALID_REQUEST`; ownership created with state `FAILED` | R-02 |
| P2 | `instance_id='i1\n'` | Install `ok`; ownership `INSTALLING`; stored instance ID `'i1\n'` | R-02 |
| P3 | Completed inspect record; set `request_digest=''`; replay same key as peer 2000 after peer 1000 | `status: ok`; response equal to the first peer's cached response | R-03 |
| P4 | Backend `fail_install=True`; inject `BrokerDBError` on `FAILED` transition | Install `error / INSTALL_FAILED`; ownership `REQUESTED`; idempotency `COMPLETED` with `error` | R-01 |
| P5 | `caller_trusted=True` plus `controller_verified=True` | Authorized `True`; `caller_trusted` alone raised `FirewallControllerAuthError` | I-01 |
| P6 | Direct `MockFirewallController.install_policy` with 16-character digest | `ok`; policy installed | I-07 |
| P7 | `_DIGEST_RE.fullmatch('a'*64 + '\n')` and `.match(...)` | Both `False` | F-07 closed |
| P8 | `REVOKED` evidence with foreign `controller_identity` but matching ownership fields | `already_revoked: True` accepted | I-02 |
| P9 | First-install 16-character digest through `FirewallControllerService` | `PermissionError: Invalid policy digest`; no ownership record created | F-07 / I-07 |

Probe P1/P2 use an authorized mock caller and the mock helper; they do not prove real backend
behavior. Probe P3/P8 require direct database modification. Probe P4 requires both a backend
failure and a database failure. Probe P5/P6 are defense-in-depth checks. Probe P9 confirms the
service-level first-install digest gate.

---

## 10. Remaining real-transport and host-validation limitations

The following remain **NOT READY** and require separate authorization and a real validation
phase:

1. **No real transport or kernel-authenticated peer identity.** `peer_uid`/`peer_gid` are
   caller/test inputs in the mock; UDS/`SO_PEERCRED` is not implemented.
2. **No privileged helper.** Capability separation, supervision, crash modes, process-level
   timeout enforcement, and helper-side durable ownership/idempotency binding are future work.
3. **Mock backend fidelity.** Real nftables/iptables read-back, rule-handle semantics, conntrack
   interaction, partial-apply behavior, and lost-response behavior must be validated against a
   real backend.
4. **Default backend is fail-closed mock.** Production wiring must inject a real backend; the
   default is not a live implementation.
5. **Timeout is validated, not enforced.** `timeout_ms` bounds are checked; wall-clock
   enforcement belongs to the future transport/process layer.
6. **Digest provenance and compiled-policy safety.** The controller binds the supplied digest but
   does not prove the compiler produced it from a safe policy. The compiled body is opaque data;
   the real helper must parse and validate it. ID-06 remains a documented heuristic-validator
   limitation, not a parser-level or execution-safety proof.
7. **First-install family provenance.** Family is caller-supplied or defaults to `ipv4`; the
   compiler/helper must prove it.
8. **Evidence integrity.** Evidence is database-row trust; a multi-controller or real-helper
   deployment needs controller/transaction binding or integrity protection.
9. **Error sanitization.** Raw `BrokerDBError` messages can contain database details; the real
   transport/error mapper must sanitize them.
10. **Database migration.** Empty/NULL idempotency digests and older records without
    `recovery_meta_json` must be validated or backfilled before live use.
11. **Reconciliation entry point.** The strict request validator requires
    `policy_id`/`policy_version`; the list-all branch is not reachable through the normal strict
    entry point.
12. **Fresh helper key on confirmed re-issue.** The controller deliberately uses a fresh
    helper-boundary idempotency key after read-back proves the previous attempt did not apply. A
    real helper must implement the same documented retry policy.

---

## 11. Implementation gate and authorization status

- **Source/test modification:** None. This phase is read-only. The only created file is this
  review document.
- **Local mock-only F-01–F-09 remediation:** PASS, subject to the non-blocking Low residuals
  R-01–R-03 and the informational items above.
- **Recommended follow-up:** Address R-01, R-02, and R-03 (and, at the project's discretion,
  I-01/I-04/I-05/I-06) in a separately authorized remediation phase before live integration or a
  zero-finding gate. None of the residuals was observed to create a false `ACTIVE`/`REVOKED`
  state in the inspected mock.
- **Live firewall integration:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.** No real
  transport, privileged helper, firewall, routing, host, provisioning, or production database
  change was made or authorized.
- **Next action:** Stop here and wait for separate approval. Do not begin real transport, helper,
  or live firewall work on the basis of this review.

---

## 12. Closure matrix

| Finding | Original 3.5 defect | 3.7 status | Basis / residual |
|---|---|---|---|
| F-01 | Same-key uncertain revoke retry | **Closed (mock)** | Read-back recovery, fresh-key re-issue only after confirmed presence, no duplicate destructive call, tests pass; I-06 cross-process revoke test gap |
| F-02 | Reconciliation swallowed `BrokerDBError` and returned `ok` | **Closed (mock)** | Per-record `PERSISTENCE_FAILURE`, top-level error, read failures propagate, tests pass; **R-01** install-failure path residual |
| F-03 | Unknown lifecycle value not fail-closed | **Closed (mock)** | Unknown state → uncertain, no rewrite/adoption; tests pass |
| F-04 | Family not bound into ownership/evidence | **Closed (mock)** | Family in identity, binding, evidence, digest, reconciliation; tests pass; I-03 provenance note |
| F-05 | Incomplete canonical digest | **Closed (mock)** | 20 fields including full compiled body and peer identity; canonicalization rejects ambiguous types; tests pass; I-03 provenance note |
| F-06 | `REVOKED` accepted without matching evidence | **Closed (mock)** | Evidence predicate checks ownership/policy/version/digest/instance/network/family; tests pass; I-02 evidence-integrity note |
| F-07 | `$` regex accepted trailing newline | **Closed (mock)** | Controller digest and helper ID/digest validators use `\A...\Z` + `fullmatch`; tests and probe P7 pass; **R-02** controller/pre-persistence ID validation residual; I-07 legacy validator |
| F-08 | Explicit-empty operation allowlist ambiguous | **Closed (mock)** | `None` default vs `set()` deny-all vs partial/complete; tests pass; I-01 flag-check note; I-09 legacy provider note |
| F-09 | Cached replay not bound to stored ownership/resource | **Closed (mock)** | Fresh ownership, stored ownership ID, resource key, snapshot; tests pass; **R-03** empty-digest residual |

**Cannot independently verify:** the real-transport, real-helper, real-backend, real-peer-credential,
and live-host aspects of all findings. Those remain out of scope and unauthorized.

---

*End of Phase 2L.2G.3.7 independent review. No live change was made. Work stops here pending
separate approval.*
