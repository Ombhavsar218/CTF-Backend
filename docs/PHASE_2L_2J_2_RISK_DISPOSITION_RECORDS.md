# Phase 2L.2J.2 — Risk Disposition Records

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Phase:** 2L.2J.2  
**Date:** 2026-11-14  
**Status:** **PREPARATION ONLY — NO FORMAL RISK ACCEPTANCE GRANTED**  

This document prepares risk-disposition records for T-11, T-13, and T-27. It does **not** approve, accept, reject, or close any risk. A coding agent cannot invent approvals, signatures, approval dates, or security authorizations. Any risk without explicit, named, recorded approval by the authorized authority remains **OPEN — ACCEPTANCE REQUIRED** (or **OPEN — TECHNICAL REMEDIATION REQUIRED** where applicable).

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

---

## 1. Disposition states used

| State | Meaning |
|---|---|
| Risk identified | Risk documented with scenario and impact. |
| Source-level Docker authority removed (T-27 specific) | Inspected broker/manager operational Docker adapter paths removed or made fail-closed/unavailable in mock-only source; no live runtime proof. |
| Docker authority independently verified absent (T-27 specific) | Independent source/test/runtime review confirms no reachable Docker authority in approved scope; not achieved. |
| Future runtime architecture designed | Fixed runtime boundary/authority model documented; partial (target design exists in 2H/2J.3), not implemented. |
| Future runtime architecture implemented | Approved fixed runtime boundary implemented and tested; not achieved. |
| Risk mitigated | Required mitigations implemented/evidenced and residual reduced/eliminated to accepted level; not achieved. |
| Risk proposed for acceptance | Evidence package prepared for decision; proposed only. |
| Risk formally accepted | Named authority explicitly accepts defined residual risk with scope/conditions/evidence/review-expiry; **none**. |
| Risk rejected | Named authority rejects acceptance; further mitigation/removal required; **none recorded**. |
| OPEN — ACCEPTANCE REQUIRED | Formal named-authority decision/evidence required. |
| OPEN — TECHNICAL REMEDIATION REQUIRED | Technical mitigation/removal evidence not yet sufficient for closure/acceptance. |

---

## 2. T-11 — Compromised controller

| Field | Record |
|---|---|
| Risk ID | T-11 |
| Original risk description | Compromised controller process/DB can issue valid helper operations for owned policies, deny service, falsify local evidence, or suppress audit. |
| Threat scenario | Attacker gains code execution or control over the unprivileged controller service/configuration/database and uses legitimate helper contract/ownership context to mutate or misrepresent owned firewall state, delay/deny operations, or suppress/falsify local evidence. |
| Potential impact | Unauthorized install/revoke/verification behavior for owned policies, denial of service, false or suppressed evidence/audit, incorrect reconciliation, loss of trust in controller-reported state. |
| Current mitigations (design/existing) | Target: controller unprivileged (no `CAP_NET_ADMIN`), fixed helper operations with peer/ownership validation and read-back, durable intent/append-only evidence, separation from broker/helper/manager/runtime, reconciliation and independent audit concepts in 2H design. No controller implementation/host evidence completed in this phase. |
| Proposed/remaining mitigations | Independent helper/runtime read-back audit channel, signed/immutable evidence externalization, strict service hardening/least privilege, mandatory backend-truth reconciliation, anomaly detection/monitoring, reduced controller authority scope as design permits. |
| Remaining exposure | Controller can authorize/request valid operations within owned scope if compromised; local evidence influence remains possible; implementation and independent audit/host evidence incomplete. |
| Evidence needed before decision | Final threat-model review, implemented mitigations and tests, helper read-back/independent audit evidence, host-lab isolation/behavior evidence, incident containment/rollback procedures, explicit residual-risk statement. |
| Required approval authority | **Project owner** and **security authority/reviewer** (named individuals/roles must be recorded). Engineering may recommend; cannot accept. |
| Required acceptance criteria (if ever accepted) | Named approval, defined scope/environment, evidence reviewed, compensating controls active, no production/live authorization implied, re-review/expiry terms recorded. |
| Required review/expiry | Time-bound review at major architecture/helper/controller changes and before host-validation/live authorization; immediate re-review on incident/new exploit path. |
| Approval name | **Not provided — OPEN — ACCEPTANCE REQUIRED** |
| Signature/attestation | **Not provided — OPEN — ACCEPTANCE REQUIRED** |
| Approval date | **Not provided — OPEN — ACCEPTANCE REQUIRED** |
| Current disposition | **OPEN — ACCEPTANCE REQUIRED**. No implementation/capability change made in this phase. |

