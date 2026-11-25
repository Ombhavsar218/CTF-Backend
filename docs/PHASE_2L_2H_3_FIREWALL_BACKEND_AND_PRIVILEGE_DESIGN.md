# Phase 2L.2H.3 — Firewall Backend and Privilege Design

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Phase:** 2L.2H.3  
**Date:** 2026-11-13  
**Status:** **DESIGN ONLY — NO IMPLEMENTATION AUTHORIZED**  
**Integration gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**Remediation:** 2L.2I.2 documentation-only overlay, amended by 2L.2I.4; design decisions below
control where they conflict with earlier text. The rule model in Section 3.3 is a mapping to the
canonical `rule-schema-v1` in 2H.1 Section 4.4.1 and does not independently define it. No runtime
control is implemented.

This document is the firewall-backend and privilege-separation design for the target architecture
in `PHASE_2L_2H_1_REAL_TRANSPORT_TARGET_ARCHITECTURE.md`. It is theoretical. It does not install
or modify nftables, iptables, Docker, capabilities, services, users, routes, NAT, conntrack, or
host firewall state.

> **Current versus future.** Today the controller uses a mock backend and in-memory mock firewall
> state. There is no real privileged helper, no capability grant, and no host rule. The nftables and
> iptables designs below are proposals. Current mock tests do not prove backend behavior, Docker
> compatibility, or privilege safety.

---

## 1. Current backend state

| Area | Current implementation | Not yet implemented |
|---|---|---|
| Controller backend seam | `FirewallBackendInterface` with mock operations | Real nftables/iptables implementation |
| Controller-to-helper | `MockFirewallBackend` -> `MockHelperExecutor` | Real UDS, real helper process |
| Privilege | No real privileges | Dedicated helper user/capability |
| Rule ownership | Controller SQLite ownership records; mock helper contract | Real chain/rule markers, read-back, handle tracking |
| IPv4/IPv6 | Contract supports address families | Real dual-stack enforcement and evidence |
| Docker | Mock Docker adapter only | DOCKER-USER/nftables coexistence validation |
| Persistence | Mock state and SQLite evidence | Kernel rule persistence and boot reconciliation |
| Audit | Mock audit sink | Durable helper/controller audit with sanitization |

The current `MockFirewallController` is not a firewall. It must not be cited as evidence that a
real backend is safe, idempotent, atomic, or Docker-compatible.

### 1.1 Carried residual dependencies

Backend/privilege work depends on the open residuals in 2H.2 Section 6: RR-01/RR-02/RR-03
canonical IDs, RR-04 `policy_version` range/type, RR-05 full-scan reconciliation, RR-06/I-3.9-01
digest DB `CHECK`, and RR-07/I-3.9-03 exception context. In particular, canonical policy
digests/versions and ownership markers must be validated before a backend marker or evidence is
trusted. These residuals are not closed by the mock backend or by this design.

The informational residuals I-07, I-08, and I-09 are also carried here; they affect helper/backend
acceptance even though they are not backend-specific:

- **I-07 — Broader identifier/field scope.** Affected: helper contract fields, ownership references,
  and the controller/helper boundary. Impact: an unvalidated identifier or alias can bypass the
  canonical ownership/operation binding. Mitigation: apply the same canonical field/identifier
  rules at every helper entry point and add negative tests. Owner: 2H.3 helper contract workstream.
  Status: **OPEN — carried**. Closure: every helper field is validated by the same schema, with no
  legacy alias acceptance.
- **I-08 — Raw `BrokerDBError` on non-failure paths.** Affected: controller persistence/error
  mapping before helper dispatch and audit. Impact: SQLite/path/exception detail can leak into
  helper-facing errors or evidence. Mitigation: sanitized bounded error mapper on every path.
  Owner: controller persistence workstream. Status: **OPEN — carried**. Closure: helper-facing
  responses/audit never contain raw DB text; tests cover non-failure paths.
- **I-09 — `strict_auth=False` legacy footgun.** Affected: controller construction and the helper
  peer boundary. Impact: a misconfigured/mock controller can authorize without trusted identity.
  Mitigation: remove the switch from the live path and require `TrustedPeerIdentity`. Owner:
  controller implementation workstream. Status: **OPEN — carried**. Closure: production cannot
  select mock auth; an import/configuration test proves it.

A backend marker or read-back result is not trusted if these residuals remain open on the path that
produced it.

---

## 2. Backend selection

