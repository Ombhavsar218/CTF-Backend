# Phase 2L.2D.1 — Independent Security Review (Read-Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Scope:** Design review only. No implementation/infrastructure changes.

## 1) Executive summary
The design is comprehensive and correctly adopts fail-closed, independent verification, and ownership separation principles. However, multiple host-specific and implementation details remain unresolved (privilege model, Docker/nftables interaction, UDS hardening details, persistence/recovery guarantees). No Critical findings from document review alone, but several High/Medium gaps require validation before live integration.

## 2) Review scope and limitations
Reviewed: `PHASE_2L_2D_CONTROLLER_SECURITY_AND_INTEGRATION_DESIGN.md`, `PHASE_2L_2A_LIVE_FIREWALL_CONTROLLER_INTERFACE_CONTRACT.md`, `PHASE_2L_2B_MOCK_CONTROLLER_CONTRACT_PARITY.md`. Read-only; no code execution/tests run beyond document inspection.

## 3) Architecture assessment
- Manager→Broker→Controller→Firewall boundary is sound; controller must independently validate.
- Risk: compromised broker could send malicious requests; controller allowlist + validation + ownership checks are required (design states this) but enforcement details unverified.

## 4) Detailed security findings

| Finding ID | Severity | Affected section | Description | Attack/Failure scenario | Impact | Evidence | Recommended remediation | Host validation required |
|---|---|---|---|---|---|---|---|---|
| SR-001 | High | 2 UDS Auth | SO_PEERCRED auth described but no concrete enforcement details (socket dir perms, symlink protection, TOCTOU) | Attacker replaces socket/symlink or abuses directory perms to impersonate | Privilege escalation/unauthorized control | 2L.2D §2 | Enforce strict dir (0700), socket (0660), resolve realpath, set SO_PASSCRED, reject non-broker UIDs, no identity headers | Yes |
| SR-002 | High | 3 Privileges | Capability requirements vague; sudo discouraged but alternatives not proven | Over-privileged service exploited | Host compromise | 2L.2D §3 | Test minimal caps in lab, prefer nftables set/map ownership, avoid full root; document exact caps | Yes |
| SR-003 | High | 4 Ownership/Recovery | Controller DB schema/details missing; corruption/restart semantics underspecified | Restart during partial install leaves orphan rules | Policy bypass/persistence issues | 2L.2D §4, 2L.2A §10 | Define schema, reconciliation state machine, backups, fail-closed on DB errors | Yes |
| SR-004 | High | 5 nftables/Docker | Docker chain ordering/DOCKER-USER/nftables hooks not concretely verified | Rules bypassed by Docker iptables/nftables rules | Isolation bypass | 2L.2D §5-6 | Lab test with actual Docker version; verify effective packet path | Yes |
| SR-005 | High | 7 Lifecycle/Recovery | "Never promote without verification" stated but evidence binding details incomplete | False VERIFIED from lost response | Policy enforcement failure | 2L.2D §7, 2L.2A §5 | Enforce evidence in DB with atomic transitions, no boolean trust | Yes |
| SR-006 | Medium | 2 UDS | Supplementary groups not addressed explicitly as untrusted | Group membership exploited | Authz bypass | 2L.2D §2 | Explicitly ignore supplementary groups; allowlist by UID/GID only | Yes |
| SR-007 | Medium | 6 Network isolation | IPv6/conntrack/metadata/SSR specifics need verification | Bypass via IPv6, DNS, metadata, established flows | Egress bypass | 2L.2D §6,8 | Test IPv6 symmetry, block ::ffff/metadata, conntrack after revoke | Yes |
| SR-008 | Medium | 4 Ownership | "Never trust comments/labels" stated but marker format not enforced | Marker spoofing if logic flawed | Rule deletion of foreign rules | 2L.2A §4 | Enforce broker-generated key in sets/maps, independent index | Yes |
| SR-009 | Medium | 8 Threat model | Some threats listed but mitigations not all concrete | Races/corruption gaps | Residual risk | 2L.2D §8 | Add concrete controls/tests | Yes |
| SR-010 | Low | 9 Testing | Mock tests cannot prove isolation (acknowledged) | Over-reliance on mocks | False confidence | 2L.2D §9 | Require host-level adversarial tests before approval | Yes |

## 5) Attack scenarios (key)
- Broker compromise → controller must reject via allowlist/validation
- UDS socket hijack → prevented by perms/peer creds/realpath
- IPv6 bypass → requires symmetric rules + forwarding checks
- Revocation + conntrack → existing flows may persist; need drop/conntrack flush strategy
- Docker reordering → DOCKER-USER/nftables hook priority critical

## 6) Testing gaps
- **Unit:** authz edge cases, validation (done partially in mocks)
- **Integration:** broker-controller over UDS (not implemented)
- **Host-level:** nftables/Docker interaction, IPv4/IPv6 symmetry, published ports
- **Adversarial:** bypass attempts, race conditions
- **Recovery/fault-injection:** restart, DB corruption, lost responses

## 7) Recommended corrections
1. Specify UDS hardening (dir/socket perms, realpath, SO_PASSCRED, no identity headers)
2. Define minimal capabilities per backend with lab evidence
3. Design controller DB schema + reconciliation
4. Plan Docker/nftables host validation tests
5. Enforce evidence binding in all transitions

## 8) Prioritized remediation roadmap
P0: Privilege/UDS hardening design details + lab plan  
P1: Ownership persistence schema + reconciliation  
P2: Docker/nftables compatibility tests  
P3: Adversarial/recovery tests

## 9) Final readiness assessment
**NOT READY — LIVE FIREWARK INTEGRATION NOT AUTHORIZED**  
Even with no Critical findings, High/Medium gaps require host validation. Mock tests cannot prove isolation.

## Final Execution Report
- **Documents inspected:** PHASE_2L_2D, PHASE_2L_2A, PHASE_2L_2B
- **Files created:** `docs/PHASE_2L_2D_1_INDEPENDENT_SECURITY_REVIEW.md`
- **Files modified:** none
- **Findings:** Critical: 0, High: 5, Medium: 4, Low: 1, Informational: 0
- **Main security gaps:** UDS hardening, privilege model, Docker/nftables compatibility, ownership persistence/recovery, evidence binding
- **Documentation checks:** Consistency verified across phases; design correctly states NOT READY
- **Confirmation:** No implementation/infrastructure changes occurred
**Status:** Review complete. Awaiting explicit approval.
