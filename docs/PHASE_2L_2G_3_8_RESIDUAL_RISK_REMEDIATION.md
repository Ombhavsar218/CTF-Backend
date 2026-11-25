# Phase 2L.2G.3.8 — Residual Risk Remediation (R-01, R-02, R-03)

**Scope:** local mock-only controller / persistence / helper-contract remediation  
**Date:** 2026-11-09  
**Base review:** `docs/PHASE_2L_2G_3_7_INDEPENDENT_REVOKE_RECOVERY_AND_IDEMPOTENCY_REVIEW.md`  
**Prior remediation:** `docs/PHASE_2L_2G_3_6_REVOKE_RECOVERY_AND_IDEMPOTENCY_HARDENING.md`  
**Mode:** implementation, regression tests, verification, and documentation only.

> **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
>
> This phase is local mock-only code remediation. It does not implement, validate, or authorize a
> real transport, UDS/`SO_PEERCRED`, privileged helper, sudo/capabilities, nftables/iptables/UFW/
> Docker firewall changes, routing/NAT/conntrack changes, systemd/host permission changes, live
> Docker, provisioning, or production/cloud database changes. No real host or firewall change was
> made.

---

## 1. Decision

| Decision layer | Result |
|---|---|
| Local mock-only 2G.3.8 remediation of R-01, R-02, and R-03 | **PASS** |
| Real transport / privileged helper / live firewall readiness | **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED** |

R-01, R-02, and R-03 are demonstrably remediated in the local mock scope. New fault-injection and
corruption tests cover each finding. All required suites pass on the final source and test set. No
existing test assertion was weakened or removed.

The PASS is limited to the three phase-scoped residuals and the local mock suites. It is **not** a
live security certification and does not authorize real firewall integration.

---

## 2. Scope and constraints

In scope:

- install-failure persistence error handling (R-01);
- controller/pre-persistence canonical validation of `policy_id`, `instance_id`, and `network_id`
  (R-02);
- stored idempotency request-digest integrity before cached-response disclosure (R-03);
- directly necessary regression tests;
- preservation of F-01 through F-09 and the existing mock security properties;
- local verification and this report.

Out of scope and not performed:

- no real firewall backend, privileged helper, UDS/`SO_PEERCRED`, sudo/capabilities, routing/NAT/
  conntrack, systemd/host, live Docker, or provisioning work;
- no production or cloud database infrastructure;
- no unrelated feature expansion or weakening of existing tests.

---

## 3. Findings and root causes

### R-01 — install backend-failure path swallowed persistence errors

- **Original severity:** Low.
- **Root cause:** The install failure branch caught broad exceptions while attempting the
  `REQUESTED`/`VALIDATING`/`INSTALLING -> FAILED` transition and lifecycle-history write. A
  `BrokerDBError` from either write could be swallowed. The controller then reached the normal
  idempotency-completion tail and stored the backend error as a `COMPLETED` idempotency response.
- **Impact:** The caller could not distinguish a persistence failure from a fully recorded backend
  failure. The ownership record could remain at its prior state while idempotency claimed a
  completed outcome. This was a reliability/error-visibility defect, not a demonstrated privilege
  escalation.

### R-02 — controller/pre-persistence identifier validation was not canonical

- **Original severity:** Low.
- **Root cause:** The controller enforced digest format and some type checks, but did not apply the
  helper contract's canonical `_ID_RE` to controller-supplied `policy_id`, `instance_id`, or
  `network_id` before ownership/idempotency persistence. Malformed policy IDs could create
  ownership rows before helper rejection, and malformed optional instance/network values could be
  persisted end-to-end. The helper contract also did not validate non-empty optional instance and
  network identifiers.
- **Impact:** Data-integrity and log/identity confusion. No privilege escalation was found.

### R-03 — empty/NULL stored request digest skipped peer-identity binding

