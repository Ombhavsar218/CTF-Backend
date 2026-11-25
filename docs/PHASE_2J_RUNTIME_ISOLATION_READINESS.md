# Phase 2J — Runtime Isolation Implementation Readiness Review

**Date:** 2026-11-01  
**Status:** Documentation-only. No infrastructure, Docker, firewall, routing, NAT, IPv4/IPv6, UDS, or runtime provisioning changes were made. Runtime provisioning remains disabled.

**Primary updated:** `ctf-platform-be/docs/PHASE_2I_CHALLENGE_NETWORK_ISOLATION_ARCHITECTURE.md`  
**Created:** `ctf-platform-be/docs/PHASE_2J_RUNTIME_ISOLATION_READINESS.md`


## 1) Final Architecture (Consolidated)

Components:
- Django backend (auth/ownership/session/lifecycle)
- Runtime Manager (orchestration/policy validation)
- Restricted Docker Broker (container/network ops, ownership, audit, orphan recovery)
- Central ingress proxy (TLS/auth/routing, no Docker/socket/admin/DB/firewall)
- Per-instance gateway (1:1 to instance network, minimal routing)
- Challenge containers (isolated, read-only, dropped caps, no-new-privileges)
- Mapping API (read-only, fail-closed, mTLS/network-allowlisted)
- Host firewall controller (per-instance allowlists, DOCKER-USER)
- Persistent ownership and audit DBs (SQLite/WAL)

**Selected long-term:** **Option D (hybrid central ingress + per-instance gateways)**.

### Alternatives comparison (on 2 vCPUs / 3.8 GiB RAM / 48 GiB disk)

| Option | Trust boundaries | Network reachability | Proxy compromise impact | Cross-instance exposure | Resource consumption (est.) | Operational complexity | Recovery behavior |
|---|---|---|---|---|---|---|---|
| **A) Central proxy attached to all per-instance networks** | Shared trust boundary; proxy in many nets | Can reach all attached nets | **Highest** if attached to all | High without strict per-dest firewall | ~50-150 MB (1 proxy) — lowest | Moderate but high-risk | Hard to revoke cleanly; stale routes/attachments; high blast radius |
| **B) Central proxy with serialized attachment switching** | Central, but serialized | Only current net at a time | Lower if strict, switching window risky | Moderate if race leaves attachment | ~50-100 MB | High (locking/races) | Poor UX; race-prone; hard to guarantee atomicity |
| **C) Per-instance proxy workers** | Per-instance boundary (strong) | 1:1 per worker | **Lowest** per worker | Negligible by topology | ~50-100 MB/worker (linear) | High (many workers/lifecycle) | Isolated failures; more objects to manage |
| **D) Hybrid (central ingress + per-instance gateways)** | Separated duties (ingress vs gateway) | Central minimal, gateway 1:1 | **Low** (gateway affects one instance) | Minimal with 1:1 + firewall | Central ~30-60 MB + gateway ~30-60 MB/instance | Highest but cleanest | Failure-isolated; safer but complex | 

**Verdict:** Option D is the strongest for containment, but **not production-ready without evidence**. On this host it is likely feasible only at very low concurrency (1-2 instances). Option A is **only acceptable if 1:1 dynamic attachment + verified per-destination/per-port firewall are guaranteed** — currently high-risk.


## 2) Final Network Architecture (Zones)

| Zone | Components | Permitted communication | Must never communicate |
|---|---|---|---|
| **1) Management zone** | Django, Runtime Manager, Restricted Docker Broker, persistent DBs, Mapping API (mgmt leg) | Control-plane only, peer-cred enforced (UDS preferred). | Challenge containers; arbitrary proxy→mgmt except allowlisted mapping API. |
| **2) Central ingress zone** | Central ingress proxy | To Mapping API (allowlisted, read-only), to frontend, to per-instance gateway/backend on mapped routes only. | Docker socket, broker admin, manager admin, DB directly, arbitrary challenge nets. |
| **3) Per-instance gateway zone** | Per-instance gateway (1:1) | To assigned challenge container on approved port only; to central ingress as needed; to allowlisted mapping/control as needed. | Other instance gateways/containers, management services, host/LAN/metadata/internet. |
| **4) Individual challenge instance zone** | Challenge container(s) | Only to assigned gateway/proxy on established flows (responses) or as strictly allowed. | Internet, DNS (unless restricted), RFC1918/LAN, link-local, metadata, host, management, other challenge instances. |

