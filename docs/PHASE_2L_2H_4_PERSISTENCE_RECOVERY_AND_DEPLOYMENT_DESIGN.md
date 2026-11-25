# Phase 2L.2H.4 — Persistence, Recovery, and Deployment Design

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Phase:** 2L.2H.4  
**Date:** 2026-11-13  
**Status:** **DESIGN ONLY — NO IMPLEMENTATION AUTHORIZED**  
**Integration gate:** **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
**Remediation:** 2L.2I.2 documentation-only overlay, amended by 2L.2I.4; design decisions below
control where they conflict with earlier text. Persistence stores and reuses the canonical
`rule-schema-v1` from 2H.1 Section 4.4.1; it does not define a second rule language. No runtime
control is implemented.

This document designs durable controller state, crash/restart recovery, database migration, and a
future Ubuntu deployment model. It does not create a database, run a migration, create users or
directories, install services, grant capabilities, or change any host or firewall state.

> **Current versus future.** The current controller uses SQLite for mock ownership, lifecycle,
> idempotency, audit, and evidence. That schema is real code, but it has only been exercised with
> the mock backend and local tests. The schema extensions, recovery semantics, service layout, and
> operational controls below are proposals. No target control is implemented by this document.

---

## 1. Current persistence review

### 1.1 Current controller database

The current `ControllerOwnershipStore` opens a SQLite database (default under the broker data
directory or `FIREWALL_CONTROLLER_DB_PATH`) and enables WAL mode. Its current tables are:

| Table | Current purpose | Current limitations relevant to 2H |
|---|---|---|
| `controller_ownership` | One row per policy/version with ownership, state, lifecycle version, rule IDs, single `address_family`, reconciliation status | No per-family state; no schema version; no DB-level digest/type checks; single-family evidence |
| `controller_lifecycle_history` | State-transition history with request/operation IDs | No FK; IDs are app-validated only; history retention policy not designed |
| `controller_idempotency` | Key + operation + request digest + PENDING/COMPLETED status + response/recovery metadata | No real helper/backend replay boundary; no `FAILED`/`UNCERTAIN` state distinction; known ID/digest residuals |
| `controller_audit` | Local structured audit rows | Mock audit sink; no independent helper audit/retention/tamper model |
| `controller_evidence` | Controller verification evidence, single address family, rule IDs | No helper identity, backend transaction/read-back digest, per-family rows, or evidence-schema version |

The current unique index on `(policy_id, policy_version)` and lifecycle `CASE`/CAS handling are
real controls. They are not proof of real backend correctness, multi-family atomicity, or
crash-safe helper integration.

### 1.2 Current broker persistence

The broker has separate persistent ownership/network/audit storage and mocked Docker operations.
It does not currently write controller ownership/evidence. That separation must remain: the
broker is not a second controller database.

### 1.3 Current known residuals

The following remain open and are carried into the target design (full register in 2H.2):

- `request_id`, `operation_id`, and `idempotency_key` canonical validation scope;
- non-SQLite-range/wrong-type `policy_version`;
- incomplete full-scan reconciliation;
- I-3.9-01: missing digest database `CHECK`;
- I-3.9-03: retained exception `__context__`.

The informational residuals I-07, I-08, and I-09 are also carried here with their exact meaning:

- **I-07 — Broader identifier/field scope.** Affected: controller ownership/evidence fields,
  idempotency records, and recovery scans. Impact: fields or aliases outside the canonical gate can
  create ambiguous ownership/idempotency state. Mitigation: universal canonical validation and
  migration constraints. Owner: 2H.4 persistence workstream. Status: **OPEN — carried**. Closure:
  every persisted/read field uses one canonical rule with negative migration/recovery tests.
- **I-08 — Raw `BrokerDBError` on non-failure paths.** Affected: controller/broker SQLite reads and
  writes, including success and initial-intent paths. Impact: SQLite text, paths, or exception
  context can leak through errors or evidence. Mitigation: sanitized error mapper at every
  persistence boundary. Owner: persistence workstream. Status: **OPEN — carried**. Closure: no raw
  DB text reaches caller, audit, or evidence; tests cover non-failure paths.
- **I-09 — `strict_auth=False` legacy footgun.** Affected: controller construction and any recovery
  tool that constructs the service. Impact: a live/mock auth switch can bypass trusted identity.
  Mitigation: remove it from production construction; require `TrustedPeerIdentity`; test-only
  provider outside production imports. Owner: controller workstream. Status: **OPEN — carried**.
  Closure: deployment/import test proves mock auth cannot be selected in a live path.

