# Post-J.20 Stage 1B.7 — Independent Remediation Verification (Mock-Only)

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.** This milestone is review-only.
No application source code, test, runtime configuration or gate status was changed. No gate was
closed, no risk was accepted, and no live/Docker/host operation was performed.

## 1. Scope and baseline

Repository: `E:\Flag-hunt\ctf-platform-be` 
HEAD verified: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` 
Review baseline: 26 modified tracked files, 176 untracked entries, 0 staged files.

Baseline posture accepted for this review:
- Stage 1B.1–1B.4: **VERIFIED (scoped)**.
- Stage 1B.5: independent review complete; decision **CONDITIONALLY READY FOR FORMAL
  ACCEPTANCE REVIEW (not production authorization)**.
- Stage 1B.6: **VERIFIED (scoped)**; SR-07, SR-08 and SR-09 each **VERIFIED FIXED (scoped)**.

Documents inspected before review:
- `docs/POST_J20_STAGE_1B_6_TARGETED_RESIDUAL_GAP_REMEDIATION.md`
- `docs/POST_J20_STAGE_1B_5_FINAL_RISK_REGISTER.md`
- `docs/POST_J20_STAGE_1B_5_INDEPENDENT_SECURITY_REVIEW.md`
- `docs/POST_J20_STAGE_1B_5_REMEDIATION_ROADMAP.md`
- `docs/POST_J20_STAGE_1B_5_FINAL_READINESS_DECISION.md`
- `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md`
- Stage 1B.1–1B.4 verification documents for consolidated assessment context.

## 2. Phase 1 — Evidence verification

### 2.1 Recorded Stage 1B.6 artifacts

| Artifact set | Recorded summary | Exit evidence | Independent check |
|---|---|---:|---|
| `post_j20_stage_1b6_new_suite.stdout.txt`, `.stderr.txt`, `.exit.txt` | `16 passed, 1 warning in 6.14s` | `EXIT=0` | Confirmed from raw files. |
| `post_j20_stage_1b6_targeted.stdout.txt`, `.stderr.txt`, `.exit.txt` | `301 passed, 1 warning in 140.82s (0:02:20)` | `EXIT=0`, `ELAPSED_SECONDS=142.74` | Confirmed from raw files. |
| `post_j20_stage_1b6_full.stdout.txt`, `.stderr.txt`, `.exit.txt` | `944 passed, 1 warning in 391.61s (0:06:31)` | `EXIT=0`, `ELAPSED_SECONDS=395.89` | Confirmed from raw files. |

No recorded artifact reports `failed` or `errors`. The full-suite count is internally
consistent: 928 tests at Stage 1B.4 plus 16 new Stage 1B.6 tests = 944. Stdout contains the
pre-existing pydantic v2 deprecation notice; stderr contains the pre-existing
`pytest-asyncio` `PytestDeprecationWarning` plus PowerShell's native-stderr capture wrapper.
Those warnings are unchanged from earlier milestones and are not test failures.

### 2.2 Non-destructive independent rerun

The focused Stage 1B.6 suite was rerun without writing new evidence files:

```
venv\Scripts\python.exe -m pytest broker/tests/test_post_j20_stage_1b6_targeted_residual_gaps.py -q
```

Actual result: **16 passed, 1 warning in 7.11s**. No failures or errors. No source or test
file was modified.

### 2.3 Evidence-hygiene observation

`post_j20_stage_1b6_new_suite.initial_failure.note.txt` correctly records the initial
`3 failed, 11 passed, EXIT=1` chronology and the three corrected test/contract mistakes, but
its final paragraph still names an earlier intermediate capture as "14 passed ... EXIT=0".
The authoritative final artifacts are `post_j20_stage_1b6_new_suite.stdout.txt`
(`16 passed`) and `.exit.txt` (`EXIT=0`). This is a documentation-hygiene inconsistency only
(SR-14 lineage); it does not weaken any control or test result. The artifact was preserved,
not edited, under this review-only milestone.

## 3. Phase 2 — Independent review of SR-07

### 3.1 Store layer: typed conflict classification

- `BrokerDBCanonicalError(BrokerDBError)` carries stable `OWNERSHIP`, `INTEGRITY` and
  `PERSISTENCE` categories (`broker/firewall_controller_service/ownership_store.py:15-24`).
- `BrokerDBIdempotencyConflict` and `BrokerDBCanonicalBodyConflict` are explicit
  `BrokerDBError` subclasses (`ownership_store.py:27-42`).
- `create_idempotency_record()` uses exactly targeted
  `ON CONFLICT(idempotency_key, operation_type) DO NOTHING`; only a zero-row insert raises
  `BrokerDBIdempotencyConflict` (`ownership_store.py:490-528`, especially `:507-513`). Genuine
  DB failures remain plain `BrokerDBError` or typed canonical errors (`:515-526`).
- `store_canonical_policy_body()` uses exactly targeted
  `ON CONFLICT(policy_id, policy_version) DO NOTHING`; only a zero-row insert raises
  `BrokerDBCanonicalBodyConflict` (`ownership_store.py:737-814`, especially `:789-802`).
  PK/FK/CHECK and generic storage failures become `BrokerDBCanonicalError(..., PERSISTENCE)`,
  not an idempotent conflict (`:805-812`).
- `ensure_canonical_policy_body()` resolves only the typed canonical-body conflict by
  re-reading and fully validating the durable winner (`ownership_store.py:831-858`).

No message-substring classification remains in the reviewed classification paths. A search
of `broker/firewall_controller_service/` found no `in str(e)`-style or lowercased-text error
matching used to classify persistence conflicts.

### 3.2 Service layer: sanitization and replay

- `_sanitize_canonical_policy_error()` is type/category based
  (`controller_service.py:441-461`): `PermissionError` is re-raised;
  `BrokerDBCanonicalError` maps by `.category` to the same three bounded public errors;
  generic `BrokerDBError` maps to `FirewallControllerPersistenceError`; unknown exceptions map
  to a bounded request error. No new public exception type was introduced.
- Idempotency duplicate handling uses
  `isinstance(create_exc, BrokerDBIdempotencyConflict)` (`controller_service.py:977`). After
  any create exception, the service performs a bounded authoritative re-fetch; if no record
  exists it re-raises the last fetch or create error (`:968-1015`). Replay decisions are then
  validated by stored digest and ownership binding, not exception text (`:816-829`, `:878-893`,
  `:962-1017`).

**Residual hardening note (non-blocking):** the broad `except Exception as create_exc` at
`:968` is not gated on `unique_collision`; the typed flag only extends the retry window
(`:977`, `:999-1011`). If a non-conflict create error occurs while a same-key record already
exists, the service proceeds to validated replay/pending classification instead of re-raising
the original create error. That is defensible because the authoritative record is independently
validated, but the comment at `:973-976` overstates the guarantee. Likewise, the catch-all at
`:461` bounds unknown read-back exceptions as a request error rather than a persistence error.
These are documentation/hardening residuals, not a failure of the scoped classification fix.

### 3.3 Public compatibility and outcome distinction

- New store exceptions subclass `BrokerDBError`; public service sanitization retains
  `PermissionError`, `FirewallControllerRequestError` and
  `FirewallControllerPersistenceError` as the bounded error surface.
- `status='PENDING'` and the separate informational `operation_outcome` column remain distinct
  (`ownership_store.py:112-117`, `:511`). `UNCERTAIN` is not a lifecycle state and is excluded
  from `NON_TERMINAL_OUTCOMES`; it is produced only for ambiguous outcomes
  (`controller_service.py:774-782`). Reconciliation reports pending rows with their own
  outcome and does not auto-replay (`:2021-2029`). A `COMPLETED` but uncertain cached revoke
  takes the recovery path, never silent success (`:824-827`). Terminal completion remains
  CAS-guarded with authoritative replay on a guard miss (`:1471-1499`).

### 3.4 Focused tests reviewed

`broker/tests/test_post_j20_stage_1b6_targeted_residual_gaps.py:102-156,250-261` covers typed
canonical-body conflict resolution, generic storage failure not being treated as an idempotent
conflict, typed idempotency duplicate vs generic failure, all three structured category
mappings plus plain-`BrokerDBError` fallback, and conflict-winner mismatch failing closed. No
skip or weakened assertion was found.

**SR-07 conclusion: VERIFIED (scoped).** String-based classification was replaced by targeted
SQL conflict targets plus typed/structured exceptions. Genuine storage failures remain
distinguishable, unrelated exceptions are not promoted to conflicts by message text, public
error compatibility is preserved, and PENDING/UNCERTAIN remain separate concepts. The noted
broad-catch and catch-all residuals are scoped hardening/documentation items.

## 4. Phase 3 — Independent review of SR-08

### 4.1 Missing vs failed reads

- `_query_dicts()` explicitly documents that storage failures propagate and absence is a
  caller-represented empty result (`ownership_store.py:367-380`); `BrokerDB.query` re-raises
  `BrokerDBError` and wraps other exceptions as `BrokerDBError` (`broker/app/db.py:286-297`).
- `get_canonical_policy_body()` returns `None` only for zero rows and propagates read failures
  (`ownership_store.py:860-867`). Missing records and failed reads are therefore distinct.
- `ensure_canonical_policy_body()` puts the trusted pre-read in `try`; `BrokerDBError` is
  explicitly re-raised with the SR-08 comment and other exceptions are wrapped as
  `BrokerDBError('Canonical policy body pre-read failed: ...')`
  (`ownership_store.py:831-858`, especially `:841-847`). The prior
  `except Exception: existing = None` conversion is gone.
- Only the typed `BrokerDBCanonicalBodyConflict` from the targeted single-body insert is
  resolved by re-reading the durable winner (`:852-858`). A missing winner raises
  `BrokerDBError` (`:856-857`), and existing/winner bodies pass
  `_validate_existing_canonical_policy_body()` (`:816-829`).

### 4.2 Fail-closed validation and promotion gates

- `read_trusted_canonical_policy_body()` enforces version normalization, ownership/owner
  binding, schema-v1, JSON parsing, required-families parsing, rule normalization, digest
  recomputation, ownership-digest binding and expected-digest checks
  (`ownership_store.py:869-938`, especially `:885-927`). Generic storage failures remain
  `BrokerDBError`, not absence.
- Install persistence occurs before backend dispatch (`controller_service.py:1210-1212`);
  pre-checks for inspect/remove/verify use bounded sanitization (`:1214-1220`, `:475-478`,
  `:493-502`). `verify_policy` requires a trusted read before evidence and before
  `VERIFYING → VERIFIED → ACTIVE` (`:1364-1374`, `:1394-1419`), and inspect responses are gated
  on trusted read-back (`:1444-1464`).
- Reconciliation converts an outer canonical probe failure into `mark_persistence_failure()`
  and skips adoption; corrupt or mismatched bodies become `uncertain`; the aggregate returns
  `RECONCILIATION_PERSISTENCE_FAILURE` (`:1663-1699`, `:2031-2037`). No promotion path is
  reached on a failed read.

### 4.3 Legacy scope and focused tests

- Legacy no-rules installs are scoped by `validate_install_policy_rules` returning `None` for
  absent rules and rejecting a schema-v1 `compiled` mirror without rules
  (`rule_schema_v1.py:372-378`). The service only populates `req['rules']` when rules are
  present (`controller_service.py:862-876`), and `_ensure_canonical_policy_body_persisted()` is
  a no-op for absent rules (`:415-422`) on the install path (`:1210-1212`).
- Focused tests cover: pre-read failure propagation with zero backend install calls
  (`test_post_j20_stage_1b6_targeted_residual_gaps.py:161-172`); reconciliation outer-probe
  failure as `RECONCILIATION_PERSISTENCE_FAILURE` with no adoption/reconciled action
  (`:175-197`); legacy no-rules success with no canonical body (`:200-207`); corrupt JSON as
  `uncertain` (`:210-234`); digest mismatch as `BrokerDBCanonicalError(INTEGRITY)` (`:237-247`);
  and conflict-winner mismatch fail-closed (`:250-260`). No assertion was weakened or skipped.

**Non-blocking note:** a nested canonical read failure *inside*
`read_trusted_canonical_policy_body()` during reconciliation is caught by the generic handler
and labeled `invalid_canonical_policy_body`/`uncertain` rather than
`RECONCILIATION_PERSISTENCE_FAILURE` (`controller_service.py:1682-1690`). It still fails closed
with no promotion; the focused test injects failure into the outer probe, which is correctly
classified.

**SR-08 conclusion: VERIFIED (scoped).** Failed reads are no longer treated as absence;
missing, unavailable, corrupt and mismatched canonical data are distinguished or fail closed; no
reviewed install, promotion or reconciliation path advances on a failed read; and legacy
no-rules compatibility remains narrowly scoped.

## 5. Phase 4 — Independent review of SR-09

### 5.1 Uniform guarded helper

`_set_reconciliation_status()` (`controller_service.py:1528-1583`) now implements the source
state contract:
- re-reads the authoritative record with `get_by_policy(pid, pver)` (`:1552`);
- verifies ownership identity is unchanged (`:1553`);
- requires the fresh `installation_state` to be in the caller's explicit `allowed_states`
  (`:1554-1555`);
- validates operation/policy binding through `_validate_ownership_binding(...)` using the
  operation-bound `inspect_req` (`:1556-1560`);
- optionally enforces `require_evidence` for verification or revocation status writes
  (`:1561-1566`);
- writes only under `reconciliation_version_guard(fresh['lifecycle_version'])` (`:1567-1568`);
- records an operation-bound audit row `reconcile_status_<status>` on success
  (`:1569-1579`);
- returns `False` on `PermissionError` from stale/identity/binding conflicts (`:1581-1583`).

Store-side primitives support the guard: thread-local
`reconciliation_version_guard` (`ownership_store.py:670-685`), versioned
`update_reconciliation_status` CAS (`:687-725`), lifecycle CAS (`:443-473`), grouped
`atomic_write()` state+history transactions (`:290-336`), audit/history/evidence appenders
(`:415-441`, `:475-486`) and append-only triggers (`:242-256`).

### 5.2 All reconciliation status writes

All 11 decision writes inside `reconcile_pending_operations` pass explicit `allowed_states`
and the generated `inspect_req`. The two previously unguarded branches are included:
- `needs_verification` under `allowed_states=('INSTALLING',)`
  (`controller_service.py:1814-1817`);
- `failed` under `allowed_states=('FAILED',)` (`controller_service.py:1844-1846`).

Other writes cover invalid/mismatched canonical body, unknown state, ACTIVE readback mismatch,
ACTIVE ok, install readback unavailable, VERIFYING errors/no-evidence, and unhandled known
states (`:1684-1715`, `:1768-1796`, `:1933-1950`, `:2001-2003`). Terminal-ish FAILED,
CLEANUP_PENDING and ORPHANED states intentionally perform no automatic status write
(`:1995-1997`). The `inspect_req` is constructed per iteration from fresh operation IDs bound
to policy, version, digest, ownership, instance, network and family (`:1647-1661`).

### 5.3 Evidence, stale workers and repeated recovery

Lifecycle promotions still require bound evidence: verification evidence at
`controller_service.py:1736` and `:1942`; revocation evidence at `:1879` and `:1905-1922`;
strict evidence binding in the store at `ownership_store.py:584-624`. Stale status writes return
conflict rather than overwriting. Tests prove:
- stale `ACTIVE` worker cannot overwrite a `REVOKING` state (`test_post_j20_stage_1b6_...py:265-280`);
- identity mismatch returns conflict without overwrite (`:283-304`);
- repeated reconciliation is stable and operation-bound with distinct audit request IDs
  (`:307-333`);
- every captured guard in the `needs_verification` path sees a non-null version
  (`:346-361`);
- a threaded stale worker cannot overwrite terminal `REVOKING` state/status (`:364-395`);
- ambiguous lifecycle state becomes `uncertain` with no promotion (`:398-416`).

**Scoped caveats:** compatibility fallbacks at `controller_service.py:1541-1547` bypass the
new state/identity checks for test-only stores lacking the guard and for legacy guarded
callers without `allowed_states`; no production `reconcile_pending_operations` call site uses
those fallbacks. `require_evidence` is not supplied by any current status-write caller because
VERIFIED/REVOKED decisions are lifecycle transitions, where evidence is already enforced.
The guard test captures the `needs_verification` path but not the `failed` path, although the
code routes both through the same helper. Status and audit are separate writes within the
guarded section, not one atomic transaction; this does not permit a status overwrite.

**SR-09 conclusion: VERIFIED (scoped).** Every production reconciliation status write is
identity-bound, source-state-fenced and lifecycle-version-CAS-guarded; stale workers conflict
rather than overwrite; terminal states are fenced; repeated recovery remains stable. The
compatibility, dead-parameter, test-coverage and status/audit atomicity notes are scoped
residuals, not bypasses.

## 6. Independent verification conclusion

| Finding | Intended property | Independent conclusion |
|---|---|---|
| SR-07 | Structured, non-string persistence classification with public error compatibility | **VERIFIED FIXED (scoped)** |
| SR-08 | Failed canonical reads never become absence; corruption/unavailability fails closed | **VERIFIED FIXED (scoped)** |
| SR-09 | Uniform explicit-state, identity-bound, CAS-fenced reconciliation status writes | **VERIFIED FIXED (scoped)** |

These conclusions apply only to the mock-only controller/persistence paths and evidence
reviewed here. They do not close gates, accept residual risk, prove host enforcement, authorize
live firewall integration, or imply production readiness.
