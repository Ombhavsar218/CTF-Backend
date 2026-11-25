# Post-J.20 Stage 1B.16 — Independent Mock-Only Security Review

**Date:** 2026-11-18
**Type:** Independent, review-only assessment (no implementation, no test execution, no host/live operations)
**Repository:** `E:\Flag-hunt\ctf-platform-be`
**Scope:** Mock-only firewall-controller work through Stage 1B.15 (J.1–J.20, Stage 1A / 1A.1–1A.5, Stage 1B.0–1B.15)

> **MANDATORY STATUS — NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
>
> T-11, T-13 and T-27 remain **OPEN — ACCEPTANCE REQUIRED**. This review changes no gate
> status, no acceptance state, no risk disposition, and creates no authority approval.

---

## 1. Mandatory boundary observed

This milestone was conducted strictly as a review:

- No application source or test file was modified.
- No Docker daemon/socket or runtime operation was performed.
- No UDS / `SO_PEERCRED` / kernel-identity implementation was performed.
- No privileged helper, Linux capability, nftables/iptables/DOCKER-USER or host firewall operation was performed.
- No host permission change, host validation, cloud, production or live-backend operation was performed.
- No Stage 1C work was started.
- No test was executed. Findings were derived from source inspection and from already-preserved raw artifacts. Historical completion reports were treated as claims to be challenged, not as proof.

## 2. Phase 1 — Repository and evidence baseline

### 2.1 Git baseline (before review)

| Item | Before review |
|---|---|
| HEAD | `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` |
| Branch | `main` |
| Modified tracked files | 26 |
| Untracked entries (`git status --porcelain`, collapsed-directory method) | 279 |
| Untracked files (`git ls-files --others --exclude-standard`, expanded) | 656 |
| Staged files | 0 |

The 26 modified tracked files are the same set recorded in `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md` §1.1 and preserved by `post_j20_stage_1b15_initial_git_state.txt` / `post_j20_stage_1b15_final_git_state.txt`. Untracked work includes the entire `broker/`, `manager/`, `docs/`, `instances/`, `audit/`, `ops/`, `platform_settings/` trees and the raw evidence `.txt` files. No reset, clean, revert, stage, commit or deletion was performed.

**Counting-methodology note:** the historical 1B.15 artifacts (249 → 279) count collapsed `?? ` entries via `git status --porcelain`. An expanded `git ls-files --others` count yields 656 individual files. Both are reported so the difference is not mistaken for user-work loss.

### 2.2 Evidence corpus actually inspected

- Gate register: `docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md`; risk dispositions: `docs/PHASE_2L_2J_2_RISK_DISPOSITION_RECORDS.md`; J.20 final decision/traceability/trust/limitations/ledger documents.
- Stage 1B.5/1B.8 finding definitions: `POST_J20_STAGE_1B_5_FINAL_RISK_REGISTER.md`, `POST_J20_STAGE_1B_8_ACCEPTANCE_DECISION_MATRIX.md`.
- Authority chain: `POST_J20_STAGE_1B_10_AUTHORITY_DECISION_TRACKER.md`, `POST_J20_STAGE_1B_11_AUTHORITY_RESPONSE_INTAKE.md`, `POST_J20_STAGE_1B_11_DECISION_RECONCILIATION_MATRIX.md`, `POST_J20_STAGE_1B_12_AUTHORITY_AND_HOST_BLOCKER_MAP.md`.
- Stage 1B.13/1B.14/1B.15 implementation, evidence, residual and verification documents.
- Raw artifacts: `docs/evidence/post_j20_stage_1b15/*` (20 files: 10 stdout + 10 exit), `post_j20_stage_1b1*.txt` … `post_j20_stage_1b15*.txt`, `j17_broker_*.txt`, `j18_broker_full.txt`, `j19_broker_full.txt`, `post_j20_stage_1a*/1a1*/1a2*/1a5*`.
- Source under `broker/` (app and firewall-controller service) and test source under `broker/tests/`.

### 2.3 Evidence limitations recorded up front