No migration or recovery design in this document silently closes them.

---

## 2. Target persistence model

### 2.1 Database separation

| Store | Owner | Contents | Must not contain |
|---|---|---|---|
| Broker SQLite | Broker | Broker resource ownership, network ownership, broker audit, broker recovery state | Controller lifecycle/evidence authority |
| Controller SQLite | Controller | Firewall ownership, lifecycle, idempotency, evidence, controller audit, reconciliation state | Broker-wide resource state; helper credentials |
| Helper audit/log | Helper | Sanitized operation/read-back/error audit | Controller DB writes; secrets; raw request bodies |
| Operator backup | Deployment | Consistent DB snapshots, evidence archives, restore metadata | Live writable state |

Only the controller writes controller ownership/evidence. The helper has no direct database access.
A shared database would collapse the controller/helper trust boundary and is not approved.

### 2.2 Proposed schema extensions

All names are proposals, not implemented migrations.

| Table | Purpose | Proposed key fields/constraints |
|---|---|---|
| `controller_schema_migrations` | Track applied schema versions/checksums | `version INTEGER PRIMARY KEY`, `applied_at`, `checksum`, `status` |
| `controller_meta` | Controller identity, schema/backend version, reconciliation lease | key/value with bounded canonical values; no secrets |
| `controller_ownership` | Aggregate ownership/lifecycle authority | Existing fields plus `schema_version`, `rule_schema_version`, `required_families_json`, `canonical_policy_json`, `owner_marker_hash`, `backend`, `last_error_code`, `reconciliation_status`, `unknown_reason`; canonical digest/version checks; `lifecycle_version` CAS; `CHECK` on digest/version/state; no stored `PARTIALLY_*` |
| `controller_family_state` | Per-family install/revoke state and evidence reference | `(ownership_reference, family)` PK; FK to ownership `ON DELETE RESTRICT`; state enum; `desired_state`; `observed_digest`; `last_readback_at`; `backend_transaction_id`; `rule_handles_json`; `CHECK` family/state/digest; no success without read-back |
| `controller_evidence` | Immutable per-family verification evidence | `evidence_id` PK; FK to `controller_family_state(ownership_reference, family)` `ON DELETE RESTRICT`; ownership/policy/version/digest/family; ruleset/read-back digest; rule handles; helper UID/GID/PID audit data; helper version; backend/transaction ID; request/operation/idempotency IDs; verification result/time; evidence schema version; **append-only triggers; no update/delete** |
| `controller_idempotency` | Durable request outcome/recovery | `idempotency_key` **global PK/unique**; operation, canonical request digest, authenticated principal, ownership binding, `status` (`PENDING`, `COMPLETED`, `FAILED`, `UNCERTAIN`), `recovery_state`, `attempt_count`, `last_error_code`; canonical key/digest checks |
| `controller_operation_journal` | Optional operation-attempt journal for audit/recovery | Operation/attempt row, operation type, ownership, backend action, start/end, result/error code; bounded, append-only; no raw backend text |
| `controller_reconciliation_state` | Single-flight scan/lease and progress | Lease owner, expiry, scan generation, last complete scan, cursor/batch, non-terminal count |
| `controller_audit` | Durable controller audit | Existing plus event schema/version, sanitized result/error code, evidence/operation references; no secret/raw bodies |

The operation journal is optional if existing lifecycle/idempotency tables are sufficient. It must
not become a second source of truth for ownership.

**Canonical policy persistence (N-02).** `canonical_policy_json` stores the exact canonical JSON
array from `rule-schema-v1` (2H.1 Section 4.4.1) together with `rule_schema_version = "rule-schema-v1"`,
`required_families_json`, and `canonical_policy_digest`/`compiled_rule_digest`. It is not a
backend-specific projection and is not reconstructed from a lossy summary. The controller validates
the canonical schema before insert, checks the digest and family set, and passes the same canonical
rules to the helper; the helper revalidates the same fields and compares the read-back digest. A
migration that cannot store or verify the canonical JSON is not approved. If a deployment stores the
blob in a separate controller-only object store instead of a column, the content and digest are
identical and the reference is immutable; that storage choice does not create a second schema.
No layer may normalize a CIDR, add a direction, add a protocol, or widen a port during persistence
or recovery.

### 2.3 Per-family state model

The current single `address_family` column cannot represent a dual-stack policy safely. The target
uses `controller_family_state` rows for each required family:

| Family state | Meaning |
|---|---|
| `PENDING` | Desired but not attempted/confirmed |
| `INSTALLING` | Intent exists; backend may be changing |
| `INSTALLED` | Backend write returned, not yet independently verified |
| `VERIFIED` | Exact read-back matched; evidence persisted |
| `REVOKING` | Removal intent exists; backend may be changing |
| `REVOKED` | Absence independently verified |
| `FAILED` | Known failure; no success |
| `UNKNOWN` | Ambiguous/corrupt state; must be quarantined/reconciled |

Aggregate rules:

- `ACTIVE` only if every required family is `VERIFIED`/active for the exact policy digest and
  ownership generation.
- `REVOKED` only if every required family is `REVOKED` with absence evidence.
- Any failed/unknown required family prevents dual-stack success and requires
  cleanup/reconciliation.
- A single-family policy is allowed only with explicit approved policy semantics and evidence;
  it must not silently pass as dual-stack.
- Legacy rows without per-family state are migrated to `UNKNOWN`, not auto-promoted.

### 2.4 Lifecycle states and transitions

Current states in the mock controller include `REQUESTED`, `VALIDATING`, `INSTALLING`, `VERIFYING`,
`VERIFIED`, `ACTIVE`, `REVOKING`, `CLEANUP_PENDING`, `FAILED`, `REVOKED`, and `ORPHANED`. The
target keeps the evidence-gated model. **`PARTIALLY_INSTALLED` and `PARTIALLY_REVOKED` are derived
API statuses from per-family rows, not persisted aggregate lifecycle values.** This removes the
earlier ambiguity while preserving partial visibility:

```text
REQUESTED -> VALIDATING -> INSTALLING -> VERIFYING -> VERIFIED -> ACTIVE
                              |              |
                              +-> FAILED / CLEANUP_PENDING / UNKNOWN

ACTIVE -> REVOKING -> CLEANUP_PENDING -> REVOKED
              |
              +-> FAILED / UNKNOWN
```

Per-family rows carry the truth: one family may be `VERIFIED` and another `FAILED` while the
aggregate remains `INSTALLING`/`FAILED`/`CLEANUP_PENDING`. A read model may expose
`PARTIALLY_INSTALLED`/`PARTIALLY_REVOKED`, but those strings are never written to
`controller_ownership.installation_state`.

All transitions use compare-and-set on lifecycle version and a durable reason. No transition to
`ACTIVE` or `REVOKED` is allowed solely because a helper call returned "ok"; controller read-back
and evidence are mandatory. The aggregate transition and family/evidence writes occur in one
`BEGIN IMMEDIATE` transaction; a trigger/guard rejects `ACTIVE` without all required families
`VERIFIED` and `REVOKED` without all required families `REVOKED` with absence evidence.

### 2.5 Durable intent and evidence

Install:

1. Validate request, authoritative ownership, canonical fields, family/digest.
2. Persist `INSTALLING`/intent and idempotency `PENDING` before calling the helper.
3. Call the helper with bounded deadline.
4. Treat missing/ambiguous response as uncertain; do not promote.
5. Read back through helper inspect/verify.
6. Persist per-family evidence only after exact match.
7. Promote `ACTIVE` only when all required families are verified.
8. Mark idempotency `COMPLETED` only with the final state/evidence reference.

Revoke:

1. Persist `REVOKING`/non-active intent and idempotency `PENDING` before mutation.
2. Call helper to remove only owned rules.
3. Read back each required family; persist absence evidence.
4. Promote `REVOKED` only after all required families are absent; otherwise remain
   `REVOKING`/`CLEANUP_PENDING` (partial status is derived, not stored).

Evidence is append-only and controller-generated. A caller cannot submit evidence as a trusted
fact. The helper's returned read-back data is input to controller validation, not evidence by
itself.

Enforcement (design, not implemented):

- `PRAGMA foreign_keys=ON`; `controller_family_state` and `controller_evidence` reference
  `controller_ownership(ownership_reference)` with `ON DELETE RESTRICT`.
- `BEFORE UPDATE` and `BEFORE DELETE` triggers on `controller_evidence` raise `ABORT`; corrections
  are new evidence rows that reference the superseded evidence, never in-place mutation.
- A transaction updates family state and aggregate state together with lifecycle CAS. A guard
  rejects an aggregate `ACTIVE` unless every required family is `VERIFIED` for the same policy
  digest/ownership generation, and rejects `REVOKED` unless every required family is `REVOKED` with
  absence evidence.
- Evidence rows include canonical policy/read-back digests, backend transaction ID, helper
  UID/GID/PID (audit only), request/operation/idempotency IDs, and verification time. Missing or
  mismatched fields prevent promotion.