**Attachments:** proxy/components must have **minimal network attachments** (prefer 1:1). No shared multi-tenant challenge bridge. **Ports:** only catalog-approved `approved_container_port` routable. **Proxy restrictions:** no Docker socket, no broker/manager admin, no DB, no firewall privileges.


## 3) Challenge Lifecycle & Rollback

1. Student requests instance → Django validates auth/ownership
2. Manager validates approved spec (catalog/digest/limits/policy)
3. Broker creates isolated network (ownership recorded)
4. Broker creates challenge container (labels/ownership, verified)
5. Per-instance gateway configured (1:1)
6. Firewall policy installed & verified (per-dest/port, default-deny)
7. Mapping API publishes authorized route
8. **ACTIVE** only if all controls verified
9. Session expires/revoked → invalidate routes
10. Established connections terminated/blocked per policy
11. Gateway detached/removed
12. Container stopped/removed (verified)
13. Network removed (ownership-verified)
14. Ownership/audit finalized

**Rollback:** at any failure → fail closed, no promotion to ACTIVE, compensating cleanup, record in orphan/ownership, routes blocked, never claim success without verification.


## 4) Network & Firewall Specification

**Requirements:** default-deny, per-instance destination + approved port, symmetric IPv4/IPv6, block host-originated/forwarded to mgmt/LAN/host/link-local/metadata/internet, block bridge-to-bridge, enforce in **DOCKER-USER** before NAT, conntrack for established/related, DNS restricted/default-deny, safe install/verify/revoke/recover. Do not apply commands now.


## 5) Broker & Ownership Requirements

Broker must validate ops, only approved images+immutable digests, independent policy validation, manage approved nets/containers, persistent ownership, reject unknown/unowned, idempotent, structured audit. **Network ownership independent of Docker labels.** Handle creation/persistence/removal failures, host restart, duplicates, orphans. **Unknown resources never auto-deleted.**


## 6) Proxy & Gateway Security

Central ingress: auth/routing only, no Docker/socket/admin/DB/firewall. Per-instance gateway: 1:1 only. Mapping API: read-only fail-closed (ownership/session/expiry/approved port), no client-supplied targets, Host-header validated, SSRF prevented, stale/malformed rejected, immediate revocation. Connection limits/timeouts/WS limits.


## 7) Resource & Capacity Planning (Estimates Only — Not Benchmarked)

| Component | Memory (est.) | CPU (est.) | Notes |
|---|---|---|---|
| Central ingress | 30-60 MB | 5-10% | Minimal if routing only |
| Per-instance gateway | 30-60 MB | 2-5% | Per instance |
| Challenge container | 64-256 MB (per limits) | 0.1-0.5 cores | Per catalog profile |
| Broker/Manager/Django | 150-300 MB total | 5-15% | Control plane |
| Firewall/logging | 10-30 MB | 1-5% | Overhead |
| **Total (conservative)** | **~400-800 MB overhead + containers** | **<50% typical** | Leave headroom on 3.8 GiB |

**POC limits (conservative):** **1-2 concurrent challenge instances max**, 1 central + 1-2 gateways, 50-80 MB/gateway, 50-100 conns/gateway, 3600s max lifetime. **Must benchmark before increasing.**


## 8) Security Validation Plan (Key Acceptance Tests)

Isolation: cross-instance blocked; challenge→mgmt/host/LAN/metadata/internet/DNS blocked; IPv4+IPv6 symmetric. Proxy: no Docker/broker/admin access; no unauthorized instances; stale mappings rejected. Lifecycle: safe rollback, expiry revocation, established connections handled, partial cleanup recoverable, reboot safe. Persistence: ownership survives restart, unknown networks not deleted, orphan recovery idempotent, no secret leakage. Each test requires preconditions, actions, expected behavior, evidence, pass/fail.