### 2.1 Recommendation

| Criterion | nftables | iptables + DOCKER-USER |
|---|---|---|
| Preferred target | **Primary** on supported Ubuntu Linux | **Compatibility fallback** only |
| IPv4/IPv6 | Native `inet` family and sets/maps | Separate `iptables` and `ip6tables` |
| Atomicity | Transactional batch via netlink/libnftables | `iptables-restore --noflush` per family; less clean across families |
| Ownership | Dedicated table/chains, comments, chain naming, structured JSON read-back | Custom chains, comments, `iptables-save` read-back; fragile |
| Docker coexistence | Separate table; hook/priority must be validated | DOCKER-USER jump; ordering and Docker restarts must be validated |
| Complexity | Moderate; requires nftables version/kernel validation | High; v4/v6 duplication and legacy behavior |
| Recommended role | Primary implementation | Only where nftables is unavailable or incompatible after lab proof |

**Decision status:** proposed, not approved. The exact nftables version, kernel, Docker mode, hook
priority, and fallback conditions must be established in the host validation lab. The fallback is
not a license to maintain two active backends at once; one backend must be selected per host and
recorded in evidence.

### 2.2 What the backend must never do

- Flush the host ruleset, Docker tables, or another service's chains.
- Edit Docker NAT tables or Docker-owned filter chains except a dedicated, owned
  `DOCKER-USER` jump in the validated fallback.
- Accept arbitrary rule text, chain names, table names, executable paths, or shell arguments.
- Delete rules merely because they look stale or unowned. Unknown rules are reported, not adopted
  or removed.
- Treat an unverified write as success.
- Persist challenge rules by rewriting the operator's global firewall configuration.

---

## 3. nftables primary design

### 3.1 Ownership model

The helper owns a dedicated nftables table, proposed as `inet flaghunt`. It does not own the host
ruleset, Docker tables, or operator baseline.

```text
table inet flaghunt
  chain fh_base_forward        # helper-owned base chain at a lab-validated forward hook
  chain fh_base_input          # only if host-input path is in scope and validated
  chain fh_p_<ownership-hash>  # one chain per ownership record / family as needed
  set fh_managed_v4            # managed challenge networks/addresses (if used)
  set fh_managed_v6
```

The exact hook priority and whether input/output base chains are required are **open decisions**.
They must be selected with traffic tests against Docker and the host, not guessed.

Proposed properties:

- The table and all chain names are fixed or derived from a helper-computed hash; callers never
  supply them.
- A per-ownership chain isolates one policy's rules and makes install/revoke/cleanup auditable.
- The base chain must not set a host-wide `drop` policy that breaks unrelated traffic. It should
  match managed challenge networks and drop unmatched managed traffic, while returning/accepting
  unrelated traffic according to the operator-approved baseline.
- If an unknown chain or rule exists inside the owned table and is not attributable to a known
  ownership record, the helper treats it as **drift/unknown**, reports it, and does not delete it
  without an approved reconciliation path.
- No rule may use an unbounded destination (`0.0.0.0/0`, `::/0`) or an arbitrary accept for all
  protocols/ports. The policy compiler and helper both reject broad or ambiguous rules.
- NAT is out of scope. The firewall controller does not create DNAT/SNAT/masquerade rules.

### 3.2 Ownership markers

A marker is a canonical, bounded identifier recorded in the chain/rule and independently
recomputed by the helper. Proposed marker fields:

- marker schema/version;
- ownership record hash;
- policy hash/ID;
- policy version;
- canonical policy digest prefix;
- family.

Because nftables comments have length limits, the full canonical identifier/digest stays in the
controller database, while the rule/chain carries a collision-resistant hash/prefix. The helper
recomputes the expected marker from the request and compares both the chain name and the marker.
A prefix alone is not sufficient authority; the controller ownership record and exact normalized
ruleset read-back are also required.

The marker proves **which owned object is being changed**. It does not prove that the request is
authorized; peer identity and controller ownership still do.

### 3.3 Rule model and validation

The helper receives canonical `rule-schema-v1` typed data, never raw nft syntax. The canonical
field names, types, required/optional status, enumerations, validation, normalization, CIDR scope,
and digests are defined once in 2H.1 Section 4.4.1. The controller and helper both validate that
schema; this section only maps it to the backend. It does not define an alternative rule model.

