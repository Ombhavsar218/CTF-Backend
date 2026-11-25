# Post-J.20 Stage 1B.17 — Remediation Implementation (Mock-Only)

**Mandatory status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED

T-11, T-13, T-27 remain: OPEN — ACCEPTANCE REQUIRED

## Phase 1 — Baseline and reproduction

- HEAD before work (recorded): `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068`
- Branch before work: `main`
- Baseline snapshot (from prior review context / this session): 26 modified tracked files, 0 staged, 279 untracked collapsed / 661 untracked expanded (workspace unchanged by this milestone except newly added 1B.17 files and this doc set).
- Reproduction: created `broker/tests/test_post_j20_stage_1b17_remediation.py` and executed initial corrective runs. Initial run showed failures covering R16-01/R16-05/R16-02/R16-03/R16-04/R16-06/R16-09/R16-07 expectations. Raw evidence:
  - `docs/evidence/post_j20_stage_1b17/initial_new_suite.stdout.txt`, `initial_new_suite.exit.txt`, `initial_new_suite.meta.txt`
  - `docs/evidence/post_j20_stage_1b17/initial_new_suite_repro.stdout.txt`, `initial_new_suite_repro.exit.txt`, `initial_new_suite_repro.meta.txt`
  - `docs/evidence/post_j20_stage_1b17/corrective_new_suite_1.stdout.txt` (1 fail set after partial fixes), `corrective_new_suite_2.stdout.txt`, `corrective_new_suite_final.stdout.txt`, `corrective_new_suite_final.exit.txt`, `corrective_new_suite_final.meta.txt`

## Phase 2 — Identity and authorization (R16-01, R16-05, R16-08)

### R16-01 (`broker/app/auth.py`)

- Existing behavior: test-transport headers (`X-Broker-Peer-*`) were merged with attached `request.state.peer_credentials` using `{**real_peer, **peer_info}` style logic where the merged result could allow header-sourced fields to influence the final `peer_info` passed to the authorizer depending on order in the original code path; conflicting identities could be ambiguous.
- Change (minimal, mock/test contract explicit): when trusted transport credentials (`request.state.peer_credentials`) are present, they are the only identity source. Conflicting header values are ignored and audited via `broker.identity.header_conflict_ignored` with field names only (no values). When no trusted transport credentials are present, the mock/test header abstraction remains available (unchanged semantics for legacy tests).
- Mock identity contract (documented in code comment): headers are not kernel-authenticated; no SO_PEERCRED/UDS trust claim added here. This is test-transport only.
- Evidence: `broker/tests/test_post_j20_stage_1b17_remediation.py::test_r16_01_trusted_mock_peer_identity_cannot_be_overridden_by_headers`, `test_r16_01_conflicting_headers_do_not_change_trusted_identity`, `test_r16_01_mock_header_contract_remains_available_without_trusted_transport` (pass in final suite).

### R16-05 (`broker/firewall_controller_service/authorization_strict.py`, `broker/firewall_controller_service/authorization.py`)

- Existing behavior: `StrictAuthorizationProvider` rejected caller-supplied trusted flags when `controller_verified` was not set to truthy in a specific branch, leaving a bypass path where `controller_verified=True` could suppress rejection for fields like `trusted`/`verified`. `MockAuthorizationProvider` had a similar `verified`+`controller_verified` exception.
- Change: reject any of the listed trusted-flag fields when set truthy regardless of `controller_verified`. `MockAuthorizationProvider` no longer honors the `controller_verified` alias to suppress rejection of `verified`.
- Evidence: `test_r16_05_caller_controller_verified_cannot_suppress_strict_rejection[...]`, `test_r16_05_service_rejects_caller_trust_flag_without_ownership_side_effect`, `test_r16_05_mock_authorizer_also_rejects_controller_verified_alias`.

### R16-08

- Documented absence of production wiring for controller/authorizer/UDS transport remains unchanged by this milestone (no real UDS, no production wiring added). Evidence is captured in prior 1B.16 documentation; this milestone does not implement production transport wiring.

## Phase 3 — Reconciliation and ownership (R16-02, R16-03, R16-06)

### R16-02 (`broker/firewall_controller_service/controller_service.py`)

- Existing behavior: several successful promotion paths persisted lifecycle transitions but did not always persist reconciliation decision/status via the guarded `reconciliation_status` write in the same logical outcome, leaving stale `reconciliation_status` possible after promotions.
- Change (minimal): after successful guarded lifecycle transitions for promotions, perform guarded `_set_reconciliation_status(..., allowed_states=(...) )` writes (`ok` for ACTIVE/REVOKED as appropriate) and treat write conflicts/failures as fail-closed/uncertain outcomes per existing contract. Audit remains inside the guarded status write transaction when applicable.
- Evidence: `test_r16_02_verified_promotion_persists_reconciliation_status`, `test_r16_02_revoke_confirmation_persists_reconciliation_status`, `test_r16_02_verifying_recovery_persists_reconciliation_status`, `test_r16_02_status_persistence_failure_is_fail_closed`, `test_r16_02_status_cas_conflict_is_uncertain_not_reconciled`.

