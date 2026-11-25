# Phase 2L.2J.2 — Controlled Host-Validation Plan

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Phase:** 2L.2J.2  
**Date:** 2026-11-14  
**Status:** **PLANNING DOCUMENT — NOT EXECUTED; NO HOST OPERATION AUTHORIZED**  
**Scope:** Future, separately authorized controlled host-validation specifications for UDS/socket permissions (N-01), kernel-authenticated identity (`SO_PEERCRED`), canonical `rule-schema-v1`, firewall backends (nftables primary, iptables fallback), persistence/idempotency/recovery/reconciliation, and host-validation entry criteria.

No real UDS transport, `SO_PEERCRED` integration, privileged helper, Linux capabilities, Docker runtime integration, nftables/iptables/DOCKER-USER operations, systemd deployment, host firewall changes, production infrastructure, or cloud deployment were implemented, configured, started, stopped, or executed by this phase. All cases below are **planned validation specifications**, not executed tests.

**Canonical sources:** 2H.1 §4.4.1 (`rule-schema-v1`), 2H.1 §5.1–5.3 (UDS/identity target), 2H.2 (threats/residuals), 2H.3 (backend/privilege), 2H.4 (persistence/recovery/deployment), 2H.5 (roadmap/test mapping), 2J.1 (gate register), 2J.3 (risk/authority), 2J.4 (rollback/evidence).

---

## 1. Execution preconditions (future phase only)

This plan may be executed only in a future, separately authorized phase after all Phase L entry criteria are satisfied. Mandatory environment constraints:
- Isolated disposable Linux test host/VM(s) with snapshots and no production network exposure.
- No production firewall dependency, no production sockets, no production credentials.
- Approved rollback procedure and documented host recovery access.
- Approved service accounts/groups, socket permission design, `SO_PEERCRED` design, `rule-schema-v1`, helper privilege boundary, Docker authority boundary, and backend test scope.
- Required approvals/dispositions per 2J.3 and 2J.1.

A plan alone does **not** make host validation ready.

---

## 2. Phase E — UDS socket and group-inheritance validation (N-01/H-01)

**Target (2H.1 §5.1–5.2):** `/run/flaghunt` `root:root 0755`; each edge directory server-owned, client-primary-group, mode `2750` with `S_ISGID`; socket server-owned, client-group, mode `0660`; kernel setgid-directory inheritance assigns client group; no `chown`/`chgrp`, no `CAP_CHOWN`, no server supplementary-group access, no insecure fallback; fail-closed verification; safe stale/live socket handling.

**Edges:** manager→broker `/run/flaghunt/manager-broker/broker.sock`, broker→controller `/run/flaghunt/broker-controller/controller.sock`, controller→helper `/run/flaghunt/controller-helper/helper.sock`, broker→runtime `/run/flaghunt/broker-runtime/runtime.sock` (runtime only if approved/in-scope).

### 2.1 Ownership and permissions

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| UDS-PERM-01 | Approved accounts/groups created; tmpfiles config installed on isolated host | Inspect `/run/flaghunt` and each edge directory before service start | `/run/flaghunt` `root:root 0755`; each edge dir exact server UID/GID owner:group and mode `2750` | `stat`/`ls -ldn`, tmpfiles config, host identity snapshot | All paths match target exactly | Any wrong path, owner, group, or mode |
| UDS-PERM-02 | Edge service started/bound | Inspect socket inode and directory after bind | Socket exists as socket type, owner server UID, group client GID, mode `0660`; directory remains `2750` with setgid | `stat`/`ls -ln`, service logs (bounded), startup verification output | Exact owner/group/mode/type; setgid preserved | Wrong type/owner/group/mode, symlink, or missing setgid |
| UDS-PERM-03 | Bound socket | Verify `S_ISGID` and no group/other write on directory; no setuid/setgid unexpected bits on socket | Directory has setgid bit and no unsafe write bits; socket `0660` only | `stat` format `%A/%a/%F/%U/%G`, bit checks | Bits exactly as specified | Missing setgid, group/other write, or unexpected bits |
| UDS-PERM-04 | Parent path created | Inspect parent traversal permissions from authorized client and unauthorized user contexts | Authorized client can traverse/connect as designed; unauthorized local user cannot traverse directory (`other ---`) | Access checks as authorized/unauthorized users, `namei -l` or equivalent | Traversal matches design; no unauthorized traversal | Unauthorized user can traverse/connect or authorized client blocked by design error |
| UDS-PERM-05 | Service running as server account | Confirm server process is not member of client supplementary group for socket access | Effective/supplementary groups do not include client group used for access; access still works via inherited socket group | `id`, `/proc/<pid>/status` groups, connection success | No supplementary-group workaround used | Server relies on added client group membership |

