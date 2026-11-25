# Phase 2L.2I.3 — Complete Independent Follow-up Architecture Security Review

**Review date:** 14 November 2026

**Review mode:** Read-only documentation and code inspection.

**Scope:** Flaghunt firewall-controller architecture after Phase 2L.2I.2.

**Live firewall gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

## Objective

Perform one comprehensive, independent, read-only architecture and security review of the Flaghunt
firewall-controller architecture following Phase 2L.2I.2, verify whether the previously identified
architectural findings were actually remediated, identify remaining risks, assess cross-document
consistency, and determine whether the project may begin planning controlled host-validation
activities.

### Executive summary

The Phase 2L.2I.2 work is a real design-remediation effort. It materially improves the target
architecture: it selects direct-bind UDS, removes HTTP from the target manager path, introduces an
immutable kernel-identity model, separates Docker access behind a restricted runtime adapter, and
freezes a protocol envelope and operation set. The prior five High and nine Medium findings were
preserved and individually mapped. No original finding disappeared.

The remediation is nevertheless not a complete or internally consistent architecture result, and it
does not close the security findings:

- **H-01 remains open.** The target socket directory/socket ownership values are coherent, but the
  mechanism that makes a server-created socket belong to the client group is unspecified on every
  UDS edge. The current `uds.py` accepts `uid`/`gid` arguments and never uses them. This is new
  finding **N-01**.
- **H-05 remains open.** The "frozen" rule schema in 2H.1 rejects ICMP and has no direction, state,
  or DNS fields, while 2H.3 requires those semantics and permits optional ICMP. The compiled object
  has no frozen schema. This is new finding **N-02**, a High-severity design contradiction.
- **H-02, H-03, and H-04 are only partially resolved.** The target designs are substantially better,
  but current code still contains a broker Docker adapter, a manager Docker adapter, request-field
  controller identity, HTTP header identity, and a manager broker client stub. Target controls do
  not exist in executable form.
- **M-03 is only partially resolved.** I-07, I-08, and I-09 are present in 2H.2 and 2H.5, but absent
  from 2H.1, 2H.3, and 2H.4. The 2I.2 cross-document matrix claims those documents' residual
  sections contain the items. They do not. This is new finding **N-03**.
- **T-27 remains open and unaccepted.** The broker has no target Docker authority, but current code
  and tests still contain Docker adapters in broker and manager. The runtime adapter is documented
  but unimplemented. Rootful Docker host-root equivalence is not accepted.
- **T-11 and T-13 remain open and unaccepted.** The threat model identifies the risks and possible
  controls, but no named acceptance authority, acceptance criteria, acceptance record, or host
  isolation/monitoring evidence exists.
- **RR-01 through RR-07 and I-07 through I-09 all remain open.** No owner is assigned to any of
  them, despite 2H.5 requiring owners and plans.
- **No real transport, socket, `SO_PEERCRED`, helper, Docker, firewall, systemd, or host test was
  run.** Existing tests are in-process/mock tests; several are placeholder or exception-swallowing
  tests. They are not evidence that the target controls work.

### Decision snapshot

| Question | Decision | Reason |
|---|---|---|
| Is the firewall-controller architecture documentation complete, consistent, and safe enough to proceed? | **CONDITIONAL** | Direction is sound, but N-01, N-02, and N-03 are open; T-27, T-11, and T-13 are unaccepted; target controls are unimplemented and untested. |
| May controlled host-validation planning begin? | **CONDITIONALLY READY** | Planning may begin only after N-01/N-02 are closed, the new design gaps are reviewed, T-27/T-11/T-13 are formally accepted or removed, and I-07–I-09 are propagated with owners. No host operation is authorized. If those conditions are not met, the correct status is **NOT READY**. |
| Is live firewall integration authorized? | **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED** | Unchanged. This review cannot open the live gate. |

### Finding and residual counts

| Measure | Closed | Open | Partially resolved | Total |
|---|---:|---:|---:|---:|
| High findings (H-01 to H-05) | 0 | 2 | 3 | 5 |
| Medium findings (M-01 to M-09) | 2 (documentation-only) | 1 | 6 | 9 |
| New findings (N-01 to N-04) | 0 | 4 | 0 | 4 |

The two Medium closures are **documentation/traceability closures only**: M-04's per-threat test
mapping now exists, and M-05's missing threat entries now exist. They do not close the underlying
controls or tests. M-09 remains the host-validation gate.

### Previous review decisions

| Decision source | Decision at the start of this review | Treatment in this review |
|---|---|---|
| Phase 2L.2I.1 independent review | **CONDITIONAL — Specific blockers must be resolved.** | Preserved as the baseline; not automatically superseded. |
| Phase 2L.2I.2 targeted remediation | **CONDITIONAL — Targeted design remediation is complete; implementation remains blocked by open residual acceptance and unexecuted host tests.** | Reassessed independently; its "design complete" claim is accepted only in part. |
| Phase 2L.2H design phase | **DESIGN COMPLETE — REAL FIREWALL IMPLEMENTATION NOT AUTHORIZED** | Preserved; this review does not authorize implementation. |
| Live firewall gate | **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED** | Unchanged. |

## 1. Strict Scope and Safety Restrictions

This review was performed as documentation and code inspection only. No source code, application
test, runtime configuration, environment file, migration, socket, UDS transport, `SO_PEERCRED`
integration, privileged helper, Linux capability, Docker configuration, firewall rule, systemd unit,
host setting, cloud resource, or production system was changed or executed.

Specifically, this review did not:

- create or modify application source code or tests;
- create or apply database migrations;
- install dependencies or packages;
- create sockets, bind a UDS, mount a socket, or pass descriptors;
- call `SO_PEERCRED` or implement kernel identity verification;
- implement or start a privileged helper;
- invoke `sudo`, change capabilities, or change service users/groups;
- execute Docker operations, change Docker permissions, or inspect live containers;
- execute `nftables`, `iptables`, Docker `DOCKER-USER`, or any firewall operation;
- start, stop, enable, disable, or modify systemd services;
- run host, integration, soak, fault-injection, or destructive tests;
- change host, cloud, or production state;
- open the live firewall gate.

The one permitted repository change is the creation of this review document. Repository-change
verification is reported in Section 15. The existing working tree already contained unrelated
modified and untracked files before this review; those were not reverted or attributed to this
phase.

## 2. Required Input Documents

### 2.1 Documents read in full

The following required documents were read completely at their current repository state. Line counts
are the counts observed during this review.

| Document | Lines | Role in this review |
|---|---:|---|
| `docs/PHASE_2L_2I_1_INDEPENDENT_ARCHITECTURE_SECURITY_REVIEW.md` | 1,065 | Original F-01–F-14 findings, five High and nine Medium findings, and prior CONDITIONAL decision. |
| `docs/PHASE_2L_2I_2_TARGETED_ARCHITECTURE_BLOCKER_REMEDIATION.md` | 984 | Claimed 2I.2 remediation, H/M dispositions, RR/I registers, 17-section mapping, and cross-document consistency claims. |
| `docs/PHASE_2L_2H_1_REAL_TRANSPORT_TARGET_ARCHITECTURE.md` | 851 | Transport, UDS, identity, protocol, operation contract, management edge, consistency rules, live gate. |
| `docs/PHASE_2L_2H_2_THREAT_MODEL_AND_TRUST_BOUNDARIES.md` | 399 | T-01–T-28, test mapping, residual registers, T-11/T-13/T-27, legacy residuals. |
| `docs/PHASE_2L_2H_3_FIREWALL_BACKEND_AND_PRIVILEGE_DESIGN.md` | 515 | Helper separation, fixed operations, rule model, socket paths, nftables/iptables design, open decisions. |
| `docs/PHASE_2L_2H_4_PERSISTENCE_RECOVERY_AND_DEPLOYMENT_DESIGN.md` | 539 | Schema, evidence, idempotency, recovery, service users, socket modes, deployment, final checklist. |
| `docs/PHASE_2L_2H_5_IMPLEMENTATION_AND_VALIDATION_ROADMAP.md` | 538 | Sequence, test layers, gates, open decisions, RR/I residuals, final checklist. |

### 2.2 Code and tests inspected

Code inspection was targeted at claims that had to be verified, not at a full source audit.