| Canonical field / behavior | Backend mapping and validation |
|---|---|
| `family` | Explicit `ipv4` or `ipv6`; select the corresponding nftables family/table or iptables/ip6tables path. No IPv4-mapped IPv6, inferred family, or ambiguous "both". |
| `source_cidr`, `destination_cidr` | Canonical network CIDRs wholly within the owned challenge network. Reject `/0`, unspecified, loopback, link-local, multicast, reserved, benchmark, documentation, metadata, host/LAN, and IPv4-mapped ranges. Do not mask host bits or widen a CIDR to make it fit. |
| `protocol` | `tcp` or `udp` only in v1. `any`, `icmp`, `icmpv6`, SCTP, and all others are unsupported and rejected. The earlier "optional ICMP" sentence is superseded; a future schema version must define ICMP type/code and approval. |
| `port_start`, `port_end` | Integer 1..65535 with `start <= end`. Map to source/destination port match only where the canonical direction requires it. No arbitrary all-port accept; an explicit full-range drop is allowed only inside the owned scope. |
| `direction` | `ingress` or `egress`; select the fixed input/output or forward hook according to the validated edge. No implicit both and no backend default. Two rules are required for both directions. |
| `action` | `accept` or `drop`; map to the fixed backend verdict. No reject/log/continue/queue action. |
| State | Not a canonical rule field. Conntrack may be used only for return traffic of a flow that an explicit canonical rule already accepts; no global established/related accept and no hidden state default. |
| DNS | Not a separate field or protocol. An explicit `udp` or `tcp` rule to the approved in-scope resolver on port 53 is the only representation. Default deny; no wildcard resolver or implicit DNS permission. |
| Size/depth | At most 256 rules, bounded object depth, 4096 characters per string, and the 65,536-byte frame limit; reject rather than truncate. |
| Ownership | Required ownership reference/marker, checked against the controller record before backend access; not a rule field and never caller-chosen. |
| Idempotency | Operation/key/digest binding, with conflicting reuse rejected; not a rule field and never used to infer success. |

The helper must reject unsupported fields and protocol/family combinations rather than silently
dropping them. It must reject a policy that the selected backend cannot represent exactly. The
helper does not accept the current `2L.2G.3` helper payload or a legacy flat rule shape as an
alternate rule language.

### 3.4 Install flow

```text
controller persists intent/ownership state (non-terminal)
  -> controller validates ownership, lifecycle, schema, families, digest
  -> helper authenticates controller peer
  -> helper validates contract + ownership marker
  -> helper checks for conflicting owned chain and unknown drift
  -> helper builds a fixed transactional batch:
       create per-ownership chain(s)
       add bounded rules
       add base-chain jump/dispatch
     (both families in one transaction where the backend guarantees it)
  -> helper applies the batch without shell
  -> helper reads back the owned table
  -> helper returns structured handles/digest/family result
  -> controller independently verifies read-back
  -> controller stores evidence and only then promotes state
```

If the backend cannot guarantee cross-family atomicity, the controller must not report a
two-family install as successful. It records per-family state and enters a partial/uncertain
recovery path. The helper must not hide a partial result.

### 3.5 Verification and read-back

Verification is independent of the write call. The helper reads the actual backend state through a
fixed structured interface (prefer libnftables/netlink; a fixed backend executable is acceptable
only with an absolute path, structured argv, no shell, and no caller-controlled strings).

Verification must compare:

- owned table/chain existence and markers;
- expected normalized rules for the family;
- absence of unexpected rules in the owned chain;
- base-chain dispatch/jump marker;
- family parity and required families;
- normalized ruleset digest;
- rule handles for audit, with the caveat that handles are not the sole identity.

Read-back failure, parse ambiguity, permission failure, or a digest mismatch is **not success**.
The controller records uncertainty and reconciles; it does not promote `ACTIVE`.

### 3.6 Revocation flow

```text
controller persists REVOKING / non-active intent
  -> helper authenticates and validates ownership marker
  -> helper removes only that ownership's jump/chain(s)
  -> helper reads back both required families
  -> controller stores absence evidence
  -> controller marks REVOKED only when every required family is confirmed absent
```

Removal must be idempotent:

- If the owned chain/jump is already absent and no marker remains, verification is positive.
- If a marker is partially present or ownership cannot be proven, the helper must not delete
  unrelated rules; it returns an uncertain/conflict result.
- Unknown/unowned chains in the owned table are not removed automatically.
- A helper crash mid-revoke leaves a partial state; the controller must retry inspection and
  cleanup, never infer success from the lost response.

