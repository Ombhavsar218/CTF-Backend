# Phase 2L.2G.3.9 — Independent Residual Risk Security Review

**Date:** 2026-11-11  
**Review type:** Independent source, call-path, persistence, and test review  
**Reviewed phase:** 2L.2G.3.8 — remediation of R-01, R-02, R-03 and preservation of F-01 through F-09  
**Implementation scope:** Local mock-only controller service and SQLite persistence  
**Review decision:** **CONDITIONAL**  
**Live status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

---

## 1. Executive decision

The 3.8 implementation substantially improves the controller and closes R-01 and the R-03 disclosure path. However, the unconditional **PASS** reported by 3.8 is not independently sustained.

| Item | Independent classification |
|---|---|
| R-01 — install failure-state persistence and error sanitization | **VERIFIED CLOSED** |
| R-02 — canonical caller-identifier validation before store/persistence | **PARTIALLY CLOSED** |
| R-03 — invalid stored idempotency digest must fail closed before replay | **VERIFIED CLOSED** at the service boundary |
| F-01 through F-09 | **VERIFIED CLOSED** in the mock scope |
| Overall local mock-only implementation | **CONDITIONAL** |
| Real transport / privileged host integration | **NOT AUTHORIZED / NOT REVIEWED** |

Two new low-severity R-02 alternate-entry-point findings were reproduced:

1. **F-3.9-01 — `health_check` bypasses caller-identifier validation and can persist an idempotency record for a malformed identifier.**
2. **F-3.9-02 — `reconcile_pending_operations` bypasses caller-identifier validation before the ownership lookup.**

Both are reachable by an already-authorized caller. Neither bypasses authentication, changes ownership state, invokes the privileged backend with an invalid ownership record, or discloses a cached idempotent response. They are validation, error-contract, and data-integrity defects, not privilege-escalation defects. R-02 nevertheless fails its stated acceptance criterion that malformed identifiers be rejected before **any** store access or idempotency persistence.

No Critical, High, or Medium finding was identified. R-02 requires a small source fix and regression tests in a separately authorized change. Until then, the correct gate is **CONDITIONAL**, not PASS, and live firewall integration remains unauthorized.

---

## 2. Scope, evidence standard, and limitations

### 2.1 Scope

This review independently inspected:

- Actual controller source, persistence implementation, authorization and helper-contract boundaries.
- Public entry points and the shared `_call` path, including pre-validation, ownership lookup, idempotency replay, operation dispatch, persistence failure handling, and reconciliation.
- Actual test source and test execution, not merely reported counts.
- R-01, R-02, and R-03 behavior.
- The continued presence and behavior of F-01 through F-09.
- Cross-process concurrency, crash/restart behavior, and test database isolation.
- Django manager-client tests and Django system checks.

### 2.2 Independence and non-modification

- No source or test file was modified during this review.
- No remediation was implemented.
- The only deliverable artifact created by this review is this document; no source or test file was changed.
- Adversarial probes were run as temporary, external Python snippets or here-strings against the current source. They did not alter the repository.
- Test counts in this document are from commands executed during this review, not copied from the 3.8 report.

### 2.3 Explicit limitations

This review did **not** and does **not** authorize:

- UDS or `SO_PEERCRED` implementation or validation.
- Real privileged helper processes, sudo, capabilities, or setuid/setgid behavior.
- Live nftables/iptables/UFW operations.
- Routing, NAT, conntrack, systemd, host, or Docker operations.
- Provisioning, cloud, or production database access.
- Production migration or production integrity validation.

The reviewed implementation remains a local mock-only controller with SQLite persistence. Real transport identity, real helper isolation, real firewall state, multi-host ordering, and production database integrity remain outside this review and outside the authorization gate.

---

## 3. Inspected source and principal call paths

### 3.1 Controller service

`broker/firewall_controller_service/controller_service.py`

- `_call` — shared entry path:
  - Authorization and legacy validation: lines 638-641.
  - Caller-identifier validation gate: lines 643-648.
  - Idempotency pre-check and digest conflict check: lines 653-665.
  - Ownership lookup and binding: lines 667-690.
  - Durable idempotency creation, replay, and pending handling: lines 692-742.
  - Install failure branch: lines 987-1050.
  - Health-check dispatch and completion: lines 929-930, 1131-1148.
  - Public `health_check`: lines 1150-1151.
