# Phase 2L.2J.4 — Rollback and Evidence Plan

**Project:** Flaghunt CTF Platform  
**Repository:** `E:\Flag-hunt\ctf-platform-be`  
**Phase:** 2L.2J.4  
**Date:** 2026-11-14  
**Status:** **PLANNING DOCUMENT — NOT EXECUTED; NO ROLLBACK/HOST OPERATION AUTHORIZED**  
**Scope:** Failure containment, rollback boundaries, audit/evidence requirements, and evidence acceptance criteria for a future separately authorized controlled host-validation phase.

No rollback, recovery, firewall, Docker, systemd, database, or host operation was performed by this phase. This document defines required future procedures only.

**Hard rule:** rollback/recovery procedures must **not** recommend or perform deletion of unknown or foreign firewall rules. Unknown/foreign rules are reported, preserved, and escalated.

---

## 1. General containment principles

| Principle | Requirement |
|---|---|
| Fail closed | On identity, permission, schema, ownership, backend, persistence, or evidence uncertainty, deny/stop the unsafe action; do not grant access or claim success. |
| Preserve evidence | Capture state before destructive recovery where safe; avoid overwriting logs/artifacts needed for investigation. |
| Owned scope only | Any cleanup/removal action may target only resources positively identified as owned/managed by the operation and verified by read-back/digest/markers. |
| No false terminal state | Uncertain external operations must never be represented as confidently `ACTIVE` or `REVOKED` without sufficient evidence. |
| Escalate ambiguity | Unknown external state, foreign rules, corruption, or conflicting evidence require human/platform/security escalation. |
| No production impact | Future execution only in approved isolated disposable environment with recovery access. |

---

## 2. Failure containment and rollback scenarios

| Scenario | Detection | Immediate containment | Safe state | Required evidence | Recovery conditions | Escalation authority | Explicitly prohibited recovery actions |
|---|---|---|---|---|---|---|---|
| Incorrect socket permissions | Startup/runtime verification failure, `stat` mismatch, audit/log alert | Stop/reject service bind/readiness; block client use of affected socket | Service not ready; no socket accepted with wrong mode/owner/group/setgid | `stat`/ownership/mode, logs, config, tmpfiles, process state | Correct approved config/accounts/tmpfiles; re-verify on isolated host; rerun UDS-PERM/LIFE/FAIL tests | Deployment/platform owner; security reviewer for permission model changes | `chmod 0666`/widening perms, removing setgid, adding insecure ACLs, CAP_CHOWN/chown workaround, auto-fallback |
| Unauthorized socket access | Permission denied anomalies, unexpected peer acceptance, audit of unauthorized UID/GID/connect | Refuse connection; fail closed; isolate/restart affected service if needed | No authorized operation performed for unauthorized peer | Peer credentials, socket perms, audit logs, connection records | Fix ownership/groups/allowlists; verify cross-UID deny tests | Security authority + platform owner | Weakening socket/dir permissions, broadening allowlists without approval, ignoring peer identity |
| Identity verification failure | Missing/malformed/mismatched `SO_PEERCRED`, allowlist mismatch, schema/auth errors | Reject request/connection; no backend/helper mutation | No privileged operation executed | Credential evidence, rejection code, request metadata (bounded), audit | Restore trusted transport path and allowlists; pass ID-* tests | Security reviewer; controller/broker owner | Trusting caller headers/body identity, bypassing peer checks, default-allow |
| Helper unavailable | Connection timeout/refused, health/readiness failure, operation timeout | Fail closed for operations requiring helper; mark outcomes uncertain where external state unknown | No new firewall mutation assumed; prior verified state unchanged unless evidence shows otherwise | Service status, connection errors, request IDs, pending intents | Restore helper service/config; reconcile pending/uncertain intents before retry | Platform owner; helper owner; security if repeated/unknown impact | Reporting success, blind retries without idempotency/reconciliation, deleting unknown rules |
| Backend unavailable | nftables/iptables command/interface failure, kernel/subsystem error, read-back failure | Abort mutating flow safely; persist uncertain/failed state per design; no false terminal success | Backend state as last verified; no claimed new state | Backend error (bounded), ruleset/read-back snapshot, intent/evidence records | Restore backend capability; reconcile owned objects by markers/read-back | Platform/security owner | Broad flush/reset, deleting foreign rules, assuming apply/remove succeeded |
| Partial firewall installation | Read-back mismatch, per-family incomplete state, timeout after partial apply | Mark partial/uncertain; stop further unsafe mutations; preserve owned markers/evidence | Partially installed owned state treated non-terminal/uncertain until reconciled | Intended canonical policy, applied/read-back diff, per-family evidence, digests | Reconcile owned policy only: complete or remove owned partial artifacts based on evidence and approved procedure | Controller/backend owner; security reviewer | Claiming ACTIVE, deleting foreign rules, unowned cleanup, ignoring per-family mismatch |
| Partial revoke | Owned rules remain after revoke attempt or read-back inconclusive | Mark uncertain/not-revoked; block false REVOKED; preserve evidence | Rules may still be present; treat as not safely removed until confirmed | Before/after/read-back evidence, ownership markers | Retry/remove only owned marked rules; confirm absence by read-back | Controller/backend owner; security reviewer | Claiming REVOKED without absence proof, broad chain/table flush |
| Database failure | Connection/write/read errors, transaction failure, lock/IO errors | Fail closed for operations requiring durable intent/evidence; stop unsafe progression | No unrecorded mutation; prior committed state only | DB error (bounded/sanitized), transaction/request IDs, service state | Restore DB service/storage/integrity; reconcile intents vs backend evidence | Platform/persistence owner; security for integrity concerns | Continuing mutation without durable record, manual state fabrication, silent data loss |
| Persistence corruption | Integrity check failure, invalid canonical/digest/state, schema invariant violation | Quarantine affected records/process path; fail closed; halt automated trust/reconciliation decisions for corrupted scope | Corrupted scope not trusted; backend treated unknown until independently verified | Integrity reports, checksums/digests, affected records, snapshots | Restore from approved backup/snapshot or rebuild from verified evidence; independent verification before reuse | Security authority + persistence owner | Auto-repair by guessing, trusting corrupted digests/states, deleting evidence |
| Docker/runtime adapter failure | Runtime UDS/API error, timeout, daemon unavailable, operation failure | Fail closed runtime operations; do not mutate firewall/controller state based on assumed runtime success | No runtime change assumed; owned runtime state unknown until reconciled | Runtime request/response, container/resource IDs, adapter logs, daemon status (bounded) | Restore adapter/daemon if approved; reconcile only owned managed resources | Runtime/platform owner; security if authority boundary involved | Arbitrary Docker cleanup, deleting unknown containers/resources, granting broker/manager Docker access |
| Unexpected foreign firewall rules | Read-back/reconciliation detects unknown/unowned rules | Preserve rules; record/report; do not modify | Foreign rules unchanged; Flaghunt owned state evaluated separately | Full ruleset snapshot, ownership marker scan, reconciliation report | Escalate for human review; adjust only owned Flaghunt artifacts if needed | Security authority + platform/network owner | Deleting, flushing, or "normalizing" unknown/foreign rules |
| Service restart | Planned/unplanned restart detected, readiness changes, stale pending intents | Re-run startup verification; block readiness on verification failure; reconcile pending/uncertain operations | Services ready only after checks pass; intents reconciled before confidence | Startup logs, verification results, intent/evidence state, socket/backend state | Complete verification and reconciliation; resume only safe operations | Platform owner; component owner | Skipping verification, auto-deleting sockets/paths unsafely, assuming in-flight ops succeeded |
| Upgrade failure | Version/config/schema mismatch, failed migration/startup, health check failure | Stop rollout; keep prior known-good state where possible; fail closed | Prior approved version/state or isolated stopped state | Version/config hashes, migration logs, health/readiness, backups | Roll back to approved artifact/config/snapshot; verify integrity and reconciliation | Platform/deployment owner; security for boundary changes | In-place partial fixes outside approved procedure, deleting unknown state, continuing with mismatched schema |
| Rollback failure | Rollback step errors, inconsistent state after rollback, missing backup/snapshot | Halt further automated changes; preserve all evidence; isolate host/environment | Last known state frozen for investigation | Rollback logs, state snapshots, backend/DB/socket evidence, error details | Manual recovery by authorized operators using verified backups/snapshots; independent verification before any reuse | Project owner + security authority + platform owner | Repeated blind rollback attempts, destructive cleanup of unknown state, declaring recovery without evidence |