---

## 3. T-13 — Compromised privileged helper / `CAP_NET_ADMIN`

| Field | Record |
|---|---|
| Risk ID | T-13 |
| Original risk description | Compromised helper with `CAP_NET_ADMIN` can mutate host firewall/network state, bypass intended boundaries, or cause denial of service. |
| Threat scenario | Exploitation of helper parsing, backend interaction, dependency, or local privilege boundary causes unintended netfilter/network operations or disruption despite fixed-operation intent. |
| Privilege escalation / host impact implications | `CAP_NET_ADMIN` enables powerful network/firewall state changes; compromise may affect host networking, co-located services, traffic policy enforcement, and containment assumptions. |
| Potential host impact | Unauthorized firewall/network mutation, policy bypass/disruption, denial of service, interference with host/container networking, loss of trust in enforcement state. |
| Current mitigations (design/existing) | Target: dedicated helper with minimal capability (only if validated), fixed operation allowlist, canonical schema validation, ownership markers/read-back, no shell/arbitrary commands, hardening (seccomp/MAC/minimal runtime) planned, isolated host validation required before broader use. No helper implementation/capability grant performed in this phase. |
| Intended privilege restrictions | `CAP_NET_ADMIN` only as strictly required and validated; no other capabilities; fixed ops; no shell; bounded schema; least-privilege service account and filesystem/runtime hardening; isolated UDS + kernel peer auth in target design. |
| Required security controls | Capability minimization/hardening, fixed-op enforcement, input validation, ownership/read-back checks, non-broad flush/foreign-rule protection, audit, timeout/fail-closed behavior, rollback/containment procedures. |
| Required evidence before decision | Exact capability/hardening evidence, fixed-op/no-shell code evidence, negative/fuzz validation as applicable, host-lab tests, rollback/containment evidence, explicit residual-risk statement. |
| Required approval authority | **Project owner** and **security authority/reviewer** with platform/host-operations input (named). |
| Required acceptance criteria (if ever accepted) | Named approval, scope-limited approved environment, evidence reviewed, compensating controls/monitoring active, no production/live authorization implied, change-triggered re-review. |
| Required review/expiry | Time-bound and change-triggered (helper code, kernel/netfilter stack, capability/profile changes, before live authorization); immediate re-review on incident. |
| Approval name | **Not provided — OPEN — ACCEPTANCE REQUIRED** |
| Signature/attestation | **Not provided — OPEN — ACCEPTANCE REQUIRED** |
| Approval date | **Not provided — OPEN — ACCEPTANCE REQUIRED** |
| Current disposition | **OPEN — ACCEPTANCE REQUIRED**. No helper/capability/host implementation performed in this phase. |

---

## 4. T-27 — Docker/runtime authority and host-root-equivalent residual

