# Post-J.20 Stage 1B.16 — Final Residual Risk Register

**Date:** 2026-11-18
**Type:** Independent, review-only consolidation. No gate status, acceptance state or risk disposition changed.
**Companions:** `POST_J20_STAGE_1B_16_INDEPENDENT_SECURITY_REVIEW.md`, `POST_J20_STAGE_1B_16_EVIDENCE_CHALLENGE_MATRIX.md`

> **MANDATORY STATUS — NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
>
> T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**.

## 1. Status vocabulary applied

Exactly one status is assigned per finding:

| Status | Applied meaning |
|---|---|
| **VERIFIED FIXED** | Scoped source + raw-artifact evidence supports closure of the specific technical finding. Not a gate closure. |
| **PARTIALLY MITIGATED** | Some control/evidence exists; material scope, universal proof, host evidence or acceptance remains. |
| **OPEN — REMEDIATION REQUIRED** | A concrete technical defect or missing control remains and is fixable/verifiable inside the mock-only boundary. |
| **OPEN — ACCEPTANCE REQUIRED** | Technical work may be complete or architecturally bounded; a named authority decision is the outstanding action. |
| **UNVERIFIED — EVIDENCE MISSING** | No raw evidence supports the claim; historical report only. |
| **NOT APPLICABLE** | Explicit reason given; the finding does not apply to the reviewed mock-only scope. |

**Separation of activities (not interchangeable):** technical remediation ≠ independent verification ≠ risk acceptance ≠ formal authority approval ≠ host/live operational evidence. A row below may show a fixed technical finding while its gate remains open, or an accepted-risk item with no live evidence. Fixing code never closes a gate.

## 2. Consolidated risk matrix

### 2.1 SR series (Stage 1B.5 independent review)

| ID | Status | Evidence basis | Remaining limitation / next activity |
|---|---|---|---|
| SR-01 | **VERIFIED FIXED** (informational control set) | Durable intent/idempotency ledger, intent-before-backend, CAS + terminal outcome + `COMPLETED`; 1B.1/1B.4 suites; 1B.15 full suite | Legacy NULL-outcome tolerance and message-string duplicate-create classification documented; not a gate. |
| SR-02 | **VERIFIED FIXED** (informational control set) | Lifecycle FSM, versioned CAS, rollback on conflict (`controller_service.py:59-71,188-192`) | Non-uniform VERIFYING journaling was scoped-resolved in 1B.14 at `:1449-1465` without gate change. |
| SR-03 | **VERIFIED FIXED** (informational control set) | Authority-derived targets, evidence gates, trusted readback, fail-closed uncertainty | Non-converging uncertainty when readback unavailable; mock backend truthfulness unverified. |
| SR-04 | **VERIFIED FIXED** (informational control set) | Completion CAS, reconciliation version guard, canonical UNIQUE winner validation | SR-07/08/09 scoped fixes depended on this; no universal DB constraint. |
| SR-05 | **PARTIALLY MITIGATED** | Ownership/evidence binding and canonical readback (`ownership_store.py:869-938`) | `controller_policy_bodies` detection, not append-only prevention (residue 1). |
| SR-06 | **PARTIALLY MITIGATED** | Strict auth default and J.16 fail-closed construction improvements; `controller_service.py:73-88` | Mock seams/request-dict identity not kernel-authenticated; `authorization.py:5-20`; acceptance **PENDING** (tracker row 30). |
| SR-07 | **VERIFIED FIXED** (scoped) | Typed/targeted `ON CONFLICT` classification (`ownership_store.py:27-33,507-513`); 1B.6 full suite 944 passed | Create-race narrowing documented as unresolved in 1B.14; no security defect evidenced. |
| SR-08 | **VERIFIED FIXED** (scoped) | Canonical pre-read failures propagate as `BrokerDBError` (`controller_service.py:474-498`); 1B.13/1B.14 nested fault test | Legacy fail-open reads (residue 4) are a different library-only subsystem. |
| SR-09 | **VERIFIED FIXED** (scoped) | Uniform allowed-state/identity/CAS reconciliation status fencing (`controller_service.py:1666-1712`) | **Does not cover R16-02** (missing status writes on successful promotions). |
| SR-10 | **OPEN — ACCEPTANCE REQUIRED** | `ownership_store.py:301-302` explicitly DB-only; SR-10 tracker row 29 `[NOT RECORDED]` / PENDING | Architectural limitation; no formal disposition. Not mock-only fixable; authority decision required. |
| SR-11 | **UNVERIFIED — EVIDENCE MISSING** | No live-backend idempotency/readback/failure-semantics evidence | Live contract tests required; cannot be established with mocks. |
| SR-12 | **UNVERIFIED — EVIDENCE MISSING** | No kernel peer identity, UDS lifecycle/permission, mutual transport verification, cross-UID deny, or host firewall evidence | Host/live security boundary evidence required. |
| SR-13 | **PARTIALLY MITIGATED** | Legacy compatibility separation verified in covered paths | Universal migration/quarantine and deployed-envelope closure open (N-02/H-05/M-08). |
| SR-14 | **PARTIALLY MITIGATED** | Documentation-hygiene known limitation; stale 14-vs-16 artifact chronology documented | Stale artifacts preserved by design; no control failure; no gate effect. |

### 2.2 RR series (security gate register §6)

| ID | Status | Evidence basis | Remaining limitation |
|---|---|---|---|
| RR-01 | **PARTIALLY MITIGATED** | J.15/J.16 canonical identifier/no-side-effect coverage in inspected paths | Universal boundary enforcement, aliases, migration and DB constraints incomplete. |
| RR-02 | **PARTIALLY MITIGATED** | Covered-path policy/version/digest/instance/network/family binding | Legacy alias/migration authority (N-02/H-05/SR-13) pending. |
| RR-03 | **PARTIALLY MITIGATED** | Same-key/different-payload rejection, bounded pending classification, terminal CAS, typed conflicts | Global per-receiver scope, migration semantics, extra DB constraints not evidenced. |
| RR-04 | **PARTIALLY MITIGATED** | Bool/negative/type/range checks in covered contract/service paths | Universal DB/app/legacy enforcement unproven. |
| RR-05 | **PARTIALLY MITIGATED** | Trusted readback/fail-closed handling, J.17/J.18 per-policy reconciliation contract | No single atomic unit covers backend effect + durable state/evidence/history + terminal outcome; complete cross-table/orphan inventory open. |
| RR-06 | **PARTIALLY MITIGATED** | J.17 append-only triggers for history/evidence/audit; FK-enforcing controller connections | DB-enforced digest CHECK constraints, migration, full FK/WAL/concurrency stress and complete integrity matrix open. |
| RR-07 | **OPEN — REMEDIATION REQUIRED** | Partial bounded mappings in selected paths; 1B.13 sanitizer (`error_sanitization.py:22-55`) | Universal sanitized error mapper and leakage-negative proof absent; internal raw text at `mock_helper_executor.py:145-147` (R16-07). Fixable in mock-only scope. |

### 2.3 M series (architecture/implementation findings)

