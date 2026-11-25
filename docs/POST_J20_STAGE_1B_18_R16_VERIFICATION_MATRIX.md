# Post-J.20 Stage 1B.18 — R16 Verification Matrix (Independent, Read-Only)

**Mandatory status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED

No source, test or raw evidence was modified. No tests were executed in Stage 1B.18. Raw evidence references are Stage 1B.17 artifacts.

## 1. Summary matrix

| ID | Source location | Test location | Raw evidence reference | Independent result | Classification | Remaining limitation |
|---|---|---|---|---|---|---|
| R16-01 | `broker/app/auth.py:22-62`; `broker/app/authorization.py:23-45` | `broker/tests/test_post_j20_stage_1b17_remediation.py:98-175` | `corrective_new_suite_final.{stdout,exit}.txt`; `focused_auth_authorization.*`; `full_broker_suite.*` | Trusted attached credentials win; header conflicts ignored and audited by field name. Malformed inputs fail closed. | VERIFIED FIXED (scoped) | No runtime code attaches `peer_credentials`; header-only identity remains default. A non-dict peer with a raising `to_dict()` produces an unhandled 500 (denial, no grant). |
| R16-02 | `controller_service.py:1690-1739`, `:1902-1934`, `:1945-2013`, `:2015-2048`, `:2052-2125`, `:2127-2206` | `test_post_j20_stage_1b17_remediation.py:205-271`; `test_post_j20_stage_1b14_persistence_reconciliation_residuals.py:319-335` | `corrective_new_suite_final.*`; `corrective_new_suite_1/2.*`; `focused_reconciliation_lifecycle.*` | Three named promotions correctly guarded; broader status-consistency claims not supported. | PARTIALLY MITIGATED | No-status `reconciled` paths (`revoke_already_confirmed`, `already_revoked`, terminal no-change); unsafe conditional `status_written` at `:2030`; promotion and status writes are separate transactions and the window is undocumented. |
| R16-03 | `rule_schema_v1.py:419-478`; callers `controller_service.py:928`, `helper_contract.py:240-241`, `app/firewall_controller.py:78`; schema `ownership_store.py:135-152` | `test_post_j20_stage_1b17_remediation.py:276-305` | `corrective_new_suite_final.*`; `final_changed_files.txt` | Check exists and rejects heuristic claims when passed a record, but no production caller passes ownership context and no CIDR column is persisted. | OPEN | Out-of-scope CIDR installs still succeed at every real ingress; test `:305` codifies fail-open absence of scope. No authoritative scope source exists. |
| R16-04 | `rule_schema_v1.py:491-511`; `controller_service.py:418,490,552,1161`; `ownership_store.py:779-785,921-925`; `helper_contract.py:206-207` | `test_post_j20_stage_1b17_remediation.py:346-380` | `initial_new_suite.stdout.txt:293-303`; `corrective_new_suite_final.*`; `final_changed_files.txt` | Schema-level rules-only alias removed for supplied canonical digest; canonical digest remains optional and aliases remain in persisted ownership/body binding. | PARTIALLY MITIGATED | Caller can omit `canonical_policy_digest`; persisted `canonical_policy_digest` is normally the compiled rule digest and the ownership-store alias is forceable on first-install state. |
| R16-05 | `authorization_strict.py:17-47`; `authorization.py:17-20`; `helper_contract.py:74-78,171-173` | `test_post_j20_stage_1b17_remediation.py:178-200`; `test_firewall_controller_j16_authorization_identity.py:143-150` | `corrective_new_suite_final.*`; `focused_auth_authorization.*` | Suppression by `controller_verified` removed for the six named flags. | PARTIALLY MITIGATED | Rejection is `is True` only; truthy non-booleans pass. `controller_verified`, `authorized`, `is_admin` are not rejected by providers despite being forbidden claims at helper boundary. No current escalation found. |
| R16-06 | `controller_service.py:32-44`, `:2233-2234`; ID regex `:68`; replay comparator `:590` | `test_post_j20_stage_1b17_remediation.py:310-341` | `corrective_new_suite_2.stdout.txt:28,66`; `corrective_new_suite_final.*` | Simple `p1`/`p10` overlap fixed. | PARTIALLY MITIGATED | `partition(':')` ignores version and is ambiguous for valid colon-containing IDs; NULL/empty `resource_key` bypasses filter; full-scan test was removed rather than fixed. |
| R16-07 | `mock_helper_executor.py:65-77,99-103,145-152`; `helper_contract.py:242-245`; `error_sanitization.py:22-60`; `controller_service.py:281-304,729-741` | `test_post_j20_stage_1b17_remediation.py:406-433`; `test_post_j20_stage_1b13_canonical_validation_sanitization.py:258-370` | `corrective_new_suite_final.*`; `focused_canonical_integrity.*` | Generic execution exception return is bounded and type-only internally. | PARTIALLY MITIGATED | Validation-error return forwards schema/internal `e.code`/`e.message`; `helper_contract.py:244` has `str(e)` fallback; controller `result`/`details` are not scrubbed. |
| R16-08 | `broker/app/main.py:9-16`; `routes.py`; `uds.py:20-44`; `auth.py:13-21` | No production-wiring test exists or is claimed | 1B.17 residual/final docs; raw mock-only run artifacts | No production wiring found; docs accurately state absence. | VERIFIED DOCUMENTATION / OPEN BY DESIGN | Controller security properties remain library/mock-only. Underlying condition is unresolved and out of authorized scope. |
| R16-09 | `rule_schema_v1.py:331-427` | `test_post_j20_stage_1b17_remediation.py:383-401`; `test_post_j20_stage_1b15_boundary_persistence_integrity.py:205-278` | `initial_new_suite.stdout.txt:304-323`; `corrective_new_suite_final.*`; `focused_canonical_integrity.*` | Non-empty compiled mirrors validated; deep legacy markers detected with node budget; mixed representations rejected. | VERIFIED FIXED (scoped) | No-rules path returns at `:434` before mirror validation; 10,000-node budget does not bound raw ingress payload bytes. Legacy `{}` carve-out remains documented. |
| R16-10 | `docs/evidence/post_j20_stage_1b17/` (50 files) | N/A (evidence review) | all `.stdout/.stderr/.exit/.meta.txt`, `final_git_state.txt`, `final_changed_files.txt` | Run-level artifacts complete; narrative inaccuracies found. | IMPROVED, NOT CLOSED | Unsupported R16-04 cause, inverted Django stream attribution, mislabeled git counts, elapsed-like `STARTED=`, removed full-scan test; historical 1B.13–1B.15 gaps remain. |

