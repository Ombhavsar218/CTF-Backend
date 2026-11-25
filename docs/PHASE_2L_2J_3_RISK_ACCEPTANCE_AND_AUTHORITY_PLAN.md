# Phase 2L.2J.3 — Risk Acceptance and Authority Plan

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Phase:** 2L.2J.3  
**Date:** 2026-11-14  
**Status:** **PREPARATION DOCUMENT — NO FORMAL RISK ACCEPTANCE GRANTED**  
**Scope:** Formal risk-acceptance preparation for T-11, T-13, and T-27; Docker/runtime authority model; approval responsibilities; and acceptance criteria for a future separately authorized controlled host-validation phase.

This document does **not** approve, accept, or reject any security risk. A coding agent cannot approve security risks on behalf of the project owner or security authority. Any risk without an explicit, named, recorded approval by the authorized party remains **OPEN — ACCEPTANCE REQUIRED**.

---

## 1. Risk disposition states

| State | Meaning | Current applicability |
|---|---|---|
| Risk identified | Risk is documented with scenario and impact. | T-11, T-13, T-27 identified. |
| Risk mitigated | Required mitigations implemented and evidenced; residual reduced to accepted level or eliminated. | Not achieved for T-11/T-13/T-27. |
| Risk proposed for acceptance | Residual risk, mitigations, evidence, and conditions are documented for decision. | Proposed in this plan only; not accepted. |
| Risk formally accepted | Named authority explicitly accepts defined residual risk with scope, conditions, evidence, and review/expiry terms. | **None.** |
| Risk rejected | Named authority rejects acceptance; further mitigation/removal required. | **None recorded.** |

**T-11:** OPEN — ACCEPTANCE REQUIRED  
**T-13:** OPEN — ACCEPTANCE REQUIRED  
**T-27:** OPEN — ACCEPTANCE REQUIRED (or removal/mitigation to an acceptable evidenced state; N-04 source authority also open)

---

## 2. T-11 — Compromised controller

| Field | Preparation record |
|---|---|
| Original risk | T-11: compromised controller process/DB can issue valid helper operations for owned policies, deny service, falsify local evidence, or suppress audit. |
| Threat scenario | Attacker gains code execution or privileged control over the unprivileged controller service, its configuration, or its local database; uses legitimate helper contract/ownership context to mutate or misrepresent owned firewall state. |
| Security impact | Unauthorized install/revoke/verification behavior for owned policies, denial of service, false or suppressed evidence/audit, delayed or incorrect reconciliation, loss of trust in controller-reported state. |
| Existing mitigation (design/current) | Controller intended to be unprivileged (no `CAP_NET_ADMIN`); helper performs fixed operations with peer/ownership validation and read-back; durable intent/evidence/append-only records planned; separation from broker/helper/manager; threat mapped in 2H.2. |
| Remaining exposure | Controller still authorizes/requests valid helper operations for owned scope; local evidence can be influenced if controller compromised; implementation and independent helper/runtime audit evidence not complete. |
| Possible additional mitigation | Independent helper/runtime read-back audit channel, signed/immutable evidence externalization, strict least-privilege service hardening, mandatory reconciliation from backend truth, anomaly detection, reduced controller authority scope, external approval for sensitive operations (design decision if needed). |
| Required approval authority | **Project owner** and **security authority/reviewer** (named individuals/roles must be recorded in a future approval record). Engineering lead may recommend but cannot accept residual risk. |
| Required evidence before acceptance decision | Final threat model review; implemented mitigations and test evidence; helper read-back/independent audit evidence; host-lab behavior evidence; incident containment/rollback procedures; explicit residual-risk statement. |
| Acceptance conditions (if ever accepted) | Acceptance limited to defined scope/environment; compensating controls active (monitoring, reconciliation, isolated host/phase as applicable); no acceptance for production/live integration by this document. |
| Review or expiry conditions | Time-bound review (recommended: at each major architecture change, helper/controller change, or before host-validation/live authorization); immediate re-review on incident or new exploit path. |
| Current disposition | **OPEN — ACCEPTANCE REQUIRED**. No approval, signature, or authority recorded. |

---

## 3. T-13 — Compromised privileged helper (`CAP_NET_ADMIN`)