- Inconsistent rows are quarantined and reported; they are never repaired by updating evidence or
  inferring success.

---

## 3. Idempotency, concurrency, and authority

### 3.1 Idempotency

**Decision (2L.2I.2): global-per-receiver idempotency key scope.** The durable key is
`idempotency_key` alone, unique across all operations at that receiver; it is not scoped to an
operation type. The row also binds the operation, canonical request digest, authenticated
principal, and ownership. This matches the frozen wire contract and removes the prior PK
contradiction.

- Key identity: global `idempotency_key` plus canonical request digest, operation, authenticated
  principal, and ownership binding.
- Same key + same canonical request/principal may return the prior outcome only if it is safe and
  complete.
- Same key + different operation/digest/ownership/principal is a conflict, never a cached success.
- `PENDING` from a crash is not success; it is reconciled.
- `UNCERTAIN`/`FAILED` must be distinguishable from `COMPLETED`.
- Helper replay cache is bounded and not durable; the controller database remains authoritative.
- Keys and IDs are canonical strings; booleans, numbers, lists, control characters, empty, or
  oversized values are rejected.

### 3.2 Concurrency

- Target deployment: **one active controller per host**. Multi-controller/HA is not designed.
- SQLite WAL + `BEGIN IMMEDIATE` + unique constraints + lifecycle CAS serialize writes.
- Per-ownership operations are serialized; conflicting install/revoke does not run in parallel.
- The helper serializes per ownership/marker as defense in depth.
- A reconciliation scan uses a single-flight lease stored in `controller_meta`/reconciliation
  state; a second scan waits or exits, not duplicates cleanup.
- SQLite busy/locked is a bounded retry/fail-closed condition, not a reason to proceed without
  durable state.
- Two OS processes accidentally sharing the DB are unsupported; a second writer must not be
  deployed.

### 3.3 Unknown and corrupt states

- Unknown `installation_state`/family state is quarantined; no transition, no deletion, no
  auto-adoption.
- Ownership/digest mismatch is a conflict; do not "repair" by rewriting ownership.
- A record with missing evidence is not active, even if rules happen to exist.
- A rule/chain that exists but is not owned is reported as unknown drift; the helper must not
  delete it without an approved cleanup decision.
- Operator recovery is audited and requires a documented approval path.

---

## 4. Crash and restart recovery

### 4.1 Crash-boundary matrix

| Crash point | Durable state | Possible backend state | Recovery action | Forbidden inference |
|---|---|---|---|---|
| Before intent commit | None | Unchanged | No side effect; request may be retried with same key | Do not assume a helper call happened |
| After intent, before helper call | Intent/PENDING | Unchanged | Revalidate; safe retry; no success | Do not mark active |
| During helper request, no response | Intent/PENDING | Unknown/partial | Treat uncertain; inspect owned state; idempotent retry only after read-back | Do not blind-resend or mark success |
| Helper response received, before evidence | Intent/PENDING | Changed | Independently read back; evidence only on exact match | Do not trust the response alone |
| Evidence stored, before state promotion | Evidence exists; state old | Changed | Reconcile state from evidence/read-back with CAS | Do not duplicate mutation |
| State promoted, before idempotency completion | Terminal state + evidence | Changed | Complete idempotency only if state/evidence consistent | Do not rerun mutation |
| Helper crash after mutation | Intent/PENDING | Partial/unknown | Restart/liveness; inspect; cleanup/retry | Do not assume failure or success |
| Controller crash | Durable intent/state | Possibly changed | Startup full-scan reconciliation; inspect; CAS | Do not auto-adopt unknown rules |
| DB corruption/lock failure | Unreliable state | Unknown | Fail closed; quarantine/restore; reconcile | Do not auto-repair or continue writes |
| Host reboot | DB persistent; kernel rules may be absent | Unknown/partial | Start services; integrity check; reconcile all owned/non-terminal | Do not assume rules survived |

### 4.2 Startup reconciliation

On every controller start:

1. Verify DB file, WAL/SHM ownership/mode and SQLite quick check; fail closed on corruption.
2. Load schema version and verify compatibility.
3. Acquire the single-flight reconciliation lease (bounded, expiring).
4. Scan **all** owned records in batches, not only `PENDING` rows:
   - non-terminal lifecycle states;
   - pending/uncertain idempotency;
   - active records with stale/missing evidence;
   - records with partial/unknown family state;
   - legacy records marked for migration review.
5. For each, inspect only the owned backend object through the helper; compare ownership marker,
   family, digest, and evidence.
