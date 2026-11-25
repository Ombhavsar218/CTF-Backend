# Post-J.20 Stage 1B.18 — Final Residual Risk Register (Review-Only)

**Mandatory status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED

**T-11 / T-13 / T-27:** OPEN — ACCEPTANCE REQUIRED

This register records independent dispositions. It does not close, accept, downgrade or upgrade any risk. No named authority, approval date, signature or acceptance decision was created or changed.

## 1. Material mock-only technical residuals

| ID | Residual | Evidence | Disposition | Why it blocks Outcome A |
|---|---|---|---|---|
| R16-03 | Ownership CIDR scope enforcement remains inoperative at every production/mock ingress | `rule_schema_v1.py:443-478` conditional on caller-supplied `ownership_rec`; callers `controller_service.py:928`, `helper_contract.py:241`, `app/firewall_controller.py:78` omit it; no CIDR column in `ownership_store.py:135-152` | OPEN | Concrete source-proven defect identified in Stage 1B.16 remains unfixed at system level. |
| R16-02 | Reconciliation success/status consistency incomplete | `controller_service.py:2060-2065`, `:2123-2124`, `:2209-2211` (no status write); `:2030-2047` (conditional `status_written`); separate transaction groups | PARTIALLY MITIGATED | Broader status consistency claim is false; false-success and stale-status constructions remain. |
| R16-04 | Rules-only compiled digest still aliases canonical binding in controller/ownership-store paths | `controller_service.py:418,490,552,1161`; `ownership_store.py:779-785,921-925`; `helper_contract.py:206-207` | PARTIALLY MITIGATED | Metadata/identity binding can be bypassed by omitting the optional canonical digest. |
| R16-06 | Pending-ledger identity filter is not exact by `policy_id:policy_version` | `controller_service.py:32-44`, `:2233-2234`; `_ID_RE` at `:68`; exact replay comparator at `:590` | PARTIALLY MITIGATED | Misattribution remains for version overlaps, colon IDs and missing resource keys; full-scan test removed. |
| R16-07 | Validation/helper error text is not universally bounded | `mock_helper_executor.py:99-103`; `helper_contract.py:242-245`; `controller_service.py:281-304,729-741` | PARTIALLY MITIGATED | Internal schema/exception messages can escape at helper boundary; controller nested fields unscrubbed. |
| R16-05 | Trusted-flag rejection invariant incomplete | `authorization_strict.py:23-25`; `authorization.py:17-20`; `helper_contract.py:74-78` | PARTIALLY MITIGATED | Truthy non-booleans and several forbidden claim fields are accepted; no current escalation but future consumer risk. |
| R16-01 runtime benefit | Trusted-credential precedence is correct but no production credential is attached | `auth.py:34-51`; no non-test assignment to `peer_credentials`; `main.py`/`routes.py` | LIMITATION OF VERIFIED FIX | Header-only mock seam remains runtime default until R16-08 is authorized. |
| R16-09 boundary split | No-rules path skips compiled mirror validation; payload bytes unbounded | `rule_schema_v1.py:331-369`, `:428-434`; `request_validator.py` | SCOPED LIMITATION | Not the reported bypass; recorded to prevent overclaiming universal representation closure. |

## 2. Evidence governance residuals

| ID | Residual | Disposition |
|---|---|---|
| R16-10 | Stage 1B.17 run-level artifacts complete; narrative causal claim, Django stream attribution, git count labels, `STARTED=` semantics and completion wording inaccurate | IMPROVED, NOT CLOSED |
| E-1 | Full-scan R16-06 test failed in `corrective_new_suite_2` and is absent from final suite | OPEN (coverage gap) |
| E-2 | Historical Stage 1B.13–1B.15 evidence gaps remain (no stderr for some runs, no exit codes for j17/j18/j19, reported-only counts 218/J.18 16/J.19 28, no authored final hash snapshot, truncated 1A1/1A2/j17 stdout, FK-pragma expectation conflict) | UNCHANGED / UNRESOLVED |
| E-3 | Stage 1B.17 residual/final/gate wording overstates R16-02/R16-03/R16-04/R16-06/R16-07 closure | DOCUMENTATION DEFECT |

