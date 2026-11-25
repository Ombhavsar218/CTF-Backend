# Phase 2L.2J.6 — Independent Verification (Mock-Only)
## Canonical Policy Persistence, Legacy Adapter and Read-Back Integrity

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Phase:** 2L.2J.6 Independent Verification  
**Date:** 2026-11-15  
**Scope:** Post-implementation re-inspection of 2J.6 source/tests/docs, persistence/read-back evidence, regression/Django-check results, N-04 reconfirmation, and git integrity within mock-only boundary.  
**Authorization boundary:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

This verification is based on local source inspection and executed test evidence only. It does **not** constitute host, transport, kernel, runtime, firewall-backend, or production security proof.

---

## 1. Initial repository/Git baseline

- **Root:** `E:/Flag-hunt/ctf-platform-be` (`git rev-parse --show-toplevel`)
- **Branch:** `main...origin/main`
- **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` (`b365584 New: Challenges backend`)
- **`git diff --stat` (pre-existing tracked):** 26 files changed, 2540 insertions(+), 80 deletions(-)
- **Pre-existing modified tracked (26, preserved):** `.env.example`, `.gitignore`, `README.md`, `achievements/views.py`, `announcements/views.py`, `challenges/admin_urls.py`, `challenges/models.py`, `challenges/serializers.py`, `challenges/tests.py`, `challenges/urls.py`, `challenges/views.py`, `config/__init__.py`, `config/settings.py`, `config/urls.py`, `requirements.txt`, `submissions/serializers.py`, `submissions/stats.py`, `submissions/tests.py`, `submissions/urls.py`, `submissions/views.py`, `users/admin_views.py`, `users/management/commands/setup_groups.py`, `users/tests.py`, `users/throttling.py`, `users/urls.py`, `users/views.py`
- **Pre-existing untracked:** preserved (including `broker/`, `manager*`, `docs/`, debug/fix/out artifacts, deployment/config additions, zips, etc.). No reset/clean/checkout/revert/staging/commit.

---

## 2. Files independently reopened

### 2J.6 source
- `ctf-platform-be/broker/firewall_controller_service/ownership_store.py`
  - Additive `controller_policy_bodies` table (ownership/policy/version binding, `schema_version`, canonical rules JSON, required families, compiled/canonical digests, metadata, FK/indexes) and `PRAGMA foreign_keys=ON`.
  - `store_canonical_policy_body`: validates/normalizes via shared `rule_schema_v1`, recomputes digest, verifies ownership existence/binding/digest consistency, transactional insert, fail-closed.
  - `ensure_canonical_policy_body`: idempotent only when existing record validates/matches.
  - `get_canonical_policy_body` and `read_trusted_canonical_policy_body`: trusted read-back revalidates schema version/JSON/rules, recomputes compiled digest, checks stored/ownership/expected digests and owner/ownership-record bindings; fails closed on corruption/mismatch.
- `ctf-platform-be/broker/firewall_controller_service/controller_service.py`
  - `_ensure_canonical_policy_body_persisted` invoked for `install_policy` before backend dispatch when `req['rules']` present; no-op for legacy installs without rules.

### 2J.6 tests
- `ctf-platform-be/broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py` (6 tests): install persistence + trusted read-back success; write-time digest mismatch rejection; corrupt JSON and tampered digest read-back failure; owner/ownership-record/expected-compiled-digest mismatch failure; unsupported schema-version failure; legacy no-rules install compatibility.

### Preserved/reconfirmed
- 2J.3–2J.5 schema/contract/policy-version/mock-boundary/lifecycle hardening behavior preserved by passing regressions.
- Broker/manager Docker adapters remain fail-closed/unavailable in covered tests (N-04 not closed).

### Documentation
- `ctf-platform-be/docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` (2J.6 evidence/status notes).
- `ctf-platform-be/docs/PHASE_2L_2J_6_ENGINEERING_REMEDIATION_REPORT.md`.

---

## 3. Actual code paths inspected

1. **Canonical body persistence (store):** write validates schema-v1 rules and digests against ownership, inserts into `controller_policy_bodies` in a transaction.
2. **Install integration (controller service):** schema-v1 install requests persist/ensure canonical body after ownership resolution/binding and before backend dispatch.
3. **Trusted read-back (store):** loads ownership + body, validates bindings/schema/JSON/rules, recomputes compiled digest, enforces digest/owner/version-related expectations, returns normalized body info.

**Not fully integrated/verified:** trusted read-back use in all inspection/verification/reconciliation/service read/response paths; legacy firewall compiler/state canonical adapters/migrations; full fault-injection and adversarial matrices.

---

## 4. Valid request trace (mock-only)

1. Schema-v1 install request (`rules` present) processed by `FirewallControllerService.install_policy`.
2. Controller normalizes/validates rules and binds digests (prior phases) and persists canonical body via store before backend dispatch.
3. `ControllerOwnershipStore.read_trusted_canonical_policy_body(policy_id, policy_version)` returns ownership + normalized canonical rules, `schema_version='rule-schema-v1'`, and recomputed `compiled_rule_digest` matching stored value.

**Result:** Implemented and tested.

---

## 5. Invalid/corrupt request and read-back traces (mock-only)

1. **Write-time digest mismatch:** `store_canonical_policy_body` rejects mismatched `compiled_rule_digest` (`BrokerDBError`).
2. **Corrupt JSON:** tampered `canonical_rules_json` causes trusted read-back to fail closed (`BrokerDBError`).
3. **Tampered stored digest:** trusted read-back recomputes digest and rejects mismatch (`BrokerDBError`).
4. **Binding mismatches:** expected owner, ownership-record id, and compiled-digest mismatches rejected by trusted read-back (`BrokerDBError`).
5. **Unsupported schema version:** tampered `schema_version` rejected (`BrokerDBError`).
6. **Legacy compatibility:** install without `rules` succeeds and no canonical body record is required/created.

**Result:** Implemented and tested for covered store/read-back paths.

---

## 6. Persistence/read-back, inspection/verification, reconciliation verification

| Area | Status | Evidence |
|---|---|---|
| Canonical policy-body persistence (controller store) | **Implemented and tested (partial)** | Additive table + install-path persistence + 2J.6 tests pass. |
| Trusted read-back integrity | **Implemented and tested (partial)** | Schema/JSON/rule revalidation, recomputed digest, binding checks, fail-closed cases pass. |
| Inspection using trusted canonical read-back | **Not implemented (full integration)** | No end-to-end wiring verified across inspection service paths. |
| Verification using trusted canonical read-back | **Not implemented (full integration)** | No end-to-end wiring verified across verification service paths. |
| Recovery/reconciliation fail-closed on corrupt canonical bodies | **Partially verified (regressions only)** | Existing suites pass; canonical-body-specific reconciliation integration/matrix not implemented. |
| Legacy adapter/migration safety | **Not implemented** | No explicit adapters/conversion/migration matrix added. |

---

## 7. Negative/adversarial test evidence

- **New 2J.6:** `broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py` — **6 passed**.
- **Focused regressions:** schema/lifecycle/policy-version/active (24 passed), revoke/idempotency/security/helper (124 passed).
- **Full suites:** `manager/tests` **30 passed, 1 warning**; `broker/tests` **625 passed, 1 warning**.
- **Backend check:** `.\venv\Scripts\python.exe manage.py check` — **0 issues**.
- **Not executed/implemented:** requested full adversarial matrix (transaction rollback/partial/interrupted writes, unauthorized service-boundary read-back, full inspection/verification/reconciliation canonical-corruption/cross-owner isolation, legacy conversion/ambiguous-record handling, migration failure/rollback/repeated migration), live Docker/host/firewall tests.

---

## 8. Docker authority verification

- No operational Docker authority, socket access, or fallback introduced.
- Existing fail-closed broker/manager adapter behavior preserved (manager/broker suites passed).
- **N-04:** **PARTIALLY RESOLVED** (not verified closed; host/runtime proof absent).

---

## 9. Git integrity

- **Root/branch/HEAD:** `E:/Flag-hunt/ctf-platform-be`, `main...origin/main`, `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`.
- **Pre-existing modified tracked (26):** preserved (unchanged baseline).
- **Pre-existing untracked:** preserved.
- **2J.6 delta:** `broker/firewall_controller_service/ownership_store.py`, `broker/firewall_controller_service/controller_service.py`, `broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py`, `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md`, `docs/PHASE_2L_2J_6_ENGINEERING_REMEDIATION_REPORT.md`, `docs/PHASE_2L_2J_6_INDEPENDENT_VERIFICATION.md`.
- No reset, clean, checkout, revert, staging, or commit performed.

---

## 10. Gate/finding assessment (independent)

| ID | Status | Classification |
|---|---|---|
| N-02 | **PARTIALLY IMPLEMENTED** | Durable canonical body persistence + trusted read-back primitives implemented/tested; end-to-end lifecycle/integration/adapters/migrations incomplete. |
| N-03 | **PARTIALLY RESOLVED** | Evidence updated; underlying gaps remain. |
| H-05 | **PARTIALLY RESOLVED** | Full 2L.2I.2/rule-schema migration incomplete. |
| M-01 | **PARTIALLY VERIFIED** | No global redesign/migration in 2J.6; regressions passed. |
| M-06 | **PARTIALLY RESOLVED / PARTIALLY VERIFIED** | Integrity primitives added; full hardening/migrations incomplete. |
| M-08 | **PARTIALLY RESOLVED** | Contract migration incomplete. |
| RR-04 | **PARTIALLY RESOLVED** | Preserved; constraints/migration incomplete. |
| RR-05 | **OPEN / PARTIALLY ADDRESSED** | Reconciliation integration for canonical bodies incomplete. |
| RR-06 | **PARTIALLY RESOLVED** | Read-back recomputation/verification in implemented paths; DB constraints/migrations incomplete. |
| N-04 | **PARTIALLY RESOLVED** | Fail-closed reconfirmed; not closed. |
| T-11/T-13/T-27 | **OPEN — ACCEPTANCE REQUIRED** | Unchanged. |
| HV-EC-01–HV-EC-20 / M-09 | **NOT READY / OPEN** | Host-dependent, unverified. |

---

## 11. Exact test commands and results

| Exact command | Collected | Passed | Failed | Skipped | Warnings | Exit code | Duration/notes |
|---|---:|---:|---:|---:|---:|---:|---|
| `.\venv\Scripts\python.exe -m py_compile broker/firewall_controller_service/ownership_store.py broker/firewall_controller_service/controller_service.py` | n/a | n/a | 0 | n/a | 0 | 0 | `PY=0` |
| `.\venv\Scripts\python.exe -m pytest -q broker/tests/test_firewall_controller_canonical_policy_persistence_2j6.py` | 6 | 6 | 0 | 0 | 1 | 0 | 1.95s |
| `.\venv\Scripts\python.exe -m pytest -q broker/tests/test_firewall_controller_rule_schema_v1.py broker/tests/test_firewall_controller_rule_lifecycle_2j5.py broker/tests/test_firewall_controller_policy_version_hardening.py broker/tests/test_firewall_controller_active_enforcement.py` | 24 | 24 | 0 | 0 | 1 | 0 | 5.18s |
| `.\venv\Scripts\python.exe -m pytest -q broker/tests/test_firewall_controller_revoke_recovery_and_idempotency_hardening.py broker/tests/test_firewall_controller_security_remediation.py broker/tests/test_firewall_controller_helper_contract.py` | 124 | 124 | 0 | 0 | 1 | 0 | 35.43s |
| `.\venv\Scripts\python.exe -m pytest -q manager/tests` | 30 | 30 | 0 | 0 | 1 | 0 | 1.85s |
| `.\venv\Scripts\python.exe -m pytest -q broker/tests` | 625 | 625 | 0 | 0 | 1 | 0 | 149.00s (0:02:29) |
| `.\venv\Scripts\python.exe manage.py check` | n/a | n/a | 0 | n/a | n/a | 0 | 0 silenced issues |

---

## 12. Final disposition

Phase 2L.2J.6 is **CONDITIONAL / PARTIALLY COMPLETE** (mock-only). Durable canonical schema-v1 policy-body persistence primitives, install-path persistence, trusted read-back validation, and targeted tests were implemented and all executed regressions plus `manage.py check` passed. Full 2J.6 objectives (inspection/verification/reconciliation integration, legacy adapters/migrations, complete adversarial/fault-injection coverage, N-02 end-to-end closure) remain incomplete.

**Host-validation readiness:** NOT READY  
**Mandatory final status:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
