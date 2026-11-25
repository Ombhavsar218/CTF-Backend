# Phase 2L.2G.3.6 — Revoke Recovery and Idempotency Hardening

**Scope:** local mock-only controller/persistence/authorization/helper-contract remediation
**Date:** 2026-11-07
**Base review:** `docs/PHASE_2L_2G_3_5_INDEPENDENT_OWNERSHIP_AND_REVOKE_SECURITY_REVIEW.md`
**Prior remediation:** `docs/PHASE_2L_2G_3_4_OWNERSHIP_BINDING_AND_REVOKE_LIFECYCLE_REMEDIATION.md`

> **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
>
> This phase is local mock-code remediation only. It does not implement or authorize a real
> transport, UDS/`SO_PEERCRED`, privileged helper, sudo/capabilities, nftables/iptables/UFW/Docker
> firewall changes, routing/NAT/conntrack changes, systemd/host permission changes, live
> provisioning, or production/cloud database changes.

## 1. Decision

| Decision layer | Result |
|---|---|
| Local mock-only 2G.3.6 remediation of F-01 through F-09 | **PASS** |
| Real transport / privileged helper / live firewall readiness | **NOT READY — NOT AUTHORIZED** |

All nine findings from the 2G.3.5 independent review are remediated in the local mock scope and
covered by new regression tests. No existing assertion was weakened, and no coverage was reduced
to obtain a passing result. F-01 and F-02, the material conditions of the 2G.3.5 review, are
remediated and independently exercised by fault-injection tests.

## 2. Scope and constraints

In scope:

- controller revoke recovery, persistence error classification, ownership identity, idempotency
  digest, replay binding, and lifecycle corruption handling;
- controller operation allowlist semantics;
- helper contract identifier/digest validation;
- mock helper retry semantics required to exercise same-key controller recovery;
- local regression tests and this report.

Out of scope and not performed:

- no real firewall backend, helper, transport, kernel credential, routing, host, or provisioning
  changes;
- no production or cloud database changes;
- no unrelated feature changes.

## 3. Files changed

| File | Change |
|---|---|
| `broker/firewall_controller_service/controller_service.py` | Family-inclusive ownership identity; canonical idempotency digest; replay ownership/identity binding; same-key revoke recovery; revoked-evidence gates; reconciliation persistence-failure classification and unknown-state detection; fresh backend attempt key on confirmed re-issue. |
| `broker/firewall_controller_service/ownership_store.py` | `complete_idempotency_record` now persists `ownership_record_id` and a `recovery_meta_json` ownership-identity snapshot with `COALESCE` semantics. |
| `broker/firewall_controller_service/authorization_strict.py` | `None` operation allowlist means the documented fixed supported-operation default; an explicitly empty set denies every operation. |
| `broker/firewall_controller_service/helper_contract.py` | Identifier/digest regexes now use `\A...\Z` and `.fullmatch`; exact full-string format is enforced. |
| `broker/firewall_controller_service/mock_helper_executor.py` | Mock helper idempotency caches only definitive successful responses, so a transient failed attempt does not permanently pin the mock helper to a stale error. |
| `broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py` | New F-01 through F-09 regression suite (96 tests including parametrization). |

No real transport, privileged helper, firewall, routing, host, provisioning, or production
database file was created or modified.

## 4. Finding-by-finding remediation

