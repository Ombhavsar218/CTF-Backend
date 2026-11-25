# Post-J.20 Stage 1B.5 — Final Risk Register (Mock-Only)

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

**T-11, T-13 and T-27: OPEN — ACCEPTANCE REQUIRED.** This register consolidates review
findings only. It does not close gates, accept risk, authorize live integration, or change
any existing status. No source implementation was modified in this milestone.

Source: `docs/POST_J20_STAGE_1B_5_INDEPENDENT_SECURITY_REVIEW.md` (findings SR-01–SR-14).

## 1. Classification summary

| Classification | Count | Finding IDs |
|---|---:|---|
| Verified controls (informational) | 5 | SR-01, SR-02, SR-03, SR-04, SR-05 |
| Partially mitigated risks | 4 | SR-06, SR-07, SR-08, SR-09 |
| Unverified assumptions | 2 | SR-11, SR-12 |
| Known limitations | 3 | SR-10, SR-13, SR-14 |
| Formally accepted residual risks | 0 | none |

Severity in this register is contextual: "High" for SR-12 reflects production/host
context, not a proven defect in the mock implementation. No Critical finding was
identified in the reviewed Stage 1B mock-only code.

## 2. Consolidated risk entries

| ID | Risk / control | Classification | Severity | Confidence | Security impact | Existing mitigation | Residual exposure | Gate linkage | Acceptance evidence required |
|---|---|---|---|---|---|---|---|---|---|
| SR-01 | Durable intent/idempotency ledger | Verified control | Informational | High | Prevents lost intent, duplicate conflicting payloads, stale completion overwrite | Intent-before-backend, CAS, terminal outcome + `COMPLETED` in one transaction, authority replay | Legacy NULL-outcome tolerance; message-string duplicate-create classification; process-local cache | M-01 | Existing 1B.1/1B.4 suites; global scope closure where required |
| SR-02 | Lifecycle FSM and versioned CAS | Verified control | Informational | High | Prevents stale/duplicate terminal transitions | Explicit edges, versioned CAS, rollback on conflict | Split install-failure writes; history-less intermediate verify step; multiple transaction groups | M-01, M-06 | Existing 1B.2/1B.4 suites; transaction matrix acceptance |
| SR-03 | Evidence- and readback-gated recovery | Verified control | Informational | High | Prevents fabricated ACTIVE/REVOKED states | Authority-derived targets, evidence gates, trusted readback, fail-closed uncertainty | Non-converging uncertainty when readback unavailable; full-scan scope; null policy_id error entry | RR-05, RR-06, M-06 | Existing 1B.3 suites; completeness review |
| SR-04 | Cross-table consistency guards | Verified control | Informational | High | Prevents conflicting terminal outcomes and stale reconciliation writes | Completion outcome CAS, reconciliation version guard, canonical UNIQUE winner validation | Depends on SR-07/SR-08/SR-09 remediation for full closure | RR-05, RR-06, M-06 | Existing 1B.4 suite; new typed-error/guard tests |
| SR-05 | Ownership/evidence binding and canonical read-back | Verified control | Informational | High | Prevents cross-policy replay and evidence substitution | Authoritative request rebuild, binding predicates, append-only triggers, digest recomputation/readback | `controller_policy_bodies` has detection, not append-only prevention | N-02, H-05, M-06 | Existing trigger/readback suites; future migration acceptance |
| SR-06 | Auth/trust boundary | Partially mitigated | Medium | High | Mock identities are not kernel-authenticated; permissive seams remain | Strict-by-default auth, empty allowlists, claim stripping, per-request helper identity, focused 136-pass suite | Request-dict peer claims; `controller_verified` trusted flag; non-strict test provider; no SO_PEERCRED wiring | I-07, I-09, T-11, T-13, T-27 | Named-authority acceptance + host-authenticated identity evidence |
| SR-07 | String-based persistence classification | Partially mitigated | Medium | High | Misclassification can invert idempotent-race vs genuine-failure outcomes | Unmatched failures fail closed; F-02 raw `BrokerDBError` preserved | Message-format coupling at `ownership_store.py:804`, `controller_service.py:436-460,972-976` | M-01, RR-07, I-08 | Typed-error fault matrix; regression equivalence |
| SR-08 | Canonical pre-read failure treated as absence | Partially mitigated | Medium | High | Transient read failure can be misclassified and mask corruption | Final winner revalidation and trusted readback still fail closed | `ownership_store.py:794-797` contradicts `:337-342` | M-06, RR-06, I-08 | Fault-injected pre-read failure test |
| SR-09 | Non-uniform reconciliation status fencing | Partially mitigated | Low | High | Stale worker can overwrite newer `reconciliation_status` | Lifecycle CAS still protects state; other branches guarded | Unguarded `controller_service.py:1754,1781` | RR-05, M-06 | Concurrency test for those branches |
| SR-10 | No cross-system atomicity | Known limitation | Medium | High | Crash between DB and backend effects remains uncertain by design | Intent before dispatch, evidence before promotion, uncertain classification, no fabricated success | Best-effort duplicate prevention; operator action may be needed | M-01, M-06, RR-05, RR-06 | Formal acceptance of documented limitation |
| SR-11 | Mock backend semantics assumed | Unverified assumption | Medium | High | Real backend could break key dedup or readback truthfulness | Key reuse, readback gate, `REVOKE_UNCONFIRMED`, mock tests | No live backend evidence | T-11, T-13, T-27, H-02, N-04 | Authorized live integration contract tests |
| SR-12 | Host enforcement/kernel peer identity unproven | Unverified assumption | High (production) | High | No proof of host firewall state, peer identity, runtime authority | Strict mock-only scope, fail-closed adapters, explicit documentation | Full host trust boundary open | T-11, T-13, T-27, H-02, N-04 | Named-authority acceptance + host evidence |
| SR-13 | Legacy compatibility separation | Verified control / known limitation | Low | High | Preserves compatibility without unsafe conversion | Canonical enforcement at service/helper; conditional body handling; lazy import | Residual coupling; universal migration/quarantine open | N-02, H-05 | Future gate closure evidence |
| SR-14 | Gate/evidence documentation hygiene | Known limitation | Low | High | Reader confusion, not a control failure | Final exit-code evidence preserved; this evidence-only register update | Scope-label mismatch; stale historical artifact states | All gates (documentation only) | Governance scope-label reconciliation |

