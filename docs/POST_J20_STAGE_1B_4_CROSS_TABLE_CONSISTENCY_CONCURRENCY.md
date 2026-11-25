# Post-J.20 Stage 1B.4 — Cross-Table Consistency and Concurrency (Mock-Only)

**Mandatory status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

**T-11, T-13, T-27: OPEN — ACCEPTANCE REQUIRED.** This document is evidence only. No gate
is closed, no gate status is changed, and no acceptance is claimed. No Stage 1B.5 or later
work is part of this task.

Repository: `E:\Flag-hunt\ctf-platform-be`
Baseline before this task (verified): HEAD `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`,
26 modified tracked files, 108 untracked files, 0 staged files, no 1B.4 files present.

Scope is strictly mock-only: disposable SQLite databases and in-process/file-backed mock
backends only. No Docker daemon/socket/SDK/container, UDS/`SO_PEERCRED`, privileged helper,
Linux capabilities, nftables, iptables, host firewall, host permission changes, system
services, cloud deployment, or live firewall operations.

Preserved baselines: Stage 1A.5, Stage 1B.1 (single `controller_idempotency` ledger,
informational operation outcomes), Stage 1B.2 (`atomic_write()` DB-only boundaries,
evidence before `REVOKED`, idempotency completion as final write, separate granular
install-failure writes, separate `VERIFYING`/canonical-body writes), and Stage 1B.3
(evidence-gated `VERIFYING` recovery, persistence-classified pending-ledger scan).

---

## Phase 1 — Cross-table consistency invariant inventory

Sources inspected before source modification:
`broker/firewall_controller_service/ownership_store.py` (schema, triggers, CAS/completion APIs),
`broker/firewall_controller_service/controller_service.py` (all lifecycle, ledger, evidence,
canonical-body and reconciliation call sites).

### 1. Ownership state and version

- **Records/columns:** `controller_ownership`: `ownership_record_id` (PK), `policy_id`,
  `policy_version`, `instance_id`, `network_id`, `canonical_policy_digest`, `address_family`,
  `installation_state`, `lifecycle_version`, `updated_at`, `revoked_at`,
  `reconciliation_status`, `last_reconciliation_at`.
- **DB constraints:** PK on `ownership_record_id`; `UNIQUE(policy_id, policy_version)`;
  `NOT NULL` on identity/digest/state/version; `lifecycle_version` is a plain integer with
  no DB-enforced monotonicity or state-value domain constraint.
- **Application enforcement:** `LIFECYCLE_TRANSITIONS` allow-list plus
  `_check_lifecycle_transition()`; every ownership-state write in `controller_service.py`
  uses `update_ownership_state(..., expected_version=...)` with a `BEGIN IMMEDIATE` CAS
  (`WHERE ... AND installation_state=? AND lifecycle_version=?`), incrementing the version
  and returning `PermissionError('LIFECYCLE_VERSION_CONFLICT')` on no-match;
  `atomic_write()` groups the CAS with its lifecycle-history row.
- **Concurrent writers:** install (create/intent, revalidation, backend-ok, backend-failure),
  verify (`VERIFYING`, `VERIFIED`, `ACTIVE`), revoke (`REVOKING`, `REVOKED`), reconciliation
  (four CAS transitions), and recovery paths sharing the same store/DB.
- **Remaining race windows:** a stale writer can read a valid `(state, version)` snapshot and
  lose its CAS; that is safe (fails closed) but its *other* writes are not automatically
  fenced. Non-state columns (`reconciliation_status`, `recovery_meta`) are written by
  unconditional SQL and are not version-guarded, so a stale reconciliation decision can land
  after a newer lifecycle decision.
- **Provable / not provable:** provable — at most one state transition succeeds per version,
  no lost increments, no duplicate ownership for a policy/version, no illegal transition from
  a CAS winner. Not provable from the schema alone — that a history row's `prev_state`
  corresponds to the immediately preceding committed history row under interleaving, or that
  an unconditional reconciliation-status write reflects the newest observed backend state.