- `_validate_identifier` and `_validate_caller_identifiers`: lines 191-216.
- `_validate_authoritative_optional_identifier`: lines 219-230.
- `_validated_stored_idempotency_digest`: lines 259-282.
- `_idempotency_replay_decision`: lines 285-313.
- `_validate_replay`: lines 386-426.
- `_req_digest` and `_DIGEST_FIELDS`: lines 138-167.
- `_has_revocation_evidence`: lines 466-480.
- `_read_back_revoke`, `_store_verification_evidence`, and revoke completion: lines 482-537, 900-915, 1108-1129.
- `reconcile_pending_operations`: lines 1172-1260.
- `_raise_install_failure_persistence_error`: lines 233-257.

### 3.2 Persistence and boundaries

- `broker/firewall_controller_service/ownership_store.py`
  - Schema: lines 16-90.
  - Ownership CAS/state/lifecycle history: lines 130-243.
  - Idempotency create/get/complete: lines 313-355, 375-398.
  - Evidence: lines 448-487, 540-563.
- `broker/firewall_controller_service/authorization_strict.py` — strict allowlist and explicit-empty handling.
- `broker/firewall_controller_service/helper_contract.py` — helper ID/digest contract.
- `broker/firewall_controller_service/mock_helper_executor.py` — mock helper boundary, identity provider, idempotency.
- `broker/firewall_controller_service/mock_backend.py` — controller-to-helper adapter; strips caller-supplied auth claims and peer identity.
- `broker/firewall_controller_service/errors.py` — `FirewallControllerPersistenceError`.
- `broker/app/firewall_controller_contract.py` — legacy `_validate_request`; coercion only in returned object.
- `broker/app/db.py` — `BrokerDBError`.
- `broker/tests/conftest.py` — test database isolation.

### 3.3 Test source inspected

- `broker/tests/test_firewall_controller_residual_risk_remediation.py` — new R-01/R-02/R-03 suite, 69 tests.
- `broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py` — F-01 through F-09, 96 tests.
- `broker/tests/test_firewall_controller_ownership_binding_remediation.py` — ownership binding.
- `broker/tests/test_firewall_controller_revoke_lifecycle_remediation.py` — revoke lifecycle.
- `broker/tests/test_firewall_controller_persistence_failure_closure.py`.
- `broker/tests/test_firewall_controller_persistent_recovery_integration.py`.
- `broker/tests/test_firewall_controller_helper_identity_propagation.py`.
- `broker/tests/test_firewall_controller_helper_contract.py`.
- `broker/tests/test_firewall_controller_cross_process_crash_recovery.py`.
- `broker/tests/test_firewall_controller_cross_process_concurrency.py`.

---

## 4. R-01 verification — install failure-state persistence and sanitized error

### 4.1 What the implementation does

When the backend install returns a non-`ok` result, the controller attempts to persist a failable failure state and lifecycle history, records an audit event, and raises a sanitized `FirewallControllerPersistenceError` if the failure state cannot be fully persisted.

Observed behavior from source and tests:

| Scenario | State write | History write | Result |
|---|---|---|---|
| Backend failure, persistence succeeds | `FAILED` persisted | persisted | Sanitized persistence error raised; idempotency completed with the error response; same-key replay returns the persisted error |
| Backend failure, state persistence fails | Previous state preserved | Not written | Sanitized `PERSISTENCE_FAILURE`; idempotency stays `PENDING`; no false success |
| Backend failure, history persistence fails | `FAILED` persisted | Not written | Sanitized error; idempotency stays `PENDING`; details report history not persisted |
| Backend failure, failure-state read unavailable | Previous state may remain | Not written | Sanitized `persistence_unavailable`; idempotency stays `PENDING` |
| Advanced or uncertain state already present | Must not be overwritten | Must not be overwritten | Error is raised; state remains advanced; idempotency stays `PENDING` |
| Fresh-key recovery after DB restoration | Failure state persisted | Persisted | New key can proceed; old key remains recoverable/blocked |

Source evidence:

- Install failure path: `controller_service.py:987-1050`.
- Sanitized error construction: `controller_service.py:233-257`.
- `FirewallControllerPersistenceError` with `PERSISTENCE_FAILURE`: `errors.py:18-22`.

### 4.2 Independent checks

The new suite executed successfully, including:

