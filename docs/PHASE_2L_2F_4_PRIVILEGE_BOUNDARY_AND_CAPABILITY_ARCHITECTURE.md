# Phase 2L.2F.4 — Privilege Boundary and Capability Architecture (Design-Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Decision:** CONDITIONAL — Important privilege decisions remain unresolved

## 1) Architecture comparison
- **A) Controller with capabilities:** Simpler but larger attack surface
- **B) Unprivileged controller + privileged helper (RECOMMENDED):** Strong separation, limited blast radius
- **C) Root service:** Excessive privilege, not recommended

## 2) Capability analysis
| Operation | Required | Capability | Notes |
|---|---|---|---|
| nftables/iptables rule changes | Yes | CAP_NET_ADMIN | Must be narrowly scoped |
| Rule inspection/read-back | Varies | CAP_NET_ADMIN or none | Prefer read via appropriate APIs |
| Socket operations | No | None | Unprivileged |

## 3) Privileged helper contract (recommended)
- Fixed binary path, enum operations only
- Peer verification, strict validation
- No shell, no arbitrary scripts
- Timeouts, audit logging
- Idempotent where possible

## 4) systemd and filesystem
- Dedicated users/groups
- Socket permissions 660, restricted dir
- NoNewPrivileges, CapabilityBoundingSet minimal
- Read-only where possible

## 5) Threat analysis
Compromised broker/controller/helper mitigated by separation

## 6) Recommendation
**B) Unprivileged controller + privileged helper** preferred pending Linux validation.

**FINAL DECISION:** CONDITIONAL — **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