6. Decide: reinstall owned active intent, retry cleanup, quarantine unknown, or report drift.
7. Persist result/evidence/reason with CAS; never auto-promote without exact read-back.
8. Release the lease; metrics report duration, backlog, uncertainty, and drift.

A full scan must not enumerate/deleting all host rules. It reconciles controller-owned records and
reports unknown state. Full-host firewall ownership remains outside this controller.

### 4.3 Revocation/recovery priority

- Revocation and cleanup take priority over new installs when the host is uncertain.
- A policy in `REVOKING`/`CLEANUP_PENDING` must not be treated as active for new traffic.
- If the helper cannot confirm absence, the controller reports a security-relevant uncertainty and
  escalates; it does not claim revocation.
- Operator-approved emergency cleanup must preserve unrelated host/Docker rules and audit.

---

## 5. Database migration and integrity

### 5.1 Migration principles

- Forward-only migrations tracked by `controller_schema_migrations`; no ad hoc schema edits.
- Back up the DB and verify the backup before migration.
- Migrate on a copy first; production migration requires an approved change window.
- Use SQLite table rebuilds for new `CHECK`/type constraints; preserve data and indexes.
- Do not silently coerce/backfill unsafe values. Invalid legacy rows are quarantined for review.
- No destructive migration/table drop without an explicit approved retention decision.
- Rollback is by restoring the pre-migration backup and previous binaries; no untested down
  migration.
- Migration and helper/controller versions must be compatibility-checked; a helper must not serve
  a schema it does not understand.
- After migration: integrity check, row counts, uniqueness, evidence/ownership backfill checks,
  and a reconciliation dry run.

### 5.2 Specific schema hardening

| Residual/requirement | Proposed migration/control |
|---|---|
| `request_id` canonical scope (RR-01) | App-level canonical validation plus optional bounded-length/character `CHECK`; validate on every read/write path |
| `operation_id` canonical scope (RR-02) | Canonical validation, operation binding, optional `CHECK`/index; audit correlation |
| `idempotency_key` canonical scope (RR-03) | Canonical validation + **global** uniqueness/digest/principal binding; rebuild PK to `idempotency_key`; detect duplicates before backfill; no unsafe backfill |
| `policy_version` range/type (RR-04) | App rejects bool/float/string/overflow; SQLite `CHECK` for integer/non-negative signed-64 range; quarantine bad legacy rows |
| Digest `CHECK` (RR-06 / I-3.9-01) | Add canonical 64-hex SHA-256 `CHECK` to digest-bearing tables after verifying legacy rows; fail closed on invalid read |
| Evidence completeness | Per-family evidence table with FK; **append-only update/delete triggers**; no evidence promotion from a write response; corrections are new rows |
| Aggregate invariants (F-11) | Transaction + CAS + guard/trigger: `ACTIVE` only when all required families `VERIFIED`; `REVOKED` only when all required families `REVOKED` with absence evidence; `PARTIALLY_*` are derived, not stored |
| Foreign keys | `PRAGMA foreign_keys=ON`; ownership/family/evidence FKs with `ON DELETE RESTRICT`; orphan checks |
| Single-family legacy evidence | Backfill to `family=UNKNOWN`/legacy scope, not auto-verified; require reconciliation |
| Idempotency status | Add `FAILED`/`UNCERTAIN` semantics; preserve existing PENDING/COMPLETED rows; no silent success |
| Schema version | Add `controller_schema_migrations` and compatibility checks before serving |

### 5.3 Integrity checks

- `PRAGMA quick_check` at startup; full `integrity_check` on backup/restore and scheduled
  maintenance.
- Verify WAL/SHM ownership/mode; checkpoint under controlled conditions.
- Detect disk-full/read-only conditions and fail closed.
- Audit gaps, row count anomalies, duplicate ownership, missing evidence, and orphan history rows.
- Corrupt DB: stop writes, quarantine/copy, restore approved backup, reconcile, investigate; never
  auto-repair evidence/ownership.

---

## 6. Future Ubuntu deployment model

### 6.1 Supported platform assumptions

Target is Linux-only, with an Ubuntu LTS host using systemd, Unix domain sockets, `SO_PEERCRED`,
nftables (primary), and rootful Docker with a validated firewall integration. Ubuntu 22.04 and
24.04 LTS are candidate baselines; exact kernel, nftables, Docker, and Python/runtime versions
must be pinned and validated in the host lab. A host that does not meet the prerequisites must
fail the deployment gate, not fall back silently to unsafe behavior.

### 6.2 Service users and groups (proposed)