### 3.7 Docker interaction

Docker's firewall behavior must be treated as an external, version-dependent dependency.

- The primary nftables design uses a separate `inet flaghunt` table and does not flush Docker
  tables.
- Docker may use iptables-nft; the exact hook/priority relationship with Docker's filter chains
  and bridge forwarding must be validated with real traffic.
- Docker NAT and port-publishing rules are not owned by this controller and must not be edited.
- A `DOCKER-USER` jump is a **fallback** integration, not an assumed primary mechanism. It must
  carry a unique marker and be removed only when it matches the helper's ownership.
- Docker start/restart/upgrade may reorder or recreate chains. The controller must detect drift by
  read-back and reconcile owned rules; it must not blindly reinsert duplicate jumps.
- A host with an unsupported Docker/firewall combination must fail the host validation gate rather
  than silently using unsafe ordering.

### 3.8 Persistence across restart

- Kernel rules may survive controller/helper restart; they may not survive host reboot.
- The controller database is the durable source of truth for ownership and intent. A static
  global firewall file is not the source of challenge policy.
- On boot, the operator-owned baseline may load first. The helper/controller then reconcile owned
  records by inspection.
- Challenge rules must not be automatically adopted from a saved file if the controller has no
  matching ownership/evidence.
- If required rules are absent, only owned active intents may be reinstalled; if present but
  unowned/unknown, report and fail closed rather than deleting blindly.
- Boot ordering and the pre-reconciliation exposure window are deployment decisions requiring
  explicit approval.

---

## 4. iptables + DOCKER-USER fallback design

The fallback is considered only after lab evidence shows nftables cannot meet the host/Docker
requirements. It must preserve the same ownership and evidence rules.

### 4.1 Model

- Separate `iptables` (IPv4) and `ip6tables` (IPv6) operations. No cross-family aliasing.
- Helper-owned custom chains, for example `FLAGHUNT-FWD` and per-ownership
  `FLAGHUNT-P-<hash>`.
- A single owned jump in `DOCKER-USER` at a lab-validated position. The jump is marked with a
  unique comment/ownership hash.
- Never flush `DOCKER-USER`, Docker chains, or the host filter table.
- No NAT/SNAT/DNAT/masquerade changes.
- No `iptables -F`/`iptables -X` on shared chains.

### 4.2 Atomicity and read-back

- Use a single `iptables-restore --noflush --wait` batch per family where possible.
- If IPv4 and IPv6 cannot be committed atomically together, the controller must track per-family
  state and never claim dual-stack success.
- Read back with `iptables-save`/`ip6tables-save` or a structured backend API; parse the owned
  chains only.
- Rule handles are audit data; comments/ownership markers and normalized rules are the identity.
- Removal checks the exact owned jump/comment and chain; a missing owned object may be idempotent
  success only when absence is positively confirmed.
- Unknown/unowned rules are reported, not deleted.

### 4.3 Fallback risks

- IPv4/IPv6 divergence.
- Docker restart/upgrade may recreate `DOCKER-USER` or reorder rules.
- `iptables-nft` vs legacy `iptables` behavior differs.
- Chain/comment limits and rule ordering are more fragile than nftables.
- The fallback must not become an implicit second source of truth. The controller records which
  backend is active and refuses mixed ownership.

---

## 5. Privilege separation

### 5.1 Architecture comparison

| Model | Description | Decision |
|---|---|---|
| Root controller | Controller runs as root and applies rules directly | **Rejected**: excessive blast radius; controller parsing/DB compromise becomes root/host firewall compromise |
| Capable controller | Controller holds `CAP_NET_ADMIN` directly | **Rejected for target**: larger attack surface and no narrow helper boundary |
| Unprivileged controller + capable helper | Controller has no caps; helper has only the required capability | **Recommended** |
| Root helper with full root | Helper runs as root/root shell | **Rejected**: parsing/command-injection bug becomes full host compromise |
| Unprivileged helper with no caps and external setuid tool | Delegates to a broadly privileged tool | **Rejected**: hidden privilege and command surface |

### 5.2 Capability analysis