- **Original severity:** Low.
- **Root cause:** The idempotency pre-check and replay decision treated a stored `request_digest`
  as a truthy comparison guard. A missing, empty, malformed, or wrong-length stored digest could
  skip the digest comparison, including the authenticated peer identity covered by the digest.
  `_validate_replay` still checked ownership/resource/snapshot binding, but the ownership snapshot
  does not include peer identity.
- **Impact:** A corrupt or migrated idempotency row could disclose a cached response to a different
  authorized peer. The trigger required a corrupt/migrated row, so severity was Low.

---

## 4. Files changed

| File | Change |
|---|---|
| `broker/firewall_controller_service/controller_service.py` | Added canonical controller identifier validation before store access and persistence; validated authoritative optional identifiers; added strict stored-digest integrity validation and best-effort corruption audit; added sanitized install-failure persistence error handling; preserved prior/advanced lifecycle state; added a late idempotency re-check to preserve idempotency-conflict classification under concurrent same-key races. |
| `broker/firewall_controller_service/errors.py` | Added `FirewallControllerPersistenceError` with error code `PERSISTENCE_FAILURE`. |
| `broker/firewall_controller_service/helper_contract.py` | Validates non-empty `instance_id`/`network_id` with the same canonical `_ID_RE`; empty/`None` remain optional for helper compatibility. |
| `broker/tests/test_firewall_controller_residual_risk_remediation.py` | New 69-test R-01/R-02/R-03 regression suite, including fault injection, corruption, restart, concurrency, and no-overwrite coverage. |
| `docs/PHASE_2L_2G_3_8_RESIDUAL_RISK_REMEDIATION.md` | This report. |

No real transport, privileged helper, firewall, routing, host, provisioning, or production
database file was created or modified.

---

## 5. Implementation

### 5.1 R-01 — fail closed when install-failure persistence fails

The install failure path now distinguishes the backend failure from the persistence of the
failure state.

When the backend returns a non-`ok` install response, the controller:

1. Re-reads the authoritative ownership record. A read failure raises
   `FirewallControllerPersistenceError` (reason `persistence_unavailable`) instead of treating the
   record as missing.
2. Refuses to proceed if the ownership record is missing.
3. Re-validates ownership identity so a concurrent replacement is not overwritten.
4. Attempts the `FAILED` transition only for failable states (`REQUESTED`, `VALIDATING`,
   `INSTALLING`), using the existing lifecycle CAS/version.
5. Records lifecycle history only after the state write succeeds.
6. Raises a sanitized `FirewallControllerPersistenceError` if the state or history cannot be
   fully persisted.
7. Never reaches the normal `complete_idempotency_record` tail when that error is raised. The
   idempotency record remains `PENDING`.

The sanitized error shape is:

```python
{
    "error_code": "PERSISTENCE_FAILURE",
    "message": "Install failure could not be fully persisted",
    "details": {
        "operation": "install_policy",
        "backend_error_code": "<bounded backend code or BACKEND_ERROR>",
        "failure_state_persisted": False,
        "lifecycle_history_persisted": False,
        "reason": "<bounded reason>",
    },
}
```

The exception is raised with `from None`; raw persistence exceptions and backend error messages
are not chained into the user-visible error. `backend_error_code` is bounded to
`[A-Za-z0-9_.:-]{1,64}`. Audit failure is best-effort and does not prevent the fail-closed
response.

Resulting state matrix:

| Case | Ownership state | Idempotency | Caller result |
|---|---|---|---|
| Failure state and history persist | `FAILED` | `COMPLETED` with backend error; replayable | Backend error response |
| Failure state write fails | Prior state, e.g. `REQUESTED` | `PENDING` | Sanitized `PERSISTENCE_FAILURE` |
| Failure state succeeds, history write fails | `FAILED` | `PENDING` | Sanitized `PERSISTENCE_FAILURE` |
| State advanced concurrently | Preserved advanced state, never downgraded | `PENDING` | Sanitized `PERSISTENCE_FAILURE` |
| Ownership missing or unreadable | No false completion | `PENDING` | Sanitized `PERSISTENCE_FAILURE` |