### 2.2 Group inheritance

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| UDS-GRP-01 | Authorized client in client primary/service group as designed | Authorized client connects and performs allowed handshake/operation | Connect succeeds; kernel peer identity later verifiable | Connection result, peer identity evidence, logs | Authorized client can connect | Authorized client denied despite correct config |
| UDS-GRP-02 | Unauthorized local user not in client group | Unauthorized user attempts connect | Connect fails due to filesystem/socket permissions; no insecure fallback | Command/result, errno, socket state | Access denied fail-closed | Connect succeeds |
| UDS-GRP-03 | Server account context | Server creates/binds socket | Socket group inherited from setgid directory equals client GID without `chown`/`chgrp` | Pre/post bind `stat`, strace/audit only if approved and non-invasive | Correct inherited group; no ownership-change syscall/path used | Wrong group, chown/chgrp used, or fallback permissions applied |
| UDS-GRP-04 | Client has unexpected supplementary group (not matching edge client group) or missing required group | Attempt connect/authorization as misconfigured identity | Filesystem/socket access denied or service rejects as unauthorized per design | Group config, connect/auth result | Misconfigured principal cannot gain access | Access granted incorrectly |
| UDS-GRP-05 | Incorrect group membership assigned to directory or socket (simulated config error before start, if safely possible in isolated test) | Start service with wrong group config | Service fails closed at startup/verification; no bind/readiness with wrong group | Startup logs, service state, socket absence/unchanged state | Fail-closed; no ready service | Service starts/binds with wrong group |

### 2.3 Lifecycle

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| UDS-LIFE-01 | No existing socket | Initial service start | Directory verified, temp-bind/atomic rename or equivalent safe bind performed, socket created with exact permissions, service ready | Startup logs, `stat`, readiness state | Safe creation and exact final state | Unsafe bind, wrong perms, or not ready |
| UDS-LIFE-02 | Service running with active socket | Controlled restart | Service stops cleanly, restart verifies path, stale/live handling follows design, new socket ready without unsafe deletion of unrelated paths | Stop/start logs, socket inode/time/stat, connection tests | Restart succeeds safely; no unsafe deletion | Restart fails unsafely, leaves wrong perms, or deletes live/unrelated inode unsafely |
| UDS-LIFE-03 | Existing stale socket file owned correctly but not live | Start service | Service detects stale socket via approved checks and replaces it safely (own-inode cleanup/temp-bind+rename as designed) | Pre/post state, probe evidence, logs | Stale socket replaced safely | Stale socket blocks startup incorrectly or removed without checks |
| UDS-LIFE-04 | Existing live socket serving valid peer | Start second instance/misconfigured start | New instance must not unlink or replace live socket unsafely; fail closed or refuse takeover per design | Both process states, socket inode continuity, logs | Live socket protected | Live socket replaced/unlinked |
| UDS-LIFE-05 | Socket creation failure induced (e.g. read-only/path precondition in isolated env, if safe) | Start service | Service fails closed, reports bounded error, does not become ready, no insecure fallback | Error/logs, readiness, filesystem state | Fail-closed | Service reports ready or falls back insecurely |
| UDS-LIFE-06 | Permission mismatch (directory/socket mode wrong) | Start or verify | Service rejects path and fails closed | Verification logs, state | Rejected | Accepted |
| UDS-LIFE-07 | Group mismatch | Start or verify | Service rejects and fails closed | Logs/state | Rejected | Accepted |
| UDS-LIFE-08 | Directory ownership mismatch | Start or verify | Service rejects and fails closed | Logs/state | Rejected | Accepted |

