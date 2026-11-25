# Post-J.20 Stage 1A.4 — Full-Suite Context and Failure-Trace Investigation (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Branch:** `main`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged)  
**Task:** investigation of historically observed cross-process idempotency classification failure (mock-only, diagnostic-only; no application behavior/persistence changes)  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

## 1. Historical failure evidence (preserved)

**Source:** Stage 1A.2 monitored full broker suite (`post_j20_stage_1a2_broker_full_monitored.stdout.txt`, `.stderr.txt`, `.meta.txt`, `.exit.txt`, `post_j20_stage_1a2_run_monitored.ps1`).

| Field | Value |
|---|---|
| Command | `.\venv\Scripts\python.exe -m pytest broker/tests -q` |
| Start / End | `2026-11-17T13:50:56.6811312+05:30` / `2026-11-17T13:55:22.2522412+05:30` |
| Duration | 265.571s meta (262.93s / 0:04:22 pytest) |
| Actual exit code | **1** |
| Results | **855 collected, 853 passed, 1 failed, 0 skipped, 0 errors, 1 warning** |
| Failure | `FAILED broker/tests/test_firewall_controller_j8_hardening.py::test_xproc_conflicting_idempotency_repeatable_no_false_success` |
| Assertion | `assert any(r.get("error") == "FirewallControllerIdempotencyError" for r in errors)` → `AssertionError` (at `broker\tests\test_firewall_controller_j8_hardening.py:153`) |
| Progress context | `-q` progress showed `F` in the ~59% segment (`......................................................F................. [ 59%]`); no per-test names/order in output |

**Prior context:** Stage 1A.3 could not reproduce in 80 harness iterations or combined crash-recovery/J.8 run; exact root cause remained unproven at that point.

## 2. Test ordering and preceding-sequence analysis

- **Preserved 1A.2 output:** pytest `-q` provides aggregate progress dots and final failure summary only; it does **not** record per-test identifiers in execution order. Therefore the **exact preceding test sequence cannot be established** from preserved captured evidence.
- **Current collection (indicative, not authoritative for 1A.2):** `pytest broker/tests --collect-only -q` (this environment) collected **854 tests** and placed `test_firewall_controller_j8_hardening.py::test_xproc_conflicting_idempotency_repeatable_no_false_success` immediately after `test_firewall_controller_j19_docker_runtime_authority.py::test_error_sanitization_no_socket_env_or_internal_leakage` and before other j8/j9 tests. This differs in total count from the 1A.2 run (855 collected) and is not proof of 1A.2 ordering.
- **Representative preceding-test context supported by preserved ordering evidence:** **none** (exact/defensible ordering not established). Controlled alternatives executed (combined j19+j8, crash-recovery+j8, diagnostic harness) as evidence-gathering contexts.

## 3. Shared state / isolation inspection

| Area | Findings (evidence from source inspection) |
|---|---|
| Target test (`j8_hardening`) | Per-iteration `tempfile.mkdtemp()`; fresh `db_path`/`be_path` per iteration; `_be_save` initializes backend state; `mp.get_context("spawn")`; `ProcessPoolExecutor(max_workers=2, mp_context=ctx)` used as context manager (closed/joined per iteration) |
| Worker (`_worker_install_conflict`, crash-recovery) | Spawned process builds fresh backend/service/store from provided paths; catches exceptions and returns `{'ok': False, 'error': type(e).__name__, 'pid': ...}` or `{'ok': True, 'status': ..., 'pid': ...}`; no shared mutable in-process state across iterations |
| Environment mutations | No `os.environ`/`setenv`/`monkeypatch`/autouse fixtures found in `test_firewall_controller_j8_hardening.py` or `test_firewall_controller_cross_process_crash_recovery.py` (grep inspection) |
| DB/temp paths | Isolated temp directories/paths per iteration; no reuse of target DB across iterations |
| Potential global factors (not directly evidenced) | Module-level imports/singletons, SQLite WAL/locking behavior under concurrent first-use on fresh DB, process-pool/spawn overhead under full-suite load |

## 4. Test-only diagnostic capture design

**Goal:** capture per-worker operation/result, exception class and sanitized classification, key identifiers, persisted idempotency/ownership state, completion order/timing without altering synchronization, transaction behavior, or application logic.