- No test was executed in this milestone; test results below are attributed to raw artifacts, not to independent execution.
- No authored final SHA-256 snapshot exists for Stage 1B.15; preservation was corroborated by read-only recomputation against `post_j20_stage_1b15_initial_file_hashes.txt`.
- Some historical counts (`218 passed`, J.18 `16 passed`, J.19 `28 passed`) are **reported-only** with no matching raw artifact in the repository.
- No `*_stderr.txt` artifacts exist in the 1B.13/1B.14/1B.15 evidence sets despite documentation that says "stdout/stderr".
- No exit-code artifacts exist for the `j17`/`j18`/`j19` full-suite runs.
- `docs/PHASE_2L_2J_20_IMPLEMENTATION_EVIDENCE_LEDGER.md` ends at J.19; Stage 1A/1B material is recorded in the gate register and post-J.20 documents instead.
- Source-level absence of a production wiring point for `FirewallControllerService`, `BrokerAuthorizer` configuration, and UDS credential attachment means mock-boundary controls cannot be treated as deployed-runtime controls.

---

## 3. Phase 2 — Independent security review by domain

### A. Authentication and authorization

**A.1 Strict controller defaults — partially verified (scoped).**
`broker/firewall_controller_service/controller_service.py:73-88` constructs `StrictAuthorizationProvider` by default with empty UID/GID allowlists; `strict_auth=False` without an explicit provider raises `FirewallControllerAuthError` (`controller_service.py:85-88`). `authorization_strict.py:27-44` rejects missing/malformed identity, empty allowlists, unlisted operations, and non-allowlisted UID/GID. `broker/tests/test_firewall_controller_j16_authorization_identity.py:99-176` asserts these properties. This supports the documented "implicit non-strict construction rejected" improvement for the covered constructor path.

**A.2 Explicit `auth=` injection remains a test seam.** `controller_service.py:77-79` accepts any injected provider; `authorization.py:5-20` (`MockAuthorizationProvider`) accepts caller `source_component`/`caller_source` and computes `allowed_sources` without using it. This is only reachable by code that constructs the service, not by a request alone. It is **not** kernel identity proof (SR-06/I-09).

**A.3 NEW FINDING R16-01 — broker HTTP caller headers override UDS peer credentials.**
`broker/app/auth.py:15-22` builds `peer_info` from `X-Broker-Peer-*` headers. At `auth.py:27-33`:

```python
real_peer = getattr(request.state, "peer_credentials", None)
if real_peer is not None:
    if isinstance(real_peer, dict):
        peer_info = {**real_peer, **peer_info}  # real creds take precedence conceptually
```

Python dict expansion gives the **second** mapping precedence, so caller headers override `real_peer` despite the comment. `broker/app/authorization.py:9-17` constructs the module-global `authorizer = BrokerAuthorizer()` with `uid=-1`, `gid=-1`, `broker_token=""`; `verify_peer` therefore performs no UID/GID check and no token check (`authorization.py:26-45`, `:43-45`), leaving only the default username `flaghunt-mgr` enforced. `BrokerSettings` (`broker/app/config.py:12-16`) is not wired to this authorizer. `require_broker_auth` is applied to all broker HTTP routes (`broker/app/routes.py:44,50,136,163,192,219,277`). Repository-wide search found **no** non-test assignment to `request.state.peer_credentials`; UDS extraction exists at `broker/app/uds.py:20-44` but is not attached in inspected runtime paths. No test asserts header-vs-UDS precedence (`broker/tests/test_broker.py:17-101` uses header identity only; `test_broker_uds.py` tests `BrokerAuthorizer` directly).

**Assessment:** this is a concrete source-level defect in a live-wired module. In the current mock-only runtime it is a documented test-transport seam; once UDS is connected, `R16-01` becomes a kernel-identity bypass. It must be corrected and regression-tested inside the mock-only boundary before authority review.