## 9) Implementation Roadmap (Reviewable Milestones)

| Phase | Focus | Dependencies | Deliverables | Acceptance/Rollback |
|---|---|---|---|---|
| **2K** | Broker & network lifecycle | Catalog/ownership design | Persistent ownership, network/container ops, orphans | Fail closed, idempotent, rollback on failure |
| **2L** | Network isolation & firewall controller | 2K, DOCKER-USER design | Per-instance rules, verification, revocation, reconciliation | Verified before ACTIVE, stale rule removal |
| **2M** | Per-instance gateway | 2K/2L | 1:1 gateway, routing limits, isolation | No mgmt access, 1:1 enforced |
| **2N** | Central ingress & mapping API | 2M, auth | Fail-closed mapping, revocation, WS/limits | No arbitrary targets, ownership verified |
| **2O** | Recovery, reconciliation & audit hardening | 2K-2N | Orphan recovery, restart tests, audit | Idempotent, unknown networks protected |
| **2P** | Controlled first challenge deployment | 2O | Single instance test in lab | All controls verified |
| **2Q** | Security validation & concurrency benchmarking | 2P | Full matrix + benchmarks | Decide capacity increase only if passed |


## 10) Final Readiness Decision

**NOT READY — SECURITY GAPS REMAIN.**

### Unresolved issues (must be addressed)
- **1:1 dynamic attachment guarantee** (atomicity/races) — critical for Option A; easier with Option D but complex
- **Dynamic firewall rule management** (DOCKER-USER ordering, bridge/veth, rule drift)
- **IPv4/IPv6 symmetry enforcement/disablement**
- **Mapping API reliability & fail-closed guarantees**
- **Ownership verification independent of Docker labels (robust)**
- **Orphan reconciliation for networks/attachments**
- **Proxy host-originated egress restrictions**
- **Connection tracking after revocation**
- **Resource feasibility of Option D on 2 vCPUs/3.8 GiB (needs benchmarking)**
- **Lab validation of full security test matrix**

### Which phase must address
- Attachment/state machine + control plane: **2L/2M**
- Firewall + DOCKER-USER: **2L**
- Mapping API + ingress: **2N**
- Recovery/orphans/audit: **2O**
- Validation/benchmarks: **2Q**

**Do not declare production-ready.** Implementation should only proceed via the milestone roadmap with lab validation.


## Completion Report

1. **Files created/modified:** Updated `ctf-platform-be/docs/PHASE_2I_CHALLENGE_NETWORK_ISOLATION_ARCHITECTURE.md` (Phases 2I.1-2I.3 appended). Created `ctf-platform-be/docs/PHASE_2J_RUNTIME_ISOLATION_READINESS.md` (this document).
2. **Architecture selected:** Option D (hybrid central ingress + per-instance gateways) long-term; Option A only with strict guarantees. Alternatives compared.
3. **Network/firewall design:** Zones defined, default-deny, per-dest/per-port, symmetric IPv4/IPv6, DOCKER-USER, bridge-to-bridge blocked, conntrack, DNS/internet/host/LAN/metadata blocked.
4. **Lifecycle/rollback:** 16-step lifecycle with rollback at every failure, no ACTIVE without verification.
5. **Security test matrix:** Isolation/proxy/lifecycle/persistence covered with evidence requirements.
6. **Resource/concurrency estimates:** Estimates only (not benchmarked); POC 1-2 instances max.
7. **Remaining security gaps:** 10 items listed above.
8. **Implementation sequence:** 2K→2L→2M→2N→2O→2P→2Q.
9. **Readiness decision:** **NOT READY — SECURITY GAPS REMAIN.**
10. **Confirmation:** No code, Docker, infrastructure, firewall, routing, NAT, IPv4/IPv6, UDS, or runtime provisioning changes occurred. Documentation only. Runtime provisioning remains disabled.
