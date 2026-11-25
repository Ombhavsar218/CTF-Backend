# Post-J.20 Stage 1B.8 — Outstanding Authority and Evidence Requirements

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.** This document is a requirements
inventory, not an acceptance record, risk acceptance, gate closure or authorization.

## 1. Named-authority acceptance requirements

No named-authority acceptance record, signed decision, approval form or gate-closure evidence was
found for any residual risk. `PHASE_2L_2J_3_RISK_ACCEPTANCE_AND_AUTHORITY_PLAN.md` §4 records
**zero** approvals; §6 defines the required record fields.

### 1.1 Absolute blockers

| Risk | Decision required | Evidence prerequisite | Named authority |
|---|---|---|---|
| **T-11** — compromised controller | Complete mitigations (independent helper audit/read-back, least privilege, evidence integrity), then formal acceptance **if residual remains**, or approved mitigation/removal closure. | Threat/mitigation evidence; independent helper audit design/tests; host isolation/monitoring plan; SR-06/SR-11/SR-12 prerequisites; signed acceptance/closure record. | **Project owner and security authority** (acceptance); controller/security engineering (mitigation). |
| **T-13** — privileged helper capability | Minimize capability/surface (fixed operations, no shell, hardening, seccomp/MAC, read-back), then formal acceptance **if residual remains**, or approved capability-surface reduction/removal **with host-lab proof**. | Capability/hardening design and tests; helper isolation evidence; host-lab results; rollback/containment evidence; signed acceptance/closure record. | **Project owner and security authority** (acceptance); helper/platform/security engineering; platform/host-operations input. |
| **T-27** — runtime/Docker host-root-equivalent residual | Maintain no broker/manager Docker authority; complete compatibility/deployment review; implement fixed runtime boundary if retained; validate controls; obtain formal acceptance **or remove the rootful runtime path**. Must address H-02/N-04. | Source/negative tests; runtime fixed-operation tests; packaging/deployment/host/runtime isolation evidence; independent review; signed acceptance or removal evidence. J.19 is **not** acceptance. | **Project owner and security authority** (acceptance if retained); broker/manager/runtime owners (mitigation). |

### 1.2 Required content of any acceptance record

Per the authority plan, each record must include:

- Risk/decision ID (T-11, T-13, T-27 or other explicit item).
- Exact decision: accept, reject, defer or mitigate-closed.
- Scope and limitations: environment, phase, systems, duration, excluded scope.
- **Named authority**: person/role and authority basis.
- Date/time of approval.
- Evidence reviewed.
- Conditions and compensating controls.
- Review/expiry trigger.
- Signature or equivalent formal attestation.

The record must explicitly state that **mock evidence is not host evidence**, must limit
acceptance to the named residual, and must not be implied by a passing test suite. No such record
exists.

### 1.3 Additional named-authority dispositions

- **SR-10** — formal disposition of the documented lack of end-to-end atomicity across SQLite
  writes and backend effects. Uncertainty is deliberate and may require operator/authority action.
- **SR-06 / I-09** — disposition of mock trust seams (`strict_auth=False`,
  `MockAuthorizationProvider`, `controller_verified`) for any live-capable construction path.
- **SR-14 and evidence chronology** — governance-owned scope-label reconciliation and 14-vs-16
  evidence chronology handling at formal acceptance.
- **Gate closure generally** — VERIFIED CLOSED requires implementation, test, runtime, review and
  formal acceptance evidence independently reviewed. Engineering artifacts alone are insufficient.

## 2. Host/runtime and live-backend evidence requirements

None of the following was produced in Stage 1B.7. No host, Docker, firewall, privileged, UDS,
capability or live-backend operation was performed in this review.

### 2.1 UDS / transport / kernel identity

| Area | Required evidence | Related gates |
|---|---|---|
| UDS lifecycle | Pinned-host `2750` setgid directories, `0660` sockets, exact owner/group/mode, stale vs live socket behavior, restart/upgrade and UID/GID drift tests. | H-01, M-02, N-01 |
| Kernel peer identity | Typed `SO_PEERCRED` adapters; removal of caller-supplied identity from request schema/auth/digest/logging; mutual verification; spoof/missing/malformed/mismatch negatives; cross-UID deny. | H-03, H-04, M-07 |
| Manager↔broker transport | Direct-bind UDS, mutual kernel peer verification, removal of unsafe header merge/optional-token live behavior, pinned-host transport tests. | H-04 |

