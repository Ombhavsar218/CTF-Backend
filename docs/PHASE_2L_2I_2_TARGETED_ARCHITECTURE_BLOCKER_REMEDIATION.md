# Phase 2L.2I.2 - Targeted Architecture Blocker Remediation

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Phase:** 2L.2I.2  
**Date:** 2026-11-14  
**Scope:** Documentation and design only  
**Prior review:** Phase 2L.2I.1 - **CONDITIONAL — Specific blockers must be resolved**  
**Final decision:** **CONDITIONAL — Targeted design remediation is complete; implementation remains blocked by open residual acceptance and unexecuted host tests**  
**Integration gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

This report records a targeted, documentation-only remediation of the five architecture documents
from Phase 2L.2H. It does not implement a transport, socket, `SO_PEERCRED` adapter, privileged
helper, capability, Docker change, firewall rule, systemd unit, migration, deployment, or host
change. It does not convert any proposed control into an implemented control.

The prior Phase 2L.2I.1 decision remains the starting point:

> **CONDITIONAL — Specific blockers must be resolved.**

Phase 2L.2H remains:

> **DESIGN COMPLETE — REAL FIREWALL IMPLEMENTATION NOT AUTHORIZED.**

The five High findings and nine Medium findings from Phase 2L.2I.1 are disposed of below. The
original findings are not renamed, merged, omitted, or rewritten. The `F-01` through `F-14` IDs from
2L.2I.1 are preserved and mapped explicitly to the `H-01` through `H-05` and `M-01` through `M-09`
labels used by the remediation request.

---

## 1. Executive decision

### 1.1 Decision

The targeted architecture contradictions identified in Phase 2L.2I.1 have been remediated at the
design level:

- the UDS permission model now has a coherent direct-bind ownership model;
- the broker no longer retains direct Docker authority;
- kernel peer identity is an immutable typed boundary derived only from `SO_PEERCRED`;
- manager-to-broker transport is fixed as direct-bind UDS, not HTTP;
- the wire protocol, operation set, timeout field, ownership field, error registry, version, and
  compatibility behavior are frozen;
- the nine Medium findings are individually dispositioned;
- RR-01 through RR-07 remain open; I-07, I-08, and I-09 are now explicitly tracked;
- legacy mock residuals are recorded and not silently closed;
- all five Phase 2L.2H documents were updated consistently.

This is **not** a security PASS. It is a design-remediation result. No executable control exists,
no test was run in this phase, and no implementation is authorized.

### 1.2 Decision matrix

| Gate question | Result | Reason |
|---|---|---|
| Are the five High design defects individually addressed? | **Yes, at design level** | H-01, H-03, H-04, and H-05 are coherently specified; H-02 removes broker Docker authority but leaves the runtime adapter's host-root residual open. |
| Are all nine Medium findings individually disposed of? | **Yes** | Each has an explicit disposition in Section 10. Several remain open at implementation or host-gate level. |
| Are RR-01 through RR-07 preserved? | **Yes** | All remain open in the 2H.2 register and in Section 11. |
| Are I-07, I-08, and I-09 explicitly tracked? | **Yes** | Added with exact titles/evidence and legacy mapping in 2H.2 and Section 12. |
| Are the five documents internally and cross-document consistent? | **Yes for the addressed design decisions** | Section 13 records the matrix and the remaining host-level gaps. |
| Is implementation authorized? | **No** | Risk acceptance, host-lab testing, independent review, and explicit authorization are still absent. |
| Is the live firewall authorized? | **No** | The live gate remains closed. |

### 1.3 Final decision statement

> **CONDITIONAL — Targeted design remediation is complete; implementation remains blocked by open residual acceptance and unexecuted host tests.**

This is the strongest supportable decision. A PASS would misrepresent documentation edits as tested
security. A FAIL would ignore that the design contradictions were actually corrected.

---

## 2. Scope, constraints, and non-claims

### 2.1 Scope

This phase remediates the Phase 2L.2I.1 findings in:

1. `PHASE_2L_2H_1_REAL_TRANSPORT_TARGET_ARCHITECTURE.md`
2. `PHASE_2L_2H_2_THREAT_MODEL_AND_TRUST_BOUNDARIES.md`
3. `PHASE_2L_2H_3_FIREWALL_BACKEND_AND_PRIVILEGE_DESIGN.md`
4. `PHASE_2L_2H_4_PERSISTENCE_RECOVERY_AND_DEPLOYMENT_DESIGN.md`
5. `PHASE_2L_2H_5_IMPLEMENTATION_AND_VALIDATION_ROADMAP.md`

It also creates this report and records the remediation traceability.

### 2.2 Hard constraints observed

No source, test, runtime configuration, migration, UDS socket, `SO_PEERCRED` call, helper privilege,
Docker object, firewall table/rule, systemd unit, service account, package, host baseline, network
state, or deployment state was changed **by this phase**. The changes made by this phase are
documentation-only; pre-existing working-tree changes outside this phase are not attributed to it.

No claim in this report is based on executing a real control. The current mock implementation
remains the only executed implementation.

### 2.3 Non-claims

This report does **not** claim that:

- a Unix domain socket exists;
- `SO_PEERCRED` is implemented or exercised;
- the privileged helper exists or has `CAP_NET_ADMIN`;
- the controller has been deployed;
- Docker authority has been removed from a running service;
- the runtime adapter exists;
- any nftables/iptables rule or Docker network was created or verified;
- any RR or I residual is closed;
- the mock tests prove live security;
- the architecture is ready for live firewall integration.

---

## 3. Inputs and evidence base

### 3.1 Primary review input

The finding source is:

`docs/PHASE_2L_2I_1_INDEPENDENT_ARCHITECTURE_SECURITY_REVIEW.md`

Its decision was **CONDITIONAL — Specific blockers must be resolved**, with no Critical finding,
five High findings, and nine Medium findings.

### 3.2 Design documents

The five 2H documents were inspected and edited where required. The relevant design areas were:

- 2H.1: protocol, UDS edges, socket modes, `SO_PEERCRED`, timeouts, manager/broker transport;
- 2H.2: trust boundaries, threat register, residual register, assumptions, open questions;
- 2H.3: helper privilege model, socket/filesystem ownership, startup order, Docker interaction;
- 2H.4: schema, lifecycle, evidence, idempotency, service users, socket permissions, deployment;
- 2H.5: implementation sequence, test layers, go/no-go criteria, unresolved decisions.

