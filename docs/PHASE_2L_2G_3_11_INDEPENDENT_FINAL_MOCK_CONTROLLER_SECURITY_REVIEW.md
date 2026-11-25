# Phase 2L.2G.3.11 — Independent Final Mock Controller Security Review

**Project:** Flaghunt  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Review type:** Independent, read-only source, call-path, persistence, and test review  
**Reviewed phases:** 2L.2G.3.5 through 2L.2G.3.10  
**Scope:** Local mock-only firewall controller and SQLite persistence  
**Date:** 2026-11-13  
**Decision:** **PASS — local mock-only targeted remediation and preservation**  
**Integration gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

No real transport, UDS/`SO_PEERCRED`, privileged helper, sudo/capability, firewall, routing,
NAT, conntrack, systemd/host, Docker, provisioning, cloud, or production database operation was
performed or authorized by this review.

---

## 1. Executive decision

The Phase 2L.2G.3.10 remediation is sustained for the authorized local mock-only scope.

| Item | Final classification |
|---|---|
| F-3.9-01 — `health_check` identifier-validation bypass | **CLOSED** |
| F-3.9-02 — reconciliation validation bypass | **CLOSED** |
| I-3.9-01 — no database `CHECK` constraint for digest format | **OPEN — accepted informational residual** |
| I-3.9-02 — inaccurate 3.8 test-isolation explanation | **CLOSED — documentation correction verified** |
| I-3.9-03 — suppressed exception context retains raw persistence details | **OPEN — accepted informational residual** |
| R-01 — install failure-state persistence and error sanitization | **VERIFIED CLOSED** |
| R-02 — canonical caller identifiers before store access | **VERIFIED CLOSED for the 3.10 canonical field scope** |
| R-03 — corrupt stored digest fails closed before replay | **VERIFIED CLOSED at the service boundary** |
| F-01 through F-09 — 3.6 revoke/recovery hardening | **VERIFIED PRESERVED** |

No new Critical, High, Medium, or in-scope Low security finding was identified. The remaining
open items are the previously accepted informational limitations, plus the already documented
I-07/I-08 field-scope and raw-error-text residuals. They do not bypass authentication, change
authoritative ownership, invoke the backend with an invalid ownership record, or disclose a
cached idempotent response. They do not reopen F-3.9-01 or F-3.9-02.

The earlier 3.9 decision was **CONDITIONAL** because R-02's acceptance criterion was not met at
two entry points. Those two entry points now pass the canonical gate before any ownership-store,
idempotency-store, or backend access. This review therefore changes the local mock-only gate to
**PASS**, while retaining the separate live-integration gate as **NOT READY**.

The 3.10 report's universal-sounding statement that “no invalid request creates…” is accurate for
the canonical fields in the 3.10 scope (`policy_id`, `instance_id`, `network_id`). It is not a
claim that every legacy request field has been canonically validated; the broader field-scope
limitation remains explicitly documented below.

---

## 2. Independence, inputs, and method

This review did not rely on the 3.10 report's test counts or conclusions. The following were
independently inspected:

- `docs/PHASE_2L_2G_3_5_*`, `3_6_*`, `3_7_*`, `3_8_*`, `3_9_*`, and `3_10_*`.
- `broker/firewall_controller_service/controller_service.py` in full, including `_call`,
  `_validate_caller_identifiers`, `_validate_ownership_binding`, `_validate_replay`,
  idempotency recovery, lifecycle transitions, evidence persistence, install failure handling,
  and reconciliation.
- `broker/firewall_controller_service/ownership_store.py`, including schema creation, SQLite
  transactions, ownership creation, lifecycle CAS, idempotency records, evidence writes, and
  reconciliation status updates.
- `request_validator.py`, `authorization_strict.py`, `authorization.py`, `audit.py`, `errors.py`,
  `helper_contract.py`, `helper_authorization.py`, `mock_helper_executor.py`, `mock_transport.py`,
  `peer_identity.py`, `mock_backend.py`, `backend_interface.py`, and the legacy
  `broker/app/firewall_controller.py`.
- `broker/tests/conftest.py` and the controller regression suites, including the 3.10
  identifier-entry-point suite and the R-03/F-01-through-F-09 suites.