| ID | Status | Evidence basis | Remaining limitation |
|---|---|---|---|
| M-01 | **PARTIALLY MITIGATED** | FSM/CAS/version guards; VERIFYING journaling scoped-resolved at `controller_service.py:1449-1465` | Non-uniform transition journaling globally; migration/scope closure open. |
| M-02 | **OPEN — REMEDIATION REQUIRED** | Design complete; implementation/tests open; traceability matrix says `OPEN / BLOCKED` | Host/transport/privilege environment blocked; not mock-only remediable, but remediation (not acceptance) is the action. |
| M-03 | **PARTIALLY MITIGATED** | Documentation corrected; tracking improved | Acceptance/authority tracking open. |
| M-04 | **VERIFIED FIXED** (documentation/traceability scope only) | Register §4 "Documentation-only closed" | Underlying control/test/risk is **not** closed; gate unaffected. |
| M-05 | **VERIFIED FIXED** (documentation/traceability scope only) | Register §4 "Documentation-only closed" | Underlying control/test/risk is **not** closed; gate unaffected. |
| M-06 | **PARTIALLY MITIGATED** | J.6/J.7 canonical persistence/readback; J.17 additive append-only triggers | `controller_policy_bodies` not append-only; no global atomicity; migration/per-family closure open. |
| M-07 | **PARTIALLY MITIGATED** | Code/config logic partially present | No deployment inventory proof; host evidence required. |
| M-08 | **PARTIALLY MITIGATED** | Strict helper contract validation in mock scope | Full envelope/rule-schema-v1/`deadline_ms`/closed ops-errors migration open. |

### 2.4 I / H / N series

| ID | Status | Evidence basis | Remaining limitation |
|---|---|---|---|
| I-07 | **PARTIALLY MITIGATED** | J.15/J.16 covered-boundary canonical digest/request/operation/idempotency/policy-ID checks | Universal entry-point/alias/field closure unproven; reinforced by R16-03/R16-04/R16-09. |
| I-08 | **PARTIALLY MITIGATED** | J.16 error-boundary inventory; 1B.13 bounded mappings | Universal bounded sanitizer and leakage-negative proof absent (RR-07). |
| I-09 | **OPEN — ACCEPTANCE REQUIRED** | Implicit non-strict construction now rejected (`controller_service.py:73-88`) | Mock seam not removed/isolated from all live-capable/import/config paths (R16-08); tracker row 31 PENDING. |
| H-02 | **PARTIALLY MITIGATED** | Fail-closed adapters; J.19 authority matrix and negative tests in mock scope | Deployment/host/runtime evidence and T-27 acceptance absent. |
| H-05 | **PARTIALLY MITIGATED** | Schema-v1 validation in covered paths; J.15 entry-point inventory; 1B.15 boundary verification | Full 2L.2I.2 envelope/legacy removal/migration and universal consistency incomplete. |
| N-02 | **PARTIALLY MITIGATED** | Schema-v1 boundaries, canonical persistence/readback in key paths | End-to-end envelope, legacy migration/adapters/quarantine, universal readback/response authority open. |
| N-04 | **PARTIALLY MITIGATED** | J.19 audited runtime source shows no Docker client/socket/env enablement in inspected paths; adapters fail closed | Packaging-copy/host/runtime evidence and independent closure absent; T-27 OPEN. |

### 2.5 T series (authority-acceptance gates)

| ID | Status | Evidence basis | Remaining limitation |
|---|---|---|---|
| T-11 | **OPEN — ACCEPTANCE REQUIRED** | Tracker row 26 `[NOT RECORDED]` / PENDING; intake found no valid response | No named approver, decision, scope, conditions, date or attestation. No gate closure. |
| T-13 | **OPEN — ACCEPTANCE REQUIRED** | Tracker row 27 `[NOT RECORDED]` / PENDING | No real helper/capability minimization, host-lab evidence or signed acceptance. |
| T-27 | **OPEN — ACCEPTANCE REQUIRED** | Tracker row 28 `[NOT RECORDED]` / PENDING; N-04 only partially resolved | No host/root-equivalent or runtime residual elimination; no formal acceptance. |

### 2.6 New Stage 1B.16 findings

