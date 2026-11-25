# Phase 2L.1 — Firewall Policy Engine and Rule Compiler

**Date:** 2026-11-01  
**Status:** Implemented offline with mocked controller only. No real firewall rules applied.

## A) Django verification (Part A)
- Correct env: `ctf-platform-be/venv/Scripts/python.exe`, settings `config.settings`, PYTHONPATH `E:\Flag-hunt\ctf-platform-be`
- `python manage.py test instances.tests.test_manager_client` → **Ran 33 tests, OK**
- `python manage.py check` → **System check identified no issues (0 silenced)**

## B) Architecture inspected
- broker/app: config, dependencies, routes, db, network_ownership, network_recovery, docker_adapter, policy, recovery
- Reused existing ownership/audit patterns; no destructive changes to Phase 2H/2K records

## C) Firewall policy model
Created `broker/app/firewall_policy.py`:
- `FirewallPolicy`, `FirewallPolicyTarget`, `FirewallPolicyModel`
- Rejects arbitrary caller-supplied IP/subnet/ports, unrestricted destinations/ports, host networking context, internet egress by default stance, unauthorized DNS (enforced via restrictions), requires explicit IPv4/IPv6 policy, default-deny
- Resolved from broker-controlled inputs only

## D) Rule compiler
Created `broker/app/firewall_compiler.py`:
- Deterministic, validates policy, produces normalized internal rules, enforces per-instance/destination/port restrictions, rejects duplicates/conflicts/unsupported protocols/invalid IP/ports, never generates unrestricted ACCEPT rules, stable output
- No rule execution, no shell commands generated

## E) Architecture/interfaces
Created `broker/app/firewall_controller.py` with `FirewallController` interface and `MockFirewallController` (install/inspect/verify/revoke/remove_stale/health_check, simulated failure). Proxy has no firewall admin privileges.

## F) Persistent firewall state
Extended `broker/app/db.py` with `firewall_policies` table (policy_id/version/instance/network/challenge/digest/state/lifecycle/verification/revocation timestamps). Parameterized SQL, transactions, unique constraints, idempotent operations, restart-safe, fail-closed.

## G) Policy lifecycle
States: `DRAFT → VALIDATED → COMPILED → INSTALL_PENDING → INSTALLED → VERIFIED → REVOKE_PENDING → REVOKED`. Failure states visible/recoverable. VERIFIED requires positive controller verification. Installation failure does not activate instance. Revocation idempotent; failed revocation remains pending. Unknown policies never auto-removed. Ownership checked before modification.

## H) Security tests
Added `broker/tests/test_firewall_policy.py` covering default-deny, unauthorized destinations/ports, IPv4/IPv6, invalid IP/protocol, duplicates/conflicts, arbitrary subnet/caller targets, unknown network/ownership mismatch, DB unavailable/restart, concurrency, controller install/verify/revoke failures, duplicate revocation, stale detection, mock restart, no unrestricted ACCEPT, no real execution.

## I) Limitations
- No live firewall controller (mock only). No rules applied to system.
- Not integrated into challenge activation yet.
- Proxy never receives firewall admin privileges.

## J) Verification
Will run broker/firewall/network/orphan/manager/Django tests.
