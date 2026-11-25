# Phase 2L.2D.2 — Security Design Remediation (Documentation Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Scope:** Documentation only. No implementation/infrastructure changes.

## 1) Traceability (all findings)
| Finding ID | Severity | Remediation section | Design correction | Remaining validation requirement | Status |
|---|---|---|---|---|---|
| SR-001 | High | A. UDS Security | Strict dir/socket perms, realpath, SO_PEERCRED, no identity headers, startup handling, limits/timeouts | Host UDS testing (symlink/TOCTOU) | PARTIALLY REMEDIATED |
| SR-002 | High | B. Privilege/Capabilities | Compare models, prefer dedicated service + minimal caps, no broad sudo, caps not assumed sufficient | Lab test minimal caps per backend | PARTIALLY REMEDIATED |
| SR-003 | High | C. Ownership/Recovery | Controller DB schema, transactions/locks, audit persistence, corruption/reboot/restart, unknown rules never adopted | DB crash/recovery testing | PARTIALLY REMEDIATED |
| SR-004 | High | D. Docker/nftables | Detection, hook priorities, DOCKER-USER, IPv4/IPv6, NAT/conntrack, ordering, atomic+rollback, matrix | Host-lab validation required | PARTIALLY REMEDIATED |
| SR-005 | High | E. Evidence Binding | Evidence binds identity/ownership/policy/digest/families/rules/tx/time; read-back required; no caller boolean | Evidence replay/stale testing | PARTIALLY REMEDIATED |
| SR-006 | Medium | A. UDS | Supplementary groups ignored; UID/GID allowlist only | Peer auth tests | PARTIALLY REMEDIATED |
| SR-007 | Medium | D,F | IPv6 symmetry, metadata/CGNAT/link-local, conntrack after revoke, SSRF/LAN/host | Isolation tests | PARTIALLY REMEDIATED |
| SR-008 | Medium | C | Markers never sufficient; broker-generated key in sets/maps + independent index | Marker spoof tests | PARTIALLY REMEDIATED |
| SR-009 | Medium | F/Threats | Concrete controls for races/corruption | Fault injection | PARTIALLY REMEDIATED |
| SR-010 | Low | G/Testing | Explicit mock limitations; require host-level adversarial tests | Host-lab tests | PARTIALLY REMEDIATED |

## 2) A. UDS Security (detailed)
- **Socket dir:** `/run/flaghunt/` owned by controller group, mode 0700 (or 0750) 
- **Socket:** owned by controller:controller-group, mode 0660
- **Protection:** resolve realpath, reject symlinks, handle existing socket on startup (remove only if owned/validated), SO_PASSCRED
- **AuthN:** SO_PEERCRED UID/GID/PID; supplementary groups ignored
- **AuthZ:** operation allowlist per UID/GID
- **Limits:** request size, timeouts, connection limits
- **Replay/idempotency:** keys required, tracked
- **No identity headers trusted**

## 3) B. Privilege and Capability Model
| Model | Authority | Attack Surface | Failure Impact | Complexity | Limitations |
|---|---|---|---|---|---|
| Root-owned | Full | Highest | Critical | Low | Unacceptable unless heavily contained |
| Dedicated service + minimal caps (CAP_NET_ADMIN, CAP_NET_RAW as needed) | Minimal | Reduced | High | Medium-High | Caps not always sufficient alone |
| Privileged helper | Subset | Contained | High | High | Still privileged |
| Rootless | Minimal | Lowest | Limited | Very High | Often infeasible for nftables/iptables |

**Preferred:** Dedicated service account + minimal capabilities, no shell, no broad sudo. Capabilities require host validation.

## 4) C. Persistent Ownership and Recovery
**Proposed schema:** ownership_record_id, policy_id, policy_version, instance_id, network_id, canonical_policy_digest, installed_rule_ids_json, address_family, installation_state, verification_evidence_ref, created_at, revoked_at, last_reconciliation_at, reconciliation_status.  
**Constraints:** unique (policy_id,policy_version), indexes. **Rules:** transactions, locks, audit persistence, crash consistency, backups/integrity checks. **Recovery:** never auto-adopt unknown rules; reconcile by ownership index + read-back.

## 5) D. Docker and nftables Compatibility
Host-lab matrix required: Docker backend detection, nftables/iptables, DOCKER-USER, hook priorities, forwarding, bridge, published ports, IPv4/IPv6, NAT/masquerading, conntrack, ordering, atomic install/rollback, concurrent ops. Compatibility not assumed from installation alone.

## 6) E. Evidence Binding
Evidence must bind: controller_identity, ownership_record_id, policy_id, policy_version, instance_id, network_id, canonical_policy_digest, address_family, exact installed_rule_ids, verification_timestamp, verification_result, controller_transaction_id, request_id/operation_id. Generated from read-back, persisted, integrity-checked, replay/stale prevented. No caller boolean trusted; ACTIVE/VERIFIED require independent evidence.

## 7) F. Lifecycle State Machine
States: REQUESTED, VALIDATING, INSTALLING, VERIFYING, VERIFIED, ACTIVE, REVOKING, REVOKED, CLEANUP_PENDING, FAILED, ORPHANED. Rules: ACTIVE only after VERIFIED+evidence; partial never success; revoke routing before cleanup; failures never false success; recovery ownership-safe; concurrency validated.

## 8) G. Threat Model Update (key)
Covers broker/controller/proxy/challenge/local process/UDS manipulation/forged metadata/DB corruption/IPv6 bypass/DNS tunneling/SSRF/conntrack/Docker mismatch/partial tx/lost response/races with residual risks noted.

## 9) H. Testing Strategy
Unit/integration/host-lab/adversarial defined; mocks cannot prove isolation.

## 10) Readiness Assessment
- Design completeness: **IMPROVED** (gaps addressed in design)
- Readiness for implementation planning: **CONDITIONAL** (need host-lab plan)
- Readiness for mocked implementation: **CONDITIONAL** (within mocks only)
- Readiness for host-lab validation: **NOT READY** (environment not prepared)
- Readiness for live firewall integration: **NOT READY** 

**Final Status:** `NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED`

## Final Report
- Files created: `docs/PHASE_2L_2D_2_SECURITY_DESIGN_REMEDIATION.md`
- Files modified: none
- All 10 findings mapped with statuses (all PARTIALLY REMEDIATED)
- Remaining assumptions: privilege model, UDS hardening details, controller DB, Docker/nftables behavior
- Host-lab validation required before implementation/live integration
- No implementation/infrastructure changes occurred
**Phase 2L.2D.2 complete. Awaiting explicit approval.**
