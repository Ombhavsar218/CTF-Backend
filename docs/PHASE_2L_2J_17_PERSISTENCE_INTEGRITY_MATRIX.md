# Phase 2L.2J.17 — Persistence Integrity Matrix (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be` | **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | **Date:** 2026-11-16

Status/evidence is mock-only and based on inspected source/tests. No host/runtime/live claims.

## 1. Persistent entities (inspected)

### `controller_ownership`
| Aspect | Details |
|---|---|
| Primary key | `ownership_record_id TEXT PRIMARY KEY` |
| Foreign keys | None defined |
| Unique constraints/indexes | `idx_ctrl_own_unique` UNIQUE `(policy_id, policy_version)`; index `idx_ctrl_own_instance` |
| Required fields | `ownership_record_id, policy_id, policy_version, instance_id, network_id, canonical_policy_digest, installation_state, lifecycle_version` (NOT NULL/defaults) |
| Nullable/optional | `installed_rule_ids_json, address_family, verification_evidence_ref, revoked_at, last_reconciliation_at, reconciliation_status` (nullable/defaulted as defined) |
| CHECK constraints | None at DB level (gap) |
| Mutable fields | `installed_rule_ids_json, address_family, installation_state, lifecycle_version, verification_evidence_ref, updated_at, revoked_at, last_reconciliation_at, reconciliation_status, canonical_policy_digest/identity fields as currently modeled` (app-controlled) |
| Append-only expectation | No (mutable state record) |
| Transaction boundaries | `create_ownership`: BEGIN IMMEDIATE, uniqueness check, insert, commit. `update_ownership_state`: BEGIN IMMEDIATE, CAS/conditional update, rowcount check, commit. `update_reconciliation_status`: single-statement execute+commit path. |
| Recovery behavior | Read-back/reconcile uses authoritative record; CAS prevents stale overwrite in covered paths; fail-closed on missing/mismatched bindings. |
| Existing/J.17 tests | J.3–J.16 suites + `test_firewall_controller_j17_persistence_integrity.py` (fresh/reopen, CAS, partial-progress recovery, races) |
| Remaining integrity gaps | No DB CHECK for state/version/digest format/policy_version range; no FKs from dependent tables except policy_bodies; lifecycle/version semantics app-enforced; destructive/admin DB mutation outside triggers not fully prevented; full migration/constraint hardening blocked by compatibility/no-destructive-change rule. |

### `controller_lifecycle_history`
| Aspect | Details |
|---|---|
| Primary key | `history_id INTEGER PRIMARY KEY AUTOINCREMENT` |
| Foreign keys | None defined (gap; compatibility risk to add destructively) |
| Unique constraints/indexes | Index `idx_ctrl_lc_hist_own` |
| Required fields | `new_state NOT NULL`; `history_id`/timestamp defaults |
| Nullable fields | `ownership_record_id, policy_id, policy_version, prev_state, operation_id, request_id, transition_reason, result, error_info` |
| CHECK constraints | None |
| Mutable fields | **Append-only expectation**; J.17 adds DB triggers blocking UPDATE/DELETE (`trg_ctrl_lc_hist_no_update/delete`) |
| Append-only expectations | Append-only history of transitions (no in-place mutation/deletion) |
| Transaction boundaries | Inserted via store `_execute_fk` (single-statement autocommit path in current implementation), separate from many state/evidence operations (partial-write possible across tables). |
| Recovery behavior | Reconcile/recovery inspects history/evidence/state; repeated recovery should not fabricate false promotions. |
| Existing/J.17 tests | J.12/J.13/recovery suites; J.17 append-only trigger tests, reopen preservation, repeated recovery |
| Remaining integrity gaps | No FK enforcement to ownership; no DB-level transition validity checks; inserts not atomically coupled to all related state/evidence writes; admin bypass possible only outside SQLite trigger protections if triggers removed/schema altered (not claimed). |

