# Phase 2L.2J.6 — Engineering Remediation Report (Mock-Only)
## Canonical Policy Persistence, Legacy Adapter and Read-Back Integrity

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be` (git root: `E:/Flag-hunt/ctf-platform-be`)  
**Branch/commit (baseline):** `main...origin/main`, `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (`b365584 New: Challenges backend`)  
**Phase:** 2L.2J.6  
**Date:** 2026-11-15  
**Scope:** Mock-only incremental implementation toward durable canonical policy-body persistence and trusted read-back integrity; partial completion of requested workstreams.  
**Authorization boundary:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

No real Docker daemon/socket access, no real container/network operations, no UDS, no `SO_PEERCRED`, no privileged helper, no Linux capabilities/`CAP_NET_ADMIN`, no nftables/iptables/`DOCKER-USER`, no real host firewall/systemd/host-permission changes, no real Linux host validation, no cloud/production deployment, and no real firewall operations were implemented or executed.

---

## 1. Executive result

- **Canonical policy persistence/read-back (N-02 related):** **PARTIALLY IMPLEMENTED / PARTIALLY VERIFIED (mock-only)**.
  - **Implemented and tested:** additive durable canonical schema-v1 policy-body persistence in controller ownership store (`controller_policy_bodies`), store-level write/read validation (normalized rules, schema version, ownership/digest bindings), trusted read-back recomputing compiled rule digest and failing closed on corruption/mismatch/unsupported schema, and controller install-path persistence for schema-v1 rule-bearing installs.
  - **Not completed:** full trusted read-back integration across inspection/verification/reconciliation for all relevant canonical records, complete legacy adapter/migration strategy for all legacy contracts/records, broker legacy compiler/state canonicalization/migration, comprehensive adversarial/fault-injection matrix, and end-to-end N-02 closure.
- **Regressions:** `manage.py check` passed (0 issues). `manager/tests` **30 passed, 1 warning**. `broker/tests` **625 passed, 1 warning** (149.00s). Targeted new 2J.6 tests **6 passed**.
- **N-04:** **PARTIALLY RESOLVED** (fail-closed adapters reconfirmed by passing suites; no operational Docker authority introduced; not verified closed).
- **Host-validation readiness:** **NOT READY**
- **Live firewall integration:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

---

## 2. Initial Git baseline

Verified from `ctf-platform-be` before and after modifications:

- `git rev-parse --show-toplevel`: `E:/Flag-hunt/ctf-platform-be`
- `git status --short --branch`: `## main...origin/main`
- `git rev-parse HEAD`: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`
- `git diff --stat`: 26 tracked files changed, 2540 insertions(+), 80 deletions(-) (pre-existing)
- **Pre-existing modified tracked files (26, preserved):** `.env.example`, `.gitignore`, `README.md`, `achievements/views.py`, `announcements/views.py`, `challenges/admin_urls.py`, `challenges/models.py`, `challenges/serializers.py`, `challenges/tests.py`, `challenges/urls.py`, `challenges/views.py`, `config/__init__.py`, `config/settings.py`, `config/urls.py`, `requirements.txt`, `submissions/serializers.py`, `submissions/stats.py`, `submissions/tests.py`, `submissions/urls.py`, `submissions/views.py`, `users/admin_views.py`, `users/management/commands/setup_groups.py`, `users/tests.py`, `users/throttling.py`, `users/urls.py`, `users/views.py`
- **Pre-existing untracked entries (preserved):** substantial set including `broker/`, `manager*`, `docs/`, `audit/`, `instances/`, debug/fix/out artifacts, deployment/config additions, zips, etc.
- No `git reset`, `git clean`, `git checkout --`, broad revert, staging, or commit performed.

---

## 3. Existing persistence architecture

| Component | Store/DB | Current role | Canonical schema-v1 rule-body persistence before 2J.6 |
|---|---|---|---|
| Controller ownership/evidence/idempotency/audit/lifecycle | `broker/firewall_controller_service/ownership_store.py` (`ControllerOwnershipStore`, SQLite via `broker.app.db.BrokerDB`) | Authoritative controller ownership, lifecycle state, idempotency records, evidence, audit/history, reconciliation status | **No** durable canonical rule bodies; digests/metadata/state only |
| Broker firewall policy state (legacy app path) | `broker/app/firewall_state.py`, `broker/app/db.py` (`firewall_policies`, `firewall_verification_evidence`) | Legacy firewall policy lifecycle, compiled legacy rules JSON, legacy digest/evidence | **No** schema-v1 8-field canonical bodies (legacy format) |
| Mock backend/state runtime | `broker/app/firewall_controller.py` (`MockFirewallController`) | In-memory install/inspect/verify/revoke state | In-memory only (2J.5 added schema-v1 validation/normalization when rules present) |

**Decision:** Controller-side schema-v1 install flows already bind ownership/digests in `ControllerOwnershipStore`; adding an **additive canonical policy-body table in `ControllerOwnershipStore`** is the least-invasive correct boundary for durable mock-only persistence of schema-v1 rule bodies without disrupting broker legacy `firewall_state`/compiler model.

---

## 4. Legacy/canonical model decision

| Format/context | Classification | Decision | Rationale |
|---|---|---|---|
| Schema-v1 8-field rules (`rule-schema-v1`, 2H.1 §4.4.1) on controller/helper/install boundaries | **Canonical schema-v1** | Validate/normalize via shared `rule_schema_v1.py`; persist durably in controller store for schema-v1 install requests; trusted read-back must revalidate and recompute digest | Target canonical contract; 2J.3/2J.4/2J.5 enforcement preserved |
| Controller/mock install requests without `rules` (digest/compiled legacy payloads) | **Supported legacy/mock format** (existing compatibility) | Continue to accept where existing behavior requires; do not create canonical body records; do not claim canonical persistence | Preserve existing tests/flows; no safe universal conversion without rule bodies |
| Helper contract envelope `SCHEMA_VERSION=2L.2G.3` with optional schema-v1 rule validation when rules present | **Supported legacy envelope with canonical rule validation (partial)** | Preserve; no full 2L.2I.2 migration in 2J.6 | Compatibility retained; migration out of scope/safe completion here |
| Broker firewall flat rules (`dest_ip/dest_subnet/dest_port/...`) in `firewall_policy.py`/`firewall_compiler.py`/`firewall_state.py` | **Legacy format (separate model)** | Keep separate; do **not** reinterpret as schema-v1; no silent conversion | Field semantics incompatible with schema-v1 8-field contract; unsafe to guess mappings |
| Unknown/ambiguous/malformed canonical records or schema versions | **Unsupported/ambiguous** | Fail closed on write/read/validation paths implemented | Prevent corrupt or ambiguous policy acceptance |

**No multiple competing adapters introduced.** Explicit single-adapter conversion for all legacy contracts was **not implemented** in 2J.6.

---

## 5. Actual implementation changes

1. **`broker/firewall_controller_service/ownership_store.py`**
   - Added additive `controller_policy_bodies` table (schema-v1 policy body id, ownership/policy/version binding, `schema_version`, canonical rules JSON, required families, compiled/canonical digests, controller/request/operation metadata, FK to ownership, unique `(policy_id, policy_version)`).
   - Enabled `PRAGMA foreign_keys=ON` during schema init (additive; no destructive migration).
   - Added canonical body APIs: `store_canonical_policy_body`, `ensure_canonical_policy_body` (idempotent with validation), `get_canonical_policy_body`, `read_trusted_canonical_policy_body`.
   - Trusted read-back validates ownership existence/binding, schema version (`rule-schema-v1`), JSON parse, required families, shared schema-v1 normalization, recomputed compiled rule digest equality, stored/ownership/expected digest consistency, and owner/ownership-record/compiled-digest bindings; fails closed (`BrokerDBError`) on corruption/mismatch/unsupported schema/missing data.

2. **`broker/firewall_controller_service/controller_service.py`**
   - Added `_ensure_canonical_policy_body_persisted(req, ownership_rec)` and invoked it for `install_policy` before backend dispatch when schema-v1 `rules` are present, binding to authoritative ownership and normalized request digests/rules.
   - Preserved legacy installs without `rules` (no canonical body required).

3. **Tests:** added `broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py` (6 tests) exercising actual store/service behavior.

4. **Preserved:** 2J.3 schema-v1 validator/integration, 2J.4 policy-version hardening, 2J.5 mock-state install validation, existing ownership/idempotency/revoke-recovery/auth/fail-closed Docker behavior (validated by regressions and `manage.py check`).

---

## 6. Files modified and created

### Modified
1. `ctf-platform-be/broker/firewall_controller_service/ownership_store.py`
2. `ctf-platform-be/broker/firewall_controller_service/controller_service.py`
3. `ctf-platform-be/docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` (evidence-justified update)
4. `ctf-platform-be/docs/PHASE_2L_2J_6_ENGINEERING_REMEDIATION_REPORT.md` (this report)
5. `ctf-platform-be/docs/PHASE_2L_2J_6_INDEPENDENT_VERIFICATION.md`

### Created
1. `ctf-platform-be/broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py`
2. `ctf-platform-be/docs/PHASE_2L_2J_6_ENGINEERING_REMEDIATION_REPORT.md`
3. `ctf-platform-be/docs/PHASE_2L_2J_6_INDEPENDENT_VERIFICATION.md`

---

## 7. Persistence design

- **Boundary:** Controller ownership store (`ControllerOwnershipStore`) — additive canonical body table linked to authoritative ownership record.
- **Stored for schema-v1 installs (when `rules` present):** `policy_body_id`, `ownership_record_id`, `policy_id`, `policy_version`, `schema_version='rule-schema-v1'`, canonical normalized rules JSON, required families JSON, `compiled_rule_digest`, `canonical_policy_digest`, controller/request/operation identifiers, timestamps.
- **Write behavior:** validates/normalizes rules via shared validator, recomputes compiled digest, verifies ownership exists and binding/digest consistency, inserts transactionally; `ensure_*` is idempotent only when existing record validates and matches.
- **Not stored:** Canonical rule bodies for legacy installs without schema-v1 `rules`; no replacement of broker legacy `firewall_state` records.

---

## 8. Database and migration changes

- **Change:** additive `CREATE TABLE IF NOT EXISTS controller_policy_bodies` and indexes in controller store schema init; `PRAGMA foreign_keys=ON`.
- **Migration type:** safe additive schema evolution on existing/new controller DBs (no destructive table recreation, no data deletion/reset).
- **Reversibility:** table/index creation is additive; removing code paths would require separate rollback planning (not performed).
- **Legacy records:** existing ownership/evidence/idempotency/lifecycle records unchanged; legacy canonical-body absence remains valid for legacy flows.
- **Disposable DB testing:** exercised implicitly via temp DBs in existing/new tests and full suite runs.
- **Not implemented:** formal migration framework/versioned migration scripts, interrupted/partial migration fault-injection matrix, explicit legacy-record conversion/quarantine state model beyond fail-closed validation.

---

## 9. Read-back integrity

**Implemented and tested (store/trusted API):**
- Loads ownership + canonical body record.
- Verifies ownership/body binding and policy/version identity.
- Verifies schema version (`rule-schema-v1`) when required.
- Parses rules JSON and required families; rejects corrupt JSON/missing data.
- Revalidates rules via shared schema-v1 validator (rejects invalid/noncanonical/unsupported content as applicable).
- Recomputes `compiled_rule_digest` and compares with stored/ownership/expected digests.
- Enforces expected owner/ownership-record/compiled-digest bindings when provided.
- Returns normalized canonical representation on success; fails closed on mismatch/corruption.

**Not fully implemented:** single trusted read-back path wired into all inspection/verification/reconciliation/service response flows for every relevant canonical policy operation.

---

## 10. Inspection and verification

- **Implemented:** existing ownership/auth/digest/lifecycle checks and 2J.3–2J.5 schema/install hardening preserved; canonical body persistence/read-back primitives available.
- **Not implemented/completed:** mandatory use of trusted canonical read-back in all inspection/verification service paths and response construction, full bounded fail-closed behavior for all corrupt canonical records in those operations, and evidence-to-read-back canonical comparisons as specified.
- **Status:** **Implemented but partially verified / partially implemented.**

---

## 11. Recovery and reconciliation

- **Implemented/preserved:** existing revoke recovery/idempotency/reconciliation logic and hardening suites remain passing (full broker regression).
- **Not implemented/completed:** reconciliation/inspection/verify integration with trusted canonical body read-back for all relevant records, fail-closed handling for malformed/unsupported/corrupt canonical persisted bodies in all reconciliation branches, quarantine/explicit corrupt-state handling aligned to spec, and deterministic fault-injection matrix for persistence/read-back/reconciliation failures.
- **Status:** **Implemented but partially verified.**

---

## 12. Legacy compatibility results

- Legacy installs without schema-v1 `rules` remain supported and do not require canonical body persistence (**tested**).
- Broker legacy firewall compiler/state format remains separate and not converted to schema-v1 (**by design in this phase**).
- No explicit controlled legacy-to-canonical adapters added for legacy firewall policy records/contracts.
- Unsupported/ambiguous canonical records fail closed in implemented read-back/write validation paths (**tested**).

---

## 13. Adversarial tests

**New 2J.6 tests (`broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py`, 6 passed):**
- Install persists canonical body; trusted read-back returns normalized rules/digests.
- Write rejects compiled digest mismatch.
- Trusted read-back fails closed on corrupt JSON and stored digest mismatch (tampered record).
- Trusted read-back fails closed on owner mismatch, ownership-record mismatch, expected compiled-digest mismatch.
- Trusted read-back fails closed on unsupported schema version.
- Legacy install without rules succeeds without canonical body record.

**Not implemented (requested matrix, partial list):** duplicate/conflicting policy-body edge cases beyond DB uniqueness behavior, transaction rollback/partial/interrupted write fault injection, unauthorized read-back at service/API boundary, inspection/verification/reconciliation corrupt/missing-evidence/uncertain/repeated/cross-owner isolation against canonical bodies, legacy safe conversion/ambiguous legacy-record handling, migration failure/rollback/repeated migration tests.

---

## 14. N-02 final assessment

- **Status:** **PARTIALLY IMPLEMENTED**.
- **Implemented and tested (2J.6 contribution):** durable additive canonical schema-v1 policy-body persistence in controller store, install-path persistence for schema-v1 rule-bearing requests, trusted read-back validation/recomputed-digest fail-closed behavior, and compatibility for legacy no-rules installs.
- **Implemented but partially verified:** preservation of prior schema/contract/policy-version/lifecycle behavior (full suites and `manage.py check` passed).
- **Not implemented:** full N-02 lifecycle closure (canonical body integration into all inspection/verification/reconciliation/read-back/response paths, legacy adapter strategy/migration, broker legacy model alignment/conversion where safe, complete adversarial coverage, 2L.2I.2 envelope/SCHEMA-01–05).

---

## 15. Related gate reassessment

| ID | Assessment | Notes |
|---|---|---|
| N-02 | **PARTIALLY IMPLEMENTED** | Foundational persistence/read-back progress; end-to-end closure incomplete. |
| N-03 | **PARTIALLY RESOLVED** | Evidence/docs updated; I-07/I-08/I-09/M-06/RR gaps remain. |
| H-05 | **PARTIALLY RESOLVED** | Full 2L.2I.2/rule-schema migration incomplete. |
| M-01 | **PARTIALLY VERIFIED** (no 2J.6 scope expansion) | No global idempotency redesign/migration; regressions passed. |
| M-06 | **PARTIALLY RESOLVED / PARTIALLY VERIFIED** | Additive canonical-body integrity primitives and tests added; full evidence/persistence integrity hardening and migrations incomplete. |
| M-08 | **PARTIALLY RESOLVED** | No full contract migration; prior boundaries preserved. |
| RR-04 | **PARTIALLY RESOLVED** | Preserved; no full constraints/migration completion. |
| RR-05 | **OPEN / PARTIALLY ADDRESSED** | Reconciliation not fully hardened for canonical persisted bodies. |
| RR-06 | **PARTIALLY RESOLVED** | Trusted read-back recomputes/verifies digests in implemented paths; DB-level canonical digest constraints/migrations incomplete. |
| N-04 | **PARTIALLY RESOLVED** | Reconfirmed fail-closed; not verified closed. |
| T-11/T-13/T-27 | **OPEN — ACCEPTANCE REQUIRED** | Unchanged. |

---

## 16. Exact test commands and results

Environment: `E:\Flag-hunt\ctf-platform-be`, `.\venv\Scripts\python.exe` (Windows). Warnings: `PytestDeprecationWarning` (asyncio_default_fixture_loop_scope unset), `PydanticDeprecatedSince20`.

| Exact command | Collected | Passed | Failed | Skipped | Warnings | Exit code | Duration |
|---|---:|---:|---:|---:|---:|---:|---|
| `.\venv\Scripts\python.exe -m py_compile broker/firewall_controller_service/ownership_store.py broker/firewall_controller_service/controller_service.py` | n/a | n/a | 0 | n/a | 0 | 0 | n/a (`PY=0`) |
| `.\venv\Scripts\python.exe -m pytest -q broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py` | 6 | 6 | 0 | 0 | 1 | 0 | 1.95s |
| `.\venv\Scripts\python.exe -m pytest -q broker/tests/test_firewall_controller_rule_schema_v1.py broker/tests/test_firewall_controller_rule_lifecycle_2j5.py broker/tests/test_firewall_controller_policy_version_hardening.py broker/tests/test_firewall_controller_active_enforcement.py` | 24 | 24 | 0 | 0 | 1 | 0 | 5.18s |
| `.\venv\Scripts\python.exe -m pytest -q broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py broker/tests/test_firewall_controller_security_remediation.py broker/tests/test_firewall_controller_helper_contract.py` | 124 | 124 | 0 | 0 | 1 | 0 | 35.43s |
| `.\venv\Scripts\python.exe -m pytest -q manager/tests` | 30 | 30 | 0 | 0 | 1 | 0 | 1.85s |
| `.\venv\Scripts\python.exe -m pytest -q broker/tests` | 625 | 625 | 0 | 0 | 1 | 0 | 149.00s (0:02:29) |
| `.\venv\Scripts\python.exe manage.py check` | n/a | n/a | 0 | n/a | n/a | 0 | System check identified no issues (0 silenced) |

**Not executed:** live Docker/host/firewall tests. Full monorepo/frontend suites not separately enumerated beyond executed backend/pytest targets. Migration fault-injection matrix not executed (no migration framework/scripts added).

---

## 17. Independent verification

- Reopened/inspected 2J.6-modified source/tests: `ownership_store.py` (additive table + store/read-back APIs), `controller_service.py` (install-path canonical body persistence hook), `test_firewall_controller_canonical_policy_persistence_2j6.py`.
- **Valid trace:** schema-v1 install persists canonical body; `read_trusted_canonical_policy_body` returns normalized rules and matching recomputed digest.
- **Invalid/corrupt traces:** write-time digest mismatch rejected; read-back fails closed on corrupt JSON, tampered stored digest, owner/ownership-record mismatch, expected compiled-digest mismatch, unsupported schema version.
- **Compatibility:** legacy install without rules succeeds and creates no canonical body.
- **Regressions:** focused suites, full `broker/tests`/`manager/tests`, and `manage.py check` passed.
- **Limitations confirmed:** no full inspect/verify/reconcile integration, no legacy adapters/migrations/conversion, incomplete adversarial matrix.
- See `docs/PHASE_2L_2J_6_INDEPENDENT_VERIFICATION.md`.

---

## 18. Docker authority verification

- No operational Docker authority introduced. Existing broker/manager adapters remain fail-closed/unavailable in covered behavior (passing manager/broker suites and prior N-04 tests).
- **N-04:** **PARTIALLY RESOLVED** (not verified closed; no host/runtime proof).

---

## 19. Git integrity

- **Root:** `E:/Flag-hunt/ctf-platform-be` | **Branch:** `main...origin/main` | **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`
- `git status --short --branch` unchanged in pre-existing baseline; 26 pre-existing modified tracked files and pre-existing untracked set preserved.
- **2J.6 changes:** `broker/firewall_controller_service/ownership_store.py`, `broker/firewall_controller_service/controller_service.py`, `broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py`, `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md`, `docs/PHASE_2L_2J_6_ENGINEERING_REMEDIATION_REPORT.md`, `docs/PHASE_2L_2J_6_INDEPENDENT_VERIFICATION.md`.
- No reset, clean, checkout, revert, staging, or commit performed. No unrelated user work overwritten.