### 2.4 Failure behavior

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| UDS-FAIL-01 | Incorrect mode (e.g. `0750`, `0770`, `0666` cases as applicable) | Present incorrect mode and start/verify | Fail closed on incorrect mode | Config/state, logs | No ready service/socket acceptance | Any acceptance or auto-relaxation |
| UDS-FAIL-02 | Incorrect owner | Present incorrect owner and start/verify | Fail closed | Logs/state | Rejected | Accepted |
| UDS-FAIL-03 | Incorrect group | Present incorrect group and start/verify | Fail closed | Logs/state | Rejected | Accepted |
| UDS-FAIL-04 | Missing setgid bit (`0750`-like or other) | Present missing `S_ISGID` and start/verify | Fail closed; `0750` directory invalid for socket dir | `stat`, logs | Rejected | Accepted or treated as equivalent |
| UDS-FAIL-05 | Any mismatch condition | Observe remediation behavior | No automatic insecure permission fallback (`chmod 0666`, world/group-widening, CAP_CHOWN, shared group) | Code/config behavior, logs, resulting perms | No fallback observed | Any insecure fallback |
| UDS-FAIL-06 | Stale/non-owned/foreign socket candidate | Trigger cleanup path | No unsafe socket deletion; only approved own-inode stale cleanup after checks | Pre/post inode/path evidence, logs | Safe behavior only | Foreign/live/unchecked deletion |

---

## 3. Phase F — SO_PEERCRED and kernel-identity validation plan

**Target:** trusted identity source is kernel-authenticated UDS peer credentials (`SO_PEERCRED` on Linux) obtained at the transport boundary by the receiving service; authorization uses exact numeric UID/GID allowlists; caller-controlled identity headers/fields never override kernel identity.

### 3.1 Identity validation matrix

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| ID-01 | Authorized UID/GID client, correct socket | Send valid request | Credentials obtained, UID/GID match allowlist, operation authorized (subject to other checks) | Peer credential capture (bounded), auth decision, audit/result | Accepted with kernel identity attribution | Denied incorrectly or attributed to caller data |
| ID-02 | Unauthorized UID | Connect/send as wrong UID | Rejected at peer/authorization check | Credential evidence, rejection code/log | Rejected | Accepted |
| ID-03 | Authorized UID but unauthorized GID / unauthorized UID but authorized GID (as applicable) | Send request | Rejected unless policy explicitly allows exact pair | Evidence | Exact allowlist enforced | Partial match accepted incorrectly |
| ID-04 | Missing credentials (simulated transport/API failure in test harness, if possible) | Attempt authorization without valid credentials | Fail closed; reject | Error handling evidence | Rejected | Accepted or defaulted |
| ID-05 | Malformed identity data | Inject malformed credential representation at boundary test point (implementation test harness) | Fail closed; bounded error | Validation evidence | Rejected safely | Crash, bypass, or unsafe parse |
| ID-06 | Request includes caller-supplied identity headers (e.g. legacy HTTP/header fields) | Send request with spoofed headers over target transport | Headers ignored for identity; kernel identity used exclusively | Request payload, auth decision, logs | No privilege/identity change from headers | Header overrides or influences authorization |
| ID-07 | Request includes spoofed UID/GID fields in body | Send spoofed fields | Ignored/rejected per schema; kernel identity authoritative | Schema/auth evidence | No override | Override or acceptance |
| ID-08 | Identity mismatch (socket peer vs claimed/request context where applicable) | Present mismatch case | Reject | Evidence | Rejected | Accepted |
| ID-09 | Connection identity changes / reconnect as different principal | Reconnect and resend | Each connection/request authenticated from current peer credentials; no stale trust | Per-connection evidence | Correct per-connection identity | Stale or cached wrong identity used |
| ID-10 | Unauthorized socket client reaches network path but not allowed by UID/GID | Connect from non-allowlisted principal that can reach socket only in negative test setup | Rejected | Evidence | Rejected | Accepted |
| ID-11 | Repeated requests from authorized client | Send duplicates/retries | Each request independently authenticated; idempotency handled separately | Request/audit evidence | Consistent auth decisions | Auth bypass on repeat |
| ID-12 | Invalid operation by authorized identity | Send disallowed/unknown operation | Authorized identity but operation rejected by allowlist/schema | Authz evidence | Correct rejection | Operation allowed |
| ID-13 | Unexpected connection termination | Terminate mid-request/response | No partial trust, bounded timeout/cleanup, uncertain state handled safely | Logs/state | Safe cleanup; no false success | Hang, crash, or false success |

