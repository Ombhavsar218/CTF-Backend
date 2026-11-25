# Phase 2L.2I.1 — Independent Architecture and Security Design Review

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Review type:** Independent, read-only architecture and security design review  
**Reviewed phase:** 2L.2H — Real-Transport Architecture Design  
**Previous decision:** DESIGN COMPLETE  
**Date:** 2026-11-13  
**Decision:** **CONDITIONAL — Specific blockers must be resolved.**  
**Integration gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

> This review created only this document. It did not modify application source, tests, configuration,
> migrations, dependencies, services, sockets, capabilities, firewall state, Docker, systemd, or host
> configuration. No UDS, `SO_PEERCRED`, privileged helper, `CAP_NET_ADMIN`, nftables, iptables, or live
> transport was implemented or exercised.

---

## 1. Executive decision

The five Phase 2L.2H documents describe a sound security direction: a privileged helper is isolated from
an unprivileged controller, kernel `SO_PEERCRED` replaces caller-supplied identity, helper operations are
fixed and typed, firewall mutations require read-back and evidence, and terminal lifecycle states are
not inferred from a request being sent. The documents are unusually clear about the distinction between
the current local mock and the proposed Linux target.

The architecture is **not** ready for real-transport implementation as written. I found:

| Severity | Count | Meaning |
|---|---:|---|
| Critical | 0 | No fundamental defect requires abandoning the architecture. |
| High | 5 | Design or implementation-contract blockers that must be corrected before real transport or helper work. |
| Medium | 9 | Important gaps that must be resolved or explicitly accepted before the relevant phase. |
| Low / Informational | 0 separately counted | Covered by the Medium gaps or by the open decisions already listed in 2H. |

The decision is **CONDITIONAL**, not PASS, because the following High findings remain open:

1. **The proposed socket directory modes cannot work as written.** The client is not in the directory
   group, and in the direct-bind case the server is not able to create the socket either. The three
   required UDS edges would be inaccessible or contradictory across documents.
2. **The broker's Docker authority is not bounded.** The documents call the broker "restricted" and say
   it cannot mutate host firewall state, but a conventional Docker socket is effectively host-root
   equivalent and can bypass the controller/helper chain. No Docker API proxy or accepted-risk statement
   exists.
3. **The target controller identity adapter is undefined.** The current controller authorizes from
   `req["peer_uid"]`/`req["peer_gid"]`, and the current idempotency digest includes those request fields.
   The target documents say the kernel identity is authoritative but do not define how it reaches the
   service, how request identity fields are removed, or how the digest binds the authenticated peer.
4. **The manager-to-broker boundary is unresolved and the current HTTP path is unsafe.** The 2H documents
   leave UDS versus loopback HTTP open, but the existing broker auth still accepts test headers and
   merges them over real peer credentials; an empty broker token is treated as valid. If the HTTP option
   is selected, this is not a safe implementation base.
5. **The wire contract is not frozen.** The proposed envelope is nested under `policy`, while the
   current controller and helper contracts are flat; `deadline_ms` and `timeout_ms` conflict; operation
   names and schema versions differ from the current helper contract; and no complete request/response
   schema or error-code registry exists.

There is no Critical finding because the intended trust direction and privilege separation are viable,
and the problems above are fixable without replacing the architecture. There is also no PASS because
these are not merely optional cleanups: the first three directly affect whether the required chain can
be built and whether identity is actually kernel-authenticated.

The 3.11 local mock PASS remains valid only for its scoped mock review. It is not evidence that any target
control exists.

### 1.1 Decision matrix against the requested criteria

| Criterion | Result |
|---|---|
| No unresolved Critical or High design finding | **Not met** — five High findings. |
| No blocking trust-boundary or privilege-separation defect | **Not met** — broker Docker authority and controller identity seam. |
| Required implementation contracts sufficiently defined | **Not met** — socket permissions, wire schema, manager-broker edge, and identity adapter are incomplete or contradictory. |
| Remaining decisions explicitly documented and accepted for later resolution | **Partially met** — the documents list many decisions, but the unresolved socket permissions and trust-boundary issues are not merely deferred decisions; they are incorrect or incomplete as written. |
| Architecture fundamentally unsafe or unsuitable | **Not met** — no redesign is required; remediation is possible. |

---

## 2. Review scope and limitations

### 2.1 Scope

This review covers the complete proposed chain:

```text
Manager -> Restricted Broker -> Unprivileged Firewall Controller -> Privileged Helper -> Host Firewall
```

It reviews:

- authority, trust assumptions, authentication, authorization, validation, error handling, audit, and
  failure boundaries;
- UDS creation, ownership, permissions, lifecycle, `SO_PEERCRED`, allowlists, framing, limits,
  timeouts, malformed input, replay, and fail-closed behavior;
- privilege separation, service identities, `CAP_NET_ADMIN`, seccomp, systemd hardening, filesystem
  permissions, and the rejection of root/shell execution;
- nftables primary and iptables/DOCKER-USER fallback design, ownership markers, IPv4/IPv6 parity,
  validation, atomicity, Docker interaction, and restart persistence;
- persistence, recovery, evidence, migrations, integrity, concurrency, unknown states, Ubuntu
  deployment, operations, monitoring, and testing;
- the 24-threat register, RR-01 through RR-07, and the earlier mock-controller limitations;
- cross-document consistency and implementation readiness.

### 2.2 Method and limitations

This was a static, read-only review of the documents and the relevant current code. I did not:

- implement or modify any source, test, configuration, migration, service, socket, capability, or host
  state;
- run a live UDS, `SO_PEERCRED`, privileged helper, nftables, iptables, Docker, systemd, or firewall
  experiment;
- grant privileged access or use sudo;
- rerun the 3.11 test suites or treat their counts as newly reproduced evidence.

The 3.11 review is treated as prior evidence for the current mock scope only. The current code is used
to establish existing behavior and constraints, not to prove any proposed target control. The review
does not assume that a design statement is implemented.

### 2.3 Environment assumptions used for the review

The proposed target assumes:

- a Linux host with Unix domain sockets and `SO_PEERCRED`;
- systemd and a supported Ubuntu LTS baseline;
- nftables as primary, with iptables/DOCKER-USER only as a validated fallback;
- rootful Docker and a validated Docker firewall integration;
- host root and the kernel are trusted for the local authentication model;
- service users, groups, and runtime directories are provisioned by a trusted deployment process;
- the controller and broker use separate local SQLite databases with no untrusted shared writer.

These assumptions are appropriate for the design, but several of them are not yet validated in a host
lab. The documents correctly call many of them open decisions.

---

## 3. Documents and code inspected

### 3.1 Required design documents

| Document | Use in this review |
|---|---|
| `docs/PHASE_2L_2H_1_REAL_TRANSPORT_TARGET_ARCHITECTURE.md` | Target components, trust boundaries, UDS, protocol, operation contract, open decisions. |
| `docs/PHASE_2L_2H_2_THREAT_MODEL_AND_TRUST_BOUNDARIES.md` | Assets, boundaries, 24-threat register, residual register, assumptions/non-goals. |
| `docs/PHASE_2L_2H_3_FIREWALL_BACKEND_AND_PRIVILEGE_DESIGN.md` | nftables/iptables design, ownership markers, capability and hardening design. |
| `docs/PHASE_2L_2H_4_PERSISTENCE_RECOVERY_AND_DEPLOYMENT_DESIGN.md` | Schema extensions, per-family state, crash matrix, migration, Ubuntu deployment. |
| `docs/PHASE_2L_2H_5_IMPLEMENTATION_AND_VALIDATION_ROADMAP.md` | Roadmap, test layers, dependencies, go/no-go criteria. |

### 3.2 Prior review and existing contract

| Document | Use in this review |
|---|---|
| `docs/PHASE_2L_2G_3_11_INDEPENDENT_FINAL_MOCK_CONTROLLER_SECURITY_REVIEW.md` | Scoped mock PASS, F/R classifications, and accepted residuals. |
| `docs/PHASE_2L_2A_LIVE_FIREWALL_CONTROLLER_INTERFACE_CONTRACT.md` | Earlier controller interface intent; used only as context, not as a frozen target contract. |

### 3.3 Current code inspected for behavior and constraints