**Implementation (test-only, external to app/tests under test):** `C:\Users\bhavs\AppData\Local\Temp\opencode\stage1a4_diag_harness.py` (preserved artifact; imports repo via PYTHONPATH).
- Reuses existing test helpers for backend-state setup and request construction (`_be_save`, `_make_file_backed_backend`, `_req`) and mirrors worker flow.
- Defines `_diag_worker_install_conflict` that: executes same `FirewallControllerService(...).install_policy(req)` operation; on exception returns `{'ok':False,'error':type(e).__name__,'error_str':str(e)[:500],'pid','bad','dt','db':<snapshot>}`; on success returns status/result plus timing and snapshot. **No changes to app/service/store code paths, no added sleeps/retries, no synchronization hooks.**
- Read-only DB snapshot after operation completion in worker (`sqlite3` select of `controller_idempotency` key fields/status/digest/response_len and `controller_ownership` state/digest) for traceability.
- Driver runs same contention pattern (spawn, 2 workers, same key/conflicting digests, 10 runs per cycle) and emits `FAIL_TRACE` JSON on first assertion-condition failure.

**Limitations:** diagnostic harness is a controlled reproduction vehicle (not identical to pytest test object execution context/full-suite preceding state); worker-defined-in-script under spawn requires file-based module semantics (addressed by temp file). Snapshot is post-hoc/read-only and does not instrument in-transaction timing. Captured `error_str` is sanitized/truncated for local diagnosis.

**Secondary confirmation harness:** `C:\Users\bhavs\AppData\Local\Temp\opencode\stage1a4_realworker_repro.py` (uses real `_worker_install_conflict` to confirm failure shape against production test worker behavior).

## 5. Reproduction attempts and results

| Context | Command / method | Result |
|---|---|---|
| Diagnostic harness (controlled, isolated contention pattern) | `$env:PYTHONPATH='.'; .\venv\Scripts\python.exe C:\Users\bhavs\AppData\Local\Temp\opencode\stage1a4_diag_harness.py` (`DIAG_CYCLES` default 20, `DIAG_RUNS` 10) | **FAIL_TRACE captured (cycles=3, bad=1), exit 0** (harness reported reproduction) |
| Real-worker confirmation harness | `$env:PYTHONPATH='.'; .\venv\Scripts\python.exe C:\Users\bhavs\AppData\Local\Temp\opencode\stage1a4_realworker_repro.py` | **BAD captured (i=25), DONE_BAD, exit 0** |
| Combined j19 + j8 (controlled sequence, collection-adjacent context) | `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_j19_docker_runtime_authority.py broker/tests/test_firewall_controller_j8_hardening.py -q` | **39 passed, 1 warning, 13.90s, exit 0** |
| Combined crash-recovery + j8 (Stage 1A.3/1A.4 evidence) | `pytest broker/tests/test_firewall_controller_cross_process_crash_recovery.py broker/tests/test_firewall_controller_j8_hardening.py -q` | **18 passed, 1 warning, 17.71s, exit 0** |
| Full broker suite | Not rerun in this task (not required absent fix; completed 1A.2 evidence preserved) | n/a |

No blind repeated full-suite launches performed.

## 6. Reproduced failure traces (complete, preserved)

### 6.1 Diagnostic harness trace (rich)
```json
{
  "iteration": 2,
  "run": 7,
  "dt": 0.5250543000001926,
  "r1": {
    "ok": false,
    "error": "BrokerDBError",
    "error_str": "Schema init failed: database is locked",
    "pid": 5440,
    "bad": false,
    "dt": 0.08197180000024673,
    "db": {"db_err": "no such table: controller_idempotency"}
  },
  "r2": {
    "ok": true,
    "status": "ok",
    "result": {"status": "installed", "policy_id": "xpc2", "rule_handles": [], "verified_readback": true, "digest_verified": true},
    "pid": 1780,
    "bad": true,
    "dt": 0.31070120000003953,
    "db": {
      "idem": [{"idempotency_key": "kxpc2-j8", "operation_type": "install_policy", "request_digest": "cffd5920e31bac43bdfee70b8121969d709e7f33f208493c147c935030458be9", "status": "COMPLETED", "lifecycle_state": null, "ownership_record_id": "528bc4c9-e462-411d-9d31-8cf051cfa3cb", "response_len": 397, "completed_at": "2026-11-17 08:39:15"}],
      "own": [{"policy_id": "xpc2", "policy_version": 1, "installation_state": "INSTALLING", "canonical_policy_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]
    }
  },
  "db_path": "C:\\Users\\bhavs\\AppData\\Local\\Temp\\tmptly6kulk\\c.db"
}
```
**Interpretation:** r1 (non-conflicting payload, `bad=false`) failed during DB/schema initialization (`BrokerDBError: Schema init failed: database is locked`) before idempotency tables/state were available; r2 (conflicting payload, `bad=true`, digest `bbbb...`) completed successfully and persisted the winning COMPLETED idempotency/ownership records. No double-success.

