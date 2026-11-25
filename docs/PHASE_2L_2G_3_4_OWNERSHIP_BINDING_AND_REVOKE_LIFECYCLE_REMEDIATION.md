# Phase 2L.2G.3.4 — Ownership Binding and Revoke Lifecycle Remediation

**Scope:** local mock-only controller/helper-boundary remediation
**Date:** 2026-11-07
**Base review:** `docs/PHASE_2L_2G_3_3_INDEPENDENT_IDENTITY_REMEDIATION_REVIEW.md`
**Prior remediation:** `docs/PHASE_2L_2G_3_2_HELPER_IDENTITY_PROPAGATION_AND_CONTRACT_HARDENING.md`

> **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
>
> This phase is controller/mock-code remediation only. It does not implement or authorize a real
> transport, UDS/`SO_PEERCRED`, privileged helper, capabilities, firewall backend, routing/NAT,
> conntrack, systemd/host hardening, provisioning, or production/cloud database changes.

## 1. Decision

| Decision layer | Result |
|---|---|
| Local mock-only 2G.3.4 remediation | **PASS** |
| Real transport / privileged helper / live firewall readiness | **NOT READY — NOT AUTHORIZED** |

The prioritized 2G.3.3 findings ID-01 through ID-05 are remediated and covered by focused tests.
ID-06 remains a documented validator limitation, not a parser guarantee. Informational findings
ID-07 through ID-14 remain real-transport/host gates or mock-fidelity notes.

## 2. Files changed

| File | Change |
|---|---|
| `broker/firewall_controller_service/controller_service.py` | Authoritative ownership binding, identity-bound idempotency validation, explicit lifecycle transitions, evidence-gated revoke completion, read-back confirmation, retry/read-back precheck, reconciliation binding. |
| `broker/firewall_controller_service/ownership_store.py` | Read methods now propagate `BrokerDBError`; genuine absence still returns `None`/empty. |
| `broker/firewall_controller_service/helper_authorization.py` | Omitted operation allowlist now means empty/deny instead of all operations. |
| `broker/tests/_helper_identity.py` | Test fixture explicitly opts into the operations it needs. |
| `broker/tests/test_firewall_controller_helper_identity_propagation.py` | Test auth helper made explicit; strict ownership expectations preserved. |
| `broker/tests/test_firewall_controller_helper_contract.py` | Controller fixture no longer sends caller `ownership_reference`; helper auth operations made explicit. |
| `broker/tests/test_firewall_controller_ownership_binding_remediation.py` | New ownership-binding tests. |
| `broker/tests/test_firewall_controller_revoke_lifecycle_remediation.py` | New successful-revoke/lifecycle/retry tests. |
| `broker/tests/test_firewall_controller_remediation_authorization_storage_allowlists.py` | New ID-03/04/05/06 tests. |

No existing assertion was weakened. Existing tests that encoded the old permissive behavior were
updated only to the new contract: caller ownership metadata must match persistence, and helper
operation allowlists must be explicit.

## 3. Finding disposition