### R16-03 (`broker/firewall_controller_service/rule_schema_v1.py`)

- Existing behavior: validator attempted heuristic ownership-network inference from arbitrary ownership dict keys (e.g. `network_cidr`, `network_cidrs`) when a record was passed; in practice this could be misleading/inoperative.
- Change: do not silently infer scope. If `ownership_rec` is provided but contains any unsupported CIDR-scope-like keys and no explicit `owned_network_cidrs` list, raise `UNSUPPORTED_OWNERSHIP_SCOPE`. If explicit `owned_network_cidrs` (list of canonical CIDR strings) is provided, enforce subnet containment for normalized rule CIDRs by IP version. Absence of any scope claim remains backward-compatible (no enforcement) for existing flows.
- Evidence: `test_r16_03_unsupported_heuristic_ownership_claim_is_rejected`, `test_r16_03_explicit_owned_cidrs_are_enforced_when_supplied`, `test_r16_03_no_ownership_context_remains_backward_compatible`.

### R16-06 (`broker/firewall_controller_service/controller_service.py`)

- Existing behavior: reconciliation pending-ledger filtering used prefix matching (`resource_key.startswith(policy_id)`) allowing overlaps such as `p1` matching `p10:1`.
- Change: exact resource-key match (`policy_id:policy_version`) via `_resource_key_matches_policy(...)` helper.
- Evidence: `test_r16_06_pending_ledger_filter_does_not_match_overlapping_prefix`, `test_r16_06_ledger_filter_is_exact_in_both_directions`.

## Phase 4 — Canonical policy integrity (R16-04, R16-09)

### R16-04 (`broker/firewall_controller_service/rule_schema_v1.py`, `controller_service.py`)

- Existing behavior: validation accepted `canonical_policy_digest` equal to `compiled_rule_digest` as an alias.
- Change: require `canonical_policy_digest` to equal the full canonical digest computed from complete canonical inputs (including identity/metadata/families/rules binding). Alias acceptance removed. At helper boundary, do not synthesize canonical digest from compiled-rule digest; forward only caller-supplied canonical digest when present as a string.
- Evidence: `test_r16_04_compiled_rule_digest_is_not_a_canonical_policy_digest`, `test_r16_04_complete_canonical_digest_is_accepted_and_bindings_independent`.

### R16-09 (`broker/firewall_controller_service/rule_schema_v1.py`)

- Existing behavior: non-empty `compiled` dicts without `schema_version`/`rules` could be treated permissively in some paths; legacy-marker detection was depth-limited.
- Change: any non-empty `compiled` representation is validated against mirror contract (unknown fields rejected; required fields enforced when present in schema-v1 shape). Legacy marker detection walks the structure with a node budget (no silent depth-bypass). Empty `{}` remains the explicit legacy/no-mirror marker.
- Evidence: `test_r16_09_nonempty_compiled_representation_is_always_validated`, `test_r16_09_nested_legacy_markers_are_detected_beyond_old_depth_bound`, `test_r16_09_empty_legacy_compiled_object_remains_compatible`.

## Phase 5 — Error handling (R16-07)

### R16-07 (`broker/firewall_controller_service/mock_helper_executor.py`)

- Existing behavior: helper execution failures returned `str(e)[:200]` in outward error message.
- Change: outward error message is bounded and non-disclosing (`"Internal helper execution error; see internal audit"`); exception type is recorded in internal audit only.
- Evidence: `test_r16_07_internal_helper_exception_text_is_not_returned`.

## Phase 6 — Tests and verification summary

- New suite: `broker/tests/test_post_j20_stage_1b17_remediation.py` (27 passed, final).
- Focused regressions (all passed): auth/authorization + helper contract + broker app auth/integration suites; reconciliation/lifecycle suites; canonical integrity suites; idempotency/concurrency suites.
- Full broker suite: `1032 passed, 1 warning` (383.45s), exit 0.
- Django manager client: `33 tests OK`, exit 0.
- `manage.py check`: no issues, exit 0.
- Raw evidence root: `docs/evidence/post_j20_stage_1b17/` (initial/corrective/focused/final runs with `.stdout.txt`, `.stderr.txt`, `.exit.txt`, `.meta.txt` as applicable).

## Unresolved / out of scope

- No production UDS/SO_PEERCRED wiring, no kernel identity claims, no privileged helper/host firewall/Docker/live operations performed.
- R16-08 remains documented as absent production wiring (no implementation in this milestone).
- Any further changes to production wiring, migrations, or live integration require explicit authorization and are outside this mock-only remediation.