| Operation | Required capability | Process | Notes |
|---|---|---|---|
| Read/write netfilter rules via nftables/netlink | `CAP_NET_ADMIN` (expected) | Helper only | Confirm exact read/write behavior in host lab; do not assume unprivileged read-back |
| iptables/ip6tables fallback changes | `CAP_NET_ADMIN` (expected) | Helper only | Separate v4/v6; no `CAP_SYS_ADMIN` |
| Raw packet sockets / ping diagnostics | `CAP_NET_RAW` may be needed by diagnostic tools | Not the controller/helper default | Do not grant for firewall operations without separate review |
| Load kernel modules, change sysctl, mount, ptrace | `CAP_SYS_ADMIN` or broader | None | Forbidden |
| UDS/socket operations | None | All services | Unprivileged |
| SQLite/controller evidence | None beyond file permissions | Controller | Helper has no DB access |
| Docker container lifecycle | Docker daemon access (host-root-equivalent) | Runtime adapter only | **Broker has no Docker socket/group/API**; fixed catalog-bound operations only |
| Service management | systemd | Deployment operator | Not granted to runtime services |

**Conclusion:** the target helper is expected to need **`CAP_NET_ADMIN` only**, but the exact set
is conditional on the validated backend/library and must be proven in a disposable host lab. The
controller, broker, and manager receive **no capabilities**. `CAP_NET_RAW`, `CAP_SYS_ADMIN`,
`CAP_DAC_OVERRIDE`, `CAP_SYS_MODULE`, and full root are not approved.

The runtime adapter has **no Linux capabilities** but has Docker socket access. That access is
host-root-equivalent; it is a separate high-risk boundary (2H.2 T-27), not a low-privilege
component. The broker's Docker authority is removed; the runtime adapter cannot call the helper or
read controller ownership/evidence. If the host-root residual is unacceptable, online Docker daemon
access must be removed and challenge containers supplied by an externally isolated runtime.

`CAP_NET_ADMIN` is not a minor privilege. It can alter host networking, netfilter, interfaces,
qdiscs, and routing. A compromised helper therefore remains a high-residual-risk event (see
`PHASE_2L_2H_2_THREAT_MODEL_AND_TRUST_BOUNDARIES.md`, T-13).

### 5.3 Process isolation and service hardening

Proposed helper baseline (illustrative design, not an applied unit):

