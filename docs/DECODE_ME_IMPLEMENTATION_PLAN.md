# Decode Me — Implementation Plan

**Stage:** 3 backend integration implemented (Decode Me not registered or published)  
**Dates:** Stage 1 planning 2026-11-19; Stage 3 implementation 2026-11-20  
**Basis:** Verified findings in `DECODE_ME_ARCHITECTURE_ASSESSMENT.md`, design in `DECODE_ME_CHALLENGE_SPECIFICATION.md`, and current source inspection during Stage 3.

This document records planned stages and the **actual Stage 3 backend implementation**. Stage 3 implemented the minimum backend functionality required to support Decode Me with secure Student/Competitor separation, while preserving existing challenge/submission behavior. No challenge registration, artifact upload, or publication was performed.

---

## 1. Guiding constraints (maintained)

- No frontend files, Docker/terminal/runtime/firewall-controller/host-firewall/infrastructure changes.
- No existing challenge records modified; no Decode Me challenge created, uploaded, or published.
- Reused existing flag hashing/verification, submission/solve, hint unlock, attachment download authorization, and challenge visibility primitives.
- No destructive database commands; no dependency changes.
- Existing modifications and untracked files were preserved; no Git staging/commit/reset/stash/clean/discard actions were taken.

---

## 2. Stage 3 — Actual backend integration

### 2.1 Pre-implementation inspection (performed)

- Inspected `challenges/models.py`, `challenges/serializers.py`, `challenges/views.py`, `challenges/urls.py`, `challenges/admin_urls.py`, `challenges/permissions.py`, `submissions/models.py`, `submissions/services.py`, `submissions/views.py`, `users/models.py`, `users/serializers.py`, `users/views.py`, and `config/observability.py`.
- Inspected existing migration and test patterns for `challenges`, `submissions`, and `users`.
- Confirmed `User.onboarding` is a JSON payload containing questionnaire data (including optional `userType`) used by onboarding/profile flows and frontend mode presentation; it is **not** a safe/account-authoritative field for protected content gating by itself.
- `git status` is unavailable in this workspace (`fatal: not a git repository...`); baseline modified/untracked state was preserved and no Git operations were performed.

### 2.2 Learning mode source and default (actual)

- **Authoritative source:** `users.User.learning_mode` (new persisted field, separate from account role/permissions and separate from `onboarding` payload authority).
- **Allowed values:** `student`, `competitor` (`User.LEARNING_MODE_CHOICES`).
- **Default:** `competitor` (`User.LEARNING_MODE_DEFAULT`) — least-disclosure default for users with missing/invalid persisted mode.
- **Normalization/fallback:** `User.normalize_learning_mode()` accepts only `student`/`competitor`; `User.effective_learning_mode` returns normalized persisted value or falls back to `competitor`.
- **Persistence/update paths:**
  - `PATCH /api/v1/auth/me/preferences/` accepts `learning_mode` via `PreferencesSerializer` (validated; updates only preference fields; does not change role/groups/staff/superuser state).
  - `POST /api/v1/auth/onboarding/` stores onboarding payload as before and, if `userType` is explicitly valid (`student`/`competitor`), syncs `learning_mode` in the same save; it does not overwrite unrelated onboarding data outside the submitted payload and does not change account role/permissions.
  - `GET /api/v1/auth/me/` exposes `learning_mode` as the effective (normalized/fallback) value via `UserSerializer`.
- **Migration backfill:** `users/migrations/0009_decode_me_learning_mode_and_mode_content.py` adds `learning_mode` with default `competitor` and backfills from `onboarding.userType` only when explicitly valid (`student`/`competitor`), without modifying onboarding data.
- **Non-repudiation of account classification:** `role`, `is_staff`, `is_superuser`, groups, and other account-authorization fields are unchanged by learning-mode updates.

### 2.3 Flag compatibility and hashing (actual)

- **Authoring validation:** `challenges.serializers.FLAG_PATTERN` now accepts `CTF{...}` and `FLAG{...}` (`^(?:CTF|FLAG)\{.+\}$`), preserving legacy CTF compatibility.
- **Error message:** invalid flag format reports `The flag must be of the form CTF{...} or FLAG{...}.`
- **Storage/verification:** unchanged secure behavior — plaintext accepted only on write paths, hashed via `ChallengeFlag.set_flag()` / Django `make_password`, verified via `ChallengeFlag.verify()` / `check_password` (case-sensitive, constant-time comparison semantics as before).
- **API exposure:** flag remains write-only; public/admin serializers do not expose plaintext flags or hashes (`admin` exposes `has_flag`/`flag_note` only). Submission history continues to store only correctness metadata, not plaintext guesses.
- **Logging redaction:** `config.observability._FLAG_RE` updated to redact both `CTF{...}` and `FLAG{...}` tokens.

