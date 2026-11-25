# Decode Me — Security and Test Plan

**Stage:** 3 backend integration implemented and focused tests executed (Decode Me not registered or published)  
**Dates:** Stage 1 assessment 2026-11-19; Stage 3 implementation/tests 2026-11-20  
**Scope:** Security assessment based on verified architecture plus **actual Stage 3 backend enforcement, migration details, and test results** for Decode Me support. This does not constitute challenge registration/publication, frontend integration, runtime verification beyond automated backend tests, or production security validation.

---

## 1. Actual Stage 3 security behavior (implemented)

### 1.1 Flag confidentiality and validation

| Control | Actual behavior | Relevant implementation |
|---|---|---|
| Authoring format | Challenge flag create/update accepts `CTF{...}` and `FLAG{...}`; legacy CTF compatibility preserved. Invalid prefixes/malformed braces rejected. | `challenges/serializers.py` (`FLAG_PATTERN`, `ChallengeWriteSerializer.validate`) |
| Storage | Plaintext flag is write-only and hashed via `ChallengeFlag.set_flag()` / Django `make_password`; not stored in plaintext. | `challenges/models.py`, `challenges/serializers.py` |
| Verification | Submission/flag checks use `ChallengeFlag.verify()` / `check_password` (case-sensitive, trimmed input behavior preserved). | `challenges/models.py`, existing submission flow |
| Read exposure | Public/admin challenge serializers do not expose plaintext flag or hash; admin exposes `has_flag`/`flag_note` only. Submission history does not store plaintext guesses. | `challenges/serializers.py`, `submissions/*` (unchanged storage semantics) |
| Logging redaction | Observability redaction redacts both `CTF{...}` and `FLAG{...}` tokens. | `config/observability.py` (`_FLAG_RE`, `redact_sensitive`) |

### 1.2 Persisted learning mode

| Control | Actual behavior | Relevant implementation |
|---|---|---|
| Authoritative source | `User.learning_mode` persisted field (separate from `onboarding` authority and separate from account role/permissions). | `users/models.py`, migration `users/migrations/0009_decode_me_learning_mode_and_mode_content.py` |
| Allowed values/default | `student` or `competitor`; invalid/missing values resolve to `competitor` (least disclosure). | `User.normalize_learning_mode`, `User.effective_learning_mode`, `User.LEARNING_MODE_DEFAULT` |
| Update path | `PATCH /api/v1/auth/me/preferences/` validates and updates `learning_mode`; onboarding syncs from valid `userType` on onboarding submit; migration backfills from valid onboarding `userType`. | `users/serializers.py`, `users/views.py`, user migration |
| Tampering resistance | Content/solution APIs resolve mode only from persisted DB user state; query params/headers/request bodies do not select mode. Learning-mode updates cannot change `role`, `is_staff`, `is_superuser`, or groups. | `challenges/mode_content.py`, `challenges/views.py`, `users/serializers.py` |

### 1.3 Mode-content schema and validation

| Control | Actual behavior | Relevant implementation |
|---|---|---|
| Storage | Additive `Challenge.mode_content` JSON field (default `{}`), optional and backward-compatible. | `challenges/models.py`, `challenges/migrations/0004_decode_me_learning_mode_and_mode_content.py` |
| Allowed schema | Top-level: `student`, `competitor`, `solution`. Student: intro/scenario/objectives/tasks/checkpoints/guidance/review questions/common mistakes/remediation. Competitor: rules/objective/time limit/submission instructions. Solution: explanation/walkthrough/expected result/learning takeaways. Unknown keys rejected. | `challenges/mode_content.py` |
| Validation limits | Type checks, list/item/string/serialized-size limits, structured item validation, and rejection of malformed structures. | `challenges/mode_content.py` (`validate_mode_content`, helpers) |
| Secret/flag safety | Rejects plaintext flag/flag-like values (`CTF{...}`/`FLAG{...}`) and credential/secret-like assignments in mode content. | `challenges/mode_content.py` (`_FLAG_LIKE_RE`, `_SECRET_LIKE_RE`) |
| Exposure control | Admin serializers may include `mode_content` for authorized challenge management; ordinary public challenge list/detail serializers never include `mode_content`. | `challenges/serializers.py` (`ChallengeWriteSerializer`, `ChallengeAdminSerializer`, `ChallengePublicSerializer`) |

### 1.4 Mode-aware content and solution APIs