- `test_install_backend_failure_persists_failed_state_and_history`
- `test_install_failure_state_write_failure_is_sanitized`
- `test_install_failure_history_write_failure_is_sanitized_and_not_overclaimed`
- `test_install_failure_does_not_overwrite_advanced_or_uncertain_state`
- `test_install_failure_persistence_recovery_after_db_available`

Additional database-unavailable probe:

```text
EXCEPTION FirewallControllerPersistenceError
  Install failure could not be fully persisted
  error_code=PERSISTENCE_FAILURE
  details={'operation': 'install_policy', 'backend_error_code': 'INSTALL_FAILED',
           'failure_state_persisted': False, 'lifecycle_history_persisted': False,
           'reason': 'persistence_unavailable'}
STATE REQUESTED
IDEM PENDING
```

This confirms that a database failure during the failure-persistence path does not produce a false success, does not overwrite ownership state, and leaves the idempotency record pending.

### 4.3 Classification

**R-01: VERIFIED CLOSED.**

The failure-state persistence behavior, no-overwrite behavior, CAS behavior, sanitized error classification, and fresh-key recovery are supported by source, tests, and an independent database-unavailable probe.

### 4.4 Informational observation — suppressed exception context

`raise ... from None` suppresses traceback display, but the raw `BrokerDBError` remains accessible as `__context__`:

```text
CONTEXT_TYPE BrokerDBError
CONTEXT_STR database unavailable: secret detail
SUPPRESS True
CAUSE None
```

Normal traceback formatting honors `__suppress_context__`, so this is not a user-visible leak in the default path. It is recorded as **I-3.9-03** rather than reopening R-01. Callers must not explicitly serialize `exc.__context__` or a custom exception-chain walker.

---

## 5. R-02 verification — canonical caller-identifier validation

### 5.1 Expected behavior

For every applicable entry point where `policy_id`, `instance_id`, or `network_id` enter the service:

1. Validate the original request values, not a coerced copy.
2. Reject malformed, non-canonical, explicitly empty optional values, unsupported types, and control characters before any ownership lookup or persistence.
3. Do not create ownership or idempotency records for an invalid request.
4. Preserve documented omitted/`None` optional semantics.
5. Do not pass unsupported SQL binding values to SQLite.

### 5.2 What is correctly implemented

`_validate_caller_identifiers` applies `_ID_RE.fullmatch` to `policy_id` and to explicitly supplied `instance_id`/`network_id`. Omitted or `None` optional values remain supported; explicit empty strings are rejected.

The five `_call`-dispatched policy operations were independently probed with `policy_id='p1\n'` and `policy_id=['p1']`:

```text
install_policy      newline/list  PermissionError: Invalid policy_id  store_calls=0
inspect_policy      newline/list  PermissionError: Invalid policy_id  store_calls=0
verify_policy       newline/list  PermissionError: Invalid policy_id  store_calls=0
revoke_policy       newline/list  PermissionError: Invalid policy_id  store_calls=0
remove_stale_policy newline/list  PermissionError: Invalid policy_id  store_calls=0
```

All ten combinations rejected before any store access. The new suite's install-based invalid-ID tests and optional-omission tests also pass. The helper contract independently rejects malformed optional identifiers.

### 5.3 Finding F-3.9-01 — `health_check` bypasses caller-identifier validation and persists invalid idempotency data

- **Unique ID:** F-3.9-01
- **Severity:** Low
- **Affected file/function:** `broker/firewall_controller_service/controller_service.py` — `_call` line 647 and `health_check` line 1150.
- **Status:** OPEN — causes R-02 to be **PARTIALLY CLOSED**.

**Concrete scenario:**

1. An authorized caller sends `health_check` with the required shape fields and an idempotency key.
2. `_call` explicitly skips `_validate_caller_identifiers` for `health_check` (`if operation != 'health_check'`).
3. The legacy validator requires `policy_id`, `policy_version`, and `compiled_rule_digest` for health check (`firewall_controller_contract.py:52-56`), so the malformed identifier is part of the accepted request shape.
4. `_req_digest` accepts the malformed string or list.
5. The controller performs `get_by_policy(policy_id, policy_version)`.
6. With a non-empty malformed string such as `'p1\n'` and no matching ownership, the controller creates an idempotency record and completes it after the backend health check returns.
7. With an unsupported value such as `['p1']`, SQLite raises a raw `BrokerDBError` from the binding operation.

**Reproduced evidence:**