### 3.2 Identity handling specification (to verify)

| Aspect | Required specification |
|---|---|
| Trusted identity source | Kernel `SO_PEERCRED` (UID/GID/PID as available) for the connected UDS peer; PID informational only, not a stable authorization key. |
| Point where credentials are obtained | Immediately on accept/connect validation at transport boundary before trusting request payload for authorization decisions. |
| Authorization decision | Exact numeric UID/GID allowlist per edge and operation class; deny-by-default; no empty/wildcard/negative allowlists. |
| Rejection behavior | Fail closed with bounded error code; no backend/helper mutation; no fallback to headers/body identity. |
| Audit evidence | Record trusted UID/GID (and PID if available), edge/service, operation, request identifiers (bounded), decision, and bounded error/result; no raw secrets/payload dumps. |
| Timeout behavior | Connection/read/write/deadline enforced; timeout yields bounded failure/uncertain handling as designed, never inferred success. |
| Failure behavior | Missing/malformed/mismatched credentials, unauthorized peer, schema/operation violations, or transport errors close/abort safely and do not grant access. |

---

## 4. Phase G — Canonical `rule-schema-v1` validation plan

**Canonical source:** `docs/PHASE_2L_2H_1_REAL_TRANSPORT_TARGET_ARCHITECTURE.md` §4.4.1 (`rule-schema-v1`, protocol `2L.2I.2`). No competing schema may be created. Any discovered contradiction requires a new traced design decision, not an ad hoc schema change.

