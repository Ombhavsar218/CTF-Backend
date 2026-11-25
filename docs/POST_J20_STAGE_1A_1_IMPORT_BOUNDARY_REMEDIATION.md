# Post-J.20 Stage 1A.1 — Import-Boundary Remediation (Mock-Only, Stabilization)

**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Branch:** `main`  
**HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (unchanged)  
**Task scope:** narrowly scoped mock-only stabilization (import boundary + cross-process test reliability evidence); **no Stage 1B started**  
**Date:** 2026-11-17

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**

## 1. Baseline (inspected, preserved)

| Item | State |
|---|---|
| Git | `main` @ `b365584...` (unchanged); **26 modified tracked files** preserved (unchanged set as previously recorded); **376 untracked entries** at baseline inspection (plus Stage 1A.1 artifacts/captures added during this task, preserved) |
| Inspected source/tests | `broker/app/firewall_controller.py`, `broker/firewall_controller_service/mock_backend.py`, `broker/firewall_controller_service/__init__.py`, `broker/firewall_controller_service/app.py`, `broker/firewall_controller_service/controller_service.py`, `broker/firewall_controller_service/ownership_store.py`, `broker/tests/test_firewall_controller_contract.py`, `broker/tests/test_firewall_controller_j8_hardening.py`, `broker/tests/test_firewall_controller_cross_process_crash_recovery.py` (worker/helpers) |
| Existing logs/evidence preserved | prior Stage 1A captures/docs preserved; Stage 1A.1 incomplete full-suite captures preserved (`post_j20_stage_1a1_broker_full*`, `post_j20_stage_1a1_broker_full_rerun*`) |

No git reset/clean/checkout/revert/staging/commit performed. No Docker/daemon/socket/container/UDS/SO_PEERCRED/privileged-helper/capability/nftables/iptables/host-firewall/host-permission/service/Linux/cloud/production operations performed.

## 2. Circular import — root cause

**Reproduced baseline (isolated collection):**
- Command: `.\venv\Scripts\python.exe -m pytest broker/tests/test_firewall_controller_contract.py -q`
- Result: **1 error during collection, 1 warning, 0.37s, exit 2**
- Error: `ImportError: cannot import name 'MockFirewallController' from partially initialized module 'broker.app.firewall_controller' (most likely due to a circular import)`

**Exact import dependency chain (reproduced):**
1. `broker/tests/test_firewall_controller_contract.py` imports `MockFirewallController` from `broker.app.firewall_controller`
2. `broker/app/firewall_controller.py` (module level) imported `RuleSchemaError, validate_install_policy_rules` from `broker.firewall_controller_service.rule_schema_v1`
3. Importing `broker.firewall_controller_service.rule_schema_v1`/service package triggered `broker/firewall_controller_service/__init__.py` → `app.py` → `controller_service.py` → `mock_backend.py`
4. `broker/firewall_controller_service/mock_backend.py` imports `MockFirewallController` from `broker.app.firewall_controller`
5. `broker.app.firewall_controller` was partially initialized at step 4 → `ImportError`

This is an import-order-sensitive structural cycle: it manifests when `broker.app.firewall_controller` is imported first in contexts that pull service package initialization (including isolated collection of the contract test), but could be avoided in other full-suite import orders.

## 3. Minimal compatibility-preserving correction

**Source file modified:** `broker/app/firewall_controller.py`

**Change (exact, minimal):**
- Removed module-level import: `from broker.firewall_controller_service.rule_schema_v1 import RuleSchemaError, validate_install_policy_rules`
- Added lazy import inside `MockFirewallController.install_policy` at the point where canonical schema-v1 rule validation/normalization is required (`if isinstance(req, dict) and req.get('rules') is not None:`):  
  `from broker.firewall_controller_service.rule_schema_v1 import RuleSchemaError, validate_install_policy_rules`
- Preserved existing validation logic, control flow, and exception conversion: `except RuleSchemaError as e: raise FirewallControllerRequestError(getattr(e, 'message', str(e)))`

**Compatibility impact:**
- **Public import paths preserved:** `MockFirewallController` remains importable from `broker.app.firewall_controller`; service package exports unchanged.
- **Runtime behavior preserved:** rule validation/normalization executes when `rules` are present, same module/types used, same request mutation/error conditions.
- **Exception types/semantics preserved:** `RuleSchemaError` handled identically and converted to `FirewallControllerRequestError` as before; no exception type or established message-contract changes intended.
- **No broad package restructuring:** no changes to package `__init__` side effects, `mock_backend` API, or unrelated modules.
- **Test collection order not changed:** fix addresses the dependency cycle, not test ordering.

**Import-order regression coverage added (fresh Python processes):** `broker/tests/test_post_j20_stage_1a1_import_order.py`
- app-controller-first import/use
- isolated collection/run of `broker/tests/test_firewall_controller_contract.py` via subprocess
- service-before-app import
- mock-backend/app-controller import order
- app-controller → mock-backend → service import order