| Area | Files and evidence inspected |
|---|---|
| Controller identity and digest | `broker/firewall_controller_service/controller_service.py`, especially identity/digest fields, `_validate_caller_identifiers`, `_canonicalize`, request handling, `policy_version` handling, and audit fields. |
| Controller authorization | `broker/firewall_controller_service/authorization_strict.py`, especially peer UID/GID extraction and caller-flag rejection. |
| Controller transport | `broker/firewall_controller_service/mock_transport.py`, especially identity injection into request dictionaries. |
| Helper contract | `broker/firewall_controller_service/helper_contract.py`, especially `SCHEMA_VERSION`, allowed protocols, allowed fields, timeout fields, and operation names. |
| Persistence | `broker/firewall_controller_service/ownership_store.py`, especially `controller_ownership`, idempotency keying, `controller_audit`, and `controller_evidence`. |
| Broker HTTP/auth | `broker/app/auth.py`, `authorization.py`, `config.py`, `dependencies.py`, `routes.py`, `main.py`. |
| Broker UDS | `broker/app/uds.py`, especially directory creation, `chmod`, and unconditional unlink behavior. |
| Broker Docker | `broker/app/docker_adapter.py` and `broker/app/dependencies.py`. |
| Manager client/runtime | `manager/app/broker_client.py` and `manager/app/runtime/docker_adapter.py`. |
| Tests | `broker/tests/test_broker_uds.py`, `test_firewall_controller_transport_mock.py`, `test_firewall_controller_helper_identity_propagation.py`, `test_firewall_controller_revoke_recovery_and_idempotency_hardening.py`, and `manager/tests/test_runtime_adapter.py`. |

### 2.3 Evidence classification

Every claim in this review is classified using one of the following evidence states. The distinction
is intentional: documentation is not implementation, and mock behavior is not host behavior.

| Evidence state | Meaning in this review |
|---|---|
| **Verified evidence** | Directly verified in the current document or source text by this review, with the cited line/section. This does not imply runtime execution. |
| **Documentation-only claim** | A design decision, target value, gate, or intended control stated in a document, with no executable implementation or executed test. |
| **Implemented but untested** | Code exists, but this review did not execute it and no independent host or integration test result establishes the behavior. Most current controller behavior is in this category. |
| **Mock-only test** | A test uses in-process objects, patched functions, injected identities, or mock Docker clients. It can show intended Python behavior, not kernel, socket, privilege, Docker, firewall, or host behavior. |
| **Unimplemented architecture** | The target component or control does not exist in executable form: real UDS, `SO_PEERCRED`, restricted helper, runtime adapter, nftables/iptables execution, deployment enforcement. |
| **Unaccepted risk** | A residual risk is documented as open but has no formal acceptance by an identified authority, with criteria and evidence. T-27, T-11, T-13, RR-01–RR-07, and I-07–I-09 are in this category. |

No test was executed by this review. References to "tests" mean test files or test identifiers were
inspected; they do not mean the test passed, failed, or ran on a host.

## 3. Review A — Verify All Five High-Severity Findings

The 2I.2 report's dispositions were not accepted automatically. Each High finding was checked against
the original 2I.1 finding, the 2I.2 decision, the updated 2H documents, and the current code/tests
where the finding concerns current behavior. A design correction is recorded separately from an
implemented control.

| ID | Original title | Design status | Implementation/test status | Final disposition |
|---|---|---|---|---|
| H-01 | Socket directory permissions cannot support the documented UDS edges. | Directory/socket values fixed; group-assignment mechanism still missing (N-01). | No real UDS; current helper ignores `uid`/`gid`. | **OPEN** |
| H-02 | Broker Docker authority can bypass the controller/helper and host-firewall restriction claim. | Target broker/runtime boundary designed; T-27 residual open. | Broker and manager Docker adapters still present; runtime adapter absent. | **PARTIALLY RESOLVED** |
| H-03 | Target controller identity adapter is undefined; current service reads request `peer_uid`/`peer_gid` and includes them in the digest. | Typed `SO_PEERCRED` target designed. | Current request identity and digest behavior remain; no real peer adapter. | **PARTIALLY RESOLVED** |
| H-04 | Manager-broker boundary is unresolved; current HTTP auth is unsafe if retained. | Direct-bind UDS target designed; HTTP removed from target. | Current broker is still HTTP/FastAPI with unsafe header auth; manager client is a stub. | **PARTIALLY RESOLVED** |
| H-05 | Wire protocol/operation contract is not frozen and conflicts with current contracts. | Envelope and operation set largely frozen; rule schema contradiction remains (N-02). | Current helper contract still uses `2L.2G.3`, old operations, `timeout_ms`, and broader protocols. | **OPEN** |

### H-01 — Socket directory permissions cannot support the documented UDS edges.

**Original security issue (F-01).** The prior model could not simultaneously give a direct-bind
server directory write permission and a client directory execute permission. A server-owned directory
with a different client group is the correct shape, but a server must also create the socket in the
client group with mode `0660`. Without an explicit group-assignment mechanism, implementers are
pushed toward world-writable sockets, `CAP_CHOWN` on every server, or adding each server to its
client's group. Those workarounds weaken the separation the architecture claims.

**2I.2 decision and updated evidence.** 2I.2 Section 5 selects direct bind, server-owned `0750`
directories, client-group traversal, and socket `0660`, with exact owner/group/mode checks. 2H.1
Sections 5.1–5.2 and 2H.4 Section 6.3 repeat the same owner:group/mode values. Those values are
consistent across the documents.

**Independent assessment.** The values do not establish a workable creation mechanism. The server's
primary group is the server service group (for example, `flaghunt-broker`), while the socket group
must be the client group (for example, `flaghunt-manager`). A server cannot normally `chown` a socket
to a group it is not a member of, and no document selects a setgid directory, a
`systemd-tmpfiles` ownership mechanism, a supplementary-group policy, or a `CAP_CHOWN` design.
2H.5 Section 7 leaves the supplementary-group policy open. The current
`broker/app/uds.py:47–69` accepts `uid` and `gid` parameters but never calls `chown`, `fchown`, or
`fchmod` on a socket; it only creates/chmods the directory and unlinks the path. The target security
property therefore depends on an unimplemented, unspecified mechanism.

**Remaining dependency.** Close N-01: choose and document one mechanism, implement it in the socket
lifecycle, add startup assertions, and prove cross-UID connect/deny behavior on a real host.

**Disposition: OPEN.** The directory model is improved, but the High finding is not closed.

### H-02 — Broker Docker authority can bypass the controller/helper and host-firewall restriction claim.

**Original security issue (F-02).** A broker with Docker API access has host-root-equivalent
authority: it can create privileged containers, mount host paths, join host namespaces, or alter
network state. That bypasses the controller/helper restriction claim.

**2I.2 decision and updated evidence.** 2I.2 Section 6 and 2H.1 Sections 3.2 and 5.7 move Docker
behind a restricted `flaghunt-runtime` adapter with a fixed operation catalog and no privileged
containers, host mounts, host networking, or capability grants. 2H.2 T-27 and 2H.4 Section 6.2 repeat
that only the runtime adapter may hold Docker access. The design also states that a rootful Docker
daemon remains host-root-equivalent and that the residual requires acceptance.

**Independent assessment.** The target boundary is directionally correct but is not implemented or
enforced. Current `broker/app/dependencies.py:47–49` still constructs `BrokerDockerAdapter`;
`broker/app/routes.py:48–63` still exposes container creation; `broker/app/docker_adapter.py` still
accepts a Docker client. The current dependency supplies no client, so the route fails closed at
runtime, but the authority-bearing code path remains. In addition,
`manager/app/runtime/docker_adapter.py:18–26` implements a `DockerRuntimeAdapter` and
`manager/tests/test_runtime_adapter.py` exercises it with `MagicMock` clients. The target says the
manager has no Docker authority. The manager adapter is not wired into manager routes in the
inspected code, so live reachability is not established; the code-level boundary is nevertheless not
mechanically removed.

**Remaining dependency.** Implement the runtime adapter; remove or fail-closed the broker and manager
Docker paths; prove no broker/manager Docker socket, group, or client reachability; execute the
RTA-01–RTA-06 tests; and obtain a formal T-27 acceptance or remove rootful Docker entirely.

**Disposition: PARTIALLY RESOLVED.** The architecture-level broker design is resolved; H-02 is not
closed because the runtime residual is open and current Docker authority paths remain.

### H-03 — Target controller identity adapter is undefined; current service reads request `peer_uid`/`peer_gid` and includes them in the digest.

**Original security issue (F-03).** If the controller trusts UID/GID values from a request, any
process that can submit a request can assert another peer's identity. Including those values in the
security digest makes a spoofed identity look like part of an authenticated request.

**2I.2 decision and updated evidence.** 2I.2 Section 7 and 2H.1 Section 5.3 define an immutable typed
identity derived only from `SO_PEERCRED`, supplied out of band, copied once, and never read from
request JSON or headers. The request schema rejects identity fields. 2H.2 T-04 and T-01 require
identity-spoof tests.

**Independent assessment.** Current code still contradicts the target.
`broker/firewall_controller_service/authorization_strict.py:25–33` reads `peer_uid` and `peer_gid`
from the request dictionary and converts them with `int()`. `controller_service.py` includes
`peer_uid` and `peer_gid` in the identity/digest fields and audit context.
`mock_transport.py:11–18` injects a `PeerIdentity` into the request. No real kernel credential is
consulted. The strict provider also permits caller-supplied `controller_verified: true` to suppress
rejection of other caller-supplied identity flags at lines 21–23; that is not the target's immutable
identity model. Existing identity tests inject dictionaries or call Python classes; they do not
create a UDS or call `SO_PEERCRED`.

