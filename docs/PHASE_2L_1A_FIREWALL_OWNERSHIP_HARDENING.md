# Phase 2L.1a — Firewall Policy Ownership and Validation Hardening

**Date:** 2026-11-01  
**Status:** Implemented. No real firewall/Docker/infrastructure changes. Mocked controller only.

## Original vulnerabilities (from audit)
- Caller-supplied network/instance/IP/subnet/ports not cross-verified against persistent ownership
- Policy objects could be created without ownership verification; compiler trusted them
- IPv4-mapped IPv6 allowed; broad CIDRs (/0) not rejected; "both" IP version ambiguous
- VERIFIED could be set without positive controller verification
- Proxy had firewall admin authority in model

## Ownership resolution design
- `FirewallPolicyModel.create_policy()` requires `network_store` and verifies network via `PersistentNetworkOwnershipStore.verify()`
- Network must be active and owned by broker; instance must match network's `instance_id`
- Container ownership verified via `PersistentOwnershipStore.verify()` if provided
- Caller cannot override resolved values; all targets marked `verified=True`, policy marked `ownership_verified=True`
- Missing/inconsistent/deleted/stale/orphaned ownership -> fail closed

## Trusted vs untrusted inputs
- Trusted: broker-generated IDs, persistent ownership records (network_ownership, container ownership)
- Untrusted: caller-supplied network_id/instance_id/IP/subnet/port/labels/metadata/ownership claims - never used as authority

## IP normalization rules
- Explicit IPv4/IPv6; reject IPv4-mapped IPv6 (`::ffff:...`)
- Reject "both" in this phase
- Normalize via `ipaddress`; reject malformed
- Reject loopback/link-local/multicast/reserved
- Reject prefixlen 0 (/0, ::/0)
- IP version must match policy's ip_version

## CIDR restrictions
- Reject unrestricted (/0, ::/0)
- Reject broad/unrestricted; allow only verified challenge-network destinations (Docker private subnets allowed if verified)
- Block host/LAN/metadata/loopback/link-local/multicast/reserved

## Compiler trust boundary
- Compiler requires `policy.ownership_verified` and all targets `verified`
- Rejects proxy as source
- Produces only broker-verified targets

## Proxy authority restrictions
- `ALLOWED_SOURCES` removed `proxy`; proxy cannot be authorized firewall source
- Proxy has no firewall admin privileges (enforced)

## Tests added
Added regression tests in `broker/tests/test_firewall_policy_hardening.py` for arbitrary IDs, ownership mismatch, unknown/deleted/orphaned, caller-supplied IP/subnet differing, IPv4-mapped IPv6, IP mismatch, /0, ::/0, unauthorized destinations, DNS, host/external, unverified policy to compiler, mutation after validation, proxy source rejected. Existing valid cases preserved.

## Remaining limitations
- No live controller integration; not wired to routes yet
- Some special address checks applied; full subnet membership validation against owned network details could be enhanced
- "both" rejected in this phase by design