### 2.4 Structured challenge content (actual)

- **Model:** additive `Challenge.mode_content` JSONField (`default=dict`, `blank=True`) in `challenges/models.py`; existing challenges remain compatible (empty/default).
- **Migration:** `challenges/migrations/0004_decode_me_learning_mode_and_mode_content.py` adds `mode_content` (additive, no data rewrite).
- **Admin write/read:** `ChallengeWriteSerializer` accepts optional `mode_content` (validated) for create/update; `ChallengeAdminSerializer` includes `mode_content` for admin inspection/editing. Ordinary public challenge serializers never include `mode_content`.
- **Validation:** implemented in `challenges/mode_content.py` via `validate_mode_content()` and integrated into `ChallengeWriteSerializer.validate_mode_content()`.
  - Top-level keys allowed: `student`, `competitor`, `solution` (unknown keys rejected).
  - `student` keys: `introduction`, `scenario`, `learning_objectives`, `tasks`, `checkpoints`, `guidance`, `review_questions`, `common_mistakes`, `remediation_guidance`.
  - `competitor` keys: `challenge_rules`, `objective`, `time_limit`, `submission_instructions`.
  - `solution` keys: `explanation`, `walkthrough`, `expected_result`, `learning_takeaways`.
  - Type/structure validation, bounded list sizes/counts, bounded string lengths, structured item validation, and serialized-size limit enforced; malformed/unknown structures rejected.
  - Plaintext flag/flag-like values (`CTF{...}`/`FLAG{...}`) and credential/secret-like assignments are rejected.
- **Reuse:** existing `ChallengeHint` and `ChallengeAttachment` models/endpoints are reused; no duplicate hint/unlock/attachment systems and no unnecessary tables introduced.

### 2.5 Mode-aware content API (actual)

- **Endpoint:** `GET /api/v1/challenges/<pk>/content/` (`ChallengeModeContentView`, name `challenge-mode-content`).
- **Auth/permissions:** `IsAuthenticated` required.
- **Mode resolution:** exclusively from persisted user data via `resolve_learning_mode(request.user)` / `User.effective_learning_mode`; query params, headers, and request bodies are never accepted for mode selection.
- **Visibility/publication rules:** uses published-challenge access for ordinary users; unpublished/draft/scheduled challenges return 404 unless caller has `challenges.view_challenge`.
- **Response behavior:** returns only the caller’s allowed section (`student` or `competitor`) plus mode/challenge metadata; never returns the other mode’s content and never returns solution content.
- **Defaults:** missing/invalid persisted mode resolves to `competitor` (least disclosure).

### 2.6 Solve-gated solution API (actual)

- **Endpoint:** `GET /api/v1/challenges/<pk>/solution/` (`ChallengeSolutionView`, name `challenge-solution`).
- **Auth/permissions:** `IsAuthenticated` required.
- **Publication rules:** same published/404-unless-`view_challenge` behavior as mode-content endpoint.
- **Authorization policy (enforced):** solution content is returned only when the persisted mode is `student` **and** a `Solve` record exists for the exact authenticated user and exact challenge (`Solve.objects.filter(user=user, challenge=challenge).exists()`).
  - Client-supplied completion flags are ignored.
  - Another user’s solve or a solve for another challenge does not grant access.
  - Competitor-mode users do not receive solution content through this endpoint (even if solved), consistent with least-disclosure/backend policy for this stage.
  - Unsolved/unauthorized requests receive standard 403 permission response with no cross-mode/other-user disclosure.
- **Leakage prevention:** solution content is excluded from ordinary challenge list/detail responses, admin/player public serializers, and mode-content responses.

### 2.7 Mode-aware hints (actual)

