# Post-J.20 Stage 1B.5 — Remediation Roadmap (Mock-Only Assessment)

**Mandatory security status: NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**

**T-11, T-13 and T-27: OPEN — ACCEPTANCE REQUIRED.** This roadmap records recommended
follow-up work only. No item in it was implemented in Stage 1B.5, no gate is closed by it,
and nothing here authorizes Stage 1C, Docker integration, or live firewall work.

Findings referenced: `docs/POST_J20_STAGE_1B_5_INDEPENDENT_SECURITY_REVIEW.md` (SR-01–SR-14).

## 1. Sequencing principles

1. Keep Stage 1B.1–1B.4 implementation and evidence intact; do not reset, revert, clean,
   stage or commit existing work.
2. Fix source-provable classification/guard gaps before expanding scope.
3. Keep all changes narrow and mock-only; no schema migration or broad refactor without a
   separately authorized stage and acceptance decision.
4. Treat host/runtime items as acceptance-gated, not engineering-only closures.
5. Preserve superseded evidence artifacts with chronology; never delete failed runs to
   imply a clean history.

## 2. Priority 1 — narrow source hardening (before any further scope expansion)

| Roadmap item | Finding | Affected code | Recommended action (not performed here) | Acceptance evidence |
|---|---|---|---|---|
| P1.1 | SR-07 | `ownership_store.py:794-809`; `controller_service.py:436-460,972-976` | Replace exception-message substring classification with typed `sqlite3.IntegrityError`/constraint-name checks and explicit exception categories; keep bounded response sanitization. | Fault-injection matrix for intentional UNIQUE race, genuine UNIQUE violation, generic DB failure, and message-format variation; all existing Stage 1B suites still pass. |
| P1.2 | SR-08 | `ownership_store.py:794-797` | Catch only a specific not-found condition from `get_canonical_policy_body`; re-raise every other exception as `BrokerDBError`, preserving the rule at `ownership_store.py:337-342`. | Test injecting a read failure into canonical ensure, asserting raw persistence failure and no insert; canonical-body regression suite green. |
| P1.3 | SR-09 | `controller_service.py:1754,1781`; guarded helper `:1527-1537` | Route `REQUESTED`/`INSTALLING`/`MISSING` reconciliation status writes through the version-guarded helper with the snapshot `lifecycle_version`. | Deterministic concurrency test where a stale reconciler cannot overwrite a newer status; existing 1B.3/1B.4 suites green. |

**Exit criterion for Priority 1:** all three gaps are closed by scoped changes, independently
reviewed, and evidenced with actual exit codes. Until then, SR-06/SR-07/SR-08/SR-09 remain
open findings in the risk register.

## 3. Priority 2 — trust-boundary preparation (engineering prerequisites only)

| Roadmap item | Finding | Recommended action (not performed here) | Acceptance evidence |
|---|---|---|---|
| P2.1 | SR-06 | Keep strict auth mandatory outside tests; remove or isolate `strict_auth=False`, `MockAuthorizationProvider`, and `controller_verified` trusted-flag acceptance from any live-capable path. | Source audit showing no permissive seam reachable outside explicit tests; adversarial auth tests green. |
| P2.2 | SR-06, SR-11, SR-12 | Define an authenticated identity object supplied by a real transport; do not accept uid/gid from request JSON. Do not wire UDS/SO_PEERCRED in this milestone. | Design review and named-authority approval of the transport boundary before any implementation. |
| P2.3 | SR-10, SR-11 | Preserve uncertainty semantics; add backend contract tests for idempotency-key honouring and readback truthfulness only when a real backend is authorized. | Live contract evidence (out of mock scope) plus unchanged mock suites. |

**Exit criterion for Priority 2:** prerequisites documented and accepted; no live trust
boundary implementation is attempted without separate authorization.

## 4. Priority 3 — governance, documentation and acceptance

| Roadmap item | Finding | Recommended action (not performed here) | Acceptance evidence |
|---|---|---|---|
| P3.1 | SR-14 | Reconcile Stage 1B-local scope labels for RR-05/RR-06/M-01/M-06 with the canonical register definitions; add a chronology note for superseded artifacts. | Governance-owned doc review; statuses unchanged until acceptance. |
| P3.2 | SR-02, SR-10 | Decide whether split install-failure writes and multi-transaction operations are accepted designs or require grouped/migration changes. | Named-authority risk disposition; no implicit acceptance from this roadmap. |
| P3.3 | SR-05 | Decide whether detection-only integrity for `controller_policy_bodies` is sufficient or whether append-only/migration constraints are required. | Migration/acceptance evidence if changed; otherwise explicit disposition. |
| P3.4 | SR-12, T-11, T-13, T-27 | Obtain formal acceptance after any authorized host/runtime evidence exists. | Named-authority acceptance records; no gate closure by engineering evidence alone. |

## 5. Explicitly excluded from this roadmap

- Stage 1C or any later milestone work.
- Docker daemon/socket/SDK/container integration, UDS/SO_PEERCRED wiring, privileged
  helper, Linux capabilities, nftables/iptables, host firewall, host permission changes,
  system services, cloud deployment, or live firewall operations.
- Broad source refactoring, new parallel state machines or ledgers, schema migrations, or
  weakening/removing existing tests or assertions.
- Git reset, clean, revert, stage or commit of existing user work.

## 6. Relationship to the readiness decision

This roadmap supports the decision in
`docs/POST_J20_STAGE_1B_5_FINAL_READINESS_DECISION.md`: the mock-only Stage 1B evidence is
complete enough for a **conditional formal acceptance review**, but production readiness is
not authorized and no gate is closed. Priority 1 items are the concrete engineering
conditions attached to that conditional posture; T-11/T-13/T-27 and host evidence remain
authority-level blockers.