**Remaining dependency.** Implement the real peer-credential adapter, remove identity fields from
the request schema and digest, remove caller-controlled verification flags, and execute spoof,
wrong-UID, wrong-GID, missing-credential, and stale-descriptor tests.

**Disposition: PARTIALLY RESOLVED.** The target contract is documented; the High finding is not
implemented or closed.

### H-04 — Manager-broker boundary is unresolved; current HTTP auth is unsafe if retained.

**Original security issue (F-04).** The current broker exposes HTTP routes protected by
caller-supplied identity headers and an optional bearer token. If retained, any local caller that
can reach the port can spoof identity headers or exploit weak token defaults.

**2I.2 decision and updated evidence.** 2I.2 Section 8, 2H.1 Sections 3.1, 4.1, 5.1, and 7, and
2H.4 Section 6.3 replace the manager-broker edge with direct-bind UDS, server-side `SO_PEERCRED`, and
UID/GID allowlists. No HTTP fallback is permitted in the target.

**Independent assessment.** The current broker is still a FastAPI HTTP application
(`broker/app/main.py:9–16`). `broker/app/auth.py:15–33` parses `X-Broker-Peer-Uid`,
`X-Broker-Peer-Gid`, `X-Broker-Peer-User`, and `X-Broker-Token`; it merges the caller-derived
dictionary after real peer data (`{**real_peer, **peer_info}`), so caller headers override the
kernel values it claims to prefer. The token check is skipped if the token header is absent, and
`broker/app/config.py:9–16` defaults the token to empty and the authorized UID/GID to `-1`.
`broker/app/authorization.py:40–48` treats negative allowlists as allowing any peer. The manager
`BrokerClient` is a 31-line abstraction that does not implement a real UDS request. These are current
unsafe behaviors, not merely missing future work.

**Remaining dependency.** Implement the UDS manager/broker client and server, delete or hard-disable
HTTP in the live path, enforce kernel identity on both sides, remove token/header identity, and add
cross-UID and spoof tests on a host.

**Disposition: PARTIALLY RESOLVED.** The target is documented; current unsafe HTTP behavior remains
and the UDS boundary is unimplemented.

### H-05 — Wire protocol/operation contract is not frozen and conflicts with current contracts.

**Original security issue (F-05).** If the manager, broker, controller, and helper do not agree on
one exact message schema and operation set, a request can be interpreted differently at different
layers, especially around identity, ownership, timeout, and rule semantics.

**2I.2 decision and updated evidence.** 2I.2 Section 9 and 2H.1 Sections 4.1–4.5 freeze the
`flaghunt-local` envelope, schema version `2L.2I.2`, message classes, operation names, required
fields, `deadline_ms`, bounded frame sizes, and error registry. 2H.5 treats `2L.2H.1` and
`ownership_record_id`/`timeout_ms` as migration-only names.

**Independent assessment.** The envelope and operation-level freeze is substantially improved, but
the rule payload is still contradictory. 2H.1 Section 4.4 states that each rule has exactly
`family`, `protocol` (`tcp` or `udp`), `source_cidr`, `destination_cidr`, `port_start`, `port_end`,
and `action`, and explicitly rejects `icmp`. It places no direction, state, or DNS semantics in the
frozen rule and does not limit CIDRs to the owned challenge network. 2H.3 Section 3.3 instead
requires direction, connection-state, DNS destination semantics, source/destination values bounded
to the owned network, and optional approved ICMP. The `compiled` object is described as data-only,
but no canonical compiled schema exists to reconcile those fields. This is a direct contract
conflict, recorded as N-02.

Current `broker/firewall_controller_service/helper_contract.py:16` still declares
`SCHEMA_VERSION = "2L.2G.3"`; line 26 allows `icmp`, `icmpv6`, and `any`; lines 50–51 permit port 0
and superset behavior; and line 71 still accepts `timeout_ms`. The current helper operations are
`REMOVE_OWNED_POLICY` and `RECONCILE_OWNED_POLICY`, not the target operation names. The current
contract is therefore not a migration-only difference; it is a different contract.

**Remaining dependency.** Reconcile the rule schema and compiled object first, then freeze the
result in 2H.1/2H.3/2H.4/2H.5 and update the helper contract and negative tests.

**Disposition: OPEN.** H-05 is not closed until the rule contract is internally consistent and the
helper migration is defined.

## 4. Review B — Verify All Nine Medium-Severity Findings

The Medium findings are mostly documentation/schema/lifecycle corrections. They are assessed on
whether the design requirement is met and whether the required implementation/test evidence exists.
No test was executed for this review.

| ID | Original title | 2I.2 evidence and updated documents | Independent verification | Missing evidence | Final disposition |
|---|---|---|---|---|---|
| M-01 | Idempotency key scope contradicts across documents and schema. | 2I.2 §10.1; 2H.1 §4.3; 2H.4 §3.1; 2H.5. | Target is global-per-receiver key scope. The current idempotency schema and the test at `test_firewall_controller_revoke_recovery_and_idempotency_hardening.py:773` use per-operation scope. No migration exists. | DB migration, conflict/replay tests, cross-operation tests. | **PARTIALLY RESOLVED** |
| M-02 | Target UDS lifecycle is not matched by current scaffold, and the target lacks an implementation contract. | 2I.2 §10.2; 2H.1 §5.2; 2H.4 §6.3; 2H.5. | Target lifecycle is direct bind, dead/live probe, temp-bind plus atomic rename, own-inode cleanup, and exact checks. Current `broker/app/uds.py:55–64` makes directories, chmods, and unconditionally unlinks the path; it does not probe, lstat, verify owner/mode, or preserve an inode. | Implementation and real path/permission tests. | **PARTIALLY RESOLVED** |
| M-03 | 2H residual register omits I-07, I-08, and I-09. | 2I.2 §10.3; 2H.2 §6/6.1; 2H.5 §2.5; 2I.2 §13.1 claims all five documents. | I-07–I-09 are present in 2H.2 and 2H.5, but absent from 2H.1 §2.4, 2H.3 §1.1, and 2H.4 §1.3; 2H.4's final checklist lists only RR-01–RR-07. The 2I.2 matrix overstates this. No severity/impact/owner is assigned. | Propagation to all docs, classification, owners, corrected matrix. See N-03. | **PARTIALLY RESOLVED** |
| M-04 | No per-threat validation test mapping. | 2I.2 §10.4; 2H.2 §4.3; 2H.5 §4.2. | The T-01–T-28 mapping exists and includes test IDs and gates. This closes the mapping finding, not the tests. | None for the mapping; execution remains under M-09/host gate. | **CLOSED — documentation/traceability only** |
| M-05 | Threat register misses supply-chain, resource, audit, and Docker-host threats. | 2I.2 §10.5; 2H.2 §4 T-25–T-28; 2H.5. | T-25–T-28 are present with controls, residual risk, detection, recovery, and test IDs. This closes the register omission, not the controls. | None for the register; controls/tests remain open. | **CLOSED — threat-register only** |
| M-06 | Evidence immutability is prose-only and partial states can be represented falsely. | 2I.2 §10.6; 2H.4 §2.2–2.5 and §5.2; 2H.5. | Design specifies append-only evidence, FKs/`ON DELETE RESTRICT`, no stored `PARTIALLY_*`, per-family derived state, and read-back. Current `controller_evidence` table has no triggers, FKs, or aggregate invariants. | Migration, trigger/FK tests, partial-state/read-back tests. | **PARTIALLY RESOLVED** |
| M-07 | Numeric UID/GID allowlists and runtime deployment assumptions are incomplete. | 2I.2 §10.7; 2H.1 §5.3; 2H.3 §5.4; 2H.4 §6.2. | Target uses proposed numeric IDs, exact paths/modes, and startup checks. Current broker defaults are `authorized_manager_uid=-1`, `gid=-1`, empty token, and `/run/flaghunt/broker.sock`; no deployment assertions exist. | Numeric config, startup checks, service-account tests. | **PARTIALLY RESOLVED** |
| M-08 | Current helper contract is broader than the target and conflicts on timeout/ownership/version. | 2I.2 §10.8; 2H.1 §4.3–4.4; 2H.3 §4/5.7; 2H.5. | Target migration contract is `2L.2G.3` to `2L.2I.2`, `timeout_ms` to `deadline_ms`, `ownership_record_id` to `ownership_reference`, fixed operation names, and TCP/UDP only. Current helper has old version, old operations, old fields, and `any`/ICMP. | Implementation, migration, compatibility/negative tests. | **PARTIALLY RESOLVED** |
| M-09 | Exact nftables/iptables/Docker/host-validation behavior is unexecuted. | 2I.2 §10.9; 2H.3 §8; 2H.4 §9; 2H.5 §6–7. | The documents explicitly leave the host gate open. No host, Docker, firewall, privilege, reboot, or rollback test exists in the executed evidence set. | Complete controlled host-validation evidence and acceptance. | **OPEN** |

