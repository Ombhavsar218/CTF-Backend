# Phase 2L.2A — Live Firewall Controller Interface Contract (DESIGN ONLY)

**Date:** 2026-11-02  
**Status:** Design/documentation only. No live firewall implementation. No infrastructure changes.

## 1) Architecture
```
Firewall Policy Engine (broker)
  ↓ (verified policy + compiled rules + digest)
Firewall Controller Interface (contract)
  ↓ (restricted, UDS, peer creds)
Restricted Firewall Controller Service (separate, least privilege)
  ↓
Host Firewall Backend (nftables OR iptables+DOCKER-USER)
  ↓
Installed Rule Verification (read-back + digest + ownership)
```

## 2) Backend comparison
| Aspect | nftables | iptables + DOCKER-USER |
|---|---|---|
| Docker compatibility | Good with nftables integration; need care with chains | DOCKER-USER exists but ordering/complexity; legacy |
| IPv4/IPv6 | Native family support, cleaner | Separate iptables/ip6tables |
| Rule ownership | Can use sets/maps + comments + custom marks; need strong ownership IDs | Comments/marks possible but fragile |
| Atomic updates | `nft -f` with atomic transactions where possible | Less atomic by default; script-based |
| Rollback | Transactional + snapshots | Harder, error-prone |
| Persistence | Ruleset can be saved; versioned | Rules saved separately per family |
| Verification | Read-back via `nft list ruleset` with filtering | Read-back via iptables-save |
| Failure recovery | Better structure | More manual |
| Complexity | Modern but requires nftables present | Widely present but fragile |

**Recommendation:** Prefer **nftables** as primary (cleaner atomicity, unified IPv4/IPv6 handling), with iptables+DOCKER-USER only as fallback if nftables unavailable. Both require same ownership/verification model.

## 3) Controller API contract
All requests/responses include: `request_id`, `timestamp`, `controller_id`, `controller_version`, `operation_id`/`idempotency_key`. Broker-generated: policy_id, policy_version, compiled_rule_digest, instance_id, network_id, ownership_id. Controller-generated: operation results, actual rule IDs/handles.

Operations:
- `health_check()` → `{status, controller_id, version, families_supported, capabilities}`
- `install_policy(req)` → `{status, installed, verified_readback, rule_handles, errors[], digest_verified}`
- `inspect_policy(req)` → `{status, rules[], ownership_match, digest_match}`
- `verify_policy(req)` → `{status, verified, readback_match, digest_match, evidence{...}}`
- `revoke_policy(req)` → `{status, revoked, partial[], errors[]}`
- `remove_stale_policy(req)` → `{status, removed[], skipped[], errors[]}`
- `reconcile_pending_operations(req)` → `{status, reconciled[], pending[], unknown[]}`

Reject: host paths, shell commands, arbitrary chains/expressions, arbitrary interfaces.

## 4) Rule ownership model
- Broker-generated ownership key: `fh:<policy_id>:<policy_version>:<instance_id>:<network_id>:<digest_prefix>`
- Stored as non-removable marker (custom set/map element + encrypted/structured comment)
- Tracked per family (IPv4/IPv6)
- Survives restart via persisted ownership index
- Never delete unowned rules
- Partial ownership tracked

## 5) Installation and rollback
Sequence: validate → revalidate ownership → version check → digest check → prepare → atomic apply → read-back → verify exact match → record evidence → VERIFIED only after broker evidence validation. Rollback on any failure; partial installs never reported as success.

## 6) IPv4/IPv6
Separate families, dual-stack tracked independently. Partial failure blocks VERIFIED. No IPv6 bypass. Missing family handled explicitly.

## 7) Docker integration
Consider Docker bridges, per-instance networks, container-to-container/host, egress, DNS, forwarding, NAT, DOCKER-USER chain ordering, conntrack. Application-level isolation insufficient; host firewall required. Prevent host/LAN/metadata/other-challenge access.

## 8) Revocation and cleanup
Idempotent, invalidate before cleanup, partial revocation tracked, unknown rules untouched, orphaned ownership recovered via reconcile, conntrack considerations.

## 9) Privilege separation
Separate controller service (not manager/broker), UDS with peer creds (uid/gid), narrow allowlist, minimal capabilities (NET_ADMIN/NET_RAW as needed), no shell, audit all operations. Prefer capability-restricted over full root where possible.

## 10) Persistence and recovery
Broker and controller state reconciled; operation state machine; never infer success from send; verify digest/version on recovery.

## 11) DNS and egress
Default deny DNS/egress; only designated resolvers if explicitly allowed; block metadata (169.254.169.254, fe80::/10 link-local, etc.), private LAN by default.

## 12) Audit events
Installation/verfication/revocation/reconciliation/unknown rule/controller unavailable - no secrets logged.

## 13) Threat model (summary)
Controller/broker/proxy/challenge compromise, backend unavailable, kernel reload, IPv6 bypass, chain reordering, tampering, DB corruption, lost responses, concurrent ops, reboot - mitigated by ownership, verification, fail-closed, evidence binding.

## 14) Implementation roadmap
1. Interface contract approval (this doc)  
2. Mock controller parity tests  
3. Controller service skeleton (separate, no activation)  
4. nftables backend prototype (lab only)  
5. Ownership/verification/reconciliation  
6. Integration tests with broker  
7. Security validation

## 15) Readiness checklist
- [ ] Contract reviewed/approved
- [ ] Backend chosen for target env
- [ ] Privilege model approved
- [ ] Lab environment prepared (isolated)
- [ ] Rollback tested
- [ ] All Phase 2L.1 tests pass

**This is design only. No code/infra changes made.**