## 2. Finding-by-finding inspection detail

### R16-01 — header spoofing / trusted identity precedence

`auth.py:34-49` attaches precedence to `request.state.peer_credentials`. Header values are parsed at `:22-32` and used only for conflict comparison at `:40-43`; conflict audit logs only `path` and sorted field names (`:45-48`). With a real peer dict, `peer_info = trusted_peer` (`:49`). With no real peer, the mock header seam remains active (`:51`). Empty trusted data reaches `verify_peer({})`, which raises (authorization module `:23-24`), and malformed header integers 401 before trust resolution.

No non-test assignment to `request.state.peer_credentials` exists in `broker/app`; `uds.py` is an extraction helper with no caller. Every wired route uses `Depends(require_broker_auth)`. Consequently, the precedence fix is correct but currently vacuous at runtime. The mock seam is explicitly documented as non-kernel at `auth.py:13-21`.

### R16-02 — reconciliation promotion status

Guarded writer `_set_reconciliation_status` (`:1690-1739`) requires a guard context manager and non-empty allowed states, re-reads the authoritative record, verifies unchanged identity, checks the fresh state is in `allowed_states`, binds the decision via `_validate_ownership_binding`, and performs status + audit in one `atomic_write()` with lifecycle-version CAS. `PermissionError` returns `False` (conflict), and `BrokerDBError` is caught by callers as persistence failure.

Named original promotions now write status: `promoted_to_active` (`:1925`), `revoke_confirmed` (`:2084`) and `verifying_recovered_with_evidence` (`:2188`); `active_ok` and `marked_needs_verification` also write status.

Remaining gaps proved by source:

- `revoke_already_confirmed` (`:2060-2065`) and `already_revoked` (`:2123-2124`) append `reconciled` with no status write.
- terminal no-change outcomes at `:2209-2211` likewise report reconciled without status refresh.
- `status_written` at `:2030` is assigned only inside `if prev in (...)`. A concurrent state change leaves it unbound (first iteration → generic uncertain) or stale-True from a previous target (later iteration → false `reconciled` at `:2047`).
- lifecycle state/history commits (e.g. `:1914-1920`, `:2073-2081`, `:2166-2184`) precede the status transaction. A crash or DB failure between them leaves promoted state with stale status. The Stage 1B.17 implementation doc calls this “same logical outcome” without disclosing the window.
- CAS failure appends `uncertain` and leaves durable promoted state with stale status; the Stage 1B.17 test asserts only response-level uncertainty, not final state/status consistency.

### R16-03 — ownership CIDR scope

`validate_install_policy_rules(req, ownership_rec=None)` enforces scope only inside `if ownership_rec and isinstance(ownership_rec, dict)` (`rule_schema_v1.py:443`). Unsupported heuristic fields are rejected (`:449-456`), and explicit `owned_network_cidrs` are validated and enforced (`:457-478`). However:

- all three production callers omit `ownership_rec` (`controller_service.py:928`, `helper_contract.py:241`, `app/firewall_controller.py:78`);
- `controller_ownership` has `network_id` but no CIDR column (`ownership_store.py:135-152`);
- repo grep found `owned_network_cidrs` only in the validator and the new test;
- the Stage 1B.17 test at `:305` explicitly asserts that absence of ownership context remains backward-compatible.

The original Stage 1B.16 requirement was to pass authoritative ownership/network context and enforce scope (or remove/relocate the dead check with explicit documentation). Neither occurred. Original finding remains OPEN.

### R16-04 — canonical digest binding