No success or fully-durable claim is made when the failure state cannot be persisted. The durable
`PENDING` record and preserved ownership state provide reconciliation context. A deliberate
recovery attempt can use a fresh idempotency key; the old pending record remains available for
reconciliation.

### 5.2 R-02 — canonical identifiers before persistence

The controller now applies the same canonical identifier rule used by the helper contract:

```text
\A[A-Za-z0-9._:-]{1,128}\Z
```

Validation occurs after authorization and legacy request-shape validation, but before any
ownership lookup, ownership creation, state write, lifecycle history write, or idempotency
persistence.

Rules:

- `policy_id` is required and must be a canonical string. `NULL`/`None`, empty, whitespace,
  control characters, trailing `\n`/`\r`, over-128-character values, and unsupported types are
  rejected.
- `instance_id` and `network_id` remain optional. Omitted fields and explicit `None` remain
  supported for compatibility and normalize to an empty stored value.
- An explicitly supplied empty string, malformed string, or unsupported type for
  `instance_id`/`network_id` is rejected. Values are never coerced to strings.
- Authoritative stored `instance_id`/`network_id` values are also validated when non-empty.
  Legacy empty/NULL optional values remain accepted; non-empty malformed values fail closed as a
  corrupt authoritative ownership record.
- Valid identifiers, including the 128-character boundary and the permitted punctuation set, are
  preserved exactly.

The helper contract now validates non-empty optional `instance_id`/`network_id` with the same
`_ID_RE`. Empty and `None` values remain optional at the helper boundary. A regression test asserts
that the controller and helper identifier patterns are identical.

The existing strict 64-hex digest gate remains unchanged. R-02's phase-scoped controller
pre-persistence validation covers `policy_id`, `instance_id`, and `network_id`.

### 5.3 R-03 — stored digest integrity before replay

`_validated_stored_idempotency_digest` now requires the stored `request_digest` to be a string
matching exactly 64 hexadecimal characters:

```text
\A[a-fA-F0-9]{64}\Z
```

It is used by both the pre-ownership idempotency check and `_idempotency_replay_decision`. A
missing, `NULL`, empty, malformed, wrong-length, non-hex, or non-string stored digest causes:

```python
FirewallControllerIdempotencyError(
    "Corrupt idempotency record: stored request digest is missing or invalid",
    details={"reason": "stored_request_digest_invalid"},
)
```

The error code remains `IDEMPOTENCY_CONFLICT`. The denial occurs before any cached response is
disclosed. The peer-identity digest comparison is never skipped: a valid stored digest must match
the current request digest, which includes the authenticated peer identity, operation, ownership
fields, address family, and compiled payload fields.

A best-effort `idempotency_digest_corrupt` audit event records the operation, idempotency key,
reason, whether a digest was present, and the stored value's type. Audit failure is caught and does
not bypass denial. The denial path never repairs, rewrites, or "fixes" the corrupt digest.

The existing `_validate_replay` ownership-record, resource, and ownership-identity snapshot checks
remain in force after the digest is validated.

### 5.4 Concurrency ordering fix for same-key conflicts

Final verification exposed a pre-existing race in the cross-process same-key conflict test. If a
second process missed the first process's idempotency row during the initial pre-check, but then
observed the first process's ownership row, it could reject with an ownership-digest
`PermissionError` before re-checking the idempotency conflict. Both outcomes deny the request, but
the established contract for the same key/different payload is
`FirewallControllerIdempotencyError`.

The controller now re-checks the idempotency record after an ownership-binding `PermissionError`.
If a late record exists and its validated digest differs from the current request digest, the
controller raises the idempotency conflict. If the record is absent or has the same valid digest,
the original ownership denial is preserved; if the late record is corrupt, the sanitized
corrupt-digest error is raised. This re-check:

- performs no writes and creates no side effects;
- never returns a cached response;
- raises the same sanitized corrupt-digest error if the late record is corrupt;
- preserves idempotency-conflict classification under concurrency.

