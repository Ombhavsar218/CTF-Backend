# Phase 2L.2G.3.10 — Targeted Identifier Validation Remediation

**Project:** Flaghunt  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Scope:** Local mock-only firewall controller  
**Date:** 2026-11-13  
**Implementation status:** **PASS — targeted remediation of F-3.9-01 and F-3.9-02**  
**Integration gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

No real transport, UDS/`SO_PEERCRED`, privileged helper, sudo/capability, firewall, routing,
NAT, conntrack, systemd/host, Docker, provisioning, cloud, or production database operation was
performed or authorized.

---

## 1. Executive summary

The two Low-severity findings from
`docs/PHASE_2L_2G_3_9_INDEPENDENT_RESIDUAL_RISK_SECURITY_REVIEW.md` are addressed in the service
boundary:

| Finding | Original severity | Outcome |
|---|---|---|
| F-3.9-01 — `health_check` bypasses canonical caller-identifier validation | Low | **CLOSED in implementation** |
| F-3.9-02 — `reconcile_pending_operations` bypasses validation before ownership lookup | Low | **CLOSED in implementation** |
| I-3.9-01 — no database `CHECK` constraint for stored digest format | Informational | **Documented; no migration added** |
| I-3.9-02 — 3.8 test-isolation explanation inaccurate | Informational | **Corrected in the 3.8 report** |
| I-3.9-03 — suppressed exception context retains raw persistence details | Informational | **Residual in-process risk documented; no external disclosure path found** |

Both findings now fail before any ownership-store, idempotency-store, or backend access.
Invalid identifiers produce the established `PermissionError("Invalid <field>")` validation
error, not raw SQLite binding exceptions. No invalid request creates an idempotency record,
ownership record, lifecycle transition, evidence record, or backend action.

The targeted implementation passes all required suites, including the complete `broker/tests`
suite. Independent review was **not** started by this phase.

---

## 2. Original findings

### 2.1 F-3.9-01 — `health_check` validation bypass

- **Severity:** Low.
- **Affected path:** `FirewallControllerService._call` skipped
  `_validate_caller_identifiers` when `operation == "health_check"`.
- **Scenario:** An already-authorized caller supplied the required legacy health-check shape
  fields plus an idempotency key and a malformed `policy_id`, an unsupported type, or explicitly
  empty optional identifiers.
- **Observed pre-remediation behavior:**
  - `policy_id='p1\n'` returned `status: ok` and persisted a completed idempotency record with
    `resource_key='p1\n:1'`.
  - `policy_id=['p1']` reached SQLite and raised a raw
    `BrokerDBError: DB error: Error binding parameter 0 - probably unsupported type.`
  - Explicitly empty `instance_id`/`network_id` were accepted.

### 2.2 F-3.9-02 — reconciliation validation bypass

- **Severity:** Low.
- **Affected path:** `reconcile_pending_operations` called `get_by_policy` before any canonical
  caller-identifier validation.
- **Scenario:** An authorized caller supplied malformed or unsupported identifiers.
- **Observed pre-remediation behavior:**
  - `policy_id='p1\n'` returned `status: ok` with an `uncertain` result for the malformed ID.
  - `policy_id=['p1']` raised a raw `BrokerDBError` from the SQLite binding operation.
  - Explicitly empty `instance_id`/`network_id` were accepted.

### 2.3 Informational findings

- **I-3.9-01:** `controller_idempotency.request_digest` is `TEXT NOT NULL` but has no database
  `CHECK` constraint or migration-level format validation.
- **I-3.9-02:** The 3.8 report attributed an earlier default-database test failure to the
  absence of an environment override, but `broker/tests/conftest.py` sets
  `FIREWALL_CONTROLLER_DB_PATH` to a fresh temporary path before broker imports.
- **I-3.9-03:** `FirewallControllerPersistenceError` is raised with `from None`, which suppresses
  normal traceback context but does not delete the raw `BrokerDBError` retained in
  `exception.__context__`.

---

## 3. Root cause

### 3.1 Health check

`health_check` is implemented through the shared `_call` path, but `_call` contained an explicit
operation-name exception:

```python
if operation != 'health_check':
    self._validate_caller_identifiers(req)
```

The legacy request validator still requires `policy_id`, `policy_version`, and
`compiled_rule_digest` for health checks. As a result, health checks could carry caller-supplied
identifiers past the canonical gate, compute an idempotency digest, access ownership storage, and
persist an idempotency record.