| Field | Preparation record |
|---|---|
| Original risk | T-13: compromised helper with `CAP_NET_ADMIN` can mutate host firewall/network state, bypass intended boundaries, or cause denial of service. |
| Threat scenario | Attacker exploits helper parsing, backend interaction, dependency, or local privilege boundary to execute unintended netfilter operations or disrupt host networking despite fixed-operation design. |
| Security impact | Host firewall/network manipulation, bypass of intended policy boundaries, traffic disruption/denial, potential impact on co-located services, loss of containment assumptions. |
| Existing mitigation (design/current) | Dedicated helper with minimal capability (`CAP_NET_ADMIN` only, if validated), fixed operation allowlist, canonical schema validation, ownership markers, no shell/arbitrary command execution, read-back verification, service hardening/seccomp/MAC planned, isolated host-validation before any broader use. |
| Remaining exposure | `CAP_NET_ADMIN` is inherently powerful for network/firewall state; implementation hardening and host evidence incomplete; kernel/userspace exploit chains cannot be excluded by documentation. |
| Possible additional mitigation | Stronger seccomp/AppArmor/SELinux profile, minimal binary/runtime dependencies, read-only filesystem, no dynamic code loading, separate read/verify helper (if designed), strict backend ownership checks, external monitoring/reconciliation, remove capability by alternative architecture (major redesign). |
| Required approval authority | **Project owner** and **security authority/reviewer** with platform/host-operations input (named individuals/roles must be recorded). |
| Required evidence before acceptance decision | Exact capability grant evidence; hardening profiles; fixed-op/no-shell code evidence; fuzz/negative validation results as applicable; host-lab tests; rollback/containment evidence; residual-risk statement. |
| Acceptance conditions (if ever accepted) | Scope-limited to approved isolated environment/phase; no production/live acceptance implied; compensating controls and monitoring required; helper changes trigger re-review. |
| Review or expiry conditions | Time-bound and change-triggered re-review (helper code, kernel, nftables/iptables stack, capability/profile changes, or before live authorization). |
| Current disposition | **OPEN — ACCEPTANCE REQUIRED**. No approval, signature, or authority recorded. |

---

## 4. T-27 — Docker/runtime authority and host-root-equivalent residual

| Field | Preparation record |
|---|---|
| Original risk | T-27: runtime-adapter/Docker daemon authority can be host-root-equivalent (especially rootful Docker). Compromise or misuse can enable host/container escape impact, broad runtime control, or firewall/Docker interference. Current source also retains broker/manager Docker adapter code paths (N-04). |
| Threat scenario | (a) A component with Docker API/socket access issues arbitrary/unsafe operations. (b) Runtime adapter is compromised. (c) Broker/manager adapter path becomes reachable with a client/wiring change and is abused. |
| Security impact | Host-root-equivalent runtime control, unauthorized container/network/mount/namespace operations, data exposure, interference with firewall/DOCKER-USER behavior, compromise propagation. |
| Existing mitigation (design/current) | Target architecture: broker/manager/controller/helper/monitor have no Docker socket/group/API; only approved runtime component may access Docker via fixed catalog-bound operations on isolated UDS with `SO_PEERCRED`, ownership labels/spec digest, resource restrictions, and audit. Current broker adapter is clientless/fail-closed by default in inspected wiring; manager adapter not route-wired in inspected code. |
| Remaining exposure | N-04 open: broker adapter wired and manager adapter present/exported in source. No runtime service implemented. Rootful Docker residual remains high even with fixed adapter. No host/runtime evidence. |
| Possible additional mitigation | Remove broker/manager Docker code entirely; implement fixed runtime adapter with strict allowlist/denylist and non-root/rootless constraints where feasible; eliminate online Docker dependency; isolate Docker host; use signed images/digests and strong audit; independent runtime review. Rootless/non-Docker alternatives require new design decisions. |
| Required approval authority | **Project owner** and **security authority/reviewer** with runtime/platform owner (named individuals/roles must be recorded). |
| Required evidence before acceptance decision | N-04 closure evidence (source removal/negative tests); runtime boundary implementation and tests if retained; Docker non-interference/backend evidence; host isolation evidence; explicit residual-risk statement for rootful Docker if retained. |
| Acceptance conditions (if ever accepted) | No acceptance while N-04 open. If retained, acceptance must be scope-limited, environment-limited, and conditioned on fixed-operation enforcement, monitoring, and isolation; not valid for production/live integration. |
| Review or expiry conditions | Re-review on any Docker/runtime code change, socket access change, image/catalog change, host upgrade, or before live authorization. |
| Current disposition | **OPEN**. Not formally accepted. **N-04 source authority remains open** and is a blocking dependency. |

---

## 5. Docker/runtime authority model (required future architecture)

### 5.1 Component access