### Medium count and closure notes

**Medium total: 9. Closed: 2. Open: 1. Partially resolved: 6.**

M-04 and M-05 are closed only in the documentation/traceability sense. Their original findings were
about missing mappings/entries, and those mappings/entries now exist. Their associated controls and
tests are not closed: T-25–T-28 are tracked in 2H.2 and 2H.5, and no test has run. Calling either
finding "security resolved" would be incorrect.

## 5. Review C — F-01 Through F-14 Traceability

All original F-01–F-14 identifiers remain present. The table below maps each to its H/M remediation,
the design evidence, the remaining gap, and the final disposition. No finding was renamed, combined,
or silently removed.

| Finding | Severity | Remediation mapping | Evidence | Remaining gap | Final status |
|---|---|---|---|---|---|
| F-01 — Socket directory permissions cannot support the documented UDS edges. | High | H-01; 2I.2 §5 | 2H.1 §5.1–5.2; 2H.4 §6.3; target values consistent | N-01 socket-group mechanism; current `uds.py` ignores `uid`/`gid`; no cross-UID test | **OPEN** |
| F-02 — Broker Docker authority can bypass the controller/helper and host-firewall restriction claim. | High | H-02; 2I.2 §6 | 2H.1 §3.2/5.7; 2H.2 T-27; 2H.4 §6.2; target broker no Docker/runtime adapter | Broker/manager Docker adapters remain; runtime adapter absent; T-27 unaccepted; RTA tests not run | **PARTIALLY RESOLVED** |
| F-03 — Target controller identity adapter is undefined; current service reads request `peer_uid`/`peer_gid` and includes them in the digest. | High | H-03; 2I.2 §7 | 2H.1 §5.3; 2H.2 T-04/T-01; target immutable `SO_PEERCRED` | Current request identity/digest and mock injection remain; no real peer adapter | **PARTIALLY RESOLVED** |
| F-04 — Manager-broker boundary is unresolved; current HTTP auth is unsafe if retained. | High | H-04; 2I.2 §8 | 2H.1 §3.1/4.1/5.1/7; 2H.4 §6.3; target direct-bind UDS | Current HTTP header auth and unsafe merge remain; manager client stub; no UDS test | **PARTIALLY RESOLVED** |
| F-05 — Wire protocol/operation contract is not frozen and conflicts with current contracts. | High | H-05; 2I.2 §9 | 2H.1 §4.1–4.5; 2H.3 §3.3; 2H.5 | N-02 rule-schema conflict; current helper `2L.2G.3`/old operations | **OPEN** |
| F-06 — Idempotency key scope contradicts across documents and schema. | Medium | M-01; 2I.2 §10.1 | 2H.1 §4.3; 2H.4 §3.1; global key design | Current per-operation schema/test; no migration or conflict tests | **PARTIALLY RESOLVED** |
| F-07 — Target UDS lifecycle is not matched by current scaffold, and the target lacks an implementation contract. | Medium | M-02; 2I.2 §10.2 | 2H.1 §5.2; 2H.4 §6.3; lifecycle contract | Current `uds.py` blind unlink/no checks; implementation/tests absent | **PARTIALLY RESOLVED** |
| F-08 — 2H residual register omits I-07, I-08, and I-09. | Medium | M-03; 2I.2 §10.3 | 2H.2 §6/6.1; 2H.5 §2.5 | Missing from 2H.1 §2.4/2H.3 §1.1/2H.4 §1.3; matrix overstates; owners absent | **PARTIALLY RESOLVED** |
| F-09 — No per-threat validation test mapping. | Medium | M-04; 2I.2 §10.4 | 2H.2 §4.3; 2H.5 §4.2; all T-01–T-28 have test IDs/gates | Mapping only; no test executed; host gate remains | **CLOSED — mapping only** |
| F-10 — Threat register misses supply-chain, resource, audit, and Docker-host threats. | Medium | M-05; 2I.2 §10.5 | 2H.2 §4 T-25–T-28 with controls/test IDs | Register only; controls/tests unimplemented/unexecuted | **CLOSED — register only** |
| F-11 — Evidence immutability is prose-only and partial states can be represented falsely. | Medium | M-06; 2I.2 §10.6 | 2H.4 §2.2–2.5/5.2; triggers/FKs/per-family design | Current evidence table lacks triggers/FKs/invariants; no migration/tests | **PARTIALLY RESOLVED** |
| F-12 — Numeric UID/GID allowlists and runtime deployment assumptions are incomplete. | Medium | M-07; 2I.2 §10.7 | 2H.1 §5.3; 2H.3 §5.4; 2H.4 §6.2; numeric-ID design | Current defaults `-1`/empty/old path; no deployment assertions | **PARTIALLY RESOLVED** |
| F-13 — Current helper contract is broader than the target and conflicts on timeout/ownership/version. | Medium | M-08; 2I.2 §10.8 | 2H.1 §4.3–4.4; 2H.3 §4/5.7; migration contract | Current helper old version/operations/fields/`any`/ICMP; no migration/tests | **PARTIALLY RESOLVED** |
| F-14 — Exact nftables/iptables/Docker/host-validation behavior is unexecuted. | Medium | M-09; 2I.2 §10.9 | 2H.3 §8; 2H.4 §9; 2H.5 §6–7; explicit open gate | No host/Docker/firewall/privilege/reboot/rollback test or acceptance | **OPEN** |

**Traceability conclusion.** All 14 original findings remain identifiable. No finding was
incorrectly marked closed in this review. The only closures are M-04/M-05 documentation findings,
and their security controls/tests remain explicitly open. The 2I.2 report's claim that the
architecture is fully design-remediated is not accepted because H-01, H-05, and M-03 retain
unresolved defects (N-01, N-02, N-03).

## 6. Review D — Reassess T-27

T-27 is the residual for runtime-adapter and Docker host-root authority. It is not closed by moving
Docker from the broker to another component: rootful Docker access is host-root-equivalent regardless
of the component's name unless the component is externally isolated and its operation surface is
technically constrained.

### 6.1 Question-by-question assessment

| Question | Assessment | Evidence |
|---|---|---|
| Does the broker have direct or indirect Docker authority? | The current code still contains and wires a `BrokerDockerAdapter`; the dependency passes no client, so the route fails closed in the inspected configuration. The target removes broker Docker authority, but that is not implemented. The manager also contains a separate `DockerRuntimeAdapter`, though it is not wired into manager routes in the inspected code. | `broker/app/dependencies.py:47–49`; `broker/app/routes.py:48–63`; `broker/app/docker_adapter.py`; `manager/app/runtime/docker_adapter.py:18–26`; 2H.1 §3.2/5.7; 2H.2 T-27. |
| Can a runtime adapter exercise host-root-equivalent authority? | Yes, by design, if it holds the rootful Docker socket. The fixed operation catalog reduces the generic API to challenge operations, but the daemon remains capable of host-level effects. The documents acknowledge this and require acceptance. No runtime adapter service exists in the inspected code. | 2H.1 §3.2/5.7; 2H.3 §5.7; 2H.4 §6.2; 2H.5 open decision/acceptance gate. |
| Can the controller request operations outside its intended authority? | The target controller may request only the fixed helper operation set for owned policies. A compromised controller can still request valid operations for owned policies (T-11), and the current helper contract still exposes old operations. There is no evidence of arbitrary shell/rule-text execution in the target, but no real helper enforcement exists. | 2H.1 §4.3–4.5; 2H.3 §4/5.7; `helper_contract.py`; 2H.2 T-11/T-12. |
| Are operation boundaries technically enforceable? | The design intends fixed enums, ownership labels/references, read-back, and no shell. Those are enforceable in principle. They are not implemented, and the Docker daemon boundary remains generic unless the runtime adapter's fixed operations and isolation are real. | 2H.1 §4.4; 2H.3 §4/5.7; 2H.2 T-27; no runtime adapter code. |
| Is Docker access isolated behind a sufficiently restricted component? | Not in the current repository. The broker and manager contain Docker adapters; the runtime adapter is documentation-only. The target separation is not mechanically enforced by packaging, users, groups, or tests. | Broker/manager adapters above; 2H.4 §6.2; 2H.5 RTA tests. |
| Does the architecture document the boundary and residual? | Yes. The target boundary is documented, and T-27 is explicitly open. Documentation alone does not close the residual. | 2H.2 T-27; 2I.2 §6; 2H.5 §6–7. |
| Is the residual formally accepted? | No. There is no named acceptance authority, acceptance criteria, signed record, or host isolation evidence. 2I.2 Section 6 says the residual blocks implementation until accepted or removed. | 2H.2 T-27; 2I.2 §6.4; 2H.5 open decisions. |

### 6.2 Evidence-state distinction

