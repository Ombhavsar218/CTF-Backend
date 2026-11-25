# Phase 2L.1b — Firewall Lifecycle and Integrity Hardening

**Date:** 2026-11-01  
**Status:** Implemented offline with mocked controller only. No real firewall/Docker/infrastructure changes.

## Subnet and instance membership verification
Added `broker/app/firewall_membership.py` with `FirewallMembershipVerifier`:
- Resolves network via persistent ownership (must be active, owned)
- Verifies instance-network binding
- Verifies container ownership
- Requires subnet/IP metadata from trusted ownership records; rejects if missing
- Verifies IP/subnet belong to owned network subnet; rejects outside subnet
- Verifies IP version matches
- Rejects loopback/link-local/multicast/reserved

Integrated into `FirewallPolicyModel.create_policy()` - membership verification enforced.

## Controller verification evidence
- Evidence stored in `firewall_verification_evidence` (policy_id, policy_version, compiled_rule_digest, controller_operation, controller_result, verified_at)
- `record_verification_evidence()` and `has_valid_verification_evidence()` 
- `transition()` can require evidence; VERIFIED only via trusted flow with positive evidence
- Evidence bound to policy version and digest; cannot be forged by caller boolean alone

## Compiled-rule digest integrity
- Canonical serialization in `FirewallRuleCompiler.canonical_serialize()` with stable ordering
- Digest recomputed on compile; stored in DB
- `verify_digest()` and `recompute_digest()` available
- Rejects digest/policy version mismatches; tampering detected

## Lifecycle transition enforcement
- Transitions validated; VERIFIED requires controller evidence
- INSTALL_PENDING requires validated ownership and verified digest
- Revocation idempotent; revoked cannot be reactivated without new policy version
- Ownership revalidation pattern supported

## Concurrency and recovery
- BEGIN IMMEDIATE transactions, conditional updates
- Evidence persists across restart
- Stale evidence cannot validate newer version

## Tests
Added `broker/tests/test_firewall_lifecycle_integrity.py` covering direct VERIFIED without evidence, forged evidence, evidence for other/old policy, digest mismatch, mutation, ownership changes, membership failures, controller failures, concurrent operations, restart scenarios, stale evidence, reactivation attempt.

## Remaining limitations
- Full instance IP metadata may not always be present; fail-closed by design
- Not integrated into routes yet