### 2.2 Runtime authority / helper hardening

| Area | Required evidence | Related gates/risks |
|---|---|---|
| Docker/runtime boundary | Absence of broker/manager Docker socket/SDK/API/authority in packaging, deployment and runtime paths; compatibility exports isolated or removed; fixed-operation boundary if retained. | H-02, N-04, T-27 |
| Helper capability surface | Fixed operations, no shell, capability minimization, seccomp/MAC as applicable, read-back truthfulness, rollback/containment and host-lab proof. | T-13, M-09 |
| Host firewall | Approved isolated-lab nftables/iptables/DOCKER-USER behavior, capability limits, service/permission isolation and rollback evidence. | M-09 |
| Deployment identity | Numeric UID/GID inventory and exact allowlist assertions; startup assertions; negative configuration tests. | M-07 |

### 2.3 Live backend / data authority

| Area | Required evidence | Related risks/gates |
|---|---|---|
| Live contract | Authorized tests proving real-backend idempotency-key honoring, readback truthfulness, failure/error semantics and duplicate-effect containment. Mock behavior is not sufficient. | SR-11, T-11/T-13 |
| Envelope alignment | End-to-end `rule-schema-v1` / `2L.2I.2` envelope alignment across broker, controller, helper, backend, persistence and response paths. | N-02, H-05, M-08 |
| Legacy migration | Migration/quarantine decision and evidence; rejection of incompatible legacy forms; universal no-silent-conversion proof beyond the scoped no-rules path. | N-02, H-05, SR-13 |
| DB constraints | DB-enforced digest constraints/migrations; migration evidence; comprehensive integrity/failure/concurrency stress beyond covered append-only triggers. | RR-06, M-06 |

All host/runtime/live evidence must be independently reviewed and must be separately authorized
before collection. This Stage 1B.8 review does not authorize it.

## 3. Universal validation and sanitization requirements

| ID | Required evidence | Classification |
|---|---|---|
| **I-07** | Canonical `request_id`, `operation_id`, `idempotency_key` and `policy_version` validation at all broker/controller/helper/persistence entry points, with negative tests for aliases and malformed values. | Future authorized engineering. |
| **RR-01** | Same universal canonical validation; no-side-effect evidence at every receiver. | Future authorized engineering. |
| **RR-02** | Same universal validation plus operation-binding, uniqueness/conflict and evidence-correlation tests. | Future authorized engineering. |
| **RR-03** | Global per-receiver key/canonical form/digest/principal/operation/ownership binding; migration and replay/conflict tests. | Future engineering + DB/migration evidence. |
| **RR-04** | Integer/range/type rejection in app/schema/DB; bool/string/float/overflow/out-of-range negatives; migration evidence. | Future engineering + DB/migration evidence. |
| **I-08 / RR-07** | Sanitized bounded error mapper on all persistence/transport paths; leakage-negative response, log and audit evidence. Must include explicit disposition of SR-07 broad-catch/catch-all notes and SR-08 nested canonical-read classification note at `controller_service.py:1682-1690`. | Future engineering + environment-specific evidence. |
| **I-09** | Remove `strict_auth=False`, `MockAuthorizationProvider` and `controller_verified` from live construction; require `TrustedPeerIdentity`; isolate test-only provider; import/config negatives and deployment assertions. | Future engineering + named-authority disposition. |

## 4. SR-07 / SR-08 / SR-09 residual disposition requirements

The scoped fixes remain **VERIFIED FIXED (scoped)**. The following are residual disposition items,
not control failures of the scoped remediations.

### SR-07 residuals

- Broad `except Exception as create_exc` at `controller_service.py:968` is not gated on the typed
  conflict flag; non-conflict create errors with an existing same-key record may proceed to
  validated replay/pending classification. Comment at `:973-976` overstates the guarantee.
- Catch-all at `controller_service.py:461` bounds unknown read-back exceptions as request errors
  rather than persistence errors.
- Required: disposition under I-08/RR-07; typed-error fault matrix and regression equivalence;
  correct comment/scope label through authorized documentation governance.

### SR-08 residual

- A nested canonical read failure inside `read_trusted_canonical_policy_body()` during
  reconciliation is labeled `invalid_canonical_policy_body`/`uncertain` rather than
  `RECONCILIATION_PERSISTENCE_FAILURE` (`controller_service.py:1682-1690`). It still fails closed
  with no promotion.
- Required: disposition under I-08/RR-07; fault-injected nested-read test evidence.

