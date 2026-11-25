# Phase 2L.2J.17 — Fault Injection and Transaction/Recovery Matrix (Mock-Only)

**Repository:** `E:\Flag-hunt\ctf-platform-be` | **HEAD:** `b3655841ffc0a0cea2cfd33ad56d7ed355a4d068` | **Date:** 2026-11-16

All fault injection is **test-only, disabled by default, explicit test wiring, disposable DBs**, and **not activatable** through production requests/public runtime configuration. No host/network/privileged operations.

## 1. Deterministic injection mechanisms used

| Mechanism | Source | Scope |
|---|---|---|
| Store method-failure wrappers (`FailOnMethodStore` patterns) | J.12/J.13 existing suites | Per-method injectable failures in test stores |
| Connection wrappers / commit-failure instrumentation | J.12/J.13/J.17 (`FailCommitConnection`/instrumented conn) | Commit/execute failure at selected transaction points |
| Direct DB tamper/corruption (test fixtures) | J.12/J.13/J.17, canonical persistence tests | Corrupt JSON, digest mismatch, binding mismatch, missing body, ownership mutation (where not append-only protected) |
| Barrier-based concurrency | J.12/J.13/J.17 | Deterministic concurrent install/verify/revoke/reconcile races in covered cases |
| Fresh-process reopen/retry simulation | J.12/J.13/J.17 | New store/service instances against same DB, repeated recovery/reconcile |

## 2. Injection point matrix (required points)

| Injection point | Covered by tests/evidence | Outcome/property evidenced (covered) | Gaps / notes |
|---|---|---|---|
| Before transaction start | Method-failure before create/update paths (J.12/J.13/J.17 patterns) | Fail-closed, no false success; state unchanged or safely absent | Not every operation path individually hooked |
| After transaction start | Connection/commit-failure wrappers around transactional methods | Rollback/no partial committed state in covered create/evidence/idempotency/update cases | Internal mid-statement hook points limited |
| After initial reads | Binding/ownership tamper and CAS/readback adversarial cases (J.13/J.17) | Fail-closed on mismatch/stale binding in covered paths | Deterministic hook after every read not instrumented |
| Before CAS | CAS expected-version mismatch/rejection tests (J.13/J.17/store behavior) | Stale snapshot rejected, no overwrite | Explicit pre-CAS injected delay hook not universally added |
| After CAS | Update commit-failure simulations (J.17) | No false ACTIVE/VERIFIED on failed commit; state remains prior/safe | Not all CAS transitions individually instrumented |
| Before evidence insertion | Evidence-store/commit failure paths (J.12/J.13/J.17) | No promotion to ACTIVE on failed evidence persistence in covered cases | — |
| After evidence insertion | Direct conflicting insert and recovery/reconcile checks (J.17) | No false ACTIVE/VERIFIED promotion from conflicting/mismatched context in covered logic | Append-only prevents mutation/deletion; duplicate logical evidence handling remains application-dependent |
| Before canonical-body persistence | Create/install failure paths and missing-body recovery (J.17/J.12 contexts) | Recoverable/fail-closed, no false promotion | — |
| After canonical-body persistence | Corrupt/tamper/missing-body recovery tests (J.12/J.13/J.17) | Trusted read-back/reconcile fail closed; uncertain/not ACTIVE | — |
| Before idempotency completion | Completion/commit-failure and pending cases (J.12/J.13/J.17) | No false COMPLETED/success; bounded handling in covered cases | — |
| Before commit | Commit-failure wrappers on create/evidence/idempotency/update (J.12/J.13/J.17) | Rollback/no partial commit | — |
| Commit failure | J.12/J.13/J.17 commit-failure tests | No partial committed state / no false promotion | — |
| After commit but before response | Response-loss approximations via committed progress + caller retry/reopen (J.13/J.17) | Deterministic replay/no duplicate/no false ACTIVE in covered cases | True in-process post-commit/pre-response hook not added to production code; approximated safely |
| Reopen after uncertain outcome | J.12/J.13/J.17 repeated reopen/reconcile | Fail closed, no false ACTIVE/VERIFIED | — |
| Repeated recovery | J.13/J.17 loops | No state escalation, no duplicate evidence explosion in covered cases | — |
| Concurrent conflicting operation | Barrier races install/verify/revoke/reconcile (J.12/J.13/J.17) | No stale overwrite/reactivation/duplicate ownership in covered cases | Exhaustive interleaving matrix incomplete |

## 3. Verified safety properties (covered cases)
- No false ACTIVE promotion.
- No false VERIFIED promotion.
- No duplicate ownership records for same policy/version in tested conflicts.
- No conflicting same-key different-payload success.
- No unbounded retry loop in tested persistent idempotency failure paths (existing J.10 bounded wait/deadline preserved).
- Corrupted/missing canonical body not trusted as valid promotion input in covered recovery/read-back paths.
- CAS/stale snapshot rejection in covered store/service cases.

## 4. Gaps and constraints
- True intra-transaction hook points inside every multi-step service flow (before/after every internal read/CAS/evidence/body/idempotency write) are **not exhaustively instrumented** without broader production refactoring; J.17 uses safe test-only wrappers, DB instrumentation, and deterministic approximations.
- "After commit but before response" is approximated via committed-state + lost-response/retry scenarios, not a production hook.
- Multi-table atomicity remains incomplete by design in current implementation (documented in persistence integrity matrix); demonstrated partial states tested as recoverable/fail-closed in covered cases.
- Exhaustive evidence/concurrency/race/state matrix and host/runtime crash behavior remain incomplete/out of scope.

**NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**
