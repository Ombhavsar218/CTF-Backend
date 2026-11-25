# Post-J.20 Stage 1B.6 — Targeted Residual Gap Remediation (Mock-Only)

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.** This milestone addresses only
the three source-provable residual gaps recorded in Stage 1B.5. It does not close any gate,
claim formal risk acceptance, authorize live firewall integration, start Stage 1C, or
perform Docker/UDS/host operations.

## 1. Baseline and pre-change identification

Repository: `E:\Flag-hunt\ctf-platform-be`  
HEAD verified: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`  
Baseline working tree: 26 modified tracked files, 166 untracked files, **0 staged files**
before Stage 1B.6 artifacts. No reset, clean, revert, stage or commit was performed.

The four Stage 1B.5 deliverables were read before any source change:
- `docs/POST_J20_STAGE_1B_5_INDEPENDENT_SECURITY_REVIEW.md`
- `docs/POST_J20_STAGE_1B_5_FINAL_RISK_REGISTER.md`
- `docs/POST_J20_STAGE_1B_5_REMEDIATION_ROADMAP.md`
- `docs/POST_J20_STAGE_1B_5_FINAL_READINESS_DECISION.md`

| Finding ID | Gap | Exact affected code before change | Reproduction evidence | Acceptance criteria |
|---|---|---|---|---|
| SR-07 | String-based persistence classification | `ownership_store.py:create_idempotency_record()` (INSERT + message text), `store_canonical_policy_body()`/`ensure_canonical_policy_body()` (`'UNIQUE constraint failed'` + table substring), `controller_service.py` duplicate-create caller and `_sanitize_canonical_policy_error()` (message-substring category mapping) | Message matching cannot distinguish the canonical-body PRIMARY KEY (`policy_body_id`) conflict from the intended `(policy_id, policy_version)` UNIQUE race; driver text changes could invert classification; raw DB text was mapped to public categories | Typed conflict exceptions; targeted `ON CONFLICT(...) DO NOTHING`; structured canonical categories; genuine `BrokerDBError` propagation; deterministic expected/unexpected error tests |
| SR-08 | Canonical pre-read failure treated as absence | `ownership_store.py:ensure_canonical_policy_body()` — `except Exception: existing = None`, contradicting `_query_dicts()` rule at `ownership_store.py:337-342` | A `BrokerDBError` from `get_canonical_policy_body()` was converted to \"no body\" and the insert path continued | Read failures propagate as `BrokerDBError`; missing/corrupt/mismatched/unavailable data fails closed; no install/promotion/reconciliation treats unverified read as absence; legacy no-rules no-op preserved |
| SR-09 | Non-uniform reconciliation status fencing | `controller_service.py:_set_reconciliation_status()` plus previously unguarded writes at `controller_service.py:1754` (`needs_verification`) and `:1781` (`failed`) | Two reconciliation branches wrote status directly without version guard/source-state binding; stale workers could overwrite a newer decision | Every reconciliation decision uses explicit allowed source states, fresh authoritative record, identity/policy binding, CAS, operation-bound audit, and uncertain handling for conflicts |

## 2. Scope of source changes

Only two service source files and one new test file were changed:
- `broker/firewall_controller_service/ownership_store.py`
- `broker/firewall_controller_service/controller_service.py`
- `broker/tests/test_post_j20_stage_1b6_targeted_residual_gaps.py` (new)

No parallel ledger, state machine, schema migration, broad refactor or weakened assertion was
introduced. All Stage 1B.1–1B.5 behavior and evidence files were preserved.

## 3. Gap 1 — SR-07: structured persistence classification

**Implemented changes**
- Added typed `BrokerDBError` subclasses in `ownership_store.py`:
  - `BrokerDBCanonicalError` with stable `OWNERSHIP`, `INTEGRITY` and `PERSISTENCE` categories.
  - `BrokerDBIdempotencyConflict` for the exact `controller_idempotency` PRIMARY KEY.
  - `BrokerDBCanonicalBodyConflict` for the exact `controller_policy_bodies(policy_id, policy_version)` UNIQUE index.
- `create_idempotency_record()` now issues
  `ON CONFLICT(idempotency_key, operation_type) DO NOTHING`; a zero-row insert raises the
  typed conflict. Generic failures remain plain `BrokerDBError`.
- `store_canonical_policy_body()` now issues
  `ON CONFLICT(policy_id, policy_version) DO NOTHING`; a zero-row insert raises the typed
  conflict. PK/FK/other integrity errors and generic storage failures are not reclassified.
- `ensure_canonical_policy_body()` resolves only `BrokerDBCanonicalBodyConflict` by
  re-reading and fully validating the durable winner.
- `controller_service.py` duplicate-create handling now uses
  `isinstance(create_exc, BrokerDBIdempotencyConflict)` instead of message substrings.
- `_sanitize_canonical_policy_error()` now uses `BrokerDBCanonicalError.category` instead of
  matching exception text. Public exception compatibility is preserved by subclassing
  `BrokerDBError` and retaining the same bounded service errors.

**Deterministic tests**
- Typed canonical-body conflict resolves the durable winner.
- Generic canonical storage failure is not an idempotent conflict and blocks backend dispatch.
- Idempotency duplicate is typed; generic idempotency failure is not.
- Structured canonical categories map to the same bounded `PermissionError`,
  `FirewallControllerRequestError` and `FirewallControllerPersistenceError` responses.

## 4. Gap 2 — SR-08: canonical read failures are never absence

**Implemented changes**
- `ensure_canonical_policy_body()` now re-raises `BrokerDBError` from the trusted pre-read and
  wraps any non-DB read failure as `BrokerDBError('Canonical policy body pre-read failed: ...')`.
  The previous `except Exception: existing = None` conversion was removed.
- The canonical conflict winner read is explicit: a missing winner raises `BrokerDBError`;
  a mismatched winner fails closed through trusted validation.
- Reconciliation already classified a failed `get_canonical_policy_body()` as
  `RECONCILIATION_PERSISTENCE_FAILURE`; this behavior is now covered by a regression test.
- Legacy installs without schema-v1 `rules` still return `None` before any canonical read and
  remain unchanged.

**Deterministic tests**
- Injected pre-read failure propagates as `BrokerDBError` and `backend.install_calls == 0`.
- Legacy no-rules install succeeds with no canonical body.
- Corrupt canonical JSON makes reconciliation explicitly `uncertain` with
  `reason='invalid_canonical_policy_body'` and status `uncertain`.
- Mismatched compiled digest fails closed with `BrokerDBCanonicalError(INTEGRITY)`.
- Conflict winner mismatch is a fail-closed persistence/integrity error, not a false success.
- Reconciliation read failure returns `RECONCILIATION_PERSISTENCE_FAILURE` with no adoption
  or reconciliation action.

## 5. Gap 3 — SR-09: uniform reconciliation status fencing

**Implemented changes**
- `_set_reconciliation_status()` now supports an explicit source-state contract:
  - re-reads the authoritative record;
  - verifies ownership identity is unchanged;
  - requires the fresh state to be in `allowed_states`;
  - validates operation/policy binding from the generated inspection request;
  - optionally requires verification/revocation evidence;
  - writes only under `reconciliation_version_guard(fresh.lifecycle_version)`;
  - records an operation-bound audit row (`reconcile_status_<status>`) on a successful write;
  - returns `False` on stale/ambiguous/binding conflicts (never a newer-state overwrite).
- Every reconciliation decision call site now passes explicit `allowed_states` and the
  operation-bound `inspect_req`, including the two previously unguarded writes:
  - `needs_verification` after backend-installed recovery;
  - `failed` after backend-missing recovery.
- The operation inspection request is constructed before the canonical-body validation branch
  so all decision paths share the same identity contract.
- State-changing transitions already used lifecycle CAS, allowed-edge checks and operation-bound
  lifecycle history; those controls were preserved, not replaced.

**Deterministic tests**
- Stale worker with `ACTIVE` snapshot cannot write status after state advanced to `REVOKING`.
- Ownership identity mismatch returns a conflict without overwriting status.
- Repeated reconciliation is stable and writes distinct operation-bound audit rows for the
  same policy/ownership.
- `_GuardCaptureStore` proves each status write observes a non-null version guard.
- Threaded concurrent recovery: a stale worker observed after advancement cannot overwrite
  the terminal `REVOKING` state or its status.
- Ambiguous lifecycle state is explicitly `uncertain` with no promotion.

## 6. Verification evidence

All commands used `venv\Scripts\python.exe` from `E:\Flag-hunt\ctf-platform-be`.

| Evidence file | Scope | Actual result | Exit |
|---|---|---|---:|
| `post_j20_stage_1b6_new_suite.stdout.txt`, `.stderr.txt`, `.exit.txt` | 16 new Stage 1B.6 tests | **16 passed, 1 warning in 6.14s** | **0** |
| `post_j20_stage_1b6_targeted.stdout.txt`, `.stderr.txt`, `.exit.txt` | Stage 1B.1–1B.4 suites, Stage 1A canonical, J.12/J.13/J.15/J.16/J.17, identifier/transport checks | **301 passed, 1 warning in 140.82s (0:02:20)** | **0** |
| `post_j20_stage_1b6_full.stdout.txt`, `.stderr.txt`, `.exit.txt` | Full `broker/tests` suite | **944 passed, 1 warning in 391.61s (0:06:31)**, elapsed 395.89s | **0** |

The full-suite delta is 928 (Stage 1B.4) + 16 new Stage 1B.6 tests = 944. No test was removed,
skipped or weakened. Stderr contains the pre-existing pytest-asyncio
`PytestDeprecationWarning` wrapped by PowerShell's native-stderr capture record; stdout contains
the pre-existing pydantic v2 deprecation notice. There were **0 failed and 0 errors** in the
final runs.

**Failures investigated:** the first new-suite run returned `3 failed, 11 passed, EXIT=1`.
The three failures were: an `UnboundLocalError` because `inspect_req` was referenced before its
construction in the canonical-body branch; an incorrect test assumption that reconciliation
persists the caller's request id rather than its generated operation identity; and an incorrect
previous-state value in a test rewind helper. All three were corrected without weakening any
assertion. The chronology is preserved in
`post_j20_stage_1b6_new_suite.initial_failure.note.txt`.

## 7. Final per-gap decision

| Gap | Finding | Decision | Basis |
|---|---|---|---|
| Gap 1 — String-based persistence classification | SR-07 | **VERIFIED FIXED (scoped)** | Targeted SQL conflict targets replace ambiguous message matching; typed errors and structured categories are covered by deterministic expected/unexpected-error tests; public exception behavior preserved; full suite green. |
| Gap 2 — Canonical pre-read failure treated as absence | SR-08 | **VERIFIED FIXED (scoped)** | Read failures propagate; missing/corrupt/mismatched/unavailable canonical data fails closed; legacy no-rules path preserved; no installation, promotion or reconciliation decision treats an unverified read as absence in tested paths. |
| Gap 3 — Non-uniform reconciliation status fencing | SR-09 | **VERIFIED FIXED (scoped)** | Every reconciliation decision call site now uses explicit allowed states, fresh binding/CAS and operation audit; the two previously unguarded writes are routed through the guard; stale/ambiguous/concurrent cases fail closed as conflicts. |

"Scoped" means the mock-only controller/persistence paths reviewed in Stage 1B.5 and exercised
by the tests above. It does not mean universal deployment closure or formal risk acceptance.

## 8. Residual exposure and gate posture

- SR-06, SR-10, SR-11, SR-12, SR-13 and SR-14 remain as recorded in Stage 1B.5; this milestone
  did not address host trust, live backend semantics, end-to-end atomicity, legacy migration or
  documentation-governance items.
- No gate is VERIFIED CLOSED. N-02, N-04, H-02, H-05, I-07, I-08, I-09, RR-01–RR-07, M-01 and
  M-06 remain at their existing registered statuses.
- T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**.
- No residual risk is formally accepted; the mandatory status remains
  **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
- No live firewall, Docker, UDS/`SO_PEERCRED`, privileged helper, capability, nftables/iptables,
  host permission, system-service, cloud or Stage 1C work was performed.

## 9. Final Git-state check

Before documentation updates: HEAD `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`, 26 modified
tracked files, 176 untracked entries (166 baseline + 10 new Stage 1B.6 evidence files; the new
test and document fall inside already-untracked directories), **0 staged files**. Final check
after documentation updates: same HEAD, 26 modified tracked files, 176 untracked entries,
0 staged files. No reset, clean, revert, stage or commit was performed; all prior user work
and evidence were preserved.