| ID | Status | Evidence basis | Remaining limitation / next activity |
|---|---|---|---|
| R16-01 | **OPEN — REMEDIATION REQUIRED** | `broker/app/auth.py:15-44`, `broker/app/authorization.py:9-54`, `broker/app/routes.py:44-277`; no precedence test | Reverse merge precedence, wire settings, fail closed, add regression test. Mock-only fixable. |
| R16-02 | **OPEN — REMEDIATION REQUIRED** | `controller_service.py:1884-1897,2032-2054,2110-2146` vs guarded writer `:1666-1712` | Add guarded status/audit writes to all three promotions; assert status in tests. Mock-only fixable. |
| R16-03 | **OPEN — REMEDIATION REQUIRED** | `rule_schema_v1.py:425-453`; `controller_service.py:904`; `ownership_store.py:135-152,391-392` | Pass authoritative ownership scope into validation or remove/relocate dead check; add negative test. Mock-only fixable. |
| R16-04 | **OPEN — REMEDIATION REQUIRED** | `rule_schema_v1.py:466-486` | Restrict alias to explicitly legacy-only paths or remove in schema-v1; add digest-binding tests. Mock-only fixable. |
| R16-05 | **OPEN — REMEDIATION REQUIRED** | `authorization_strict.py:20-23`; `mock_transport.py:11-18` | Strip all caller trust flags (including `controller_verified`) at transport before auth. Small mock-only fix. |
| R16-06 | **OPEN — REMEDIATION REQUIRED** | `controller_service.py:2172-2182` vs `:1003-1008` | Use exact `f"{policy_id}:"` prefix or explicit resource-key binding; add collision test. Small mock-only fix. |
| R16-07 | **PARTIALLY MITIGATED** | `mock_helper_executor.py:145-147` internal raw text; outward sanitizer at `controller_service.py:263-287` verified | No outward leak demonstrated; replace raw text with allowlisted message for defense in depth. |
| R16-08 | **UNVERIFIED — EVIDENCE MISSING** | No production wiring of controller/authorizer/UDS found in `broker/app` | Cannot be closed with mock-only tests; requires deployment/topology evidence. Also a design-documentation gap. |
| R16-09 | **PARTIALLY MITIGATED** | `rule_schema_v1.py:31,336-339,371-380` | Legacy-shape and deep-nesting bypasses of mirror/marker validation; scoped compatibility, not a demonstrated exploit. |
| R16-10 | **UNVERIFIED — EVIDENCE MISSING** | Reported-only counts; missing stderr/exit/final-hash artifacts | Add raw artifacts or mark counts explicitly as reported-only in evidence docs. |

### 2.7 Not applicable

| Finding | Status | Justification |
|---|---|---|
| None | **NOT APPLICABLE** | Every requested ID (SR-01–SR-14, RR-01–RR-07, M-01–M-08, I-07/08/09, H-02/H-05, N-02/N-04, T-11/T-13/T-27) was located and assessed against current source/evidence. No ID was discarded as out of scope. |

## 3. Separation of activities — consolidated

| Activity | State after this review |
|---|---|
| Technical remediation | SR-07/08/09 scoped fixes verified; R16-01–R16-06 remain **OPEN — REMEDIATION REQUIRED** inside the mock-only boundary. |
| Independent verification | This review independently inspected source, docs and raw artifacts; **no tests executed**. Raw final full-suite counts (973/984/1005) corroborated from artifacts. |
| Risk acceptance | **Not obtained.** Tracker: 0 accepted, 0 rejected, 0 deferred, 0 mitigate-closed; 6 PENDING. |
| Formal authority approval | **None.** No approver, signature, decision, date or review trigger recorded; none invented by this review. |
| Host/live operational evidence | **Absent.** UDS/`SO_PEERCRED`, kernel identity, privileged helper, host firewall, Docker runtime, live backend and deployment topology not evidenced. |

## 4. Gate integrity statement

- No security gate was verified closed by this review.
- No gate status, acceptance state or existing risk disposition was changed.
- The only permitted register action is a single **evidence-reference note** in `PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` §1.2 pointing to these Stage 1B.16 deliverables; it does not alter any gate row.
- T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**.
- Overall status remains **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