| Field | Record |
|---|---|
| Risk ID | T-27 |
| Original risk description | Runtime-adapter/Docker daemon authority can be host-root-equivalent (especially rootful Docker). Compromise or misuse may enable broad runtime/host impact, container/network/mount/namespace abuse, and firewall/Docker interference. Prior inspections also identified broker/manager Docker adapter authority concerns (N-04). |
| Host-root-equivalent authority concern | Rootful Docker API/socket access can provide effective host-root-equivalent control depending on daemon configuration and operations; any future runtime adapter with such access remains a high residual risk. |
| Previous broker and manager adapter paths | **Broker (pre-remediation):** `broker/app/docker_adapter.py` operational adapter accepted/stored `docker_client` and implemented container/network operations; wired via `broker/app/dependencies.py` and used by `broker/app/routes.py` (default no client but injectable/operational). **Manager (pre-remediation):** `manager/app/runtime/docker_adapter.py` operational adapter accepted/stored `docker_client`, exported via `manager/app/runtime/__init__.py`, mock-tested; not route-wired in inspected code. |
| Source-level remediation performed (this phase) | Broker adapter replaced with explicitly unavailable fail-closed implementation rejecting client injection and failing all container/network operations; broker deps/routes contain no Docker client creation/API path. Manager runtime adapter replaced with explicitly unavailable fail-closed implementation rejecting client injection and failing all operations; manager routes remain runtime-unavailable with no adapter wiring. Targeted negative tests added/updated (see 2J.2 remediation and independent review docs). |
| Negative test evidence | 82 selected tests passed (including new/rewritten broker/manager negative security and regression suites). Tests prove constructor rejection of fake clients, fail-closed operations, no mock docker API calls in tested paths, and preserved runtime-unavailable/auth/policy behaviors where applicable. **Mock-only evidence; not host/runtime proof.** |
| Remaining architectural risks | Host-root-equivalent residual remains if a runtime component with Docker authority is introduced/retained. `flaghunt-runtime` fixed-boundary service not implemented. Broker/manager compatibility adapter symbols/exports still exist but are unavailable/fail-closed (N-04 partially resolved). No host/runtime isolation, socket/group, or daemon-boundary evidence. |
| Future runtime-boundary requirements (if ever approved) | No broker/manager/controller/helper/monitor Docker socket/group/API/import/route; only approved runtime component may access Docker via isolated UDS + `SO_PEERCRED`, fixed allowlisted catalog-bound operations, ownership labels/spec digests, resource restrictions, audit, timeout/reconciliation, and fail-closed handling per 2J.3/2H design. Arbitrary Docker API/passthrough rejected. |
| Required independent review | Independent source review of final adapter/dependency/route/export/import paths and negative tests; separate runtime/host review required before any runtime integration/host validation. |
| Required formal approval authority | **Project owner** and **security authority/reviewer** with runtime/platform owner (named) for any risk acceptance or runtime authority boundary approval. |
| Required acceptance evidence | N-04 verified closure evidence (or accepted residual), runtime fixed-boundary implementation/tests if retained, host/runtime isolation and non-interference evidence, independent review records, explicit residual-risk statement for rootful Docker if retained. |
| Risk review and expiry requirements | Re-review on any Docker/runtime code, socket/group access, image/catalog, host upgrade, or before live authorization; time-bound periodic review if ever accepted. Immediate re-review on incident. |
| Distinction of states | 1) **Source-level Docker authority removed:** **Partially (mock-only).** Operational paths removed/fail-closed in inspected adapters; compatibility symbols remain unavailable. 2) **Docker authority independently verified absent:** **No (independent source-level review performed in this phase but broader/runtime/host absence not proven).** 3) **Future runtime architecture designed:** **Yes (target design documented; not implemented).** 4) **Future runtime architecture implemented:** **No.** 5) **Risk formally accepted:** **No.** |
| Approval name | **Not provided — OPEN — ACCEPTANCE REQUIRED** |
| Signature/attestation | **Not provided — OPEN — ACCEPTANCE REQUIRED** |
| Approval date | **Not provided — OPEN — ACCEPTANCE REQUIRED** |
| Current disposition | **OPEN — ACCEPTANCE REQUIRED** (and N-04 remains **PARTIALLY RESOLVED / technical closure incomplete**). Source-level exposure mitigated in mock-only scope; formal acceptance and residual elimination not achieved. |

---

## 5. Gate register update note

`docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` may be updated only where actual evidence supports a status change. This phase provides **mock-only source/test evidence** for broker/manager adapter unavailability and fail-closed behavior; it does **not** provide host/runtime/acceptance evidence sufficient to verify H-01–H-05, M-01–M-03/M-06–M-09, N-01–N-03, RR-01–RR-07, I-07–I-09, T-11/T-13, or HV-EC gates closed. N-04/T-27 status changes, if any, must be evidence-based and independently reviewed (see independent review report).

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
