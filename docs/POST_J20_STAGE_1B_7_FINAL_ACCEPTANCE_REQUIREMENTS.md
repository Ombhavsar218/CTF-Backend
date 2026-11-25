# Post-J.20 Stage 1B.7 — Final Acceptance Requirements (Mock-Only)

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

**T-11, T-13 and T-27 remain OPEN — ACCEPTANCE REQUIRED.**

## 1. Purpose

This document states the evidence and named-authority actions required before any formal
acceptance decision can be made about the Stage 1B.1–1B.6 mock-only scope. It is a requirements
checklist only. It does not accept risk, close a gate, authorize live firewall integration,
authorize Docker/UDS/host work, start Stage 1C, or imply production readiness.

Stage 1B.7 decision: **CONDITIONALLY READY FOR FORMAL ACCEPTANCE REVIEW**.

## 2. Minimum engineering evidence bundle

The following evidence is present and must be preserved unchanged for the acceptance package:

| Item | Evidence |
|---|---|
| Stage 1B.1–1B.4 implementation and verification | Completed milestone documents and captured suite artifacts; baseline **VERIFIED (scoped)**. |
| Stage 1B.5 independent review | Four deliverables: independent security review, final risk register, remediation roadmap, final readiness decision. |
| Stage 1B.6 remediation record | `docs/POST_J20_STAGE_1B_6_TARGETED_RESIDUAL_GAP_REMEDIATION.md`. |
| Stage 1B.6 raw test artifacts | `post_j20_stage_1b6_new_suite.*` (**16 passed**, exit 0), `post_j20_stage_1b6_targeted.*` (**301 passed**, exit 0), `post_j20_stage_1b6_full.*` (**944 passed**, 0 failed, 0 errors, exit 0, 391.61s). |
| Stage 1B.6 failure chronology | `post_j20_stage_1b6_new_suite.initial_failure.note.txt`; preserve with the SR-14 note below. |
| Stage 1B.7 independent verification | `docs/POST_J20_STAGE_1B_7_INDEPENDENT_REMEDIATION_VERIFICATION.md`. |
| Stage 1B.7 final assessment | `docs/POST_J20_STAGE_1B_7_FINAL_MOCK_ONLY_ASSESSMENT.md`. |
| Repository protection | HEAD unchanged, 26 modified tracked files, untracked evidence preserved, 0 staged files; no reset/clean/revert/stage/commit. |

## 3. Named-authority acceptance requirements

Formal acceptance cannot occur without explicit, named-authority records for the architecture
risks that engineering evidence alone cannot close:

| Gate | Required acceptance action |
|---|---|
| T-11 | Signed or otherwise formally recorded acceptance of the residual compromised-controller risk, or approved mitigation/removal evidence. Record scope, authority, date, residual acknowledgment and review trigger. |
| T-13 | Signed/formal acceptance of residual privileged-helper/capability risk, or approved capability-surface reduction/removal evidence with host-lab proof. |
| T-27 | Signed/formal acceptance of runtime-adapter/host-root-equivalent residual, or evidence that the rootful runtime path is removed/isolated. Must address H-02/N-04. |

Acceptance records must explicitly state that mock evidence is not host evidence and that
acceptance is limited to the named residual; they must not be implied by a passing test suite.

## 4. Host/runtime evidence prerequisites

Before any host-validation or live-capable authorization, the following evidence must exist and
be independently reviewed. None was produced in Stage 1B.7:

- UDS lifecycle proof for H-01/N-01/M-02: direct bind, `2750` setgid directories, `0660`
  sockets, owner/group/mode checks, stale/live socket handling, restart and ID-drift behavior.
- Kernel-authenticated identity proof for H-03/H-04/M-07: typed `SO_PEERCRED` adapters, mutual
  peer verification, cross-UID deny, absent/malformed credential rejection, and removal of
  request/header identity authority from live paths.
- Runtime authority proof for H-02/N-04/T-27: no broker/manager Docker socket/SDK/API/authority
  in packaging, deployment or runtime paths; compatibility exports isolated or removed;
  fixed-operation runtime boundary if runtime is retained.
