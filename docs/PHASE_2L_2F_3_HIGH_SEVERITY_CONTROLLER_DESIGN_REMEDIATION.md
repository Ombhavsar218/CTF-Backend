# Phase 2L.2F.3 — High-Severity Controller Design Remediation (Design-Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Decision:** CONDITIONAL — One or more High-severity findings remain unresolved

## 1) ARC-001 — SO_PEERCRED platform support
- **Supported:** Linux (kernel with SO_PEERCRED), fail-closed if unavailable
- **Auth:** UID/GID allowlists, no trust in headers
- **Socket:** restricted perms, validated path

## 2) ARC-002 — SQLite and firewall atomicity
- **Approach:** Persist intent first, track state machine, verify with read-back
- **Recovery:** reconciliation on startup, compensating rollback, uncertain outcomes block ACTIVE
- **No distributed atomicity claimed**

## 3) ARC-003 — Docker firewall ordering
- **Preferred:** nftables with explicit hooks; iptables+DOCKER-USER as fallback
- **Ordering:** validate actual rules, test compatibility
- **IPv4/IPv6 symmetry required**

## 4) ARC-004 — Evidence authenticity
- **Model:** controller-generated, bound to ownership/policy/digest/read-back
- **Limitations:** application-level mock evidence, not host-proof

## 5) ARC-005 — Privilege separation
- **Account:** dedicated, minimal capabilities
- **Restrictions:** no sudo, no Docker socket
- **Capabilities:** justified per operation

## 6) Remaining assumptions
SO_PEERCRED portability, Docker version compatibility, nftables support

## 7) Unresolved questions
Exact capability sets, helper process design

**FINAL DECISION:** CONDITIONAL — **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