### 4.1 Schema correctness (SCHEMA-01–SCHEMA-05 and supporting cases)

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| SCHEMA-01 | Schema harness/implementation in scope | Submit rules with missing, duplicate, unknown, or extra fields; missing required top-level policy fields | Rejected (`INVALID_RULE`/schema error as mapped) | Request/response, validator logs | All non-canonical shapes rejected | Any acceptance or silent stripping/defaulting |
| SCHEMA-02 | Same | Submit missing/defaulted/implicit `family`, `direction`, `protocol`, ports, or action | Rejected; no inferred defaults | Evidence | No defaults inferred | Bidirectional/implicit/defaulted behavior accepted |
| SCHEMA-03 | Same | Submit invalid/wrong-type values: bad CIDR, host bits, `/0`, loopback/link-local/multicast/reserved/metadata/IPv4-mapped, out-of-scope CIDR, bad port types/ranges, out-of-order ports, invalid action, invalid booleans/floats/strings | Rejected with `INVALID_RULE`/`AMBIGUOUS_RULE` as appropriate; no masking/widening | Evidence | Canonical validation enforced | Normalization/widening or acceptance |
| SCHEMA-04 | Same | Validate canonical JSON serialization, preserved array order, `compiled` exact mirror rules, `compiled_rule_digest` and `canonical_policy_digest` equality, and read-back comparison | Accept only exact canonical match; reject digest/mirror/order mismatch | Canonical bytes/digests, read-back evidence | Deterministic canonical match required | Mismatch accepted |
| SCHEMA-05 | Same | Submit `icmp`, `icmpv6`, `any`, SCTP, and other unsupported protocols; all-port accept attempts | Rejected as `UNSUPPORTED_RULE`/`INVALID_RULE` per spec; no fallback | Evidence | Explicit rejection in v1 | Accepted or silently mapped |
| SCHEMA-06 | Same | IPv4/IPv6 field handling: valid IPv4/IPv6 CIDRs in-scope, family mismatch, required_families mismatch/unsorted/duplicate | Correct family handling or rejection | Evidence | Family rules enforced | Cross-family confusion accepted |
| SCHEMA-07 | Same | Normalization cases (IPv6 representation only where allowed), non-canonical text, leading zeroes, host bits | Representation normalized only where specified; meaning-changing cases rejected | Evidence | No semantic widening | Host bits masked or invalid text accepted |
| SCHEMA-08 | Same | Schema version compatibility: `2L.2I.2`, wrong version, missing version, legacy `2L.2G.3`/flat shapes | Only approved version accepted; legacy rejected | Evidence | No silent compatibility mode | Legacy accepted |
| SCHEMA-09 | Same | `INVALID_RULE` vs `UNSUPPORTED_RULE` vs `AMBIGUOUS_RULE` mapping | Correct bounded error classification | Error codes/responses | Distinction preserved | Generic/misclassified errors hiding cause unsafely |
| SCHEMA-10 | Same | Layer consistency: transport/broker/controller/helper/backend mapping/persistence/read-back interpret identical canonical policy | Same accepted/rejected result and same canonical meaning/digest across layers | Cross-layer traces/tests | No semantic drift | Any layer redefines/defaults/widens |

### 4.2 Protocol restrictions (v1)

Must remain explicit in all validation artifacts:
- TCP and UDP only.
- ICMP and ICMPv6 explicitly rejected/deferred in v1 (no implicit allow-all, no guessed type/code).
- State and DNS are constrained semantics, not additional rule-schema fields; DNS only explicit in-scope TCP/UDP port 53 rule as defined.

### 4.3 Legacy-schema rejection and read-back consistency

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| SCHEMA-LEG-01 | Legacy fixtures available | Submit pre-`rule-schema-v1`/`2L.2G.3`-style payloads | Rejected | Evidence | No legacy acceptance | Legacy accepted |
| SCHEMA-RB-01 | Install/verify path in scope | After successful apply (future), read back and compare canonical rules/digests | Read-back equals canonical intended state | Read-back output, digests, backend evidence | Exact match | Drift accepted as success |

---

## 5. Phase H — Firewall backend validation plan

### 5.1 nftables (primary)

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| NFT-01 | Isolated host, approved backend/capability scope | Validate table/chain ownership markers and namespace | Only owned Flaghunt table/chain/rules managed; ownership explicit | Ruleset snapshot, markers | Owned scope only | Foreign/unowned scope used |
| NFT-02 | Same | Install canonical policy | Rules installed exactly as mapped; read-back matches | Before/after ruleset, read-back, digests | Exact installed/read-back state | Drift or partial success reported as success |
| NFT-03 | Policy installed | Inspect/verify | Verification reads actual backend state and matches evidence | Verification output | Accurate verification | Stale/assumed state |
| NFT-04 | Policy installed | Remove/revoke | Only owned rules removed; absence confirmed by read-back | Ruleset/read-back | Owned removal only | Foreign rules touched or absence unconfirmed |
| NFT-05 | Policy installed | Duplicate install request | Idempotent/safe per contract; no duplicate unintended rules | Ruleset, operation result | Correct idempotent outcome | Duplication or conflict mishandled |
| NFT-06 | Controlled failure injection (future test harness) | Partial install/failure | No false success; uncertain/failed state recorded; reconciliation possible | State/evidence/logs | Fail-safe state | Confident ACTIVE on partial/unknown result |
| NFT-07 | Foreign rules present | Apply/remove Flaghunt operations | Foreign rules preserved | Full ruleset diff | No foreign modification/flush | Broad flush/delete or foreign impact |
| NFT-08 | Concurrent/retry scenarios | Repeat/concurrent operations as designed | Ownership/idempotency/reconciliation protect consistency | Operation traces, final state | Consistent final state | Race corruption or ownership breach |
| NFT-09 | Atomicity/read-back | Validate transactional/atomic behavior claimed by implementation | Post-operation state matches intended or safely failed state | Evidence | No ambiguous committed state | Partial ambiguous state misreported |