| State | T-27 evidence |
|---|---|
| **Verified** | Current broker/manager source contains Docker adapters; broker route/dependency wiring exists; broker dependency passes no client; manager adapter is exercised only by mock tests; target documents say only the runtime adapter may hold Docker access. |
| **Documentation-only** | Runtime adapter service, fixed operation catalog, no privileged containers/host mounts/host networking, rootful-Docker residual, and RTA-01–RTA-06 gates. |
| **Implemented but untested** | Broker Docker route/adapter code exists but fails closed without an injected client; manager adapter code exists but is not wired to routes. This is not proof of a safe boundary. |
| **Mock-only** | `manager/tests/test_runtime_adapter.py` uses `MagicMock` Docker clients. It proves Python method behavior, not Docker isolation or host authority. |
| **Unimplemented** | The restricted runtime adapter service, its fixed operations, its Docker socket isolation, and its host tests. |
| **Unaccepted** | The rootful Docker host-root-equivalent residual and the current broker/manager Docker code paths. |

### 6.3 T-27 disposition

**OPEN — ACCEPTANCE REQUIRED.** The target boundary is coherent but not implemented. Current code
still carries Docker authority in the broker and manager, and rootful Docker remains
host-root-equivalent. T-27 must be either (a) formally accepted by an identified authority with
explicit isolation, monitoring, blast-radius, and compensating controls, or (b) removed by using an
externally isolated challenge runtime that gives the broker/manager no Docker access. A risk-register
entry is not acceptance.

## 7. Review E — T-11 and T-13 Risk Acceptance

T-11 (compromised controller) and T-13 (compromised helper with `CAP_NET_ADMIN`) are High residuals in
2H.2. A risk-register row, a design explanation, or a "will monitor" statement is not formal
acceptance. Acceptance requires an identified authority, scope, criteria, compensating controls,
monitoring/isolation evidence, and a durable record.

| ID | Original risk | Required acceptance authority | Evidence that would be required | Acceptance present? | Possible mitigation / dependency | Status |
|---|---|---|---|---|---|---|
| T-11 | A compromised controller can issue valid helper operations for owned policies, deny service, falsify local evidence, or suppress audit. | Named security/architecture owner with authority over the host-validation phase. | Controller compromise model; helper-side ownership and independent audit; DB least privilege; host isolation/monitoring; blast-radius limits; recovery/rollback evidence; CTRL-04 test result. | **No.** No authority, record, criteria, or test result. | Helper independently validates peer/ownership; helper audit is separate; controller lacks `CAP_NET_ADMIN`; DB least privilege. These are design claims, not implemented/validated. | **OPEN — ACCEPTANCE REQUIRED** |
| T-13 | A compromised helper with `CAP_NET_ADMIN` can mutate host firewall/network state, deny service, or bypass intended boundaries. | Named security/architecture owner with authority over capability grants and host isolation. | Exact capability set; seccomp/AppArmor/SELinux profile; host network isolation; independent audit; blast-radius and recovery evidence; CAP-05 test result. | **No.** No authority, record, criteria, or test result. | Fixed helper operations, no shell, ownership markers, read-back, least privilege. These reduce but do not eliminate host network authority. | **OPEN — ACCEPTANCE REQUIRED** |

2H.2 maps T-11 and T-13 to required test IDs including `CTRL-04` and `CAP-05`; those tests have not
been executed. 2H.5 Section 6.1 requires `T-11/T-13/T-27 acceptance recorded` before implementation,
and 2H.3 Section 8 leaves the exact privilege/seccomp/MAC profile open. No document contains a signed
or dated acceptance statement.

**Disposition: OPEN — ACCEPTANCE REQUIRED for both T-11 and T-13.** This review cannot accept these
residuals on the project's behalf.

## 8. Review F — RR-01 Through RR-07

RR-01 through RR-07 are preserved in 2H.2 Section 6 and 2H.5 Section 2.5. 2H.1, 2H.3, and 2H.4
reference the RR set, but 2H.4's final checklist covers only RR-01–RR-07 and does not include
I-07–I-09. All seven remain open; none has an assigned owner.

| ID | Residual | Affected component | Security implication | Current mitigation / design direction | Required closure evidence | Owner | Status |
|---|---|---|---|---|---|---|---|
| RR-01 | `request_id` canonical validation scope | Broker/controller/helper request handling and audit | Malformed IDs can confuse evidence, deduplication, or error mapping; non-string/empty/control/oversized values may reach persistence. | Canonical validation before mock store/idempotency use; framed-RPC/schema validation; no identity use. | Universal validation tests across all request paths; reject-without-mutation tests. | **Not named** | **OPEN** |
| RR-02 | `operation_id` canonical scope | Controller/helper operation evidence | Ambiguous operation identity can cause incorrect evidence binding or duplicate operation handling. | Canonical validation and operation binding; unique operation semantics. | Validation/uniqueness/binding tests. | **Not named** | **OPEN** |
| RR-03 | `idempotency_key` canonical scope | Controller persistence/idempotency | Replay, collision, or cross-operation confusion if key scope and canonical form differ. | Global-per-receiver key plus digest/operation/principal/ownership binding; conflict is not cached success. | Migration and global-scope, conflict, replay, crash tests. | **Not named** | **OPEN** |
| RR-04 | `policy_version` type/range | Controller request/DB | Boolean, string, overflow, or out-of-range values can bypass version comparison or corrupt evidence. | App rejection plus DB `CHECK`; exact integer range; no aliases. | Migration, malformed-type/range tests, DB constraint tests. | **Not named** | **OPEN** |
| RR-05 | Full-scan reconciliation | Controller recovery | Missed non-terminal states, stale ownership, or drift after restart. | Full scan of all non-terminal states; no aggregate partial state; read-back. | Crash/restart, stale, unknown, partial, and full-scan tests. | **Not named** | **OPEN** |
| RR-06 | I-3.9-01 missing digest DB `CHECK` | Controller database | Invalid or truncated digest could be inserted and later trusted. | App/helper validation plus DB `CHECK` migration. | Negative digest insertion tests; migration verification. | **Not named** | **OPEN** |
| RR-07 | I-3.9-03 retained `__context__` | Error mapping/audit/logging | Raw exception context can leak SQL, paths, or internal implementation details. | Sanitized error mapper; bounded codes; logging/transport review. | Leakage tests and log/config inspection. | **Not named** | **OPEN** |

**RR conclusion.** All seven are open. Design mitigations exist for several, but no closure evidence
or formal acceptance exists. The absence of named owners contradicts 2H.5 Section 6.1, which requires
RR-01–RR-07 to have owners/plans. This is a readiness blocker, not a documentation nicety.

## 9. Review G — I-07, I-08 and I-09

I-07, I-08, and I-09 are carried residual risks. They are present in 2H.2 Section 6/6.1 and 2H.5
Section 2.5, but not in 2H.1 Section 2.4, 2H.3 Section 1.1, or 2H.4 Section 1.3. The 2I.2
cross-document matrix at Section 13.1 states that I-07–I-09 are open in 2H.1 Sections 8, 2H.3
Sections 8, and 2H.4 Section 9. Those sections are open-decision/consistency sections; they do not
name I-07–I-09. This is a verified documentation inconsistency (N-03).

| ID | Residual title | Classification in current docs | Impact and affected component | Traceability/status | Required action |
|---|---|---|---|---|---|
| I-07 | Broader identifier/field scope | "OPEN — carried" residual; no explicit severity, impact statement, or owner. | Incomplete universal validation across broker/controller/helper fields and entries can leave non-canonical values in state/evidence. | 2H.2 §6/6.1; 2H.5 §2.5; **not named** in 2H.1 §2.4, 2H.3 §1.1, 2H.4 §1.3. **OPEN.** | Universal schema validation across all fields/entries; tests; assign owner; propagate to all docs. |
| I-08 | Raw `BrokerDBError` on non-failure paths | "OPEN — carried" residual; no explicit severity, impact statement, or owner. | Raw database errors can expose SQL, paths, or internal state in API/audit/error responses. | 2H.2 §6/6.1; 2H.5 §2.5; **not named** in 2H.1/3/4 residual lists. **OPEN.** | Sanitized error mapper on all persistence paths; leakage tests; assign owner; propagate. |
| I-09 | `strict_auth=False` legacy footgun | "OPEN — carried" residual; no explicit severity, impact statement, or owner. | If a production path can select `strict_auth=False`, identity verification is bypassed. This is an authentication footgun, not merely informational. | 2H.2 §6/6.1; 2H.5 §2.5; **not named** in 2H.1/3/4 residual lists. **OPEN.** | Remove from live path; gate test-only use; add deployment assertion; assign owner; propagate. |

**I conclusion.** All three remain open. The lack of severity, impact, affected-component, and owner
fields makes them easy to omit from acceptance decisions; I-09 in particular should be treated as at
least High if any live path can set `strict_auth=False`. Their omission from three architecture
documents and from the 2H.4 final checklist is a governance/security-tracking defect.

## 10. Review H — Cross-Document Architecture Consistency

