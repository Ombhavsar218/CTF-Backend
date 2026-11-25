# Post-J.20 Stage 1A.5 — Fresh-Database Initialization Concurrency Remediation (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Branch:** `main`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged)  
**Stage:** Post-J.20 Stage 1A.5 (mock-only, evidence-supported correction)  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

## 1. Stage 1A.4 root-cause evidence (baseline)

Reproduced and documented in `docs/POST_J20_STAGE_1A_4_FAILURE_TRACE_INVESTIGATION.md` (preserved). Key evidence:
- Two spawned workers concurrently accessed a **fresh per-iteration SQLite database** for conflicting same-key requests.
- Concurrent first-time schema/store initialization raced: losing worker failed with storage/DB init error (e.g. `BrokerDBError: Schema init failed: database is locked`, schema unavailable / `no such table: controller_idempotency`) **before** it could read/classify the winner’s idempotency record.
- Winner created one COMPLETED idempotency record and ownership state; **no double-success** observed.
- Test assertion failed because loser returned `BrokerDBError` instead of `FirewallControllerIdempotencyError` (classification unavailable pre-init), not because of duplicate application or incorrect idempotency classification once the store was readable.

## 2. Initialization-path analysis (pre-modification)

| Component | Path / behavior | Findings |
|---|---|---|
| `broker.app.db.BrokerDB` | `__init__` → `_ensure_db_dir()` → `_init_schema()`; `_init_schema()` opens conn (`sqlite3.connect(..., timeout=5.0)`), runs `PRAGMA journal_mode=WAL`, creates base tables/indexes, commits/`_secure_files()`, closes; on exception rolls back and raises `BrokerDBError("Schema init failed: {e}")` | Base schema DDL executed without cross-process serialization; no explicit `busy_timeout` pragma; init idempotent in SQL form (`IF NOT EXISTS`) but concurrent DDL/WAL setup can contend/lock across spawned processes |
| `broker.firewall_controller_service.ownership_store.ControllerOwnershipStore` | `__init__` → `self.db = BrokerDB(db_path)` → `_init_schema()`; store `_init_schema()` opens conn, sets WAL/foreign_keys, creates controller tables/indexes/triggers, commits, closes | Second init phase (controller schema) also unsynchronized across processes; previously propagated raw exceptions on DDL failure (no BrokerDBError wrapping) |
| Callers / concurrency | Workers/services construct fresh stores per process against same/new DB paths; test contention occurs on fresh DB first-use | Init contention is distinct from normal transactional operations; uniqueness/atomicity of idempotency records enforced by PK/transactions once schema exists |

**Transaction/boundary/pragmas:** connection-level autocommit/implicit transaction behavior around DDL; `journal_mode=WAL` set during init; `foreign_keys` enabled in store init/`_get_conn_fk`; SQLite connect timeout 5.0s, no `busy_timeout` set. DDL contention can manifest as `database is locked` / schema unavailable despite idempotent statements.

**Distinction from genuine failures:** init-lock/DDL/IO/connect/filesystem failures are storage/initialization failures (must remain fail-closed `BrokerDBError`/storage error) and must **not** be translated into idempotency conflicts or fabricated success. Idempotency conflict classification requires readable/consistent idempotency state and matching key semantics.

## 3. Correction design and rationale

**Proposed/implemented correction (smallest evidence-supported):** serialize schema initialization across processes using a per-database init lock file, while preserving idempotent DDL.

- **`broker/app/db.py` (`BrokerDB`):**
  - Added `_init_guard()` context manager using `<db_path>.initlock` (same DB path namespace).
  - Cross-process exclusive lock: Windows `msvcrt.locking(fd, LK_LOCK/LK_UNLCK, 1)`; POSIX `fcntl.flock(LOCK_EX/LOCK_UN)` (blocking acquisition; no polling sleep).
  - Lock acquisition/open/filesystem failures raised as `BrokerDBError("DB init lock unavailable: ..." / "DB init lock failed: ...")` (fail closed; storage/init error).
  - Wrapped existing `_init_schema()` body in `with self._init_guard(): ...` (same DDL/commit/rollback/error semantics preserved: `BrokerDBError("Schema init failed: {e}")` on genuine init failures).
- **`broker/firewall_controller_service/ownership_store.py` (`ControllerOwnershipStore`):**
  - Wrapped controller `_init_schema()` body in `with self.db._init_guard(): ...` to serialize controller schema init across processes against the same DB.
  - Preserved DDL/schema/API behavior; added fail-closed wrapping to raise `BrokerDBError("Schema init failed: {e}")` on genuine controller-init failures (consistent storage-error semantics) while re-raising existing `BrokerDBError`.

**Why this addresses the race:** base and controller schema initialization become mutually/process-serialized per DB via the same lock file. Concurrent spawned workers no longer execute first-time DDL concurrently; later workers observe initialized schema (idempotent `IF NOT EXISTS`) and can proceed to idempotency read/create/classification paths normally.

**Preserved semantics:** schema definitions unchanged; APIs unchanged; idempotency PK/uniqueness/transactional atomicity unchanged; no fabricated success/completion; no conversion of arbitrary/general `BrokerDBError` or init/storage failures into idempotency conflicts; genuine DB/init/storage failures remain storage errors (fail closed). No broad retries, no arbitrary global timeouts, no unnecessary sleeps added.

## 4. Exact files changed

| File | Change |
|---|---|
| `broker/app/db.py` | Added `sys`/`contextmanager` imports; added `BrokerDB._init_guard()` cross-process init lock; guarded `BrokerDB._init_schema()` with init lock (preserving existing schema/commit/rollback/error behavior) |
| `broker/firewall_controller_service/ownership_store.py` | Guarded `ControllerOwnershipStore._init_schema()` with `self.db._init_guard()`; preserved DDL and added fail-closed `BrokerDBError` wrapping for genuine controller schema-init failures |