### 3.2 Reconciliation

`reconcile_pending_operations` does not use `_call`. It performed:

```text
authorize -> legacy validate -> read policy_id/policy_version -> get_by_policy
```

The canonical identifier gate was never invoked on this path. Non-empty malformed strings passed
through to the store; unsupported types reached SQLite parameter binding.

### 3.3 Shared validation design

The existing canonical validator already had the required behavior:

- `_ID_RE = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")`
- non-string, empty, overlong, whitespace/control-character, newline/CR, and other malformed
  values raise `PermissionError("Invalid <field>")`;
- omitted optional identifiers and explicit `None` are accepted;
- explicitly supplied empty optional identifiers are rejected;
- no list, dictionary, or arbitrary object is coerced into a string.

The validator needed a small extension to support reconciliation's documented no-`policy_id`
full-scan mode without duplicating validation logic.

---

## 4. Changed files

| File | Change |
|---|---|
| `broker/firewall_controller_service/controller_service.py` | `_validate_caller_identifiers` accepts `require_policy`; `_call` now always invokes it; `reconcile_pending_operations` invokes it before store access. |
| `broker/tests/test_firewall_controller_identifier_validation_entrypoints.py` | New 87-test suite covering health-check and reconciliation validation, no-store/no-backend assertions, no mutation, valid behavior, and full-scan behavior. |
| `docs/PHASE_2L_2G_3_10_TARGETED_IDENTIFIER_VALIDATION_REMEDIATION.md` | This report. |
| `docs/PHASE_2L_2G_3_8_RESIDUAL_RISK_REMEDIATION.md` | Corrected the two inaccurate test-isolation statements. No unrelated historical report was changed. |

No authorization, ownership-binding, lifecycle, evidence, helper-identity, transport, or backend
implementation was changed.

---

## 5. Canonical validation call paths

### 5.1 Shared `_call` gate

All six `_call`-dispatched operations now use the same ordering:

```text
request_received
  -> authorization
  -> legacy request-shape validation
  -> canonical caller-identifier validation
  -> idempotency pre-read / digest comparison
  -> ownership lookup and binding validation
  -> idempotency reservation/replay
  -> backend operation
  -> persistence/evidence/lifecycle completion
```

The canonical gate is located at
`broker/firewall_controller_service/controller_service.py` in `_call` immediately after
authorization and legacy validation. It runs before `_req_digest`, `get_idempotency_record`,
`get_by_policy`, idempotency creation, or backend access.

### 5.2 Reconciliation gate

`reconcile_pending_operations` now uses:

```text
authorize -> legacy validate -> canonical validation -> get_by_policy / list_ownerships
```

The call is:

```python
self._validate_caller_identifiers(req, require_policy=policy_id is not None)
```

- When `policy_id` is supplied, canonical policy validation is required.
- When `policy_id` is omitted for the documented full-scan mode, a supplied `instance_id` or
  `network_id` is still canonical-validated.
- The existing full-scan behavior is preserved; it is not replaced with a second validation
  implementation.

### 5.3 Entry-point validation coverage matrix

| Public controller entry point | Dispatch path | Canonical validation location | Validation before store/backend? |
|---|---|---|---|
| `health_check` | `_call("health_check", ...)` | `_call` canonical gate | Yes |
| `install_policy` | `_call("install_policy", ...)` | `_call` canonical gate | Yes |
| `inspect_policy` | `_call("inspect_policy", ...)` | `_call` canonical gate | Yes |
| `verify_policy` | `_call("verify_policy", ...)` | `_call` canonical gate | Yes |
| `revoke_policy` | `_call("revoke_policy", ...)` | `_call` canonical gate | Yes |
| `remove_stale_policy` | `_call("remove_stale_policy", ...)` | `_call` canonical gate | Yes |
| `reconcile_pending_operations` | Direct method | Reconciliation canonical gate | Yes |

`MockControllerTransport` is a mock facade that injects peer identity and delegates to the
service; it does not add a second validation path. The legacy `MockFirewallController` in
`broker.app.firewall_controller` is a separate mock contract and was not changed.

---

## 6. Behavior after remediation