### 6.2 Real-worker trace (test-equivalent worker)
```json
{
  "i": 25,
  "r1": {"ok": true, "status": "ok", "pid": 19392},
  "r2": {"ok": false, "error": "BrokerDBError", "pid": 21084},
  "idem": [{"idempotency_key": "kxpc2-j8", "operation_type": "install_policy", "request_digest": "7d4f9696a685a4ded179234b72091cfdaf906f996f6e8f9a3ec487820d57f60d", "status": "COMPLETED"}],
  "own": [{"policy_id": "xpc2", "policy_version": 1, "installation_state": "INSTALLING", "canonical_policy_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],
  "db_path": "C:\\Users\\bhavs\\AppData\\Local\\Temp\\tmpfipxnmoa\\c.db"
}
```
**Interpretation:** symmetric race outcome (winner r1, digest `aaaa...`; loser r2 classified as `BrokerDBError` rather than `FirewallControllerIdempotencyError`). Matches test worker return contract and the historical assertion-failure signature (`errors` present but none `FirewallControllerIdempotencyError`) while preserving `len(oks) <= 1`.

## 7. Root-cause determination

**Established (by reproduced traces):** in cross-process conflicting same-key operations on a **fresh per-iteration SQLite database**, concurrent spawned workers can race during initial store/schema initialization (and/or first DB access). The losing worker may fail with a storage/DB initialization error (e.g. `BrokerDBError: Schema init failed: database is locked`, schema unavailable) **before** it can read/classify the idempotency record created by the winning worker. The winning worker can complete normally, persisting a COMPLETED idempotency record and ownership state.

**Consequences:**
- Test assertion `any(r.get("error") == "FirewallControllerIdempotencyError" for r in errors)` fails because the losing side reports `BrokerDBError`, not an idempotency-conflict classification.
- Required security invariant **holds**: conflicting same-key operations do **not** both report success (`len(oks) <= 1` satisfied in traces; only one COMPLETED record persisted).
- This is a **pre-idempotency store-availability/schema-init contention** in the test/setup path on a fresh DB, not an observed case of duplicate successful application or incorrect conflict classification once the idempotency store is readable/initialized.

**Scope/caveat:** the exact historical 1A.2 full-suite preceding context and the specific losing-worker exception in that run were not captured (ordering/trace unavailable), but the reproduced mechanism is consistent with the preserved symptom and observed intermittently in controlled contention. No claim made that every historical occurrence had the identical exception message.

## 8. Corrections

**None applied.** Per strict rules: no application behavior or persistence semantics modified, no assertions weakened/skipped/rewritten, no broad retries/arbitrary timeouts/speculative fixes. Reproduction achieved for diagnosis; any remediation (test-harness synchronization/setup or store-init resilience) would require separately justified changes outside this investigation-only scope.

## 9. Limitations and unresolved risks

- Exact 1A.2 preceding test sequence and per-test order not recoverable from preserved `-q` evidence.
- Historical 1A.2 failing worker payloads/DB snapshot not captured; reproduced traces establish a consistent mechanism but cannot prove identical internal exception details for that specific run.
- Full broker suite not rerun in this task; combined/adjacent controlled contexts passed (39 passed, 18 passed) but do not prove absence in all full-suite contexts.
- Under no-change constraints, the target test remains susceptible to intermittent failure in fresh-DB concurrent-init contention scenarios despite no-double-success invariant holding.

## 10. Final decision

**CONDITIONAL — investigation complete; reproducible failure trace obtained and root cause established for the observed classification-assertion failure mode (pre-idempotency fresh-DB schema/init contention; no double-success). No correction applied under strict no-modification rules; issue not claimed fixed.**

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

No gate status updated (no new evidence satisfying gate acceptance criteria). Do not start Stage 1B.