### 2. Lifecycle history ordering and correlation

- **Records/columns:** `controller_lifecycle_history`: `history_id` (INTEGER PRIMARY KEY
  AUTOINCREMENT), `ownership_record_id`, `policy_id`, `policy_version`, `prev_state`,
  `new_state`, `operation_id`, `request_id`, `transition_reason`, `result`, `error_info`,
  `timestamp`.
- **DB constraints:** append-only `BEFORE UPDATE` and `BEFORE DELETE` triggers; index on
  `ownership_record_id`; no FK to ownership; no uniqueness on `(ownership_record_id, prev_state,
  new_state, operation_id)`; no stored `lifecycle_version`.
- **Application enforcement:** writes are appended through `record_lifecycle_transition()`;
  grouped with the state CAS in the 13 Stage 1B.2 boundaries; preserved install-failure path
  writes state and history separately to retain granular `failure_state_persisted` /
  `lifecycle_history_persisted` reporting.
- **Concurrent writers:** install, verify, revoke, reconciliation, recovery.
- **Remaining race windows:** two writers that both hold a stale snapshot cannot both win the
  CAS, but their ungrouped/ancillary history rows (install-failure path) and append-only rows
  from different operations can interleave. Because there is no version column, `history_id`
  proves global insertion order, not that the `prev_state -> new_state` chain is contiguous
  per ownership record.
- **Provable / not provable:** provable — append-only (where SQLite triggers apply), correlated
  to an ownership record/policy/version/operation, and no silent mutation/deletion of history.
  Not provable — a continuous per-ownership state chain from history rows alone, or that a
  history row exists for every successful state write when a grouped commit was interrupted
  (Stage 1B.2 DB-only atomicity covers grouped pairs, not backend effects).

### 3. Evidence ownership and policy-version binding

- **Records/columns:** `controller_evidence`: `evidence_id` (PK), `ownership_record_id`,
  `policy_id`, `policy_version`, `instance_id`, `network_id`, `canonical_policy_digest`,
  `address_family`, `installed_rule_ids_json`, `controller_identity`,
  `controller_transaction_id`, `request_id`, `verification_timestamp`, `verification_result`.
- **DB constraints:** PK on `evidence_id`; append-only `BEFORE UPDATE`/`BEFORE DELETE` triggers;
  no FK to ownership, no uniqueness across evidence rows, no DB check on `verification_result`.
- **Application enforcement:** `_store_verification_evidence()` and
  `_store_revocation_evidence()` copy authoritative identity/digest from the validated
  ownership record. `_find_valid_verification_evidence()` / `_has_revocation_evidence()` accept
  a row only when result, ownership record id, canonical digest, policy id/version, instance,
  network and family all match the current authoritative record. Evidence is persisted before
  `REVOKED` promotion and before idempotency completion; reconciliation requires evidence for
  `VERIFIED`/`VERIFYING` promotion and for terminal `REVOKED` acceptance.
- **Concurrent writers:** verify, revoke, reconciliation (both direct completion paths).
- **Remaining race windows:** identity validation is a snapshot check, not a lifecycle CAS.
  Evidence can be appended for a still-valid ownership identity while a concurrent writer
  advances lifecycle state; the row remains correctly *bound* but may no longer describe the
  current lifecycle phase. Verification and revocation evidence rows are not mutually
  exclusive at the DB level; application result checks provide the separation.
- **Provable / not provable:** provable — no misbound evidence is accepted for promotion or
  terminal acceptance under the application binding checks; evidence is append-only. Not
  provable — that every evidence row was produced by a backend effect that succeeded (the row
  proves an *observed* result recorded by this controller, not an independent backend truth),
  or that two concurrent verifies cannot produce multiple valid evidence rows for the same
  ownership (uniqueness is intentionally not enforced).

### 4. Audit correlation and immutability