**A.4 NEW FINDING R16-05 — `controller_verified=True` suppresses trusted-flag rejection.**
`authorization_strict.py:20-23` rejects caller-supplied `caller_trusted`/`verified`/`trusted`/`auth_identity`/`x_identity`/`source_identity` only when `req.get("controller_verified") is not True`. `MockControllerTransport._inject_peer` (`mock_transport.py:11-18`) overwrites only `peer_uid`/`peer_gid`, so a caller-supplied `controller_verified=True` survives into `authorize()`. Impact is bounded: no other production code grants authority from those flags (grep found them only in rejection lists and `helper_contract.py:76-77` forbidden claims), and UID/GID allowlists still apply. This is an invariant violation, not a demonstrated privilege escalation.

**A.5 Ownership enforcement — partially verified, with NEW FINDING R16-03.**
Authoritative request rebuilding is implemented at `controller_service.py:427-446` (ownership reference, policy id/version, digest, instance/network, family are overwritten from the persisted record), caller-vs-authoritative checks at `:344-425`, and helper claims are stripped at `mock_backend.py:10,55-67`. However, CIDR scope enforcement in `rule_schema_v1.py:425-453` runs only when an `ownership_rec` dict is passed, and the production install call at `controller_service.py:904` passes none. Moreover, `controller_ownership` stores `network_id` but no CIDR column (`ownership_store.py:135-152`, `:391-392`), so the owned-network inference loop (`rule_schema_v1.py:429-445`) could not find an owned network even if the record were passed. **No rule is currently checked against the owned challenge network at the covered ingress.** This is a concrete ownership-enforcement gap, not merely a documentation limitation.

### B. Canonical validation and schema separation

**B.1 Verified (scoped).** `rule_schema_v1.py:72-75` rejects unknown fields; `:194-303` validates/normalizes rules; `:254-303` rejects duplicates, ambiguity, bad `required_families` and family mismatches. `controller_service.py:899-917` validates before ownership/idempotency side effects; `request_validator.py:6-15` suppresses raw internal exceptions; `helper_contract.py:164-257` enforces exact schema version and forbidden claims. `broker/app/firewall_controller.py:72-90` adds canonical validation on the mock state-install boundary. Stage 1B.15 added exact legacy-marker rejection (`rule_schema_v1.py`, per `POST_J20_STAGE_1B15_BOUNDARY_MATRIX.md`) and tests at `test_post_j20_stage_1b15_boundary_persistence_integrity.py:141-229`. Raw evidence: `docs/evidence/post_j20_stage_1b15/initial_new_suite_*` (5 failed / EXIT 1, preserved) followed by `corrective_new_suite_*` (21 passed / EXIT 0).

**B.2 NEW FINDING R16-09 — compiled-mirror validation is representation-dependent.** `rule_schema_v1.py:336-339` returns early when `compiled` contains neither `schema_version` nor `rules`; legacy-shaped compiled payloads therefore skip strict mirror validation. `MAX_COMPILED_DEPTH = 6` (`:31`) bounds legacy-marker detection (`:371-380`). Tests cover schema-v1 mirrors and 1B.15 mixed/legacy rejection, but not deep-nested or alternative legacy compiled representations.

**B.3 NEW FINDING R16-04 — digest alias weakens canonical binding.** `rule_schema_v1.py:482-486` accepts `provided_cpd` when it equals either the full `canonical_policy_digest` or the compiled-rule digest `crd`. The compiled digest covers rules but not the ownership/policy context (`policy_id`, `policy_version`, ownership reference, instance/network, families) that `canonical_policy_digest()` includes (`:473-481`). This is explicitly labelled legacy/mock compatibility, but in schema-v1 paths it permits a policy-context digest to be represented by a rules-only digest.

**B.4 Legacy isolation.** No silent legacy→canonical conversion was found in inspected paths; legacy `firewall_state.py` has no non-test caller. `broker/app/firewall_controller_contract.py:52-74` enforces canonical identifiers. `R16-09`/`R16-04` are the two scoped validation weakenings above; universal deployed-envelope closure remains N-02/H-05/M-08/SR-13.

### C. Error handling and information leakage

