# Post-J.20 Stage 1B.18 — Independent Security Review (Mock-Only, Review-Only)

**Mandatory status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED

**T-11 / T-13 / T-27:** OPEN — ACCEPTANCE REQUIRED

## 1. Purpose and boundary

Stage 1B.18 independently reassessed the Stage 1B.17 mock-only remediation after Stage 1B.16. This milestone was strictly review-only:

- no application source or test modification;
- no test execution (no material evidence question required a rerun);
- no Docker daemon/socket, UDS/SO_PEERCRED, kernel identity, privileged helper, Linux capability, nftables/iptables/DOCKER-USER, host firewall, host-permission, cloud, production, live-backend or Stage 1C work;
- no gate closure, risk acceptance, approval, signature, date or authority decision created or changed.

Formal authority submission readiness is not live-integration authorization.

## 2. Repository and evidence baseline (before review)

| Item | Value |
|---|---|
| HEAD | `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` |
| Branch | `main` |
| Modified tracked files | 26 |
| Staged files | 0 |
| Untracked entries (porcelain collapsed) | 281 |
| Untracked files (expanded) | 718 |

Existing user work was preserved unchanged. The 281 collapsed / 718 expanded counts are the values observed at Stage 1B.18 baseline; they differ from the 281 / 716 values recorded in the Stage 1B.17 final report, which is itself recorded as an evidence-hygiene discrepancy in `POST_J20_STAGE_1B_18_EVIDENCE_INTEGRITY_REPORT.md`.

## 3. Method

The review did not rely on completion summaries. It inspected:

- actual source in `broker/app/auth.py`, `broker/firewall_controller_service/authorization.py`, `authorization_strict.py`, `controller_service.py`, `rule_schema_v1.py`, `ownership_store.py`, `mock_helper_executor.py`, `helper_contract.py`, `error_sanitization.py` and related modules;
- the Stage 1B.17 regression suite `broker/tests/test_post_j20_stage_1b17_remediation.py` and relevant legacy suites;
- all raw artifacts in `docs/evidence/post_j20_stage_1b17/`;
- Stage 1B.13–1B.17 implementation/evidence/review/residual documents;
- `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md`;
- `docs/POST_J20_STAGE_1B_10_AUTHORITY_DECISION_TRACKER.md`, `docs/POST_J20_STAGE_1B_11_AUTHORITY_RESPONSE_INTAKE.md` and the decision reconciliation matrix;
- Stage 1B.15/1B.16 residual and readiness records.

No fresh tests were executed. All test results cited below are Stage 1B.17 raw-artifact results, explicitly identified as such.

## 4. Overall outcome

**Outcome B — NOT READY — ADDITIONAL MOCK-ONLY REMEDIATION REQUIRED.**

Stage 1B.17 corrected several concrete defects, but the independent review did not find all R16 corrections complete. Material mock-only technical defects remain, and several evidence-narrative claims are broader than the raw artifacts support. Presenting the package to authority as conditionally ready would require an authority to accept known, source-proven, mock-only-remediable defects.

The smallest justified next remediation scope is listed in §9.

## 5. R16 disposition summary

| Finding | Independent classification | Core reason |
|---|---|---|
| R16-01 | VERIFIED FIXED (scoped) | Trusted attached peer identity now wins over headers; edge cases fail closed. Benefit is unrealized in current runtime because no production credential attached exists. |
| R16-02 | PARTIALLY MITIGATED | The three named promotions are guarded, but other `reconciled` outcomes write no status, a conditional `status_written` path is unsafe, and the promotion/status boundary is not atomic or documented. |
| R16-03 | OPEN | No persisted ownership CIDR source and no production caller passes `ownership_rec`; the new check is dead code at covered ingresses. |
| R16-04 | PARTIALLY MITIGATED | The schema-level rules-only-digest alias is removed, but the field is optional and rules-only digest aliases remain in controller/ownership-store bindings. |
| R16-05 | PARTIALLY MITIGATED | Original `controller_verified` suppression is removed, but rejection uses `is True` only and several forbidden claim fields are not rejected. No current escalation was found. |
| R16-06 | PARTIALLY MITIGATED | `p1`/`p10` prefix collision is fixed; the helper is not exact by `policy_id:policy_version` for colon IDs, version overlap or missing resource keys. |
| R16-07 | PARTIALLY MITIGATED | Execution-exception disclosure is fixed; helper validation errors still return internal schema text and controller `result`/`details` are not scrubbed. |
| R16-08 | VERIFIED DOCUMENTATION / OPEN BY DESIGN | Absence of production UDS/controller/authorizer wiring is accurately documented. No production wiring was added and none is authorized. |
| R16-09 | VERIFIED FIXED (scoped) | Reported representation-dependent mirror bypasses are closed with bounded scans; no-rules representation split and payload-size considerations remain as documented limitations. |
| R16-10 | IMPROVED, NOT CLOSED | Stage 1B.17 raw run artifacts are complete, but narrative explanations, stream attribution, metadata labels and count interpretation contain inaccuracies; historical gaps remain. |

