# Post-J.20 Stage 1A.3 — Cross-Process Idempotency Failure Diagnosis and Stabilization (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Branch:** `main`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged)  
**Task:** diagnosis and evidence-gated stabilization attempt for context-sensitive cross-process idempotency failure (mock-only)  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

## 1. Objective and baseline

**Target failure:**  
`broker/tests/test_firewall_controller_j8_hardening.py::test_xproc_conflicting_idempotency_repeatable_no_false_success`

**Baseline evidence (preserved, prior stages):**
- Stage 1A.2 monitored full broker suite completed: **855 collected, 853 passed, 1 failed, 0 skipped, 0 errors, 1 warning, 262.93s (0:04:22), actual exit 1** (`post_j20_stage_1a2_broker_full_monitored.*`). Failure: `test_xproc_conflicting_idempotency_repeatable_no_false_success` with `assert any(r.get("error") == "FirewallControllerIdempotencyError" for r in errors)` (AssertionError). No double-success observed in captured evidence.
- Stage 1A.2 explicit J.8 hardening rerun: **11 passed, 1 warning, 10.80s, exit 0** (includes target test). Isolated pass not treated as proof of resolution.

**Scope of inspection (code/tests):**
- `broker/tests/test_firewall_controller_j8_hardening.py` (target test: 10 iterations, same temp DB/backend-state files per iteration, `ProcessPoolExecutor` with `spawn`, same `idempotency_key`/`policy_id`, conflicting payload via different `compiled_rule_digest`)
- `broker/tests/test_firewall_controller_cross_process_crash_recovery.py` helpers/worker: `_worker_install_conflict` (builds conflicting request, returns `{'ok': False, 'error': type(e).__name__, 'pid': ...}` on exception or `{'ok': True, 'status': r.get('status'), 'pid': ...}` on non-exception response), `_be_save`, `_make_file_backed_backend`, `_req`
- `broker/firewall_controller_service/controller_service.py` idempotency/conflict handling in `_call` (pre-check conflict detection, create-record path, uniqueness-collision handling/re-fetch classification, pending wait/replay decisions, `FirewallControllerIdempotencyError` on digest mismatch/pending/conflict cases)
- `broker/firewall_controller_service/ownership_store.py` (`controller_idempotency` PK `(idempotency_key, operation_type)`, `create_idempotency_record` wraps failures as `BrokerDBError`, transactional create/get/complete behavior)

## 2. Reproduction attempts (controlled, before any source modification)

No application/test source code modified in this task.

| Attempt | Command / method | Result | Notes |
|---|---|---|---|
| Harness using same worker/setup logic (separate process, repo on PYTHONPATH) | `.\venv\Scripts\python.exe C:\Users\bhavs\AppData\Local\Temp\opencode\stage1a3_repro_harness.py` (80 iterations, `spawn`, temp DB/state per iteration, prints BAD with subprocess results + idempotency/ownership DB rows if assertion conditions fail) | **DONE 0 bad out of 80, exit 0** | Could not capture failure; no BAD case emitted |
| Combined crash-recovery + J.8 hardening (same pytest session) | `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_cross_process_crash_recovery.py broker/tests/test_firewall_controller_j8_hardening.py -q` | **18 passed, 1 warning, 17.71s, exit 0** | Target test passed in combined context |
| Isolated target test (repeated) | Multiple `pytest broker/tests/test_firewall_controller_j8_hardening.py::test_xproc_conflicting_idempotency_repeatable_no_false_success -q` runs (including earlier 20-run and 30-run loop attempts in this session; loop summaries not fully capturable due to tool-timeout behavior, but no completed run observed as failure and no matching processes remained) | **No reproduced failure captured** | Inability to reproduce on demand in isolation |
| Full suite / representative preceding sequence | Stage 1A.2 monitored full `broker/tests -q` previously reproduced 1 failure in 855 tests (preserved). No additional full-suite run executed in this diagnosis task; full representative-prefix reproduction not completed | **Prior failure preserved; not reproduced in this task** | Context-sensitive as previously observed |

**Comparison (isolated vs broader context):** target passed in isolation/harness/combined crash-recovery+J.8 contexts in this task; failure previously manifested only in completed full-broker context (1/855). This is consistent with context-sensitive/non-deterministic behavior, but the exact triggering context was not reproduced here.

## 3. Root-cause analysis

### 3.1 Failure mechanism indicated by prior evidence
- **Observed failing condition (Stage 1A.2):** `len(errors) >= 1` satisfied in intent but `any(r.get("error") == "FirewallControllerIdempotencyError" for r in errors)` was false (AssertionError), while `len(oks) <= 1` was part of the same check sequence and no double-success was evidenced.
- **Invariant status:** required security invariant (**conflicting same-key operations must never both report success**) not shown violated.
- **Plausible mechanisms (code inspection):** (a) transient idempotency create/read races under contention where a proven uniqueness collision (`UNIQUE constraint failed` on `controller_idempotency`) could previously leak non-classified storage/fetch exceptions instead of `FirewallControllerIdempotencyError` (partially mitigated in Stage 1A.1 by bounded classification-read follow-up in `controller_service._call`); (b) other exception types escaping worker classification paths under specific timing/DB-state conditions; (c) worker/result interpretation edge cases (worker treats any non-exception controller response as `ok=True` regardless of response status, though idempotency conflicts are raised as exceptions in service path). None of these could be confirmed against an actual failing subprocess result/DB snapshot in this task because reproduction was not achieved.

### 3.2 Exact root cause
**Unproven / not established.** The failure could not be reproduced under controlled conditions in this task, and no actual failing subprocess outputs, error classifications, timing traces, or per-failure database state were captured beyond the preserved pytest assertion from Stage 1A.2. Therefore the precise failure mechanism remains unconfirmed.

## 4. Source changes

**None.** Per task rules, no speculative source change was made in the absence of a reproduced/established root cause. Existing APIs and behavior preserved.

## 5. Required verification (post-correction)

Not applicable (no justified correction implemented). No post-correction regression/full-suite reruns executed as part of a correction cycle in this task. Prior Stage 1A.2 evidence remains authoritative for completed full-suite state: **855 collected, 853 passed, 1 failed, 0 skipped, 0 errors, 1 warning, 262.93s, exit 1** (preserved).

## 6. Remaining limitations and unresolved risks

- Context-sensitive failure remains **intermittently observed historically but unreproduced on demand**; deterministic root cause not identified.
- Without a reproduced failing trace (worker return payloads, exception class/message, idempotency row status/digest/response, timing), narrowing to a defensible minimal fix risks speculative behavior change.
- Full-broker reliability for this specific cross-process conflicting-idempotency classification assertion is not proven deterministic across all execution contexts.
- Stage 1A.1 classification hardening for proven uniqueness-collision create races remains in place (separately evidenced), but its sufficiency for the unreproduced failure mode is unknown.

## 7. Final decision

**INCOMPLETE — failure could not be reproduced under controlled conditions in this task and exact root cause remains unproven; no speculative source change made.**

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

No security gate closed or status upgraded based solely on passing/non-reproducing runs. Do not start Stage 1B or Docker implementation.