**C.1 Verified (scoped).** `error_sanitization.py:22-28` defines fixed public messages; `:49-51` `sanitize_backend_message()` ignores the supplied message and returns the fixed default; `controller_service.py:263-287` remaps outward error messages by code and sanitizes backend text; `:1580-1642` classifies exceptions by allowlisted type. `BrokerDBCanonicalError` categories are typed (`ownership_store.py:15-24`), not message-substring based. Tests: `test_post_j20_stage_1b13_canonical_validation_sanitization.py:258-370`, `:471`.

**C.2 R16-07 — raw exception text at mock helper boundary (bounded, internal).** `mock_helper_executor.py:145-147` returns `str(e)[:200]` in `error_message`. This is not an allowlisted message. It is not an outward controller leak in inspected paths because the controller sanitizer replaces it, and the helper is a mock component; it remains a scoped internal-boundary limitation. `helper_contract.py:238-245` also propagates rule-schema message text internally.

**C.3 Legacy fail-open (residue 4, confirmed).** `broker/app/firewall_state.py:48-55` (`get`), `:93-99` (`has_valid_verification_evidence`) and `:157-161` (`list_by_instance`) convert storage failures to `None`/`False`/`[]`. No non-test production caller was found (only `test_firewall_policy.py:5` and `test_firewall_lifecycle_integrity.py:5` import it). Related library-only swallow paths exist at `audit_persistent.py:27-42` and `ownership_store_persistent.py:62-85`. Scope description in Stage 1B.15 remains accurate; it is a library-only fail-open, not a canonical-controller path.

### D. Persistence and integrity

**D.1 Residues 1–3 confirmed by direct source inspection.**

- `ownership_store.py:223-241` defines `controller_policy_bodies` with one FK to ownership but **no append-only trigger**. The trigger loop at `:242-256` covers only `controller_lifecycle_history`, `controller_evidence` and `controller_audit`. The body is immutable through the store API (`INSERT ... ON CONFLICT DO NOTHING` at `:789-800`, trusted revalidation at `:869-938`) and tamper-detected on trusted read (ownership binding `:892-893`, JSON parse `:904-907`, rule revalidation `:913-916`, digest recompute `:917-927`), but a direct SQL `UPDATE` is possible. Test `test_post_j20_stage_1b15_boundary_persistence_integrity.py:426-441` is explicitly named `test_canonical_body_is_not_append_only_but_trusted_read_detects_tamper`.
- `controller_lifecycle_history` (`:155-168`), `controller_idempotency` (`:170-186`), `controller_audit` (`:195-204`) and `controller_evidence` (`:205-220`) declare **no** `REFERENCES` clause. Application-level binding is extensive (`_validate_ownership_binding` `controller_service.py:344-425`, `_ownership_identity` `:113-126`, replay checks `:543-583`, evidence validation `:623-663`).
- `BrokerDB._get_conn()` (`broker/app/db.py:50-56`) does **not** enable `PRAGMA foreign_keys`. Controller-scoped enforcement exists in `_init_schema` (`ownership_store.py:134`), `_get_conn_fk()` (`:279-288`) and `atomic_write()` (`:308-312`). Test `test_post_j20_stage_1b15_boundary_persistence_integrity.py:487-524` asserts base `foreign_keys == 0`, FK connection `== 1`, and that a base-connection orphan-body insert succeeds but is rejected by trusted read.

**D.2 Idempotency/CAS — verified (scoped).** PK `(idempotency_key, operation_type)` (`ownership_store.py:170-186`), typed conflicts (`:27-33`, `:507-513`), `request_digest` conflict (`controller_service.py:919-934`), fresh authoritative replay binding (`:543-583`), versioned lifecycle CAS (`ownership_store.py:443-473`), terminal outcome/completion CAS (`:539-640`), stale completion replay (`:1544-1577`). Tests: `test_post_j20_stage_1b4_cross_table_concurrency.py:231-361,628-670`, `test_post_j20_stage_1b15_boundary_persistence_integrity.py:444-524`.