## 4. Cross-process idempotency reliability — investigation and correction

**Observed issue (evidence):** `broker/tests/test_firewall_controller_j8_hardening.py::test_xproc_conflicting_idempotency_repeatable_no_false_success` failed in this session’s full J.8 suite run with `assert any(r.get("error") == "FirewallControllerIdempotencyError" for r in errors)` (1 failed, 10 passed, 1 warning, 6.72s, exit 1) while later isolated/corrective runs passed. Prior Stage 1A full-broker context also recorded a non-deterministic failure of the same test. Required security invariant remains: **conflicting operations using the same idempotency key must never both report success**.

**Investigation (code-path, evidence-based):**
- Shared worker (`broker/tests/test_firewall_controller_cross_process_crash_recovery._worker_install_conflict`) submits two spawned processes with same `idempotency_key` and different payload (`compiled_rule_digest` differs) and reports `ok=False, error=<exception class name>` on exception, else `ok=True` with response status.
- `FirewallControllerService._call` idempotency handling: pre-check conflict detection on existing record (`_idempotency_replay_decision` raises `FirewallControllerIdempotencyError` on digest mismatch), create-record path, and on `create_idempotency_record` failure a bounded re-fetch/classification loop (transient lock contention aware). If record cannot be classified after retries, code previously raised `last_fetch_exc`/`create_exc` (e.g. `BrokerDBError`).
- `ControllerOwnershipStore.create_idempotency_record` wraps failures as `BrokerDBError('Failed to create idempotency record: ...')`; a concurrent insert on primary key `(idempotency_key, operation_type)` manifests as a uniqueness-constraint failure wrapped in `BrokerDBError`. In that case the record **provably exists**, but transient read/lock contention could prevent successful classification within the bounded window, risking leakage of a storage/create exception instead of deterministic conflict/pending classification.

**Root-cause assessment:** not fully proven to a single deterministic failing trace in this environment (non-reproducible on demand outside prior suite contexts), but code inspection identifies a real classification-reliability gap: uniqueness-collision create failures (`UNIQUE constraint failed ... controller_idempotency`) did not guarantee continued classification reads after transient read failures/deadline, allowing potential misclassification as `BrokerDBError`/fetch exception rather than `FirewallControllerIdempotencyError` in contended cross-process races. No evidence of double-success observed.

**Minimal fix implemented (real defect hardening, no invariant weakening):**
- **Source file modified:** `broker/firewall_controller_service/controller_service.py` (idempotency create-exception handling in `_call`)
- Detect uniqueness collision on create: `unique_collision = ('UNIQUE constraint failed' in create_msg and 'controller_idempotency' in create_msg)` where `create_msg = str(create_exc)`
- Preserve existing bounded re-fetch/classification loop; additionally, when `unique_collision` is true and record remains unclassified, perform a bounded follow-up classification-read window (`+1.0s`) to avoid leaking storage/create errors in place of deterministic conflict/pending classification (record existence is proven by PK uniqueness failure). No arbitrary global retry inflation; targeted to proven-collision case.
- No changes to security assertions, no weakening of conflict semantics, no “both success” tolerance.

**Test-only synchronization changes:** none made. Shared worker/tests not modified.

## 5. Exact source files modified (Stage 1A.1)

| File | Purpose |
|---|---|
| `broker/app/firewall_controller.py` | Lazy `rule_schema_v1` import in `install_policy` to break import-order-sensitive cycle; preserves public path/runtime/exception semantics |
| `broker/firewall_controller_service/controller_service.py` | Deterministic idempotency classification hardening on proven uniqueness-collision create failures |

## 6. Tests added

| File | Purpose |
|---|---|
| `broker/tests/test_post_j20_stage_1a1_import_order.py` | Fresh-process import-order coverage (including previously failing isolated contract collection context) |

## 7. Limitations

- Full `broker/tests -q` completion evidence is **unavailable** in this session: two rerun attempts started but terminated/stalled without final pytest summary/exit capture (see reliability evidence doc). Targeted regressions passed as recorded.
- Cross-process conflicting-idempotency failure was observed once in-session (J.8 suite run) and could not be deterministically reproduced afterward; controller-side classification hardening applied based on identified real gap, but deterministic full-suite proof is unavailable without completed full-suite run.
- Focused J.15/J.16/J.18 and Stage 1A regressions executed as recorded; this does not constitute universal gate closure.

## 8. Final decision

**INCOMPLETE — required full broker-suite completion evidence remains unavailable (two incomplete/non-finalized rerun attempts captured); targeted stabilization/regression evidence collected as documented.**

**Mandatory status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13, T-27:** **OPEN — ACCEPTANCE REQUIRED**