| Finding | Severity (2G.3.5) | Disposition | Remediation summary |
|---|---|---|---|
| F-01 — same-key uncertain revoke retry returns cached error | Medium (mock recovery) | **Remediated** | Cached non-success/uncertain revoke outcomes and leftover `PENDING` revoke idempotency now enter read-back recovery instead of replaying the cached error. Recovery never blindly re-executes. |
| F-02 — reconciliation swallows `BrokerDBError` and returns `ok` | Medium (mock error visibility) | **Remediated** | Per-record persistence write failures are classified as sanitized `PERSISTENCE_FAILURE` entries and force a top-level `status: error` with `RECONCILIATION_PERSISTENCE_FAILURE`; top-level read failures still propagate. |
| F-03 — unknown lifecycle state silently ignored | Low | **Remediated** | Unknown persisted states are detected, audited where possible, marked `uncertain/corrupt_ownership_state`, and never adopted or rewritten. |
| F-04 — address family absent from identity/evidence | Low | **Remediated** | `address_family` is part of the ownership identity and every revocation/verification evidence predicate; caller family mismatch is rejected. |
| F-05 — idempotency digest omitted compiled body and fields | Low | **Remediated** | The digest covers the complete canonical compiled body plus operation, policy/version, ownership references, instance/network, address family, required families, CIDRs/protocol/ports, and authenticated peer identity. |
| F-06 — already-`REVOKED` trusted without evidence | Low | **Remediated** | Terminal `REVOKED` requires matching revocation evidence (ownership, policy, version, digest, instance, network, family). Missing/corrupt/mismatched evidence fails closed; valid repeats stay idempotent. |
| F-07 — `$` regex accepts trailing newline | Low | **Remediated** | Controller and helper validators use `\A...\Z` and `.fullmatch`; identifiers and digests must match exactly. |
| F-08 — explicit empty operation allowlist broadened to all | Low / informational | **Remediated** | `None` selects the documented fixed default; explicitly empty denies all; partial and complete sets behave as supplied. |
| F-09 — replay did not compare stored ownership ID/identity | Low | **Remediated** | Replay validates current peer identity through the digest, authoritative ownership, stored ownership record ID, resource binding, and the persisted ownership-identity snapshot before any cached disclosure. |

### 4.1 F-01 — same-key revoke recovery

`_response_is_uncertain` classifies a cached revoke response as uncertain when it is not `status:
ok` or when it explicitly carries `revocation_confirmed: false`. `_idempotency_replay_decision`
returns `recover` for such a record instead of `return`, and also treats a leftover `PENDING`
revoke record as recoverable after the existing bounded wait loop. Recovery runs only after
authorization, request validation, digest conflict detection, authoritative ownership resolution,
and replay binding validation.

The definitive retry protocol is in section 5. The implementation preserves:

- durable idempotency conflict detection for a same key with a different payload;
- lifecycle compare-and-swap for `REVOKING -> REVOKED`;
- no success response without backend read-back and persisted evidence;
- no duplicate revoke when read-back proves the backend is already absent;
- no re-execution when read-back is indeterminate.

### 4.2 F-02 — persistence failure is not an uncertain outcome

`BrokerDBError` remains a distinct exception type. The following rules now hold:

- top-level ownership and idempotency **reads** that fail raise `BrokerDBError`; they are never
  converted into “record missing”;
- per-record reconciliation **writes** that fail are recorded as a sanitized
  `{'policy_id': ..., 'error_code': 'PERSISTENCE_FAILURE'}` entry in `result.errors`, set a
  persistence-failed flag, and cause a top-level `status: 'error'` with
  `error_code: 'RECONCILIATION_PERSISTENCE_FAILURE'`;
- unrelated records continue to be reconciled in the same pass;
- lifecycle fail-closed behavior is preserved: a failed evidence or state write never produces
  `REVOKED` or `ACTIVE`;
- a same-key retry after the persistence failure runs the recovery path and can complete the
  promotion.

The idempotency response write at the end of a controller call is not masked: if
`complete_idempotency_record` raises, the caller sees `BrokerDBError`. The side effect may already
have happened, so the durable record remains `PENDING` and a same-key retry performs recovery.

### 4.3 F-03 — unknown lifecycle values fail closed

Reconciliation builds the known-state set from the lifecycle transition table and validates each
persisted record before acting on it. A state outside the table is never interpreted, adopted, or
rewritten. The controller:

- records a best-effort `reconcile_unknown_lifecycle_state` audit event with
  `reason: corrupt_ownership_state`;
- marks reconciliation status `uncertain` where persistence is available;
- returns `{'policy_id': ..., 'reason': 'corrupt_ownership_state'}` in `result.uncertain`;
- continues processing other targets.

A record whose persisted ownership fields do not bind correctly is similarly reported as
`corrupt_ownership_record` and is not used to drive a backend action.

### 4.4 F-04 — family-inclusive ownership identity

`_ownership_identity` returns:

```
(ownership_record_id, policy_id, policy_version, instance_id, network_id,
 canonical_policy_digest, address_family)
```

The authoritative family is derived from persistence by `_record_family`, with the established
`ipv4` default only when the persisted family is absent. `_validate_ownership_binding` rejects:

- a supplied `address_family` that differs from the authoritative family;
- a `required_families` list whose first element differs from the authoritative family;
- a persisted family that is malformed.

Revocation and verification evidence predicates compare `address_family`, and reconciliation
inspection requests use the authoritative family. Cross-family evidence cannot satisfy a gate.
The regression suite covers substitution attempts for inspect, verify, revoke, and remove, plus
persisted-family mutation and evidence-family mismatch.

### 4.5 F-05 — canonical idempotency digest

The digest payload is the operation plus these fields:

```
policy_id, policy_version, compiled_rule_digest, canonical_policy_digest,
compiled, instance_id, network_id, address_family, required_families,
ownership_reference, ownership_record_id, expected_ownership_identity,
ip_cidr, source_cidr, destination_cidr, protocol, port, ports,
peer_uid, peer_gid
```

Canonicalization is type-preserving:

- `None`, `bool`, `str`, `int` are accepted as-is;
- finite `float` is accepted; `NaN`/`Infinity` are rejected;
- `list` is recursively canonicalized;
- `dict` requires string keys and recursively canonicalized values; duplicate keys are rejected
  defensively;
- tuples, sets, bytes, arbitrary objects, non-string keys, and nesting deeper than 64 are
  rejected.

Serialization is deterministic:

```python
json.dumps(canonical, sort_keys=True, separators=(',', ':'),
           ensure_ascii=True, allow_nan=False)
```

The SHA-256 hex digest is stored as the idempotency request digest. A same key with different
compiled content, a different security-relevant field, or a different operation scope is rejected
before backend execution. Unsupported or ambiguous payloads fail closed with
`FirewallControllerRequestError`.

The digest proves payload identity only. It does **not** prove that a compiled policy is safe;
policy safety remains a compiler/parser and real-backend responsibility (see section 16).

### 4.6 F-06 — `REVOKED` evidence verification

A terminal `REVOKED` state is accepted as proof only when matching revocation evidence exists.
`_has_revocation_evidence` requires all of:

- `verification_result == 'revoked'`;
- matching `ownership_record_id`;
- matching `policy_id` and `policy_version`;
- matching `canonical_policy_digest`;
- matching `instance_id` and `network_id`;
- matching `address_family`.

The gate is enforced in three places:

- the already-`REVOKED` dispatch path;
- `_complete_revoke` when a concurrent winner has already promoted the record;
- reconciliation when it encounters `REVOKED` or `REVOKING`.

Missing, corrupt, or mismatched evidence raises `PermissionError` or produces
`revoked_without_valid_evidence`. There is no silent repair or evidence synthesis. A repeated
valid revoke remains an idempotent `status: ok` response with `already_revoked: true`.

### 4.7 F-07 — strict identifier and digest validation

Controller and helper validators now use:

```python
_DIGEST_RE = re.compile(r"\A[a-fA-F0-9]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")
```

and call `.fullmatch`. The helper contract applies identifier validation to `request_id`,
`operation_id`, `idempotency_key`, `policy_id`, and `ownership_reference`, and digest validation
to `compiled_rule_digest`/`canonical_policy_digest`. The controller applies digest validation to
caller-supplied and persisted digests.

Rejected forms include trailing newline, trailing carriage return, CRLF, leading/trailing
whitespace, embedded whitespace, invalid hex characters, and wrong length. Exact length and
character set are preserved; 1-character and 128-character identifiers are accepted and a
129-character identifier is rejected.

### 4.8 F-08 — allowlist semantics

`StrictAuthorizationProvider` now distinguishes absence from an explicit empty set:

| Configured value | Meaning |
|---|---|
| `None` | Documented fixed default: `health_check`, `install_policy`, `inspect_policy`, `verify_policy`, `revoke_policy`, `remove_stale_policy`, `reconcile_pending_operations` |
| `set()` | Deny every operation; never broadened back to the default |
| Partial set | Only the listed operations |
| Complete set | All supported operations |

The controller service passes the configured value through unchanged. Empty UID/GID allowlists
continue to deny all requests. Regression tests cover all four operation cases at the provider
level plus explicit-empty and omitted cases through the service.

### 4.9 F-09 — replay binding

Before any cached response is disclosed, the controller:

1. authorizes the request and validates it;
2. compares the stored request digest with the current canonical digest, which includes the
   authenticated `peer_uid`/`peer_gid`;
3. resolves the current authoritative ownership record;
4. validates caller ownership metadata against that record (policy, version, instance, network,
   digest, family);
