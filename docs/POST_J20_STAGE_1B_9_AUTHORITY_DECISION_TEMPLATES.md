# Post-J.20 Stage 1B.9 — Authority Decision Templates

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.**

Repository: `E:\Flag-hunt\ctf-platform-be` | HEAD: `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`  
Milestone: Stage 1B.9 (2026-11-17), review-only authority preparation. **This document contains templates only.** No approver name, signature, date, or decision is invented, recorded, or implied. No residual risk is accepted by this document. Mock-only test evidence is **not** host/runtime/live-backend evidence and must not be treated as sufficient for acceptance of host/live risks.

## Completion instructions

- A named authority with the required role and basis must complete each template if a decision is sought.
- Mark each field explicitly; do not leave implicit blanks in a final record.
- Use `ACCEPT`, `REJECT`, `DEFER`, or `MITIGATE-CLOSED` only as defined by the project’s authority plan and only with supporting evidence attached/referenced.
- Any acceptance must be limited to the named residual, scoped environment/phase, and stated compensating controls/review trigger.

## Template A — T-11: Compromised controller residual risk

| Field | Template content |
|---|---|
| **Risk/decision ID** | T-11 — Compromised controller residual risk (OPEN — ACCEPTANCE REQUIRED) |
| **Decision required** | Record one: **ACCEPT residual** (only after documented mitigations and named-authority acceptance), **REJECT**, **DEFER**, or **MITIGATE-CLOSED** (with approved mitigation/removal closure evidence). Decision must not be implied by passing mock tests. |
| **Evidence required** | Threat/mitigation evidence; independent helper audit/read-back design and test evidence; least-privilege and evidence-integrity controls; host isolation/monitoring plan and (where applicable) host evidence; SR-06 live-seam disposition; SR-11/SR-12 prerequisites as applicable; universal validation/sanitization closure evidence relevant to the residual; signed/formal record package. |
| **Responsible authority role** | **Project owner and security authority** for acceptance/rejection/deferral/closure decision. **Controller/security engineering** responsible for mitigation evidence (role input; not approval authority unless separately named and authorized). |
| **Scope and limitations** | Environment/phase: `[NOT RECORDED]`. Systems/components in scope: `[NOT RECORDED]`. Excluded scope (including mock-only boundaries, host/live exclusions): `[NOT RECORDED]`. Duration/effective period: `[NOT RECORDED]`. Statement that mock evidence is not host evidence: `[REQUIRED — explicit text]`. |
| **Compensating controls** | `[NOT RECORDED — list controls, monitoring, isolation, audit/read-back, rollback/containment, operational restrictions]` |
| **Approval/rejection field** | Decision: `[ ] ACCEPT  [ ] REJECT  [ ] DEFER  [ ] MITIGATE-CLOSED`  <br> Named authority (person/role, basis): `[NOT RECORDED]`  <br> Rationale/conditions: `[NOT RECORDED]`  <br> Signature/attestation: `[NOT RECORDED]` |
| **Date and review/expiry trigger** | Decision date/time: `[NOT RECORDED]`  <br> Review/expiry trigger (event, milestone, timebound date, or condition): `[NOT RECORDED]` |

## Template B — T-13: Privileged helper capability residual risk