### 3.3 Current code evidence used from 2L.2I.1

The 2L.2I.1 evidence remains valid for the current mock behavior. It included:

- `broker/firewall_controller_service/authorization_strict.py`
- `broker/firewall_controller_service/controller_service.py`
- `broker/firewall_controller_service/mock_transport.py`
- `broker/firewall_controller_service/helper_contract.py`
- `broker/app/auth.py`
- `broker/app/authorization.py`
- `broker/app/uds.py`
- `broker/app/broker_settings.py`
- `manager/app/broker_client.py`
- `manager/app/routes.py`

The key current behavior used in the findings was:

- request `peer_uid`/`peer_gid` are caller-supplied mock context, not kernel identity;
- manager HTTP auth merges caller headers over peer information;
- an empty token can be accepted by the current authorization path;
- `uds.py` currently unlinks a path without the target owner/mode/symlink checks;
- the helper contract uses `timeout_ms`, `2L.2G.3`, `REMOVE_OWNED_POLICY`,
  `RECONCILE_OWNED_POLICY`, and a broader protocol/port model;
- the controller idempotency key is `(idempotency_key, operation_type)`;
- the broker path has a Docker client and no fixed proxy/allowlist boundary;
- mock authorization has a `strict_auth=False` path.

### 3.4 Evidence limitation

These observations prove current mock behavior and current gaps. They do not prove that the target
controls exist. The target sections in the five documents are design requirements only.

---

## 4. Finding-to-document mapping

### 4.1 ID mapping

The remediation request uses the following mapping. The original 2L.2I.1 IDs and titles are
preserved.

| 2L.2I.1 ID | Remediation ID | Severity | Exact 2L.2I.1 title | Primary documents changed |
|---|---|---|---|---|
| F-01 | **H-01** | High | Socket directory permissions cannot support the documented UDS edges. | 2H.1, 2H.2, 2H.3, 2H.4, 2H.5 |
| F-02 | **H-02** | High | Broker Docker authority can bypass the controller/helper and host-firewall restriction claim. | 2H.1, 2H.2, 2H.3, 2H.4, 2H.5 |
| F-03 | **H-03** | High | Target controller identity adapter is undefined; current service reads request `peer_uid`/`peer_gid` and includes them in the digest. | 2H.1, 2H.2, 2H.5 |
| F-04 | **H-04** | High | Manager-broker boundary is unresolved; current HTTP auth is unsafe if retained. | 2H.1, 2H.2, 2H.3, 2H.4, 2H.5 |
| F-05 | **H-05** | High | Wire protocol/operation contract is not frozen and conflicts with current contracts. | 2H.1, 2H.2, 2H.3, 2H.4, 2H.5 |
| F-06 | **M-01** | Medium | Idempotency key scope contradicts across documents and schema. | 2H.1, 2H.2, 2H.4, 2H.5 |
| F-07 | **M-02** | Medium | Target UDS lifecycle is not matched by current scaffold, and the target lacks an implementation contract. | 2H.1, 2H.2, 2H.4, 2H.5 |
| F-08 | **M-03** | Medium | 2H residual register omits I-07, I-08, and I-09. | 2H.2, 2H.5 |
| F-09 | **M-04** | Medium | No per-threat validation test mapping. | 2H.2, 2H.5 |
| F-10 | **M-05** | Medium | Threat register misses FD passing, supply-chain, Docker daemon, and audit/disk exhaustion. | 2H.2, 2H.5 |
| F-11 | **M-06** | Medium | Evidence immutability and aggregate lifecycle invariants are prose only. | 2H.4, 2H.5 |
| F-12 | **M-07** | Medium | Numeric UID/GID and allowlist/config contract undefined; helper config group unspecified. | 2H.1, 2H.3, 2H.4, 2H.5 |
| F-13 | **M-08** | Medium | Current helper contract is broader/differently versioned than the target rule/operation contract. | 2H.1, 2H.2, 2H.3, 2H.5 |
| F-14 | **M-09** | Medium | Exact nftables hook priority, cross-family atomicity, Docker ordering, seccomp/MAC, and boot baseline remain unvalidated. | 2H.3, 2H.4, 2H.5 |

### 4.2 Disposition summary

| ID | Design disposition | Implementation/test disposition |
|---|---|---|
| H-01 | Resolved | Open |
| H-02 | Architecture resolved for the broker; runtime-adapter residual open | Open |
| H-03 | Resolved | Open |
| H-04 | Resolved | Open |
| H-05 | Resolved | Open |
| M-01 | Resolved | Open |
| M-02 | Resolved as a lifecycle contract | Open |
| M-03 | Resolved | Open tracking |
| M-04 | Resolved | Tests not run |
| M-05 | Resolved | Tests not run |
| M-06 | Resolved as schema/guard design | Open |
| M-07 | Resolved as numeric/config design | Open |
| M-08 | Resolved as migration/tightening contract | Open |
| M-09 | Not resolvable by documentation | Open host gate |

"Resolved" means the design contradiction or undefined contract is resolved. It never means the
control is implemented or validated.

---

## 5. H-01 - Socket directory permissions cannot support the documented UDS edges

### 5.1 Original finding

**F-01 / H-01: Socket directory permissions cannot support the documented UDS edges.**

2L.2I.1 evidence: 2H.1 Section 5.1 documented a root-owned `0750` directory with a client in a
different group; 2H.4 Section 6.3 repeated the mismatch; 2H.3 Section 5.4 said the helper runtime
directory was service-owned. A direct-bind server needs directory write permission, while a client
needs directory execute permission. The prior model did not consistently provide both.

### 5.2 Decision

**Direct bind, server-owned directory, client-group traversal, numeric identities.**

| Edge | Directory | Directory mode | Socket mode | The client can | The server can |
|---|---|---|---|---|---|
| Manager -> broker | `flaghunt-broker:flaghunt-manager` | `0750` | `0660` | Traverse and connect | Bind/replace/remove |
| Broker -> controller | `flaghunt-fwcontroller:flaghunt-broker` | `0750` | `0660` | Traverse and connect | Bind/replace/remove |
| Controller -> helper | `flaghunt-fwhelper:flaghunt-fwcontroller` | `0750` | `0660` | Traverse and connect | Bind/replace/remove |
| Broker -> runtime adapter | `flaghunt-runtime:flaghunt-broker` | `0750` | `0660` | Traverse and connect | Bind/replace/remove |