## 3. Stage 1B.15 residuals re-challenged

| # | Residual | Independent check | Status |
|---:|---|---|---|
| 1 | `controller_policy_bodies` mutable, tamper-detected not append-only | `ownership_store.py:223-240` has one FK and no update/delete trigger; trigger loop at `:244-256` covers lifecycle history, evidence and audit only | ACCURATE / UNCHANGED |
| 2 | Missing DB-level FK bindings where previously identified | `ownership_store.py:155-186` DDL for lifecycle history and idempotency has no `REFERENCES`; evidence/audit similarly not bound | ACCURATE / UNCHANGED |
| 3 | Global foreign-key enforcement limitation | `broker/app/db.py:50-56` does not issue `PRAGMA foreign_keys=ON`; controller-scoped enforcement exists but is not global | ACCURATE / UNCHANGED |
| 4 | Legacy state-store failed-read fail-open | `broker/app/firewall_state.py:48-55` converts storage failure to `None`; no non-test production caller found | ACCURATE / UNCHANGED |
| 5 | No end-to-end DB/backend atomicity | `ownership_store.py:301-302` explicitly limits `atomic_write()` to DB-only; SR-10 PENDING | ACCURATE / UNCHANGED |
| 6 | Migration authority and deployed-schema closure | additive ALTER TABLE without authoritative plan/backfill/schema-version closure (`ownership_store.py:188-194`; `db.py:249`) | ACCURATE / UNCHANGED |
| 7 | T-11/T-13/T-27/SR-10/SR-06/I-09 unresolved | tracker/intake/reconciliation matrix all PENDING with `[NOT RECORDED]` responses | ACCURATE / UNCHANGED |

None of these residuals was closed by Stage 1B.17 evidence.

## 4. Earlier finding dispositions

- SR-01–SR-04, SR-07–SR-09: remain at their Stage 1B.16 classifications; SR-09’s scoped fix does not cover R16-02 missing/conditional status writes.
- SR-05, SR-06, SR-13, SR-14, RR-01–RR-06, M-01, M-03, M-06–M-08, I-07, I-08, H-02, H-05, N-02, N-04: remain partially mitigated with no new closure evidence.
- RR-07: remains partially mitigated; the concrete helper execution-exception leak was fixed, but universal bounded-error/leakage-negative proof remains absent.
- M-02: remains open; host/transport/privilege environment was not touched.
- M-04/M-05: remain documentation/traceability scope closures only; underlying controls are not closed.
- SR-10, SR-11, SR-12, I-09, T-11, T-13, T-27: remain open/unverified/authority-pending as previously recorded.

## 5. Structural and authority risks

| Item | Current state | Authority response |
|---|---|---|
| T-11 | OPEN — ACCEPTANCE REQUIRED | `[NOT RECORDED]`, PENDING |
| T-13 | OPEN — ACCEPTANCE REQUIRED | `[NOT RECORDED]`, PENDING |
| T-27 | OPEN — ACCEPTANCE REQUIRED | `[NOT RECORDED]`, PENDING |
| SR-10 | Known limitation; no formal disposition | `[NOT RECORDED]`, PENDING |
| SR-06 | Partially mitigated; mock seams not live identity proof | `[NOT RECORDED]`, PENDING |
| I-09 | Open / partially resolved | `[NOT RECORDED]`, PENDING |

No approver, role basis, decision, scope, evidence list, conditions, date, expiry trigger or attestation was found or created.

## 6. Disposition statement

Stage 1B.18 confirms that technical remediation and independent verification are not interchangeable with formal authority review, risk acceptance, host/live operational evidence or live-integration authorization. The remaining mock-only defects are source-proven and bounded; the authority items require named authority action and cannot be closed by further mock-only code.

No risk was accepted by this register.

Final status: **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