---

## 3. Evidence collection and audit requirements (Phase K)

### 3.1 Required evidence categories

| Category | Minimum evidence |
|---|---|
| Host and environment | Host/VM ID, isolation statement, OS/distribution, kernel version, architecture, relevant package/runtime versions |
| Software versions | Component versions/commits/build IDs, schema/protocol version (`2L.2I.2`), `rule-schema-v1`, helper/backend versions, config versions |
| Service identities | Service account names, numeric UID/GID mappings, group memberships, allowlist configuration identifiers |
| Socket/transport | Socket paths, directory/socket `stat` output, setgid/mode/owner/group, parent permissions, `SO_PEERCRED` verification results (bounded) |
| Rule/policy | Canonical policy input (redacted as needed), canonical JSON/hash inputs where approved, canonical rule digest, policy/ownership IDs, schema version |
| Backend | Backend selected (nftables/iptables), owned table/chain/rule snapshots, read-back output, ownership markers, operation result |
| Persistence/lifecycle | Durable intent records, lifecycle transitions, idempotency records, evidence records, reconciliation outcomes, timestamps |
| Test/audit | Test ID, preconditions, procedure reference, result, pass/fail, operator/reviewer, logs (bounded), screenshots/artifacts as applicable |
| Failure/rollback | Detection signal, containment actions, safe state, recovery actions, escalation record, final disposition |

### 3.2 Evidence management controls

| Control | Requirement |
|---|---|
| Evidence identifiers | Unique ID per artifact/case (e.g. `EV-YYYYMMDD-<phase>-<seq>`), linked to test/scenario ID and requirement/finding ID. |
| Timestamp requirements | UTC timestamps for collection, test start/end, operation, and review; host clock source recorded. |
| Integrity requirements | Hashes/checksums for key artifacts, immutable storage or append-only log where feasible, chain of custody/collector recorded. |
| Redaction requirements | Remove/mask passwords, tokens, private keys, secrets, unnecessary personal data, and sensitive host details not needed for verification. |
| Retention requirements | Retain per project/security policy for approved validation phases; minimum until independent review and disposition complete. |
| Responsible reviewer | Assigned independent security/platform reviewer validates completeness and pass/fail criteria; engineering owner provides artifacts. |
| Evidence acceptance criteria | Artifact complete, attributable, time-stamped, integrity-protected, redacted appropriately, reproducibly linked to procedure, and sufficient to support the claimed result without inference. |

### 3.3 Audit record minimum fields

`timestamp_utc`, `evidence_id`, `scenario_or_test_id`, `component`, `service_identity`, `trusted_peer_uid/gid` (if applicable), `operation`, `policy_id/ownership_reference` (if applicable), `schema_version`, `canonical_digest` (if applicable), `backend`, `result`, `bounded_error_code`, `correlation/request ids`, `reviewer/status`.

Never include passwords, tokens, private keys, raw secret payloads, or unnecessary sensitive host information.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**