| File | Relevance |
|---|---|
| `broker/firewall_controller_service/controller_service.py` | Current validation order, lifecycle, idempotency digest, reconciliation, and request identity use. |
| `broker/firewall_controller_service/authorization_strict.py` | Current strict authorization reads `peer_uid`/`peer_gid` from the request object. |
| `broker/firewall_controller_service/mock_transport.py` | Current mock transport injects peer identity into the request. |
| `broker/firewall_controller_service/peer_identity.py` | Mock identity provider; not kernel authentication. |
| `broker/firewall_controller_service/helper_contract.py` | Current helper schema version, operation names, protocol/port allowlists, and timeout field. |
| `broker/firewall_controller_service/ownership_store.py` | Current SQLite schema, uniqueness, evidence, and idempotency constraints. |
| `broker/firewall_controller_service/mock_backend.py` | Current controller-to-helper adapter strips some identity fields and stamps the current schema version. |
| `broker/firewall_controller_service/request_validator.py` | Current legacy request validation. |
| `broker/app/auth.py` | Current broker HTTP auth and test peer headers. |
| `broker/app/authorization.py` | Current broker peer/token checks and empty-token behavior. |
| `broker/app/uds.py` | Current UDS scaffold; not compliant with the target lifecycle rules. |
| `broker/app/config.py` | Current flat socket path and mode defaults. |
| `broker/app/firewall_controller_contract.py` | Current flat controller request shape. |
| `manager/app/broker_client.py` | Current manager-to-broker transport is a contract stub that does not connect. |

---

## 4. Trust-boundary findings

### 4.1 Boundary review matrix

| Boundary | Authority and intended authentication | Validation and authorization | Error/audit responsibility | Failure boundary | Review result |
|---|---|---|---|---|---|
| User -> Manager | Existing application authentication; user intent only | Existing Django/manager authorization; no firewall authority | Manager application audit | User request failure; no host privilege | No new defect in scope. |
| Manager -> Broker | Manager unprivileged; target UDS/peer identity or HTTP token | Broker validates operation/resource policy; current HTTP path also accepts test headers | Broker audit | Broker error must not become firewall success | **Blocked by H-04.** The target edge is unresolved and the current HTTP path is unsafe. |
| Broker -> Controller | Broker unprivileged; controller verifies kernel peer identity | Controller independently validates identity, operation, schema, ownership, lifecycle | Controller audit and durable state | No helper call unless validation passes | **Blocked by H-01/H-03/H-05.** Intended design is correct; implementation seam is not defined. |
| Controller -> Helper | Controller unprivileged; helper verifies kernel peer identity | Helper fixed enum/schema, ownership marker, bounded operation | Helper independent audit and sanitized result | Uncertain backend state remains uncertain; controller reconciles | Design direction sound; **H-01/H-02** affect deployability and bypass resistance. |
| Helper -> Kernel | Only helper has `CAP_NET_ADMIN` | Fixed backend interface, compiled typed data, ownership checks, read-back | Helper audit plus controller evidence | Helper crash/partial state requires reconciliation | Sound direction; exact backend/hook/capability proof remains open. |
| Service -> SQLite | Controller writes only controller DB; broker writes only broker DB | File permissions, single writer, CAS, integrity checks | Local audit rows | Corrupt/unavailable DB must fail closed | Mostly sound; evidence immutability and aggregate invariants need enforcement. |
| Controller/Helper -> Audit | Separate writers; sanitized structured records | Bounded reason/error codes, no raw SQL/paths/tracebacks | Independent helper audit and controller audit | Audit failure must not silently permit mutation | Mostly sound; implementation and retention are open. |

### 4.2 Bypass-path analysis

1. **Broker Docker authority can bypass the controller.** The documents say the broker may access the
   Docker operations needed for container/network responsibilities, but "firewall mutation is not a
   broker privilege" is not sufficient. A conventional Docker socket permits root-equivalent host
   actions, including privileged containers, host mounts, network namespace changes, and firewall
   manipulation. A compromised broker with that socket can bypass the controller and helper entirely.
   The threat register's T-10 only covers a compromised broker calling the controller; it does not
   model Docker API authority. This is **F-02 (High)**.

2. **Controller identity seam.** The target says request JSON identity must never be authority. The
   current controller's strict provider reads `peer_uid` and `peer_gid` from the request dictionary, and
   the current request digest includes those fields. The target documents do not define an
   out-of-band `PeerIdentity` parameter, a stripping rule at the UDS adapter, or a new digest contract.
   If an implementer injects the kernel identity into the same request dictionary, caller-controlled
   fields can survive or the digest can be computed from the wrong value. This is **F-03 (High)**.

3. **Manager/broker test headers.** The current broker auth accepts `X-Broker-Peer-UID`,
   `X-Broker-Peer-GID`, and `X-Broker-Peer-User`, then merges them over `request.state.peer_credentials`.
   The merge order means the test headers win, contrary to the comment. The current broker token
   verifier also returns success when `broker_token` is empty. The target documents correctly say the
   test headers must not exist in the live path, but the HTTP fallback has no mandatory-token or
   header-removal contract. This is **F-04 (High)**.

4. **Helper command surface.** The fixed enum, typed data, absence of shell, and caller-supplied
   identity rejection are good. No arbitrary command executor path is described. A compromised
   controller remains able to request valid owned-policy operations; that is the accepted T-11 risk,
   not a hidden command injection path.

### 4.3 Can the broker or manager obtain unrestricted host firewall privileges?

- **Manager:** No. The documents keep it unprivileged and outside the controller/helper socket path.
- **Broker:** It has no `CAP_NET_ADMIN` by design, but the answer is **not yet confirmed** because its
  Docker access is not bounded. A raw Docker socket or equivalent broad Docker API would make the
  "restricted broker" claim false. The architecture must either introduce a narrow Docker API proxy
  with a fixed operation allowlist and no privileged-container/host-mount capability, or explicitly
  accept that a broker compromise is host-root equivalent and stop claiming the broker is restricted.
- **Controller:** No `CAP_NET_ADMIN`; correct.
- **Helper:** `CAP_NET_ADMIN` only; correct in intent, but `CAP_NET_ADMIN` is itself broad and remains
  a High residual risk (T-13).

### 4.4 Failure boundaries

The controller/helper failure semantics are generally strong: intent before side effect, uncertainty
after timeout/reset, read-back before promotion, and reconciliation on restart. The manager/broker
edge is weaker because the target transport is undecided and the current HTTP auth behavior is not
fail-closed. The database boundary is conceptually separate but relies on deployment permissions and
application discipline; it does not yet have schema-enforced evidence immutability or aggregate-state
invariants.

---

## 5. UDS and `SO_PEERCRED` assessment

### 5.1 Socket directories and permissions — **High blocker**

The proposed layout in 2H.1 §5.1 and 2H.4 §6.3 is:

| Socket | Directory | Socket |
|---|---|---|
| Manager -> Broker | `/run/flaghunt/manager-broker` `root:flaghunt-broker` `0750` | `flaghunt-broker:flaghunt-manager` `0660` |
| Broker -> Controller | `/run/flaghunt/broker-controller` `root:flaghunt-fwcontroller` `0750` | `flaghunt-fwcontroller:flaghunt-broker` `0660` |
| Controller -> Helper | `/run/flaghunt/controller-helper` `root:flaghunt-fwhelper` `0750` | `flaghunt-fwhelper:flaghunt-fwcontroller` `0660` |

This cannot work as written under normal Linux permissions:

- A client needs **execute** on every parent directory to traverse to the socket. The manager is not in
  `flaghunt-broker`; the broker is not in `flaghunt-fwcontroller`; the controller is not in
  `flaghunt-fwhelper`. The clients therefore cannot reach the sockets.
- In the direct-bind case, the server needs **write** on the directory to create the socket. A
  `root:<server-group>` `0750` directory does not give the non-root server write permission, because
  the server is not the owner and its group is the server group, which has only `r-x`.
- 2H.3 §5.4 says the helper runtime directory is "service-owned, `0750`; socket `0660` with the
  controller group," while 2H.4 §6.3 says `/run/flaghunt/controller-helper` is `root:flaghunt-fwhelper`.
  Those are different ownership models.

This is not a theoretical edge case. It means the three required UDS edges are not deployable as
documented. It also undermines the T-01/T-03/T-12 control claims that cite root-owned `0750` directories.

A correct model must choose one of the following, explicitly:

**Option A — direct bind by the server:**

```text
directory:  server_user:client_group 0750   # server owns; client group has traverse
socket:     server_user:client_group 0660   # client group can connect
parent:     root:root 0755 or stricter      # no world write
```

The server creates the socket because it owns the directory; the client traverses via the group. The
client must not have directory write permission.

**Option B — systemd socket activation:**

```text
directory:  root:client_group 0750 or 0751  # systemd creates; clients traverse
socket:     server_user:client_group 0660
```

The directory owner and socket creator are the service manager; the service does not need directory
write. `RuntimeDirectoryPreserve`, `SocketMode`, `SocketUser`, and `SocketGroup` must be defined with
exact numeric IDs, and the client still needs traverse permission.

The documents should adopt one model for all three edges, use numeric UIDs/GIDs, add exact `stat`
verification at startup, and test with distinct users. This is **F-01**.

### 5.2 Creation, replacement, and cleanup

The target rules in 2H.1 §5.2 are appropriate:

- restrictive umask;
- bind to a temporary path in the owned runtime directory or use systemd's atomic setup;
- reject an existing path unless it is the expected socket owned by the expected service and not live;
- never unlink a symlink, directory, or arbitrary path;
- remove only the service's own socket on controlled shutdown;
- `FD_CLOEXEC` and inherited descriptor closure;
- reject symlinks, unexpected owner/group, or world-writable directories.

The current `broker/app/uds.py` scaffold does **not** meet these rules: `setup_unix_socket` calls
`os.makedirs`, `chmod`s the directory, and unconditionally `os.unlink`s any existing path. It does not
verify owner, group, mode, inode type, or liveness. This is a current mock scaffold, not the target, but
the target documents do not provide a replacement implementation contract or a test for the exact
lifecycle. The target must not reuse this helper unchanged. This is **F-07 (Medium)**.

The current broker config also uses the flat path `/run/flaghunt/broker.sock`, while 2H.4 proposes
`/run/flaghunt/manager-broker/broker.sock`. That is a current/target mismatch, not a defect by itself,
but it needs a migration/configuration plan.

### 5.3 Linux `SO_PEERCRED` semantics

The documents correctly state the essential semantics:

- `SO_PEERCRED` returns `struct ucred { pid, uid, gid }` for the connected peer;
- UID and primary GID are the authorization keys;
- PID is audit/correlation only;
- supplementary groups are not trusted by default;
- request JSON, HTTP headers, query parameters, and claimed PIDs are not authentication;
- non-Linux, unavailable, malformed, or unexpected credentials fail closed;
- the client should verify the server's peer UID/GID before sending a privileged request.

Those statements are correct and answer the required "why HTTP headers cannot replace kernel identity"
question. I did not find an incorrect claim that `SO_PEERCRED` proves the current process or that PID is
a stable identity.

The review did find three unaddressed semantics/assumptions:

1. **File-descriptor passing.** `SO_PEERCRED` reflects the process that connected, not every process
   that may subsequently use a passed file descriptor. If an allowed-UID service passes a connected
   socket to a less-trusted child or another process, the server still sees the original credentials.
   The target should prohibit `SCM_RIGHTS` for client sockets, close descriptors on exec, and treat
   allowed-UID compromise as T-11/T-12. The threat register does not list descriptor passing.
2. **Socket activation and server-side verification.** With systemd socket activation, client-side
   `SO_PEERCRED` verification may observe the socket creator/service-manager identity rather than the
   service process. The design says the client verifies the server but does not define how this works
   with activation. This requires host-lab validation or a different server-identity proof.
3. **User namespaces.** If any service runs in a user namespace, `SO_PEERCRED` UIDs/GIDs are mapped in
   the receiving namespace. The documents assume host services; that assumption should be explicit.

These are **F-10 (Medium)** and are not evidence of an authorization bypass in the intended
host-service model.

### 5.4 UID/GID allowlists and numeric identity

The design says allowlists are explicit, non-empty, and loaded from root-owned configuration. That is
the right policy. It does not define:

- where the allowlist file lives;
- its format;
- whether names or numeric IDs are stored;
- how the service proves the configured UID/GID matches the deployed service account;
- how an empty or unresolved allowlist is detected at startup;
- how the socket group and the primary GID relate.

The current broker defaults (`authorized_manager_uid = -1`, `authorized_manager_gid = -1`,
`broker_token = ""`) are not a safe target baseline. A numeric-identity contract and fail-closed
startup check are required. This is **F-12 (Medium)**.

### 5.5 Framing, size limits, and malformed input

The proposed 4-byte unsigned big-endian length, 64 KiB default maximum, UTF-8 JSON, one logical request
per connection, and rejection of zero/oversized/truncated/trailing/invalid UTF-8/invalid JSON/
duplicate-key/non-object input is a good design. The current helper contract also has a 64 KiB bound
and bounded compiled-policy depth.

Two implementation details remain undefined:

- canonical JSON serialization (sorting, separators, number handling, duplicate-key detection);
- exact maximum response size and error-response shape.

Python's standard `json.loads` does not reject duplicate keys by default, so the "reject duplicate
keys" requirement needs an explicit parser or hook. This is part of **F-05**, not a reason to reject the
framing model.

### 5.6 Timeouts and connection handling

The design requires bounded accept/read/validation/backend/write deadlines, a bounded `deadline_ms`
hint, a server-enforced hard deadline, and uncertainty on timeout. That is correct.

The naming is inconsistent with the current contract: 2H.1 uses `deadline_ms`, while
`helper_contract.py` allows and validates `timeout_ms`. The target contract must pick one field or
define a mapping. This is part of **F-05**.

### 5.7 Replay and duplicate-request protection

The intended layers are:

- controller durable idempotency keyed by key, operation, request digest, and ownership;
- helper bounded replay cache;
- no implicit retries;
- uncertain outcomes reconciled by read-back.

The direction is sound. The unresolved issues are:

- whether an idempotency key is unique per operation or globally (F-06);
- whether the authenticated peer identity is part of the canonical request digest (F-03);
- how duplicate keys in the JSON framing are rejected (F-05);
- what the helper cache does after restart (it is explicitly non-durable, so controller state is the only durable authority).

### 5.8 Fail-closed behavior

The fail-closed conditions in 2H.1 §5.7 are appropriate: missing/malformed `SO_PEERCRED`, empty
allowlists, unsafe socket ownership/mode, invalid schema/framing/fields, missing ownership, read-back
failure, and raw-error-only outcomes all deny the operation. The socket permission defect does not
create a bypass; it creates an unusable deployment. The identity adapter gap creates a potential
bypass if implemented carelessly.

### 5.9 UDS conclusion

The UDS design is conceptually correct and uses the right kernel primitive. It is not implementation-ready
because the directory permission model is wrong, the current scaffold violates the target lifecycle,
numeric identity/config is undefined, and the controller identity adapter is not specified.

---

## 6. Privilege-separation assessment

### 6.1 Strengths

- The controller is deliberately unprivileged and has no `CAP_NET_ADMIN`.
- The helper is the only intended `CAP_NET_ADMIN` process.
- The helper contract uses a fixed operation enum and typed data, rejects unknown fields and
  caller-supplied identity/authorization claims, and does not expose shell execution.
- The design rejects root controller, capable controller, root helper, and setuid/external privileged
  tool models.
- The helper has no direct controller/broker database access.
- The design proposes dedicated users/groups, no login shell, read-only code/config, `NoNewPrivileges`,
  capability bounding/ambient sets, seccomp, MAC, filesystem restrictions, and bounded restart.
- The design correctly recognizes that `CAP_NET_ADMIN` is not a minor privilege and leaves T-13 as a
  High residual risk.

### 6.2 Gaps and escalation paths

| Area | Assessment | Finding |
|---|---|---|
| Helper command surface | Good: fixed enum/schema, no shell, no caller-selected chain/table/executable. | No arbitrary command executor path found. |
| `CAP_NET_ADMIN` scope | Broad by nature; can alter interfaces, routes, qdiscs, netfilter. Exact minimal set is not proven. | T-13 remains High residual; must be accepted with host isolation/monitoring. |
| Socket access | Required chain is unworkable as documented; helper socket directory ownership conflicts. | **F-01**. |
| Broker Docker authority | Not bounded; can bypass controller/helper. | **F-02**. |
| Helper config permissions | "root-owned `0640` or stricter" does not state the group that must read it; helper may be unable to read its config or the file may be too broad. | **F-12** (Medium). |
| Seccomp/MAC | Proposed but no exact syscall/profile; `MemoryDenyWriteExecute`/`PrivateDevices` compatibility open. | **F-14** (host validation). |
| `RestrictAddressFamilies` | Proposed `AF_UNIX AF_NETLINK`; must be proven compatible with the chosen nftables library and helper runtime. | **F-14**. |
| systemd socket activation | Preferred, but server-identity semantics and `RuntimeDirectory` ownership are not fully defined. | **F-01/F-10**. |
| Helper implementation | Native fixed binary versus locked-down interpreter is open; supply-chain and code-loading implications are not resolved. | **F-10/F-14**. |
| Root/shell rejection | Correctly explained and rejected. | Adequate design. |

### 6.3 Privilege conclusion

The privilege-separation architecture is the strongest part of the 2H design. It remains viable. It is
not complete because the helper cannot be deployed on the documented socket permissions, the broker's
Docker authority can bypass the helper, and the exact capability/hardening proof is deferred to a lab.

A compromised controller can still issue valid helper operations for owned resources. The documents
acknowledge this as T-11. The review does not treat that as a design failure, but it does mean the
architecture cannot claim "controller compromise cannot affect the host firewall." It can only claim a
narrower blast radius. That limitation must remain explicit.

---

## 7. Firewall-backend assessment

### 7.1 Backend selection and compatibility

The nftables-first recommendation is reasonable:

| Criterion | Review |
|---|---|
| IPv4/IPv6 | `inet` family is a better fit than separate iptables/ip6tables. |
| Atomicity | Transactional batches are preferable where the backend guarantees them. |
| Ownership | Dedicated table/chains and comments are cleaner than fragile shared-chain edits. |
| Read-back | Structured netlink/libnftables read-back is preferable to parsing shell output. |
| Docker coexistence | A separate table is safer than editing Docker tables, but the hook/priority relationship is host-specific. |
| Fallback | iptables/DOCKER-USER is a reasonable compatibility fallback only after lab proof. |

The design does not select exact table/chain names, hook priorities, or Docker coexistence rules. That
is correctly identified as open. It cannot be approved for live use without host validation.

### 7.2 Ownership markers

The proposed marker fields (schema/version, ownership hash, policy hash/ID, policy version, digest
prefix, family) and per-ownership chain names are a sound way to isolate ownership and cleanup. The
documents correctly state that a marker proves **which owned object** is being changed, not that the
request is authorized.

Important limitation: the helper can only verify the marker it is given and its own recomputation. It
cannot independently verify the controller's authoritative ownership database. A compromised
controller can therefore ask the helper to install or remove a valid-looking owned object within the
helper's allowed rule model. That is T-11, and the marker is not a defense against it.

### 7.3 Atomicity, rollback, and read-back

- The install flow correctly requires durable intent, validation, a fixed batch, read-back, evidence,
  and only then promotion.
- The design correctly refuses to report dual-stack success when the backend cannot guarantee
  cross-family atomicity; per-family state and uncertainty are the right fallback.
- Revocation correctly requires absence evidence before `REVOKED`.
- Unknown/unowned rules are reported, not auto-deleted.
- Rule handles are correctly treated as audit data, not sole identity.

The exact nftables transaction boundary and cross-family guarantee remain open (F-14). The design is
safe at the semantic level because it refuses to infer success, but it is not a complete backend
specification.

### 7.4 IPv4/IPv6 parity

The requirement for explicit required families, per-family chains/rules/evidence, no `ACTIVE` without
parity, and no silent omission is correct. The IPv6-disabled host case is left open. The design says
"fail closed or require an explicit approved policy"; that is the right choice, but the approval and
evidence representation are not defined. This must be resolved before live deployment.

### 7.5 CIDR, protocol, port, and rule-model validation

The target rule model is appropriately strict:

- explicit family;
- canonical CIDR;
- reject `/0`, loopback, link-local, multicast, reserved, metadata, host/LAN ranges, and
  broadcast/network misuse;
- bounded protocol allowlist;
- ports 1-65535 or bounded ranges;
- explicit direction;
- no unbounded all-protocol accept;
- no NAT.

The current helper contract is broader than the target: it allows `any`, `icmp`, `icmpv6`, and port `0`
(`helper_contract.py`), while the target design rejects all-protocol rules and uses 1-65535. The target
may intentionally tighten this, but the documents do not define the version transition or compatibility
mapping. This is **F-13 (Medium)** and part of **F-05**.

### 7.6 Docker interaction

The Docker design is directionally correct:

- separate nftables table;
- never flush Docker tables;
- no Docker NAT ownership;
- DOCKER-USER only as a marked fallback;
- detect drift and never duplicate jumps;
- fail host validation if ordering is unsupported.

However, the same Docker dependency creates the **F-02** trust-boundary problem: the broker's own Docker
access is not bounded, and the documents do not model Docker daemon/API compromise. The firewall
controller can be correct while a broker with raw Docker access bypasses it. The threat model must cover
this or the Docker access must be narrowly proxied.

### 7.7 Restart persistence, boot baseline, and host assumptions

The persistence design correctly avoids making a global firewall file the source of challenge policy.
It says the controller DB is authoritative, boot baseline is operator-owned, unknown rules are not
adopted, and reconciliation must handle missing/partial rules. The pre-reconciliation exposure window
and boot baseline remain open decisions (F-14).

Host-specific assumptions requiring validation:

- exact Ubuntu/kernel/nftables versions;
- nftables hook priority and Docker interplay;
- `iptables-nft` versus legacy behavior if fallback is used;
- capability requirements for read/write netfilter;
- seccomp/MAC compatibility;
- systemd socket activation and `SO_PEERCRED` behavior;
- Docker restart/upgrade behavior;
- IPv6 availability;
- boot ordering and baseline.

### 7.8 Backend conclusion

The firewall design is conceptually feasible and appropriately cautious about atomicity and ownership.
It is not host-validated, and its interface/version details are incomplete. Do not run any nftables or
iptables command based on this review; none was run here.

---

## 8. Persistence and recovery assessment

### 8.1 Strengths

The persistence design has the right core properties:

- separate broker and controller databases;
- controller-only ownership/evidence authority;
- durable intent before helper side effects;
- idempotency records with status and recovery metadata;
- per-family state;
- evidence before terminal promotion;
- uncertainty for timeout/reset/partial outcomes;
- startup full-scan reconciliation;
- no auto-adoption of unknown rules;
- no false `ACTIVE`/`REVOKED` from a helper response;
- migration by backup, copy, validate, forward-only, and restore on rollback;
- integrity checks and disk-full/read-only fail-closed behavior.

The crash matrix in 2H.4 §4.1 is thorough and correctly refuses to infer success or failure from a lost
response.

### 8.2 Gaps

| Area | Finding |
|---|---|
| Idempotency key scope | 2H.2 RR-03 says "per-operation uniqueness"; 2H.4 §3.1 says "same key + different operation ... is a conflict." The current primary key is `(idempotency_key, operation_type)`, which permits the same key for different operations. This must be decided and enforced consistently. **F-06**. |
| Evidence immutability | `controller_evidence` is described as append-only/immutable, but the schema has no trigger, foreign key, or permission model that enforces it. The controller can update/delete rows. **F-11**. |
| Aggregate invariants | "`ACTIVE` only if every required family is `VERIFIED`" and "`REVOKED` only if every family is `REVOKED`" are prose invariants. The design does not define a transaction, trigger, or CAS that makes it impossible to persist an inconsistent aggregate row. **F-11**. |
| Partial states | 2H.4 says `PARTIALLY_INSTALLED`/`PARTIALLY_REVOKED` are added, but also asks whether they are primary or derived. The current lifecycle state machine does not include them. This is open, not a defect, but it must be frozen before implementation. |
| Full-scan reconciliation | The current mock scans all `list_ownerships()` rows and pending idempotency, but it lacks the target per-family/uncertain/partial state model. The target design is broader; the current behavior is not proof of target coverage. RR-05 remains open. |
| Schema/version migration | No exact DDL, migration version, checksum, or compatibility matrix is provided. The design says forward-only and backup-based, which is good, but not implementable as a migration recipe yet. |
| `policy_version` and IDs | The current legacy validator accepts bool as int and coerces IDs to strings; the target plans stricter rules. RR-01..RR-04 remain open. |

### 8.3 Does the design ever treat an unverified backend operation as success?

At the design level, **no**. The install/revoke flows require read-back and evidence; timeout/reset is
uncertain; partial family state blocks terminal promotion; unknown rules are not adopted. This is the
right semantic.

At the implementation level, the current mock service has evidence-gating paths, but it is not a real
backend and does not prove multi-family or crash-safe helper integration. The target must enforce the
invariants in storage and tests, not only in prose.

### 8.4 Can an incorrect `ACTIVE` or `REVOKED` state occur?

The design intends to prevent it. The following are the remaining ways an implementation could still
produce it, and therefore the required tests:

- writing aggregate state without a transaction spanning family rows;
- promoting on a helper response instead of controller read-back;
- accepting stale evidence after ownership/digest change;
- reconciling a `VERIFIED` record without exact evidence matching;
- marking `REVOKED` when only one family is absent;
- treating a missing helper response as success;
- using a stale socket or peer identity after replacement;
- skipping the full-scan because only `PENDING` rows were inspected.

The crash matrix and 2H.5 test plan cover many of these, but the per-threat validation mapping (F-09)
is missing and the schema invariants (F-11) are not enforced.

### 8.5 Persistence conclusion

The persistence/recovery design is strong and should be retained. It is not yet a complete schema
migration/contract, and it has two important semantic ambiguities: idempotency key scope and
aggregate/evidence invariants. These are resolvable without redesign.

---

## 9. All 24 threat-register results

### 9.1 Method

I reviewed all 24 entries in 2H.2 §4.1 and §4.2 for attacker capability, attack path, impact,
preventive control, detection, recovery, residual risk, and proposed validation test. The controls are
proposed, not implemented.

### 9.2 Per-threat result

No threat-register row contains a proposed validation-test identifier. 2H.5 §4.2 has general test
categories, but the traceability from T-01..T-24 to a specific test is absent. The "validation" column
below therefore records that gap rather than inventing tests.