The five 2H documents and the 2I.2 report were compared directly. Target values are largely
consistent, but consistent prose is not sufficient where the documents contradict each other or
where the implementation still uses a different contract.

### 10.1 Consistency matrix

| Area | 2H.1 | 2H.2 | 2H.3 | 2H.4 | 2H.5 | Independent result |
|---|---|---|---|---|---|---|
| Manager-to-broker transport | Direct-bind UDS; no HTTP target | TB-1/T-01/T-03 | Section 5.5 | Section 6.3/6.5 | Sections 2.1–2.4 | Target values consistent; current HTTP remains; H-04 open. |
| Broker-to-controller transport | Direct-bind controller socket | T-01/T-03/T-11 | Section 5.5 | Section 6.3 | Sections 2.1–2.4 | Target values consistent; no real route; H-05/M-02 open. |
| UDS ownership and permissions | §5.1–5.2 table | T-01/T-03 | §5.4 | §6.2–6.3 | §2.4/§4 | Owner:group/mode values consistent; creation mechanism N-01 open. |
| Message framing | Envelope/frame/limits | T-02/T-08 | §4 | n/a | §3/§4 | Target consistent; no protocol library; H-05 open. |
| Request validation | Exact fields/IDs/digests | T-04/T-07/T-08 | §3/§4 | §2 | §2.3 | Mostly consistent; rule payload conflict N-02; current validators differ. |
| Timeouts and failure handling | `deadline_ms`, hard deadlines | T-02/T-08 | §4.3 | §5 | §4 | Target consistent; current helper uses `timeout_ms`; M-08 open. |
| Authentication and peer verification | `SO_PEERCRED`, typed identity | T-01/T-04/T-12 | §5.3–5.5 | §6.3 | §2.3/§4 | Target consistent; current request/header identity; H-03/H-04 open. |
| UID/GID allowlists | Numeric IDs/proposed | T-01/T-04 | §5.4 | §6.2 | §2.3 | Target numeric design consistent; current `-1`/empty defaults; M-07 open. |
| Service accounts and privilege separation | Process matrix | T-10/T-11/T-12 | §5.2–5.7 | §6.2–6.4 | §2.1–2.7 | Target consistent; no enforcement/tests; N-01/N-04/ T-27 open. |
| Unprivileged controller / restricted helper | Controller no `CAP_NET_ADMIN`; helper fixed ops | T-11–T-13 | §5.5–5.7 | §6.4 | §2.6 | Target consistent; helper unimplemented; T-11/T-13 unaccepted. |
| Fixed operation allowlist / no shell | Fixed enum/no shell | T-01/T-12 | §4 | §2 | §3 | Target consistent; current helper old ops; H-05/M-08 open. |
| nftables primary / iptables and DOCKER-USER fallback | Design consistent | T-08/T-27 | §3/§6/§8 | §9 | §4/§7 | Design consistent; no host execution; M-09 open. |
| IPv4/IPv6 parity | Per-family rules/state | T-07/T-08 | §3.3 | §2.4/§3 | §4 | Design consistent; no tests; M-06/M-09 open. |
| Policy ownership and verification | `ownership_reference`, read-back | T-07/T-11 | §4/§5.7 | §2–§3 | §4 | Target consistent; current `ownership_record_id`; M-08 open. |
| Durable intent and lifecycle | CAS/lifecycle version | T-05/T-07 | §4 | §2.4/§3 | §3 | Design consistent; current schema lacks CAS/migrations; M-01/M-06 open. |
| Idempotency | Global-per-receiver | T-05/T-06 | §4 | §3.1 | §3 | Target consistent; current per-operation schema/test; M-01 open. |
| Uncertain outcomes / reconciliation | `UNCERTAIN`, full scan | T-05/T-07 | §4 | §3/§5 | §3 | Design consistent; no execution; RR-05 open. |
| Restart recovery | Durable intent/replay | T-05/T-07 | §5 | §5 | §3 | Design consistent; no crash tests; RR-05/M-09 open. |
| Evidence retention and DB integrity | Append-only/FK/read-back | T-07/T-08 | §5 | §2.5 | §4 | Design consistent; current schema no triggers/FKs; M-06 open. |
| Deployment and validation | Paths/modes/numeric IDs | T-01/T-03/T-27 | §5/§7 | §6 | §6–7 | Design consistent; group mechanism N-01; no host tests; M-09 open. |
| Residual registers | RR-01–RR-07 only | RR + I-07–I-09 | RR only | I-3.9 only | RR + I-07–I-09 | **Inconsistent:** I-07–I-09 not propagated; N-03. |

### 10.2 Direct contradictions and overstatements

1. **Rule schema: 2H.1 §4.4 versus 2H.3 §3.3.** 2H.1 freezes exactly seven fields (`family`,
   `protocol` limited to `tcp`/`udp`, source/destination CIDR, port range, action), rejects ICMP,
   and omits direction, state, and DNS semantics. 2H.3 requires direction, connection-state, DNS
   destination semantics, bounded owned-network CIDRs, and optional approved ICMP. These cannot both
   be the frozen contract. This is N-02 and keeps H-05 open.
2. **Residual propagation: 2I.2 §13.1 versus the 2H residual lists.** 2I.2 states I-07–I-09 are open
   in 2H.1 §8, 2H.3 §8, and 2H.4 §9. The actual residual lists are 2H.1 §2.4 (RR only), 2H.3 §1.1
   (RR only), and 2H.4 §1.3 (I-3.9 only); 2H.4's final checklist at line 509 also lists only
   RR-01–RR-07. This is N-03 and keeps M-03 partially resolved.
3. **"Frozen" protocol claim versus the unfrozen rule payload.** 2I.2 §14.1 says the target documents
   agree on a frozen operation/timeout/error contract. The envelope and operations largely do, but
   the rule/compiled contract does not. The claim is broader than the evidence.
4. **Socket owner/group values versus creation mechanism.** 2H.1 §5.1/§5.2 and 2H.4 §6.3 require
   exact owner/group/mode, but no document selects the mechanism that gives a server-created socket
   the client group. This is N-01 and keeps H-01 open.
5. **Target no-Docker claim versus current code.** 2H.1/2H.4 say broker and manager have no Docker
   authority; current broker and manager contain Docker adapters. This is an implementation gap,
   amplified by N-04, not a contradiction among target documents.
6. **Target no-HTTP claim versus current broker.** 2H.1 says no HTTP fallback; current broker is a
   FastAPI application with header identity and an optional token. This is H-04, an implementation
   gap that makes the target unsafe if the current path is ever exposed live.

### 10.3 Cross-document conclusion

**CONDITIONAL.** Most target values are consistent, and the direction is coherent. The architecture
is not internally complete because N-01, N-02, and N-03 are open and because several "resolved"
claims are documentation-only. No new critical contradiction was found beyond N-02, but a High
contract contradiction is sufficient to prevent a PASS.

## 11. Review I — Additional Architecture Security Assessment

The review considered confused-deputy paths, privilege escalation, authentication bypass, replay and
duplication, socket/path races, resource exhaustion, input-validation gaps, IPv4/IPv6 asymmetry,
ownership confusion, Docker networking, persistence corruption, crash/uncertain outcomes, logging
leakage, fail-open/fail-closed behavior, and rollback/recovery. No additional Critical finding was
identified. Four new findings are recorded below.

### 11.1 New findings

| ID | Severity | Title | Verified evidence | Credible impact / attack path | Required action |
|---|---|---|---|---|---|
| N-01 | **Medium** | Socket group assignment is unspecified on every UDS edge. | 2H.1 §5.1–5.2; 2H.4 §6.2–6.3; 2H.5 §7 open decision 4; `broker/app/uds.py:47–69` accepts `uid`/`gid` but never chowns. | A server in its primary service group cannot create a socket owned by the client group without a setgid directory, supplementary-group membership, `CAP_CHOWN`, or a workaround. Workarounds can make the socket world-writable, grant a server access to client sockets, or fail startup. This blocks H-01 and host validation. | Select one mechanism (setgid directory, tmpfiles ownership, or explicit group policy), implement it, assert owner/group/mode at startup, and test cross-UID connect/deny. |
| N-02 | **High** | The frozen firewall rule schema conflicts with 2H.3 rule semantics. | 2H.1 §4.4: exactly seven fields, `tcp`/`udp` only, no direction/state/DNS, rejects ICMP, arbitrary CIDRs. 2H.3 §3.3: direction, state, DNS, bounded owned-network CIDRs, optional ICMP. `compiled` has no schema. | An implementer cannot satisfy both contracts. Likely outcomes are fail-closed rejection of valid policies or ambiguous defaults (both directions/unrestricted CIDR) that could install a broader rule than intended. This is a design-level over-permission risk before any host test. | Define one canonical rule and compiled schema, including direction/state/DNS/ICMP and CIDR bounds; update 2H.1/2H.3/2H.4/2H.5 and the helper contract; add negative tests. |
| N-03 | **Medium** | I-07/I-08/I-09 propagation, classification, and ownership are incomplete; the 2I.2 matrix overstates agreement. | 2I.2 §10.3/§13.1; 2H.2 §6/6.1; 2H.5 §2.5; absent from 2H.1 §2.4, 2H.3 §1.1, 2H.4 §1.3 and 2H.4 line 509; no severity/impact/owner. | Readers of standalone documents may omit I-09's `strict_auth=False` bypass or I-08's raw-error leak from acceptance gates. This is not a direct exploit by itself, but it can lead to an unaccepted auth-bypass/info-leak path in live code. | Propagate I-07–I-09 to every residual/checklist section, add severity/impact/affected component/owner, correct the 2I.2 matrix, and require explicit acceptance. |
| N-04 | **Medium** | Docker authority remains in broker and manager code; the "runtime adapter only" boundary is not mechanically enforced. | `broker/app/dependencies.py:47–49`; `broker/app/routes.py:48–63`; `broker/app/docker_adapter.py`; `manager/app/runtime/docker_adapter.py:18–26`; mock-only `manager/tests/test_runtime_adapter.py`. | The broker route fails closed without a client, and the manager adapter is not wired to routes in the inspected code, so live reachability is not proven. If a client is injected, code is reused, or wiring changes, manager/broker compromise yields host-root-equivalent Docker authority. This extends H-02/T-27. | Remove or relocate Docker adapters, enforce no broker/manager Docker socket/group, implement the runtime adapter boundary, and add import/route/Docker-access tests. |