- Public controller entry points, idempotency reservation, cached replay, reconciliation,
  evidence mutation, and persistence failure paths.

The review used read-only inspection and temporary-database probes. No source or test file was
modified. Only this review document was created.

Environment used for the independent test run:

```text
Windows / PowerShell
Python 3.10.0
pytest 8.3.4
Virtual environment: E:\Flag-hunt\ctf-platform-be\venv
```

---

## 3. Scope and non-authorization

This is a local mock-only review. The following remain outside the review and are **not
authorized**:

- UDS transport, `SO_PEERCRED`, and kernel-authenticated peer identity.
- Real helper process identity, helper authorization, or helper contract enforcement over a real
  transport.
- Privileged helper execution, sudo, capabilities, namespaces, and filesystem isolation.
- Real nftables/iptables/UFW state, transaction semantics, and rollback.
- Routing, NAT, conntrack, systemd, host, and Docker effects.
- Multi-host SQLite/DB locking, distributed ordering, and production database migration.
- Production secrets, operational logging, monitoring, provisioning, and cloud systems.

`MockFirewallController` in `broker/app/firewall_controller.py` is a compatibility mock used
inside the helper executor. It is not the reviewed public controller service and does not prove
real helper or firewall behavior. Its health-check defaults and in-memory state are not evidence
for live readiness.

---

## 4. F-01 through F-09 — 3.6 hardening preservation

The 3.6 hardening suite ran unchanged and passed with **96 tests**. Source inspection confirms
that the 3.10 changes did not remove or weaken the 3.6 protections.

| Finding | Preserved behavior | Evidence |
|---|---|---|
| F-01 — same-key uncertain revoke retry replayed cached error | Uncertain or non-success revoke outcomes enter read-back recovery; cached errors are not blindly replayed | `_call`, `_idempotency_replay_decision`, `_read_back_revoke`; 3.6 suite |
| F-02 — reconciliation swallowed `BrokerDBError` | Per-record persistence failure becomes sanitized `PERSISTENCE_FAILURE` and top-level `RECONCILIATION_PERSISTENCE_FAILURE` | `reconcile_pending_operations`; 3.6 suite |
| F-03 — unknown/absent revoke state treated as success | Unknown backend state remains uncertain; terminal `REVOKED` requires evidence | `_read_back_revoke`, `_has_revocation_evidence`; 3.6 suite |
| F-04 — evidence not bound to full ownership identity/family | Evidence checks include record ID, policy ID/version, instance, network, digest, and address family | `_has_revocation_evidence`, `_store_revocation_evidence`; 3.6 suite |
| F-05 — incomplete revoke idempotency digest | Canonical digest covers all security-relevant fields and peer identity | `_DIGEST_FIELDS`, `_req_digest`; 3.6 suite |
| F-06 — lifecycle/evidence ordering | Evidence is persisted before promotion to a terminal success state | `_complete_revoke`, verification activation path; 3.6 suite |
| F-07 — digest regex accepted trailing newline | Exact `\A...\Z` validation is used for identifiers and digests | `_DIGEST_RE`, `_ID_RE`, helper contract; 3.6 suite |
| F-08 — strict authorization allowlist semantics | Empty/omitted allowlists deny; strict provider requires explicit peer identity | `StrictAuthorizationProvider`, helper authorization; 3.6 suite |
| F-09 — cached response replayed after ownership change | Replay re-reads authoritative ownership and validates record/resource/identity bindings before disclosure | `_validate_replay`; 3.6 suite |

The review found no test weakening, skip, or assertion removal in the preservation suites.

---

## 5. R-01, R-02, and R-03

### 5.1 R-01 — install failure-state persistence and sanitization

**Status: VERIFIED CLOSED.**

When install returns a non-`ok` result, the controller attempts to persist a failable state and
lifecycle history. If that persistence cannot be completed, it raises a sanitized
`FirewallControllerPersistenceError` with bounded details. It does not complete the idempotency
record as a success and does not overwrite an advanced state.

An independent fault-store probe reproduced the sanitized behavior:

```text
TYPE                 FirewallControllerPersistenceError
STR                  Install failure could not be fully persisted
DETAILS              {'operation': 'install_policy',
                      'backend_error_code': 'INSTALL_FAILED',
                      'failure_state_persisted': False,
                      'lifecycle_history_persisted': False,
                      'reason': 'persistence_unavailable'}
CONTEXT_TYPE         BrokerDBError
CONTEXT_STR          raw-sqlite-detail-SECRET (synthetic marker)
SUPPRESS_CONTEXT     True
TRACEBACK_HAS_RAW    False
TRACEBACK_HAS_CONTEXT_HEADER False
IDEM_STATUS          PENDING
```

The raw `BrokerDBError` remains reachable in-process as `__context__`; that is I-3.9-03, not an
external disclosure path. Other persistence paths can still propagate a raw `BrokerDBError`
directly; that is the pre-existing I-08 informational item.

### 5.2 R-02 — canonical caller identifiers before store access

**Status: VERIFIED CLOSED for the 3.10 canonical field scope (`policy_id`, `instance_id`,
`network_id`).**

`_validate_caller_identifiers` is invoked by `_call` for all six dispatched operations before
`_req_digest`, idempotency lookup, ownership lookup, or backend dispatch. It is invoked directly by
`reconcile_pending_operations` before `get_by_policy` or `list_ownerships`. Only those two call
sites exist.

The validator:

- requires a canonical string `policy_id` when required;
- validates explicitly supplied `instance_id` and `network_id` against the exact
  `\A[A-Za-z0-9._:-]{1,128}\Z` format;
- accepts omitted or explicit-`None` optional identifiers;
- rejects explicit empty optional identifiers;
- rejects non-strings, lists, dictionaries, booleans, bytes, control characters, whitespace, and
  overlong values without coercing them.

An independent probe sent a newline-bearing `policy_id` to every dispatched entry point:

```text
health_check           PermissionError: Invalid policy_id; store_calls=[]
install_policy         PermissionError: Invalid policy_id; store_calls=[]
inspect_policy         PermissionError: Invalid policy_id; store_calls=[]
verify_policy          PermissionError: Invalid policy_id; store_calls=[]
revoke_policy          PermissionError: Invalid policy_id; store_calls=[]
remove_stale_policy    PermissionError: Invalid policy_id; store_calls=[]
```

The 3.10 suite independently asserts the same zero-access property for invalid health and
reconciliation inputs, including optional identifiers and unsupported types, using counting
store and backend wrappers. A malformed full-scan reconciliation optional identifier is rejected
before `list_ownerships`.

**Field-scope qualification.** The historical R-02 wording covers “identifiers” broadly. The 3.8
and 3.9 reports explicitly excluded `request_id`, `operation_id`, `idempotency_key`, ownership-
reference fields, and broader legacy-validator breadth from the canonical gate. Those exclusions
remain in force and are documented as I-07/I-08 informational residuals below. They are
pre-existing, not introduced by 3.10, and do not reopen the two 3.9 findings. Under a universal
reading of R-02 that includes those excluded fields, R-02 would remain partially closed; that
broader reading is outside the 3.10 phase and is tracked as the I-07 field-scope limitation.

### 5.3 R-03 — corrupt stored digest denial

**Status: VERIFIED CLOSED at the service boundary.**

The service validates the stored request digest exactly (64 hexadecimal characters) before any
cached-response decision. An independent probe injected empty, short, non-hex, `None`, and
non-string digest values into a completed verify idempotency record. Every case produced:

```text
FirewallControllerIdempotencyError:
Corrupt idempotency record: stored request digest is missing or invalid
backend_calls = 0
```

The valid completed response was not disclosed, and the backend was not invoked. The direct store
still accepts malformed digests when bypassing the service; that is I-3.9-01, not a service
replay bypass.

---

## 6. F-3.9-01 and F-3.9-02 — final classification

### 6.1 F-3.9-01 — health-check validation bypass

**Final classification: CLOSED.**

`health_check` now passes through the same canonical gate as the other dispatched operations.
The gate runs before:

- idempotency digest computation;
- `get_idempotency_record`;
- `get_by_policy`;
- any backend health call;
- any idempotency completion.

The 87-test 3.10 suite uses counting store/backend wrappers to assert zero access for newline,
CR, leading/trailing whitespace, tab, NUL, list, dictionary, integer, boolean, bytes, and
overlong identifiers. It also verifies that valid health checks still replay idempotently.