A 20-iteration process-pool reproduction produced one `PermissionError` before the fix and 20/20
`FirewallControllerIdempotencyError` results after the fix. The final cross-process suite passes.

---

## 6. Regression coverage

The new suite contains **69 tests**:

| Area | Coverage |
|---|---|
| R-01 | Successful failure persistence and replay; state-write failure with two persistence messages (including a secret-bearing "database is locked" message); history-write failure; concurrent state advance/no overwrite; fresh-key recovery after persistence returns; no false completion. |
| R-02 | Invalid `policy_id` across 13 malformed/NULL/unsupported values; invalid `instance_id` and `network_id` across 12 values each; omitted and `None` optional fields; controller/helper pattern identity; 128-character and punctuation boundaries; corrupt authoritative optional identifiers; helper-contract malformed optional identifiers. |
| R-03 | Eight corrupt stored-digest forms (NULL, empty, malformed, short, long, non-hex, integer, bytes); audit failure does not prevent denial; valid matching replay; different authorized peer rejection; denial after process restart; concurrent replay never discloses cached response; corrupt value is not repaired. |

No skip was added. No existing test was changed or weakened.

---

## 7. Verification results

All commands were run from `E:\Flag-hunt\ctf-platform-be` with the project virtual environment.
Each pytest command was preceded by a fresh temporary controller database to isolate
cross-process tests from repository default DB state:

```powershell
$db = Join-Path $env:TEMP ("fc_3_8_" + [guid]::NewGuid().ToString() + ".db")
$env:FIREWALL_CONTROLLER_DB_PATH = $db
```

### 7.1 New R-01/R-02/R-03 regression suite

```powershell
.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_residual_risk_remediation.py -q
```

Result: **69 passed, 1 warning in 18.04s**.

### 7.2 3.6 hardening suite (F-01 through F-09)

```powershell
.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_revoke_recovery_and_idempotency_hardening.py -q
```

Result: **96 passed, 1 warning in 31.84s**.

### 7.3 Ownership and revoke lifecycle

```powershell
.\venv\Scripts\python.exe -m pytest `
  broker\tests\test_firewall_controller_ownership_binding_remediation.py `
  broker\tests\test_firewall_controller_revoke_lifecycle_remediation.py -q
```

Result: **38 passed, 1 warning in 25.00s**.

### 7.4 Persistence and recovery

```powershell
.\venv\Scripts\python.exe -m pytest `
  broker\tests\test_firewall_controller_persistence_failure_closure.py `
  broker\tests\test_firewall_controller_persistent_recovery_integration.py -q
```

Result: **40 passed, 1 warning in 12.73s**.

### 7.5 Helper identity and helper contract

```powershell
.\venv\Scripts\python.exe -m pytest `
  broker\tests\test_firewall_controller_helper_identity_propagation.py `
  broker\tests\test_firewall_controller_helper_contract.py -q
```

Result: **80 passed, 1 warning in 0.94s**.

### 7.6 Cross-process and crash recovery

```powershell
.\venv\Scripts\python.exe -m pytest `
  broker\tests\test_firewall_controller_cross_process_crash_recovery.py `
  broker\tests\test_firewall_controller_cross_process_concurrency.py -q
```

Result: **10 passed, 1 warning in 5.49s**.

### 7.7 Full controller suite

```powershell
$files = Get-ChildItem broker\tests\test_firewall_controller*.py | ForEach-Object { $_.FullName }
& .\venv\Scripts\python.exe -m pytest $files -q
```

Result: **412 passed, 1 warning in 133.54s**.

### 7.8 Full Broker suite

```powershell
.\venv\Scripts\python.exe -m pytest broker\tests -q
```

Result: **515 passed, 1 warning in 147.75s**.

### 7.9 Django manager-client tests

```powershell
.\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client -v 1
```

Result: **Ran 33 tests — OK**, system check identified no issues (0 silenced).

### 7.10 Django system check

```powershell
.\venv\Scripts\python.exe manage.py check
```