```text
health_check newline
  status=ok
  store=get_idempotency_record,get_by_policy,create_idempotency_record,complete_idempotency_record
  idem=COMPLETED resource_key='p1\n:1'

health_check list
  EXCEPTION BrokerDBError
  DB error: Error binding parameter 0 - probably unsupported type.
  store=get_idempotency_record,get_by_policy

health_check explicit empty instance/network
  status=ok
  store=get_idempotency_record,get_by_policy,create_idempotency_record,complete_idempotency_record
  idem=COMPLETED resource_key='health:1'
```

**Impact:**

- A malformed identifier bypasses the R-02 canonical gate.
- An invalid request durably creates a `COMPLETED` idempotency row with the malformed value in `resource_key` and in the request digest.
- An unsupported SQL type reaches the store and returns a raw database binding error instead of the canonical permission/request error.
- No ownership record is created, no lifecycle state is changed, and no privileged firewall operation is performed. There is no privilege escalation.
- The issue is a validation-contract, error-handling, and data-integrity defect. It is Low because it requires an already-authorized caller and does not cross an authorization boundary.

**Required remediation (not implemented in this review):**

- Apply canonical caller-identifier validation to `health_check` whenever `policy_id`, `instance_id`, or `network_id` are present; or remove those fields from the health-check contract and stop persisting them in idempotency metadata.
- Ensure malformed `health_check` input cannot reach `get_by_policy` or `create_idempotency_record`.
- Add regression tests covering `health_check` with newline, list, control-character, explicitly empty optional, and unsupported-type identifiers, asserting no store access and no idempotency/ownership persistence.
- Verify the fix does not break valid health-check requests such as `policy_id='health'`, `policy_version=0`, `compiled_rule_digest='0'*64`, with omitted optional identifiers.

**Real transport/host validation required to reproduce:** No. This is a local service validation defect.

### 5.4 Finding F-3.9-02 — `reconcile_pending_operations` bypasses validation before ownership lookup

- **Unique ID:** F-3.9-02
- **Severity:** Low
- **Affected file/function:** `broker/firewall_controller_service/controller_service.py` — `reconcile_pending_operations`, lines 1172-1190.
- **Status:** OPEN — contributes to R-02 **PARTIALLY CLOSED**.

**Concrete scenario:**

1. An authorized caller sends a reconciliation request with the required shape fields.
2. `auth.authorize` and legacy `validator.validate` pass for a non-empty malformed `policy_id` such as `'p1\n'`, an unsupported value such as `['p1']`, or an explicitly empty `instance_id`/`network_id`.
3. The method immediately calls `get_by_policy(policy_id, policy_version)`.
4. `_validate_caller_identifiers` is never called on this path.

**Reproduced evidence:**

```text
reconcile newline
  status=ok
  uncertain=[{'policy_id': 'p1\n', 'policy_version': 1,
              'reason': 'no_ownership_no_adoption'}]
  store=get_by_policy

reconcile list
  EXCEPTION BrokerDBError
  DB error: Error binding parameter 0 - probably unsupported type.
  store=get_by_policy

reconcile explicit empty instance/network
  status=ok
  reason=no_ownership_no_adoption
  store=get_by_policy
```

**Impact:**

- Invalid identifiers are accepted and an invalid request can return `status: ok`.
- Unsupported types reach SQLite and produce a raw `BrokerDBError`.
- The validation-before-store requirement is violated.
- No ownership record, lifecycle history, idempotency record, or backend action is created on the reproduced no-record path.
- No privilege escalation or cached-response disclosure occurs. This is Low.

**Required remediation (not implemented in this review):**

- In `reconcile_pending_operations`, validate the original request identifiers after authorization/legacy validation and before `get_by_policy`.
- Preserve full-scan reconciliation when no policy-specific identifiers are supplied. A practical fix is to validate the fields that are present and required for a policy-specific lookup, or call a reconciliation-specific validator that permits the no-`policy_id` full-scan mode.
- Add regression tests for newline, list, explicitly empty optional, and unsupported-type values on the policy-specific reconciliation path, asserting rejection before store access.
- Add a test that a full-scan reconciliation with no identifiers still works.

**Real transport/host validation required to reproduce:** No. This is a local service validation defect.

### 5.5 R-02 remaining field-scope limitation