---

## 20. Remaining limitations

1. Trusted canonical read-back not yet integrated into all inspection/verification/reconciliation/service read/response paths.
2. Legacy/canonical adapter strategy incomplete; broker legacy firewall compiler/state model not migrated to schema-v1 and not explicitly adapted with full rejection/conversion matrix.
3. No formal migrations/migration safety tests (beyond additive schema init) or legacy-record conversion/quarantine handling.
4. Comprehensive adversarial/fault-injection coverage (transaction rollback/partial/interrupted writes, unauthorized read-back boundaries, cross-owner service isolation for canonical bodies, reconciliation/verification corrupt-record matrices) incomplete.
5. I-07/M-01/RR-01–RR-04, M-06 (full), RR-05, I-08/RR-07, I-09, and full 2L.2I.2 envelope/SCHEMA-01–05 workstreams remain open/partial.
6. HV-EC-01–HV-EC-20 unverified; M-09 open. T-11/T-13/T-27 **OPEN — ACCEPTANCE REQUIRED**.

---

## 21. What is ready for Phase 2L.2J.7

- **Ready (mock-only, evidenced):** additive controller-store canonical schema-v1 policy-body persistence and trusted read-back primitives, install-path persistence hook for schema-v1 rules, 6 new passing persistence/read-back tests, full broker/manager regression stability, and `manage.py check` pass.
- **Next targets:** wire trusted read-back into inspection/verification/reconciliation/read-back responses with bounded fail-closed behavior; define/implement explicit legacy adapters or explicit rejection/quarantine for non-canonical records; add safe migrations and fault-injection/adversarial tests; complete remaining N-02/M-06/RR-05/RR-06 evidence; continue I-07/I-08/I-09/M-01 work under mock-only boundary.

**Mandatory final status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