`rule_schema_v1.py:492-511` now requires a supplied canonical digest to equal the full `canonical_policy_digest()` computed over policy identity, version, ownership reference, families, instance/network and normalized rules. This closes the exact schema-level alias quoted in Stage 1B.16.

However, `canonical_policy_digest` is optional at ingress (`broker/app/firewall_controller_contract.py:53`). Controller code still derives authoritative digests with `compiled_rule_digest or canonical_policy_digest` (`controller_service.py:418,490,552`), persists the compiled digest as `canonical_policy_digest` on first install (`:1161`), and the ownership store accepts the rules-only digest as a canonical alias (`ownership_store.py:779-785`) and as proof on trusted read (`:921-925`). The Stage 1B.17 residual statement that the alias is “not a caller-accepted canonical digest at ingress” is too narrow: a caller-derived `compiled_rule_digest` reaches `expected_digest` at `:552` and is accepted at `ownership_store.py:924`.

### R16-05 — caller-controlled trusted flags

`StrictAuthorizationProvider.authorize()` rejects six flag names with `is True` before checking peer identity (`authorization_strict.py:23-25`); `MockAuthorizationProvider` rejects `verified` and `caller_trusted` (`authorization.py:17-20`). Because the rejection no longer checks `controller_verified`, the original suppression is removed and tests pass with `controller_verified=True`.

The invariant is incomplete: truthy non-boolean values are accepted; `controller_verified`, `authorized` and `is_admin` are listed as forbidden claims in `helper_contract.py:74-78` but are not rejected by either provider; the mock provider rejects only 2 of 15 forbidden fields. No consumer currently grants authority from those fields, so this remains an invariant/defense-in-depth gap rather than demonstrated escalation. A stale claim at `POST_J20_STAGE_1B_12_RESIDUAL_GAP_INVENTORY.md:53` (“strict mode rejects `controller_verified`”) is unsupported by current source.

### R16-06 — exact policy identity

`_resource_key_matches_policy()` (`:32-44`) splits on the first colon and compares only the head when a colon exists. It fixes `p1` vs `p10:1` but fails exactness:

- `p1:1` and `p1:2` both match `policy_id='p1'`;
- policy IDs may contain `:` (`_ID_RE` at `:68` is `[A-Za-z0-9._:-]{1,128}`), so `a:b:1` is dropped for `a:b` and wrongly included for `a`;
- rows with NULL/empty `resource_key` bypass the filter entirely (`:2233`);
- replay binding at `:590` uses exact full-string equality, demonstrating inconsistent identity semantics.

The `test_r16_06_full_scan_keeps_overlapping_identities_distinct` case failed in `corrective_new_suite_2` (`Missing policy_id` from the public validator) and is absent from the final 27-test suite. The final green run therefore no longer exercises that path.

### R16-07 — outward error leakage

`mock_helper_executor.py:145-152` now returns `EXECUTION_ERROR` with fixed text `Internal helper execution error; see internal audit`, and logs only `type(e).__name__`. This closes the exact `str(e)[:200]` finding.

The outward validation path at `:99-103` still returns `e.code` and `e.message` verbatim from `HelperContractError`; `helper_contract.py:242-245` forwards `RuleSchemaError.message` and falls back to `str(e)`. The controller sanitizer (`:281-304`) rewrites `error_message` for error responses, but `result` and `details` are not scrubbed (for example `_revoke_unconfirmed_response` at `:729-741`). The Stage 1B.17 residual claim “Outward helper errors bounded/non-disclosing” is broader than the source supports.

### R16-08 — production wiring limitation

No production route, app factory or middleware wires `FirewallControllerService`, strict allowlists, `BrokerAuthorizer` peer-credential attachment or UDS identity. `auth.py:13-21` explicitly labels its contract MOCK/TEST-ONLY. Stage 1B.17 docs consistently state that no real UDS/kernel identity or production wiring was added. This documentation is verified; the underlying security condition remains OPEN BY DESIGN and out of authorized scope.

### R16-09 — representation-independent validation

`validate_compiled_mirror()` (`:331-369`) rejects non-empty unknown representations, requires exact schema version and rules, enforces depth/string bounds and compares byte-for-byte canonical rules. `_contains_legacy_flat_rule_markers()` (`:372-394`) uses an iterative stack with a 10,000-node budget and detects markers at any depth. `validate_no_mixed_rule_representations()` (`:397-416`) rejects legacy markers in the request and compiled subtree before any branch. The reported bypasses are fixed.

Limitations: the no-rules path returns at `:434` before `validate_compiled_mirror()`; the empty `{}` carve-out remains a documented legacy marker; and there is no ingress request-byte limit, so the node budget is a structural bound rather than a full payload-size control.

### R16-10 — evidence completeness

See `POST_J20_STAGE_1B_18_EVIDENCE_INTEGRITY_REPORT.md`. Raw run-level evidence is complete; narrative and governance claims are not fully accurate.

## 3. Conclusion

Only R16-01 and R16-09 are fully verified for the defects as scoped; R16-08 documentation is verified while the condition remains open. R16-02, R16-04, R16-05, R16-06 and R16-07 are partially mitigated, R16-03 is open, and R16-10 remains improved but not closed. This does not support Outcome A.

Final status: **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