| Field | Template content |
|---|---|
| **Risk/decision ID** | T-13 — Privileged helper capability residual risk (OPEN — ACCEPTANCE REQUIRED) |
| **Decision required** | Record one: **ACCEPT residual** (only after capability minimization/hardening and named-authority acceptance), **REJECT**, **DEFER**, or **MITIGATE-CLOSED** (capability-surface reduction/removal with host-lab proof). |
| **Evidence required** | Capability/hardening design and tests; fixed operations/no-shell evidence; seccomp/MAC/capability minimization as applicable; helper isolation and read-back truthfulness; host-lab tests and rollback/containment evidence; SR-11 live-backend contract prerequisites as applicable; signed/formal record package. |
| **Responsible authority role** | **Project owner and security authority** for decision. **Helper/platform/security engineering** and **platform/host-operations** for mitigation/host evidence input (not approval authority unless separately named and authorized). |
| **Scope and limitations** | Environment/phase: `[NOT RECORDED]`. Helper/runtime components and capabilities in scope: `[NOT RECORDED]`. Exclusions (host/live not proven, mock-only limits): `[NOT RECORDED]`. Duration: `[NOT RECORDED]`. Mock ≠ host evidence statement: `[REQUIRED — explicit text]`. |
| **Compensating controls** | `[NOT RECORDED — capability bounds, isolation, monitoring, rollback, operational restrictions]` |
| **Approval/rejection field** | Decision: `[ ] ACCEPT  [ ] REJECT  [ ] DEFER  [ ] MITIGATE-CLOSED`  <br> Named authority (person/role, basis): `[NOT RECORDED]`  <br> Rationale/conditions: `[NOT RECORDED]`  <br> Signature/attestation: `[NOT RECORDED]` |
| **Date and review/expiry trigger** | Decision date/time: `[NOT RECORDED]`  <br> Review/expiry trigger: `[NOT RECORDED]` |

## Template C — T-27: Runtime/Docker authority residual risk

| Field | Template content |
|---|---|
| **Risk/decision ID** | T-27 — Runtime/Docker host-root-equivalent residual risk (OPEN — ACCEPTANCE REQUIRED; H-02/N-04 related) |
| **Decision required** | Record one: **ACCEPT residual** if retained (with formal named-authority acceptance), **REJECT**, **DEFER**, or **MITIGATE-CLOSED** (rootful runtime path removed/isolated). Must address H-02/N-04. J.19 mock-only audit is **not** acceptance. |
| **Evidence required** | Source/negative tests; runtime fixed-operation tests; packaging/deployment/host/runtime isolation evidence showing no broker/manager Docker socket/SDK/API/authority in runtime paths; compatibility export isolation/removal evidence; independent review; signed/formal record package. |
| **Responsible authority role** | **Project owner and security authority** for decision. **Broker/manager/runtime owners** for mitigation/isolation evidence (not approval authority unless separately named and authorized). |
| **Scope and limitations** | Environment/phase: `[NOT RECORDED]`. Runtime paths/components in scope: `[NOT RECORDED]`. Exclusions (packaging/host not proven, mock-only limits): `[NOT RECORDED]`. Duration: `[NOT RECORDED]`. Mock ≠ host evidence statement: `[REQUIRED — explicit text]`. |
| **Compensating controls** | `[NOT RECORDED — authority restrictions, deployment controls, monitoring, removal/isolation plan]` |
| **Approval/rejection field** | Decision: `[ ] ACCEPT  [ ] REJECT  [ ] DEFER  [ ] MITIGATE-CLOSED`  <br> Named authority (person/role, basis): `[NOT RECORDED]`  <br> Rationale/conditions: `[NOT RECORDED]`  <br> Signature/attestation: `[NOT RECORDED]` |
| **Date and review/expiry trigger** | Decision date/time: `[NOT RECORDED]`  <br> Review/expiry trigger: `[NOT RECORDED]` |

## Template D — SR-10: Atomicity disposition

