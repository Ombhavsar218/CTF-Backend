# Post-J.20 Stage 1B.15 — Residual Risk Assessment

**Mandatory status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED.**

**T-11, T-13, T-27 remain OPEN — ACCEPTANCE REQUIRED.**

This document classifies controls into **VERIFIED (scoped)**, **PARTIAL**, **UNRESOLVED**, and **UNVERIFIED / OUT OF SCOPE**. Passing mock tests are not host, production, or gate-closure evidence.

## 1. VERIFIED (scoped mock-only)

| Control | Evidence | Disposition |
|---|---|---|
| No silent legacy → canonical conversion | Legacy compiler/state modules have no canonical references; 1B.15 no-conversion tests; existing 1A separation test | VERIFIED (scoped) |
| No canonical → legacy downgrade | Canonical body/readback/reconciliation tests; body JSON contains only schema-v1 fields | VERIFIED (scoped) |
| Mixed/ambiguous payload rejection | 1B.15 mixed top-level, legacy compiled, schema-v1 mirror, and helper-contract negative tests | VERIFIED (scoped) |
| Validator invocation at covered ingress | Service (`controller_service.py:899-917`) and mock adapter (`firewall_controller.py:75-78`) invocation-negative tests | VERIFIED (scoped) |
| Legacy no-rules compatibility | 1B.15 legacy no-rules install/inspect/reconcile; legacy regression group | VERIFIED (scoped) |
| API/exception contract preservation | Canonical validation/legacy/regression groups; bounded outward errors unchanged | VERIFIED (scoped) |
| Canonical body persistence/readback | Body persistence, digest recompute, schema/ownership binding tests | VERIFIED (scoped) |
| Append-only history/evidence/audit | Deterministic UPDATE/DELETE rejection tests | VERIFIED (scoped) |
| Idempotency digest/CAS integrity | Corrupt-digest replay denial and stale-outcome CAS test | VERIFIED (scoped) |
| Additive idempotency migration | Legacy table without outcome columns migrated with NULL outcomes | VERIFIED (scoped) |
| Controller FK enforcement on writes | `_get_conn_fk()` and `_execute_fk()` FK-negative test | VERIFIED (scoped) |

## 2. PARTIAL controls

| Control | What is proven | What is not proven |
|---|---|---|
| `controller_policy_bodies` immutability | Direct UPDATE is possible but trusted read detects digest/JSON tamper | No append-only trigger; P4.1 authority decision for schema change remains pending |
| Evidence/history ownership binding | Application-side binding verified; append-only triggers prevent update/delete | No DB FK from `controller_evidence` or `controller_lifecycle_history` to `controller_ownership` |
| Idempotency resource binding | `resource_key` and ownership record id validated on replay | No DB FK/unique resource constraint tying an idempotency row to ownership/policy |
| Foreign-key enforcement | Controller write path enables `PRAGMA foreign_keys=ON` | Base `BrokerDB._get_conn()` (`broker/app/db.py:50-56`) does not; global/deployment-level FK behavior is not guaranteed |
| Schema version/migration | `schema_version` seeded at 1; additive idempotency migration preserves legacy NULL outcomes | No authoritative migration plan, down-path, deployed schema audit, or data-owner approval |
| Legacy state-store reads | Digest verification fails closed on mismatch | `get`, `has_valid_verification_evidence`, and `list_by_instance` convert storage failures to absence (`firewall_state.py:48-55,93-99,157-161`) |
| End-to-end atomicity | DB-only grouped writes and rollback verified | No atomicity across backend effects, filesystem state, and DB (SR-10 remains pending) |

## 3. UNRESOLVED items requiring named authority or future approved work

- **T-11, T-13, T-27**: OPEN — ACCEPTANCE REQUIRED. No valid named-authority response records are present.
- **SR-10**: end-to-end DB↔backend atomicity not addressed; DB-only boundary remains explicitly labeled.
- **SR-06 / I-09**: permissive/test-only authorization seam disposition remains pending named authority.
- **P4.1**: append-only protection for `controller_policy_bodies` requires accepted migration/compatibility impact; not implemented.
- **SR-07 create-race narrowing**: scoped targeted-conlict classification remains as documented in Stage 1B.14; not reopened here.
- **Legacy library fail-open reads**: contract-preserving correction was not attempted because it would alter established legacy API behavior; documented as PARTIAL/UNRESOLVED above.

## 4. UNVERIFIED / OUT OF SCOPE (must not be claimed)

- UDS transport lifecycle, `SO_PEERCRED`, kernel-authenticated peer identity, and real transport deadlines.
- Docker runtime/socket/SDK/container isolation and privileged-helper capabilities/seccomp/MAC.
- nftables/iptables/host firewall state and host permission enforcement.
- Live backend contract, production/cloud deployment, and real firewall effects.
- Universal deployed envelope validation and migration closure (N-02/H-05/M-08/SR-13).
- Stage 1C and any live integration or production readiness claim.
- Gate closure, formal acceptance, or residual-risk acceptance.

## 5. Gate disposition

No gate status, risk disposition, acceptance record, or production-readiness claim was changed. The Stage 1B.15 gate-register entry is evidence-only.

Final milestone disposition: **COMPLETE — SCOPED MOCK-ONLY VERIFICATION** with the PARTIAL/UNRESOLVED/UNVERIFIED controls above explicitly retained.