`/run/flaghunt` is `root:root` `0755`, non-world-writable. `systemd-tmpfiles` creates the child
directories with exact owner/group/mode before the services start. The server verifies the
directory with `lstat`, rejects symlinks and unexpected owners/modes, probes an existing socket,
and uses a unique temporary socket plus atomic `rename` when replacing a dead socket. It never
unlinks an arbitrary path and never removes a live server's socket. Cleanup is limited to its own
inode. `/run` is tmpfs, so reboot recreation is expected.

### 5.3 Why this resolves the finding

- The server has directory write permission because it owns the directory.
- The client has traverse permission through its group, but not directory write.
- Socket `0660` grants connect access to the intended client group.
- The client cannot replace the server's socket path.
- The server still verifies `SO_PEERCRED`; filesystem permission is not authentication.
- The helper socket is inaccessible to the manager and broker; the runtime adapter socket is
  inaccessible to the controller and helper.

### 5.4 Residual and implementation requirements

- Cross-UID permission tests are not run.
- The live services do not yet create these directories or sockets.
- A deployment that allows another writer into the directory invalidates the model.
- The runtime directory's parent chain must remain root-owned and non-writable by services.
- The target needs startup checks for owner/group/mode, socket type, symlink, dead/live socket, and
  own-inode cleanup.

---

## 6. H-02 - Broker Docker authority can bypass the controller/helper and host-firewall restriction claim

### 6.1 Original finding

**F-02 / H-02: Broker Docker authority can bypass the controller/helper and host-firewall
restriction claim.**

2L.2I.1 evidence: 2H.1 Section 3.2 allowed the broker to access needed Docker operations; 2H.2
T-10 covered only broker-to-controller; there was no Docker API proxy/allowlist; the current
adapter used a Docker client. A broker with broad Docker API access can create privileged
containers, mount the host, join host namespaces, or alter networking, which defeats the intended
firewall restriction.

### 6.2 Decision

**Remove all direct Docker authority from the broker. Introduce a separate restricted runtime
adapter with fixed operations. Treat the adapter's rootful Docker access as an explicit
host-root-equivalent residual.**

| Component | Docker socket/group/API | Firewall-control socket | Allowed action |
|---|---|---|---|
| Manager | None | Broker management UDS | User/manager operations |
| Broker | **None** | Controller client; manager server; runtime client | Fixed runtime requests only |
| Controller | None | Broker server; helper client | Ownership/evidence |
| Helper | None | Controller server | Fixed firewall backend |
| Runtime adapter | **Yes**, rootful Docker socket | Broker server | Fixed `RUNTIME_*` operations |

The adapter exposes only:

- `RUNTIME_CREATE_INSTANCE`
- `RUNTIME_START_INSTANCE`
- `RUNTIME_INSPECT_INSTANCE`
- `RUNTIME_STOP_INSTANCE`
- `RUNTIME_REMOVE_INSTANCE`

The adapter resolves the image and complete container settings from a read-only catalog keyed by
`catalog_id`. It does not accept caller image names/digests, commands, mounts, volumes, devices,
capabilities, security options, privileged flags, host namespace modes, or arbitrary network modes.
It verifies ownership labels and the catalog/spec digest before mutation.

Fixed restrictions include: pinned image digest, non-root user, no privileged mode, no new
privileges, no host network/PID/IPC/UTS namespace, no Docker socket mount, no host bind mount, no
devices, drop all capabilities, seccomp/AppArmor, read-only root filesystem where compatible,
bounded tmpfs, CPU/memory/PID/lifetime limits, and an internal challenge network with no arbitrary
egress.

### 6.3 What is resolved and what is not

Resolved at architecture level:

- the broker no longer has direct Docker authority;
- the broker cannot bypass the runtime adapter with a generic Docker client;
- runtime operations are catalog-bound and fixed;
- the adapter has no firewall-control socket and cannot call the helper;
- the threat model now separates T-10 (broker scope) from T-27 (adapter/Docker scope).

Not resolved:

- a rootful Docker daemon is host-root-equivalent;
- a compromised runtime adapter can still be extremely dangerous;
- container escape, daemon compromise, kernel compromise, and Docker networking side effects are
  not eliminated;
- the residual has no named acceptance authority;
- no Docker restriction or label test has been run.

The design does **not** claim that a proxy removes Docker authority. The residual is explicit. If it
is not accepted, online Docker daemon access must be removed and challenge runtime supplied by an
externally isolated system.

**H-02 disposition:** architecture-level boundary resolved for the broker; **T-27 remains open and
blocks implementation until explicitly accepted or removed.**

---

## 7. H-03 - Target controller identity adapter is undefined; current service reads request peer_uid/peer_gid and includes them in the digest

### 7.1 Original finding

**F-03 / H-03: Target controller identity adapter is undefined; current service reads request
`peer_uid`/`peer_gid` and includes them in the digest.**

2L.2I.1 evidence: the current authorization path consumes request fields; the controller service
reads them and includes identity fields in its digest; the mock transport injects caller-controlled
values. The target had no typed, out-of-band identity contract.

### 7.2 Decision

**Immutable `TrustedPeerIdentity` constructed only from the accepted socket's `SO_PEERCRED`, before
request parsing.**

```text
TrustedPeerIdentity
  uid: uint32                 # kernel SO_PEERCRED uid
  gid: uint32                 # kernel SO_PEERCRED primary gid
  pid: uint32                 # audit/correlation only
  source: literal "SO_PEERCRED"
  connection_id: transport-generated bounded value
  bound_at: monotonic timestamp
```

The type has no request constructor, no JSON/dict constructor, and no mutable identity fields. It is
bound to one accepted connection. One request per connection prevents later-request identity
confusion.

Authorization receives `(TrustedPeerIdentity, parsed_request)` as separate inputs. Request identity
fields are not stripped and silently accepted; they are rejected. The rejected field set includes
`peer_uid`, `peer_gid`, `peer_pid`, `uid`, `gid`, `pid`, `caller_uid`, `caller_gid`,
`caller_trusted`, `verified`, `trusted`, `auth_identity`, `x_identity`, `source_identity`,
`controller_verified`, `authorized`, and `is_admin`.