## 3. Aggregate risk posture

- **Mock-only implementation risk:** no proven Critical or High defect in the reviewed
  Stage 1B code paths. The strongest verified controls are the ledger CAS, lifecycle CAS,
  atomic DB write groups, evidence/readback gating, append-only triggers and canonical
  trusted read-back.
- **Robustness risk:** three source-provable medium items remain (SR-06 trust boundary in
  production context, SR-07 string-based classification, SR-08 read-failure-as-absence).
  They are narrow and local, but they are not eliminated by the current suite.
- **Reporting risk:** SR-09 can misreport reconciliation status in two branches without
  changing lifecycle state.
- **Scope risk:** SR-10/SR-11/SR-12 are inherent to mock-only evidence. Passing tests must
  not be read as host enforcement, real identity, live backend, or formal acceptance proof.
- **Governance risk:** SR-14; no gate is verified closed and no risk is formally accepted.

## 4. Accepted residual risks

**None.** No named-authority acceptance record, risk-acceptance form, or gate-closure
evidence was found for T-11, T-13, T-27 or any other gate. All residual items above remain
open for acceptance or remediation as applicable.

## 5. Invariants that must remain true until acceptance

1. Mandatory status remains **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
2. T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**.
3. No gate is marked VERIFIED CLOSED by this review.
4. No live firewall/Docker/UDS/SO_PEERCRED/privileged helper/host permission operation is
   performed under this milestone.
5. No end-to-end atomicity claim is made across SQLite writes and backend effects.
6. Evidence rows remain controller observations at a mock boundary, not host truth.

## 6. Stage 1B.6 evidence-only update (2026-11-17)

This section records later evidence only; it does not change any gate, formal acceptance
status, or the Stage 1B.5 baseline classification of other findings.

- **SR-07 (string-based persistence classification): VERIFIED FIXED (scoped).** Targeted
  `ON CONFLICT(...)` conflict targets and typed `BrokerDBIdempotencyConflict` /
  `BrokerDBCanonicalBodyConflict` / `BrokerDBCanonicalError(category=...)` replace message
  classification in `ownership_store.py` and `controller_service.py`. Evidence:
  `docs/POST_J20_STAGE_1B_6_TARGETED_RESIDUAL_GAP_REMEDIATION.md`,
  `post_j20_stage_1b6_new_suite.*`, `post_j20_stage_1b6_targeted.*`,
  `post_j20_stage_1b6_full.*` (full broker suite 944 passed, exit 0).
- **SR-08 (canonical pre-read failure treated as absence): VERIFIED FIXED (scoped).** The
  trusted pre-read no longer converts storage failures to absence; missing, unavailable,
  corrupt and mismatched canonical data fail closed; legacy no-rules installs remain a no-op.
  Evidence: same Stage 1B.6 document and focused fault-injection tests.