| Component | May request runtime operations? | Direct Docker socket/API access | Notes |
|---|---|---|---|
| Manager | No (target) | **Forbidden** | No Docker socket/group/API/import/route. |
| Restricted broker | Only via fixed runtime-adapter UDS contract, if runtime feature approved | **Forbidden** | No Docker socket/group/API/import/route; no generic Docker client. |
| Unprivileged controller | No | **Forbidden** | Firewall-control only. |
| Privileged helper | No | **Forbidden** | Firewall backend only. |
| Runtime adapter (`flaghunt-runtime`, future, if approved) | Executes only fixed catalog-bound operations | **Permitted only for this component**, only if explicitly approved | Host-root-equivalent residual (T-27) remains unless removed. |
| Monitor/other services | No | **Forbidden** | No runtime authority. |

### 5.2 Explicit operation allowlist (target, if runtime retained)

Allowed only as fixed `RUNTIME_*` operations resolved from approved catalog/spec (example set; final IDs must match approved contract): `RUNTIME_CREATE_INSTANCE`, `RUNTIME_START_INSTANCE`, `RUNTIME_INSPECT_INSTANCE`, `RUNTIME_STOP_INSTANCE`, `RUNTIME_REMOVE_INSTANCE`. Catalog lookup/read-only metadata only as explicitly defined; caller supplies approved identifiers, not raw Docker parameters.

### 5.3 Rejected operation list

Arbitrary Docker API passthrough; image pull/build/push/import/export; arbitrary container create/run/exec/cp/attach; arbitrary command/entrypoint/env injection; host bind mounts/volumes/devices; host/network/PID/IPC/UTS namespaces; privileged containers; capability adds; security-opt relaxation; port publishing not explicitly approved by catalog; network connect/disconnect outside approved model; daemon/config changes; swarm/node/volume/network/plugin/system-prune style operations; any operation not in fixed allowlist.

### 5.4 Resource ownership, authn/authz, isolation, restrictions

| Control | Requirement |
|---|---|
| Resource ownership | Every runtime object labeled/attributed to approved challenge/instance/owner; inspect/stop/remove only for owned managed resources; unknown/unlabeled resources never adopted or deleted. |
| Authentication | Kernel `SO_PEERCRED` peer identity on runtime UDS; exact numeric allowlist for authorized caller(s) only. |
| Authorization | Caller authorized per operation and owned resource; catalog/spec digest and policy checks required. |
| Resource isolation | Pinned image digests, non-root container user where possible, read-only rootfs where possible, bounded tmpfs/cpu/memory/pids/lifetime, no host mounts/namespaces/devices, no-new-privileges, drop capabilities, internal approved network only. |
| Command/API restrictions | No shell; no raw Docker CLI/API exposure to callers; fixed request schema and bounded fields. |
| Audit requirements | Independent runtime audit for request, caller identity, operation, resource IDs, catalog/spec digest, result/error, timestamps, and correlation IDs; no secrets/raw payload dumps. |
| Timeout/resource exhaustion | Bounded operation timeouts, concurrency/rate limits, bounded retries, disk/log quotas, fail-closed on exhaustion. |
| Failure handling | No false success; uncertain outcomes reconciled; cleanup limited to owned resources after verification. |
| Recovery behavior | Restart-safe reconciliation of managed resources; orphan/unknown resources reported, not auto-deleted. |

### 5.5 Required tests (future)

- Broker/manager import, route, socket, and group negative tests (no Docker authority).
- Fixed-operation positive/negative schema and authorization tests.
- Catalog/spec digest and ownership-label enforcement tests.
- Resource-restriction tests (mounts, namespaces, caps, privileged, devices, ports, networks).
- Timeout/exhaustion/failure/uncertain-outcome tests.
- Audit and reconciliation tests.
- Host-lab runtime isolation and Docker non-interference evidence (separately authorized).

---

## 6. Approval responsibilities matrix (template)

No approvals are recorded by this phase. Future records must capture:

| Record field | Required content |
|---|---|
| Risk/decision ID | T-11, T-13, T-27, Docker authority boundary, host-validation entry, etc. |
| Decision | Accept / reject / defer / mitigate-closed |
| Scope and limitations | Environment, phase, systems, duration, excluded scope |
| Named authority | Person/role, organization/project authority basis |
| Date/time | Approval timestamp |
| Evidence reviewed | Document IDs, test results, review records, artifacts |
| Conditions/compensating controls | Mandatory controls and monitoring |
| Review/expiry | Next review date and trigger events |
| Signature/attestation | Recorded approval artifact (outside this codebase unless approved) |

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**