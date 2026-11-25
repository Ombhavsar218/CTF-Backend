# Phase 2L.2E.4.2.1 — Independent Concurrency, Transaction and Recovery Audit (Read-Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Phase acceptance:** CONDITIONALLY ACCEPTED (with findings)

## 1) Files inspected
controller_service.py, ownership_store.py, authorization_strict.py, tests, docs.

## 2) Mapping of 4.1 High findings
- **LIA-001 (swallowed transitions):** PARTIALLY RESOLVED — many transitions now propagate PermissionError, but broad try/except still exists in verify/revoke paths (lines ~187-228) and failures can be caught.
- **LIA-002 (idempotency races):** PARTIALLY RESOLVED — atomic INSERT added, conflict detection on concurrent create, but fallback in-memory cache and exception-based flow remain; SELECT-then-INSERT race possible.
- **LIA-003 (CAS/versioning):** PARTIALLY RESOLVED — lifecycle_version added with conditional updates checking expected version/state; rowcount==0 raises LIFECYCLE_VERSION_CONFLICT, but not all updates use CAS (some paths still update without version in fallback cases).

## 3) Findings
| ID | Severity | File/Method | Issue | Impact |
|---|---|---|---|---|
| CA-001 | High | controller_service._call verify/revoke | Broad try/except around lifecycle/evidence can swallow errors | May allow partial transitions |
| CA-002 | High | controller_service._call idempotency | In-memory fallback + exception handling can create duplicate execution paths | Race under concurrency |
| CA-003 | High | ownership_store.update_ownership_state | CAS used where passed, but some calls pass no version; rollback on rowcount==0 good but coverage incomplete | Stale overwrites possible |
| CA-004 | Medium | controller_service | Completion persistence raises on failure (good) but backend already called in some flows | Uncertain outcome |
| CA-005 | Medium | ownership_store.create_idempotency_record | INSERT without handling duplicate in a single atomic check properly; relies on exception | Race window |

## 4) Test results
Executed concurrency/integrity + lifecycle/idempotency + enforcement + active integration tests. Core behaviors present; full independent concurrency not proven by sequential tests.

## 5) Recommendation
Harden remaining try/except, remove/strengthen in-memory fallback, ensure all lifecycle updates use CAS, improve idempotency reservation to be fully atomic with transaction.

## 6) Final status
**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**. Improvements made but critical gaps remain.