The pre-remediation scenario—`policy_id='p1\n'` returning `ok` and persisting a malformed
idempotency resource key—is no longer reachable through the reviewed service.

### 6.2 F-3.9-02 — reconciliation validation bypass

**Final classification: CLOSED.**

`reconcile_pending_operations` now calls `_validate_caller_identifiers` after authorization and
legacy validation, but **before** `get_by_policy`, `list_ownerships`, pending-idempotency reads,
backend inspection, or lifecycle/evidence mutation.

The 3.10 suite verifies:

- invalid policy, instance, and network identifiers raise `PermissionError`;
- no store method is called and no backend inspection occurs;
- a seeded installed/verified policy retains its lifecycle history and evidence;
- valid policy-specific reconciliation still works;
- valid full-scan reconciliation with no policy ID still works;
- full-scan reconciliation rejects a supplied malformed optional identifier.

The `require_policy=policy_id is not None` argument preserves the documented full-scan branch.
The default validator still requires the legacy policy fields, so full-scan is only reachable with
a permissive validator or a future reconciliation-specific contract. This is a functional
limitation, not an established validation bypass.

---

## 7. Public entry-point and validation-order matrix

| Entry point | Dispatch path | Canonical validation point | Before store/backend? | Invalid-input behavior |
|---|---|---|---|---|
| `health_check` | `_call` | `_validate_caller_identifiers` at `_call` before digest/idempotency/ownership | Yes | `PermissionError("Invalid <field>")`; zero access |
| `install_policy` | `_call` | Same canonical gate before digest/idempotency/ownership | Yes | `PermissionError`; no intent/ownership/idempotency record |
| `inspect_policy` | `_call` | Same canonical gate | Yes | `PermissionError`; zero access |
| `verify_policy` | `_call` | Same canonical gate | Yes | `PermissionError`; zero access |
| `revoke_policy` | `_call` | Same canonical gate | Yes | `PermissionError`; zero access |
| `remove_stale_policy` | `_call` | Same canonical gate | Yes | `PermissionError`; zero access |
| `reconcile_pending_operations` | Direct method | Reconciliation canonical gate before `get_by_policy`/`list_ownerships` | Yes | `PermissionError`; zero access |

The shared `_call` order is:

```text
copy request
audit request_received
authorize (strict per-request identity)
legacy validator
canonical caller-identifier gate
compute request digest
pre-read idempotency and detect same-key/different-payload conflict
read authoritative ownership
validate ownership binding
reserve/complete durable idempotency
perform lifecycle/backend/evidence work
complete idempotency and return
```

No cached response is returned before ownership binding and replay validation. For health checks,
replay is intentionally allowed after the canonical gate because health does not depend on
ownership and does not disclose ownership state.

`MockControllerTransport` injects identity and delegates to the service; it does not add a second
validation path. Direct `FirewallControllerService` calls trust the caller-supplied `peer_uid` and
`peer_gid`; only the mock transport overwrites them from an explicit peer argument. This is a
mock-only seam, not kernel authentication.

---

## 8. Persistence, concurrency, recovery, and error propagation

The SQLite store uses WAL mode, explicit transactions for multi-step writes, a primary key on the
ownership record, a uniqueness constraint on `(idempotency_key, operation_type)`, lifecycle CAS
updates via `BEGIN IMMEDIATE`, and separate evidence/history tables. The reviewed behavior is:

- A first install reserves durable intent before backend side effects.
- Ownership state transitions use expected previous state and lifecycle version.
- Concurrent losers re-read and fail closed rather than overwriting a winner.
- Idempotency is durable at the controller boundary; the helper cache is in-memory mock state.
- Pending idempotency recovery is bounded and does not fabricate a completed response.
- A `REVOKED` terminal state requires matching revocation evidence.
- Verification evidence is stored before promotion to `ACTIVE`.
- Reconciliation classifies per-record persistence failures as sanitized errors and does not
  return false success.
- Unknown or corrupt persisted lifecycle states are reported as uncertain, never adopted or
  rewritten automatically.
- Cross-process tests use temporary databases; spawned workers inherit the isolated environment.
- The repository default databases are not used by the test harness.

