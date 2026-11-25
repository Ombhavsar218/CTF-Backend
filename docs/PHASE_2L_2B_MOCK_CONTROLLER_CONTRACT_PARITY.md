# Phase 2L.2B — Mock Controller Contract Parity (Mock-Only)

**Date:** 2026-11-02  
**Status:** Implemented with mocked controller only. No live firewall/Docker/infrastructure changes.

## Contract implementation
Extended `broker/app/firewall_controller_contract.py` with strict request validation and response schema. Updated `MockFirewallController` to implement all operations with request_id/operation_id/idempotency_key/policy/version/digest, controller identity/version/timestamp, structured results, sanitized errors.

## Idempotency
- Same key + same payload returns cached response
- Same key + different payload rejected
- Duplicate install/revoke/verify handled
- Persistent within mock instance (restart-safe behavior testable)

## Partial installation
Failure injection: `fail_install_ipv4/ipv6`, readback mismatch, ownership mismatch. Partial results reported with error codes; never marked fully successful; VERIFIED requires evidence.

## Partial revocation
Idempotent revoke, partial states tracked, unknown rules untouched.

## Ownership integrity
Requires ownership identity/context; mismatch rejected with error code. Evidence + readback required; comments/labels not trusted.

## Verification evidence
Evidence bound to policy_id, policy_version, compiled_rule_digest, operation_id, controller_id, timestamp, families, readback result. Forged/stale/cross-policy evidence rejected. Boolean alone not trusted.

## IPv4/IPv6
Per-family tracking, dual-stack requires both as applicable, partial failures block VERIFIED.

## State machine
REQUESTED/PREPARING/INSTALLING/PARTIALLY_INSTALLED/INSTALLED/VERIFYING/VERIFIED/REVOKING/PARTIALLY_REVOKED/REVOKED/CLEANUP_PENDING/FAILED supported via controller responses.

## Recovery/concurrency
Reconciliation operation added; lost responses/retries/idempotency tested; unknown rules never auto-deleted.

## Tests
Added `broker/tests/test_firewall_controller_contract.py` for schema validation, idempotency, partial install/revoke, ownership mismatch, evidence validation, IPv4/IPv6, reconciliation.

## Implemented and tested (2B.2)
- Structured idempotency errors via `FirewallControllerIdempotencyError` (error_code `IDEMPOTENCY_CONFLICT`) replacing generic RuntimeError
- Identical and conflicting idempotency key tests; no internal traces exposed
- In-process concurrent duplicate requests test; broker DB transaction safety via `BEGIN IMMEDIATE`

## Implemented but not tested
- Cross-process concurrency/idempotency persistence (requires separate process restart)

## Known limitations
- Mock in-memory idempotency state (lost on process restart) — not restart-safe
- No cross-process locking in mock; cross-process guarantees come from broker DB
- No real firewall backend

## Not implemented
- Live firewall controller, UDS server, nftables/iptables integration