Result: **System check identified no issues (0 silenced).**

### 7.11 Summary

| Suite | Result |
|---|---|
| New 3.8 regression suite | 69 passed |
| 3.6 hardening | 96 passed |
| Ownership/revoke lifecycle | 38 passed |
| Persistence/recovery | 40 passed |
| Helper identity/contract | 80 passed |
| Cross-process/crash | 10 passed |
| Full controller | 412 passed |
| Full Broker | 515 passed |
| Django manager-client | 33 tests, OK |
| Django system check | No issues |
| Skips | 0 |
| Failures in final runs | 0 |

Warnings: each pytest run reports the pre-existing Pydantic class-based `config` deprecation
warning. The environment also emits a `PytestDeprecationWarning` about the unset
`asyncio_default_fixture_loop_scope` on stderr before collection; it is not a test failure and is
not counted in the pytest warning summary. PowerShell may display a native-command exit code of 1
because of that stderr warning even when pytest reports zero failures; the pytest summary is
authoritative.

### 7.12 Verification notes

- An initial combined invocation that reused the repository default controller DB failed
  `test_cross_process_identical`; the test passed in isolation and in the fresh-temp-DB runs used
  for final verification. `broker/tests/conftest.py` assigns `FIREWALL_CONTROLLER_DB_PATH` to a
  fresh per-pytest-process temporary path before broker modules import, so the test suite does
  not use the repository default DB. This was a test-isolation condition, not a demonstrated
  controller behavior regression.
- Final verification also exposed the same-key concurrency race described in section 5.4. It was
  reproduced, fixed without weakening the test, and re-verified with 20/20 process-pool iterations
  and the final suite. The final cross-process result is 10 passed.
- No test failure exists in the final reported runs.

---

## 8. F-01 through F-09 and existing security properties

The prior hardening remains intact:

| Property | Status after 3.8 |
|---|---|
| F-01 same-key uncertain revoke recovery | Preserved. Valid revoke recovery still classifies cached uncertain/error outcomes as recover; R-03 only denies corrupt stored digests. |
| F-02 reconciliation persistence-failure classification | Preserved. Reconciliation still reports sanitized persistence failures; R-01 adds the install-failure-specific sanitized error instead of swallowing it. |
| F-03 unknown/corrupt lifecycle state fail-closed | Preserved. R-01 never adopts or rewrites an unknown/advanced state. |
| F-04 address-family identity/evidence binding | Preserved. R-02 does not change family derivation or evidence predicates. |
| F-05 canonical digest coverage | Preserved. Peer identity, operation, ownership fields, family, and compiled fields remain in the idempotency digest. |
| F-06 evidence-gated `REVOKED` | Preserved. No success/terminal transition is fabricated by the persistence or replay changes. |
| F-07 exact regex/fullmatch validation | Strengthened. Controller identifier validation uses the canonical `\A...\Z` rule; helper optional identifiers use the same rule. |
| F-08 authorization allowlist semantics | Preserved. No authorization change. |
| F-09 replay ownership binding | Preserved and strengthened. Corrupt digests are rejected before the existing ownership ID/resource/snapshot replay checks. |
| Ownership binding and peer identity | Preserved; R-03 closes the corrupt-digest path that could bypass peer comparison. |
| Lifecycle CAS and no state downgrade | Preserved; R-01 no-overwrite test covers a concurrent advance. |
| Evidence-gated terminal revoke | Preserved. |
| Reconciliation fail-closed behavior | Preserved. |
| Durable idempotency and replay | Preserved for valid records; corrupt records fail closed without disclosure. |
| Helper identity/contract | Preserved; optional identifier validation added without removing optional compatibility. |
| Sanitized errors and best-effort audit | Preserved; R-01 and R-03 add sanitized errors and best-effort audit. |

---

## 9. Compatibility analysis

- **No existing test assertions were changed.** The full controller count increased from the prior
  343 to 412, and the full Broker count from 446 to 515, because of the new 69-test suite.