| Input | Result |
|---|---|
| `policy_id='p1\n'` on health check | `PermissionError("Invalid policy_id")`; no store/backend access |
| `policy_id=['p1']` on health check | `PermissionError("Invalid policy_id")`; no raw `BrokerDBError` |
| Explicit empty `instance_id` or `network_id` | `PermissionError("Invalid instance_id" / "Invalid network_id")` |
| Omitted `instance_id`/`network_id` | Accepted; valid health check/reconciliation behavior preserved |
| Explicit `None` optional identifiers | Accepted; valid behavior preserved |
| Malformed `policy_id` on reconciliation | `PermissionError("Invalid policy_id")` before `get_by_policy` |
| Unsupported list/dict/object identifiers | Rejected; no string coercion |
| Whitespace, CR, tab, NUL, overlong IDs | Rejected by the canonical regex |
| Valid health check (`policy_id='health'`, version `0`, digest `0` × 64) | `status: ok`, controller identity returned, idempotency record completed |
| Valid policy-specific reconciliation | Installation state reconciled; `active_ok` for active verified policy |
| Full-scan reconciliation with no policy ID | Preserved and still functional under a permissive validator |

Validation failures occur before `_req_digest`, before any idempotency reservation, and before
any ownership lookup. No invalid request creates or mutates ownership, idempotency, lifecycle,
evidence, or backend state. Best-effort audit events may still record that the request was
received and failed validation; they do not contain store or backend mutations.

---

## 7. Regression test evidence

New suite:
`broker/tests/test_firewall_controller_identifier_validation_entrypoints.py`

Coverage includes:

- health-check `policy_id` values: trailing newline, carriage return, leading/trailing spaces,
  tab, NUL, list, dictionary, integer, boolean, bytes, and overlong values;
- health-check `instance_id` and `network_id` values: explicit empty, newline, CR, whitespace,
  tab, NUL, list, dictionary, integer, boolean, bytes, and overlong values;
- health-check omitted and explicit-`None` optional identifiers;
- valid health-check idempotent replay;
- no raw `BrokerDBError` on list-valued policy IDs;
- reconciliation invalid `policy_id`, `instance_id`, and `network_id` values;
- no store method calls on invalid health-check or reconciliation input, verified with a
  counting store wrapper;
- no backend health/inspect calls on invalid input;
- no idempotency record after invalid health-check input;
- no lifecycle or evidence mutation against a seeded installed/verified policy;
- valid policy-specific reconciliation;
- valid reconciliation with omitted and explicit-`None` optional identifiers;
- full-scan reconciliation without a policy ID;
- full-scan reconciliation rejecting a supplied malformed optional identifier.

The new suite contains **87 tests**. The established R-01/R-02/R-03 suite remains unchanged at
**69 tests**; the Phase 2L.2G.3.6 hardening suite remains unchanged at **96 tests**.

---

## 8. Test execution

All commands were run from `E:\Flag-hunt\ctf-platform-be` with the repository virtual
environment. No test was skipped or weakened.