The 3.8 report documents that validation of `request_id`, `operation_id`, `idempotency_key`, and ownership-reference fields was not expanded into a controller-wide gate. That remains an informational, pre-existing scope limitation. It is not counted as a new 3.9 finding because 3.8 explicitly scoped it out and the helper contract/ownership checks remain in force.

### 5.6 R-02 classification

**R-02: PARTIALLY CLOSED.**

The five `_call` policy operations are correctly hardened, but two reachable entry points bypass the gate:

- `health_check` (F-3.9-01) — can persist invalid idempotency data.
- `reconcile_pending_operations` (F-3.9-02) — can access the store and return success for invalid identifiers.

The 3.8 claim that validation occurs before **any** ownership lookup or idempotency persistence is therefore false for the current source.

---

## 6. R-03 verification — stored idempotency digest fail-closed behavior

### 6.1 Implementation

`_validated_stored_idempotency_digest` requires a non-empty string matching exactly 64 lowercase or uppercase hexadecimal characters. It is called:

- Before the cached replay decision in the `_call` pre-check (`controller_service.py:661-665`).
- Again during the late concurrency re-check (`controller_service.py:683-689`).
- For the replay decision itself (`_idempotency_replay_decision`, lines 285-313).

On failure it raises `FirewallControllerIdempotencyError` with the documented corrupt-digest reason, emits a best-effort `idempotency_digest_corrupt` audit event, does not return the cached response, and does not repair the stored row. `_validate_replay` additionally binds replay to the current authoritative ownership record and identity snapshot; a different authorized peer fails the request-digest comparison because `_req_digest` includes `peer_uid` and `peer_gid`.

### 6.2 Independent evidence

The new suite executed:

- `test_corrupt_stored_digest_denies_replay_without_disclosure` for `None`, empty, non-hex, 63-character, 65-character, and invalid-hex values, plus integer and bytes values.
- `test_corrupt_digest_audit_failure_does_not_prevent_denial`.
- `test_valid_digest_with_matching_peer_and_ownership_replays`.
- `test_valid_digest_with_different_authorized_peer_is_rejected`.
- `test_corrupt_digest_after_process_restart_denies_and_is_not_repaired`.
- `test_concurrent_replay_with_corrupt_digest_never_returns_cached_response`.

The 3.6 hardening suite additionally executed F-09 ownership/identity replay tests, including ownership-record replacement, in-place instance change, and family change.

### 6.3 Classification

**R-03: VERIFIED CLOSED at the service boundary.**

The originally reported disclosure path — an empty or invalid stored digest allowing a cached response to be returned to a different authorized peer — is closed by the service boundary. The corrupt row is denied and audited, not repaired. The digest is validated before cached-response disclosure on the `_call` path.

### 6.4 Informational residual — no database CHECK/migration validation

The `controller_idempotency.request_digest` column is `TEXT NOT NULL` but has no database `CHECK` constraint or migration-level format validation (`ownership_store.py:56-70`). This is recorded as **I-3.9-01**. It does not reopen the R-03 disclosure path because all service reads validate the digest before disclosure, but a future migration/import could still write invalid data that is only rejected at the service boundary. The 3.8 report already documents this limitation.

---

## 7. Concurrency, replay, and persistence analysis

### 7.1 Late idempotency re-check

The late re-check at `controller_service.py:671-690` runs only after `_validate_ownership_binding` raises `PermissionError`. It reads the idempotency row and validates the stored digest; it does not write, create ownership, return a cached response, or call the backend. It either raises the documented idempotency conflict for a different payload or re-raises the permission error.

Independent source review and the F-09 tests support that this ordering does not expose a cached response before ownership/identity validation. No new issue was reproduced.

### 7.2 Same-key concurrency

- `test_cross_process_identical` passed 20/20 repeated process-pool runs.
- `test_xproc_conflicting_idempotency_same_key` passed 20/20 repeated process-pool runs.
- The full cross-process/crash suite passed 10/10.

The repeated runs used the pytest harness without a manually exported controller DB path. They therefore exercised the harness isolation described in section 11.

### 7.3 Transaction boundaries

- Ownership state updates and lifecycle history writes are separate operations; R-01 explicitly handles partial persistence and never reports false success.
- Ownership state transitions use a lifecycle-version CAS with a hard 409-style failure if the row changed.
- Idempotency records are durable SQLite rows with `PENDING`/`COMPLETED` states; a failure that cannot complete persistence leaves `PENDING` rather than fabricating success.
- The reviewed concurrency model is local SQLite only. Multi-host/distributed ordering is not validated.