| ID | Threat (short) | Result | Assessment | Validation mapping |
|---|---|---|---|---|
| T-01 | Unauthorized local process | **Conditional** | Correct kernel-auth/allowlist intent; socket permission defect **F-01** undermines deployability; no real UDS. | Generic only (F-09). |
| T-02 | Local resource exhaustion | **Conditional** | Bounded deadlines, frame size, one request/connection, and limits are appropriate; exact connection/worker limits and per-peer quota are undefined. | Generic only (F-09). |
| T-03 | Socket spoofing/replacement | **Conditional** | Target `lstat`/owner/mode/no-symlink rules are correct; current `uds.py` unconditionally unlinks and does not validate ownership/mode; client server verification under activation is unvalidated. | Generic only (F-09). |
| T-04 | UID/GID spoofing | **Gap** | Target says ignore request identity, but the current controller reads request `peer_uid`/`peer_gid`; target adapter and digest contract are missing (**F-03**). | Generic only (F-09). |
| T-05 | Request replay | **Conditional** | Controller durable idempotency and helper cache are the right layers; digest binding to kernel identity and exact helper cache semantics are unspecified. | Generic only (F-09). |
| T-06 | Idempotency-key collision | **Gap** | Key scope contradiction between "per-operation" and "different operation is a conflict"; current schema permits same key across operations (**F-06**). | Generic only (F-09). |
| T-07 | Ownership substitution | **Adequate design** | Controller resolves ownership from its DB; helper marker is not authorization; CAS/generation is the right control. Current mock only. | Generic only (F-09). |
| T-08 | Information leakage | **Conditional** | Sanitized bounded errors are designed; current I-08 raw `BrokerDBError` paths are not tracked in RR-01..RR-07; no target error mapper. | Generic only (F-09). |
| T-09 | Compromised manager | **Conditional** | Manager remains unprivileged; manager->broker authentication is unresolved and the HTTP fallback is unsafe (**F-04**). | Generic only (F-09). |
| T-10 | Compromised broker | **High gap** | Does not model broker Docker API root-equivalence; a broker with a raw Docker socket can bypass the controller/helper (**F-02**). | Generic only (F-09). |
| T-11 | Compromised controller | **High residual** | Correctly acknowledged: helper marker cannot prevent a valid controller request for an owned resource. No formal risk acceptance or host-isolation criteria. | Generic only (F-09). |
| T-12 | Malicious/compromised helper client | **Conditional** | Fixed enum/schema and allowlist are correct; socket permissions (**F-01**) and controller compromise (T-11) delimit the control. | Generic only (F-09). |
| T-13 | Privilege escalation via helper/`CAP_NET_ADMIN` | **High residual** | Correctly recognized as serious; exact minimal capability and seccomp/MAC proof are open; formal acceptance missing. | Generic only (F-09). |
| T-14 | Concurrent policy operations | **Conditional** | Single active controller, CAS, and per-ownership serialization are the right controls; lease and helper serialization details are not frozen. | Generic only (F-09). |
| T-15 | Partial installation | **Conditional** | Per-family state and no `ACTIVE` without parity are correct; cross-family atomicity is explicitly open. | Generic only (F-09). |
| T-16 | Partial revocation | **Conditional** | Absence evidence and no `REVOKED` until all families are absent are correct; crash semantics need tests. | Generic only (F-09). |
| T-17 | Helper crash | **Conditional** | Controller treats lost response as uncertain and reconciles; helper idempotency/durability and restart behavior need exact contract. | Generic only (F-09). |
| T-18 | Controller crash | **Conditional** | Intent-before-side-effect and startup scan are correct; full-scan state coverage and schema/version handling remain open (RR-05). | Generic only (F-09). |
| T-19 | DB corruption/tampering | **Conditional** | Separate DBs, WAL, integrity checks, and evidence gating are good; digest `CHECK` remains open (RR-06); malicious controller/root can tamper. | Generic only (F-09). |
| T-20 | Host restart | **Conditional** | Boot ordering, baseline, and reconciliation are designed; pre-reconciliation exposure window and actual systemd dependencies are open. | Generic only (F-09). |
| T-21 | IPv4/IPv6 inconsistency | **Conditional** | Parity design is correct; IPv6-disabled/one-family policy is open; host traffic tests missing. | Generic only (F-09). |
| T-22 | Docker firewall interaction | **Conditional** | Separate table, no Docker flush, DOCKER-USER fallback, and drift detection are correct; Docker API trust gap (**F-02**) and hook priority remain. | Generic only (F-09). |
| T-23 | Arbitrary rule/expression injection | **Conditional** | Fixed enum/typed data/no shell are correct; current helper allows `any`/`icmp`/port 0 while target is stricter; version transition is undefined (**F-13**). | Generic only (F-09). |
| T-24 | Audit tampering/suppression | **Conditional** | Independent helper/controller audit and sanitization are designed; evidence immutability and retention are not enforced (**F-11**); no audit-durability test. | Generic only (F-09). |

### 9.3 Register quality

- The 24 entries cover the requested classes and are not merely duplicated. T-10/T-11/T-12 are distinct
  (broker, controller, helper client), although their boundaries overlap.
- The "current mock limitation" column is valuable and correctly prevents crediting target controls to
  the mock.
- The register is weaker on **capability and bypass threats outside the controller/helper RPC**: Docker
  API authority, FD passing, supply-chain/update compromise, and audit/disk exhaustion.
- The register lacks per-threat test IDs, so it cannot by itself prove coverage. This is **F-09**.

### 9.4 Missing threats to add before implementation

1. **T-25 — Connected-descriptor passing/inheritance.** An allowed-UID process passes a connected
   client socket to another process; `SO_PEERCRED` still reflects the original connector. Control:
   disallow `SCM_RIGHTS` on client sockets, set `FD_CLOEXEC`, close inherited descriptors, and treat
   allowed-UID compromise as T-11/T-12.
2. **T-26 — Supply-chain/update compromise of the privileged helper or its backend library.** A
   compromised package, dynamic loader path, config, or helper binary bypasses all contract controls.
   Control: signed/pinned packages, immutable image/root-owned binary, no writable code, verified
   startup, and rollback.
3. **T-27 — Docker daemon/API compromise or over-broad broker Docker access.** A broker or Docker
   daemon with root-equivalent control bypasses the controller/helper. Control: narrow Docker API
   proxy, no privileged/host-mount operations for the broker, or explicit acceptance of host-root
   equivalence.
4. **T-28 — Audit/log/disk exhaustion or audit-sink failure.** A full disk or broken audit sink could
   suppress accountability or block durable recovery. Control: bounded audit queue, separate disk
   budget, fail-closed mutation policy when required evidence cannot be stored, and alerting.

The first three are significant enough that they should be added before the next architecture approval.
They are not inventing evidence; they are gaps in the current register.

---

## 10. RR-01 through RR-07 verification

### 10.1 Status

All seven residuals remain **open**. The 2H documents correctly say they are carried forward and not
closed by the architecture. The 3.11 local PASS did not close them.

| Residual | 2H status | Independent assessment | Classification | Remains open? |
|---|---|---|---|---|
| RR-01 — `request_id` canonical validation | Open — carried | Current `_validate_request` coerces `request_id` to `str`; the canonical identifier gate does not cover it; real transport/schema validation is not defined. | Mock remediation + real-transport requirement. | **Yes.** |
| RR-02 — `operation_id` canonical validation/uniqueness | Open — carried | Current contract does not enforce uniqueness or operation binding in the database; target schema/evidence binding is not specified. | Mock remediation + real transport + database design. | **Yes.** |
| RR-03 — `idempotency_key` canonical validation/scope | Open — carried | Current PK is `(idempotency_key, operation_type)`; 2H.2 says per-operation uniqueness while 2H.4 says same key + different operation conflicts. | Mock remediation + real transport + database design. | **Yes.** |
| RR-04 — `policy_version` range/type | Open — carried | Current `_validate_request` accepts bool as `int`; SQLite overflow is reachable; helper contract accepts bool; target `CHECK`/rejection is proposed but not implemented. | Mock remediation + real transport + database migration. | **Yes.** |
| RR-05 — full-scan reconciliation | Open — carried | Current reconciliation scans all `list_ownerships()` rows and `PENDING` idempotency, but lacks target per-family/uncertain/partial state coverage; current behavior is not target proof. | Controller design + recovery + host validation. | **Yes.** |
| RR-06 — I-3.9-01 missing digest DB `CHECK` | Open — carried | Direct `ControllerOwnershipStore` calls still accept malformed digest values; no migration/CHECK exists. | Database design + mock validation. | **Yes.** |
| RR-07 — I-3.9-03 retained exception context | Open — carried | R-01 path keeps raw `BrokerDBError` in `__context__`; normal traceback formatting suppresses it, but a future error mapper/log formatter must not serialize it. | Real transport + error/logging + deployment requirement. | **Yes.** |

