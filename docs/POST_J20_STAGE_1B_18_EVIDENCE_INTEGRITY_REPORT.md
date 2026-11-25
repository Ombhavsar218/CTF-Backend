# Post-J.20 Stage 1B.18 — Evidence Integrity Report (Read-Only)

**Mandatory status:** NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED

## 1. Scope

Independent audit of `docs/evidence/post_j20_stage_1b17/` against `docs/POST_J20_STAGE_1B_17_SECURITY_TEST_EVIDENCE.md`, `docs/POST_J20_STAGE_1B_17_FINAL_VERIFICATION_REPORT.md`, the Stage 1B.17 residual assessment, raw source/test files, and Stage 1B.13–1B.16 historical evidence limitations.

No tests were executed during Stage 1B.18. No artifact was created, modified or removed in the Stage 1B.17 evidence directory.

## 2. Corpus completeness

The directory contains **50 files**:

- 12 claimed runs × 4 artifacts (`stdout`, `stderr`, `exit`, `meta`) = 48 files;
- `final_git_state.txt`;
- `final_changed_files.txt`.

All 12 claimed runs have complete four-artifact sets. `django_manage_check.stderr.txt` is empty, consistent with the documented result. Pytest stderr files contain only the pre-existing `pytest-asyncio` `asyncio_default_fixture_loop_scope` deprecation warning; no failure detail is hidden in stderr.

## 3. Run-level verification table

| Run | Raw stdout summary | Raw EXIT | Documented claim | Substantiated? |
|---|---|---:|---|---|
| `initial_new_suite` | `23 failed, 4 passed, 1 warning in 6.37s` | 1 | 23 failed / 4 passed | Yes |
| `initial_new_suite_repro` | `23 failed, 4 passed, 1 warning in 4.48s` | 1 | 23 failed / 4 passed | Yes |
| `corrective_new_suite_1` | `7 failed, 20 passed, 1 warning in 4.17s` | 1 | 7 failed / 20 passed | Yes |
| `corrective_new_suite_2` | `2 failed, 25 passed, 1 warning in 3.72s` | 1 | 2 failed / 25 passed | Yes |
| `corrective_new_suite_final` | `27 passed, 1 warning in 3.48s` | 0 | 27 passed | Yes |
| `focused_auth_authorization` | `152 passed, 1 warning in 39.83s` | 0 | 152 passed | Yes |
| `focused_reconciliation_lifecycle` | `84 passed, 1 warning in 83.35s (0:01:23)` | 0 | 84 passed | Yes |
| `focused_canonical_integrity` | `83 passed, 1 warning in 35.06s` | 0 | 83 passed | Yes |
| `focused_idempotency_concurrency` | `35 passed, 1 warning in 40.50s` | 0 | 35 passed | Yes |
| `full_broker_suite` | `1032 passed, 1 warning in 383.45s (0:06:23)` | 0 | 1032 passed | Yes |
| `django_manager_client` | stdout: `Found 33 test(s).`; stderr: `Ran 33 tests in 0.588s` / `OK` | 0 | 33 tests OK | Result yes; stream attribution no |
| `django_manage_check` | `System check identified no issues (0 silenced)` | 0 | no issues | Yes |

Initial failures are preserved as separate `initial_*` and `corrective_*` runs with `EXIT=1`; the final and focused runs have `EXIT=0`. No incomplete run is relabeled as passing. Corrective reruns are distinguishable by filename, content and exit code.

## 4. Failure chronology check

`corrective_new_suite_1.stdout.txt` lists five R16-02 failures and two R16-06 failures. `corrective_new_suite_2.stdout.txt:3,28,65-66` lists:

- `test_r16_02_verifying_recovery_persists_reconciliation_status`;
- `test_r16_06_full_scan_keeps_overlapping_identities_distinct`.

No R16-04 test failed in either intermediate corrective run. The full-scan test is absent from the current `broker/tests/test_post_j20_stage_1b17_remediation.py` (only the two `test_r16_06_ledger_*` tests remain), so it was removed rather than corrected. The final 27-test suite does not exercise full-scan ledger attribution.

## 5. Evidence-narrative discrepancies

### 5.1 Unsupported R16-04 causal claim

`docs/POST_J20_STAGE_1B_17_SECURITY_TEST_EVIDENCE.md:17` states:

> The two intermediate corrective failures were caused by service-internal alias behavior (R16-04) and test setup details (`_verifying_with_evidence` fixture and full-scan contract).