| Field | Template content |
|---|---|
| **Risk/decision ID** | SR-10 — No end-to-end atomicity across SQLite writes and backend effects (Known limitation, Medium) |
| **Decision required** | Record formal disposition: **ACCEPT documented limitation** for a defined scope, **REJECT**, **DEFER**, or **MITIGATE-CLOSED** only if design/evidence changes the limitation (not claimed by current evidence). Define operator/authority response to deliberate uncertainty. |
| **Evidence required** | Current design/implementation evidence of transaction boundaries; evidence of uncertainty handling/reconciliation behavior; operator runbook/response expectations for partial/uncertain outcomes; any future engineering evidence if mitigation claimed. |
| **Responsible authority role** | **Project owner and/or security authority** (as designated by project governance) for limitation acceptance/disposition. **Controller/persistence/recovery engineering owner** for technical evidence input. |
| **Scope and limitations** | Operations/states in scope: `[NOT RECORDED]`. Explicit statement that backend effects and SQLite writes are not atomically committed end-to-end: `[REQUIRED if limitation accepted]`. Excluded guarantees: `[NOT RECORDED]`. Duration: `[NOT RECORDED]`. |
| **Compensating controls** | `[NOT RECORDED — reconciliation, operator review of uncertain outcomes, idempotency/outcome handling, monitoring/alerts]` |
| **Approval/rejection field** | Decision: `[ ] ACCEPT  [ ] REJECT  [ ] DEFER  [ ] MITIGATE-CLOSED`  <br> Named authority (person/role, basis): `[NOT RECORDED]`  <br> Rationale/conditions: `[NOT RECORDED]`  <br> Signature/attestation: `[NOT RECORDED]` |
| **Date and review/expiry trigger** | Decision date/time: `[NOT RECORDED]`  <br> Review/expiry trigger: `[NOT RECORDED]` |

## Template E — SR-06 / I-09: Live-seam and identity/sanitization disposition

| Field | Template content |
|---|---|
| **Risk/decision ID** | SR-06 — Auth/trust boundary (Partially mitigated) and I-09 — Strict-auth/test-seam residual (Open/Partially resolved), including live-capable path disposition |
| **Decision required** | Record disposition for mock trust seams and identity handling: **ACCEPT scoped residual** for explicitly non-live/mock scope only, **REJECT**, **DEFER**, or **MITIGATE-CLOSED** by removal/isolation and required evidence. Any live-capable path requires mitigation/closure evidence before authorization; do not accept mock seams as live identity proof. |
| **Evidence required** | Evidence of `TrustedPeerIdentity`/strict-auth enforcement in target paths; removal/isolation of `strict_auth=False`, `MockAuthorizationProvider`, and `controller_verified`-style trusted-flag acceptance from live-capable construction/import/config paths; `SO_PEERCRED`/kernel identity and host transport evidence for live paths (H-03/H-04/M-07 prerequisites); import/config negative tests and deployment assertions; universal sanitization/validation evidence where identity/errors intersect (I-08/RR-07 as applicable). |
| **Responsible authority role** | **Project owner and security authority** for residual acceptance/disposition affecting live-capable paths. **Controller/auth/transport implementation owners** and **deployment/platform owner** for technical/host evidence input. |
| **Scope and limitations** | Paths/environments covered: `[NOT RECORDED]`. Explicitly excluded live-capable paths: `[NOT RECORDED]`. Statement that request-dict peer claims and mock seams are not kernel-authenticated identity: `[REQUIRED where relevant]`. Duration: `[NOT RECORDED]`. |
| **Compensating controls** | `[NOT RECORDED — strict construction, test-only isolation, config/deployment assertions, transport hardening, monitoring]` |
| **Approval/rejection field** | Decision: `[ ] ACCEPT  [ ] REJECT  [ ] DEFER  [ ] MITIGATE-CLOSED`  <br> Named authority (person/role, basis): `[NOT RECORDED]`  <br> Rationale/conditions: `[NOT RECORDED]`  <br> Signature/attestation: `[NOT RECORDED]` |
| **Date and review/expiry trigger** | Decision date/time: `[NOT RECORDED]`  <br> Review/expiry trigger: `[NOT RECORDED]` |

## Cross-cutting record requirements

Any completed template/record must also satisfy `PHASE_2L_2J_3_RISK_ACCEPTANCE_AND_AUTHORITY_PLAN.md` §6 where applicable: evidence reviewed, conditions/compensating controls, and formal attestation. No record is complete without a named authority basis and explicit scope/limitations. Completion of these templates does not change gate status, does not authorize live integration, and does not start Stage 1C.