The 3.9/3.10 source and tests support these behaviors. The 40-test persistence/recovery group and
the 10-test cross-process/crash group passed in this review.

**Accepted error-propagation residuals.** The controller still re-raises raw `BrokerDBError`
messages on several non-failure-state persistence paths, including some initial intent and
success-path writes. `BrokerDBError` messages can contain SQLite text and paths. This is the
pre-existing I-08 informational item. No FastAPI route serializes the firewall-controller service
error chain; a real transport would need a sanitized error mapper. The R-01 failure-state path
itself is sanitized as verified above.

---

## 9. Authorization and helper boundary

- `StrictAuthorizationProvider` requires explicit `peer_uid` and `peer_gid`, checks operation
  allowlists, and rejects caller-supplied trusted-identity claims.
- The strict provider's allowlist is explicit; empty or omitted operation sets deny.
- `MockHelperAuthorizationProvider` uses fail-closed UID, GID, and operation allowlists. Empty
  sets authorize nothing.
- `MockHelperExecutor` requires an explicit identity and helper authorization policy; there is no
  implicit trusted identity and no default allowlist.
- The helper contract rejects `peer_uid`, `peer_gid`, `uid`, `gid`, `pid`, caller-trusted flags,
  verified flags, and other identity/authorization claims in request JSON.
- `MockFirewallBackend` obtains identity from an injected per-request provider and strips
  controller-only identity fields before helper dispatch.
- Unknown helper operations are rejected; the executor maps only known `HelperOperation` values to
  mock controller methods and returns `OPERATION_NOT_ALLOWED` for an unknown mapping.
- The helper treats compiled policy data as data. It does not execute shell commands or mutate
  host firewall/routing/NAT/conntrack/systemd/Docker state.
- Helper timeout enforcement is explicitly deferred to a future transport/process layer.

The strict authorization default is safe. The legacy `strict_auth=False` mock provider remains a
footgun (I-09 from 3.7); no reviewed caller uses it.

---

## 10. Findings and residual limitations

### 10.1 I-3.9-01 — no database `CHECK` constraint for digest format

**Severity: Informational.** **Status: OPEN — accepted.**

Direct `ControllerOwnershipStore.create_idempotency_record` calls still accept empty, short,
non-hex, and otherwise malformed digest strings. An independent direct-store probe accepted `''`,
`'abc'`, and a 64-character non-hex value.

Service-generated digests are canonical lowercase 64-hex SHA-256 values, and R-03 read validation
rejects malformed stored values before replay or backend access. A database migration with a
`CHECK` constraint would be defense in depth, but it requires separate approval, row validation,
and migration testing. No migration was added in 3.10, and none is required to sustain the
service-boundary R-03 result.

**Future remediation:** after separate approval, validate existing rows and add a 64-hex
`CHECK`/migration constraint.

### 10.2 I-3.9-02 — 3.8 test-isolation explanation

**Severity: Informational.** **Status: CLOSED — documentation correction verified.**

`broker/tests/conftest.py` unconditionally assigns `FIREWALL_CONTROLLER_DB_PATH` to a fresh
per-process temporary path before broker imports:

```text
_TEST_STORAGE = tempfile.mkdtemp(prefix='flaghunt-broker-test-storage-')
os.environ['FIREWALL_CONTROLLER_DB_PATH'] = os.path.join(
    _TEST_STORAGE, 'firewall_controller.db'
)
```

Spawned workers inherit the path. The corrected 3.8 sections and the 3.10 report now describe
this harness behavior. A historical sentence in the 3.8 verification notes still refers to an
earlier combined invocation; the current harness and the corrected isolation description are
consistent, and the historical note is not relied upon for the review.

**Future remediation:** none required for this phase. Keep the unconditional assignment if test
isolation is changed.

### 10.3 I-3.9-03 — suppressed exception context retains raw persistence details

**Severity: Informational.** **Status: OPEN — accepted.**

The independent R-01 probe confirms:

- `str(error)` and `error.details` are sanitized and bounded.
- `error.__context__` still references the raw `BrokerDBError`.
- `error.__suppress_context__` is `True`.
- Normal traceback formatting omits the raw context and the “During handling of the above
  exception” header.
- The durable idempotency record remains `PENDING`.