| User/group | Numeric UID/GID (proposed) | Purpose | Privilege |
|---|---|---|---|
| `flaghunt-manager` | `4600/4600` | Manager service | No capabilities, no helper/controller DB, no Docker |
| `flaghunt-broker` | `4601/4601` | Restricted broker | No capabilities; no firewall mutation; **no Docker socket/group/API** |
| `flaghunt-fwcontroller` | `4602/4602` | Controller service | No capabilities; controller DB read/write |
| `flaghunt-fwhelper` | `4603/4603` | Privileged helper | `CAP_NET_ADMIN` only; no login shell; no DB |
| `flaghunt-runtime` | `4604/4604` | Runtime adapter | No capabilities; rootful Docker socket access (host-root-equivalent) |
| `flaghunt-monitor` | `4605/4605` | Read-only metrics/log access | No capability; no DB writes |

The numeric IDs are proposed allocations; deployment must verify they are unused, allocate them
consistently, and record them in the host inventory. Each service's primary group is its own
service group. Group membership is for socket/filesystem access only; no service trusts a claimed
group as identity. The server is **not** added to the client's group; socket access is obtained by
kernel setgid-directory inheritance and the `0660` socket group, not by server supplementary-group
membership (2H.1 Section 5.1). `flaghunt-runtime` is the only user in the Docker socket group; the
broker, manager, controller, helper, and monitor must not be in it. Supplementary groups are not
used for UDS access and are never accepted as `SO_PEERCRED` authority.

### 6.3 Socket and runtime directory layout (proposed)

**Decision (2L.2I.2, completed by 2L.2I.4): direct-bind, server-owned `2750` setgid directory,
client group non-write access.** The server must own the directory to create/replace/remove its
socket; the client must not have directory write. The setgid bit makes a server-created socket
inherit the client group without `chown`/`chgrp`, `CAP_CHOWN`, or server membership in the client
group. `systemd-tmpfiles` creates the exact owner/group/mode at boot. Socket activation is not used
for these edges. A `0750` directory without setgid is invalid and fails startup, not a weaker
fallback.

| Path | Owner:group | Mode | Purpose |
|---|---|---|---|
| `/run/flaghunt` | `root:root` | 0755 | Parent runtime root; non-world-writable |
| `/run/flaghunt/manager-broker` | `flaghunt-broker:flaghunt-manager` | 2750 | Manager->broker dir (setgid) |
| `/run/flaghunt/manager-broker/broker.sock` | `flaghunt-broker:flaghunt-manager` | 0660 | Management RPC |
| `/run/flaghunt/broker-controller` | `flaghunt-fwcontroller:flaghunt-broker` | 2750 | Broker->controller dir (setgid) |
| `/run/flaghunt/broker-controller/controller.sock` | `flaghunt-fwcontroller:flaghunt-broker` | 0660 | Firewall control RPC |
| `/run/flaghunt/controller-helper` | `flaghunt-fwhelper:flaghunt-fwcontroller` | 2750 | Controller->helper dir (setgid) |
| `/run/flaghunt/controller-helper/helper.sock` | `flaghunt-fwhelper:flaghunt-fwcontroller` | 0660 | Privileged helper RPC |
| `/run/flaghunt/broker-runtime` | `flaghunt-runtime:flaghunt-broker` | 2750 | Broker->runtime adapter dir (setgid) |
| `/run/flaghunt/broker-runtime/runtime.sock` | `flaghunt-runtime:flaghunt-broker` | 0660 | Fixed runtime adapter RPC |
| `/var/run/docker.sock` | `root:docker` (host default) | host-defined | **Runtime adapter only**; broker/manager/controller/helper not in group |

Directory mode and socket mode are separate controls. The directory owner (server) can write; the
client group can read/traverse/connect but cannot create/rename/unlink. The setgid bit is verified
as `S_ISGID`, not just as a numeric `0750`; the server verifies `lstat` type/owner/group/mode,
rejects symlinks/non-sockets, probes stale sockets, and uses temp-bind + atomic rename; see 2H.1
Sections 5.1-5.2. Deployment must prove the pinned `/run` filesystem honors setgid inheritance; a
failure is a host-validation blocker, not a reason to add a shared group or world-writable socket.
Cleanup is confined to the service's own
socket inode. `/run` is tmpfs; tmpfiles recreates directories after reboot. `SO_PEERCRED` and
numeric allowlists are mandatory even when filesystem permissions pass.

### 6.4 Storage, logs, and audit (proposed)