5. compares the stored idempotency record's `ownership_record_id` with the fresh record ID;
6. compares the stored `resource_key` with `policy_id:policy_version`;
7. compares the stored `recovery_meta_json` ownership-identity snapshot, when present, with the
   fresh identity tuple.

Any mismatch raises `PermissionError` or `FirewallControllerIdempotencyError`; the cached
response is not disclosed. The snapshot is written when an idempotency record is completed, so
new records bind family, instance, network, digest, and ownership ID. Older records without the
snapshot still require matching request digest, stored ownership ID, and resource binding.

## 5. Same-key revoke recovery protocol

The definitive protocol for a same-key revoke retry is:

1. **Authorize and validate.** Authorization and request validation precede every replay and
   side effect.
2. **Reject payload conflicts.** Compute the canonical digest. If the same key exists for the
   same operation with a different digest, raise the existing idempotency conflict error before
   ownership resolution or execution.
3. **Resolve authoritative ownership.** The persisted record is the source of truth. Caller
   ownership fields are compared, never trusted.
4. **Validate replay binding.** Verify current peer identity, authoritative ownership, stored
   ownership ID, resource binding, and the ownership-identity snapshot.
5. **Classify the cached outcome.** A cached revoke response that is non-`ok`, or that carries
   `revocation_confirmed: false`, triggers recovery. A leftover `PENDING` revoke record also
   triggers recovery after the bounded wait. A definitive cached success is returned only after
   binding validation.
6. **Read back the backend first.** No destructive operation is re-issued before read-back:
   - backend absent/revoked → do not call revoke; proceed to evidence and lifecycle promotion;
   - backend present → mark a deliberate re-issue;
   - backend error/unknown → stay uncertain; do not call revoke.
7. **Re-issue only after proof of non-application.** When read-back proves the policy is still
   present, call the backend with a fresh helper idempotency key for this attempt. The durable
   controller-level idempotency key is unchanged. This prevents the backend/helper idempotency
   cache from replaying the old failure while preserving controller-level same-key semantics.
8. **Confirm after execution.** Read back again. Only a confirmed absent/revoked backend state
   permits promotion.
9. **Persist evidence before promotion.** Store revocation evidence, then perform the
   `REVOKING -> REVOKED` compare-and-swap. A concurrent winner is accepted only if the final
   state is `REVOKED` with matching evidence.
10. **Fail closed.** If any step is indeterminate or a persistence operation fails, return a
    sanitized non-success (`REVOKE_UNCONFIRMED` or the persistence exception) and leave the
    record in `REVOKING`. Never report success without read-back and evidence.

The mock helper was adjusted so that only definitive successful responses are cached. A failed
mock-helper response no longer permanently pins the helper to a transient error. This is a
mock-only fidelity change; a real helper must define equivalent retry semantics (section 16).

## 6. Persistence-failure semantics

| Failure point | Behavior |
|---|---|
| Ownership read (`get_by_policy`, `list_ownerships`) | `BrokerDBError` propagates. Never converted to “missing”. |
| Idempotency read (`get_idempotency_record`) | `BrokerDBError` propagates. |
| Ownership create / state update / lifecycle history write | `BrokerDBError` propagates; lifecycle transition does not occur. |
| Evidence write during revoke/verify | `BrokerDBError` propagates; no `REVOKED`/`ACTIVE` promotion. |
| Idempotency completion write | `BrokerDBError` propagates; the durable record remains `PENDING`; same-key retry recovers. |
| Reconciliation per-record write | Sanitized `PERSISTENCE_FAILURE` entry; top-level `status: error` / `RECONCILIATION_PERSISTENCE_FAILURE`; other records continue. |
| Reconciliation read | `BrokerDBError` propagates; not treated as absence. |
| Best-effort audit write | May be swallowed only for audit-only paths that already had this contract; security state writes are not swallowed. |

`status: ok` is never returned when a persistence write failure affected the outcome of the
operation. `BrokerDBError` remains distinguishable from an ordinary backend-uncertain result.

## 7. Unknown/corrupt lifecycle behavior

- **Unknown state value:** not in the lifecycle transition table → `corrupt_ownership_state`;
  no action; no adoption; no rewrite; audit best-effort; record marked `uncertain` where possible.
- **Corrupt ownership binding:** policy/version/digest/instance/network/family cannot be bound →
  `corrupt_ownership_record`; no backend action.
- **`REVOKED` without valid evidence:** `revoked_without_valid_evidence` or `PermissionError`;
  never success.