- **Reuse:** existing `ChallengeHint`, `HintUnlock`, `submissions.services.unlock_hint`, point/cost behavior, and server-side unlock checks preserved.
- **Mode-aware challenge definition:** challenge with non-empty validated `mode_content` (`challenges.mode_content.is_mode_aware`).
- **Public challenge payloads:** `ChallengePublicSerializer` suppresses hint metadata/text for mode-aware challenges when effective mode is not `student` (competitors/unauthenticated contexts receive empty hints). Non-mode-aware existing challenges are unchanged.
- **Reveal enforcement:** `submissions.views.HintRevealView` resolves mode from persisted user data and returns 404 for non-student reveal attempts on mode-aware published challenges, preventing hint metadata/text disclosure and preventing unlock/charge side effects for blocked users.
- **Student behavior:** progressive paid hints remain available on mode-aware challenges for student-mode users, subject to existing unlock/cost/platform rules.

### 2.8 Attachments and static challenge compatibility (actual)

- Reused existing `ChallengeAttachment` upload/download implementation and authorization (`ChallengeAttachmentDownloadView`, ID-based access, draft/scheduled protection for non-viewers).
- Decode Me remains static (`runtime_enabled=false` by design); no Docker, terminal, container, or instance functionality added.
- No `MEDIA_ROOT` public exposure workaround added; no artifact uploaded and no Decode Me challenge registered/published.

### 2.9 Migration and data safety (actual)

- **Migrations created:**
  - `challenges/migrations/0004_decode_me_learning_mode_and_mode_content.py` — adds `Challenge.mode_content` (`JSONField`, default `{}`, blank).
  - `users/migrations/0009_decode_me_learning_mode_and_mode_content.py` — adds `User.learning_mode` (choices student/competitor, default competitor, max_length 16) and data backfill from valid `onboarding.userType`.
- **Safety:** additive; no deletions/rewrites of existing challenge, flag, or hint records; no Decode Me records created/published.
- **Applied:** not applied to any persistent application database by this stage (no persistent DB migration command executed). Django’s test runner applied migrations to ephemeral test databases during automated tests.
- **Destructive actions:** none performed (no reset/flush/drop/recreate).

### 2.10 API routes and permission behavior (actual)

| Route | Method | Auth/permission | Behavior |
|---|---|---|---|
| `/api/v1/challenges/<pk>/content/` | GET | `IsAuthenticated` | Returns only caller’s persisted-mode content (`student` or `competitor`) for published challenges (or unpublished with `challenges.view_challenge`); no cross-mode content, no solution. |
| `/api/v1/challenges/<pk>/solution/` | GET | `IsAuthenticated` | Returns solution only for student-mode caller with DB `Solve` for exact challenge (and published/view-authorized access); otherwise 403 (or 404 for unauthorized unpublished access). |
| `/api/v1/auth/me/preferences/` | PATCH | authenticated user (existing endpoint conventions) | Accepts `learning_mode` (`student`/`competitor`) and existing preference fields; rejects invalid mode; does not alter role/permissions/groups/staff/superuser. |
| `/api/v1/auth/me/` | GET | authenticated user | Returns effective `learning_mode`. |
| `/api/v1/auth/onboarding/` | POST | authenticated user | Persists onboarding payload and may sync `learning_mode` when `userType` is explicitly valid. |
| Existing hint reveal/attachment/challenge APIs | existing | existing | Hint reveal additionally blocked for non-student on mode-aware challenges; attachment/download/visibility rules preserved. |

### 2.11 Decode Me content compatibility (preserved)

- Approved Stage 2 artifact remains source of truth: `ctf-platform-be/docs/challenges/decode-me/decode-me-message.txt`.
- Approved Stage 2 flag remains source of truth: `FLAG{base64_is_not_a_lock}`.
- No substitution with `FLAG{b64_is_not_encryption}` and no alternate artifact created.
- Decode Me remains unregistered and unpublished.

---

## 3. Remaining stages (planned, not executed in Stage 3)

- **Stage 4:** Frontend/admin integration (only if required) — allow `FLAG{...}` UX, mode persistence wiring, render backend-gated mode content/solution/hints; no redesign.
- **Stage 5:** End-to-end testing and verification (including frontend/build/smoke and manual API/UI checks beyond backend tests run here).
- **Stage 6:** Registration and publication of Decode Me as a new draft/published challenge using approved artifact/content and verified policies.

Open product decisions to confirm before later stages: unknown-mode handling in UX (backend default remains least-disclosure), competitor hint policy per challenge content, and student-only solution access policy (currently enforced as student-only on backend for this stage).
