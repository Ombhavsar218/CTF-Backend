# Post-J.20 Stage 1B.14 — Persistence Classification and Reconciliation Implementation

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.**

Repository: `E:\Flag-hunt\ctf-platform-be` | HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`  
Milestone: Stage 1B.14 (2026-11-18), mock-only scoped implementation. No Docker/socket/UDS/`SO_PEERCRED`/privileged-helper/capability/nftables/iptables/host-firewall/cloud/live-backend/Stage 1C operation was performed.

## 1. Scope

This stage addressed only the Stage 1B.12 residuals still applicable after Stage 1B.13:

- persistence-error classification and bounded outward errors;
- nested trusted-read failures during reconciliation;
- reconciliation status/audit/evidence guard coverage and compatibility fallbacks;
- `VERIFYING` lifecycle journaling and status/audit atomicity.

No parallel validation framework, duplicate authority source, new state machine, broad transaction redesign, rule-schema conversion, or public exception-class/code/status redesign was introduced.

## 2. Phase 1 finding-by-finding inventory

Line references marked *pre* are the current source before this stage's corrections; *post* references are the final source. Stage 1B.12 line numbers are cited from `docs/POST_J20_STAGE_1B_12_RESIDUAL_GAP_INVENTORY.md:29-40`.

| ID | Finding and references | Existing behavior / reproducible scenario | Impact | Resolved by 1B.13? | Stage 1B.14 disposition |
|---|---|---|---|---|---|
| F-14-01 | SR-07A broad create-race catch, *pre* `controller_service.py:1003-1011` (1B.12 `:968-1017`) | Any `create_idempotency_record` failure is re-fetched; if a same-key record is found, the validated replay decision runs. Comment claimed generic DB failures are never treated as duplicates. Fault: generic DB error plus a concurrent same-key winner. | No evidenced false-conflict promotion; comment/behavior mismatch could mislead review. | No | Comment corrected at *post* `:1014-1019`. Code not narrowed: gating only typed conflicts would change availability/error class under SQLite lock contention; authoritative replay still validates any found record. Explicitly unresolved code narrowing with justification. |
| F-14-02 | SR-07B canonical read classification, *pre* `controller_service.py:474-494,508-511` (1B.12 `:441-461`) | `get_canonical_policy_body()` caught only `BrokerDBError`; other faults escaped. `_sanitize_canonical_policy_error()` classified all unknown faults as `FirewallControllerRequestError('Invalid canonical policy record')`. Fault: `OSError(SENTINEL)` or service-level `FirewallControllerPersistenceError(SENTINEL)` from nested read. | Misclassified storage/internal faults as caller validation; inconsistent with Stage 1B.13 outer classification. | No | *Post* `:492-498,512-517`: all read faults go through sanitizer; `is_persistence_exception()` preserves persistence class, unknown faults map to existing bounded `FirewallControllerBackendError`, canonical ownership/integrity categories unchanged. |
| F-14-03 | SR-08 nested trusted-read failure in reconciliation, *pre* `controller_service.py:1782-1821` (1B.12 `:1663-1699`) | Nested `read_trusted_canonical_policy_body()` failure is inspected with `is_persistence_exception()`; persistence faults become `PERSISTENCE_FAILURE`; corruption remains `invalid_canonical_policy_body`. Fault: inject `BrokerDBError` inside nested read. | Before 1B.13, storage faults could be labeled invalid canonical body; safety remained fail-closed. | **Yes, already resolved in source** | No source change. Deterministic nested-read fault test added; *post* `:1798-1834` verified. |
| F-14-04 | SR-09A compatibility fallbacks, *pre* `controller_service.py:1660-1666` (1B.12 `:1541-1547`) | A store without `reconciliation_version_guard` performed an unguarded status write; missing `allowed_states` wrote under a stale caller-supplied version. Fault: legacy/test store or omitted allowed state. | Potential bypass of fresh-read, identity, state and CAS fencing if production wiring changed. | No | *Post* `:1682-1684` returns conflict `False` with no write/audit. No production caller omitted `allowed_states`; repository-wide test search found only guarded direct calls. |
| F-14-05 | SR-09B dead `require_evidence` parameter, *pre* `controller_service.py:1647-1648,1680-1685` | Private helper accepted `require_evidence` but no caller supplied it; evidence branches were unreachable and could imply false assurance. | Governance/control clarity gap. | No | Parameter and dead branches removed at *post* `:1666-1667`. Existing `_find_valid_verification_evidence` / `_has_revocation_evidence` promotion gates elsewhere were untouched. |
| F-14-06 | SR-09C failed-branch guard result discarded, *pre* `controller_service.py:1945-1948,1975-1977` (1B.12 `:1933-1950,2001-2003`) | `needs_verification` and `failed` branches reported `reconciled` even when the status CAS returned `False`. Fault: advance lifecycle version between guard read and status write. | Misleading success despite stale/fenced decision; weaker observability. | No | *Post* `:1958-1966,1993-2000` captures `status_written` and reports `uncertain/reconciliation_state_changed`; no success appended. |
| F-14-07 | SR-09D status/audit split, *pre* `controller_service.py:1686-1699` (1B.12 `:1682-1699`) | Reconciliation status committed before audit; audit failure left a committed decision without its security audit. Fault: fail `record_audit` for `reconcile_status_ok`. | Forensic/audit-traceability gap. | No | *Post* `:1698-1712` groups guard, status CAS and audit in the existing `atomic_write()` DB-only transaction; failure rolls back both writes. |
| F-14-08 | M-01 VERIFYING journaling, *pre* `controller_service.py:1445-1455` (1B.12 `:1383-1393,1421-1443`) | `INSTALLING → VERIFYING` used a standalone state write with no lifecycle-history row and no transaction group. Fault: crash/fault at that step. | Weaker audit reconstruction for an intermediate state; no unsafe promotion evidenced. | No | *Post* `:1449-1465` groups state CAS + `record_lifecycle_transition(..., 'VERIFYING', 'verification_evidence_persisted', 'ok')`; evidence is still stored before promotion, and failure rolls back before `VERIFIED`/`ACTIVE`. |
| F-14-09 | Repeated reconciliation audit entries, *pre* 1B14 test expectation | Three reconcile calls with distinct operation IDs produced three `reconcile_status_ok` audit rows. | Not a defect: audit entries correlate to distinct decisions; lifecycle history/status remained stable. | N/A | No source change. Test re-anchored to assert three operation-bound audits and stable final state; this was an initial test-design correction, not a weakened security assertion. |

## 3. Implemented changes

1. `broker/firewall_controller_service/controller_service.py`
   - `:492-498` persistence-category/unknown canonical read classification.
   - `:512-517` failed canonical-body pre-read is never treated as absence.
   - `:1014-1019` accurate create-race comment.
   - `:1449-1465` atomic, journaled `VERIFYING` establishment.
   - `:1666-1715` mandatory guard/allowed-state contract, removed dead evidence parameter, atomic status+audit write.
   - `:1958-1966,1993-2000` failed-branch conflict capture.
2. `broker/tests/test_post_j20_stage_1b14_persistence_reconciliation_residuals.py` — 11 deterministic sentinel/fault-injection tests.
3. `broker/tests/test_post_j20_stage_1b3_durable_crash_recovery.py` — cross-process crash anchor moved from grouped write `#1` (now `VERIFYING`) to `#2` (`VERIFIED`); assertions unchanged.
4. `broker/tests/test_post_j20_stage_1b4_cross_table_concurrency.py` — status barrier moved to before transactional lock acquisition; stale-guard assertion unchanged.