### 7.4 Restart and recovery

R-03 corrupt-digest denial survives process restart and does not repair the row. R-01 fresh-key recovery works after database restoration. Cross-process crash/recovery tests passed. No regression in F-01 through F-09 was found.

---

## 8. F-01 through F-09 preservation

The 3.6 hardening suite was executed independently: **96 passed, 1 warning, 0 skipped, exit 0**. Source inspection and the new R-01/R-02/R-03 tests did not reveal a regression.

| ID | Property | Classification | Evidence |
|---|---|---|---|
| F-01 | Same-key uncertain revoke readback/recovery; no duplicate revoke | **VERIFIED CLOSED** | Revoke branch and `_read_back_revoke`; hardening tests lines 273-467 |
| F-02 | Reconciliation persistence-failure propagation; no false success | **VERIFIED CLOSED** | `reconcile_pending_operations` lines 1195-1200, 1469-1475; tests lines 473-578 |
| F-03 | Unknown lifecycle state preserved, not rewritten | **VERIFIED CLOSED** | Lines 1202, 1246-1259; tests lines 586-633 |
| F-04 | Address-family evidence binding | **VERIFIED CLOSED** | `_record_family`, `_has_revocation_evidence`; tests lines 640-714 |
| F-05 | Canonical full idempotency request digest | **VERIFIED CLOSED** | `_DIGEST_FIELDS`, `_req_digest`; tests lines 720-820 |
| F-06 | Evidence-backed `REVOKED` completion | **VERIFIED CLOSED** | Evidence/store/CAS paths lines 428-480, 931-936, 1439-1456; tests lines 826-888 |
| F-07 | Strict full-string identifier/digest matching | **VERIFIED CLOSED** | `_ID_RE`, `_DIGEST_RE`, helper contract; tests lines 905-954 |
| F-08 | Strict auth explicit-empty allowlist fails closed | **VERIFIED CLOSED** | `authorization_strict.py`; tests lines 960-1008 |
| F-09 | Replay bound to ownership and identity snapshot | **VERIFIED CLOSED** | `_validate_replay` lines 386-426; tests lines 1014-1130 |

No F-01 through F-09 regression is reported.

---

## 9. Additional findings and observations

### 9.1 F-3.9-01 — `health_check` R-02 validation bypass

- **Severity:** Low
- **Affected:** `controller_service.py:_call` (line 647) and `health_check` (line 1150)
- **Impact:** invalid identifiers accepted; malformed value persisted in a completed idempotency record; raw SQLite binding error for unsupported types
- **Evidence:** probe output in section 5.3
- **Remediation:** validate health-check caller identifiers before store access/persistence, or remove identifier persistence from health check; add regression tests
- **Real transport/host validation required:** No

### 9.2 F-3.9-02 — `reconcile_pending_operations` R-02 validation bypass

- **Severity:** Low
- **Affected:** `controller_service.py:reconcile_pending_operations` (lines 1172-1190)
- **Impact:** malformed identifiers reach store; invalid request can return `status: ok`; raw SQLite binding error for unsupported types; no ownership/idempotency creation on reproduced path
- **Evidence:** probe output in section 5.4
- **Remediation:** validate identifiers before `get_by_policy`; preserve full-scan mode; add regression tests
- **Real transport/host validation required:** No

### 9.3 I-3.9-01 — No database `CHECK` constraint for digest format

- **Severity:** Informational
- **Affected:** `ownership_store.py` schema lines 56-70; R-03 service boundary
- **Scenario:** an external migration/import writes an empty or malformed `request_digest`
- **Impact:** defense-in-depth only; service validation denies disclosure, so the R-03 exploit remains closed
- **Evidence:** schema inspection; R-03 tests
- **Remediation:** add a future migration/`CHECK` constraint for 64-hex format after separate approval and row validation
- **Real transport/host validation required:** Database migration validation is separate; no live firewall validation required

### 9.4 I-3.9-02 — 3.8 report’s test-database contamination explanation is inaccurate

