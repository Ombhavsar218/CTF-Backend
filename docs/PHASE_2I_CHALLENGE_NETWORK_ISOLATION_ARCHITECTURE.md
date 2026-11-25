## Phase 2I.3 — Dynamic Proxy Attachment and Concurrency Design

Design and documentation only.

**Topology:** Option D (hybrid central ingress + per-instance gateways) recommended long-term. Option A only if 1:1 dynamic attachment + per-destination/per-port firewall verified; Option C strongest isolation but resource-heavy.

**State machine:** DETACHED → ATTACHMENT_REQUESTED → ATTACHING → FIREWALL_CONFIGURING → ACTIVE → REVOKING → DETACHING → CLEANUP_PENDING/FAILED. No ACTIVE without verification; routes invalidated before detachment.

**Controls:** Trusted control plane only (no proxy socket/admin/DB/firewall), default-deny + DOCKER-USER + per-destination/per-port, fail-closed mapping API, persistent network_ownership + network orphan recovery.

**POC limits (est.):** 1-2 instances, 1 central or 1-2 gateways, 50-80 MB/gateway, 50-100 conns, 3600s lifetime. Not benchmarked.

**Risks:** 1:1 attachment guarantee, dynamic firewall rules/DOCKER-USER, IPv6 bypass, mapping API reliability, orphan reconciliation, Option D resource feasibility.

**Confirmed:** No infrastructure/Docker/firewall/routing/NAT/IPv4-IPv6/UDS/system/runtime/code changes. Design only. Runtime provisioning remains disabled.