Both uid and primary gid must match non-empty numeric allowlists. Empty lists, missing
`SO_PEERCRED`, wrong `ucred` length, non-Linux platforms, and malformed values deny before dispatch.
Supplementary groups are not trusted. PID is audit-only. The client verifies the server's peer
uid/gid after `connect()` and before sending a request.

The idempotency digest binds the trusted principal, operation, canonical payload, ownership, and
request/operation IDs. It is never derived from caller-supplied identity fields.

### 7.3 Test-only identity

Test doubles live only under the test tree and are not importable by production entry points. There
is no production `strict_auth=False`, no mock authorization provider, and no test header/env
override. Deployment fails if an insecure identity provider is enabled.

### 7.4 Sequence

2H.1 Section 5.3 now contains the kernel identity sequence:

```text
connect -> accept -> getsockopt(SO_PEERCRED) -> immutable identity ->
allowlist check -> bounded request parse -> reject identity fields ->
authorize (identity, request) -> fixed operation -> audit -> response
```

### 7.5 Residual and implementation requirements

- `SO_PEERCRED` is not implemented or tested.
- Controller digest migration must remove request identity fields.
- Cross-UID tests must prove spoofed JSON/headers cannot authorize.
- Allowed-UID process compromise remains a residual.
- Root/kernel compromise remains out of scope.

**H-03 disposition:** design resolved; implementation and tests open.

---

## 8. H-04 - Manager-broker boundary is unresolved; current HTTP auth is unsafe if retained

### 8.1 Original finding

**F-04 / H-04: Manager-broker boundary is unresolved; current HTTP auth is unsafe if retained.**

2L.2I.1 evidence: 2H.1 and 2H.5 left UDS-versus-HTTP open; the current broker auth merged caller
headers over real peer data; authorization accepted an empty token; broker settings defaulted
insecurely; the manager client was a stub.

### 8.2 Decision

**Direct-bind UDS. No HTTP fallback in the target.**

| Item | Fixed decision |
|---|---|
| Path | `/run/flaghunt/manager-broker/broker.sock` |
| Client | Manager, UID/GID `4600/4600` |
| Server | Broker, UID/GID `4601/4601` |
| Directory | `flaghunt-broker:flaghunt-manager` `0750` |
| Socket | `flaghunt-broker:flaghunt-manager` `0660` |
| Authentication | `SO_PEERCRED` on both ends; numeric allowlists |
| Authorization | Broker operation/resource policy; manager remains responsible for user authentication |
| Protocol | `flaghunt-local` / `2L.2I.2` / `protocol_class=management` |
| Identity fields | Rejected; never authority |
| Bearer token | Not part of target |
| Test peer headers | Removed from target |
| Fallback | None |

The management operation set is `HEALTH_CHECK`, `PROVISION_INSTANCE`, `INSPECT_INSTANCE`,
`STOP_INSTANCE`, and `CLEANUP_INSTANCE`. Payloads are bounded to instance/challenge/catalog
identity and approved duration/port fields. Arbitrary images, mounts, commands, volumes, and
host/network settings are not accepted.

### 8.3 Transitional behavior

There is no automatic HTTP compatibility mode. If a temporary HTTP bridge is ever proposed, it
requires a separate approved change, a mandatory non-empty token, a loopback-only bind, no
test/peer headers, an explicit removal date, and fail-closed startup. It is not part of this target
and must not be enabled by default. The target implementation must remove the HTTP client path and
the insecure empty-token/default configuration from the live route.

### 8.4 Residual and implementation requirements

- The real UDS does not exist.
- The manager client remains a stub.
- Broker management operations are currently unavailable in the live path.
- Cross-UID/socket-permission/peer-auth tests are not run.
- The target must prove no HTTP listener is reachable from the manager path.

**H-04 disposition:** design resolved; implementation and tests open.

---

## 9. H-05 - Wire protocol/operation contract is not frozen and conflicts with current contracts

### 9.1 Original finding

**F-05 / H-05: Wire protocol/operation contract is not frozen and conflicts with current
contracts.**

2L.2I.1 evidence: 2H.1 used nested `policy` and `deadline_ms`; the current controller request was
flat; the helper used `timeout_ms`, `2L.2G.3`, `REMOVE_OWNED_POLICY`, and
`RECONCILE_OWNED_POLICY`; there was no error-code registry.

### 9.2 Frozen protocol

| Item | Frozen value |
|---|---|
| Protocol name | `flaghunt-local` |
| Schema version | `2L.2I.2` |
| Classes | `management`, `firewall_control`, `runtime` |
| Message types | `request`, `response` |
| Framing | 4-byte unsigned big-endian length + exact UTF-8 bytes |
| Maximum message | 65,536 bytes request and response |
| Encoding | Canonical JSON; duplicate keys and unknown fields rejected |
| Connections | One request/response per connection |
| Deadline field | `deadline_ms`, integer `1..120000` |
| Ownership field | `ownership_reference` only |
| Idempotency | Global per receiver |
| Version behavior | Exact match; no negotiation; no `2L.2G.3` compatibility in production |
| Identity | `SO_PEERCRED` only; no request identity fields |
| Retries | No blind retry; timeout/missing/ambiguous result is `uncertain` |

Canonical request envelope:

```json
{
  "protocol": "flaghunt-local",
  "schema_version": "2L.2I.2",
  "message_type": "request",
  "protocol_class": "firewall_control",
  "request_id": "req-...",
  "operation_id": "op-...",
  "idempotency_key": "idem-...",
  "operation": "INSTALL_POLICY",
  "deadline_ms": 5000,
  "payload": {}
}
```

Canonical response envelope:

```json
{
  "protocol": "flaghunt-local",
  "schema_version": "2L.2I.2",
  "message_type": "response",
  "protocol_class": "firewall_control",
  "request_id": "req-...",
  "operation_id": "op-...",
  "status": "ok",
  "result": {},
  "error": null,
  "server": {"service": "flaghunt-fwhelper", "version": "0.1.0", "backend": "nftables"}
}
```

`status` is `ok`, `error`, or `uncertain`. `error` is either `null` or
`{"code": "<REGISTRY_CODE>", "message": "<bounded sanitized text>", "details": {}}`. `uncertain`
is never success.

