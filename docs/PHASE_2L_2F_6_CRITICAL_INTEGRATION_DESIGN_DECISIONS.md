# Phase 2L.2F.6 — Critical Integration Design Decisions and Failure-State Resolution (Design-Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Decision:** CONDITIONAL — Important decisions or validation requirements remain unresolved

## 1) Recoverable operation protocol
- Persist intent before side effects
- Idempotency keys, operation IDs
- Execute via helper, read-back verify
- Evidence persistence before promotion
- Compensating rollback on failure
- Reconciliation on restart

## 2) Crash-state matrix
Covers all interruption points, uncertain outcomes block ACTIVE

## 3) Docker firewall compatibility
- Prefer nftables; test ordering
- Support iptables+DOCKER-USER fallback
- IPv4/IPv6 symmetry
- Validate actual rules

## 4) Platform support
- Linux only, kernel with SO_PEERCRED required
- Fail-closed on unsupported

## 5) Privileged helper contract
- Enum operations, typed schema
- Peer auth, no shell/arbitrary scripts
- Timeouts, audit, idempotency

## 6) Remaining decisions
- Exact capability set
- Helper binary location
- Test environment specs

**FINAL DECISION:** CONDITIONAL — **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