### 5.2 iptables fallback

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| IPT-01 | Fallback explicitly selected/approved | Backend selection logic | Fail-closed selection; documented fallback only when approved/supported | Selection evidence/logs | Correct backend choice | Silent unsafe fallback |
| IPT-02 | Docker/DOCKER-USER context in isolated lab | Validate DOCKER-USER interaction | Existing Docker/foreign chains preserved; only owned jumps/rules in approved locations | iptables/ip6tables snapshots | No foreign disruption | Docker/foreign rules damaged |
| IPT-03 | IPv4/IPv6 cases | Install/inspect/verify/remove for both families where required | Correct per-family behavior and parity as specified | v4/v6 rulesets, read-back | Per-family correctness | Family confusion or silent omission |
| IPT-04 | Duplicate/partial failure/removal | Repeat operations and inject failures | Safe idempotency, no false success, cleanup of owned artifacts only | Evidence | Safe outcomes | Duplication, false success, or foreign cleanup |
| IPT-05 | Ownership markers | Verify markers/tags | Only marked owned rules matched/removed | Ruleset evidence | Ownership enforced | Unmarked/broad matching |

### 5.3 Required security properties (all backends)

Validation must confirm: explicit ownership markers; no broad flush/delete; no foreign-rule removal; no arbitrary shell commands; fixed helper operations; input validation/canonical schema enforcement; fail-closed backend selection; verified post-operation state/read-back.

---

## 6. Phase I — Persistence, idempotency, and recovery validation plan

### 6.1 Durable intent and lifecycle

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| PER-01 | DB/persistence available | Begin install/revoke operation | Durable intent/state recorded before external side effect as designed | DB/state timeline, logs | Intent precedes external op | External op without durable intent |
| PER-02 | Operation progresses | Observe lifecycle transitions | Valid transitions only; ownership/version/correlation persisted | State records | Consistent lifecycle | Invalid transition or missing ownership |
| PER-03 | Evidence generated | Complete/verify operation | Evidence persisted append-only with required digests/ownership/family/result | Evidence rows/artifacts | Complete evidence | Missing/mutable/inconsistent evidence |

### 6.2 Idempotency

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| IDEM-01 | First request issued | Send initial valid request | Operation processed once per contract | Result/state | Correct initial outcome | Failure or duplicate side effect |
| IDEM-02 | Completed/known request | Repeat same idempotency key and same canonical payload/principal/operation/ownership | Safe replay of prior outcome (or equivalent safe response) without duplicate side effect | Responses, state, backend state | No duplicate mutation | Duplicate install/revoke/mutation |
| IDEM-03 | Existing key | Send same key with different payload/principal/operation/ownership | Conflict rejected | Error/state | Conflict detected | Wrong replay or overwrite |
| IDEM-04 | Concurrent identical requests | Issue concurrently | Single effective mutation; consistent outcome | Traces/state | Serialized/safe result | Double-apply/race corruption |
| IDEM-05 | After restart | Replay request | Durable idempotency decision preserved | Pre/post restart evidence | Correct replay/conflict | Lost idempotency causing duplicate mutation |
| IDEM-06 | Duplicate helper/backend response | Deliver duplicate response in test harness | Ignored or safely reconciled; no duplicate state corruption | Evidence | Safe handling | State corruption/false transition |
| IDEM-07 | Uncertain outcome | Simulate timeout/unknown result | State remains uncertain/pending reconciliation as designed; not falsely ACTIVE/REVOKED | State/evidence | Uncertain preserved | False terminal success |