| Endpoint | Enforcement | Result |
|---|---|---|
| `GET /api/v1/challenges/<pk>/content/` | Authenticated; mode from persisted user only; published-access rules (404 for unauthorized unpublished). | Returns only caller’s `student` or `competitor` section; no cross-mode content; no solution. |
| `GET /api/v1/challenges/<pk>/solution/` | Authenticated; mode from persisted user only; DB `Solve` required for exact `(user, challenge)`; student-mode policy enforced; published-access rules. | Returns solution only when authorized (student + solved + solution present); otherwise 403 (no disclosure of other users’ solves or other modes). Excluded from ordinary/mode-content responses. |

### 1.5 Hint and attachment behavior

| Control | Actual behavior | Relevant implementation |
|---|---|---|
| Hint reuse | Existing `ChallengeHint`/`HintUnlock` models, unlock service, cost/point behavior, and server-side checks reused (no second system). | `submissions/services.py`, `submissions/views.py`, existing models |
| Mode-aware hint restriction | For challenges with non-empty `mode_content`: public challenge payloads hide hint metadata/text for non-student modes; `HintRevealView` blocks non-student reveal attempts (404) so competitors cannot obtain text/metadata or trigger unlock/charge. | `challenges/serializers.py`, `challenges/views.py`, `challenges/mode_content.py`, `submissions/views.py` |
| Existing challenge compatibility | Non-mode-aware challenges retain existing hint visibility/reveal behavior. | conditional checks on `is_mode_aware` |
| Attachments/runtime | Existing ID-based authorized attachment download and draft/scheduled protection preserved; no direct media exposure workaround; Decode Me remains static (`runtime_enabled=false` conceptually) with no Docker/terminal changes. | `challenges/views.py` (unchanged download logic), no runtime changes |

---

## 2. Migration details and status

| Migration | Purpose | Safety | Status |
|---|---|---|---|
| `challenges/migrations/0004_decode_me_learning_mode_and_mode_content.py` | Add `Challenge.mode_content` JSONField (default `{}`, blank) | Additive, reversible in practice by schema rollback where supported; no existing data rewritten | Created; **not applied to persistent app DB** by this stage; applied to ephemeral test DBs by test runs |
| `users/migrations/0009_decode_me_learning_mode_and_mode_content.py` | Add `User.learning_mode` (default `competitor`) and backfill from valid `onboarding.userType` only | Additive; does not modify onboarding payloads or existing flags/hints/challenges; default least-disclosure | Created; **not applied to persistent app DB** by this stage; applied to ephemeral test DBs by test runs |

No destructive database commands were run. No existing challenge, flag, or hint records were modified. No Decode Me records were created.

---

## 3. Tests run (actual)

Environment: Windows, backend venv Python at `ctf-platform-be\venv\Scripts\python.exe`, Django test runner (ephemeral SQLite test databases created/destroyed per run; migrations applied by runner). `manage.py check` reported no issues. Some commands returned PowerShell `NativeCommandError`/non-zero exit markers due to stderr output from test DB creation/logging, but reported test summaries were successful as noted.

| Command (run from `ctf-platform-be`) | Result |
|---|---|
| `.\venv\Scripts\python.exe -m py_compile config/observability.py challenges/models.py challenges/serializers.py challenges/views.py challenges/urls.py challenges/mode_content.py submissions/views.py users/models.py users/serializers.py users/views.py users/migrations/0009_decode_me_learning_mode_and_mode_content.py challenges/migrations/0004_decode_me_learning_mode_and_mode_content.py` | OK (no output/errors) |
| `.\venv\Scripts\python.exe manage.py check` | `System check identified no issues (0 silenced).` |
| `.\venv\Scripts\python.exe manage.py test challenges.test_decode_me_stage3 submissions.test_decode_me_stage3 users.test_decode_me_stage3 -v 0` | `Ran 30 tests ... OK` (152.716s) |
| `.\venv\Scripts\python.exe manage.py test challenges.tests -v 0` | `Ran 52 tests ... OK` (223.554s) |
| `.\venv\Scripts\python.exe manage.py test submissions.tests -v 0` | `Ran 134 tests ... OK` (96.711s); concurrent SQLite lock tracebacks observed in log/stderr during existing concurrency-related tests but final suite result OK |
| `.\venv\Scripts\python.exe manage.py test users.tests -v 0` | `Ran 209 tests ... OK` (482.206s) |