### `controller_evidence`
| Aspect | Details |
|---|---|
| Primary key | `evidence_id TEXT PRIMARY KEY` |
| Foreign keys | None defined (gap) |
| Unique constraints/indexes | None beyond PK |
| Required fields | `ownership_record_id, policy_id, policy_version, instance_id, network_id, canonical_policy_digest, verification_result` NOT NULL |
| Nullable fields | `address_family, installed_rule_ids_json, controller_identity, controller_transaction_id, request_id, verification_timestamp` (default) |
| CHECK constraints | None |
| Mutable fields | **Append-only expectation**; J.17 adds DB triggers blocking UPDATE/DELETE (`trg_ctrl_evidence_no_update/delete`) |
| Append-only expectations | Evidence records immutable after insert |
| Transaction boundaries | `store_evidence`: BEGIN IMMEDIATE insert commit in its own transaction (separate from ownership state transitions in many flows). |
| Recovery behavior | Verified/active/revoked promotion paths require matching evidence in covered logic; tamper/corruption/mismatch must fail closed in covered paths. |
| Existing/J.17 tests | revoke/recovery/J.12/J.13 suites; J.17 append-only, conflicting-evidence non-promotion, reopen/recovery cases; existing tamper-via-UPDATE test updated to append-only-compatible seeding |
| Remaining integrity gaps | No FK to ownership; no uniqueness on logical evidence events; conflicting/duplicate logical evidence possible at DB level and must be handled fail-closed by application; no digest/state CHECKs; multi-table atomicity with state/history/idempotency incomplete. |

### `controller_idempotency`
| Aspect | Details |
|---|---|
| Primary key | `(idempotency_key, operation_type)` |
| Foreign keys | None defined |
| Unique constraints/indexes | PK enforces uniqueness per key+operation; index `idx_ctrl_idem_status` |
| Required fields | `idempotency_key, operation_type, request_digest, status` NOT NULL/default |
| Nullable fields | `resource_key, ownership_record_id, lifecycle_state, response_json, recovery_meta_json, completed_at` |
| CHECK constraints | None |
| Mutable fields | `status, response_json, lifecycle_state, ownership_record_id, recovery_meta_json, completed_at, updated_at` (completion/recovery updates expected) |
| Append-only expectation | No (stateful record updated on completion) |
| Transaction boundaries | `create_idempotency_record` and `complete_idempotency_record` each use own BEGIN IMMEDIATE transaction; service logic coordinates with other operations across separate transactions. |
| Recovery behavior | Same-key replay/conflict handling, pending wait/retry bounded by existing J.10 limits, reopen/retry/recovery paths in covered cases. |
| Existing/J.17 tests | J.8/J.10/J.12/J.13/J.16 suites; J.17 replay/conflict/commit-failure/response-loss approximation/reopen tests |
| Remaining integrity gaps | Global per-receiver canonical scope/migration/DB constraints incomplete (RR-03/M-01); no FK/check constraints; request_digest corruption detected in covered service logic but DB-level integrity limited. |

### `controller_audit`
| Aspect | Details |
|---|---|
| Primary key | `audit_id INTEGER PRIMARY KEY AUTOINCREMENT` |
| Foreign keys | None defined |
| Unique constraints/indexes | None |
| Required fields | `event_type` NOT NULL |
| Nullable fields | `request_id, operation_id, policy_id, ownership_record_id, details_json, timestamp` |
| CHECK constraints | None |
| Mutable fields | **Append-only expectation**; J.17 adds DB triggers blocking UPDATE/DELETE |
| Append-only expectations | Audit records immutable after insert |
| Transaction boundaries | Insert via single-statement execute path (`_execute_fk`), separate from business transactions. |
| Recovery behavior | Best-effort/auditing; failures mapped to bounded persistence errors in covered paths. |
| Existing/J.17 tests | J.17 append-only trigger test |
| Remaining integrity gaps | No FK/check constraints; audit completeness/atomicity with state transitions not guaranteed. |