- **Records/columns:** `controller_audit`: `audit_id` (INTEGER PRIMARY KEY AUTOINCREMENT),
  `event_type`, `request_id`, `operation_id`, `policy_id`, `ownership_record_id`,
  `details_json`, `timestamp`.
- **DB constraints:** append-only `BEFORE UPDATE`/`BEFORE DELETE` triggers; no FK; no uniqueness
  on correlation keys.
- **Application enforcement:** `record_audit()` inserts through `_execute_fk()`; service audit
  uses `self.audit.log()` plus explicit store audit writes at intent, evidence, revoke
  uncertainty, unknown-state and missing-evidence events. Several audit writes are deliberately
  best-effort (`except Exception: pass`) so an audit failure cannot mask the primary outcome.
- **Concurrent writers:** all request dispatch paths and reconciliation.
- **Remaining race windows:** `audit_id` gives a global append order but no per-operation
  ordering guarantee beyond insertion time; best-effort writes mean an audit record is not a
  completion proof. `updated_at`-style mutation is blocked by triggers where supported.
- **Provable / not provable:** provable — append-only and correlated by request/operation/
  ownership identifiers when recorded. Not provable — completeness of the audit stream under
  best-effort failures, or that audit ordering alone establishes lifecycle ordering.

### 5. Idempotency operation identity and terminal outcomes

- **Records/columns:** `controller_idempotency`: (`idempotency_key`, `operation_type`) PK,
  `request_digest`, `resource_key`, `ownership_record_id`, `status`, `lifecycle_state`,
  `response_json`, `recovery_meta_json`, `operation_outcome`, `outcome_updated_at`,
  `completed_at`.
- **DB constraints:** composite PK; index on `status`; no DB check limiting `operation_outcome`
  or preventing overwrite of a `COMPLETED` row.
- **Application enforcement:** `_req_digest()` binds operation + security-relevant payload;
  pre-check and replay decision reject same-key/different-payload; `create_idempotency_record()`
  creates `PENDING` before backend effects with UNIQUE-collision reclassification;
  `update_operation_outcome()` is CAS-guarded on `expected_outcomes` for `IN_PROGRESS`;
  `complete_idempotency_record()` writes `COMPLETED`, response, ownership identity metadata
  and terminal outcome as the final persistence step.
- **Concurrent writers:** same-key identical/conflicting requests, recovery retries (notably
  revoke `recover` path), and reconciliation's read-only pending scan.
- **Remaining race windows:** `complete_idempotency_record()` is an **unconditional** UPDATE
  with no `status='PENDING'` or outcome guard, so two workers that both legitimately reach the
  completion path (e.g. concurrent revoke recovery under the same key) can overwrite each
  other's terminal response/outcome. A successful `SUCCEEDED` terminal record can regress to
  `UNCERTAIN` (or vice versa) purely by completion ordering.
- **Provable / not provable:** provable — one row per `(key, operation)`, payload conflict is
  rejected, storage failures remain distinct from conflicts/pending. Not provable — that a
  terminal outcome remains stable under concurrent completion, or that a `COMPLETED` row implies
  the backend effect was independently confirmed (it records what the controller observed).

### 6. Canonical policy-body digest and trusted read-back

- **Records/columns:** `controller_policy_bodies`: `policy_body_id` (PK), `ownership_record_id`
  (FK), `policy_id`, `policy_version`, `schema_version`, `canonical_rules_json`,
  `required_families_json`, `compiled_rule_digest`, `canonical_policy_digest`,
  `controller_identity`, `request_id`, `operation_id`, timestamps.
- **DB constraints:** PK; `UNIQUE(policy_id, policy_version)`; FK to ownership; index on owner;
  no DB-level rule/schema validation.
- **Application enforcement:** `store_canonical_policy_body()` validates/normalizes schema-v1
  rules, recomputes the compiled digest, verifies ownership binding/digest, and inserts;
  `ensure_canonical_policy_body()` is an idempotent read-validate-then-write wrapper;
  `read_trusted_canonical_policy_body()` re-validates and recomputes on every trusted read.