Raw artifacts contradict the R16-04 portion: the observed failures were R16-02 and R16-06. Test setup details are partly visible in tracebacks, but the R16-04 causal attribution is unsupported.

### 5.2 Django stdout/stderr inversion

`POST_J20_STAGE_1B_17_SECURITY_TEST_EVIDENCE.md:46` says stderr contains “Creating test database...” and stdout contains `Ran 33 tests` / `OK`. Raw artifacts show the opposite for the result lines: `django_manager_client.stderr.txt` contains `Ran 33 tests in 0.588s` and `OK`; `django_manager_client.stdout.txt` contains `Found 33 test(s).` and the system-check line.

### 5.3 Git count labels and values

`POST_J20_STAGE_1B_17_FINAL_VERIFICATION_REPORT.md:50` and `docs/evidence/post_j20_stage_1b17/final_git_state.txt` record `281 untracked collapsed / 716 untracked expanded`. Raw git enumeration at Stage 1B.18 baseline showed 26 modified tracked, 0 staged, 255 collapsed `??` entries, 281 total porcelain changed entries and 718 expanded untracked files. The raw artifact preserves values, but the labels/interpretation in the final report are inaccurate. Stage 1B.18 baseline is independently recorded as 281 collapsed / 718 expanded.

### 5.4 Metadata field semantics

`.meta.txt` files use `STARTED=` with elapsed-like values (for example `STARTED=00:00:07.0659717` with `DURATION_SECONDS=7.07`). Commands, stdout, stderr, exit codes and durations are preserved; `STARTED=` is not a wall-clock timestamp despite its name.

### 5.5 Duration presentation

`POST_J20_STAGE_1B_17_SECURITY_TEST_EVIDENCE.md:24` lists the focused reconciliation duration as `85.71s` (runner meta), while raw pytest stdout reports `83.35s`. Counts and exit codes agree; the two durations measure different runner/pytest scopes but are not distinguished in the document.

### 5.6 Broader completion overstatements

`POST_J20_STAGE_1B_17_FINAL_VERIFICATION_REPORT.md:58` says all safely remediable findings were corrected. `POST_J20_STAGE_1B_17_RESIDUAL_RISK_ASSESSMENT.md:14,16,19` says R16-02, R16-06 and R16-07 were remediated. Source inspection in `POST_J20_STAGE_1B_18_R16_VERIFICATION_MATRIX.md` shows those claims are broader than the evidence. R16-03 is accurately called partial in the residual assessment but described as corrected in final/gate wording.

These are evidence-hygiene and accuracy problems, not proof that the recorded test counts or exit codes are false.

## 6. Historical evidence limitations

The following Stage 1B.16-recorded limitations remain unresolved and are not retroactively repaired:

- missing stderr artifacts for some Stage 1B.13/1B.14/1B.15 runs;
- no exit codes for j17/j18/j19;
- reported-only counts `218`, J.18 `16`, J.19 `28`;
- no authored final hash snapshot for Stage 1B.15;
- truncated 1A1/1A2/j17 stdout;
- unresolved FK-pragma expectation conflict.

Stage 1B.17 evidence is complete for Stage 1B.17 itself, but does not repair these historical gaps.

## 7. Authority and gate evidence

`docs/POST_J20_STAGE_1B_10_AUTHORITY_DECISION_TRACKER.md:26-31` records T-11, T-13, T-27, SR-10, SR-06 and I-09 with `[NOT RECORDED]` authority responses and `PENDING` status. `docs/POST_J20_STAGE_1B_11_AUTHORITY_RESPONSE_INTAKE.md:46` records `0 authority responses found and validated`. The decision reconciliation matrix records 0 valid responses and 0 approvals.

`docs/PHASE_2L_2J_1_SECURITY_GATE_REGISTER.md:71` is an evidence-only note; gate rows at `:155-157` remain OPEN — ACCEPTANCE REQUIRED. Stage 1B.18 adds another evidence-reference-only note and changes no status.

## 8. Conclusion

- Claimed test runs: all present with raw artifacts.
- Counts, exits and final summaries: substantiated.
- Initial failures and corrective reruns: preserved and distinguishable.
- Narrative explanations and some metadata/stream/count labels: not fully substantiated.
- Test coverage claims: overstated for R16-02, R16-04, R16-05, R16-06, R16-07 and R16-03; full-scan regression was removed.
- Fresh Stage 1B.18 test execution: none performed and none claimed.

Evidence is sufficient to identify the remaining technical defects, but not sufficient to support Outcome A.

Final status: **NOT READY — LIVE FIREWALL INTEGRATION NOT AUTHORIZED**.