| Finding | Severity | Disposition |
|---|---|---|
| ID-01 — ownership binding incomplete | Medium | **Remediated (mock-only).** Caller ownership metadata is validated against persistence and never used as the source of truth. |
| ID-02 — successful revoke leaves `REVOKING` | Medium | **Remediated (mock-only).** Read-back confirmation, revocation evidence, explicit promotion, no `REVOKING -> REVOKING`. |
| ID-03 — replay before authorization | Low | **Remediated.** Authorization and ownership validation precede replay disclosure; replay is identity-bound. |
| ID-04 — storage failure reported as absence | Low | **Remediated.** Read failures raise `BrokerDBError`; controller/reconciliation fail closed. |
| ID-05 — operation allowlist defaults to all | Low | **Remediated.** Missing/empty operation allowlist denies everything. |
| ID-06 — compiled-policy validator is heuristic | Low | **Limitation documented.** Typed/bounded data validation is enforced, but no parser-level safety is claimed. |
| ID-07 — mock verify digest fidelity | Informational | Unchanged. Real backend read-back remains required. |
| ID-08 — default backend is fail-closed mock | Informational | Unchanged. Production wiring must inject a real backend. |
| ID-09 — unknown `execute_method` error before auth | Informational | Unchanged. Unknown operations are rejected; no execution occurs. |
| ID-10 — timeout validated, not enforced | Informational | Unchanged. Enforcement belongs to the future transport/process layer. |
| ID-11 — helper-side ownership binding absent | Informational | Controller now binds; real helper durability/binding remains required. |
| ID-12 — mock identity `int()` coercion | Informational | Unchanged. Real kernel-typed credentials remain required. |
| ID-13 — digest algorithm assumed by format | Informational | Bound to persisted ownership for controller operations; compiler provenance remains a real-boundary gate. |
| ID-14 — `compiled` optional in helper contract | Informational | Unchanged. Real helper must require and interpret its compiled payload. |

## 4. ID-01 — Authoritative ownership binding

### 4.1 New rule

For every non-health operation, the controller resolves the ownership record from persistence by
`policy_id` + `policy_version`. The persisted record is authoritative. Caller-supplied metadata is
only compared against it; it is never forwarded as the source of truth.

The controller now verifies, where supplied or applicable:

- `ownership_reference` / `ownership_record_id`
- `policy_id`
- `policy_version`
- `instance_id`
- `network_id`
- `compiled_rule_digest` / `canonical_policy_digest`
- `address_family` / `required_families`

Missing ownership is rejected for inspect, verify, revoke, remove, and reconciliation. A first
install may create ownership, but the generated ownership ID is persisted and used; a caller-provided
ownership reference is not adopted.

### 4.2 Helper request construction

`_authoritative_request()` rewrites every ownership-bearing field from persistence before dispatch:
ownership ID/reference, policy/version, digest, instance, network, family, and required families.
This applies to install, inspect, verify, revoke, remove, and reconciliation read-backs.

### 4.3 Evidence construction

Verification and revocation evidence is built from the persisted ownership record, not from caller
or backend-result metadata. A backend response cannot substitute `instance_id`, `network_id`,
ownership ID, or canonical digest in stored evidence.

### 4.4 Concurrency

Ownership identity is compared before and after state-changing work. If authoritative identity
(ownership ID, policy/version, instance, network, digest) changes during an operation, the operation
fails closed rather than applying the new identity to the old request.

### 4.5 Coverage

New tests cover:

- matching ownership and digest succeeds;
- spoofed instance, network, ownership reference, and ownership record ID are rejected;
- mismatched digest is rejected for inspect, verify, revoke, and remove;
- missing, wrong-version, and unrelated ownership is rejected;
- a record belonging to another instance is rejected;
- concurrent ownership change invalidates an old request;
- reconciliation rejects caller mismatches and uses persisted fields;
- first install ignores a caller-supplied ownership reference;
- evidence cannot be spoofed by backend verify output.

## 5. ID-02 — Successful revoke lifecycle

### 5.1 Explicit transition table

```text
REQUESTED        -> VALIDATING, INSTALLING, FAILED
VALIDATING       -> INSTALLING, FAILED
INSTALLING       -> VERIFYING, VALIDATING, CLEANUP_PENDING, FAILED
VERIFYING        -> VERIFIED, CLEANUP_PENDING, FAILED
VERIFIED         -> ACTIVE, REVOKING, FAILED
ACTIVE           -> REVOKING
REVOKING         -> REVOKED, CLEANUP_PENDING
CLEANUP_PENDING  -> REVOKING, REVOKED, ORPHANED, FAILED
FAILED           -> CLEANUP_PENDING, ORPHANED
REVOKED          -> (terminal)
ORPHANED         -> CLEANUP_PENDING
```