- **SR-09 (non-uniform reconciliation status fencing): VERIFIED FIXED (scoped).** All
  reconciliation decision writes now use explicit allowed source states, fresh binding,
  lifecycle-version CAS and operation-bound audit; the previously unguarded
  `needs_verification` and `failed` writes are routed through the guard. Evidence: same
  Stage 1B.6 document and concurrency/guard-capture tests.
- SR-06, SR-10, SR-11, SR-12, SR-13 and SR-14 remain unchanged. T-11, T-13 and T-27 remain
  **OPEN — ACCEPTANCE REQUIRED**. No formal risk acceptance or gate closure is recorded.

## 7. Stage 1B.7 independent verification update (2026-11-17, evidence-only)

This section records independent review evidence only. It does not change gate status, accept
residual risk, or authorize live integration. Deliverables:
`docs/POST_J20_STAGE_1B_7_INDEPENDENT_REMEDIATION_VERIFICATION.md`,
`docs/POST_J20_STAGE_1B_7_FINAL_MOCK_ONLY_ASSESSMENT.md` and
`docs/POST_J20_STAGE_1B_7_FINAL_ACCEPTANCE_REQUIREMENTS.md`.

- **Phase 1 evidence confirmed:** `post_j20_stage_1b6_new_suite.*` = 16 passed, EXIT=0;
  `post_j20_stage_1b6_targeted.*` = 301 passed, EXIT=0; `post_j20_stage_1b6_full.*` =
  944 passed, 0 failed, 0 errors, EXIT=0, 391.61s. An independent non-destructive rerun of the
  focused suite produced 16 passed in 7.11s. No source/test file was modified.
- **SR-07 independently confirmed VERIFIED FIXED (scoped):** targeted SQL `ON CONFLICT`
  clauses plus typed conflict/category exceptions replace message matching
  (`ownership_store.py:15-42,490-528,737-814,831-858`), and bounded public errors and distinct
  PENDING/UNCERTAIN outcomes are preserved (`controller_service.py:441-461,774-782,962-1017,
  1471-1499,2021-2029`). Non-blocking residuals: broad create-exception catch at `:968` not
  gated on typed flag, and catch-all mapping at `:461`.
- **SR-08 independently confirmed VERIFIED FIXED (scoped):** `None` is returned only for zero
  rows (`ownership_store.py:860-867`); `_query_dicts`/`BrokerDB.query` propagate failures
  (`ownership_store.py:367-380`; `broker/app/db.py:286-297`); the canonical pre-read explicitly
  re-raises `BrokerDBError` and wraps other failures (`ownership_store.py:831-858`); trusted
  JSON/schema/binding/digest validation fails closed (`:869-938`); install, verify and
  reconciliation promotion paths are gated (`controller_service.py:1210-1220,1364-1419,
  1663-1699,1925-1993,2031-2037`); legacy no-rules scope is unchanged
  (`rule_schema_v1.py:372-378`; `controller_service.py:415-422,862-876`). Non-blocking residual:
  a nested read failure inside `read_trusted_canonical_policy_body()` is labeled
  `invalid_canonical_policy_body`/`uncertain` rather than persistence failure
  (`controller_service.py:1682-1690`), but still fails closed with no promotion.
- **SR-09 independently confirmed VERIFIED FIXED (scoped):** all 11 production reconciliation
  status writes use the guarded helper with explicit allowed states, fresh read, identity
  binding and lifecycle CAS (`controller_service.py:1528-1583,1684-1715,1768-1796,1814-1817,
  1844-1846,1933-1950,2001-2003`); lifecycle evidence gates and stale-worker/terminal-state
  tests remain intact. Non-blocking residuals: compatibility fallbacks at `:1541-1547` unused
  by production callers, unused `require_evidence` status parameter, no dedicated guard-capture
  test for the `failed` branch, and status/audit written as separate guarded writes.
- **SR-06, SR-10, SR-11, SR-12, SR-13 remain unchanged.** SR-14 gains an evidence-only
  observation: the Stage 1B.6 initial-failure note's final paragraph names an earlier 14-test
  capture while the authoritative final artifacts record 16 tests and EXIT=0; the note was
  preserved, not edited.
- **Consolidated decision:** CONDITIONALLY READY FOR FORMAL ACCEPTANCE REVIEW (not production
  authorization). T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**; no gate is
  verified closed and no residual risk is accepted.