### 11.2 N-01 detail — socket group mechanism

The target values are:

- manager→broker: directory `flaghunt-broker:flaghunt-manager` `0750`; socket same owner:group `0660`;
- broker→controller: directory `flaghunt-fwcontroller:flaghunt-broker` `0750`; socket `0660`;
- controller→helper: directory `flaghunt-fwhelper:flaghunt-fwcontroller` `0750`; socket `0660`;
- broker→runtime: directory `flaghunt-runtime:flaghunt-broker` `0750`; socket `0660`.

For each edge, the server's primary group differs from the socket's client group. A process cannot
normally change a file's group to a group it is not a member of; `chown`/`fchown` to another group
requires privilege, and adding the server to the client group gives the server membership in the
client boundary. A setgid directory would cause a newly created socket to inherit the directory group,
but no document states that the directory has the setgid bit or that the filesystem preserves it.
`systemd-tmpfiles` can create directories with a group, but it does not create the server's socket.
The current `setup_unix_socket` signature has `uid` and `gid` parameters but does not use them, which
is concrete evidence that the mechanism is absent rather than merely undocumented.

**Severity rationale.** Medium: the deployment can fail closed or implement a straightforward safe
mechanism; the finding is not an immediate remote exploit. It is a blocker because H-01's High
finding cannot be closed without it, and unsafe workarounds would raise the risk.

### 11.3 N-02 detail — rule schema contradiction

2H.1 Section 4.4 says each entry has exactly `family`, `protocol`, `source_cidr`,
`destination_cidr`, `port_start`, `port_end`, and `action`; protocols are `tcp`/`udp`; `any`, `icmp`,
and `icmpv6` are rejected. 2H.3 Section 3.3 says rules have explicit direction, connection-state, and
DNS destination semantics; source/destination are canonical CIDRs within the owned challenge
network; ICMP/ICMPv6 may be allowed only by explicit approved policy; arbitrary all-port accepts and
non-canonical CIDRs are rejected. The two models differ in fields, protocol support, and CIDR scope.
The `compiled` object is said to be data-only but has no canonical schema, so it cannot serve as the
missing bridge.

**Severity rationale.** High: this is the core firewall policy contract. A mismatch can cause either
a safe fail-closed outage or an over-permissive rule if an implementer fills missing semantics with
defaults. The risk is architectural and must be fixed before host validation.

### 11.4 N-03 detail — residual propagation and ownership

The 2I.2 report promised to update all five documents for I-07–I-09. Only 2H.2 and 2H.5 contain the
three items. 2H.2 Section 6/6.1 and 2H.5 Section 2.5 list them; 2H.1 Section 2.4, 2H.3 Section 1.1,
and 2H.4 Section 1.3 do not. 2H.4's final checklist at line 509 lists only RR-01–RR-07. The 2I.2
matrix at Section 13.1 claims otherwise. The entries also lack severity, impact/affected-component,
and owner fields, and 2H.5 Section 6.1 requires owners/plans for RR and I items without defining who
owns them.

**Severity rationale.** Medium: the immediate effect is governance/traceability, but I-09 is an
authentication bypass footgun and I-08 is an information-leak path. Losing them from standalone
documents can cause an unaccepted live risk.

### 11.5 N-04 detail — residual Docker authority in code

The target states that only the restricted runtime adapter may access Docker. Current code:

- `broker/app/dependencies.py:47–49` constructs `BrokerDockerAdapter()` with no client;
- `broker/app/routes.py:48–63` exposes container creation through that adapter;
- `broker/app/docker_adapter.py` accepts a Docker client and performs container operations;
- `manager/app/runtime/docker_adapter.py:18–26` implements `DockerRuntimeAdapter`;
- `manager/tests/test_runtime_adapter.py` uses `MagicMock` clients only.

The broker route fails closed in the inspected dependency configuration because no client is
provided. The manager adapter is not referenced by manager routes in the inspected code. Those facts
limit current reachability but do not establish the target boundary. The target's "no broker/manager
Docker authority" claim is not mechanically enforced, and the runtime adapter service is absent.
This reinforces T-27 rather than creating a separate host-root claim.

### 11.6 Other assessed areas

- **Confused deputy / ownership:** target ownership references, labels, and read-back are coherent;
  current identifiers differ and there is no real helper. Covered by H-05/M-08.
- **Authentication bypass:** current HTTP header precedence and missing-token behavior are unsafe;
  current controller request identity and `controller_verified` flag are not the target. Covered by
  H-03/H-04, not new.
- **Replay/duplication:** target global key scope is coherent; current per-operation scope and lack
  of migration are M-01/RR-03.
- **Socket/path races:** target dead/live probe, `lstat`, temp-bind, atomic rename, and own-inode
  cleanup are coherent; current blind unlink is unsafe. Covered by M-02; N-01 affects group setup.
- **Resource exhaustion:** target has bounded frames, one request per connection, deadlines, and
  audit controls. No real accept/worker cap test exists; host validation must include DOS-01–DOS-04.
- **Input/protocol:** rule schema N-02; identifier/field residuals I-07/RR-01–RR-03.
- **IPv4/IPv6:** per-family design is coherent; no parity test exists. Covered by M-06/M-09.
- **Persistence corruption:** append-only/FK/CAS design is coherent; current schema lacks it. Covered
  by M-06/RR-06.
- **Crash/uncertain outcomes:** target distinguishes `PENDING`, `UNCERTAIN`, `FAILED`, `COMPLETED`;
  no crash/reboot test exists. Covered by RR-05/M-09.
- **Logging leakage:** target requires bounded/sanitized audit; current controller audit fields and
  current error paths are not proven sanitized. Covered by I-08/RR-07.
- **Rollback/recovery:** documented gates, no host evidence. Covered by M-09.

## 12. Review J — Readiness Assessment

### 12.1 Outstanding blockers

| ID | Blocker | Severity | Why it blocks | Owner / acceptance authority |
|---|---|---|---|---|
| B-01 | N-01 socket-group assignment mechanism is unspecified. | High (blocks H-01) | No safe, specified way for server-created sockets to carry the client group; unsafe workarounds or startup failure. | Not named. |
| B-02 | N-02 rule schema conflicts with 2H.3 semantics. | High | The core policy contract is not frozen; host validation would test an ambiguous schema. | Not named. |
| B-03 | H-02/T-27/N-04 Docker boundary is not enforced or accepted. | High | Broker/manager Docker adapters remain; runtime adapter absent; rootful Docker is host-root-equivalent. | Not named. |
| B-04 | H-03 identity implementation remains request-based. | High | Current strict auth reads `peer_uid`/`peer_gid`; no real `SO_PEERCRED`; mock tests only. | Not named. |
| B-05 | H-04 manager-broker UDS is unimplemented; current HTTP auth is unsafe. | High | Header precedence, missing-token acceptance, negative allowlists, and stub client remain. | Not named. |
| B-06 | H-05/M-08 helper contract is still `2L.2G.3` with old operations/fields. | High/Medium | Target protocol/helper contract is not implementable against the current helper. | Not named. |
| B-07 | T-11/T-13 formal risk acceptance is absent. | High | No authority, criteria, evidence, or signed record for controller/helper compromise. | Not named. |
| B-08 | I-07–I-09 are incompletely propagated, classified, and owned. | Medium/High for I-09 | Standalone documents omit open validation/error/auth residual risks. | Not named. |
| B-09 | RR-01–RR-07 have no owners and no closure/acceptance evidence. | Medium | 2H.5 requires owners/plans; none are assigned. | Not named. |
| B-10 | M-01/M-06/M-07/M-08 implementation, migrations, and tests are absent. | Medium | Current schema/defaults/contracts differ from target; no migration evidence. | Not named. |
| B-11 | M-09 host/transport/Docker/firewall tests are unexecuted. | Medium (host gate) | No real UDS, `SO_PEERCRED`, helper, Docker, nftables/iptables, systemd, reboot, or rollback evidence. | Not named. |