- **Optional instance/network compatibility:** omitted fields and explicit `None` remain accepted.
  Explicit empty strings are now rejected by the controller. Legacy authoritative empty optional
  values remain accepted; non-empty malformed authoritative values fail closed.
- **Valid identifier compatibility:** values using the canonical characters and up to 128
  characters remain accepted and are stored unchanged. Values containing whitespace, control
  characters, trailing newlines/CRs, or unsupported types are now rejected before persistence.
  Callers that previously relied on non-canonical IDs must migrate those values.
- **R-01 caller compatibility:** when the failure state/history cannot be persisted, callers now
  receive `PERSISTENCE_FAILURE` instead of a normal backend-error response with a possibly
  inaccurate completed idempotency record. This is the intended fail-closed change.
- **R-03 caller compatibility:** a caller presenting a corrupt stored idempotency digest now
  receives `IDEMPOTENCY_CONFLICT` instead of a cached response. Valid matching records still
  replay normally.
- **Same-key recovery:** a failed install whose failure persistence was incomplete leaves the old
  idempotency record `PENDING`; the controller does not silently complete it on the same key.
  Reconciliation/fresh-key recovery is the supported path.
- **Concurrency error classification:** in a same-key/different-payload race, the late
  idempotency re-check may classify the denial as `IDEMPOTENCY_CONFLICT` where an ownership
  `PermissionError` might previously have been observed. Both deny; the new classification
  matches the established idempotency contract and never discloses a response.

---

## 10. Remaining limitations

The following are explicitly **not** resolved by this local mock-only phase:

1. **No live transport or kernel-authenticated peer identity.** UDS/`SO_PEERCRED` is not
   implemented. Peer UID/GID remain caller/test inputs.
2. **No privileged helper or live firewall.** The helper remains a mock. No nftables/iptables/UFW/
   Docker, routing/NAT/conntrack, systemd/host, live Docker, or provisioning behavior is validated.
3. **No production database durability proof.** Persistence behavior is SQLite/mock-scoped.
   Real database locking, migration, replication, and durability remain live-validation items.
4. **Same-key automatic recovery after R-01 persistence failure is not added.** The durable state
   remains safe and reconciliation-ready; recovery is exercised with a fresh key.
5. **R-02 phase scope.** Controller-level canonical validation added here covers `policy_id`,
   `instance_id`, and `network_id`. The broader field list suggested by the 3.7 review
   (`request_id`, `operation_id`, `idempotency_key`, and ownership-reference fields) was not
   expanded into a new controller-wide gate in this phase; existing request-shape, ownership-match,
   and helper-contract checks remain in force.
6. **Legacy `_validate_request` digest check (I-07).** The legacy validator still shape-checks a
   16-character digest. The controller service's strict 64-hex gate remains authoritative for
   non-health operations. This was not expanded in 3.8.
7. **No database `CHECK` constraint for digest format.** R-03 is enforced at the service boundary;
   externally corrupted/migrated rows are denied and audited rather than repaired.
8. **Corrupt-digest denial is not auto-repaired.** Operators must treat a corrupt idempotency row
   as an integrity incident; the controller does not rewrite it.
9. **Mock concurrency only.** The late idempotency re-check and SQLite CAS behavior are verified
   locally; distributed database and multi-host ordering semantics are out of scope.
10. **Cross-process test DB isolation.** `broker/tests/conftest.py` assigns
    `FIREWALL_CONTROLLER_DB_PATH` to a fresh per-pytest-process temporary path before broker
    module import; spawned workers inherit it. The cross-process concurrency test intentionally
    shares that isolated DB across its workers. No test was weakened.

---

## 11. Final status

**PASS — local mock-only remediation of R-01, R-02, and R-03.**

The three phase-scoped residuals are remediated, regression coverage exists, F-01 through F-09
remain intact, and all required suites pass on the final source and test set.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.**

This phase stops after implementation, verification, and documentation. No independent review, real
transport, UDS/`SO_PEERCRED`, privileged helper, or live firewall work is authorized or performed.