A retry while already `REVOKING` does not attempt `REVOKING -> REVOKING`.

### 5.2 Successful revoke sequence

```text
ACTIVE
  -> persist REVOKING (CAS on lifecycle version)
  -> backend revoke
  -> backend read-back (inspect)
  -> require missing/revoked
  -> persist revocation evidence
  -> re-read and verify ownership identity unchanged
  -> CAS REVOKING -> REVOKED
```

`REVOKED` is reached only after read-back confirmation and persisted evidence. Backend success alone
is insufficient.

### 5.3 Failure and recovery matrix

| Condition | Response | Persisted state | Evidence |
|---|---|---|---|
| Mismatched digest / ownership | `PermissionError` before backend | Unchanged | None |
| Backend revoke error | structured error | `REVOKING` | None |
| Backend timeout / uncertain | structured error | `REVOKING` | None |
| Backend success, read-back failure | `REVOKE_UNCONFIRMED` | `REVOKING` | None |
| Backend success, evidence persistence failure | `BrokerDBError` | `REVOKING` | None (or preserved prior) |
| Backend success, `REVOKED` persistence failure | `BrokerDBError` | `REVOKING` | Revocation evidence already persisted |
| Retry while backend still present | re-issue revoke, then confirm | `REVOKING` until confirmed | None until confirmed |
| Retry after backend already revoked | read-back confirms, skip duplicate revoke | `REVOKED` after evidence | Persisted once |
| Repeated revoke after `REVOKED` | synthetic idempotent success | `REVOKED` | Existing evidence |
| Restart while `REVOKING` | reconciliation read-back + evidence-gated promotion | `REVOKED` or uncertain | Persisted before promotion |

A retry in `REVOKING` reads the backend first. If revocation is already confirmed, the backend revoke
is not re-issued. If the backend still has the policy, revoke is retried. If read-back is unavailable
or ambiguous, the request fails closed without a duplicate side effect.

### 5.4 Evidence gating

`REVOKING -> REVOKED` requires matching revocation evidence for the same ownership record, digest,
instance, and network. Reconciliation applies the same gate. A sticky `REVOKING` state is preferred
over a false `REVOKED`.

### 5.5 Coverage

New tests cover:

- successful revoke reaches `REVOKED` with evidence;
- no invalid `REVOKING -> REVOKING` history;
- mismatched digest never revokes;
- same-key replay returns the original response;
- new-key repeated revoke is idempotent without a second backend side effect;
- backend failure, timeout, and uncertain outcomes remain `REVOKING` and retry successfully;
- read-back failure stays `REVOKING` and returns `REVOKE_UNCONFIRMED`;
- retry after read-back failure does not issue a duplicate backend revoke;
- evidence and lifecycle persistence failures stay `REVOKING` and retry;
- restart/reconciliation completes only after evidence;
- concurrent revoke requests converge without an invalid transition.

## 6. ID-03 — Authorization and ownership before replay

Controller order is now:

1. authorization;
2. request validation;
3. same-key/different-payload conflict check;
4. authoritative ownership resolution and binding;
5. replay validation;
6. cached response disclosure or execution.

The cached response is never disclosed before authorization and current ownership validation. The
idempotency request digest includes authenticated `peer_uid`/`peer_gid`, so another authorized peer
cannot inherit the first peer’s cached response. Caller-supplied ownership metadata is excluded from
the digest deliberately and validated against persistence instead.

## 7. ID-04 — Storage errors are not absence

`ControllerOwnershipStore` read helpers (`get_by_policy`, `get_idempotency_record`,
`get_lifecycle_history`, `get_evidence_by_*`, `get_pending_idempotency`, `list_ownerships`) now
propagate `BrokerDBError`. Genuine absence still returns `None` or an empty list.

The controller and reconciliation no longer turn a storage failure into “no ownership record” or a
successful uncertain result. Controller read/write failures surface as errors and do not authorize
or promote state.