### 12.2 Required closure evidence before host-validation planning is authorized

1. **N-01:** A selected socket-group mechanism, exact setgid/tmpfiles/supplementary-group policy,
   startup owner/group/mode assertions, and real cross-UID connect/deny evidence for all four edges.
2. **N-02:** One canonical rule and compiled schema covering direction, state, DNS, ICMP/ICMPv6, and
   owned-network CIDR bounds; updates to 2H.1/2H.3/2H.4/2H.5; negative and positive schema tests.
3. **N-03:** I-07, I-08, and I-09 added to 2H.1 §2.4, 2H.3 §1.1, 2H.4 §1.3, and 2H.4 final
   checklist; severity/impact/affected component/owner added; 2I.2 §13.1 corrected.
4. **H-02/T-27/N-04:** Runtime adapter implementation and fixed-operation evidence; removal or
   hard-disablement of broker/manager Docker paths; proof of no broker/manager Docker socket/group;
   RTA-01–RTA-06 results; formal T-27 acceptance or external isolation.
5. **H-03:** Real `SO_PEERCRED` adapter, identity removed from request schema/digest, caller
   verification flags removed, and spoof/wrong-UID/wrong-GID/missing-credential tests.
6. **H-04:** Real manager/broker UDS client and server, kernel peer verification on both sides, HTTP
   removed or hard-disabled in live paths, and header/token bypass tests.
7. **H-05/M-08:** Protocol library/envelope implementation, operation/error registry, `deadline_ms`,
   `ownership_reference`, `2L.2I.2` migration, helper contract update, and compatibility/negative tests.
8. **T-11/T-13:** Named acceptance authority, written acceptance criteria, host isolation/monitoring,
   compensating controls, blast-radius/recovery evidence, and `CTRL-04`/`CAP-05` results.
9. **RR-01–RR-07:** Owner assignment, closure evidence or formal acceptance, and tests/migrations.
10. **M-01/M-06/M-07/M-08:** Global idempotency migration, append-only/FK/per-family evidence schema,
    numeric service IDs/startup checks, and helper-contract migration.
11. **M-09:** Controlled, isolated, disposable host-validation plan with rollback, reboot, privilege,
    Docker, nftables/iptables, `DOCKER-USER`, IPv4/IPv6, and fail-closed evidence.
12. **No live authorization:** A separate explicit approval is required after the above evidence and
    a follow-up review; this phase does not grant it.

### 12.3 Decision 1 — Architecture documentation

**CONDITIONAL.** The documentation is substantially improved, but it is not complete, internally
consistent, or sufficiently evidenced for a PASS. N-01, N-02, and N-03 are open; H-01 and H-05 remain
open; H-02/H-03/H-04 are only partially resolved; T-27/T-11/T-13 are unaccepted; RR/I residuals lack
owners; and target controls are unimplemented and untested. The correct decision is CONDITIONAL, not
PASS.

### 12.4 Decision 2 — Controlled host-validation planning

**CONDITIONALLY READY.** Planning may begin only after the conditions in Section 12.2 are met,
especially closure of N-01/N-02, propagation of I-07–I-09, formal acceptance of T-27/T-11/T-13 or
removal of the underlying authority, and a reviewed rule contract. This is not permission to execute
host operations. If the conditions are not met, the status must be reported as **NOT READY**. A
"plan" that assumes the current HTTP, Docker, rule, or socket behavior is acceptable is not a valid
controlled host-validation plan.

### 12.5 Decision 3 — Live firewall integration

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.** This decision is unchanged by Phase
2L.2I.3. No live firewall, Docker, helper, systemd, host, cloud, or production operation is
authorized.

### 12.6 Recommended next phase

Recommend a documentation-only **Phase 2L.2I.4 — Targeted Design Closure and Host-Validation
Planning** with this order:

1. Resolve N-01 and N-02 and update all five 2H documents; correct the 2I.2 matrix for N-03.
2. Record formal acceptance for T-27/T-11/T-13 by a named authority, or remove the Docker
   authority and controller/helper residual from scope.
3. Assign owners and closure evidence for RR-01–RR-07 and I-07–I-09.
4. Re-review the revised architecture independently.
5. Only then prepare a controlled, isolated host-validation plan with explicit rollback and no
   production access.

Implementation, capability grants, socket creation, Docker execution, and firewall changes remain
out of scope for that planning phase unless separately authorized.

## 13. Required Deliverable

**Created document:** `docs/PHASE_2L_2I_3_INDEPENDENT_FOLLOWUP_ARCHITECTURE_SECURITY_REVIEW.md`.

No other file was created or modified by this review. The document contains the independently
verified findings, traceability matrix, T-27/T-11/T-13/RR/I assessments, cross-document consistency
review, new findings, readiness decisions, blockers, and closure evidence.

### 13.1 Deliverable coverage map

| Required item | Location in this document |
|---|---|
| 1. Executive summary | Objective — Executive summary |
| 2. Scope and limitations | Sections 1 and 2 |
| 3. Documents and code inspected | Section 2 |
| 4. Evidence methodology | Section 2.3 |
| 5. Previous review decision | Objective — Previous review decisions |
| 6. Five High findings reassessment | Section 3 |
| 7. Nine Medium findings reassessment | Section 4 |
| 8. F-01–F-14 traceability matrix | Section 5 |
| 9. T-27 reassessment | Section 6 |
| 10. T-11 and T-13 acceptance assessment | Section 7 |
| 11. RR-01–RR-07 assessment | Section 8 |
| 12. I-07–I-09 assessment | Section 9 |
| 13. Cross-document consistency | Section 10 |
| 14. New findings and attack paths | Section 11 |
| 15. Outstanding blockers | Section 12.1 |
| 16. Required closure evidence | Section 12.2 |
| 17. Readiness decisions | Section 12.3–12.5 |
| 18. Recommended next phase | Section 12.6 |
| 19. Final safety statement | Final Instruction |

## 14. Review Quality Requirements

This review was independent: it did not accept 2I.2's dispositions without checking the original
finding, the updated documents, and the current code/tests. It did not rename, combine, or delete any
finding identifier. It did not treat a design explanation as an implemented control, a mock test as
host evidence, or a risk-register entry as formal acceptance. It did not fabricate test results or
claim a host test ran.

Where evidence was unavailable, the document says **not verified**, **documentation-only**,
**mock-only**, **unimplemented**, or **unaccepted** rather than inferring success. The final decisions
are consistent with the evidence: architecture CONDITIONAL, host-validation planning CONDITIONALLY
READY only after conditions, and live integration NOT READY.

## 15. Repository Change Restrictions

**Baseline before this review.** The working tree was not clean. It already contained many modified
tracked files and many untracked files/directories unrelated to this phase; `docs/` itself was
untracked. The 2I.3 review document did not exist. These pre-existing changes were not reverted,
attributed to this review, or used as evidence of remediation.

**Changes made by this review.** Only the required review document was created. No application
source, test, runtime configuration, environment file, migration, socket, helper, privilege, Docker,
firewall, systemd, host, cloud, or production file was modified. No dependency was installed and no
test or host operation was executed.

**Post-write verification.** The working tree was checked after writing. The new file is
`docs/PHASE_2L_2I_3_INDEPENDENT_FOLLOWUP_ARCHITECTURE_SECURITY_REVIEW.md`. Because `docs/` is
untracked, Git reports the directory rather than the individual file; verification is by exact
filename and the post-write timestamp. The
post-write `git status --short` reported 26 modified tracked files and 43 untracked entries, in the
same pre-existing categories observed at baseline. No source/test/config file was modified by this
review. No unexpected change from this review was observed, and no pre-existing change was reverted.

## 16. Final Response Format

The final response must report:

- the architecture documentation decision;
- the controlled host-validation planning decision;
- the live firewall integration decision;
- the number of High findings closed, open, and partially resolved;
- the number of Medium findings closed, open, and partially resolved;
- the number of new findings by severity;
- the outstanding blockers or required closure evidence in summary form.

The final response must distinguish verified evidence, documentation-only claims,
implemented-but-untested behavior, mock-only tests, unimplemented architecture, and unaccepted risk.
It must not claim a PASS merely because the 2I.2 report says remediation is complete, and it must end
with the exact live-firewall statement below.

## Final Instruction

This review grants no implementation, host-validation, privileged-helper, Docker, firewall,
deployment, or production authorization. The architecture remains **CONDITIONAL**, controlled
host-validation planning is **CONDITIONALLY READY** only after the conditions in Section 12.2, and the
live gate remains closed.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**