### 9.3 Frozen operations

Firewall control:

- `HEALTH_CHECK`
- `INSTALL_POLICY`
- `INSPECT_POLICY`
- `VERIFY_POLICY`
- `REVOKE_POLICY`
- `REMOVE_STALE_POLICY`
- `RECONCILE_PENDING_OPERATIONS`

Management:

- `HEALTH_CHECK`
- `PROVISION_INSTANCE`
- `INSPECT_INSTANCE`
- `STOP_INSTANCE`
- `CLEANUP_INSTANCE`

Runtime:

- `RUNTIME_CREATE_INSTANCE`
- `RUNTIME_START_INSTANCE`
- `RUNTIME_INSPECT_INSTANCE`
- `RUNTIME_STOP_INSTANCE`
- `RUNTIME_REMOVE_INSTANCE`

### 9.4 Frozen field and rule contract

- IDs match `\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z`; no coercion.
- `policy_version` is an integer `0..2^63-1`; no bool/float/string/overflow.
- Digests are 64 lowercase hexadecimal characters.
- `required_families` is a non-empty unique array of `ipv4`/`ipv6`.
- Firewall rules are typed entries with `family`, `protocol` (`tcp`/`udp`), source/destination CIDR,
  port range `1..65535`, and action `accept`/`drop`; at most 256.
- `any`, ICMP/ICMPv6, port `0`, raw rule text, and implicit all-protocol are not accepted in
  `2L.2I.2`.
- Unknown operations/classes/fields are rejected before dispatch/backend access.
- No compression, streaming, multipart, or executable content.

### 9.5 Frozen error registry

`INVALID_REQUEST`, `MALFORMED_FRAME`, `REQUEST_TOO_LARGE`, `UNSUPPORTED_PROTOCOL`,
`UNSUPPORTED_SCHEMA_VERSION`, `UNKNOWN_OPERATION`, `UNKNOWN_FIELD`, `DUPLICATE_FIELD`,
`INVALID_ID`, `INVALID_DIGEST`, `INVALID_POLICY_VERSION`, `INVALID_DEADLINE`, `UNAUTHORIZED_PEER`,
`UNAUTHORIZED_OPERATION`, `OWNERSHIP_UNKNOWN`, `OWNERSHIP_MISMATCH`, `IDEMPOTENCY_CONFLICT`,
`BACKEND_UNAVAILABLE`, `BACKEND_REJECTED`, `VERIFY_FAILED`, `UNCERTAIN`, `TIMEOUT`,
`SERVICE_UNAVAILABLE`, `INTERNAL_ERROR`.

### 9.6 Compatibility mapping

The mock contract is not the target contract. Any migration must explicitly map:

| Current/mock | Target |
|---|---|
| `timeout_ms` | `deadline_ms` |
| `2L.2G.3` | `2L.2I.2` |
| `REMOVE_OWNED_POLICY` | `REMOVE_STALE_POLICY` |
| `RECONCILE_OWNED_POLICY` | `RECONCILE_PENDING_OPERATIONS` |
| `ownership_record_id` | `ownership_reference` |
| Flat controller request | Canonical envelope with `payload` |
| Per-operation idempotency key | Global-per-receiver key |

The production target does not dual-accept the old and new contracts. A version change is a
reviewed breaking change.

### 9.7 Residual and implementation requirements

- No protocol library exists for `flaghunt-local`/`2L.2I.2`.
- No real controller/helper/manager UDS client exists.
- No conformance/negative test has been run.
- The current helper contract still accepts broader values until changed in an approved phase.
- The mock `2L.2G.3` contract remains a test artifact, not a target.

**H-05 disposition:** design/contract frozen; implementation and tests open.

---

## 10. Medium findings M-01 through M-09

All nine Medium findings are individually dispositioned. None is silently closed.

### 10.1 M-01 - Idempotency key scope contradicts across documents and schema

**Source:** F-06.

**Decision:** global per receiver.

The durable key is `idempotency_key` alone, unique across all operations at that receiver. The row
binds operation, canonical request digest, authenticated principal, and ownership. Reusing the key
with a different payload/operation/principal is `IDEMPOTENCY_CONFLICT`. The previous
`(idempotency_key, operation_type)` PK is a migration target, not the target model.

**Updated:** 2H.1 Section 4.3; 2H.2 T-06/RR-03; 2H.4 Section 3.1 and schema; 2H.5 Sections 2.4,
2.6, 4.2.

**Status:** design resolved; DB migration/tests open.

### 10.2 M-02 - Target UDS lifecycle is not matched by current scaffold, and the target lacks an implementation contract

**Source:** F-07.

**Decision:** direct-bind lifecycle with tmpfiles-created server-owned `0750` directories, exact
owner/group/mode checks, dead/live socket probing, temp-bind plus atomic rename, own-inode cleanup,
`FD_CLOEXEC`, and no descriptor passing. The current `uds.py` unconditional unlink behavior is
explicitly not reusable.

**Updated:** 2H.1 Sections 5.1-5.2; 2H.2 T-03; 2H.4 Section 6.3; 2H.5 test layers.

**Status:** design resolved; implementation/tests open.

### 10.3 M-03 - 2H residual register omits I-07, I-08, and I-09

**Source:** F-08.

**Decision:** add I-07, I-08, and I-09 with exact titles, evidence, status, and acceptance gates.
Update all five documents' residual references and the legacy mock register. Do not imply that all
fields are validated.

**Updated:** 2H.2 Section 6/6.1; 2H.5 Section 2.5; cross-document consistency in Section 13.

**Status:** tracking resolved; all three remain **OPEN**.

### 10.4 M-04 - No per-threat validation test mapping

**Source:** F-09.

**Decision:** add a normative per-threat test mapping for T-01 through T-28, with test IDs and
gates, including negative/fault-injection cases.

**Updated:** 2H.2 Section 4.3; 2H.5 Section 4.2.

**Status:** mapping documented; no test executed.

### 10.5 M-05 - Threat register misses FD passing, supply-chain, Docker daemon, and audit/disk exhaustion

**Source:** F-10.

**Decision:** add T-25 (descriptor/ancillary-data injection), T-26 (supply-chain), T-27
(Docker/runtime-adapter), and T-28 (audit/disk exhaustion), each with controls, detection, recovery,
residual risk, and test IDs.