## 8. ID-05 — Explicit helper operation allowlists

`MockHelperAuthorizationProvider` now defaults omitted or empty `allowed_operations` to deny.
UID/GID allowlists remain explicit. Only enumerated operations execute.

Test fixtures opt in explicitly:

- `broker/tests/_helper_identity.authorized_backend()` configures `set(HelperOperation)` for tests
  that exercise the full success path;
- identity-propagation test auth does the same;
- helper-contract success fixtures configure operations explicitly.

New tests verify missing and empty operation allowlists deny, only the configured operation is
allowed, and unknown operations are rejected.

## 9. ID-06 — Compiled-policy limitation

Compiled policy remains strictly validated as bounded JSON-like data:

- allowed key set at every depth;
- depth and size bounds;
- scalar/container type restrictions;
- forbidden token rejection;
- no coercion to executable input.

This is defense-in-depth, not a parser or semantic proof. The blocklist can be bypassed by
obfuscated content, and the global nested-key allowlist may reject legitimate rule shapes. The real
helper must define and canonicalize a real compiled-policy schema and treat the payload strictly as
data. No parser-level safety is claimed here.

## 10. Test execution

All commands were run from `E:\Flag-hunt\ctf-platform-be` with `.\venv\Scripts\python.exe` on
Windows. PowerShell reports a non-zero process exit when pytest writes warnings to stderr; the pytest
summary is authoritative.

| Command | Result |
|---|---|
| `pytest broker/tests/test_firewall_controller_ownership_binding_remediation.py -q` | **24 passed**, 1 warning in 11.03s |
| `pytest broker/tests/test_firewall_controller_revoke_lifecycle_remediation.py -q` | **14 passed**, 1 warning in 10.28s |
| `pytest broker/tests/test_firewall_controller_remediation_authorization_storage_allowlists.py -q` | **20 passed**, 1 warning in 4.24s |
| `pytest broker/tests/test_firewall_controller_helper_identity_propagation.py -q` | **56 passed**, 1 warning in 0.40s |
| `pytest broker/tests/test_firewall_controller_helper_contract.py -q` | **24 passed**, 1 warning in 0.71s |
| All `broker/tests/test_firewall_controller*.py` | **247 passed**, 1 warning in 51.26s |
| `pytest broker/tests -q` | **350 passed**, 1 warning in 73.88s |
| `manage.py test instances.tests.test_manager_client` | **Ran 33 tests — OK** (0.015s) |
| `manage.py check` | **System check identified no issues (0 silenced).** |

The three new remediation files contribute **58 tests** (24 ownership binding + 14 revoke
lifecycle + 20 authorization/storage/allowlists). The warning in each pytest run is the pre-existing
Pydantic class-based-config deprecation. A separate `pytest_asyncio` deprecation is emitted by the
environment on stderr.

**Not executed / not authorized:** real UDS/`SO_PEERCRED` transport, privileged helper process,
sudo/capability changes, nftables/iptables/UFW/Docker firewall changes, routing/NAT/conntrack,
systemd/host permission changes, provisioning, and cloud/production database changes.

## 11. Residual real-boundary gates

These remain required before live integration and are not claimed by this phase:

1. Kernel-authenticated peer identity and per-connection binding.
2. Real helper executable, service account, privilege drop, capabilities, and host hardening.
3. IPC framing/size limits, deadline/cancellation enforcement, lost-response and partial-apply
   semantics, supervision/crash modes.
4. Real backend read-back and digest comparison, revocation/conntrack semantics, IPv4/IPv6 symmetry.
5. Real compiled-policy schema/canonicalizer and guaranteed data-only interpretation.
6. Helper-side durable ownership and idempotency across restarts.
7. Production backend injection and startup assertions (no default mock backend).
8. Realistic timings, concurrency, and persistence behavior beyond SQLite/mock scope.

## 12. Explicit stop

This phase stops at local mock-only remediation and reporting.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