### 6.3 Recovery

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| REC-01 | Crash before installation | Inject crash point | No backend mutation or intent reconciled safely; no false ACTIVE | State/backend | Safe non-applied state | False ACTIVE or orphaned mutation |
| REC-02 | Crash during installation | Inject crash | Uncertain/partial state recorded; reconciliation required before confident terminal state | State/evidence/backend | No false confidence | False ACTIVE/REVOKED |
| REC-03 | Crash after installation before confirmation | Inject crash | Reconciliation/read-back determines actual state before terminal confirmation | Evidence | Evidence-based resolution | Blind confirmation |
| REC-04 | Crash during revoke | Inject crash | Partial/uncertain revoke handled safely | State/backend | No false REVOKED | False REVOKED with rules still present |
| REC-05 | Crash after revoke before confirmation | Inject crash | Read-back confirms absence before REVOKED | Evidence | Confirmed absence | Blind confirmation |
| REC-06 | Database unavailable | Make DB unavailable in controlled test | Fail closed; no unsafe mutation or false success; bounded error | Behavior/logs | Safe failure | Mutation without durable record or false success |
| REC-07 | Corrupted state/evidence | Introduce controlled corruption case | Detected, quarantined/fail-closed, escalated; no auto-trust | Detection evidence | Safe handling | Corruption trusted |
| REC-08 | Incomplete reconciliation | Interrupt reconciliation | Resumable/retryable without unsafe side effects | State/logs | Safe retry | Duplicate cleanup/mutation or stuck unsafe state |
| REC-09 | Unknown external state | Backend/read-back inconclusive | Mark uncertain/unknown as designed; escalate; no confident terminal state | State/evidence | Uncertain preserved | Guessed terminal state |

### 6.4 Reconciliation

| Test ID | Preconditions | Procedure | Expected result | Evidence to collect | Pass criteria | Failure criteria |
|---|---|---|---|---|---|---|
| RECON-01 | Owned policy exists and matches | Run reconciliation | State confirmed/healthy | State/read-back | Match confirmed | False drift reported |
| RECON-02 | Owned policy missing | Run reconciliation | Drift detected; safe recovery action per policy (reinstall only if explicitly safe/authorized) or uncertain/escalation | Evidence | Correct detection/action | Silent ignore or unsafe action |
| RECON-03 | Foreign policy/rule exists | Run reconciliation | Foreign rule reported/preserved; never adopted or deleted as owned | Full ruleset/state | Preserved | Foreign rule modified/deleted/adopted |
| RECON-04 | Partially installed policy | Run reconciliation | Partial state identified; no false ACTIVE; remediation path defined | Per-family/state evidence | Accurate partial handling | False ACTIVE |
| RECON-05 | Mismatched digest/read-back | Run reconciliation | Mismatch detected; not treated as verified | Digests/read-back | Rejected/unverified | Mismatch accepted |
| RECON-06 | Unknown operation outcome | Reconcile | Remains/marked uncertain until evidence sufficient | State | No false terminal state | Confident guess |
| RECON-07 | Reconciliation retry | Retry after transient failure | Idempotent/safe retry; no duplicate unsafe actions | Evidence | Safe retry | Compounding side effects |

### 6.5 Required behavior summary

For every uncertain external operation: **never represent as confidently `ACTIVE` or `REVOKED` without sufficient evidence**. Each test case record must define expected lifecycle state, durable intent, evidence requirements, recovery decision, retry conditions, and final disposition.

---

## 7. Phase L — Controlled host-validation entry criteria checklist