| # | Command | Result |
|---|---|---|
| 1 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_identifier_validation_entrypoints.py -q` | **87 passed, 1 warning in 18.52s** |
| 2 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_residual_risk_remediation.py -q` | **69 passed, 1 warning in 17.00s** |
| 3 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_revoke_recovery_and_idempotency_hardening.py -q` | **96 passed, 1 warning in 30.58s** |
| 4 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_ownership_binding_remediation.py broker\tests\test_firewall_controller_revoke_lifecycle_remediation.py -q` | **38 passed, 1 warning in 20.71s** |
| 5 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_persistence_failure_closure.py broker\tests\test_firewall_controller_persistent_recovery_integration.py -q` | **40 passed, 1 warning in 13.65s** |
| 6 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_helper_identity_propagation.py broker\tests\test_firewall_controller_helper_contract.py -q` | **80 passed, 1 warning in 1.11s** |
| 7 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_cross_process_concurrency.py broker\tests\test_firewall_controller_cross_process_crash_recovery.py -q` | **10 passed, 1 warning in 7.87s** |
| 8 | PowerShell file-list invocation: `$files = Get-ChildItem -Path broker\tests -Filter 'test_firewall_controller*.py' \| Sort-Object Name \| ForEach-Object { $_.FullName }; .\venv\Scripts\python.exe -m pytest @files -q` | **499 passed, 1 warning in 125.72s** (23 controller test files) |
| 9 | `.\venv\Scripts\python.exe -m pytest broker\tests -q` | **602 passed, 1 warning in 131.02s** |
| 10 | `.\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client -v 1` | **33 tests, OK in 0.072s**; system check no issues |
| 11 | `.\venv\Scripts\python.exe manage.py check` | **System check identified no issues (0 silenced).** |

Totals:

- Failures: **0**
- Skips: **0**
- Warnings: **1 per pytest run** — the pre-existing Pydantic class-based `config` deprecation
  warning. The pre-existing `pytest-asyncio` loop-scope deprecation warning is emitted to stderr
  before collection and is not part of the pytest warning summary.
- Full controller tests increased from 412 to **499** (+87); full `broker/tests` increased from
  515 to **602** (+87). Existing suite counts are unchanged.

### 8.1 Default controller database verification

The repository default `broker/data` databases were hashed and their lengths/mtimes recorded
before and after the final test runs:

```text
broker.db              CBB570637A7F75524B12677B2455701BB0C66BD45A507FF171070BECF300CAAD
broker_audit.db        6D530C0F8A66457E148EBC39370BE972801564E5B520A2A8EA3B86C4CB1AC44F
broker_recovery.db     944D53E3C15BF489F11EC6C61857D59A4B5C10328235FE4602A109700D80E3F5
firewall_controller.db 6B4E4EA88A33BB5ABE689AD2E7D90BFB6AC29EE72ED5A0B3A4AE576573A3B440
```

Result: **DEFAULT_DB_UNCHANGED=YES** — SHA-256, file length, and mtime were identical before and
after the final full-suite runs.

---

## 9. I-3.9-03 — exception context analysis

### 9.1 Observed behavior

A controlled probe used a test-only fault store to make install-failure persistence unavailable.
The resulting exception was:

```text
TYPE                 FirewallControllerPersistenceError
STR                  Install failure could not be fully persisted
DETAILS              {"backend_error_code":"INSTALL_FAILED",
                      "failure_state_persisted":false,
                      "lifecycle_history_persisted":false,
                      "operation":"install_policy",
                      "reason":"persistence_unavailable"}
CONTEXT_TYPE         BrokerDBError
CONTEXT_STR          raw-sqlite-detail-SECRET (synthetic test marker)
SUPPRESS_CONTEXT     True
TRACEBACK_HAS_RAW    False
TRACEBACK_HAS_CONTEXT_HEADER False
```

The probe confirms:

- `str(error)` contains only the sanitized message.
- `error.details` contains only bounded operation/state/reason fields and a validated backend
  error code.
- `error.__context__` still contains the raw `BrokerDBError`.
- `error.__suppress_context__` is `True`.
- Normal traceback formatting omits both the raw context and the “During handling of the above
  exception” header.

`__suppress_context__` **does not delete** `__context__`. The raw exception object remains
reachable in-process.

### 9.2 External response and logging boundary

The firewall controller service is not wired into the FastAPI broker routes. `broker/app/main.py`
includes only the broker router; the broker routes map failures to sanitized HTTP responses such
as `HTTPException(status_code=500, detail="Internal error")`. There is no route that serializes
`FirewallControllerPersistenceError` or walks its exception chain.

The service audit path records an event such as `install_failure_persistence_failed` with the
bounded details above. `MockAuditSink` records event metadata and details, not exception objects.
`broker/app/audit.py` JSON-serializes audit event fields; it does not include exception context.
No `traceback`, `repr(exception)`, `format_exc`, or exception-chain serializer is used in the
firewall-controller service.

Therefore:

- API responses: **no context path found**.
- Serialized error payloads: **no context path found**; only explicit caller code that directly
  serializes `__context__` could expose it.
- Structured logs: **no context path found**.
- Audit records: **no context path found**.
- Traceback output: **suppressed by `from None`** in the normal formatter.
- Debug logging/error-reporting callbacks: **no such path in the service**.

### 9.3 Residual risk

An in-process debugger, custom exception-chain walker, or future transport that serializes Python
exceptions could read `exception.__context__`. That is an **informational residual risk**, not an
external disclosure path in the current mock-only service.

No exception-handling change was made: there is no concrete external disclosure path to fix, and
the existing audit event preserves operationally useful bounded diagnostics (operation, reason,
state/history persistence status, and validated backend error code). A future transport or
structured error serializer must not serialize raw exception chains.

---

## 10. I-3.9-01 — database digest constraint decision

### 10.1 Current schema

`broker/firewall_controller_service/ownership_store.py` defines:

```sql
request_digest TEXT NOT NULL
```

There is no `CHECK` constraint and no versioned migration layer in this service. Schema creation
is `CREATE TABLE IF NOT EXISTS` inside `_init_schema`.

A direct-store probe produced:

| Inserted digest | Result |
|---|---|
| `NULL` | Rejected by `NOT NULL` as `BrokerDBError` |
| Empty string | Accepted |
| Short string (`abc`) | Accepted |
| Non-hex 64-character string | Accepted |
| Valid 64-hex string | Accepted |

### 10.2 Supported service paths

Normal controller service paths do not insert malformed digests:

- `_req_digest` computes a SHA-256 digest from canonical serialized request/identity data and
  returns 64 lowercase hexadecimal characters.
- `_call` validates caller identifiers before idempotency creation.
- `create_idempotency_record` receives the service-computed digest.
- `complete_idempotency_record` does not change `request_digest`.

Historical rows, manual database edits, imports, or future migrations can still contain an
invalid digest. The existing R-03 read path detects that condition, audits
`idempotency_digest_corrupt`, and fails closed with a sanitized `IDEMPOTENCY_CONFLICT`; it does not
disclose cached data and does not repair the row.

### 10.3 Constraint decision

A database `CHECK` constraint is technically implementable, but is not added in this phase:

- SQLite `CREATE TABLE IF NOT EXISTS` does not add a constraint to an existing table.
- A real migration would require a table rebuild or equivalent migration, preservation of all
  idempotency/recovery data, and a defined policy for pre-existing malformed rows.
- There is no migration framework/versioning in the current mock-only controller.
- Adding the constraint without a row-quarantine/backfill strategy could make recovery or startup
  fail on historical data.
- The service boundary remains the authoritative protection against disclosure and mutation.

**Decision:** document the remaining hardening item and do **not** add the schema migration in
this phase. A future change should add a versioned migration, detect/quarantine invalid historical
rows, add an exact 64-hex `CHECK`, and test both fresh and upgraded databases. That change
requires separate approval.

---

## 11. I-3.9-02 — database test isolation

### 11.1 Fresh temporary controller database

`broker/tests/conftest.py` performs the environment assignment before importing broker modules:

```python
_TEST_STORAGE = tempfile.mkdtemp(prefix='flaghunt-broker-test-storage-')
...
os.environ['FIREWALL_CONTROLLER_DB_PATH'] = os.path.join(
    _TEST_STORAGE, 'firewall_controller.db'
)