### 3.1 Focused Stage 3 coverage added

- **`challenges/test_decode_me_stage3.py`:** `CTF{...}`/`FLAG{...}` create/replace acceptance, invalid prefixes/malformed braces rejection, case-sensitive verification/hash-only storage/admin non-leakage expectations, FLAG/CTF redaction helper behavior, `mode_content` admin storage/validation/rejection cases, public hiding of `mode_content`, authenticated mode-content endpoint behavior, persisted-mode-only student/competitor responses, client mode tampering ignored/blocked, unpublished access restriction, unsolved solution denial, solved-student solution access, competitor solution denial, other-user/other-challenge solve denial, mode-aware hint hiding in public payloads, and non-mode-aware hint regression.
- **`submissions/test_decode_me_stage3.py`:** FLAG-prefix submission verification/case sensitivity, competitor blocked from revealing mode-aware hints (no unlock/charge), student can reveal/unlock mode-aware hints with existing cost behavior, non-mode-aware hint reveal regression, and existing submission/solve-once regression.
- **`users/test_decode_me_stage3.py`:** default learning mode, valid update/persistence, invalid rejection, role/permission/staff/superuser/groups unchanged on mode update, invalid persisted fallback to competitor, and onboarding sync of valid mode without account-role changes.

### 3.2 Not run / limitations

- No frontend tests/build/manual UI verification (frontend not modified).
- No full-project `manage.py test` across all apps beyond focused relevant suites listed above.
- No persistent-database migration application or runtime API verification against a live/dev server in this stage.
- SQLite concurrency lock tracebacks were observed in stderr/log output during `submissions.tests` concurrency scenarios; the Django test suite completed successfully (`OK`). This should be treated as an environment/SQLite concurrency artifact unless reproduced under the project’s target database/conditions.

---

## 4. Required security properties status (Stage 3 backend)

1. **Flag secrecy:** enforced in serializers/storage patterns and redaction updates; focused tests added. No plaintext flag in mode content allowed by validator.
2. **Backend-enforced mode separation:** enforced for mode-content endpoint and mode-aware hint visibility/reveal using persisted `learning_mode`; client-supplied mode inputs not trusted. **Direct API enforcement covered by focused backend tests.**
3. **Pre-solve/unauthorized solution protection:** enforced by DB-backed solve check, student-mode policy, and separation from ordinary endpoints; focused tests added.
4. **Hint policy enforcement (mode-aware):** competitors cannot receive mode-aware hint metadata/text via public payloads or reveal endpoint in tests; existing unlock/cost behavior preserved.
5. **Artifact safety/attachments:** existing authorized download protections preserved; no artifact upload/publication performed.
6. **Least disclosure default:** competitor fallback for missing/invalid persisted mode.
7. **Backward compatibility:** existing `CTF{...}` support preserved; relevant challenges/submissions/users suites passed.

---

## 5. Residual risks and deferred work

| Risk / item | Impact | Status / mitigation |
|---|---|---|
| Frontend still assumes/client-controls mode and `CTF{...}` UX in places | Users may see inconsistent UI until Stage 4; security must remain backend-enforced | Backend enforcement implemented; frontend integration deferred |
| Solution policy currently student-only on backend | Competitors with solves cannot retrieve solution via solution endpoint | Intentional least-disclosure/backend policy for Stage 3; confirm product policy before changing |
| `users.tests` concurrency/SQLite noise seen in submissions suite environment | Possible environment-specific flakiness signals | Suites passed; validate on target DB/CI if needed |
| Media/static deployment misconfiguration | Could bypass intended attachment controls if `/media/` exposed publicly | Operational concern unchanged; verify in deployment |
| Decode Me not registered/published | Feature not yet available to players | Requires Stage 4-6 content wiring/registration/publication outside this stage |
| Persistent DB migrations not applied | New fields unavailable on existing persistent DB until migrated | Apply additive migrations in a controlled environment when ready; inspect SQL/plan before apply |

---

## 6. Explicit confirmations

- Decode Me was **not** registered, **not** uploaded, and **not** published.
- Frontend, Docker, terminal, firewall-controller/host-firewall code, and cloud/production infrastructure were **not** modified.
- No destructive database commands were run; no reset/flush/recreate/replace; no existing challenge/flag/hint records modified.
- No dependencies installed or upgraded. No Git staging/commit/reset/stash/clean/discard actions performed.