| Control | Proposed setting | Purpose |
|---|---|---|
| User/group | `flaghunt-fwhelper` / dedicated group | No login shell; no shared application user |
| Capabilities | `AmbientCapabilities=CAP_NET_ADMIN`, `CapabilityBoundingSet=CAP_NET_ADMIN` | Only the required capability; no root |
| `NoNewPrivileges` | `yes` | Prevent setuid/file-capability escalation |
| Filesystem | `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `ReadWritePaths` only runtime/log | Read-only code/config; no controller DB |
| Devices | `PrivateDevices=yes` where compatible | No unnecessary device access |
| Kernel | `ProtectKernelTunables=yes`, `ProtectKernelModules=yes`, `ProtectControlGroups=yes`, `ProtectClock=yes`, `ProtectHostname=yes` | Reduce host attack surface |
| Address families | `RestrictAddressFamilies=AF_UNIX AF_NETLINK` (exact list lab-validated) | No arbitrary network sockets |
| Syscalls | seccomp allowlist for startup, UDS, netlink, memory, logging; no `execve` after startup if using a library backend | Narrow kernel surface |
| MAC | AppArmor or SELinux profile allowing only helper paths, socket, netlink, log | Defense in depth if parsing is exploited |
| Memory | `MemoryDenyWriteExecute=yes` where compatible; `LockPersonality=yes`; `RestrictRealtime=yes`; `RestrictSUIDSGID=yes` | Reduce code injection/exploit surface |
| Proc | `ProtectProc`/`ProcSubset` where compatible | Limit information exposure |
| Umask | `0077` | Prevent accidental world-readable files |
| Network namespace | **Do not** use `PrivateNetwork=yes` | Helper must affect the host firewall namespace |
| Restart | Bounded `Restart=on-failure`, start limits, watchdog | Recover crashes without loops |

The exact compatibility of `PrivateDevices`, `MemoryDenyWriteExecute`, seccomp, and
`RestrictAddressFamilies` with the chosen nftables library is an open lab decision. The design
must not claim hardening that has not been tested.

### 5.4 Filesystem and data permissions

- Helper binary: root-owned, not group/world-writable; fixed path.
- Helper config: `/etc/flaghunt/fwhelper.json`, root-owned, group `flaghunt-fwhelper`, mode `0640`;
  numeric allowlists and socket path are mandatory; no secrets in world-readable files.
- Helper runtime directory: `/run/flaghunt/controller-helper`, owner
  `flaghunt-fwhelper:flaghunt-fwcontroller`, mode `2750` (setgid); the helper (server) has
  directory write permission; the controller has group non-write access. Socket
  `/run/flaghunt/controller-helper/helper.sock` is
  `flaghunt-fwhelper:flaghunt-fwcontroller` `0660`. Directory mode and socket mode are both
  required.
- Controller socket directory: `/run/flaghunt/broker-controller`, owner
  `flaghunt-fwcontroller:flaghunt-broker`, mode `2750` (setgid); controller (server) binds; broker
  traverses.
- Broker management socket: `/run/flaghunt/manager-broker`, owner
  `flaghunt-broker:flaghunt-manager`, mode `2750` (setgid); broker binds; manager traverses.
- Runtime adapter socket: `/run/flaghunt/broker-runtime`, owner
  `flaghunt-runtime:flaghunt-broker`, mode `2750` (setgid); runtime adapter binds; broker traverses.
- `/run/flaghunt` is `root:root` `0755`, non-world-writable; no service writes another service's
  directory. Socket activation is **not** used; tmpfiles creates exact owner/group/mode. The
  setgid bit causes the server-created socket to inherit the client group without `CAP_CHOWN` or
  server membership in that group. The helper and controller verify `S_ISGID`, owner, group, and
  mode before bind/accept; a `0750` directory, missing setgid, or wrong group fails closed. The full
  mechanism is normative in 2H.1 Section 5.1.
- Helper log/audit: service-owned directory or journald; bounded retention; no controller DB.
- Controller DB: controller-only read/write; helper cannot read it.
- Broker DB: broker-only; no controller cross-write.
- Docker socket: accessible only to `flaghunt-runtime`; broker/controller/helper/manager must not be
  in the Docker group and must not have `/var/run/docker.sock` open.
- No shared writable directory between helper and controller except the bounded UDS runtime path.
- No shell, no writable PATH, no user-controlled environment.

### 5.5 Startup and shutdown

Proposed ordering:

```text
system boot
  -> systemd-tmpfiles creates /run/flaghunt and 2750 setgid socket dirs (exact owner/group)
  -> operator-owned baseline (if approved)
  -> runtime adapter starts (no Docker operation until catalog/ownership checks)
  -> helper starts, binds helper.sock (CAP_NET_ADMIN, backend readiness)
  -> controller starts, verifies helper server peer identity, binds controller.sock
  -> broker starts, verifies controller and runtime-adapter server peers, binds broker.sock
  -> manager starts, verifies broker server peer, connects management UDS
