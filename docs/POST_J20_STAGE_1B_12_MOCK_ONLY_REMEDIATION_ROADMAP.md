# Post-J.20 Stage 1B.12 — Mock-Only Remediation Roadmap

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.**

Repository: `E:\Flag-hunt\ctf-platform-be` | HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`  
Milestone: Stage 1B.12 (2026-11-17), assessment/planning only. No implementation performed.

## 1. Planning constraints

- Reuse existing canonical contracts and persistence architecture (`controller_service.py`, `ownership_store.py`, `rule_schema_v1.py`, existing FSM/CAS/ledger/append-only/read-back patterns). **No parallel state machines and no duplicate sources of authority.**
- Preserve evidence-before-promotion, completion-as-final-write, F-02 storage-failure propagation, granular install-failure reporting, and fail-closed uncertainty unless a contract change is explicitly authorized.
- **Do not weaken existing tests or change exception contracts merely to obtain passing tests.** Any externally visible error-type/code/status contract change requires explicit justification and regression updates.
- Mock-only scope only: no host, Docker, UDS/`SO_PEERCRED`, privileged helper, capability, nftables/iptables, cloud, live-backend, or firewall operations.

## 2. Prioritized remediation sequence (mock-only engineering)

### Priority P1 — Universal canonical validation closure in repo boundaries
**Targets:** I-07, RR-01, RR-02 (covered/mock boundaries), supporting RR-03/RR-04 strictness where contract-safe.

| Step | Action | Primary files | Dependencies | Exit criteria |
|---|---|---|---|---|
| P1.1 | Inventory and centralize canonical identifier/request validation (single validator aligned with `controller_service` canonical rules/optional semantics) for service, `request_validator`, `app/firewall_controller_contract`, `app/firewall_controller`, and reconciliation/full-scan handling. | `controller_service.py`, `request_validator.py`, `app/firewall_controller_contract.py`, `app/firewall_controller.py` | None | All in-repo boundaries validate before lookup/state mutation/persistence/side effects where applicable. |
| P1.2 | Normalize/reuse binding predicate for policy/version/digest/instance/network/family/ownership/aliases in covered paths; reject contradictory/unknown alias combinations fail-closed before side effects. | `controller_service.py`, adapters/contract/read-back consumers | P1.1 | No covered path accepts contradictory correlation/ownership aliases. |
| P1.3 | Defensive store/helper checks for non-canonical keys where cheap and contract-compatible (no behavior drift). | `ownership_store.py` (only if safe) | P1.1 | Store-facing calls fail closed on malformed keys without changing public contracts. |

**Required regression tests:** per-entrypoint/field/alias negative matrix (non-string, empty, control chars, overlong, invalid charset, wrong type/bool/bounds), zero-side-effect assertions (DB/idempotency/backend/audit/history/evidence), reconciliation/adversarial replay/alias-confusion cases. Preserve existing contract tests.

### Priority P2 — Bounded error and leakage prevention
**Targets:** I-08, RR-07, SR-07 residual notes, SR-08 residual classification note.

| Step | Action | Primary files | Dependencies | Exit criteria |
|---|---|---|---|---|
| P2.1 | Introduce/route outward errors through a single bounded mapper (allowlisted error code/category + fixed/template-safe messages). Remove raw `str(e)`/schema/backend message passthroughs in `request_validator.py` and `app/firewall_controller.py`; sanitize backend `error_message`/details in controller responses. | `request_validator.py`, `app/firewall_controller.py`, `app/firewall_controller_contract.py`, `controller_service.py`, shared error utility if added within existing architecture | P1 (validation messages) | No outward path emits raw exception/DB/backend/secret-bearing strings in tested cases. |
| P2.2 | Align SR-07 residual handling: narrow/gate broad create-exception path or correct overbroad comment; classify unknown read-back exceptions consistently (request vs persistence) per policy while remaining bounded/fail-closed. | `controller_service.py` | P2.1 | Bounded, correctly categorized fail-closed behavior; comments match behavior. |
| P2.3 | SR-08 residual: distinguish nested trusted-read storage failures (`BrokerDBError`/persistence category) from canonical corruption/invalidity in reconciliation so storage faults map to persistence-failure/`RECONCILIATION_PERSISTENCE_FAILURE` without promotion. | `controller_service.py` (`1663-1699` area) | P2.1 | Storage-fault-injected nested read reports persistence failure; corruption/mismatch remains uncertain/invalid. |

**Required regression tests:** leakage-negative injection matrix across contract/validator/service/adapter/canonical-read/idempotency/revoke/install/inspect paths; fault injection for non-conflict create errors, unknown read-back exceptions, nested reconciliation read storage failure vs corruption; preserve existing error-type/code/status contracts.

### Priority P3 — Reconciliation evidence, audit integrity, and guarded-write hardening
**Targets:** SR-09 residuals, RR-05/RR-06 consistency support, M-01 journaling consistency (behavior-preserving).

| Step | Action | Primary files | Dependencies | Exit criteria |
|---|---|---|---|---|
| P3.1 | Remove or production-fence reconciliation status fallback paths (`allowed_states` required for production callers; no bypass for stores/callers lacking contract in production path). | `controller_service.py` | None | Production reconciliation cannot bypass state/identity contract; test-only seams explicitly isolated if retained. |
| P3.2 | Add guard-capture/negative coverage for `failed` branch and conflict cases; wire or remove unused `require_evidence` to avoid false assurance (prefer enforcing where intended, without changing promotion gates). | `controller_service.py`, Stage 1B test module(s) | P3.1 | All guarded status outcomes covered; no dead security-relevant parameter semantics. |
| P3.3 | Decide and, if contract-safe, implement status+audit atomicity or explicit documented failure semantics for guarded reconciliation writes. | `controller_service.py`, `ownership_store.py` (`atomic_write`) | P3.1 | No silent loss of security-relevant audit on guarded status change, or explicit fail-closed/documented behavior. |
| P3.4 | Behavior-preserving VERIFYING establishment journaling/grouping review: add grouped/history-recorded step or explicit documented exception consistent with recovery invariants. | `controller_service.py` | Review of 1B.2/1B.3 invariants | VERIFYING transition evidence/audit trail is consistent without weakening evidence-before-promotion. |

**Required regression tests:** stale-worker conflicts on needs_verification/failed/uncertain/ok, identity mismatch no-write, repeated reconcile stability, audit-failure-after-status-write behavior, verify crash/fault around VERIFYING, CAS contention, F-02 preservation, 1B.1–1B.4/J.8–J.13/J.17 regressions.

### Priority P4 — Persistence/evidence integrity hardening (additive, authority-bounded)
**Targets:** M-06 (mock-scope hardening), selected RR-05/M-01 boundaries.

| Step | Action | Primary files | Dependencies | Exit criteria |
|---|---|---|---|---|
| P4.1 | Assess additive append-only protection for `controller_policy_bodies` and audit-criticality policy; implement only if migration/compatibility impact is accepted and additive. | `ownership_store.py`, migrations if approved | P3; authority/governance review for schema change | Tamper prevention/detection and audit semantics explicitly defined; trusted read-back remains promotion gate. |
| P4.2 | Document and test DB-only transaction boundaries and crash windows; do not claim end-to-end atomicity (SR-10). | docs/tests as applicable | P3/P4.1 | Evidence accurately reflects guarantees and uncertainty. |

**Required regression tests:** attempted UPDATE/DELETE on protected tables (if hardened), audit-failure behavior per operation, crash windows between evidence/state/audit/completion, canonical corruption/tamper detection.

### Priority P5 — Legacy/canonical boundary tightening (mock-only, no migration closure)
**Targets:** N-02, H-05, M-08, SR-13 (covered boundaries only).

| Step | Action | Primary files | Dependencies | Exit criteria |
|---|---|---|---|---|
| P5.1 | Make legacy-compat alias/mirror handling explicit and test "no silent conversion/no canonical synthesis" for legacy-only paths. | `rule_schema_v1.py`, `controller_service.py`, `ownership_store.py` | P1/P2 | Legacy accepted paths remain non-canonical by design; incompatible mixed forms fail closed. |
| P5.2 | Add boundary inventory/documentation for canonical vs legacy-accepted forms in mock scope. | docs + tests | P5.1 | No ambiguity in covered paths; universal/end-to-end closure not claimed. |

**Required regression tests:** legacy no-rules lifecycle without canonical body creation, schema-v1 paths requiring valid canonical body, invalid/mismatched compiled-vs-canonical digest/mirror cases, mixed legacy+schema-v1 rejection, trusted read-back tamper cases.

### Priority P6 — Identity/test-seam hardening in mock scope (non-host)
**Targets:** SR-06, I-09 (mock-only portion).

| Step | Action | Primary files | Dependencies | Exit criteria |
|---|---|---|---|---|
| P6.1 | Restrict explicit permissive/non-strict auth injection to clearly test-only factories/contexts; add guards preventing accidental live-capable composition use in repo-known entrypoints. | `controller_service.py`, `authorization.py`, `authorization_strict.py`, composition points | Review of construction paths | Default/live-capable repo paths cannot silently use permissive seams. |

**Required regression tests:** construction/wiring negatives for permissive providers and `strict_auth=False` in default/live-capable factories; explicit test-only seam still available for tests.

## 3. Documentation/governance remediation (parallel, evidence-only)

- Maintain dated reconciliation notes for SR-14 chronology/scope-label/citation/count-method issues; do not rewrite historical artifacts (1B.9/1B.11 precedent).
- Record residual dispositions for SR-07/SR-08/SR-09 notes and error-contract expectations when P2/P3 implemented.
- Keep gate/register status unchanged unless supported by actual implementation/test/review/acceptance evidence in a future authorized milestone.

## 4. Out of scope for mock-only engineering

- T-11/T-13/T-27 acceptance or host/runtime closure; H-01/H-03/H-04/M-02/M-07/M-09/N-01 host transport/identity/firewall evidence; SR-11 live-backend contract evidence; SR-12 kernel-authenticated host identity; end-to-end DB↔backend atomicity (SR-10) closure; universal deployed envelope/migration closure (N-02/H-05/M-08/SR-13) beyond covered boundaries.

## 5. Proposed implementation milestone packaging

If approved, implement as separate mock-only milestones to control regression risk:
1. **1B.13:** P1 + P2 (validation + bounded errors/leakage + SR-07/SR-08 residual classification)
2. **1B.14:** P3 + behavior-preserving P4/P6 items
3. **1B.15:** P5 boundary hardening and documentation/governance updates

Each milestone requires: exact scope, preserved baselines, targeted + full broker regression evidence, no weakened assertions, and no gate/risk-status changes without authority evidence.