### SR-09 residuals

- Compatibility fallbacks at `controller_service.py:1541-1547` bypass state/identity checks for
  test-only stores lacking the guard or legacy guarded callers without `allowed_states`; no
  production `reconcile_pending_operations` call site uses them. They become control-affecting if
  a production caller ever uses them.
- `require_evidence` is unused by current status-write callers; evidence is enforced by lifecycle
  transitions.
- Guard-capture test covers `needs_verification` but not the `failed` branch.
- Status and audit are separate guarded writes, not one atomic transaction.
- Required: disposition under RR-05; add `failed`-branch guard capture; decide whether fallback
  removal and status/audit atomicity are required in a future authorized stage.

## 5. Migration/data-authority requirements

- **N-02 / H-05 / M-08** — end-to-end envelope alignment across broker, controller, helper,
  backend, persistence and response paths; rejection/quarantine of incompatible legacy forms;
  universal no-silent-conversion proof.
- **RR-06 / M-06** — DB-enforced digest constraints and migrations; invalid read/write rejection;
  full FK/WAL/concurrency stress; append-only guarantees beyond covered triggers.
- **SR-10** — formal acceptance of no end-to-end atomicity; define operator/authority response to
  deliberate uncertainty.
- **SR-11** — authorized live-backend contract evidence as in §2.3.
- **SR-13** — future gate-closure evidence for N-02/H-05; preserve scoped no-rules compatibility
  without silent conversion.

## 6. Documentation-governance requirements

- **SR-14** — governance-owned reconciliation of Stage 1B-local scope labels for RR-05, RR-06,
  M-01 and M-06 with canonical register definitions.
- Preserve the Stage 1B.4 statement about "no Stage 1B.5 files" as historically stale, with an
  explicit chronology note rather than deletion.
- Preserve the initial-failure note at
  `post_j20_stage_1b6_new_suite.initial_failure.note.txt`. Its final paragraph names an earlier
  intermediate 14-test capture, while the authoritative final focused suite is **16 passed /
  EXIT=0**. Add a governance note; do not edit the historical artifact.
- Preserve all superseded failed/debug captures beside final green captures with explicit
  chronology. Do not rewrite history to imply a clean run.
- Additional Stage 1B.8 evidence-hygiene observations requiring governance notes, not artifact
  rewrites: off-by-3 line citations in `POST_J20_STAGE_1B_5_INDEPENDENT_SECURITY_REVIEW.md`
  (register insertions shifted T-gate and other pointers by +3); historical `2026-11-14` /
  "43 untracked unchanged" recheck text in the gate register versus later Stage 1B counts
  (163 → 166 → 176); earlier untracked-count variance (`403` in Stage 1B.1 versus `108/163`
  in Stage 1B.4) from undisclosed counting methods; the J.20 implementation evidence ledger
  ending at J.19 with no Stage 1B rows; and minor `?`/`-`/`—` punctuation variance in the register.
  No document explains the 14 → 16 test-growth in the preserved initial-failure note; record
  this as an unexplained chronology detail rather than altering the artifact.
- Reassess the gate register only after the evidence above exists. No automatic closure from
  engineering artifacts.

## 7. Conditions precedent to any future authorization request

1. T-11, T-13 and T-27 formal named-authority records with exact scope, evidence, approver, date,
   conditions and review trigger.
2. SR-10 formal disposition and SR-06 live-seam disposition.
3. Authorized host/runtime evidence for UDS lifecycle, kernel peer identity, runtime authority,
   helper hardening, host firewall and deployment identity inventory.
4. Authorized live-backend contract evidence for idempotency, readback truthfulness, failure
   semantics and duplicate-effect containment.
5. Universal canonical validation/sanitization closure and disposition of all SR-07/SR-08/SR-09
   residual notes.
6. End-to-end envelope/migration/data-authority closure, including DB constraints and no-silent-
   conversion proof.
7. SR-14 governance reconciliation and evidence-chronology notes, with historical artifacts
   preserved.
8. Independent review of all new evidence and formal security-gate reassessment. No gate may be
   marked VERIFIED CLOSED before all required implementation, test, runtime, review and acceptance
   evidence exists.

Until every applicable condition is satisfied, the mandatory status remains **NOT READY — LIVE
FIREWALL INTEGRATION NOT AUTHORIZED**, T-11/T-13/T-27 remain **OPEN — ACCEPTANCE REQUIRED**, no
residual risk is accepted, and Stage 1C or live integration must not start.