- **Concurrent writers:** concurrent install/revalidation requests for the same policy/version
  (different idempotency keys), plus recovery re-persistence.
- **Remaining race windows:** `ensure_canonical_policy_body()` performs its existence check and
  `store_canonical_policy_body()` insert in separate transactions. Two concurrent writers can
  both observe absence; the loser hits the `UNIQUE(policy_id, policy_version)` violation, which
  surfaces as `BrokerDBError` / `FirewallControllerPersistenceError` rather than being resolved
  as an idempotent conflict against the now-existing, matching body.
- **Provable / not provable:** provable — at most one canonical body per policy/version, FK
  binding, digest recomputation on read, fail-closed on corruption/mismatch. Not provable —
  that a concurrent `ensure` cannot spuriously fail with a persistence classification, or that
  the first writer's body is the only one ever offered for insertion.

### 7. Reconciliation decisions and durable state

- **Records/columns:** decision inputs — `controller_ownership.installation_state`,
  `lifecycle_version`, `canonical_policy_digest`, `address_family`, `reconciliation_status`,
  `last_reconciliation_at`; evidence via `controller_evidence`; pending operations via
  `controller_idempotency.status`/`operation_outcome`.
- **DB constraints:** same as invariants 1/3/5; `reconciliation_status` is a free-form TEXT
  with no DB domain constraint.
- **Application enforcement:** reconciliation re-reads targets, validates persisted binding and
  canonical body, inspects the mock backend, requires evidence for promotion/terminal acceptance,
  uses CAS + `atomic_write()` for state transitions, and classifies persistence failures and
  pending ledgers distinctly (Stage 1B.3).
- **Concurrent writers:** multiple reconciliation workers, reconciliation vs in-flight
  install/verify/revoke, reconciliation vs crash recovery, and the pending-ledger scan vs
  idempotency completion.
- **Remaining race windows:** `update_reconciliation_status()` is an unconditional SQL UPDATE
  with no lifecycle-version or snapshot guard. A worker that observed an older state/backend
  result can write its decision after a newer worker (or after a lifecycle transition), leaving
  a `reconciliation_status` that contradicts the durable state. The pending-ledger scan is a
  point-in-time report: a record can complete immediately after being scanned and still be
  reported as `pending_no_auto_replay` (explicitly uncertain, not a false success).
- **Provable / not provable:** provable — no unauthorized promotion without evidence + trusted
  read-back, uncertain outcomes remain uncertain, persistence failures are classified, backends
  are never inferred from intent. Not provable — that the final `reconciliation_status` is from
  the newest reconciliation decision, or that the pending scan is a linearizable snapshot of
  the ledger.

---

## Phase 2 — Concurrency investigation plan

Scenarios to exercise before source changes (all mock-only, deterministic events/barriers where
possible, no timing sleeps used to hide races):

1. Same-key identical requests.
2. Same-key conflicting requests (payload digest mismatch).
3. Different keys targeting the same policy (initial install and revalidation).
4. Concurrent install and revoke.
5. Concurrent verify and revoke.
6. Multiple reconciliation workers.
7. Recovery competing with an in-flight operation.
8. Concurrent evidence and ownership transitions.

Each scenario is checked against the invariants above for: duplicate ownership, conflicting
terminal states, duplicate backend effects, lost committed intent, orphaned/misbound evidence,
unauthorized promotion, false success, ledger stability, and append-only integrity.

**Reproduced defects and source changes are recorded in the final sections below.**

---

## Reproduced defects (Phase 2)

All three defects were reproduced against the unmodified source with deterministic
thread barriers/events (`post_j20_stage_1b4_repro.py` and early revisions of the new
suite, retained as untracked evidence). No source was changed before this reproduction.