No route, audit event, log formatter, or response serializer in the reviewed code walks the
exception context. The residual is in-process only. A future error mapper must not serialize
`__context__` or `__cause__` chains.

**Future remediation:** keep raw storage exceptions internal; never include exception chain
objects in external responses, logs, or audit details.

### 10.4 Documented I-07/I-08 field-scope and raw-error residuals

**Severity: Informational — pre-existing, accepted outside the 3.10 canonical field scope.**

The 3.8/3.9 reports explicitly excluded `request_id`, `operation_id`, `idempotency_key`,
ownership-reference fields, and broader legacy-validator breadth from the controller-wide
canonical gate. Independent probes confirm the limitation remains:

```text
health_check policy_version=2**63
    -> raw BrokerDBError (SQLite integer overflow); store read attempted

health_check request_id=['r1']
    -> helper contract returns status=error; an idempotency record is completed

health_check idempotency_key=['k1']
    -> raw BrokerDBError from the idempotency-store binding

health_check policy_version=-1 / True
    -> accepted by the legacy integer validator; True is treated as 1
```

These are pre-existing input-validation and error-contract defects, not 3.10 regressions. They do
not escape authentication, change authoritative ownership through the canonical fields, invoke
the backend with a mismatched ownership record, or disclose a cached response. The helper
contract still rejects negative policy versions for non-health helper operations, and the
controller remains fail-closed for the reviewed ownership fields.

**Future remediation:** if a universal input-validation claim is desired, add a
reconciliation/legacy request gate for all stored/correlation fields, require a signed 64-bit
non-negative `policy_version`, reject `bool` for integer fields, and add regression tests. Do not
describe the 3.10 gate as universal until that work is complete.

### 10.5 Full-scan reconciliation functional limitation

When `reconcile_pending_operations` receives a valid `policy_id` but no `policy_version`, the
source takes the full-scan branch because the policy-specific condition requires both values. This
is reachable only with a permissive validator; the default validator requires the legacy policy
fields. The caller is already authorized for reconciliation, and no cached response or ownership
authority is disclosed or bypassed merely by the extra records being scanned. It is a functional
and operator-surprise limitation, not an established validation bypass.

**Future remediation:** either require both policy fields for policy-specific reconciliation and
reject a lone `policy_id`, or add a reconciliation-specific validator that clearly distinguishes
full-scan from policy-specific requests.

---

## 11. Independent test execution

All commands were run from `E:\Flag-hunt\ctf-platform-be` using
`.\venv\Scripts\python.exe` and the repository tests. No test was modified, skipped, or weakened.

| # | Suite / command | Result | Duration |
|---|---|---|---|
| 1 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_identifier_validation_entrypoints.py -q` | **87 passed, 1 warning** | 18.09s |
| 2 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_residual_risk_remediation.py -q` | **69 passed, 1 warning** | 22.34s |
| 3 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_revoke_recovery_and_idempotency_hardening.py -q` | **96 passed, 1 warning** | 32.49s |
| 4 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_ownership_binding_remediation.py broker\tests\test_firewall_controller_revoke_lifecycle_remediation.py -q` | **38 passed, 1 warning** | 24.66s |
| 5 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_persistence_failure_closure.py broker\tests\test_firewall_controller_persistent_recovery_integration.py -q` | **40 passed, 1 warning** | 18.56s |
| 6 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_helper_identity_propagation.py broker\tests\test_firewall_controller_helper_contract.py -q` | **80 passed, 1 warning** | 1.38s |
| 7 | `.\venv\Scripts\python.exe -m pytest broker\tests\test_firewall_controller_cross_process_concurrency.py broker\tests\test_firewall_controller_cross_process_crash_recovery.py -q` | **10 passed, 1 warning** | 8.58s |
| 8 | Full controller file list | **499 passed, 1 warning** | 136.92s (2:16) |
| 9 | `.\venv\Scripts\python.exe -m pytest broker\tests -q` | **602 passed, 1 warning** | 151.90s (2:31) |
| 10 | `.\venv\Scripts\python.exe manage.py test instances.tests.test_manager_client -v 1` | **33 tests, OK** | 0.055s test time |
| 11 | `.\venv\Scripts\python.exe manage.py check` | **System check identified no issues (0 silenced)** | 2.27s wall |