### 10.2 Additional residuals not represented by RR-01..RR-07

The 3.11 review identifies residuals outside the seven 2H identifiers. The 2H register does not
explicitly map all of them. This is a tracking gap (**F-08**):

| Residual | Evidence | Classification | Required disposition |
|---|---|---|---|
| I-07 — broader identifier/field scope | 3.11 §5.2 says `request_id`, `operation_id`, `idempotency_key`, ownership-reference fields, and broader legacy-validator breadth were excluded from the canonical gate. | Mock remediation + real transport + further investigation. | Add an explicit residual ID or state its scope inside RR-01/02/03; do not imply universal validation. |
| I-08 — raw `BrokerDBError` on non-failure paths | 3.11 §8 says several persistence paths still re-raise raw errors containing SQLite text/paths. | Mock remediation + real transport + deployment/logging. | Add a residual and a sanitized error-mapper requirement; RR-07 covers exception context, not this path. |
| I-09 — `strict_auth=False` legacy footgun | 3.11 §9 says the legacy mock provider remains a footgun; no reviewed caller uses it. | Mock remediation + deployment. | Remove it from the live path or add a deployment/transport assertion that `strict_auth` is always true. |

I-3.9-02 is closed as a documentation/test-isolation correction and is not an open residual. F-3.9-01 and
F-3.9-02 are closed; R-01/R-03 are verified closed; R-02 is verified closed for the 3.10 canonical field
scope; F-01–F-09 are preserved. Those prior decisions are not changed by this review, but they do not
close RR-01..RR-07 or I-07/I-08/I-09.

### 10.3 Closure rules

The 2H closure rules are correct: a residual closes only with tests and review, not prose. A mock fix
does not close a real-transport requirement, and a DB `CHECK` does not close application validation.
The 3.11 PASS remains scoped to the local mock.

RR-01..RR-07 must remain explicitly open in the next design revision. No status may be changed to
"resolved" merely because this review or the 2H design describes a future control.

---

## 11. Legacy mock residual assessment

This section assesses the earlier mock-controller limitations requested in the review brief and the
additional 3.11 residuals.

| Item | Current evidence/behavior | Classification | Status | Target requirement |
|---|---|---|---|---|
| `request_id` validation | `broker/app/firewall_controller_contract.py` coerces `request_id` to `str`; `controller_service._validate_caller_identifiers` covers `policy_id`/`instance_id`/`network_id`, not `request_id`. | Mock remediation required; real-transport design requirement. | **Open — RR-01.** | Canonical type/length/character validation before any store/idempotency use; same at broker/controller/helper. |
| `operation_id` validation | Same coercion; no uniqueness or operation-binding constraint in SQLite; helper validates only generic ID format. | Mock remediation required; real-transport and database design requirement. | **Open — RR-02.** | Canonical validation, operation/digest binding, duplicate detection, bounded audit retention. |
| `idempotency_key` validation | Coerced to `str`; primary key `(idempotency_key, operation_type)`; same key can be reused for another operation; target docs disagree on global vs per-operation scope. | Mock remediation required; real-transport and database design requirement. | **Open — RR-03.** | Decide scope, enforce uniqueness/conflict, bind request digest and ownership, preserve safe replay semantics. |
| Non-SQLite-range / wrong-type `policy_version` | Legacy validator checks only `isinstance(int)`; `True` is accepted as `1`; large integers can reach SQLite and overflow; helper contract also accepts bool. | Mock remediation required; real-transport and database migration requirement. | **Open — RR-04.** | Reject bool/float/string/out-of-range; enforce signed 64-bit non-negative range in app and DB. |
| Full-scan reconciliation limitations | Current `reconcile_pending_operations` can enumerate `list_ownerships()` and `get_pending_idempotency()`; target per-family/partial/uncertain state model does not exist; the default validator makes full-scan reachable only with a permissive validator. | Controller design/recovery requirement. | **Open — RR-05.** | Scan all owned/non-terminal/uncertain/legacy records; define policy-specific vs full-scan contract; test all states. |
| Database digest `CHECK` | Direct store calls accept `''`, short, non-hex, and 64-character non-hex digests; no `CHECK` exists. | Database design/migration requirement. | **Open — RR-06 / I-3.9-01.** | Validate legacy rows, add canonical 64-hex `CHECK`, retain app/helper validation, fail closed on invalid reads. |
| Python exception-context retention | R-01 path retains raw `BrokerDBError` in `__context__`; suppression works for normal formatting, but there is no transport/logging guarantee. Other paths still raise raw `BrokerDBError` (I-08). | Real-transport/deployment/investigation requirement. | **Open — RR-07 / I-3.9-03.** | Sanitized error mapper; never serialize `__context__`/`__cause__`, SQL, paths, or tracebacks; test all error paths. |
| I-07 broader field scope | 3.11 says ownership-reference fields and broader legacy-validator breadth remain outside the canonical gate. | Mock remediation + real transport + further investigation. | **Open — not explicitly in RR-01..07.** | Add tracking and tests; do not describe validation as universal. |
| I-08 raw `BrokerDBError` paths | Non-failure persistence paths can propagate raw SQLite messages/paths. | Mock remediation + real transport + deployment/logging. | **Open — not explicitly in RR-01..07.** | Add sanitized error boundary and tests. |
| I-09 `strict_auth=False` | Legacy mock provider can disable strict authorization; no reviewed caller uses it. | Mock remediation + deployment. | **Open — not explicitly in RR-01..07.** | Remove from live path or fail deployment if enabled. |

### 11.1 What the mock evidence does and does not show

The 3.11 mock review supports:

- the strict controller path rejects invalid canonical policy/instance/network identifiers;
- uncertain revoke outcomes are recovered by read-back rather than blindly replayed;
- terminal `REVOKED` requires matching evidence;
- verification evidence is stored before `ACTIVE`;
- SQLite CAS/idempotency behavior works in the mock;
- no live transport or helper exists.

It does not show:

- kernel identity;
- real UDS permissions;
- real nftables/iptables behavior;
- multi-family atomicity;
- Docker compatibility;
- privileged helper hardening;
- production deployment safety;
- closure of RR-01..RR-07 or I-07/I-08/I-09.

### 11.2 Current scaffold warnings

The current `broker/app/uds.py` and `broker/app/auth.py` are particularly unsafe to reuse as a target
basis:

- `setup_unix_socket` unconditionally removes an existing path and does not validate owner/group/mode
  or symlink status;
- broker auth merges caller-supplied peer headers over real peer credentials;
- broker auth treats an empty token as valid;
- the manager broker client is a stub that raises "transport not initialized";
- the helper contract schema/operation names/protocol allowlist are not the target contract.

These are current-state limitations, not target design claims. They must not be silently promoted into
the real architecture.

---

## 12. Cross-document consistency matrix

### 12.1 Matrix