| Requirement ID | Requirement | Required evidence | Approval authority | Current status | Blocking dependency |
|---|---|---|---|---|---|
| HV-EC-01 | Explicit project-owner approval for isolated host-validation phase | Signed/recorded approval document referencing scope, host, dates, and stop conditions | Project owner | BLOCKED | No approval recorded |
| HV-EC-02 | Explicit security approval | Security review/approval record for plan, scope, and residuals | Security authority/reviewer | BLOCKED | No approval recorded; 2J.3/2J.5 review pending acceptance |
| HV-EC-03 | Approved isolated Linux test host (pinned OS/kernel) | Host inventory, OS/kernel/version record, isolation proof, disposable/snapshot capability | Platform/infra owner + security | BLOCKED | No host approved/provisioned |
| HV-EC-04 | No production network exposure | Network isolation diagram/config evidence; firewall/routing verification plan | Platform/network owner + security | BLOCKED | No isolated host/network evidence |
| HV-EC-05 | No production firewall dependency | Confirmation host firewall state independent of production; rollback baseline | Platform owner + security | BLOCKED | No host evidence |
| HV-EC-06 | Documented host recovery access | Console/recovery access procedure, break-glass controls, tested access path plan | Platform/infra owner | BLOCKED | No host/recovery evidence |
| HV-EC-07 | Approved rollback procedure | 2J.4 rollback plan reviewed/approved for target host | Platform owner + security + project owner | BLOCKED | No approval recorded |
| HV-EC-08 | Defined service accounts and groups | UID/GID allocation/inventory, group model, no-conflict verification | Platform/deployment owner | BLOCKED | M-07 deployment assertions not executed |
| HV-EC-09 | Approved socket permission design | 2H.1 §5.1/N-01 design approval record for target host | Architecture/security/deployment owners | BLOCKED | Formal approval not recorded |
| HV-EC-10 | Approved `SO_PEERCRED` identity design | Identity design approval and test scope | Architecture/security owners | BLOCKED | Formal approval not recorded; H-03/H-04 implementation pending |
| HV-EC-11 | Approved canonical `rule-schema-v1` | 2H.1 §4.4.1 approval record | Architecture/security/schema owners | BLOCKED | Formal approval not recorded |
| HV-EC-12 | Approved helper privilege boundary | Capability/hardening boundary approval (`CAP_NET_ADMIN` scope, no shell, fixed ops) | Security/platform owners | BLOCKED | Formal approval not recorded; T-13 open |
| HV-EC-13 | Approved Docker authority boundary | Strict runtime authority model approval; broker/manager no-Docker enforcement plan | Architecture/security/runtime owners | BLOCKED | N-04 open; T-27 not accepted/mitigated |
| HV-EC-14 | Approved nftables and iptables test scope | Backend scope, DOCKER-USER/fallback constraints, non-disruption rules | Security/platform owners | BLOCKED | No approval recorded; M-09 open |
| HV-EC-15 | Approved persistence and recovery strategy | Durable intent/idempotency/reconciliation/uncertain-state strategy approval | Architecture/persistence/security owners | BLOCKED | Implementation/migration evidence absent |
| HV-EC-16 | Required risk acceptance for T-11, T-13, T-27 or documented mitigation | Signed acceptance records or mitigation-closure evidence per 2J.3 | Project owner + security authority | BLOCKED | `OPEN — ACCEPTANCE REQUIRED` / open residuals |
| HV-EC-17 | All required High-severity security gates resolved or explicitly dispositioned by authorized reviewers | 2J.1/2J.5 disposition records for H-01–H-05 and blocking High risks | Security authority + engineering owners | BLOCKED | No verified closures/formal dispositions |
| HV-EC-18 | RR-01–RR-07 closure or formal disposition | Closure evidence or authorized disposition records | Engineering owners + security authority | BLOCKED | All open |
| HV-EC-19 | Independent review of final test plan | Reviewed 2J.2/2J.4/2J.5 package with findings addressed/dispositioned | Independent security reviewer | BLOCKED | Review not completed/accepted |
| HV-EC-20 | Evidence and rollback procedures ready | Approved 2J.4 procedures, evidence templates/storage, reviewer assignment | Platform/security owners | BLOCKED | Procedures unapproved/unexercised |

**Entry decision:** **NOT READY**. No criterion is satisfied by plan existence alone; all criteria are currently blocked pending approvals, implementation, or evidence.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**