Full controller command used for row 8:

```powershell
$files = Get-ChildItem -Path broker\tests -Filter 'test_firewall_controller*.py' |
    Sort-Object Name | ForEach-Object { $_.FullName }
.\venv\Scripts\python.exe -m pytest @files -q
```

The glob selected **23** controller test files. The 499-test controller total is consistent with
the 3.10 report's 499 and the 602-test full `broker/tests` total. Existing suite counts were
unchanged from 3.10; no test was added by this review.

### 11.1 Warnings, skips, and failures

- Failures: **0**
- Skips: **0**
- Pytest warning summary: **1 per pytest run** — the pre-existing Pydantic class-based `config`
  deprecation warning.
- A pre-existing `pytest-asyncio` `asyncio_default_fixture_loop_scope` deprecation notice is
  emitted to stderr before collection; it is not part of the pytest warning summary and is not a
  test failure.
- Django manager-client: **33 tests, OK**; system check no issues.

Durations differ slightly from the 3.10 report because the independent run was performed on the
same Windows host but with different process warm-up and load. Counts and outcomes are identical.

### 11.2 Default database verification

`broker/data` was hashed before and after the independent suite run. All four default databases
retained identical SHA-256, length, and mtime:

| File | SHA-256 | Length | Last write (UTC) |
|---|---|---:|---|
| `broker.db` | `CBB570637A7F75524B12677B2455701BB0C66BD45A507FF171070BECF300CAAD` | 118784 | `2026-11-01T18:10:26.9145977Z` |
| `broker_audit.db` | `6D530C0F8A66457E148EBC39370BE972801564E5B520A2A8EA3B86C4CB1AC44F` | 118784 | `2026-11-01T18:10:26.9880404Z` |
| `broker_recovery.db` | `944D53E3C15BF489F11EC6C61857D59A4B5C10328235FE4602A109700D80E3F5` | 49152 | `2026-11-01T09:13:10.2537932Z` |
| `firewall_controller.db` | `6B4E4EA88A33BB5ABE689AD2E7D90BFB6AC29EE72ED5A0B3A4AE576573A3B440` | 204800 | `2026-11-07T06:12:50.9449929Z` |

**DEFAULT_DB_UNCHANGED=YES.**

The temporary verification probes used `tempfile.mkdtemp()` databases and did not write to the
repository default files. The test harness's unconditional temporary-path assignment is the
reason the default controller database was not used.

---

## 12. Limitations of this review

This review is deliberately limited to local mock evidence. It does not establish:

- that a real UDS peer identity or `SO_PEERCRED` implementation is correct;
- that a privileged helper is isolated or safely executed;
- that a real firewall, routing, NAT, conntrack, systemd, or Docker operation is correct;
- that SQLite behavior survives multi-host/distributed deployment;
- that a production database migration or row-corruption remediation is safe;
- that a real transport error mapper prevents raw database text disclosure.

The following are also not proven by this review:

- helper timeout enforcement (deferred to a future transport/process layer);
- production logging, monitoring, secrets handling, and operational recovery;
- behavior under a live adversarial network or host.

These limitations are the reason the live gate remains **NOT READY**.

---

## 13. Freeze recommendation and gate

### 13.1 Recommendation

**Recommend freezing the local mock-only controller implementation at the reviewed 3.10 state for
local mock testing and documentation purposes.** The target

- has no new Critical, High, Medium, or in-scope Low finding;
- closes F-3.9-01 and F-3.9-02;
- preserves F-01 through F-09, R-01, and R-03;
- passes all 11 required suites without failures or skips;
- leaves the repository default databases unchanged.

Do not promote this result to a live firewall authorization. The accepted informational residuals
(I-3.9-01, I-3.9-03, I-07/I-08 field/error scope, and the full-scan limitation) must be handled in
a separately approved hardening phase if a universal input-validation or live-transport claim is
needed.

### 13.2 Gate

**PASS — local mock-only targeted remediation and preservation.**

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.**

No live transport, privileged helper, sudo/capability, real firewall/routing/NAT/conntrack/
systemd/Docker, provisioning, cloud, or production database change is authorized by this review.
Await separate approval before beginning any such work.