- **`VERIFIED` without valid evidence:** `verified_without_valid_evidence`; not promoted.
- **`REVOKING` with backend absent/revoked:** evidence is stored before promotion to `REVOKED`.
- **`REVOKING` with backend present:** `partial_revoke_backend_still_present`; no duplicate side
  effect.
- **Unrelated valid records:** untouched and still reconcilable in their own pass.

No unknown object is auto-adopted. No corrupt state is silently repaired.

## 8. Canonical digest specification (normative summary)

```
payload = {
  "operation": operation,
  "policy_id": ..., "policy_version": ...,
  "compiled_rule_digest": ..., "canonical_policy_digest": ...,
  "compiled": <full compiled body>,
  "instance_id": ..., "network_id": ...,
  "address_family": ..., "required_families": ...,
  "ownership_reference": ..., "ownership_record_id": ...,
  "expected_ownership_identity": ...,
  "ip_cidr": ..., "source_cidr": ..., "destination_cidr": ...,
  "protocol": ..., "port": ..., "ports": ...,
  "peer_uid": ..., "peer_gid": ...
}
canonical = canonicalize(payload)     # type-preserving, no coercion
raw = json.dumps(canonical, sort_keys=True, separators=(',', ':'),
                 ensure_ascii=True, allow_nan=False)
digest = sha256(raw.encode('utf-8')).hexdigest()
```

The compiled body is covered in full, including nested content. Changing a nested compiled value
changes the digest. A different operation uses a separate idempotency scope. Unsupported types
fail closed. The digest is an identity binding, not a policy-safety proof.

## 9. REVOKED evidence verification (normative summary)

Evidence is accepted only when every field below matches the authoritative ownership record:

```
verification_result == 'revoked'
ownership_record_id
policy_id
policy_version
canonical_policy_digest
instance_id
network_id
address_family
```

The same predicate is used by the already-`REVOKED` dispatch path, `_complete_revoke`, and
reconciliation. Valid repeats are idempotent successes. Invalid evidence fails closed.

## 10. Replay behavior

| Replay condition | Result |
|---|---|
| Same key, same operation, same canonical payload, current ownership/identity match | Cached response returned after binding validation. |
| Same key, same operation, different canonical payload/security field | `FirewallControllerIdempotencyError`; no execution. |
| Same key, different operation | Separate idempotency scope; normal execution/validation. |
| Cached revoke non-`ok`/uncertain | Recovery path; no cached error disclosure; no blind re-execution. |
| Cached success but authoritative ownership changed | `PermissionError`; no disclosure. |
| Cached success but stored ownership record ID changed | `PermissionError`; no disclosure. |
| Cached success but ownership-identity snapshot changed (instance, network, family, digest) | `PermissionError`; no disclosure. |
| Cached success but peer identity changed | Digest conflict; `FirewallControllerIdempotencyError`. |
| Process restart with unchanged ownership | Durable record replays after validation; no duplicate backend call. |

## 11. Failure-state matrix

| Situation | Persisted state | Cached idempotency | Backend action | Response | Evidence |
|---|---|---|---|---|---|
| Backend revoke applied, response lost | `REVOKING` | error/uncertain or `PENDING` | none; read-back absent | `ok` | stored before `REVOKED` |
| Backend still present after failed revoke | `REVOKING` | error/uncertain | read-back present → re-issue with fresh helper key | `ok` after confirmation | stored before `REVOKED` |
| Read-back indeterminate | `REVOKING` | error/uncertain | none | `REVOKE_UNCONFIRMED` (`status: error`) | none |
| Evidence write fails | `REVOKING` | remains `PENDING`/error | none | `BrokerDBError` or sanitized non-success | none |
| Lifecycle CAS conflict | `REVOKING`/`REVOKED` | updated by winner | none on loser | success only if winner reached `REVOKED` with evidence; otherwise fail closed | winner’s evidence |
| Already `REVOKED` with valid evidence | `REVOKED` | optional | none | `ok`, `already_revoked: true` | validated |
| Already `REVOKED` without/mismatched evidence | `REVOKED` | optional | none | `PermissionError` / uncertain | invalid; no repair |
| Unknown lifecycle value | unchanged corrupt value | none | none | `uncertain/corrupt_ownership_state` | none |
| Reconciliation record write fails | best-effort state | n/a | may have inspected only | top-level `status: error`, `RECONCILIATION_PERSISTENCE_FAILURE` | none for failed record |
| Same key, different compiled body | unchanged | conflict | none | `FirewallControllerIdempotencyError` | none |
| Unsupported compiled type | unchanged | none created | none | `FirewallControllerRequestError` | none |
| Replay after ownership identity change | unchanged | cached | none | `PermissionError` | none |
| Explicit empty operation allowlist | unchanged | none | none | auth error | none |
| Omitted operation allowlist | unchanged | normal | normal if authorized | documented default applies | normal |

## 12. Regression coverage added

`broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py` contains 56
test functions and 96 collected tests after parametrization:

- **F-01:** nine tests covering recovery after backend failure, lost success response, read-back
  failure, evidence persistence failure, lifecycle persistence failure, unknown backend state,
  backend still present, concurrent same-key retries, and different-key retry.
- **F-02:** seven tests covering revocation evidence/state/reconciliation-status persistence
  failures, backend uncertainty preserved as a non-persistence outcome, recovery after database
  restoration, idempotency response persistence failure, and ownership lookup failure not treated
  as absence.
- **F-03:** three unknown-state variants plus preservation of unrelated valid records.
- **F-04:** four cross-family substitution operations, required-family mismatch, persisted-family
  mutation, verification-evidence family mismatch, and revocation-evidence family mismatch.
- **F-05:** same compiled replay, different compiled body, nested compiled content, six changed
  security fields, separate operation scope, restart replay, unsupported type, NaN, and non-string
  key.
- **F-06:** already-`REVOKED` without/mismatched/wrong-family evidence, valid evidence idempotency,
  and reconciliation variants.
- **F-07:** nine invalid digest forms, three valid digest forms, twenty-one invalid identifier
  combinations, identifier boundaries, controller trailing-newline rejection, and non-hex stored
  digest rejection.
- **F-08:** `None`, explicit-empty, partial, and complete operation sets at the provider level, plus
  explicit-empty and omitted sets through the service.
- **F-09:** same-identity replay, different-identity rejection, ownership-record replacement,
  in-place instance change with omitted fields, family change with omitted family, and concurrent
  replay/ownership change.

During authoring of the new file, several new-test setup errors were corrected: using the
operation valid for an `ACTIVE` record (`inspect_policy` rather than `verify_policy`), using the
authenticated `peer_uid`/`peer_gid` field names, using a compiled payload shape accepted by the
strict helper contract, and dropping an inapplicable “missing record” case from the unknown-state
parametrization. These were test-setup corrections, not reductions of the asserted security
properties. No existing test assertion was weakened.

## 13. Test results

All commands were run from `E:\Flag-hunt\ctf-platform-be` with the project virtual environment.

### 13.1 New 2G.3.6 regression suite

Command:

```powershell
.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py -q
```

Result: **96 passed, 1 warning in 43.71s**. The warning is the pre-existing Pydantic
class-based-`config` deprecation warning. The environment also emits a
`PytestDeprecationWarning` about `asyncio_default_fixture_loop_scope` on stderr before collection;
it is not a test failure and is not counted in the pytest warning summary.

### 13.2 Required existing remediation, lifecycle, persistence, contract, and identity suites

Command:

```powershell
.\venv\Scripts\python.exe -m pytest ^
  broker/tests/test_firewall_controller_ownership_binding_remediation.py ^
  broker/tests/test_firewall_controller_revoke_lifecycle_remediation.py ^
  broker/tests/test_firewall_controller_remediation_authorization_storage_allowlists.py ^
  broker/tests/test_firewall_controller_persistent_recovery_integration.py ^
  broker/tests/test_firewall_controller_persistence_failure_closure.py ^
  broker/tests/test_firewall_controller_crash_boundary_instrumentation.py ^
  broker/tests/test_firewall_controller_helper_contract.py ^
  broker/tests/test_firewall_controller_helper_identity_propagation.py ^
  broker/tests/test_firewall_controller_lifecycle_idempotency.py -q
```

Result: **193 passed, 1 warning in 58.20s**. The warning is the same pre-existing Pydantic
deprecation.

### 13.3 Full controller suite

Command:

```powershell
$files = Get-ChildItem broker/tests/test_firewall_controller*.py | ForEach-Object { $_.FullName }
.\venv\Scripts\python.exe -m pytest $files -q
```