## 5. Regression tests and results

### 5.1 Reproduction and targeted remediation verification

| Check | Command / method | Result | Exit |
|---|---|---|---:|
| Compile (modified sources) | `.\venv\Scripts\python.exe -m py_compile broker/app/db.py broker/firewall_controller_service/ownership_store.py` | success | 0 |
| Stage 1A.4 real-worker fresh-DB concurrent init/conflict scenario (post-fix) | `.\venv\Scripts\python.exe C:\Users\bhavs\AppData\Local\Temp\opencode\stage1a4_realworker_repro.py` (80 iterations, real `_worker_install_conflict`, spawn, fresh DB/state per iteration) | **DONE_OK 80** (no `BrokerDBError`-instead-of-conflict case) | 0 |
| Diagnostic harness (rich trace capture, post-fix) | `.\venv\Scripts\python.exe C:\Users\bhavs\AppData\Local\Temp\opencode\stage1a4_diag_harness.py` (`DIAG_CYCLES=5`, `DIAG_RUNS=5`) | **DONE cycles=5 bad=0** | 0 |
| Multiple spawned workers init/access fresh DB concurrently | ad-hoc `stage1a5_targeted_checks.py` (6 workers, 12 init/access tasks, spawn) | **ALL_OK True 12** | 0 |
| Conflicting same-key requests (concurrent fresh DB) | same script, 20 rounds via `_worker_install_conflict` | **CONFLICT_OK_ROUNDS 20** (exactly one success + correctly classified `FirewallControllerIdempotencyError` per round) | 0 |
| Genuine init/storage failure remains storage error | `BrokerDB(<directory-path>)` and `ControllerOwnershipStore(db_path=<directory-path>)` | **BROKERDB_GENUINE_STORAGE_ERROR BrokerDBError**, **STORE_GENUINE_STORAGE_ERROR BrokerDBError** | 0 |
| Idempotency uniqueness/persistence/replay (store-level) | duplicate create rejected, persisted digest readable, completion persisted | **UNIQ_OK BrokerDBError, PERSIST_OK True, COMPLETE_OK True** | 0 |

(Ad-hoc scripts preserved: `C:\Users\bhavs\AppData\Local\Temp\opencode\stage1a4_realworker_repro.py`, `stage1a4_diag_harness.py`, `stage1a5_targeted_checks.py`.)

### 5.2 Required test suites

| Suite / command | Result | Duration | Exit |
|---|---|---:|---:|
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_j8_hardening.py -q` | **11 passed, 1 warning** | 27.30s | 0 |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_cross_process_crash_recovery.py -q` | **7 passed, 1 warning** | 11.14s | 0 |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_contract.py -q` | **10 passed, 1 warning** | 0.14s | 0 |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_post_j20_stage_1a1_import_order.py -q` | **5 passed, 1 warning** | 2.93s | 0 |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_j19_docker_runtime_authority.py -q` | **28 passed, 1 warning** | 9.43s | 0 |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_post_j20_stage_1a_canonical_authority.py -q` | **12 passed, 1 warning** | 4.02s | 0 |

Warnings observed (pre-existing environment): `PytestDeprecationWarning` (`asyncio_default_fixture_loop_scope` unset), `PydanticDeprecatedSince20`.

### 5.3 Full broker suite (monitored, persistent output, actual exit code)

- **Command:** `.\venv\Scripts\python.exe -m pytest broker/tests -q`
- **Start:** `2026-11-17T14:21:55.6287332+05:30`  
- **End:** `2026-11-17T14:27:26.3394977+05:30`  
- **Duration:** 330.711s meta (322.62s / 0:05:22 pytest)
- **Actual exit code:** **0** (`post_j20_stage_1a5_broker_full.exit.txt`, `.meta.txt`)
- **Raw preserved evidence:** `post_j20_stage_1a5_broker_full.stdout.txt`, `post_j20_stage_1a5_broker_full.stderr.txt`, `post_j20_stage_1a5_broker_full.meta.txt`, `post_j20_stage_1a5_broker_full.exit.txt`, `post_j20_stage_1a5_run_broker_full.ps1`

| Collected | Passed | Failed | Skipped | Errors | Warnings | Exit |
|---:|---:|---:|---:|---:|---:|---:|
| 854 | 854 | 0 | 0 | 0 | 1 | 0 |

The previously intermittent target test `test_xproc_conflicting_idempotency_repeatable_no_false_success` passed within the completed full suite.

## 6. Remaining limitations

- Correctness evidenced in mock/local SQLite paths and captured environments; not proof of production/host/kernel/transport/runtime behavior or live-firewall readiness.
- Init serialization uses a per-DB lock file (`.initlock`) with platform file-lock primitives; behavior on atypical filesystems/locking semantics outside tested environments is not exhaustively proven (fail-closed on lock acquisition errors by design).
- `ControllerOwnershipStore._init_schema` now wraps genuine init exceptions as `BrokerDBError("Schema init failed: ...")` (consistent fail-closed storage error) rather than propagating raw sqlite exceptions as before; this is an intentional error-normalization aligned with DB init behavior.
- No security gate closure is implied by this remediation/test evidence.

## 7. Final decision

**VERIFIED (scoped) — reproduced fresh-DB concurrent initialization race remediated with evidence-supported init serialization; targeted reproductions pass (no double-success, correct conflict classification), required suites pass, and full broker suite completed successfully (854 passed, 0 failed, exit 0).**

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

No gate closed automatically. Do not start Stage 1B or Docker implementation.