`broker/firewall_controller_service/ownership_store.py` was reviewed but not modified. Existing `atomic_write()`, `reconciliation_version_guard()`, append-only triggers, CAS rules and typed conflicts were reused as-is.

## 4. Contract preservation

- Public exception classes retained: `FirewallControllerRequestError`, `FirewallControllerPersistenceError`, `FirewallControllerBackendError`, `FirewallControllerIdempotencyError`, `BrokerDBError`, `PermissionError`.
- Storage failures remain storage failures; no persistence failure was converted to a validation error.
- Failed/unknown backend outcomes remain fail-closed; no unauthorized promotion was added.
- Ownership identity, policy binding, lifecycle CAS, evidence-before-promotion, completion-as-final-write and legacy/canonical rule separation are unchanged.
- Outward text is bounded; injected sentinel strings are absent from final errors/results.
- No compatibility behavior was removed except the private `_set_reconciliation_status` fallbacks and dead `require_evidence` parameter after repository-wide call-site verification.

## 5. Verification

See `docs/POST_J20_STAGE_1B_14_SECURITY_TEST_EVIDENCE.md` for exact commands, raw artifacts, exit codes and timings. Authoritative final results:

| Suite | Result | Exit |
|---|---:|---:|
| New Stage 1B.14 suite | 11 passed | 0 |
| Focused persistence/reconciliation | 113 passed | 0 |
| Stage 1B.6–1B.13 relevant regressions | 119 passed | 0 |
| Lifecycle/idempotency/concurrency | 235 passed | 0 |
| Full `broker/tests` | 984 passed, 1 warning | 0 |
| Django `instances.tests.test_manager_client` | 33 tests OK | 0 |
| `manage.py check` | no issues | 0 |

Initial and corrective failures are preserved separately and are not rewritten.
