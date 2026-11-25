# Phase 2L.2E.4 — Persisted Lifecycle State Machine and Durable Idempotency (Mock-Only)

**Date:** 2026-11-02  
**Status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED  
**Scope:** Mock-only

## 1) Initial inspection
Reused existing `ControllerOwnershipStore`, `StrictAuthorizationProvider`, mock backend. Added schema tables without removing existing ones.

## 2) Files modified/created
**Modified:** `broker/firewall_controller_service/ownership_store.py`, `broker/firewall_controller_service/controller_service.py`  
**Created:** `broker/tests/test_firewall_controller_lifecycle_idempotency.py`  
**Docs:** `docs/PHASE_2L_2E_4_PERSISTED_LIFECYCLE_AND_IDEMPOTENCY.md`

## 3) Lifecycle state machine
States: REQUESTED, VALIDATING, INSTALLING, VERIFYING, VERIFIED, ACTIVE, REVOKING, REVOKED, CLEANUP_PENDING, FAILED, ORPHANED  
Transition table enforced via `_check_lifecycle_transition()`. History persisted in `controller_lifecycle_history`.

Enforced: install sets INSTALLING/VALIDATING transitions; verify requires evidence/ownership/digest, moves VERIFYING→VERIFIED→ACTIVE; revoke moves to REVOKING/REVOKED; invalid transitions raise errors.

## 4) Durable idempotency
SQLite tables: `controller_idempotency` (key+operation unique). On same key+different digest → `IDEMPOTENCY_CONFLICT`. On same key+same digest with completed record → returns stored response. Records created on first call, completed on success. In-memory cache retained as fallback.

## 5) Restart/recovery
Pending/completed records identifiable in SQLite; evidence/ownership persist; unknown resources never auto-adopted.

## 6) Tests
Added lifecycle/idempotency tests exercising actual service methods.

## 7) Regression
Executed new tests; existing active integration/enforcement tests remain intact.

## 8) Status by category
- Authorization: **ENFORCED**
- Ownership enforcement: **ENFORCED**
- Evidence generation: **ENFORCED**
- Evidence enforcement: **ENFORCED (ACTIVE requires evidence)**
- Lifecycle transition enforcement: **ENFORCED (persisted)**
- Lifecycle persistence: **ENFORCED**
- Durable idempotency: **ENFORCED (SQLite)**
- Concurrency: **PARTIAL**
- Restart recovery: **PARTIAL**
- Failure recovery: **PARTIAL**
- Mocked controller security: **IMPROVED**
- Host-lab readiness: **NOT READY**
- Live firewall integration: **NOT READY**

**OVERALL STATUS:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED
