# Post-J.20 Stage 1A.1 — Test Reliability Evidence (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Branch:** `main`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged)  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

All runs executed in `ctf-platform-be` using `.\venv\Scripts\python.exe` unless noted. Environment warnings observed (pre-existing): `PytestDeprecationWarning: asyncio_default_fixture_loop_scope unset`, `PydanticDeprecatedSince20`.

## 1. Baseline reproductions (preserved/recorded)

| Check | Command | Result | Duration | Exit |
|---|---|---|---:|---:|
| Isolated contract collection (baseline, before fix) | `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_contract.py -q` | **1 error during collection, 1 warning** — `ImportError: cannot import name 'MockFirewallController' from partially initialized module 'broker.app.firewall_controller'` (circular import chain via `firewall_controller -> firewall_controller_service.rule_schema_v1 -> service package -> mock_backend -> firewall_controller`) | 0.37s | 2 |
| J.8 conflicting repeatability (isolation, baseline observation in-session) | `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_j8_hardening.py -k "xproc_conflicting_idempotency_repeatable_no_false_success" -q` | **1 passed, 10 deselected, 1 warning** | 5.52s | 0 |

## 2. Initial failure preserved (post-fix targeted suite context)

| Check | Command | Result | Duration | Exit |
|---|---|---|---:|---:|
| Full J.8 hardening suite (initial run in this stabilization session) | `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_j8_hardening.py -q` | **1 failed, 10 passed, 1 warning**; `FAILED ...::test_xproc_conflicting_idempotency_repeatable_no_false_success` — `assert any(r.get("error") == "FirewallControllerIdempotencyError" for r in errors)` (AssertionError) | 6.72s | 1 |

**Corrective/diagnostic reruns for same conflicting test:**
- Isolated rerun after above failure: **1 passed, 1 warning, 5.64s, exit 0**
- Repeated isolated runs (5): `run1:0; run2:0; run3:0; run4:0; run5:0` (each via `pytest ...::test_xproc_conflicting_idempotency_repeatable_no_false_success -q`, captured as exit codes)
- Non-deterministic behavior observed across contexts; no double-success observed. A single passing isolated test is **not** presented as proof of deterministic full-suite reliability.

## 3. Required regression verification (executed)

### 3.1 Compilation
| Command | Result | Exit |
|---|---|---|
| `.\venv\Scripts\python.exe -m py_compile broker/app/firewall_controller.py broker/firewall_controller_service/controller_service.py broker/tests/test_post_j20_stage_1a1_import_order.py` | success | 0 |

### 3.2 Import boundary / contract
| Command | Result | Duration | Exit |
|---|---|---:|---:|
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_post_j20_stage_1a1_import_order.py -q` (includes fresh-process import-order checks and isolated `test_firewall_controller_contract.py` collection/run) | **5 passed, 1 warning** | 2.37s | 0 |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_contract.py -q` (post-fix) | **10 passed, 1 warning** | 0.13s | 0 |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_contract.py broker/tests/test_broker_docker.py -q` | **21 passed, 1 warning** | 2.31s | 0 |

### 3.3 Cross-process / J.8
| Command | Result | Duration | Exit |
|---|---|---:|---:|
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_j8_hardening.py -q` | **Initial:** 1 failed (`test_xproc_conflicting_idempotency_repeatable_no_false_success`), 10 passed, 1 warning; **corrective rerun (same suite) not separately captured as full suite rerun**; conflicting test isolated rerun passed (see §2) | 6.72s (initial) | 1 (initial) |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_cross_process_crash_recovery.py -q` | **7 passed, 1 warning** | 5.54s | 0 |
| Conflicting-key repeatability (5 isolated runs) | **5/5 passed** (exit 0 each) | n/a (individual) | 0,0,0,0,0 |

### 3.4 Stage 1A / canonical / authorization regressions
| Command | Result | Duration | Exit |
|---|---|---:|---:|
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_post_j20_stage_1a_canonical_authority.py -q` | **12 passed, 1 warning** | 1.82s | 0 |
| `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_j15_canonical_authority.py broker/tests/test_firewall_controller_j16_authorization_identity.py broker/tests/test_firewall_controller_j18_reconciliation_contract.py -q` | **72 passed, 1 warning** | 29.92s | 0 |

### 3.5 Manager and Django checks
| Command | Result | Duration | Exit |
|---|---|---:|---:|
| `.\venv\Scripts\python.exe -m pytest manager/tests -q` | **46 passed, 1 warning** | 6.84s | 0 |
| `.\venv\Scripts\python.exe manage.py check` | `System check identified no issues (0 silenced).` | n/a | 0 |

## 4. Full broker suite (required) — incomplete/unavailable completion evidence

**Attempt 1 (incomplete, preserved):**
- Command: `.\venv\Scripts\python.exe -m pytest broker/tests -q` (stdout/stderr captured via `Tee-Object` to `post_j20_stage_1a1_broker_full.stdout.txt`; meta `post_j20_stage_1a1_broker_full.meta.txt`)
- Start: `2026-11-17 13:35:26` (meta)
- Observed progress: reached ~50% in captured stdout (no final summary); file stopped growing; no `END`/`EXIT` written to meta; no corresponding `pytest broker/tests` process observed at later inspection
- Outcome: **terminated/stalled without pytest summary — NOT a completed test result**

**Attempt 2 / rerun (incomplete, preserved):**
- Command: `.\venv\Scripts\python.exe -m pytest broker/tests -q` (captured to `post_j20_stage_1a1_broker_full_rerun.stdout.txt`; meta `post_j20_stage_1a1_broker_full_rerun.meta.txt`)
- Start: `2026-11-17 13:39:49` (meta)
- Observed progress: reached ~50% in captured stdout (no final summary); file stopped growing; no `END`/`EXIT` written to meta; no corresponding `pytest broker/tests` process observed at later inspection
- Outcome: **terminated/stalled without pytest summary — NOT a completed test result**

**Required evidence unavailable:** collected/passed/failed/skipped/errors/warnings/duration/exit for a completed full `broker/tests -q` run in this stabilization session.

## 5. Summary of outcomes

- **Import cycle (isolated contract collection):** reproduced at baseline (exit 2), resolved post-fix; isolated and combined contract/broker-docker tests pass; fresh-process import-order tests pass.
- **Cross-process conflicting idempotency:** required invariant (no double success) not violated in observed runs; one in-session J.8 suite failure of classification/assertion recorded (initial, preserved) with subsequent isolated/repeated passes and passing crash-recovery suite; minimal controller classification hardening applied for proven uniqueness-collision create races. Deterministic full-suite reliability **not established** by a completed full broker run.
- **Targeted regressions:** Stage 1A adversarial, J.15/J.16/J.18 selected suites, J.8 crash recovery, manager suite, `manage.py check`, and relevant compilation passed as recorded.
- **Full broker suite:** **incomplete/unavailable** (two non-finalized attempts).

## 6. Final decision

**INCOMPLETE — full broker-suite completion evidence remains unavailable despite two rerun attempts; other required targeted verifications executed with results recorded above (including preserved initial J.8 failure and corrective reruns).**

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**
