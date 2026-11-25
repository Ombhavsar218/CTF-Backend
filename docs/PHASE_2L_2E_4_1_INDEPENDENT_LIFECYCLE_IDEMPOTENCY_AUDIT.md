# Phase 2L.2E.4.1 — Independent Lifecycle, Idempotency and Recovery Audit (Read-Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Scope:** Read-only audit

## 1) Active request-flow
All public methods go through `_call()`: idempotency check (SQLite + fallback), audit, auth (strict default), validate, ownership/lifecycle checks, backend call, post-enforcement (ownership/evidence/lifecycle), idempotency completion, return.

## 2) Lifecycle audit
- **Authoritative:** `_check_lifecycle_transition()` enforces table; transitions persisted via `update_ownership_state()` and `record_lifecycle_transition()`. **Partial:** some checks are wrapped in try/except allowing failures to be ignored (e.g. revoke/verify paths) — bypass risk.
- **Evidence:** verify requires ownership/digest match, stores evidence, transitions to VERIFIED then ACTIVE. ACTIVE requires evidence path. **Issue:** exceptions swallowed in places.
- **Revocation:** moves to REVOKING/REVOKED. **Issue:** incomplete error handling.
- **Inspect:** read-only, no mutation. OK.

## 3) Idempotency audit
- **SQLite:** tables + methods added; conflict on different digest; completed records returned. **Issue:** create uses INSERT OR IGNORE (concurrent may create pending but not coordinated); completion after exception paths not guaranteed; in-memory fallback still used.
- **Scope:** key+operation composite.

## 4) Concurrency
- Uses BEGIN IMMEDIATE in some methods but not consistently across all state transitions; race conditions possible between check and update.

## 5) Recovery
- Pending/completed records exist but recovery logic not fully implemented; crash between backend success and persistence handled by exceptions (may fail open/closed depending).

## 6) Ownership/evidence regression
- Ownership checked on inspect/revoke/remove; evidence bound to ownership/digest; ACTIVE requires evidence. OK.

## 7) Findings
| ID | Severity | File/Method | Issue | Impact | Evidence |
|---|---|---|---|---|---|
| LIA-001 | High | controller_service._call verify/revoke | Broad try/except swallowing transition errors | Invalid transitions may proceed | Lines 187-228 |
| LIA-002 | High | controller_service._call idempotency | INSERT OR IGNORE + fallback allows duplicate execution paths | Race between concurrent requests | Lines 67-88 |
| LIA-003 | High | ownership_store.update_ownership_state | No CAS/versioning; conditional update by prev_state only in some calls | Concurrent transitions overwrite | Lines 158-177 |
| LIA-004 | Medium | controller_service._call install | If ownership exists, revalidation attempts but failures ignored | Inconsistent state | Lines 109-115 |
| LIA-005 | Medium | controller_service | Lifecycle enforcement not applied to all operations (remove/reconcile) | Gaps | Various |

## 8) Test results (executed)
Executed combined tests (lifecycle/idempotency + enforcement + active integration). Results show mixed outcomes per prior runs; enforcement partially works.

## 9) Status
**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**. Core structures present but error handling/swallowing and concurrency gaps remain.