Full evidence and line references are in `POST_J20_STAGE_1B_18_R16_VERIFICATION_MATRIX.md`.

## 6. Independently verified security properties

The following properties were confirmed from source and/or raw artifacts, within the mock-only boundary:

1. When `request.state.peer_credentials` is attached, `require_broker_auth()` uses only that trusted identity; conflicting header fields are ignored and audited by field name (`broker/app/auth.py:34-49`).
2. Malformed peer headers and empty/malformed trusted identities fail closed to 401 in the inspected broker path (`auth.py:22-32`, `broker/app/authorization.py:23-24`).
3. The three reconciliation promotions originally named in R16-02 use guarded status writes with explicit allowed states, identity revalidation, lifecycle-version CAS and status+audit atomicity (`controller_service.py:1690-1739`, `:1925-1927`, `:1958-1960`, `:1986-1998`, `:2084-2092`, `:2188-2190`).
4. Unsupported heuristic CIDR ownership claims are rejected when an ownership record is explicitly supplied, and explicit `owned_network_cidrs` are parsed with `strict=True` and version-matched `subnet_of` checks (`rule_schema_v1.py:439-478`).
5. A supplied `canonical_policy_digest` is no longer accepted if it equals a rules-only compiled digest (`rule_schema_v1.py:491-511`).
6. Strict trusted-flag rejection no longer depends on `controller_verified` (`authorization_strict.py:20-25`; `authorization.py:17-20`).
7. Invalid `p1`/`p10` prefix attribution in the pending ledger is corrected for simple identifiers (`controller_service.py:32-44`, `:2233-2234`).
8. Generic helper execution exceptions no longer disclose raw `str(e)` outward; only a bounded fixed message is returned and the exception class name is retained internally (`mock_helper_executor.py:145-152`).
9. Non-empty compiled mirrors are validated, legacy flat-rule markers are detected at depth beyond the old bound with a 10,000-node budget, and mixed representations are rejected (`rule_schema_v1.py:331-427`).
10. Stage 1B.17 raw evidence preserves all 12 claimed runs with stdout, stderr, exit and meta artifacts; initial failures and corrective reruns are distinguishable and no failed run is reported as passing.
11. No named authority response exists for T-11, T-13, T-27, SR-10, SR-06 or I-09; all remain PENDING with `[NOT RECORDED]` response fields.
12. No gate status, acceptance state or risk disposition was changed by Stage 1B.17 or Stage 1B.18.

## 7. Cross-stage regression challenge

The twelve required security domains were reassessed:

| Domain | Result |
|---|---|
| Authentication and authorization | Header precedence fixed, but unattached trusted-peer seam leaves header-only identity as runtime default; R16-05 invariant incomplete. |
| Canonical validation and legacy separation | R16-09 fixed; canonical digest binding remains partially aliased in persistence/ownership paths (R16-04). |
| Error classification and information leakage | R16-07 execution path fixed; helper validation/result-details paths remain incompletely bounded. |
| Ownership and policy binding | R16-03 remains open at ingress; canonical ownership digest still aliases compiled rule digest. |
| Persistence and integrity | Earlier tamper-detected-but-mutable body store, missing DB FKs and global FK-pragma limitation remain accurate. |
| Lifecycle transitions and reconciliation | R16-02 partial; cross-transaction promotion/status window and no-status success outcomes remain. |
| Idempotency and concurrency | CAS guards and replay binding remain intact; reconciliation ledger attribution is not exact (R16-06). |
| Crash recovery and uncertain outcomes | Prior bounded controls preserved; no end-to-end DB/backend atomicity; promotion/status transaction boundary gap newly confirmed. |
| Append-only evidence and audit | Status+audit atomicity inside the guarded writer verified; policy body store remains mutable and tamper-detected, not append-only. |
| Migration and database integrity | Migration authority, deployed-schema closure and no-backfill additive columns remain unresolved. |
| Manager/broker/controller trust boundaries | Controller/authorizer are library/mock-only; no production ingress wiring exists (R16-08). |
| Deployment and host-security limitations | T-11/T-13/T-27 and all host/runtime evidence requirements remain open; no live validation performed or implied. |

## 8. Stage 1B.15 residuals and earlier findings

All seven Stage 1B.15 residuals were re-challenged against current source and remain accurate: mutable but tamper-detected `controller_policy_bodies` (`ownership_store.py:223-256`); absent DB-level FKs on lifecycle/history/idempotency/evidence tables (`:155-186`); no global FK enforcement in `BrokerDB._get_conn()` (`broker/app/db.py:50-56`); legacy failed-read fail-open (`broker/app/firewall_state.py:48-55`); no end-to-end DB/backend atomicity; migration authority/deployed-schema closure; and T-11/T-13/T-27/SR-10/SR-06/I-09 without authority decisions.

Earlier SR/RR/M/I/H/N classifications remain accurate except where Stage 1B.17 explicitly changed covered-path evidence. No residual was closed on the basis of a completion summary alone. In particular:

- SR-09 remains scoped-fixed, but R16-02 missing/conditional status writes are a separate partially mitigated finding;
- RR-07 remains partially mitigated: one concrete leak was fixed, but universal leakage-negative proof is absent;
- I-07/I-08 remain partially resolved for the same reason;
- SR-10, SR-06, I-09, T-11, T-13 and T-27 remain authority-pending.

## 9. Smallest necessary remediation scope for a future milestone

No implementation was performed in Stage 1B.18. If a further bounded mock-only milestone is authorized, the smallest justified scope is:

1. **R16-03:** either pass a proven authoritative ownership scope into every covered ingress or remove/relocate the dead scope primitive with explicit documentation; add ingress-level negative tests for out-of-scope CIDRs. Do not treat a caller-supplied scope as authoritative.
2. **R16-04:** remove the compiled-digest-as-canonical alias from controller/ownership-store canonical binding paths and require an explicit complete canonical digest where canonical binding is claimed; preserve only explicitly legacy-labelled compatibility paths.
3. **R16-02:** initialize/scope `status_written` safely; add guarded status writes to `reconciled` outcomes that currently write none; document or close the cross-transaction promotion/status window.
4. **R16-06:** compare the full `policy_id:policy_version` identity exactly (or use `ownership_record_id` where available); restore/replace the removed full-scan attribution test.
5. **R16-07 and R16-05:** route helper validation errors through the bounded sanitizer and reject all forbidden auth claim fields with non-`True` truthy values, including `controller_verified`, `authorized` and `is_admin`.
6. **Evidence narrative hygiene:** correct the unsupported R16-04 causal claim, Django stream attribution, git count labels, `STARTED=` metadata semantics and Stage 1B.17 overstatements without rewriting raw artifacts.

R16-08, host/live evidence, authority acceptances and end-to-end atomicity are outside a mock-only correction scope and must not be represented as fixable by this work.

## 10. Repository preservation

Baseline and final state are recorded in `POST_J20_STAGE_1B_18_FINAL_VERIFICATION_REPORT.md`. This milestone created only the six Stage 1B.18 documents and one evidence-reference note in the gate register. No application source, test, raw evidence, authority record or existing user work was modified, reset, cleaned, reverted, staged or committed.

## 11. Final decision

- Formal authority submission readiness: **NO** — material mock-only defects remain.
- Further mock-only implementation necessary: **YES**, limited to §9.
- Gate closure / risk acceptance / live authorization: **NONE**.

Final status: **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