- Helper hardening proof for T-13/M-09: fixed operations, no shell, capability minimization,
  seccomp/MAC as applicable, readback truthfulness and rollback evidence.
- Host firewall proof for M-09: approved isolated-lab execution of nftables/iptables/
  DOCKER-USER behavior with rollback records and negative tests.
- Deployment/configuration inventory for M-07: verified numeric UIDs/GIDs and exact allowlist
  assertions.

## 5. Live-backend and data-authority prerequisites

- SR-11: authorized contract tests proving real-backend idempotency-key honoring, readback
  truthfulness, failure/error semantics and duplicate-effect containment. Mock behavior is not
  sufficient.
- N-02/H-05/M-08: end-to-end `rule-schema-v1` / `2L.2I.2` envelope alignment across broker,
  controller, helper, backend, persistence and response paths; rejection or quarantine of
  incompatible legacy forms.
- N-02/H-05/SR-13: legacy migration/quarantine decision and evidence; universal no-silent-
  conversion proof beyond the currently scoped no-rules compatibility path.
- RR-06/M-06: DB-enforced digest constraints/migrations, migration evidence and comprehensive
  integrity/failure tests beyond covered append-only triggers.
- SR-10: explicit formal disposition of the documented lack of end-to-end atomicity across
  SQLite writes and backend effects.

## 6. Universal closure prerequisites

- I-07/RR-01–RR-04: canonical `request_id`, `operation_id`, `idempotency_key` and
  `policy_version` validation at all broker/controller/helper/persistence entry points, with
  negative tests for aliases and malformed values.
- I-08/RR-07: sanitized bounded error mapper on all persistence/transport paths with
  leakage-negative response, log and audit evidence. This includes disposition of the SR-07
  broad-catch and catch-all hardening notes and the SR-08 nested canonical-read classification
  note (`controller_service.py:1682-1690`).
- I-09: removal or isolation of `strict_auth=False`, `MockAuthorizationProvider` and
  `controller_verified` trusted-flag acceptance from all live-capable construction/import/config
  paths.
- RR-05: complete per-policy/full-inventory reconciliation completeness review, including
  cross-table/orphan inventory and exhaustive state/race matrices. This includes disposition of
  the SR-09 compatibility-fallback and `require_evidence` residuals.

## 7. Documentation-governance prerequisites

- SR-14: governance-owned reconciliation of Stage 1B-local scope labels for RR-05/RR-06/
  M-01/M-06 with canonical register definitions.
- Stage 1B.6 evidence chronology: retain the initial-failure note but add a governance note
  that its final paragraph names an earlier intermediate 14-test capture, while the authoritative
  final focused suite is 16 passed with `EXIT=0`. Stage 1B.7 records this observation without
  editing the historical artifact.
- Preserve superseded failed/debug captures with explicit chronology; do not delete or rewrite
  them to imply a clean history.
- Reassess the security-gate register only after the evidence above exists; no automatic gate
  closure from engineering artifacts.

## 8. Acceptance decision rules

1. A formal acceptance package must identify the accepting authority, exact residual scope,
   evidence reviewed, exclusions, date and review trigger.
2. Engineering evidence can support an acceptance review but cannot close T-11/T-13/T-27 or any
   host/runtime gate by itself.
3. A gate is **VERIFIED CLOSED** only when required implementation, test, runtime, review and
   formal acceptance evidence exists and is independently reviewed.
4. No accepted residual risk exists until a named authority records it; Stage 1B.5 and Stage 1B.7
   record zero accepted residual risks.
5. Until explicit authority action changes the status, the mandatory status remains
   **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
6. Acceptance of the mock-only engineering scope must not be represented as production
   readiness or live firewall authorization.

## 9. Current disposition

The Stage 1B.6 source-provable gaps SR-07, SR-08 and SR-09 are independently **VERIFIED FIXED
(scoped)**, and the mock-only engineering scope is **CONDITIONALLY READY FOR FORMAL ACCEPTANCE
REVIEW**. The conditions in sections 3–7 remain blockers. T-11, T-13 and T-27 remain **OPEN —
ACCEPTANCE REQUIRED**, and no gate is closed by this document.
