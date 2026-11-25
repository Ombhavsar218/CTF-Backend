# Phase 2L.2E.2.1 — Independent Active Controller Integration Audit (Read-Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Scope:** Read-only audit of active integration

## 1) Active request-flow
All public methods (`install_policy`, `verify_policy`, `revoke_policy`, `inspect_policy`, `remove_stale_policy`, `reconcile_pending_operations`, `health_check`) go through `FirewallControllerService._call()` which does: audit request_received → `self.auth.authorize()` → audit passed/failed → `self.validator.validate()` → audit passed/failed → backend method → audit completed/failed. Authorization and validation occur before backend calls.

## 2) Authorization
- **Integrated:** `StrictAuthorizationProvider` is default when `strict_auth=True` (default). Accepts `allowed_uids`/`allowed_gids` passed to service; empty sets now fail closed.
- **Enforced:** Missing/invalid `peer_uid`/`peer_gid` rejected; caller-trusted headers rejected; unauthorized UID/GID rejected; operation allowlist enforced. Auth before backend.
- **Tests:** Active integration tests added (4) cover missing identity, empty allowlists, caller headers, unauthorized.

## 3) Ownership/Evidence/Lifecycle/Idempotency
- **Ownership store instantiated** but **not actively used** in `_call()` or service methods yet (no calls to `create_ownership`, `store_evidence`, state transitions). 
- **Evidence enforcement** not wired into verify/active transitions.
- **Lifecycle state machine** not enforced by service.
- **Idempotency** remains in-memory (`self._idempotency`) not DB-backed.

## 4) Findings
| ID | Severity | Affected | Issue | Impact | Evidence | Recommendation | Host validation |
|---|---|---|---|---|---|---|---|
| AIA-001 | High | controller_service | Ownership store not used in active flow | No enforcement | No calls to ownership_store methods | Integrate ownership/evidence/state into methods | No |
| AIA-002 | High | controller_service | Evidence not validated for VERIFIED/ACTIVE | Bypass possible | Not enforced | Enforce evidence checks | No |
| AIA-003 | High | controller_service | Lifecycle not enforced | Invalid transitions allowed | No state machine | Enforce transitions | No |
| AIA-004 | Medium | controller_service | Idempotency in-memory only | Not restart-safe | self._idempotency dict | Use DB-backed idempotency | No |

## 5) Regression
Active integration tests: executed (see results); broker suite remains intact per prior phases.

## 6) Status
**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**  
Authorization is integrated and fail-closed. Ownership/evidence/lifecycle/idempotency enforcement still need active integration. Mocks cannot prove isolation.