Result: **343 passed, 1 warning in 104.76s**.

### 13.4 Full Broker suite

Command:

```powershell
.\venv\Scripts\python.exe -m pytest broker/tests -q
```

Result: **446 passed, 1 warning in 172.71s**.

### 13.5 Django manager-client tests

Command:

```powershell
.\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client
```

Result: **Ran 33 tests — OK**, system check identified no issues (0 silenced).

### 13.6 Django system check

Command:

```powershell
.\venv\Scripts\python.exe manage.py check
```

Result: **System check identified no issues (0 silenced).**

### 13.7 Warning summary

| Warning | Count | Assessment |
|---|---|---|
| `PydanticDeprecatedSince20`: class-based `config` | 1 per pytest run | Pre-existing, unrelated to this phase. |
| `PytestDeprecationWarning`: `asyncio_default_fixture_loop_scope` unset | Environment stderr | Pre-existing test-environment warning; no test failure. |
| Test failures | 0 | — |

Because PowerShell treats native-command stderr as an error record, a run may display
`Exited with code 1` even when pytest reports `0 failed` and all tests passed. The authoritative
result in this report is the pytest summary line (for example, `96 passed, 1 warning`), not the
PowerShell wrapper exit code. No test failure was observed.

## 14. Remaining limitations

The following are explicitly **not** resolved by this local mock-only phase:

1. **No real transport or kernel-authenticated peer identity.** UDS/`SO_PEERCRED` is not
   implemented. `peer_uid`/`peer_gid` are caller/test inputs in the mock.
2. **No privileged helper.** The helper remains a mock; capability separation, supervision,
   crash modes, and process-level timeout enforcement are future work.
3. **Mock backend fidelity.** Read-back behavior is deterministic mock behavior. Real nftables/
   iptables read-back, rule-handle semantics, conntrack interaction, and partial-apply behavior
   must be validated against a real backend before any live claim.
4. **Default backend is fail-closed mock.** Production wiring must inject a real backend; the
   default is not a live implementation.
5. **Timeout is validated, not enforced.** `timeout_ms` bounds are checked, but wall-clock
   enforcement belongs to the future transport/process layer.
6. **Helper-side durability and binding.** The controller binds ownership and idempotency; the
   mock helper does not maintain its own durable ownership store. A real helper must define
   equivalent binding and retry semantics.
7. **Mock identity coercion.** Mock identity values are ordinary Python integers; real
   kernel-typed credentials are required for a live claim.
8. **Digest provenance.** The controller treats the supplied canonical digest as an identity
   binding. It does not prove that the compiler produced the digest from a safe policy. Policy
   safety/parsing remains a compiler and real-backend responsibility.
9. **`compiled` remains optional in the helper contract.** The real helper must require and
   interpret its compiled payload.
10. **Heuristic compiled-policy validator (ID-06).** Typed, bounded data validation is enforced,
    but no parser-level or execution-safety proof is claimed.
11. **Replay snapshot migration.** Records completed after 2G.3.6 carry the
    `recovery_meta_json` ownership-identity snapshot. Older records fall back to the request
    digest, stored ownership record ID, and resource-key binding. A real migration can backfill
    snapshots if required.
12. **Reconciliation entry point is per-policy.** The strict request validator requires
    `policy_id`/`policy_version`, so the list-all branch in `reconcile_pending_operations` is not
    reachable through the normal strict entry point. The preserve-unrelated-records test verifies
    that reconciling a corrupt target does not modify other valid records.
13. **Fresh helper key on confirmed re-issue.** Same-key recovery deliberately uses a fresh
    helper-boundary idempotency key after read-back proves the previous attempt did not apply. A
    real helper must implement the same documented retry policy; the controller-level key remains
    durable and unchanged.

## 15. Real-boundary gates and authorization status

The following remain blocked and require separate authorization:

- real transport and UDS/`SO_PEERCRED` peer credential validation;
- privileged helper implementation, capability model, supervision, and crash recovery;
- real backend read-back and revocation semantics, including conntrack and partial-apply cases;
- systemd/host permission hardening;
- live provisioning and any production/cloud database changes;
- any nftables/iptables/UFW/Docker firewall, routing, NAT, or conntrack change.

**Final status: PASS for local mock-only 2G.3.6 remediation.**
**Live readiness remains: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.** No live change
was made, and this report does not authorize one. Work stops here pending separate approval.
