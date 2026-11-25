# Phase 2L.2J.18 — Lifecycle State / Evidence Matrix (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be` | **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | **Date:** 2026-11-16

Derived from inspected implementation (`controller_service.py` LIFECYCLE_TRANSITIONS, reconcile logic, evidence validation) and existing/J.18 tests. Actual enum states in code: `REQUESTED, VALIDATING, INSTALLING, VERIFYING, VERIFIED, ACTIVE, REVOKING, REVOKED, FAILED, CLEANUP_PENDING, ORPHANED`. Mock-only evidence.

## State matrix

| State (actual) | Required evidence/bindings for acceptance/promotion | Required bindings checked in reconcile (covered) | Permitted next transitions (code) | Reconcile can promote/change state? | Missing/invalid evidence or uncertainty effect | Repeated recovery/reconcile (covered) |
|---|---|---|---|---|---|---|
| REQUESTED | No verification/revocation evidence required for existence; ownership + canonical body (if present) must be valid/bound | Ownership record validity/binding, canonical body trusted if present, backend read-back | `VALIDATING`, `INSTALLING`, `FAILED` | Yes: may move to `INSTALLING` (if backend installed, needs verification) or `FAILED` (if backend missing), else uncertain | Backend unavailable/unknown -> uncertain, no promotion | Deterministic/fail-closed in tested cases |
| VALIDATING | Same as interrupted install states | Same as above | `INSTALLING`, `FAILED` | Yes: may move to `INSTALLING` (needs verification) or `FAILED` (backend missing), else uncertain | Backend unavailable/unknown -> uncertain | Deterministic in tested cases |
| INSTALLING | Same as interrupted install states | Same as above | `VERIFYING`, `VALIDATING`, `CLEANUP_PENDING`, `FAILED` | Yes: may mark needs verification (`INSTALLING` kept/recorded path) or `FAILED` if backend missing, else uncertain | Backend unavailable/unknown -> uncertain; no ACTIVE without verification evidence | Deterministic in tested cases |
| VERIFYING | Verification evidence required for promotion beyond uncertain handling; none sufficient for auto-promotion in current reconcile | Ownership/canonical checks | `VERIFIED`, `CLEANUP_PENDING`, `FAILED` | **No promotion.** Explicit `verifying_state_uncertain` | Missing/absent promotion path -> uncertain (no silent skip) | Idempotent/explicit uncertain in covered cases |
| VERIFIED | Valid `verified` evidence matching ownership_record_id, policy/version, digest, instance/network, family | Ownership/canonical checks + evidence validation | `ACTIVE`, `REVOKING`, `FAILED` | Yes: promote to `ACTIVE` only with valid matching evidence and CAS/identity checks | Missing/invalid evidence -> `verified_without_valid_evidence` (no promotion) | Safe/idempotent in covered cases |
| ACTIVE | Consistent backend installed state expected; prior verification evidence implied by lifecycle | Ownership/canonical checks + backend inspect consistency | `REVOKING` | No promotion; confirms `active_ok` if backend consistent, else uncertain `active_backend_mismatch_or_unavailable` | Backend mismatch/unavailable -> uncertain (no false confirmed active) | Idempotent in covered cases |
| REVOKING | Revocation evidence (`verification_result='revoked'` with matching bindings) required before/for `REVOKED` confirmation | Ownership/canonical checks, backend read-back, revocation evidence | `REVOKED`, `CLEANUP_PENDING` | Yes: can confirm/promote to `REVOKED` only with backend missing/revoked and valid revocation evidence; may store evidence in covered path | Backend still present/readback unavailable/invalid evidence -> uncertain or fail-closed; no false REVOKED | Deterministic/fail-closed in tested cases |
| REVOKED | Valid matching revocation evidence required for terminal acceptance | Ownership/canonical checks + revocation evidence | none | No promotion; reconciled as `already_revoked` only with valid evidence | Missing/invalid evidence -> `revoked_without_valid_evidence` (uncertain) | Idempotent in covered cases |
| FAILED | No promotion evidence path defined in reconcile | Ownership/canonical checks | `CLEANUP_PENDING`, `ORPHANED` | No auto state change; reported `no_auto_change_terminalish` | N/A (terminalish handling) | Stable in covered cases |
| CLEANUP_PENDING | No promotion evidence path defined in reconcile | Ownership/canonical checks | `REVOKING`, `REVOKED`, `ORPHANED`, `FAILED` | No auto state change; reported `no_auto_change_terminalish` | N/A | Stable in covered cases |
| ORPHANED | No promotion evidence path defined in reconcile | Ownership/canonical checks | `CLEANUP_PENDING` | No auto state change; reported `no_auto_change_terminalish` | N/A | Stable in covered cases |
| Unknown/unsupported persisted value | N/A | Detected before state handling | N/A | No; explicit uncertain `corrupt_ownership_state` (and audit/status update attempts) | Always uncertain/fail-closed | No silent skip |
| Known but unhandled (defensive) | N/A | Catch-all | N/A | No; explicit uncertain `unhandled_lifecycle_state:*` | Always uncertain/fail-closed | No silent skip |

## Notes
- Canonical schema-v1 policy body, when present, must be trusted/valid and digest/binding-consistent before lifecycle decisions; invalid/mismatched body yields explicit uncertain outcomes in covered paths.
- No state is silently skipped in the per-policy ownership-targeted reconcile loop; every evaluated target reaches an explicit outcome bucket or the defensive catch-all.
- **Limitation:** orphan lifecycle-history records without corresponding ownership rows are not inventoried by the current per-policy ownership-targeted reconciliation contract.
- Repeated reconciliation must not produce false ACTIVE/VERIFIED promotion or reactivation after revoke in covered cases.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