### `controller_policy_bodies` (canonical schema-v1, additive)
| Aspect | Details |
|---|---|
| Primary key | `policy_body_id TEXT PRIMARY KEY` |
| Foreign keys | `ownership_record_id -> controller_ownership(ownership_record_id)` |
| Unique constraints/indexes | UNIQUE `(policy_id, policy_version)`; index on `ownership_record_id` |
| Required fields | `ownership_record_id, policy_id, policy_version, schema_version, canonical_rules_json, compiled_rule_digest` NOT NULL |
| Nullable fields | `required_families_json, canonical_policy_digest, controller_identity, request_id, operation_id, timestamps` |
| CHECK constraints | None |
| Mutable fields | `updated_at` (model allows) though normal flow inserts/ensures; no explicit append-only trigger added (not classified as evidence/history/audit table) |
| Append-only expectation | Not strictly append-only in schema; trusted read-back validates digest/schema/bindings and fails closed on corruption/tamper in covered paths. |
| Transaction boundaries | `store_canonical_policy_body`: BEGIN IMMEDIATE, ownership/binding checks, insert, commit (separate from install state/evidence/idempotency completion). |
| Recovery behavior | Trusted read-back recomputes/validates digests, schema, bindings; missing/corrupt/mismatched bodies fail closed in covered paths. |
| Existing/J.17 tests | `test_firewall_controller_canonical_policy_persistence_2j6.py`, J.7/J.12/J.13/J.15/J.16 related suites, J.17 FK enforcement/reopen/corruption/missing-body recovery tests |
| Remaining integrity gaps | No DB CHECK for digest format/schema value/JSON validity; no append-only/immutability trigger; FK enforcement depends on per-connection pragma (J.17 improves store-managed connections); cross-table atomicity incomplete. |

## 2. Actual defects vs missing evidence (J.17 assessment)

| Item | Type | J.17 outcome |
|---|---|---|
| Append-only not DB-enforced for lifecycle history/evidence/audit | Actual integrity weakness (demonstrated by direct DB mutation possibility) | **Mitigated (additive):** triggers added in store schema init; J.17 tests verify UPDATE/DELETE blocked; existing tamper-simulation test updated to compatible seeding. Not a full immutability guarantee against schema/admin bypass outside covered controls. |
| FK enforcement not consistently enabled on all store-managed connections | Actual integrity weakness (SQLite FK pragma per-connection) | **Mitigated (covered):** store now uses FK-enforcing connections/helpers for transactional and key write paths; J.17 verifies policy_body FK rejection. BrokerDB-generic paths outside store not comprehensively changed. |
| Multi-table operations span independent transactions (install/verify/revoke/reconcile paths) | Design/implementation characteristic with partial-state risk | **Documented/tested in covered cases:** no false ACTIVE/VERIFIED promotion, recoverable/fail-closed behavior in tested scenarios. No broad redesign performed. |
| Missing DB CHECK/NOT NULL/FK coverage across all entities and digest fields | Actual schema-hardening gaps / partly compatibility-constrained | **Open / partially documented:** additive non-destructive checks not fully implementable without migration/rebuild; fail-closed application validation and trusted read-back provide covered protection. |
| Idempotency/persistence race and recovery uncertainty windows | Partially evidenced risks | **Improved evidence:** J.17 adds deterministic cases; exhaustive hookable boundary matrix and all production concurrency states not fully proven. |

## 3. Compatibility and safety notes
- No destructive migrations, no rewrites/resets/deletes of existing data.
- Triggers added via `CREATE TRIGGER IF NOT EXISTS` during init/reopen (additive). Fresh and existing-schema reopen tested in J.17.
- Existing test `test_revocation_evidence_requires_matching_family` updated to seed mismatched evidence without in-place mutation (preserves security intent under append-only enforcement).
- Limitations: DB-level bypass remains possible if triggers/schema are altered administratively; not claimed otherwise. Multi-table atomicity and full constraint set remain incomplete.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