from broker.app import ownership
from broker.app.main import app
...
```

`ControllerOwnershipStore` resolves its default path from
`FIREWALL_CONTROLLER_DB_PATH` before falling back to `broker/data/firewall_controller.db`.
Because the assignment occurs before the broker imports, a default controller store created by a
test receives the temporary path.

The controller assignment uses `os.environ[...] = ...`, not `setdefault`, so an inherited
environment value cannot redirect tests back to the repository default database.

### 11.2 Subprocess propagation

Cross-process tests use Python `spawn` contexts. Spawned workers inherit the parent process
environment, including `FIREWALL_CONTROLLER_DB_PATH`.

- Cross-process concurrency workers create services without an explicit store; they therefore
  use the inherited temporary path.
- Crash-recovery workers pass explicit temporary database paths for their deterministic
  multi-process scenarios.
- The cross-process/crash suite completed with 10 passed, and the repository default database
  hash remained unchanged.

### 11.3 Parallel and same-process isolation

`tempfile.mkdtemp()` is evaluated per pytest process. If the suite is later run with xdist, each
worker process loads its own conftest and receives a separate temporary storage directory.
Within a single pytest process, tests that intentionally share the default controller store use
the same per-session temporary database; tests requiring independent state pass an explicit
temporary store. The cross-process concurrency test intentionally shares its isolated database
across its own workers.

This run did not use xdist. The important isolation property is that no test uses the repository
default controller database.

### 11.4 3.8 report correction

The Phase 2L.2G.3.8 report previously stated that the cross-process concurrency test used the
repository default database when no environment override was set, and that final verification
used an explicit override. That explanation was inaccurate because `broker/tests/conftest.py`
already assigns a fresh temporary `FIREWALL_CONTROLLER_DB_PATH` before broker imports.

The two affected statements in `docs/PHASE_2L_2G_3_8_RESIDUAL_RISK_REMEDIATION.md` were corrected
to describe the actual conftest isolation. No unrelated historical report was altered.

---

## 12. Preserved protections

| Protection | Status after 3.10 |
|---|---|
| F-01 same-key uncertain revoke recovery | Preserved; existing 3.6 hardening tests pass |
| F-02 reconciliation persistence-failure classification | Preserved; existing tests pass |
| F-03 unknown/corrupt lifecycle state fail-closed | Preserved; no lifecycle change |
| F-04 address-family identity/evidence binding | Preserved; no family/evidence change |
| F-05 canonical digest coverage | Preserved; `_req_digest` unchanged |
| F-06 evidence-gated `REVOKED` state | Preserved; no evidence completion change |
| F-07 exact full-string identifier/digest validation | Preserved and applied to health check/reconciliation |
| F-08 strict authorization allowlist semantics | Preserved; no authorization change |
| F-09 replay ownership binding | Preserved; no replay ordering change beyond the earlier canonical gate |
| R-01 install-failure persistence/error sanitization | Preserved; 69-test residual suite passes |
| R-02 canonical caller identifiers before store/persistence | **Completed** for health check and reconciliation |
| R-03 corrupt stored digest denial/audit/no disclosure | Preserved; existing tests pass |
| Ownership binding and peer identity | Preserved; no change |
| Lifecycle CAS and evidence-gated transitions | Preserved; no change |
| Durable idempotency | Preserved for valid requests; invalid requests create no record |
| Helper identity and contract enforcement | Preserved; 80-test group passes |

No existing test assertion was weakened or removed.

---

## 13. Remaining limitations

1. **Mock-only scope.** No real UDS, `SO_PEERCRED`, privileged helper, firewall, routing, NAT,
   conntrack, systemd/host, Docker, provisioning, cloud, or production database behavior is
   validated.
2. **No database digest `CHECK` migration.** I-3.9-01 remains a future hardening item; the
   service boundary is authoritative for the current mock-only scope.
3. **In-process exception context.** `FirewallControllerPersistenceError.__context__` retains
   the raw persistence exception even though traceback formatting suppresses it. No external
   response/log/audit path exposes it; future serializers must not walk exception chains.
4. **Legacy validator breadth.** `request_id`, `operation_id`, `idempotency_key`, and
   ownership-reference fields remain outside this phase's canonical identifier gate, consistent
   with the 3.8 scope limitation. Existing request-shape, ownership-binding, and helper-contract
   checks remain in force.
5. **Full-scan reconciliation reachability.** The default legacy validator requires policy fields
   for public requests; the no-policy full-scan branch is preserved and tested with a permissive
   validator, as in the existing service design.
6. **Same-process test storage shared by default.** Tests that use the default store share the
   per-session temporary controller database; tests needing independent state use explicit
   temporary stores. This is a test-isolation property, not a controller security change.
7. **No independent review yet.** This document is an implementation report. The independent
   security review of 3.10 is a separate, not-yet-started step.

---

## 14. Completion criteria and final status

| Completion criterion | Result |
|---|---|
| F-3.9-01 demonstrably closed | **Yes** — health check validates before store/backend and before idempotency persistence |
| F-3.9-02 demonstrably closed | **Yes** — reconciliation validates before `get_by_policy`/`list_ownerships` |
| Validation occurs before store access | **Yes** — counting-store tests record zero calls on invalid input |
| Invalid requests cause no persistence/state mutation | **Yes** — no idempotency, ownership, lifecycle, or evidence mutation |
| Existing R-01/R-02/R-03 protections intact | **Yes** — 69-test residual suite passes |
| Existing F-01–F-09 protections intact | **Yes** — 96-test hardening suite passes |
| All required tests pass | **Yes** — 0 failures, 0 skips |
| Exception and database findings accurately documented | **Yes** — sections 9 and 10 |
| Default controller database untouched | **Yes** — SHA-256 and mtime unchanged |

**Implementation status: PASS — targeted identifier-validation remediation in the local mock-only
scope.**

**Final gate: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.**

No independent review is started, and no live transport or privileged host integration is
authorized by this document. Await separate approval.