- **Severity:** Informational
- **Affected:** `docs/PHASE_2L_2G_3_8_RESIDUAL_RISK_REMEDIATION.md` lines 397-402 and 488-490; `broker/tests/conftest.py` lines 18-25
- **Observation:** the 3.8 report says an initial combined invocation reused the repository default controller DB and that the cross-process test expects a fresh DB when no environment override is set. The pytest harness unconditionally sets `FIREWALL_CONTROLLER_DB_PATH` to a per-process `tempfile.mkdtemp()` path before broker imports. Spawned child processes inherit that environment. The harness therefore does not use the repository default DB under normal pytest execution.
- **Evidence:** `conftest.py` creates `flaghunt-broker-test-storage-*` and sets `FIREWALL_CONTROLLER_DB_PATH` at line 25; repeated cross-process runs passed 20/20 without a manual override; cross-process crash tests also create explicit temp DBs.
- **Impact:** documentation/reproducibility issue, not a demonstrated implementation defect. The cause of the earlier reported failure remains unexplained and should not be attributed to default-DB contamination without evidence.
- **Remediation:** correct the 3.8 report or record the actual earlier failure cause; no source change required for this observation.
- **Real transport/host validation required:** No

### 9.5 I-3.9-03 — Suppressed exception context still retains raw persistence details

- **Severity:** Informational
- **Affected:** `controller_service.py:_raise_install_failure_persistence_error` lines 233-257
- **Observation:** `from None` sets `__suppress_context__`, but `__context__` still points at the raw `BrokerDBError`; a caller that serializes `__context__` can recover the raw message.
- **Evidence:** independent probe in section 4.4; tests assert `__cause__ is None` and `__suppress_context__ is True`.
- **Impact:** no user-visible leak in default traceback formatting; potential leak only through nonstandard exception-chain serialization.
- **Remediation:** if strict sanitization is desired, raise the sanitized exception outside the `except` block or clear `__context__` before raising, and add a test.
- **Real transport/host validation required:** No

---

## 10. Exact test and check results

All commands were run from `E:\Flag-hunt\ctf-platform-be` using the project virtual environment. Each command exited 0 unless stated otherwise. No test was skipped.

### 10.1 New R-01/R-02/R-03 suite

```powershell
cmd /c ".\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_residual_risk_remediation.py -q 2>&1"
```

Result: **69 passed, 1 warning in 18.70s**. Exit 0. Skipped: 0.

### 10.2 3.6 hardening suite (F-01 through F-09)

```powershell
cmd /c ".\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_revoke_recovery_and_idempotency_hardening.py -q 2>&1"
```

Result: **96 passed, 1 warning in 33.87s**. Exit 0. Skipped: 0.

### 10.3 Ownership and revoke lifecycle

```powershell
cmd /c ".\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_ownership_binding_remediation.py broker\tests\test_firewall_controller_revoke_lifecycle_remediation.py -q 2>&1"
```

Result: **38 passed, 1 warning in 22.07s**. Exit 0. Skipped: 0.

### 10.4 Persistence and recovery

```powershell
cmd /c ".\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_persistence_failure_closure.py broker\tests\test_firewall_controller_persistent_recovery_integration.py -q 2>&1"
```

Result: **40 passed, 1 warning in 15.98s**. Exit 0. Skipped: 0.

### 10.5 Helper identity and contract

```powershell
cmd /c ".\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_helper_identity_propagation.py broker\tests\test_firewall_controller_helper_contract.py -q 2>&1"
```

Result: **80 passed, 1 warning in 2.22s**. Exit 0. Skipped: 0.

### 10.6 Cross-process and crash recovery

```powershell
cmd /c ".\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_cross_process_crash_recovery.py broker\tests\test_firewall_controller_cross_process_concurrency.py -q 2>&1"
```

Result: **10 passed, 1 warning in 12.40s**. Exit 0. Skipped: 0.

Additional repetition:

- `test_cross_process_identical`: **20/20 passed**.
- `test_xproc_conflicting_idempotency_same_key`: **20/20 passed**.

### 10.7 Full controller suite

```powershell
$files = Get-ChildItem broker\tests\test_firewall_controller*.py | ForEach-Object { $_.FullName }
& .\venv\Scripts\python.exe -m pytest $files -q 2>&1
```

Result: **412 passed, 1 warning in 134.63s**. Exit 0. Skipped: 0.

### 10.8 Full `broker/tests`

```powershell
cmd /c ".\venv\Scripts\python.exe -m pytest broker\tests -q 2>&1"
```

Result: **515 passed, 1 warning in 133.23s**. Exit 0. Skipped: 0.

### 10.9 Django manager-client tests

```powershell
cmd /c ".\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client -v 1 2>&1"
```