**D.3 Residue 5 confirmed.** `ownership_store.py:290-336` explicitly labels `atomic_write()` a database-only boundary: *"Mock backend effects and filesystem state are never inside an SQLite transaction."* Backend calls occur outside transactions (`controller_service.py:671,1289,1314,1868`); evidence write (`:1439`), intent (`:1004`), IN_PROGRESS (`:1269`) and completion (`:1549`) are separate transactions. No end-to-end DB/backend atomicity exists.

**D.4 Residue 6 confirmed.** `schema_version` is seeded at 1 (`broker/app/db.py:249`); controller tables are created inline with `CREATE TABLE IF NOT EXISTS` (`ownership_store.py:128-271`); the only additive migration is the guarded `operation_outcome`/`outcome_updated_at` ALTER (`ownership_store.py:188-194`) with no backfill and no schema-version bump. No `.sql` or Django migration covers controller tables. No authoritative migration plan, down-path, deployed-schema audit or data-owner approval exists in the repository.

### E. Lifecycle, recovery and reconciliation

**E.1 Verified (scoped).** Explicit FSM at `controller_service.py:59-71` (no direct `VERIFYING→ACTIVE`; `VERIFYING→VERIFIED→ACTIVE`), centralized enforcement at `:188-192`. Backend failure fails closed (`:1418-1420`), evidence is bound to ownership/digest/identity/family (`:653-662`), revoke requires readback + evidence before `REVOKED` (`:665-764`), uncertain revoke is `UNCERTAIN`, not `SUCCEEDED` (`:806-826`), reconciliation never auto-promotes without evidence (`:1944-1977`, `:2079-2147`). Tests: `test_post_j20_stage_1b2_atomic_persistence_boundaries.py:372-427`, `test_post_j20_stage_1b3_durable_crash_recovery.py:382-448`, `test_post_j20_stage_1b15_boundary_persistence_integrity.py:384-397`.

**E.2 NEW FINDING R16-02 — successful reconciliation promotions leave `reconciliation_status` stale.** Guarded status writes are used on uncertainty/failure branches (`controller_service.py:1820-1837,1857,1912-1958,1993,2087-2102,2155`) via `_set_reconciliation_status` (`:1666-1712`). However, three successful promotion paths write ownership state and lifecycle history **without** status/audit refresh:

- `VERIFIED→ACTIVE` at `:1884-1897` (`reconcile_promote_active`) followed by `continue` at `:1906`.
- `REVOKING→REVOKED` at `:2032-2054` (`reconcile_revoke_confirmed`).
- `VERIFYING→VERIFIED→ACTIVE` at `:2110-2146` (`reconcile_verifying_evidence_verified` / `..._activated_with_evidence`).

`reconciliation_status` defaults to `pending` (`ownership_store.py:151`) and fail branches write `uncertain`. A record can therefore be `ACTIVE`/`REVOKED` with valid evidence and history while the status field still reports `pending`/`uncertain`. Promotion tests assert state/action/history but not `reconciliation_status` (`test_post_j20_stage_1b3_durable_crash_recovery.py:382-392,451-466,818-834`; `test_post_j20_stage_1b4_cross_table_concurrency.py:432-455`). This is a status/audit/evidence consistency defect in domain E.

**E.3 NEW FINDING R16-06 — prefix-based pending-ledger policy filter.** `controller_service.py:2172-2182` filters pending rows with `str(idem['resource_key']).startswith(str(policy_id))` without the `:` delimiter, while resource keys are `f"{policy_id}:{policy_version}"` (`:1003-1008`). Reconciling `p1` can include rows for `p10:1` or `p1-foo:1`, misattributing `pending_no_auto_replay` entries. No mutation occurs, so impact is accounting/misclassification only. No test covers prefix collisions.

**E.4 Reconciliation persistence classification — verified (scoped).** Guard-missing/failed branches fail closed (`:1682-1684`), initial ownership read failures propagate as `BrokerDBError` (`:1729-1733`), pending-scan failures are classified (`:2163-2170`), and final failure returns `RECONCILIATION_PERSISTENCE_FAILURE` (`:2185-2192`). Tests: `test_post_j20_stage_1b14_persistence_reconciliation_residuals.py:167-384`.

### F. Concurrency and idempotency