1. **D-1 — stale idempotency completion overwrote a confirmed terminal outcome.**
   Two revoke-recovery workers shared one idempotency key. Worker A observed backend
   revocation, promoted `REVOKING -> REVOKED` with evidence and completed with
   `SUCCEEDED`. Worker B had already entered `IN_PROGRESS` from a stale readback error;
   its later completion used unconditional SQL and replaced A's `SUCCEEDED` record with
   `UNCERTAIN` plus an error response. Observed before fix:

   ```
   REPRO 1 terminal-overwrite:
     thread outcomes: {'A': 'ok', 'B': 'error'}
     ownership state: REVOKED
     idempotency status/outcome: COMPLETED UNCERTAIN
     cached response status: error
   ```

   This violated conflicting-terminal-outcome prevention, stable idempotency records
   and no-false-uncertainty. The `IN_PROGRESS` CAS did not fence it because B entered
   `IN_PROGRESS` before A completed.

2. **D-2 — stale reconciliation decision overwrote newer durable state.**
   A reconciler read `ACTIVE`, reached its `reconciliation_status='ok'` write, and was
   held there while a concurrent revoke committed `REVOKED`. The unconditional status
   UPDATE then wrote `ok` over the newer lifecycle decision. Observed before fix:

   ```
   REPRO 2 stale-reconciliation:
     ownership state: REVOKED
     reconciliation_status: ok
   ```

3. **D-3 — concurrent canonical-body ensure misclassified an idempotent UNIQUE race.**
   Two different-key installs for the same policy/version both observed no canonical
   body; the loser hit `UNIQUE constraint failed: controller_policy_bodies...` and
   surfaced `BrokerDBError: Failed to store canonical policy body` instead of validating
   the durable winning body. This violated "distinguish persistence failures, conflicts
   and pending operations" and produced a false failure for a legitimate operation.

Not proven as a defect and deliberately not remediated: the design-time observation
that lifecycle history has no stored `lifecycle_version` (append-only `history_id` proves
global insertion order but not a continuous per-ownership chain). Changing that schema
or adding a parallel correlation ledger is outside this narrow stage. Distinct
idempotency keys are distinct operations, so repeated backend effects for different keys
are not treated as duplicate effects; duplicate ownership and conflicting terminal states
are.

## Source changes and rationale (Phase 3)

Three narrow, mock-only changes; no schema, migration, lifecycle state, public API break,
new ledger, or parallel state machine.

1. `ControllerOwnershipStore.complete_idempotency_record(..., expected_outcomes=None)`:
   additive optional CAS guard on the current informational operation outcome, scoped by
   `BEGIN IMMEDIATE` in the same transaction as the completion write. A guard miss returns
   `False` (conflict, never `BrokerDBError`); genuine storage failures still propagate.
   `broker/firewall_controller_service/controller_service.py` now passes
   `expected_outcomes=('IN_PROGRESS',)` at the single completion site and, on a guard
   miss, replays the authoritative terminal record rather than overwriting it. If the
   authoritative record cannot be returned safely, it raises
   `FirewallControllerIdempotencyError('Operation ledger state conflict')`.
2. `ControllerOwnershipStore.reconciliation_version_guard(expected_version)`:
   additive thread-local context manager (same pattern as `atomic_write`) plus an
   optional guarded branch in `update_reconciliation_status()` using
   `WHERE ownership_record_id=? AND lifecycle_version=?`. Guard miss returns `False`;
   unguarded legacy callers keep the original write behaviour. The service helper
   `_set_reconciliation_status()` applies the guard only to reconciliation decisions
   derived from an ownership snapshot where no lifecycle CAS already fenced the write.
   `ACTIVE/ok` now reports `uncertain` with reason `reconciliation_state_changed` when
   the guard misses, instead of claiming a stale successful decision.
3. `ControllerOwnershipStore.ensure_canonical_policy_body()` was refactored to share
   `_validate_existing_canonical_policy_body()`. If the insert loses only the
   `controller_policy_bodies` UNIQUE race, it re-reads and validates the durable winner
   (ownership binding, digest, trusted read-back, rules digest) and returns its id.
   Mismatches and all other storage failures still raise `BrokerDBError`.