| Data | Proposed location | Ownership/mode | Notes |
|---|---|---|---|
| Broker DB | `/var/lib/flaghunt/broker/` | `flaghunt-broker:flaghunt-broker`, 0750 dir / 0640 file | Existing broker separation |
| Controller DB | `/var/lib/flaghunt/controller/` | `flaghunt-fwcontroller:...`, 0750 dir / 0640 file | WAL/SHM same protection |
| Backups | Operator-approved backup path | Restricted, integrity-checked | Encrypted/retained per policy |
| Controller audit | Controller DB and/or structured journal | Controller-only write | Sanitized, bounded, retained |
| Helper audit | journald or helper-owned append-only log | Helper write, monitor read | Independent of controller DB |
| Runtime adapter catalog | Read-only manifest owned by deployment | `flaghunt-runtime` read-only | Pinned images/specs; no runtime mutation |
| Runtime adapter audit | journald or adapter-owned append-only log | Runtime write, monitor read | Container lifecycle only; no controller DB |
| Metrics | Read-only metrics endpoint/file | Monitor read | No secrets/topology |

No service gets broad write access to `/var/lib/flaghunt`. The helper cannot write the controller
DB. The runtime adapter cannot write controller/broker DBs and the broker cannot read the Docker
socket. Logs must not include tokens, request bodies, SQL, Docker configuration secrets, raw paths,
or tracebacks. Evidence and audit writes are bounded and disk-full behavior is fail-closed.

### 6.5 Startup, restart, and shutdown

Proposed boot order:

```text
systemd-tmpfiles creates /run/flaghunt and exact 2750 setgid directories
  -> operator-approved baseline (if any)
  -> flaghunt-runtime.service (catalog/ownership checks; no blind Docker ops)
  -> flaghunt-fwhelper.service (binds helper.sock; CAP_NET_ADMIN)
  -> flaghunt-fwcontroller.service (binds controller.sock; controller DB/reconciliation)
  -> flaghunt-broker.service (binds broker.sock; checks controller/runtime peers)
  -> flaghunt-manager.service (management UDS client)
```

- Readiness requires DB integrity, helper peer verification, backend health, and controller
  reconciliation readiness; a listening socket alone is insufficient. Direct-bind sockets are
  created by their servers, not by systemd activation.
- Services use bounded restart limits, watchdog, and fail-closed behavior.
- On controlled shutdown, drain requests and stop in reverse order. Do not remove rules merely
  because a service stops.
- On boot, reconcile owned/non-terminal records; do not adopt unknown rules.
- The pre-reconciliation exposure window and boot baseline are explicit open decisions.

### 6.6 Upgrade and rollback

**Upgrade sequence (proposed):**

1. Preflight: change approval, backups, disk space, schema/version compatibility, backend health,
   rollback plan.
2. Stop manager/broker from accepting new work; drain.
3. Stop controller; keep existing rules for availability.
4. Back up and integrity-check controller DB.
5. Apply forward migration on a copy; verify; apply in window.
6. Upgrade helper/controller binaries with pinned packages; verify signatures/checksums.
7. Start runtime adapter, helper, controller; verify peer identity/backend/catalog; run
   reconciliation dry run.
8. Start broker/manager; verify all four UDS edges; monitor uncertainty/container/firewall drift.
9. Rollback on any failed gate: stop new services, restore DB backup and previous binaries,
   reconcile; do not flush rules blindly.

**Rollback constraints:**

- No unsupported downgrade of a migrated DB unless the pre-migration backup is restored.
- The helper and controller schema/protocol versions must be compatible; a mismatch fails closed.
- Kernel rules from a failed upgrade remain potentially active; reconciliation/cleanup is
  mandatory before declaring rollback complete.

### 6.7 Monitoring and operations

Minimum target signals:

- helper/controller/broker/manager liveness and readiness;
- peer-auth failures and socket/permission drift;
- helper operation latency, timeouts, uncertain results, crashes/restarts;
- controller idempotency backlog and non-terminal/partial/unknown records;
- reconciliation duration, last complete scan, drift count;
- DB integrity/quick-check status, disk/WAL growth, lock/busy errors;
- IPv4/IPv6 family parity and rule/read-back drift;
- Docker/firewall interaction anomalies and rule loss after Docker restart;
- runtime adapter container config/label drift, Docker socket access, and unmanaged containers;
- audit gaps, disk/inode usage, and sanitized error-code rates.

Alerts must be actionable and must not expose secrets. Emergency runbooks cover: revoke one policy,
quarantine unknown rules, helper compromise, DB corruption, host restart, and rollback.

---

## 7. Current versus target deployment comparison