| Area | 2H.1 | 2H.2 | 2H.3 | 2H.4 | 2H.5 | Result |
|---|---|---|---|---|---|---|
| Component names/roles | Manager, broker, controller, helper | Same | Same | Same | Same | **Consistent.** |
| Trust boundaries | TB table | TB-0..TB-4 | Helper boundary | Deployment boundary | TB-0..TB-4 | **Consistent labels; manager-broker content open.** |
| UID/GID identity | Names, primary GID, PID audit-only | Same | Dedicated users/groups | Same | Same | **Consistent intent; numeric IDs/config undefined (F-12).** |
| Socket directory permissions | Root:server `0750`; socket server:client `0660` | `0660` in root `0750` | Helper runtime dir service-owned `0750` | Root:server `0750` | References 2H.1 | **Conflict/defect (F-01).** |
| Socket lifecycle | Reject existing unsafe path; systemd preferred | Target control | Hardening | systemd layout | Test requirement | **Target consistent; current scaffold contradicts (F-07).** |
| Operation names | `REMOVE_STALE_POLICY`, `RECONCILE_PENDING_OPERATIONS` | Same class | Remove owned/stale | Reconcile | Same as 2H.1 | **Target consistent; current helper uses `REMOVE_OWNED_POLICY`/`RECONCILE_OWNED_POLICY` (F-05).** |
| Request/response schema | Nested `policy`, `deadline_ms` | Not repeated | Typed data | No wire schema | Summary only | **Incomplete and current/target mismatch (F-05).** |
| Timeout field | `deadline_ms` | Not repeated | Bounded deadlines | Not repeated | Generic | **`deadline_ms` vs current `timeout_ms` conflict (F-05).** |
| Error codes | Illustrative `error_code` | Bounded/sanitized | `UNCERTAIN`/`BACKEND_READBACK_FAILED` | Sanitized errors | No registry | **No frozen error-code registry (F-05).** |
| Lifecycle states | Evidence-gated terminal | T-15/T-16 | Failure table | Partial states diagram | No partial state list | **Target mostly consistent; partial state representation open (2H.4 §9.4).** |
| Backend ownership | Helper verifies marker | Ownership substitution | Per-ownership chains/markers | Controller authority | Same | **Consistent; marker is not authorization (T-11).** |
| Recovery responsibility | Controller read-back | Crash paths | Failure semantics | Crash matrix/full scan | Test/fault injection | **Consistent.** |
| Persistence semantics | Controller DB authority | DB corruption | Evidence | Schema/per-family | Summary | **Consistent except idempotency key scope (F-06).** |
| Privilege assignment | Helper only `CAP_NET_ADMIN` | Same | Same | Same | Same | **Consistent.** |
| Deployment model | Ubuntu target | Host assumptions | systemd helper | Ubuntu LTS/systemd | Roadmap | **Consistent; manager-broker UDS lacks a roadmap phase (F-04).** |
| Testing requirements | Negative tests | Threat classes | Hardening tests | Readiness checklist | Layered test plan | **Broadly consistent; no per-threat test mapping (F-09).** |
| Residual IDs | RR-01..RR-07 | RR-01..RR-07 | References | RR-01..RR-07 | RR-01..RR-07 | **Consistent, but I-07/I-08/I-09 omitted (F-08).** |
| Open decisions | 12 listed | 8 listed | 12 listed | 10 listed | 15 consolidated | **Mostly consistent; 2H.4 assumes a manager-broker UDS layout while 2H.1/2H.5 leave the edge open.** |
| Schema version | `2L.2H.1` | Not repeated | Backend version open | Migration version open | No migration | **Current helper is `2L.2G.3`; no transition plan (F-05/F-13).** |
| Ownership reference fields | `ownership_reference` | Ownership substitution | Marker/reference | `ownership_record_id` | Summary | **Both names used; no rule for conflicting values (F-05).** |
| Current vs target distinction | Explicit | Explicit | Explicit | Explicit | Explicit | **Strong and consistent.** |
| Mock does not prove live security | Explicit | Explicit | Explicit | Explicit | Explicit | **Strong and consistent.** |

### 12.2 Consistency conclusion

The documents are mostly coherent in terminology, trust direction, privilege assignment, recovery
semantics, and current/target separation. They are **not** internally consistent in four areas that
matter for implementation:

1. socket directory ownership/permissions;
2. manager-broker transport and its roadmap coverage;
3. wire schema/operation/version/timeout/error contract;
4. idempotency key scope.

They also omit explicit residual IDs for I-07/I-08/I-09 and lack per-threat test traceability. These are
fixable documentation/design defects, not reasons to abandon the architecture.

---

## 13. Implementation-readiness assessment

### 13.1 Readiness by area

| Area | Ready to implement? | Blocker/gap |
|---|---|---|
| Component boundaries and privilege model | Mostly | Broker Docker authority (F-02); exact helper hardening open. |
| UDS transport | No | Socket permissions (F-01), identity adapter (F-03), lifecycle implementation (F-07). |
| Kernel peer authentication | Partially | `SO_PEERCRED` concept is correct; numeric allowlists, adapter, activation semantics, FD passing unresolved. |
| Wire protocol | No | No frozen schema, error registry, operation names, timeout field, or schema/version migration (F-05). |
| Manager-to-broker edge | No | UDS vs HTTP unresolved; HTTP fallback unsafe as currently coded (F-04). |
| Helper contract | Partially | Fixed enum/typed data is good; target names/version/allowlists differ from current; implementation/hardening open. |
| Firewall backend | Partially | nftables design is sound; hook priority, atomicity, Docker coexistence, and host validation open (F-14). |
| Persistence schema/migration | Partially | Per-family/evidence design is sound; DDL, invariants, evidence immutability, and migration recipe are incomplete (F-11). |
| Recovery/reconciliation | Partially | Crash semantics are strong; full-scan target state coverage and tests are open (RR-05). |
| Deployment/operations | Partially | Dedicated users/services proposed; numeric IDs, units, boot baseline, audit retention, rollback drill open. |
| Threat model | Partially | 24 threats covered; Docker API, FD passing, supply chain, per-threat tests missing (F-09/F-10). |
| Residuals | No closure | RR-01..RR-07 and I-07/I-08/I-09 remain open. |

### 13.2 Blocking decisions before implementation

The following must be resolved before any real transport/helper phase:

1. **Socket permission model** for all three UDS edges, including numeric UIDs/GIDs, directory owner,
   directory mode, socket mode, socket activation versus direct bind, and exact startup `stat` checks.
2. **Broker Docker authority** — narrow API proxy, fixed operation allowlist, or explicit accepted risk
   that broker compromise is host-root equivalent.
3. **Controller identity adapter** — out-of-band `PeerIdentity`, request-field stripping, authorization
   signature change, and idempotency digest binding.
4. **Manager-broker transport decision** — UDS with peer identity or loopback HTTP with a mandatory
   token and removal of test peer headers; include the edge in the roadmap if UDS is selected.
5. **Frozen wire contract** — request/response schema, operation names, schema version, timeout field,
   error-code registry, canonical JSON, duplicate-key policy, and current/target compatibility mapping.
6. **Idempotency key scope** — global versus per-operation, with schema enforcement and tests.
7. **Residual disposition** — explicit open tracking for I-07/I-08/I-09 and acceptance/closure plans.

### 13.3 Non-blocking recommendations

These can be resolved during later design/host-validation phases, but must not be silently assumed:

- evidence signing/HMAC and key management;
- HA/multi-controller leadership;
- audit retention and remote append-only destination;
- boot-time baseline and pre-reconciliation exposure window;
- exact nftables hook priority/table layout;
- exact seccomp/AppArmor/SELinux profile;
- helper native binary versus interpreter;
- split read-only inspect helper;
- migration down/rollback policy;
- IPv6-disabled host policy and explicit one-family approval.

### 13.4 Required Linux test environment

The roadmap correctly identifies a disposable Linux lab. A credible implementation gate needs:

- Ubuntu LTS VMs with pinned kernel, nftables, iptables fallback, Docker, and systemd versions;
- dedicated test users/groups for manager, broker, controller, and helper, with distinct numeric IDs;
- a systemd socket-activation test and a direct-bind test;
- network namespaces and packet generation for IPv4/IPv6 traffic tests;
- Docker/network lifecycle fixtures, including restart/upgrade and DOCKER-USER ordering;
- crash/fault injection at each helper/controller boundary;
- SQLite backup/restore, corruption, disk-full, and lock tests;
- an independent audit-log destination and evidence-integrity checks;
- a clean-snapshot rollback process and no production credentials/sockets/firewall access.

### 13.5 Feasibility conclusion

The architecture is implementable on the intended Linux environment, but the 2H documents are not yet a
sufficient implementation contract for real transport. They are sufficient to support a focused design
remediation phase. They are not sufficient to start UDS/`SO_PEERCRED`, privileged-helper, or firewall
implementation safely.

---

## 14. Findings with evidence and remediation

### 14.1 Finding summary