Result: **33 tests, OK in 0.087s**. Exit 0. `System check identified no issues (0 silenced).`

### 10.10 Django system check

```powershell
cmd /c ".\venv\Scripts\python.exe manage.py check 2>&1"
```

Result: `System check identified no issues (0 silenced).` Exit 0.

### 10.11 Warnings and skips

- Each pytest run reports the pre-existing Pydantic class-based `config` deprecation warning.
- The environment also emits a `PytestDeprecationWarning` about the unset `asyncio_default_fixture_loop_scope` on stderr before collection; it is not a test failure and is not counted in the pytest warning summary.
- No test was skipped.
- No test failed.

---

## 11. Test database isolation

### 11.1 Harness behavior

`broker/tests/conftest.py` lines 18-25:

- Creates a per-pytest-process temporary directory with prefix `flaghunt-broker-test-storage-`.
- Sets `BROKER_DB_PATH`, `BROKER_AUDIT_DB_PATH`, and `BROKER_RECOVERY_DB_PATH` with `setdefault`.
- Unconditionally sets `FIREWALL_CONTROLLER_DB_PATH` to the temporary controller database path before broker imports.

The cross-process concurrency test creates services without passing an explicit store, so they resolve to the harness-provided temporary controller DB. Spawned child processes inherit the environment. The cross-process crash-recovery test additionally creates explicit `tempfile.mkdtemp()` database and backend files.

### 11.2 Conclusion

Under normal pytest execution, the harness cannot accidentally read or mutate `broker/data/firewall_controller.db` or another developer database. The repeated 20/20 cross-process runs and the full suites support this.

The 3.8 report’s explanation of an initial default-DB contamination is not supported by the harness. This is recorded as **I-3.9-02**. It does not invalidate the passing test results, but it is an inaccurate reproducibility claim. If the earlier failure was a real race, it needs a separate explanation and reproduction.

Outside normal pytest execution (for example, running a test module directly without conftest or with `--noconftest`), this isolation does not apply. That is not the reviewed harness.

---

## 12. Real transport and host limitations

The following remain explicitly outside the review and are **not authorized**:

- UDS peer identity and `SO_PEERCRED` behavior.
- Real helper process identity, helper authorization, and helper contract over a real transport.
- Privileged helper execution, sudo, capabilities, and filesystem/namespace isolation.
- Real nftables/iptables/UFW state, transaction semantics, and rollback.
- Routing, NAT, conntrack, systemd, host, and Docker effects.
- Multi-host SQLite/DB locking and distributed ordering.
- Production database migration, row validation, and integrity guarantees.
- Production secrets, logging, and operational monitoring.

The current evidence is local mock-only evidence. A conditional pass for that scope is not a live-firewall authorization.

---

## 13. Implementation gate and required next steps

### 13.1 Gate

**CONDITIONAL — local mock-only implementation.**

- R-01 and the R-03 disclosure path are closed at the reviewed service boundary.
- F-01 through F-09 remain intact.
- R-02 is not fully closed because `health_check` and `reconcile_pending_operations` bypass the caller-identifier gate.
- No live firewall, routing, NAT, conntrack, systemd, host, Docker, provisioning, cloud, or production database operation is authorized.

### 13.2 Required before an unconditional local PASS

1. Fix F-3.9-01: validate `health_check` identifiers before any store access or idempotency persistence, or remove identifier persistence from health check.
2. Fix F-3.9-02: validate identifiers before `get_by_policy` in policy-specific reconciliation, while preserving full-scan reconciliation.
3. Add regression tests for both paths: newline, list, control characters, explicitly empty optional values, unsupported types, and valid omitted/`None` optional values.
4. Re-run the new suite, 3.6 hardening suite, ownership/revoke, persistence/recovery, helper identity/contract, cross-process/crash, full controller, full `broker/tests`, Django manager-client tests, and `manage.py check`.
5. Correct or substantiate the 3.8 test-isolation explanation (I-3.9-02).
6. Optionally add the DB-level digest constraint/migration validation (I-3.9-01) and strict exception-context clearing (I-3.9-03) in a separately authorized change.

### 13.3 Explicit non-authorization

This review does **not** authorize:

- Live firewall integration.
- Real privileged helper deployment.
- UDS or peer-credential implementation.
- Production database migration.
- Any change to source or tests without separate approval.

**Final status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.**
