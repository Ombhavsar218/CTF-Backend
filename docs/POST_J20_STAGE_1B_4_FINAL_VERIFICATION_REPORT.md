# Post-J.20 Stage 1B.4 — Final Verification Report (Mock-Only)

**Mandatory status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

**T-11, T-13, T-27: OPEN — ACCEPTANCE REQUIRED.** This report is evidence only. No gate
is closed, no gate status is changed, and no acceptance is claimed. Stage 1B.5 was not
started.

Repository: `E:\Flag-hunt\ctf-platform-be`
Baseline before Stage 1B.4: HEAD `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`,
26 modified tracked files, 108 untracked files, 0 staged files, no Stage 1B.4 files.
Final Git state: same HEAD, **26 modified tracked files, 163 untracked files, 0 staged
files**, no Stage 1B.5 files. No reset, clean, revert, stage or commit was performed.
All original user modifications and untracked evidence were preserved; the untracked
count increased only by this milestone's evidence artifacts.

Scope remained strictly mock-only: disposable SQLite databases and in-process/file-backed
mock backends. No Docker daemon/socket/SDK/container, UDS/`SO_PEERCRED`, privileged helper,
Linux capabilities, nftables, iptables, host firewall, host permission changes, system
services, cloud deployment or live firewall operations were used.

## 1. Prerequisite and phase sequence

- Phase 1 invariant inventory was written to
  `docs/POST_J20_STAGE_1B_4_CROSS_TABLE_CONSISTENCY_CONCURRENCY.md` **before** any source
  change.
- Phase 2 reproduced three concrete defects against unmodified source (recorded in the
  same document and in `post_j20_stage_1b4_repro.py`).
- Phase 3 applied only narrow remediations for those proven defects.
- Phase 4 added a deterministic 15-test concurrency suite.
- Phase 5 ran all required suites plus the complete broker suite and captured raw
  stdout, stderr, elapsed time, summary and actual exit codes for each.

## 2. Source changes (final)

All work stayed on the injectable store/service objects; no schema, migration, lifecycle
state, ledger, public API break or broad refactoring.

1. `ControllerOwnershipStore.complete_idempotency_record(..., expected_outcomes=None)`:
   additive CAS guard on the current informational operation outcome. A guard miss
   returns `False` (conflict, never `BrokerDBError`); genuine storage failures still
   propagate. The single service completion site now passes `expected_outcomes=
   ('IN_PROGRESS',)` and replays the authoritative terminal record on a guard miss.
2. `ControllerOwnershipStore.reconciliation_version_guard(expected_version)`: additive
   thread-local guard used by `_set_reconciliation_status()` so a reconciliation decision
   derived from an older lifecycle snapshot cannot overwrite a newer decision. A miss
   yields `uncertain` with reason `reconciliation_state_changed`.
3. `ControllerOwnershipStore.ensure_canonical_policy_body()` now validates the durable
   winner of a single `controller_policy_bodies` UNIQUE race instead of misclassifying
   that idempotent conflict as a persistence failure.

Preserved: Stage 1B.1 single idempotency ledger and informational outcomes; Stage 1B.2
`atomic_write()` DB-only boundaries, evidence before `REVOKED`, completion as final write,
separate granular install-failure writes; Stage 1B.3 evidence-gated `VERIFYING` recovery
and persistence-classified pending-ledger scan; F-02 raw `BrokerDBError` propagation;
append-only history/audit/evidence controls; uncertainty semantics; all existing
assertions. No end-to-end atomicity across SQLite and mock backend effects is claimed.

## 3. Verification evidence

Captured by `post_j20_stage_1b4_runner.py` into
`post_j20_stage_1b4_<suite>.stdout.txt`, `.stderr.txt` and `.exit.txt`.

| Suite | Summary | Exit | Wall time |
|---|---|---|---|
| New Stage 1B.4 | 15 passed, 1 warning in 18.22s | 0 | 20.58s |
| Stage 1B.1 | 16 passed, 1 warning in 12.19s | 0 | 15.06s |
| Stage 1B.2 | 19 passed, 1 warning in 20.07s | 0 | 22.65s |
| Stage 1B.3 | 24 passed, 1 warning in 33.53s | 0 | 36.33s |
| J.8 | 11 passed, 1 warning in 29.62s | 0 | 32.09s |
| J.9 | 5 passed, 1 warning in 4.17s | 0 | 7.07s |
| J.10 | 9 passed, 1 warning in 6.78s | 0 | 9.50s |
| J.12 | 14 passed, 1 warning in 8.13s | 0 | 10.57s |
| J.13 | 22 passed, 1 warning in 16.10s | 0 | 21.06s |
| J.17 | 20 passed, 1 warning in 16.45s | 0 | 19.43s |
| **Complete broker suite** | **928 passed, 1 warning in 460.22s (0:07:40)** | **0** | **463.32s** |

Full-suite evidence files:
- `post_j20_stage_1b4_full.stdout.txt` — final line `928 passed, 1 warning in 460.22s (0:07:40)`.
- `post_j20_stage_1b4_full.stderr.txt` — pre-existing `PytestDeprecationWarning` only.
- `post_j20_stage_1b4_full.exit.txt` — `EXIT=0`,
  `ELAPSED_SECONDS=463.32`, `SUMMARY=928 passed, 1 warning in 460.22s (0:07:40)`.

**Failure investigation:** none required — 928 passed, 0 failed, 0 errors, actual exit 0.
The single warning is the pre-existing pytest-asyncio `asyncio_default_fixture_loop_scope`
configuration warning; the stdout warning is the pre-existing pydantic v2 deprecation.
No assertion was weakened or skipped to obtain these results.

The new suite was additionally repeated 15 times during development; two early failures
were traced to over-strict test expectations and corrected to assert the real invariants
(durable `PENDING` intent after a losing distinct-key CAS is not a lost record; a
distinct-key version-conflict `PermissionError` is not a false success). The final suite
passed all repetitions.

## 4. Findings and residual limitations

- No remaining reproducible defect was found in the three repaired areas by the required
  suites.
- Lifecycle history remains append-only and globally ordered by `history_id`, but has no
  stored lifecycle version; a continuous per-ownership chain is not claimed.
- The pending-ledger reconciliation scan is a point-in-time report and may report an
  operation that completes immediately afterwards as pending/uncertain — never as success.
- Evidence proves what the controller observed at a mock backend boundary, not host
  firewall state.
- These limits are documented in
  `docs/POST_J20_STAGE_1B_4_CROSS_TABLE_CONSISTENCY_CONCURRENCY.md` and the security-gate
  register entry; they are not gate closures.

## 5. Stage 1B.5 prerequisite confirmation

The Stage 1B.4 full broker regression evidence is **complete**: the runner exited with
actual exit code 0 and captured stdout, stderr, elapsed time and summary for the full
suite. Combined with the completed Stage 1B.1–1B.4 documentation, source, test evidence
and preserved Git state, the **Stage 1B.4 prerequisite for Stage 1B.5 is satisfied**.

This confirmation does **not** start Stage 1B.5, authorize live firewall integration, or
close/alter any gate. T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**, and the
mandatory status remains **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