| ID | Severity | Finding | Evidence | Required remediation | Blocks |
|---|---|---|---|---|---|
| F-01 | **High** | Socket directory permissions cannot support the documented UDS edges. | 2H.1 §5.1 (root:server `0750`; client in different group); 2H.4 §6.3; 2H.3 §5.4 says service-owned helper dir. A client needs directory execute; a direct-bind server needs directory write. | Choose direct-bind (`server:client 0750`, socket `server:client 0660`) or activation (`root:client 0750/0751` + systemd); use numeric IDs; add startup owner/mode checks and cross-UID tests. | Real UDS. |
| F-02 | **High** | Broker Docker authority can bypass the controller/helper and host-firewall restriction claim. | 2H.1 §3.2 B says broker may access needed Docker operations; 2H.2 T-10 covers only broker->controller; no Docker API proxy/allowlist; current adapter uses a Docker client. | Define a narrow Docker API proxy/fixed operations with no privileged-container/host-mount/network-admin capability, or explicitly accept host-root-equivalent broker compromise and revise claims/threat model. | Trust boundary / helper phase. |
| F-03 | **High** | Target controller identity adapter is undefined; current service reads request `peer_uid`/`peer_gid` and includes them in the digest. | `authorization_strict.py:25-31`; `controller_service.py:632-638` and `_DIGEST_FIELDS` at `139-145`; `mock_transport.py:11-18`; 2H.1 lines 86-88, 260-262, 322-330. | Add out-of-band `PeerIdentity` from the accepted UDS; forbid/strip identity fields in request schema; change auth signature; define digest binding to kernel identity; test spoofed JSON + real credentials. | Real UDS. |
| F-04 | **High** | Manager-broker boundary is unresolved; current HTTP auth is unsafe if retained. | 2H.1 §4.1/§7; 2H.5 §7; current `broker/app/auth.py:28-33` merges headers over real peer; `authorization.py:43-45` accepts empty token; `BrokerSettings` defaults; `manager/app/broker_client.py` is a stub. | Resolve UDS vs HTTP; if HTTP, mandatory non-empty token, loopback bind, remove test headers, fail closed on missing token; if UDS, add a real manager-broker phase/tests. | Manager-broker edge. |
| F-05 | **High** | Wire protocol/operation contract is not frozen and conflicts with current contracts. | 2H.1 §4.2/§5.6 (nested `policy`, `deadline_ms`); current flat `ControllerRequest`; helper `timeout_ms`; helper names `REMOVE_OWNED_POLICY`/`RECONCILE_OWNED_POLICY`; helper schema `2L.2G.3`; no error-code registry. | Freeze a field-level JSON schema/IDL, exact operation names, timeout field, schema/version migration, error registry, canonical JSON/duplicate-key rules, and compatibility mapping to the mock contract. | Real transport. |
| F-06 | **Medium** | Idempotency key scope contradicts across documents and schema. | 2H.2 RR-03 says per-operation uniqueness; 2H.4 §3.1 says same key + different operation is a conflict; current PK `(idempotency_key, operation_type)`. | Decide global or per-operation scope; enforce by PK/unique constraints; update replay/conflict rules and tests. | 2H.1/2H.2 persistence. |
| F-07 | **Medium** | Target UDS lifecycle is not matched by current scaffold, and the target lacks an implementation contract. | 2H.1 §5.2 target rules; `broker/app/uds.py:55-65` unconditionally unlinks, no owner/mode/symlink checks; current path `/run/flaghunt/broker.sock` differs from 2H.4. | Do not reuse `uds.py` unchanged; implement target lifecycle (temp path/atomic install, `lstat`, owner/mode, no symlink, safe cleanup); add path migration. | 2H.3. |
| F-08 | **Medium** | 2H residual register omits I-07, I-08, and I-09. | 3.11 §5.2, §8, §9; 2H.2 RR-07 only covers I-3.9-03; no I-08 raw-error or I-09 `strict_auth=False` tracking. | Add explicit residual IDs/dispositions and update all five docs and acceptance gates; do not imply universal validation. | Residual acceptance. |
| F-09 | **Medium** | No per-threat validation test mapping. | 2H.2 §4 has no validation-test column; 2H.5 §4.2 has generic categories; 24 threats lack test IDs. | Add a `Validation test` column with test IDs/gates for T-01..T-24, including negative cases and fault injection; map missing threats T-25..T-28. | Threat acceptance. |
| F-10 | **Medium** | Threat register misses FD passing, supply-chain, Docker daemon, and audit/disk exhaustion. | 2H.2 §4; 2H.1 §5.2 mentions `FD_CLOEXEC` but no threat; Docker API not in T-10; no supply-chain threat. | Add T-25..T-28 and controls/tests; require close-on-exec/no `SCM_RIGHTS` on client sockets. | Threat model. |
| F-11 | **Medium** | Evidence immutability and aggregate lifecycle invariants are prose only. | 2H.4 §2.2/§2.5 says append-only and aggregate rules; schema has no trigger/FK/transaction; current evidence table allows updates/deletes. | Add append-only enforcement, FKs, transaction/trigger/CAS for family + aggregate invariants, and tests for inconsistent rows. | Persistence. |
| F-12 | **Medium** | Numeric UID/GID and allowlist/config contract undefined; helper config group unspecified. | 2H.1 §5.3 says root-owned allowlists; 2H.4 §6.2/§6.3 uses names; 2H.3 §5.4 says config `0640` but no group; current broker defaults empty/-1. | Define numeric IDs, config path/format/owner/group/mode, startup validation, fail-closed empty allowlist, and deployment checks. | UDS/deployment. |
| F-13 | **Medium** | Current helper contract is broader/differently versioned than the target rule/operation contract. | `helper_contract.py`: `ALLOWED_PROTOCOLS` includes `any`/ICMP, port 0 allowed, `SCHEMA_VERSION = "2L.2G.3"`; target says bounded TCP/UDP and `2L.2H.1`. | Define intentional tightening and version transition; update tests/fixtures; do not assume current mock acceptance proves target validation. | Helper phase. |
| F-14 | **Medium / host gate** | Exact nftables hook priority, cross-family atomicity, Docker ordering, seccomp/MAC, and boot baseline remain unvalidated. | 2H.3 §2.1/§3.1/§5.3/§8; 2H.4 §6.5; 2H.5 §6.3. | Resolve in the disposable host lab; no live approval until traffic, drift, reboot, rollback, and capability tests pass. | Live gate. |

### 14.2 No Critical finding

I did not find a design defect that makes the architecture fundamentally unsafe or unsuitable. The
intended chain has a coherent least-privilege direction, and the remaining problems are in contracts,
permissions, and trust-boundary completeness. A redesign is not required; a focused remediation and
re-review are.

### 14.3 Gate blockers and residual acceptance

The following are not optional "later" items:

- **G-01:** Correct the socket directory/permission model and all three UDS edges.
- **G-02:** Bound or explicitly accept the broker Docker authority.
- **G-03:** Define the kernel-identity adapter and request-field stripping.
- **G-04:** Resolve manager-broker transport and make the HTTP fallback fail closed.
- **G-05:** Freeze the wire/operation/error/version contract.
- **G-06:** Formalize RR-01..RR-07 plus I-07/I-08/I-09 and add per-threat tests.
- **G-07:** Obtain explicit risk acceptance for T-11 and T-13, with defined host isolation/monitoring
  criteria; the 2H.0 gate currently requires this but no acceptance record exists.

T-11 and T-13 are correctly identified as High residual risks, not solvable by the current design alone.
The architecture can proceed only if the residual is explicitly accepted and bounded. It cannot claim
that controller compromise or `CAP_NET_ADMIN` helper compromise is harmless.

---

## 15. Recommended next phase

### 15.1 Recommendation

Do **not** proceed to 2H.1..2H.10 implementation under the current documents. Recommend a design-only
phase:

**2L.2I.2 — Architecture Remediation and Contract Freeze**

Its scope should be documentation/design only, with no UDS/helper/firewall implementation:

1. Correct the three UDS directory/socket ownership and mode models; choose direct bind or systemd
   activation per edge; define numeric IDs and startup checks.
2. Define the controller's out-of-band `PeerIdentity` contract, request-field rejection, authorization
   signature, and idempotency digest binding.
3. Resolve the manager-broker edge and remove or hard-disable the current test-header/empty-token path;
   add the edge to the roadmap if UDS is selected.
4. Bound broker Docker access through a narrow API proxy or explicitly revise the trust model and accept
   host-root-equivalent broker compromise.
5. Freeze the wire schema, operation names, schema version, timeout field, error-code registry,
   canonical JSON rules, and compatibility mapping to the current mock contract.
6. Resolve idempotency key scope and evidence/aggregate invariants.
7. Add explicit residual tracking for I-07/I-08/I-09 and per-threat validation tests, including missing
   threats T-25..T-28.
8. Record explicit risk acceptance for T-11/T-13 with host isolation/monitoring criteria.
9. Re-run an independent design review after the remediation.

Only after that remediation and re-review should the project consider the 2H.0 approval gate. The 2H.1
mock-layer validation and later phases remain separately unauthorized.

### 15.2 What could remain non-blocking

The following may stay open until their relevant phase if they are explicitly accepted and tracked:

- HA/multi-controller design;
- evidence signing/HMAC;
- audit retention/remote destination;
- exact boot baseline and pre-reconciliation window;
- helper native binary versus interpreter;
- split inspect helper;
- exact seccomp/MAC profile;
- migration rollback/downgrade policy;
- precise Ubuntu/kernel/nftables/Docker version pins (but they must be pinned before host validation).

### 15.3 What must not start

- real UDS or `SO_PEERCRED` implementation;
- privileged helper implementation or capability grants;
- nftables/iptables mutation;
- Docker firewall integration changes;
- systemd service deployment;
- live pilot or production;
- any action based on the current mock/3.11 PASS.

---

## 16. Explicit authorization boundary

This phase was read-only. I created only this review document. I did not:

- modify application source, tests, configuration, migrations, or dependencies;
- implement UDS, `SO_PEERCRED`, a privileged helper, or any backend;
- use sudo or grant Linux capabilities;
- execute nftables/iptables or modify Docker networking/firewall configuration;
- start or stop services;
- change host, cloud, or production state;
- open the live firewall gate.

The 3.11 local mock PASS, the 2H DESIGN COMPLETE status, and this CONDITIONAL review do **not** authorize
real transport, privileged helper work, firewall changes, deployment, or production use. Any future
implementation requires a separate explicit approval after the blockers above are resolved and
re-reviewed.

**CONDITIONAL — Specific blockers must be resolved.**

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
