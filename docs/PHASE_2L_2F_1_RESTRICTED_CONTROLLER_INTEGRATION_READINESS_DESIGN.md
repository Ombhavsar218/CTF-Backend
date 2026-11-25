# Phase 2L.2F.1 — Restricted Controller Integration Architecture and Readiness Design (Design-Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Decision:** CONDITIONAL — Architecture documented, but important design decisions remain unresolved

## 1) Executive architecture
Manager → Restricted Broker → Restricted Firewall Controller → Host Firewall  
Controller is a separate security boundary. Broker must not receive unrestricted host privileges.

## 2) Trust boundaries
- Broker: orchestrates, no direct privileged firewall ops
- Controller: isolated, authenticated via UDS + SO_PEERCRED
- Host: firewall enforcement (nftables/iptables)

## 3) Communication contract
- Unix Domain Socket, directory perms restricted
- SO_PEERCRED for peer UID/GID, explicit allowlists
- No trust in caller headers
- Size limits, timeouts, idempotency
- Safe errors

## 4) Persistent ownership
- Controller-owned SQLite, independent from Broker
- Policy/instance binding, unique constraints
- CAS/versioning, durable idempotency
- Audit history, recovery

## 5) Firewall backend
- nftables preferred, iptables+DOCKER-USER fallback
- IPv4/IPv6, atomic install/rollback, read-back verification, revocation/cleanup

## 6) Privilege separation
- Dedicated service account, minimal capabilities
- No Docker socket, no unrestricted sudo
- Hardened systemd, restricted dirs

## 7) Lifecycle and evidence
States: DETACHED → ATTACHMENT_REQUESTED → ATTACHING → FIREWALL_CONFIGURING → ACTIVE → REVOKING → DETACHING → CLEANUP_PENDING/FAILED  
ACTIVE requires valid persisted evidence from backend read-back

## 8) Threat model (high level)
Compromised broker, forged ownership, partial installs, reboot, IPv4/IPv6 divergence

## 9) Failure and recovery
Persistence failures block transitions, rollback on failure, restart recovery

## 10) Future staged validation
Stage A: Mock contract; B: UDS+auth; C: Ownership+crash-recovery; D: nftables backend; E: Docker+IPv4/IPv6; F: Security review

## 11) Outstanding risks
SO_PEERCRED portability, Docker chain ordering, conntrack, nftables/iptables compatibility, atomicity across SQLite and backend

**CONCLUSION:** Design complete. **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