Preserved explicitly: `atomic_write()` DB-only boundaries; evidence before `REVOKED`
promotion and before idempotency completion; separate granular install-failure writes;
separate `VERIFYING`/canonical-body writes; F-02 raw `BrokerDBError` for failed ownership
lookup; append-only triggers/controls; uncertainty semantics; no end-to-end atomicity
claim across SQLite writes and mock backend effects.

## Concurrency test results (Phase 4)

New suite: `broker/tests/test_post_j20_stage_1b4_cross_table_concurrency.py` — **15
passed, 1 warning, exit 0**. It uses deterministic thread barriers/events and real
spawned-process SQLite contention. Coverage: same-key identical/conflicting requests;
different keys targeting one policy; concurrent install/revoke and verify/revoke;
multiple reconcilers; reconciliation vs revoke recovery; evidence/ownership binding
mismatch; stale CAS; stale reconciliation decisions; terminal-outcome stability;
append-only history/audit/evidence under concurrent writers; canonical-body single row;
cross-process same-key conflict classification. Assertions check actual invariants —
single ownership, at most one terminal transition, one backend effect per same-key
operation, stable per-key ledger rows, no misbound evidence, no `REVOKED -> ACTIVE`
promotion, and append-only integrity — not merely exception classes.

The suite was repeated 15 times during development. Two early failures were traced to
over-strict test expectations (a losing distinct-key request legitimately leaves durable
`PENDING` intent; a distinct-key operation may legitimately fail with a version-conflict
`PermissionError`), not to source defects; the assertions were corrected to assert the
real invariants and the final suite passed every repetition. No assertion was weakened
to accept a false success or a lost record.

## Full regression evidence (Phase 5)

Captured by `post_j20_stage_1b4_runner.py`; each suite has `.stdout.txt`, `.stderr.txt`
and `.exit.txt` with `EXIT`, `ELAPSED_SECONDS` and `SUMMARY` in the repository root.

| Suite | Result | Exit |
|---|---|---|
| New Stage 1B.4 | 15 passed, 1 warning, 18.22s | 0 |
| Stage 1B.1 | 16 passed, 1 warning, 12.19s | 0 |
| Stage 1B.2 | 19 passed, 1 warning, 20.07s | 0 |
| Stage 1B.3 | 24 passed, 1 warning, 33.53s | 0 |
| J.8 | 11 passed, 1 warning, 29.62s | 0 |
| J.9 | 5 passed, 1 warning, 4.17s | 0 |
| J.10 | 9 passed, 1 warning, 6.78s | 0 |
| J.12 | 14 passed, 1 warning, 8.13s | 0 |
| J.13 | 22 passed, 1 warning, 16.10s | 0 |
| J.17 | 20 passed, 1 warning, 16.45s | 0 |
| Complete broker suite | 928 passed, 1 warning, 460.22s (0:07:40) | 0 |

Warnings are the pre-existing pytest-asyncio/pydantic deprecation warnings. Any failure
would be investigated rather than suppressed; none occurred in the targeted suites.

## Remaining risks and limitations

- Evidence rows prove what this controller observed at a backend boundary; they are not
  independent proof of host firewall state. No live firewall claim is made.
- `controller_lifecycle_history` is append-only and globally ordered by `history_id`,
  but has no stored lifecycle version; a continuous per-ownership chain is not claimed.
- The pending-ledger reconciliation scan is a point-in-time report; a record can complete
  immediately after being scanned. It is reported as uncertain/pending, never as success.
- SQLite `BEGIN IMMEDIATE` serialises DB writers; mock backend effects remain outside the
  DB transaction. No end-to-end atomicity is claimed.
- The canonical-body UNIQUE resolution is intentionally narrow: it revalidates only the
  single durable winner of that exact constraint; any mismatch still fails closed.
- T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**. This evidence does not close
  or alter any gate. Live firewall integration remains unauthorized; Stage 1B.5 and later
  work were not started.