**Updated:** 2H.2 Section 4; 2H.1 Sections 5.2/5.5; 2H.5 test layers.

**Status:** threats documented; controls/tests open.

### 10.6 M-06 - Evidence immutability and aggregate lifecycle invariants are prose only

**Source:** F-11.

**Decision:** add append-only evidence enforcement, foreign keys, transaction/CAS aggregate guards,
and explicit family/aggregate invariants. `PARTIALLY_INSTALLED` and `PARTIALLY_REVOKED` become
derived API statuses, not stored aggregate states. `ACTIVE` requires all required families
`VERIFIED`; `REVOKED` requires all required families `REVOKED` with absence evidence.

**Updated:** 2H.4 Sections 2.2-2.5 and 5.2; 2H.5 Sections 2.6/4.2.

**Status:** design resolved; migration/trigger tests open.

### 10.7 M-07 - Numeric UID/GID and allowlist/config contract undefined; helper config group unspecified

**Source:** F-12.

**Decision:** define proposed numeric IDs `4600`-`4605`, per-service primary groups, exact socket
paths/modes, root-owned `0640` service configs, non-empty numeric allowlists, and startup validation.
Empty/wildcard/zero allowlists fail closed. The helper config group is `flaghunt-fwhelper`.

**Updated:** 2H.1 Section 5.3; 2H.3 Section 5.4; 2H.4 Sections 6.2-6.3; 2H.5 Sections 2.3/2.7.

**Status:** design resolved; deployment checks open.

### 10.8 M-08 - Current helper contract is broader/differently versioned than the target rule/operation contract

**Source:** F-13.

**Decision:** intentional tightening and explicit version transition:
`2L.2G.3` -> `2L.2I.2`; `timeout_ms` -> `deadline_ms`; `REMOVE_OWNED_POLICY` ->
`REMOVE_STALE_POLICY`; `RECONCILE_OWNED_POLICY` -> `RECONCILE_PENDING_OPERATIONS`; bounded
TCP/UDP, no `any`/ICMP/port 0 in v1. The old contract is not dual-accepted in production.

**Updated:** 2H.1 Sections 4.3-4.4; 2H.2 T-25/T-27; 2H.3 Sections 4/5.7; 2H.5 Section 2.4.

**Status:** design/migration contract resolved; implementation/tests open.

### 10.9 M-09 - Exact nftables hook priority, cross-family atomicity, Docker ordering, seccomp/MAC, and boot baseline remain unvalidated

**Source:** F-14.

**Decision:** not resolvable by documentation. It remains an explicit open host gate: exact
nftables hook priority, cross-family atomicity, Docker/DOCKER-USER ordering, seccomp/MAC profile,
capability proof, boot baseline, traffic/drift/reboot/rollback tests, and T-11/T-13/T-27 risk
acceptance.

**Updated:** 2H.3 Sections 5.2/5.7 and open decisions; 2H.4 Section 9; 2H.5 Sections 4-7.

**Status:** **OPEN - blocks live integration.**

### 10.10 Medium disposition table

| ID | F-ID | Disposition | Open item |
|---|---|---|---|
| M-01 | F-06 | Design resolved: global key | DB migration/tests |
| M-02 | F-07 | Design resolved: deterministic direct-bind lifecycle | Implementation/tests |
| M-03 | F-08 | Tracking resolved | I-07/I-08/I-09 remain open |
| M-04 | F-09 | Mapping resolved | Tests not run |
| M-05 | F-10 | Threats T-25..T-28 added | Controls/tests not run |
| M-06 | F-11 | Schema/guard design resolved | Migration/trigger tests |
| M-07 | F-12 | Numeric/config design resolved | Deployment checks |
| M-08 | F-13 | Version/tightening contract resolved | Implementation/tests |
| M-09 | F-14 | Explicitly retained as host gate | **Open** |

---

## 11. Residual-risk register RR-01 through RR-07

All seven original residuals remain open. No documentation edit closes them.

| ID | Residual | Status | Remediation/control recorded | Closure evidence still required |
|---|---|---|---|---|
| RR-01 | `request_id` canonical validation scope | **OPEN** | Frozen ID regex; reject non-string/empty/control/oversized before store/idempotency; test every path | Universal validation tests, not only 3.10 fields |
| RR-02 | `operation_id` canonical validation/uniqueness | **OPEN** | Frozen ID regex; unique per attempt; operation binding; audit correlation | Uniqueness/operation-binding tests and DB support |
| RR-03 | `idempotency_key` canonical validation/scope | **OPEN** | Global-per-receiver key; digest/principal/ownership binding; unique constraint | Migration from `(key, operation)` PK with duplicate handling and conflict tests |
| RR-04 | `policy_version` range/type | **OPEN** | App rejects bool/float/string/overflow; SQLite signed-64/non-negative check; quarantine legacy rows | Migration and malformed-value tests |
| RR-05 | Full-scan reconciliation coverage | **OPEN** | Controller scans all owned/non-terminal/uncertain/legacy records; no auto-adoption | Fault-injection and restart tests |
| RR-06 | I-3.9-01 digest DB `CHECK` | **OPEN** | Canonical 64-hex check on digest-bearing tables after legacy validation | Migration tests and invalid-read fail-closed tests |
| RR-07 | I-3.9-03 retained `__context__`/exception context | **OPEN** | Bounded error mapper; no raw exception context/traceback in response or audit | Exception-chain/logging tests on all paths |

The four-location closure rule remains in force: mock-layer, real transport, database migration,
and deployment/operations. A fix in one location does not close the others.

---

## 12. I-07, I-08, I-09, and legacy mock residuals

### 12.1 Added informational residuals

| ID | Exact residual title | Evidence basis | Status | Required disposition |
|---|---|---|---|---|
| I-07 | Broader identifier/field scope | `request_id`, `operation_id`, `idempotency_key`, ownership-reference fields, and legacy-validator breadth were excluded from the 3.10 canonical gate; 3.11 Sections 5.2/8/9; 2L.2I.1 F-08; current coercion/legacy validation | **OPEN** | Universal canonical ID/ownership validation at every entry point; no field claimed validated without a test |
| I-08 | Raw `BrokerDBError` on non-failure paths | SQLite text/paths may propagate through initial intent or success-path writes; 3.11 raw-error observations; 2L.2I.1 F-08 | **OPEN** | Sanitized error mapper on all persistence paths; bounded codes; no raw SQLite text/path in response/log/audit |
| I-09 | `strict_auth=False` legacy footgun | `MockAuthorizationProvider` authorizes any valid dictionary without peer identity; 3.7/3.11; 2L.2I.1 F-08 | **OPEN** | Remove from live path; test-only provider outside production imports; production requires `TrustedPeerIdentity`; deployment assertion |