**F.1 Verified (scoped).** SQLite init is serialized by a file lock (`broker/app/db.py:58-116`, Windows `msvcrt.locking` / POSIX `fcntl.flock`), WAL is enabled (`db.py:118-123`, `ownership_store.py:128-134`), `atomic_write()` uses `BEGIN IMMEDIATE` with thread-local re-entrancy (`ownership_store.py:45-106,273-336`). Same-key tests assert one effect and stable ledger (`test_post_j20_stage_1b4_cross_table_concurrency.py:231-361`), cross-process conflict/fresh-init tests exist (`:694-725`, `test_post_j20_stage_1a5_fresh_db_init_initialization` artifacts), and deterministic fault hooks are test-only (J.12/J.13/1B.2/1B.3/1B.14/1B.15 suites).

**F.2 Limitations.** Cross-process tests use real spawned processes with a **file-backed mock backend** (`test_firewall_controller_cross_process_crash_recovery.py:1-12,53-172`) and `os._exit(9)` kills (`test_post_j20_stage_1b3_durable_crash_recovery.py:580-618`) — these are mock-only proofs, not host/live evidence. `test_firewall_controller_deterministic_concurrency.py:149-150` asserts only `lifecycle_version >= v0` (weak assertion; stronger coverage is in 1b4/J.13/J.18). A test inconsistency remains: `test_post_j20_stage_1b2_atomic_persistence_boundaries.py:570-588` expects an FK violation on a plain `sqlite3.connect` (no FK pragma), while `test_post_j20_stage_1b15_boundary_persistence_integrity.py:496-498` asserts base connections have `foreign_keys == 0`. This was not resolved by test execution in this milestone.

### G. Architecture and deployment boundary

**G.1 Verified as mock-only.** `MockFirewallBackend` (`mock_backend.py:13-19`), `MockHelperExecutor` (`mock_helper_executor.py:1-10`) and helper contract are explicit mocks; Docker adapters are fail-closed/unavailable in inspected runtime paths (H-02/N-04 partially resolved with J.19 negative tests). No real helper, capability set, UDS server, `SO_PEERCRED`, host firewall rule, privileged helper or live backend was found or exercised.

**G.2 NEW FINDING R16-08 — no production ingress wiring for the controller.** Repository-wide inspection found no runtime route or application factory that wires `FirewallControllerService`, `ControllerOwnershipStore`, strict allowlists, or `BrokerAuthorizer` configuration into `broker.app.main`/`routes`. `broker/app/routes.py:18-275` exposes only health/container routes. Mock transport/helper wiring is instantiated in tests and debug scripts. This means controller-side security properties are proven at library/mock boundaries only; deployed topology, socket permissions, process UIDs/GIDs and configuration provenance are **not** established.

**G.3 Boundary conclusion.** Current evidence proves a **mock security boundary** with fail-closed application logic in covered paths. It does **not** prove an operating-system security boundary (kernel-authenticated peer identity, UDS lifecycle/permissions, mutual transport verification, cross-UID deny, real helper isolation, host firewall enforcement). T-13 and T-27 remain open for this reason. Mock-only tests must not be described as proof of real host isolation.

---

## 4. Finding-ID disposition verification (current evidence)

Full detail is in `POST_J20_STAGE_1B_16_RESIDUAL_RISK_REGISTER.md`. Summary:

| Group | Independently supported current disposition |
|---|---|
| SR-01–SR-05 | Verified control sets with documented residuals; not gate closures. |
| SR-06 | Partially mitigated; mock seams, no live identity proof; acceptance PENDING. |
| SR-07, SR-08, SR-09 | VERIFIED FIXED (scoped) by typed/targeted conflicts, fail-closed canonical reads and guarded reconciliation fencing. SR-09 status-fencing fix does **not** cover the new R16-02 missing status writes on promotions. |
| SR-10 | Known architectural limitation; no formal disposition; PENDING. |
| SR-11, SR-12 | Unverified assumptions; no live/host evidence. |
| SR-13 | Partially mitigated (legacy separation; universal migration open). |
| SR-14 | Documentation-only known limitation; stale artifacts remain. |
| RR-01–RR-07 | Open / partially resolved in covered paths; no gate closed. |
| M-01–M-08 | Partially resolved; M-04/M-05 documentation-only lineage; no gate effect. |
| I-07, I-08 | Open / partially resolved (covered boundary sanitization; universal proof missing). I-07 is reinforced by R16-03/R16-04/R16-09. |
| I-09 | Open / partially resolved; acceptance PENDING. |
| H-02, H-05, N-02, N-04 | Partially resolved; mock-only evidence; host/deployment/migration evidence absent. |
| T-11, T-13, T-27 | **OPEN — ACCEPTANCE REQUIRED**; no valid authority response recorded (`AUTHORITY_DECISION_TRACKER.md` §Tracker rows 26–28; `AUTHORITY_RESPONSE_INTAKE.md` §3: "0 authority responses found and validated"). |

Contradictions found between documents are limited to wording/classification (e.g. M-02 "partially resolved" in the register vs "OPEN / BLOCKED" in the traceability matrix; M-04/M-05 "documentation-only closed" vs "partially resolved (documentation lineage)"). All agree that no gate is closed. These are recorded in the evidence challenge matrix.

---

## 5. Stage 1B.15 residual challenge result

| # | Stage 1B.15 residual | Independent result |
|---|---|---|
| 1 | `controller_policy_bodies` mutable, tamper-detected, no append-only trigger | **Accurate.** Source confirmed at `ownership_store.py:223-256`; tamper detection at `:869-938`. |
| 2 | Evidence/history/idempotency DB FKs absent; app bindings verified | **Accurate.** No `REFERENCES` in those DDLs; app bindings confirmed. |
| 3 | Base `BrokerDB._get_conn()` does not globally enable FKs | **Accurate.** `db.py:50-56`; controller-scoped FK connections only. |
| 4 | Legacy state-store fail-open in library-only subsystem | **Accurate.** `firewall_state.py:48-55,93-99,157-161`; no non-test caller. |
| 5 | No end-to-end DB/backend atomicity | **Accurate.** Explicit DB-only boundary at `ownership_store.py:301-302`. |
| 6 | Migration authority / deployed-schema closure pending | **Accurate.** Inline `CREATE TABLE IF NOT EXISTS`, additive ALTER with no backfill/version bump, no approved plan. |
| 7 | T-11/T-13/T-27/SR-10/SR-06/I-09 unresolved | **Accurate.** Tracker and intake confirm PENDING / no valid responses. |

None of the seven was automatically treated as fixed.

---

## 6. Independent review conclusion

The mock-only implementation contains substantial verified controls (canonical ingress validation, typed conflict handling, fail-closed canonical readback, versioned CAS, append-only history/evidence/audit triggers, deterministic crash/recovery tests). Raw artifacts corroborate the final Stage 1B.13→1B.14→1B.15 full-suite progression (973 → 984 → 1005 passed, EXIT 0) and the 21-passed Stage 1B.15 corrective run.

However, independent source inspection found **concrete, mock-only-remediable defects** in properties the review was explicitly asked to assess:

- `R16-01` caller headers override UDS peer credentials and permissive/default-unwired broker authorization.
- `R16-02` successful reconciliation promotions leave `reconciliation_status` stale (status/audit inconsistency).
- `R16-03` ownership CIDR scope checks are inoperative at covered ingress.
- `R16-04` compiled-digest alias weakens canonical policy binding.
- `R16-05`, `R16-06`, `R16-07`, `R16-09` smaller invariant/evidence gaps.
- `R16-08` no production ingress wiring, so controller controls are library/mock-only.

These are not merely unresolved authority acceptances or host-evidence gaps; they are fixable technical defects inside the mock-only boundary. The readiness decision is therefore recorded in `POST_J20_STAGE_1B_16_FINAL_READINESS_ASSESSMENT.md` as **Outcome B — NOT READY — ADDITIONAL MOCK-ONLY REMEDIATION REQUIRED**, with the smallest justified remediation scope stated there. No gate, acceptance or risk disposition was changed by this review.