| Area | Current | Target proposal | Status |
|---|---|---|---|
| Host OS | Windows development workspace | Ubuntu LTS Linux | Not deployed |
| Service users | Application/test users | Dedicated manager/broker/controller/helper users | Proposed |
| UDS | Mock/no live socket | Four direct-bind UDS boundaries (manager-broker, broker-controller, controller-helper, broker-runtime) | Proposed |
| Capabilities | None | Helper `CAP_NET_ADMIN` only | Not granted |
| Docker authority | Broker adapter wired but clientless; manager adapter exported/mock-tested; no runtime service | Broker/manager none; separate runtime adapter with host-root residual | Proposed; N-04/T-27 open |
| Controller DB | Mock schema, single family | Migrated schema with per-family state/evidence | Proposed |
| Recovery | Mock/local tests | Durable intent + full-scan reconciliation | Proposed |
| Backend | Mock | nftables primary / iptables fallback | Proposed |
| Boot | N/A | systemd ordering + reconciliation | Proposed |
| Upgrade | N/A | backup/migrate/reconcile/rollback | Proposed |
| Monitoring | Mock/test logging | Structured metrics/audit/alerts | Proposed |

---

## 8. Deployment prerequisites checklist (not executed)

- [ ] Architecture/threat/backend/persistence docs approved and open decisions resolved.
- [ ] Ubuntu/kernel/nftables/Docker versions pinned and host-lab validated.
- [ ] Dedicated numeric users/groups and no-login helper account approved; runtime adapter is the
      only Docker socket user; broker/manager/controller/helper are not in Docker group.
- [ ] Socket directories and modes validated as `2750` setgid with exact owner/client group;
      manager-broker, broker-controller, controller-helper, and broker-runtime paths inaccessible
      to unrelated users; kernel setgid inheritance and cross-UID connect/deny proven; directory
      vs socket modes correct.
- [ ] Canonical `rule-schema-v1` policy JSON and digest stored/read back exactly; no legacy rule
      shape or lossy projection; controller/helper negative schema tests pass.
- [ ] Helper capability set proven minimal; no root/shell; seccomp/MAC profile validated.
- [ ] Controller schema migration, backup/restore, and integrity checks validated.
- [ ] Per-family evidence, append-only triggers/FKs, aggregate invariants, and full-scan
      reconciliation implemented and tested.
- [ ] UDS peer auth, malformed input, timeout, connection-limit, FD/ancillary-data, and typed
      identity tests pass on all four edges.
- [ ] nftables/iptables install/verify/revoke/rollback tests pass in isolated lab.
- [ ] Docker/`DOCKER-USER`/IPv4/IPv6 ordering tests pass.
- [ ] Crash/restart/fault-injection tests pass with no false `ACTIVE`/`REVOKED`.
- [ ] Residual register RR-01..RR-07 and I-07..I-09 closed or explicitly risk-accepted with
      evidence; N-01/N-02 host tests complete; N-04 source authority removed.
- [ ] Monitoring, audit retention, runbooks, and rollback drill complete.
- [ ] Security review and change approval obtained.
- [ ] Live gate explicitly re-opened; it remains closed today.

---

## 9. Open decisions

1. Exact supported Ubuntu/kernel/nftables/Docker versions and host baseline.
2. Single controller per host vs future HA/lease design.
3. Exact operation journal scope beyond lifecycle/idempotency/evidence tables.
4. Evidence signing/HMAC and key management.
5. Audit retention, tamper resistance, and independent helper/runtime log destination.
6. Boot-time baseline and acceptable pre-reconciliation exposure window.
7. Backup encryption/retention and restore approval authority.
8. Migration rollback policy and whether any down migrations are supported.
9. Explicit risk acceptance for T-11/T-13/T-27, including host isolation/monitoring and a named
   acceptance authority.
10. Runtime adapter catalog manifest ownership, image signing/provenance, and Docker socket group.

**Resolved by 2L.2I.2 and completed by 2L.2I.4:** manager->broker is direct-bind UDS with
`SO_PEERCRED` (no HTTP); `PARTIALLY_*` are derived from per-family rows, not persisted; socket
directories are direct-bind server-owned `2750` setgid with kernel-inherited client groups and no
supplementary-group access; idempotency keys are global-per-receiver; evidence is append-only with
FKs and aggregate invariants; `canonical_policy_json` stores the canonical `rule-schema-v1` rules
and digest without a second rule language. A `0750` socket directory is invalid.

---

**DESIGN COMPLETE — REAL FIREWALL IMPLEMENTATION NOT AUTHORIZED**

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