```

- Controller/helper readiness must be positively checked; a listening socket alone is not proof
  that the backend is safe. Direct-bind sockets are created by each server after owner/mode checks;
  no systemd socket activation is used.
- On controlled shutdown, stop accepting new requests, finish/cancel in-flight work within a
  bounded window, then stop services in reverse order.
- Do **not** remove firewall rules merely because a service is stopping. Persistent rules protect
  challenge isolation until reconciliation; removing them could create a bypass.
- On restart, reconcile against durable controller intent and actual backend state.

### 5.6 Why unrestricted root or shell execution is unacceptable

- A root helper turns any parsing bug, library vulnerability, or command-injection path into full
  host compromise.
- A shell/argv interface allows caller text to become commands, options, file paths, or chain
  names; allowlists and quoting are fragile.
- A root controller would let a compromised DB/service mutate arbitrary host network state with no
  narrow boundary.
- The helper's fixed enum + typed data + `CAP_NET_ADMIN` only does not eliminate risk, but it
  reduces the blast radius from "full root" to "controlled host netfilter operations" and makes
  independent validation/read-back possible.

### 5.7 Docker runtime adapter segregation (H-02)

The broker must not have Docker socket access, Docker group membership, or a generic Docker client.
The target introduces a separate `flaghunt-runtime` service (numeric UID/GID `4604/4604`) that is
the only process with the Docker socket. It exposes a fixed UDS operation set to the broker:
`RUNTIME_CREATE_INSTANCE`, `RUNTIME_START_INSTANCE`, `RUNTIME_INSPECT_INSTANCE`,
`RUNTIME_STOP_INSTANCE`, and `RUNTIME_REMOVE_INSTANCE`.

The adapter resolves the image and complete container configuration from a read-only catalog. It
does not accept caller image names/digests, commands, entrypoints, mounts, volumes, networks,
capabilities, devices, security options, privileges, or namespace modes. It constructs:

- pinned image digest from the catalog;
- non-root user, no privileged mode, no new privileges;
- no host network/PID/IPC/UTS namespace; no Docker socket mount; no host filesystem bind;
- no devices; drop all capabilities; seccomp/AppArmor profile; read-only root filesystem where
  compatible; bounded tmpfs;
- CPU, memory, PID, and lifetime limits;
- an internal challenge network with no arbitrary egress; no arbitrary host port publication;
- ownership labels `flaghunt.managed=true`, `flaghunt.instance_id`, `flaghunt.challenge_id`,
  `flaghunt.catalog_id`, `flaghunt.spec_digest`, and `flaghunt.owner=broker`.

Before start/stop/inspect/remove, the adapter verifies the labels, catalog/spec digest, container
ID, and network/storage ownership. Unknown or unmanaged containers are reported, never adopted or
removed. The adapter never writes the controller DB, never calls the helper, and never applies
firewall rules.

**Residual:** access to a rootful Docker daemon is host-root-equivalent. A compromised runtime
adapter can potentially control host networking and containers despite these restrictions. The
design does not claim that a proxy removes that risk. If the residual is not accepted, the broker
must have no online container runtime at all, or the runtime must be externally isolated. This is
T-27 and requires explicit risk acceptance plus host-lab validation.

**Current-code audit (N-04).** The target above is not mechanically enforced today:

- `broker/app/dependencies.py` constructs `BrokerDockerAdapter(docker_client=None, ...)`.
  `broker/app/routes.py` still injects that adapter into create/start/inspect/stop/remove/health
  routes. `BrokerDockerAdapter._ensure_client()` fails closed when no client is supplied, so the
  inspected deployment has no proven Docker reachability, but the class accepts a Docker client and
  implements container/network operations. A wiring change or client injection would restore
  host-root-equivalent authority.
- `manager/app/runtime/docker_adapter.py` exports `DockerRuntimeAdapter`; its tests use
  `MagicMock` clients and prove only mock behavior. No manager route is wired to it in the inspected
  code. Its continued presence is not a security boundary.
- No `flaghunt-runtime` service or fixed-operation UDS endpoint exists. The broker/manager UIDs are
  not yet deployed, so the target no-Docker claim is design-only.

N-04 remains **OPEN** until the broker/manager adapters are removed or relocated behind a
separately reviewed boundary and tests prove the absence of Docker imports, routes, socket/group
access, and host-root-equivalent operations.

**Required future restrictions for N-04 (design acceptance criteria):**

| Area | Required restriction |
|---|---|
| Allowed operations | Only the five fixed `RUNTIME_*` operations; catalog lookup is read-only and catalog-bound. |
| Rejected operations | Arbitrary image/digest selection, command/entrypoint, mount/volume, network mode, host namespace, privileged flag, device, capability, security-option, exec, image pull, daemon configuration, and generic Docker API passthrough. |
| Authority ownership | Only the `flaghunt-runtime` service may hold the Docker socket/group. Broker, manager, controller, helper, and monitor must have no Docker socket, group, or API. |
| API boundary | A fixed UDS envelope/operation enum, not the Docker HTTP API or a shell. The caller supplies only approved identifiers; the adapter resolves the catalog/image/container spec. |
| Resource restrictions | Pinned digest, non-root, no host namespaces/mounts/devices, drop all capabilities, no-new-privileges, read-only root, bounded tmpfs/CPU/memory/PID/lifetime, internal network, no arbitrary egress/published ports. |
| Authentication/authorization | `SO_PEERCRED` broker UID/GID allowlist, ownership labels, catalog/spec digest, exact operation/resource authorization; no caller identity headers/tokens. |
| Audit | Independent runtime audit with operation/resource/digest/result/error; Docker event correlation; no raw secrets or arbitrary payload dump. |
| Failure behavior | Fail closed on unavailable daemon, unknown/unmanaged container, label/digest mismatch, timeout, or uncertain result; never adopt/remove unknown resources. |
| Testing/acceptance | Import/route/socket/group negative tests for broker and manager; fixed-operation positive/negative tests; host-lab label/digest/namespace/resource tests; `RTA-01..07`; explicit T-27 acceptance. |

---

## 6. Failure and uncertainty semantics

| Situation | Helper result | Controller action | Must not do |
|---|---|---|---|
| Request validates, backend write succeeds, read-back matches | Success with structured evidence data | Store evidence; promote only per lifecycle rules | Promote on write response alone |
| Backend write succeeds, read-back fails/ambiguous | `UNCERTAIN`/`BACKEND_READBACK_FAILED` | Keep non-terminal; retry inspection; reconcile | Report success or delete blind |
| Timeout/connection reset | No trustworthy result | Treat as uncertain; inspect backend; idempotent retry | Blind retry that can duplicate side effects |
| One family succeeds, one fails | Partial/uncertain with family detail | Per-family state; cleanup/retry; no dual-stack success | Mark `ACTIVE` |
| Revocation partially succeeds | Partial/uncertain | Keep `REVOKING`/cleanup; retry; evidence absence only when complete | Mark `REVOKED` |
| Unknown/unowned rule appears | Report drift; no mutation | Quarantine/operator review; no auto-adoption | Delete because it looks stale |
| Helper crash | Connection failure | Restart/reconcile; inspect | Assume write failed |
| Controller crash | Durable intent remains | Startup scan/read-back; CAS | Assume success/failure |

Detailed crash points and recovery are in
`PHASE_2L_2H_4_PERSISTENCE_RECOVERY_AND_DEPLOYMENT_DESIGN.md`.

---

## 7. Current versus target comparison

| Control | Current mock | Target proposal | Implementation status |
|---|---|---|---|
| Backend | `MockFirewallController` | nftables primary; iptables fallback | Not implemented |
| Capability | None | `CAP_NET_ADMIN` helper only | Not granted/implemented |
| Helper process | In-process mock | Dedicated systemd service, hardened | Not implemented |
| Rule ownership | SQLite ownership records; mock contract | Table/chain markers + read-back + evidence | Not implemented |
| IPv4/IPv6 | Contract fields | Per-family rules/evidence; fail closed on parity | Not implemented |
| Docker | Broker adapter wired but clientless; manager adapter exported/mock-tested; no runtime service | Broker/manager have no target Docker authority; fixed runtime adapter; lab-validated DOCKER-USER interaction | Design only; N-04/T-27 open |
| Runtime adapter | None | Separate `flaghunt-runtime`; fixed catalog-bound Docker operations; host-root residual | Not implemented |
| Atomic install | Mock result | Transactional batch; per-family fallback | Not implemented |
| Revocation | Mock result | Owned-only removal + absence evidence | Not implemented |
| Restart | Mock tests | Kernel/DB reconciliation | Not implemented |

---

## 8. Open decisions

**Resolved by 2L.2I.4:** the canonical rule schema, direction/state/DNS semantics, CIDR bounds,
TCP/UDP-only v1 protocol support, ICMP deferral, and error mapping are fixed in 2H.1 Section 4.4.1;
socket directories are `2750` setgid with kernel-inherited client groups and no supplementary-group
access; a `0750` directory is invalid. The following remain open:

1. Exact nftables version/kernel/Docker combination and supported Ubuntu LTS target.
2. nftables base-chain hook priority and whether host-input/output paths are in scope.
3. Per-ownership chain design vs a single chain with markers; recommendation is per-ownership
   chain for cleanup/read-back isolation.
4. Cross-family atomicity guarantee; partial install/revoke is represented by per-family rows and
   derived status, not a persisted `PARTIALLY_*` aggregate state (resolved in 2H.4 Section 2.4).
5. Whether the helper uses libnftables/netlink or a fixed backend executable; no shell in either
   case.
6. Whether a fixed read-only inspect helper is split from the mutating helper.
7. Exact seccomp/AppArmor/SELinux profile and whether `MemoryDenyWriteExecute`/`PrivateDevices`
   are compatible.
8. Exact `CAP_NET_ADMIN` read-back behavior and whether any `CAP_NET_RAW` is ever needed.
9. Fallback trigger criteria and whether both backends may coexist on a host.
10. How unknown/unowned rules are quarantined and who approves cleanup.
11. Whether challenge rules may ever be persisted in a static boot file, and the pre-reconciliation
    exposure window.
12. Evidence signing/HMAC by the helper and key management.
13. Explicit risk acceptance for T-11/T-13 and T-27, including host isolation/monitoring and a
    named acceptance authority.
14. Runtime-adapter catalog ownership, immutable manifest format, and Docker socket group mapping.

---

**DESIGN COMPLETE — REAL FIREWALL IMPLEMENTATION NOT AUTHORIZED**

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