### 12.2 Legacy mock residual register

| Item | Current evidence/classification | Status | Target location |
|---|---|---|---|
| `request_id` validation | Coerced to `str`; excluded from canonical gate | **OPEN - RR-01/I-07** | Envelope schema + mock validation |
| `operation_id` validation | Coerced; no uniqueness/operation binding | **OPEN - RR-02/I-07** | Envelope schema + operation journal |
| `idempotency_key` validation/scope | Coerced; PK `(key, operation_type)`; documents disagreed | **OPEN - RR-03/I-07** | Global unique key + DB migration |
| Non-SQLite-range `policy_version` | Accepts bool as int; overflow reachable | **OPEN - RR-04** | App + DB check |
| Full-scan reconciliation | Scans some owned/pending rows; target coverage missing | **OPEN - RR-05** | Controller recovery design + 2H.7 |
| Database digest `CHECK` | Direct store accepts malformed digest | **OPEN - RR-06/I-3.9-01** | DB migration + app/helper validation |
| Python exception-context retention | Raw `BrokerDBError` in `__context__`; raw errors elsewhere | **OPEN - RR-07/I-3.9-03/I-08** | Error mapper + logging/deployment |
| Broader field/validator scope | Legacy validator breadth and ownership refs excluded | **OPEN - I-07** | Universal schema + tests |
| `strict_auth=False` | Mock provider bypasses peer identity | **OPEN - I-09** | Remove/gate test-only + deployment assertion |

The legacy register is not a closed list. It records known mock-layer residuals so that the target
design does not accidentally present them as resolved. The current mock remains the only executed
implementation.

---

## 13. Cross-document consistency verification

### 13.1 Consistency matrix

| Topic | 2H.1 | 2H.2 | 2H.3 | 2H.4 | 2H.5 | Result |
|---|---|---|---|---|---|---|
| Direct-bind UDS, no HTTP fallback | Sections 3.1, 4.1, 5.1-5.2, 5.8 | TB-1; T-01/T-03; assumptions | Section 5.5 | Section 6.3/6.5 | Sections 2.1-2.4, 3, 4 | Consistent |
| Service IDs/allowlists | Section 3.4, 5.3 | Section 3.2 | Section 5.4 | Section 6.2 | Section 2.3 | Consistent |
| Broker has no Docker authority | Sections 3.1-3.2 | T-10, T-27 | Sections 5.2, 5.7 | Sections 6.2-6.4 | Sections 2.1-2.4, 2.7 | Consistent |
| Runtime adapter fixed operations | Sections 3.1-3.2, 4.4 | T-27 | Section 5.7 | Sections 6.2-6.4 | Sections 2.3-2.4, 3 | Consistent |
| Immutable `SO_PEERCRED` identity | Section 5.3 | Section 3.2; T-04 | Section 5.4 | Sections 6.2-6.3 | Sections 2.4, 4.2 | Consistent |
| Protocol name/version/envelope | Sections 4.1-4.4 | T-25..T-28 references | Sections 5.4, 5.7 | Section 6.3 | Sections 2.4, 4.2 | Consistent |
| `deadline_ms` / no `timeout_ms` | Sections 4.3-4.4, 5.6 | Cross-reference | Section 5.7 | Section 6.3 | Sections 2.4, 4.2 | Consistent |
| `ownership_reference` / no wire alias | Sections 4.2-4.4 | Cross-reference | Section 5.7 | Sections 2.2, 2.5 | Sections 2.4, 4.2 | Consistent |
| Global idempotency | Section 4.3 | T-06; RR-03 | Section 5.7 | Sections 2.2, 3.1, 5.2 | Sections 2.4, 2.6, 4.2 | Consistent |
| Per-family derived partial states | Sections 3.4, 5.7 | T-15/T-16 | Section 5.7 | Sections 2.4, 2.5 | Sections 2.4, 4.2 | Consistent |
| Append-only evidence/FKs | Section 5.7 | T-24/T-25 | Section 5.7 | Sections 2.2, 2.5, 5.2 | Sections 2.6, 4.2 | Consistent |
| RR-01..RR-07 open | Section 8 | Section 6 | Section 8 | Section 9 | Section 2.5 | Consistent |
| I-07..I-09 open | Section 8 | Sections 6/6.1 | Section 8 | Section 9 | Section 2.5 | Consistent |
| Live gate closed | Header, Section 8 | Header, assumptions | Header, Section 8 | Header, Section 8 | Header, Section 6.3 | Consistent |

### 13.2 Contradictions removed

The remediation removed or explicitly superseded the following conflicts:

1. Root-owned `0750` directory with a different-group client versus a direct-bind server needing
   directory write.
2. Broker Docker access versus the claim that the broker cannot bypass the firewall chain.
3. Caller-supplied mock `peer_uid`/`peer_gid` versus kernel-authenticated identity.
4. Manager UDS-versus-HTTP open decision versus the live HTTP auth weakness.
5. Nested `policy`, flat controller request, `timeout_ms`, helper operation names, `2L.2G.3`, and
   missing error registry.
6. Per-operation versus global idempotency key scope.
7. Stored `PARTIALLY_INSTALLED`/`PARTIALLY_REVOKED` versus an aggregate state machine.
8. Prose-only evidence immutability versus database enforcement.
9. Undefined numeric IDs/config versus named-only service identities.
10. Broker `ownership_record_id` alias versus the target `ownership_reference`.
11. Missing T-25..T-28 threat classes and missing I-07/I-08/I-09 residual entries.

### 13.3 Remaining consistency limits

- The documents are internally consistent about the **target design**, not about a live
  implementation.
- 2H.5 is a roadmap; its phase gates are not test results.
- The runtime adapter's host-root residual remains intentionally unresolved.
- Host-lab values (nftables hook priority, seccomp/MAC exact profile, Docker ordering, boot
  baseline) remain open by design.

---

## 14. Validation and test evidence status

### 14.1 What was verified in this phase

- The five 2H documents were read and edited in the affected areas.
- The 2L.2I.1 finding IDs and titles were preserved.
- The original High/Medium findings were mapped to H-01..H-05 and M-01..M-09.
- The target documents now agree on:
  - direct-bind UDS;
  - numeric service identities;
  - no HTTP manager path;
  - no broker Docker authority;
  - immutable `SO_PEERCRED` identity;
  - frozen protocol/version/operation/timeout/error contract;
  - global idempotency;
  - per-family derived partial states;
  - append-only evidence/FK design;
  - explicit T-25..T-28 threats;
  - open RR-01..RR-07 and I-07..I-09.
- No source, test, migration, runtime config, UDS, helper, Docker, firewall, systemd, or host state
  was changed.

### 14.2 What was not verified

- No socket was created.
- No `SO_PEERCRED` call was made.
- No cross-UID allow/deny test was run.
- No directory/socket mode test was run.
- No `SCM_RIGHTS`/descriptor test was run.
- No protocol conformance/negative test was run.
- No idempotency or evidence-trigger test was run.
- No helper capability/seccomp/MAC test was run.
- No nftables/iptables/Docker test was run.
- No runtime adapter test was run.
- No crash/restart/reconciliation test was run.
- No live host validation was attempted.

### 14.3 Test gate

2H.2 Section 4.3 now maps T-01..T-28 to test IDs and gates. 2H.5 Section 4.2 expands the required
negative, fault-injection, host, and recovery cases. These are **requirements**, not results.

The documentation-only phase cannot satisfy any host or implementation gate. A future review must
require executed evidence. No skipped or blocked test may be summarized as a pass.

---

## 15. Unresolved decisions and required acceptance

The following remain open and must not be treated as design-complete:

1. **T-11 controller compromise:** explicit risk acceptance, host isolation/monitoring criteria, and
   named acceptance authority.
2. **T-13 `CAP_NET_ADMIN` helper compromise:** explicit risk acceptance and bounded blast-radius
   criteria.
3. **T-27 runtime adapter/Docker host-root equivalence:** explicit acceptance or removal of online
   Docker daemon access. A proxy does not eliminate this authority.
4. **Helper implementation:** native fixed binary versus locked-down interpreter; exact
   supply-chain/seccomp/MAC profile.
5. **Single helper versus split read-only helper.**
6. **nftables table/chain/hook priority and Docker coexistence.**
7. **IPv6-disabled host policy and one-family approval** (if ever allowed).
8. **Evidence signing/HMAC and key management.**
9. **Audit retention/tamper resistance and independent helper/runtime audit.**
10. **Boot baseline and pre-reconciliation exposure window.**
11. **Backup/restore and migration rollback policy.**
12. **Exact supported Ubuntu/kernel/nftables/Docker versions.**
13. **Runtime catalog manifest ownership, image signing/provenance, Docker socket group mapping.**
14. **T-11/T-13/T-27 host-lab test criteria and acceptance authority.**

None of these is resolved by the design edits. They are prerequisites for 2H.0/2H.9/2H.10.

---

## 16. Files changed and documentation-only assurance

### 16.1 Files changed

| File | Change |
|---|---|
| `docs/PHASE_2L_2H_1_REAL_TRANSPORT_TARGET_ARCHITECTURE.md` | Direct-bind UDS, no HTTP fallback, numeric IDs, typed identity, frozen protocol/envelope/operations/errors, runtime adapter, consistency rules |
| `docs/PHASE_2L_2H_2_THREAT_MODEL_AND_TRUST_BOUNDARIES.md` | Runtime boundary, T-25..T-28, per-threat tests, I-07..I-09, legacy register, updated assumptions/questions |
| `docs/PHASE_2L_2H_3_FIREWALL_BACKEND_AND_PRIVILEGE_DESIGN.md` | Direct-bind directory/socket model, runtime adapter segregation, Docker residual, startup order, open decisions |
| `docs/PHASE_2L_2H_4_PERSISTENCE_RECOVERY_AND_DEPLOYMENT_DESIGN.md` | Global idempotency, append-only evidence/FKs, derived partial states, numeric users, exact socket modes, runtime adapter deployment |
| `docs/PHASE_2L_2H_5_IMPLEMENTATION_AND_VALIDATION_ROADMAP.md` | Updated diagrams/matrix/protocol/residuals, phase sequence, tests, go/no-go criteria, unresolved decisions |
| `docs/PHASE_2L_2I_2_TARGETED_ARCHITECTURE_BLOCKER_REMEDIATION.md` | This report |

### 16.2 Explicit non-changes

No file under `broker/`, `manager/`, `tests/`, migration directories, deployment templates, or any
runtime/configuration directory was changed **by this phase**. No socket, process, service account,
capability, Docker object, firewall rule, systemd unit, or host setting was touched by this phase.

### 16.3 Document-only assurance

The remediation is traceable to documentation edits and design decisions. It is not evidence of a
running system. Any future implementation must add tests and obtain its own review.

---

## 17. Final decision and authorization boundary

### 17.1 Final decision

> **CONDITIONAL — Targeted design remediation is complete; implementation remains blocked by open residual acceptance and unexecuted host tests.**

This is the only supportable decision:

- The five High design defects are no longer ambiguous.
- H-02's broker Docker authority is removed, but T-27's runtime-adapter host-root residual is
  explicitly open.
- All nine Medium findings are dispositioned.
- RR-01..RR-07 and I-07..I-09 remain open.
- No test or live control exists.
- No authorization to implement has been granted.

### 17.2 Integration gate

> **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

No live firewall integration, Docker integration, privileged helper deployment, UDS deployment,
service account creation, capability grant, migration, or host change is authorized.

### 17.3 Required next action

An independent follow-up review must:

1. verify this remediation against the five 2H documents;
2. confirm that every H/M finding is individually accounted for;
3. decide whether the direct-bind permission model, runtime-adapter residual, frozen protocol,
   identity contract, and residual register are acceptable;
4. require explicit T-11/T-13/T-27 acceptance or removal;
5. keep the live gate closed until a separately authorized implementation and host-lab validation
   phase produces executed evidence.

Stop after documentation changes. Do not implement.
