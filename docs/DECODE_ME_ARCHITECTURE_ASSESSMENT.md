# Decode Me — Architecture Assessment

**Stage:** 1 (Inspection and documentation only)  
**Date:** 2026-11-19  
**Scope:** Existing Flaghunt backend (`ctf-platform-be`) and frontend (`ctf-platform`) inspected from source in `E:\Flag-hunt`. No application source code, frontend code, database records, migrations, dependencies, Docker state, Git staging, or commits were modified.

---

## 1. Inspection summary

Flaghunt already provides most primitives needed for a static, downloadable cryptography challenge:

- Published challenges are publicly listable/readable via REST endpoints.
- Challenge content is modeled on `Challenge` (`description`, `scenario`, `objectives`, `instructions`, `cheatsheet`, tags, category, difficulty, points, status, etc.).
- Flags are never stored in plaintext: `ChallengeFlag` stores a salted Django password hash and verifies with constant-time `check_password`.
- Flag submission is authenticated, published-only, records every attempt without storing plaintext guesses, and awards a solve once per user/challenge.
- Paid hints are modeled as `ChallengeHint` rows, revealed server-side through authenticated unlocks, and hidden from public responses until unlocked for the requesting user.
- Downloadable artifacts are supported via `ChallengeAttachment` and an ID-based authorized download endpoint.
- Docker/runtime is optional (`runtime_enabled` defaults to `false`); non-runtime/static challenges are supported.
- Student/Competitor presentation exists in frontend/user onboarding data, but it is **not** a backend-enforced content boundary.

Primary gaps for **Decode Me** (FLAG-format, guided student content, competitor separation, post-solve solution):

1. Challenge flag creation/update currently requires `CTF{...}` prefix in backend and admin UI.
2. No structured storage for student tasks, checkpoints, conceptual explanations, review questions, common mistakes, competitor-only rules, or gated solution content.
3. No backend-enforced Student/Competitor mode content separation; mode toggles are client-side and public challenge payloads are mode-agnostic.
4. Native hint visibility is not mode-aware (hint metadata is returned to all callers; text remains protected until unlock).
5. No solution field/endpoint and no post-solve gated delivery mechanism.

---

## 2. Backend inspection

### 2.1 Challenge domain models

| Area | Verified implementation | Source |
|---|---|---|
| Challenge model | `Challenge` stores `title`, `slug`, `description`, `scenario`, `objectives` (JSON list), `instructions`, `category` FK (`PROTECT`), `difficulty` choices `Easy/Medium/Hard/Insane`, `points`, `author`, `created_by`, `tags` (JSON list), `featured`, `trial`, `solves`, `connection_info`, runtime fields (`runtime_enabled/image/command/connection_type/internal_port/cpu/memory/pids/read_only/duration_minutes/access_mode`), `cheatsheet` (JSON list), `status` (`draft/published/scheduled`), `publish_at`, timestamps. `has_flag` and `verify_flag(raw)` delegate to related flag. | `ctf-platform-be/challenges/models.py` (`ChallengeQuerySet`, `Challenge`) |
| Category model | `Category` has `name`, unique `slug`, `description`, `icon`, `color`, `order`; slug auto-derived via `unique_slug`. Deletion protected conceptually by app logic for challenge/achievement references in views (not DB cascade for challenges: challenge FK uses `PROTECT`). | `ctf-platform-be/challenges/models.py` (`Category`, `unique_slug`), `ctf-platform-be/challenges/views.py` (`_achievement_category_references`, admin category delete) |
| Flag model | `ChallengeFlag` one-to-one to challenge; stores `hash`, optional `note`, `updated_at`. `normalize()` strips surrounding whitespace only and preserves case. `set_flag()` hashes with `make_password(normalize(raw))`. `verify()` uses `check_password(normalize(raw), self.hash)`. No plaintext storage/serialization. | `ctf-platform-be/challenges/models.py` (`ChallengeFlag`) |
| Hint model | `ChallengeHint` FK to challenge, `text`, `cost` (non-negative), `order`, ordered by `order,id`. Cascade-deletes with challenge. | `ctf-platform-be/challenges/models.py` (`ChallengeHint`) |
| Attachment model | `ChallengeAttachment` FK to challenge, `FileField(upload_to='challenge_files/')`, optional display `name`, `uploaded_at`, `display_name`/`extension` helpers, `post_delete` signal removes backing file. | `ctf-platform-be/challenges/models.py` (`ChallengeAttachment`, `_delete_attachment_file`) |
| Submission/solve/unlock models | `Submission` stores user/challenge/correct/timestamp only (no plaintext guess). `Solve` unique per `(user, challenge)` with points snapshot. `HintUnlock` unique per `(user, hint)` with cost snapshot and denormalized challenge FK. | `ctf-platform-be/submissions/models.py` (`Submission`, `Solve`, `HintUnlock`) |
| Instance model | `ChallengeInstance` exists for runtime instances (not required for Decode Me). | `ctf-platform-be/instances/models.py` |

### 2.2 Serializers

| Area | Verified implementation | Source |
|---|---|---|
| Public challenge serializer | `ChallengePublicSerializer` exposes: `id, slug, title, category, category_id, difficulty, points, description, scenario, objectives, instructions, author, tags, featured, trial, solves, solved, connectionInfo, instanceMode, cheatsheet, hints, files, createdAt, status`. `solved` computed from context `solved_ids` or fallback DB check against `submissions.models.Solve`. No flag/hash/note/runtime image/command/port/solution fields. | `ctf-platform-be/challenges/serializers.py` (`ChallengePublicSerializer`) |
| Admin challenge serializer | `ChallengeAdminSerializer` extends public shape and replaces hints with `AdminHintSerializer` (text/cost/order), adds `has_flag`, `flag_note`, `publishAt`, `created_by`, `updated_at`. Never exposes plaintext flag. | `ctf-platform-be/challenges/serializers.py` (`ChallengeAdminSerializer`) |
| Write serializer | `ChallengeWriteSerializer` accepts write-only `flag`, `flag_note`, `publishAt`, `hints` and admin runtime fields. `FLAG_PATTERN = re.compile(r'^CTF\{.+\}$')`; create requires non-empty flag and matching pattern; update applies pattern when flag provided. Validates runtime config (image required when enabled; internal port required for enabled HTTP runtime). Persists flag via `ChallengeFlag.set_flag()` and rewrites hints. `to_representation` returns admin serializer. | `ctf-platform-be/challenges/serializers.py` (`FLAG_PATTERN`, `ChallengeWriteSerializer`) |
| Public/admin hints | `PublicHintSerializer` returns `id,cost,order,revealed,text` where text is empty unless hint id in `revealed_hint_ids`. `AdminHintSerializer` returns `id,text,cost,order`. `ChallengeHintWriteSerializer` accepts `text,cost`. | `ctf-platform-be/challenges/serializers.py` |
| Attachments | `AttachmentSerializer` returns `id,name,size,type,url`; URL is reversed to `challenges_api:attachment-download` (not storage URL). | `ctf-platform-be/challenges/serializers.py` (`AttachmentSerializer`, `human_size`) |
| Flag submission serializer | `FlagSubmissionSerializer` validates `flag` required/nonblank/trimmed/max 256 chars. No prefix check and no case normalization beyond trim. | `ctf-platform-be/submissions/serializers.py` (`FlagSubmissionSerializer`) |

### 2.3 Views, endpoints, permissions, and behavior

| Area | Verified implementation | Source |
|---|---|---|
| Public challenge APIs | `GET /api/v1/challenges/` (`PublicChallengeListView`, `AllowAny`, plain array) supports `category`, `difficulty`, `search`. `GET /api/v1/challenges/{id}/` (`PublicChallengeDetailView`) returns published only. `GET /api/v1/categories/` returns categories with published challenge counts. | `ctf-platform-be/challenges/views.py`, `ctf-platform-be/challenges/urls.py`, `ctf-platform-be/config/urls.py` |
| Admin challenge APIs | `GET/POST /api/v1/admin/challenges/`, `GET/PATCH/DELETE /api/v1/admin/challenges/{id}/`, `PATCH /api/v1/admin/challenges/{id}/status/` guarded by `IsAuthenticated` + `DjangoModelPermissionsWithView` (`view/add/change/delete_challenge`). Only draft challenges deletable. Status endpoint validates `draft/published/scheduled` and requires `publishAt` for scheduled. Audit actions logged. | `ctf-platform-be/challenges/views.py` (`AdminChallengeListCreateView`, `AdminChallengeDetailView`, `AdminChallengeStatusView`), `ctf-platform-be/challenges/admin_urls.py` |
| Attachment APIs | Admin upload/delete: `POST /api/v1/admin/challenges/{id}/attachments/`, `DELETE /api/v1/admin/challenges/{id}/attachments/{attachment_pk}/` require `IsAuthenticated` + `HasChallengeChangePermission` (`challenges.change_challenge`). Upload enforces `MAX_CHALLENGE_ATTACHMENT_BYTES`. Download: `GET /api/v1/challenges/{id}/attachments/{attachment_pk}/download/` allows published attachments publicly; draft/scheduled require `challenges.view_challenge` else 404; serves `FileResponse(..., as_attachment=True)` with `Cache-Control: private, no-store`. | `ctf-platform-be/challenges/views.py`, `ctf-platform-be/challenges/permissions.py`, `ctf-platform-be/challenges/urls.py` |
| Flag submit | `POST /api/v1/challenges/{id}/submit/` (`FlagSubmitView`, `IsAuthenticated`, `FlagSubmitThrottle`) resolves published challenge only, verifies against stored hash, records `Submission(correct=...)` without plaintext, returns incorrect/already-solved/correct responses with hint-cost/net-points messaging, and awards solve once via `services.award_solve`. | `ctf-platform-be/submissions/views.py`, `ctf-platform-be/submissions/services.py`, `ctf-platform-be/submissions/urls.py` |
| Hint reveal | `POST /api/v1/challenges/{id}/hints/{hint_id}/reveal/` (`HintRevealView`, `IsAuthenticated`, `HintRevealThrottle`) ignores request body, checks platform setting `allow_hints`, requires published challenge and hint belonging to it, uses `unlock_hint` for server-side cost/deduction/uniqueness, returns text only on success/already-unlocked. | `ctf-platform-be/submissions/views.py`, `ctf-platform-be/submissions/services.py`, `ctf-platform-be/platform_settings/services.py` (referenced) |
| History/stats/leaderboard | Personal submission/solve history, stats, leaderboard endpoints exist and are scoped/read-only as implemented. | `ctf-platform-be/submissions/views.py`, `ctf-platform-be/submissions/urls.py` |
| Runtime | Instances/terminal subsystems exist; challenge runtime fields exist on model/serializers/admin UI. Decode Me can remain `runtime_enabled=false` with no instance. | `ctf-platform-be/challenges/models.py`, `ctf-platform-be/challenges/serializers.py`, `ctf-platform-be/instances/*`, `ctf-platform-be/config/settings.py` |
| User mode source | `User.onboarding` JSON can contain `userType`; onboarding POST stores submitted validated data and marks complete. No dedicated endpoint found to persist only mode changes outside onboarding/profile flows. | `ctf-platform-be/users/models.py`, `ctf-platform-be/users/serializers.py` (`OnboardingSerializer`), `ctf-platform-be/users/views.py` (`OnboardingView`), `ctf-platform-be/users/urls.py` |

### 2.4 Answers to required backend questions

1. **How is a challenge created?**  
   - Admin API: `POST /api/v1/admin/challenges/` handled by `challenges.views.AdminChallengeListCreateView` (`perform_create` saves `created_by=request.user`, logs audit). Input validated/saved by `challenges.serializers.ChallengeWriteSerializer.create()` (creates challenge, hashes/stores flag via `ChallengeFlag.set_flag`, bulk creates hints).  
   - Permissions: DRF model permissions require `challenges.add_challenge` for POST.  
   - Seeder exists for sample data: `challenges.management.commands.seed_challenges.Command._seed_challenges()`.

2. **How is its flag stored and validated?**  
   - Stored: `ChallengeWriteSerializer` receives write-only plaintext `flag`; `create/update` call `ChallengeFlag.set_flag()` which stores `make_password(normalize(raw))` in `ChallengeFlag.hash`. Plaintext discarded.  
   - Validated: player submit path `submissions.views.FlagSubmitView.post()` → `Challenge.verify_flag()` → `ChallengeFlag.verify()` → `check_password(normalize(raw), hash)`. Correct/incorrect attempts recorded as `Submission` rows without plaintext.

3. **Is flag validation case-sensitive?**  
   - **Yes.** `ChallengeFlag.normalize()` only strips surrounding whitespace (`str(raw).strip()`), preserving case; `check_password` compares exact normalized input against hash. `FlagSubmissionSerializer` trims whitespace but does not alter case.

4. **How are downloadable files currently supported?**  
   - Model/storage: `ChallengeAttachment(file=FileField(upload_to='challenge_files/'), name, uploaded_at)` with delete-signal cleanup.  
   - Upload: admin `POST /api/v1/admin/challenges/{id}/attachments/` (`AdminChallengeAttachmentView.post`, multipart `file`, optional `name`), requires `challenges.change_challenge`, enforces `settings.MAX_CHALLENGE_ATTACHMENT_BYTES` (default 25 MiB), audited.  
   - Download: `GET /api/v1/challenges/{id}/attachments/{attachment_pk}/download/` (`ChallengeAttachmentDownloadView.get`), ID-scoped lookup, published public / draft-scheduled restricted to `view_challenge` else 404, `FileResponse` attachment download, guessed content type, `Cache-Control: private, no-store`. Serializer exposes authorized endpoint URL, not direct storage path.

5. **Can a challenge exist without a Docker runtime?**  
   - **Yes.** `Challenge.runtime_enabled` defaults to `False`; runtime fields optional/validated conditionally in write serializer. Static challenges are served normally by public detail/list APIs. (Instance start logic rejects non-runtime-enabled challenges in runtime services; not needed for Decode Me.)

6. **How are hints stored and returned?**  
   - Stored: `ChallengeHint(challenge,text,cost,order)`; written on admin create/update by replacing challenge hints.  
   - Returned: public challenge payload includes hint metadata via `PublicHintSerializer` (`id,cost,order,revealed,text`) with text only for hints unlocked by requesting user (`HintUnlock` IDs injected in view context). Admin payload includes full hint text/cost/order.  
   - Reveal: authenticated `POST /api/v1/challenges/{id}/hints/{hint_id}/reveal/` validates published challenge/hint ownership, charges once via `unlock_hint` (`HintUnlock` unique constraint, balance checks), returns hint text and remaining points.

7. **Can learning objectives, tasks and checkpoints be stored?**  
   - **Partially.** `Challenge.objectives` is a JSON list of strings and is supported in model/serializers/admin UI/frontend rendering.  
   - **No dedicated support** for structured tasks, checkpoints, task completion/progress state, review questions, common mistakes, or solution objects. These could only be approximated in free-form text/JSON blobs, which is insufficient for backend mode gating and post-solve protection without schema/API changes.

8. **Can Student Mode and Competitor Mode receive different content?**  
   - **Not currently in backend.** `userType` is stored in `User.onboarding` (and surfaced by auth/user serializers), but challenge public/admin APIs do not branch by user type and no challenge endpoint accepts/derives mode for content filtering. Frontend toggles (`Challenges.jsx`, `Settings.jsx`) update local app state via `updateUser` only. Therefore different content cannot be securely separated today.

9. **Are solutions protected until a successful solve?**  
   - **No solution mechanism exists.** No solution field/serializer/API found in challenges or submissions. Completion UI shows points/modal only; repeated correct submits return `alreadySolved` with no extra points. Any future solution must be gated server-side on `Solve` existence for the requesting user.

10. **Which existing APIs can be reused?**  
    - Public: `GET /api/v1/challenges/`, `GET /api/v1/challenges/{id}/`, `GET /api/v1/categories/`, attachment download endpoint.  
    - Admin: challenge CRUD/list/detail/status, attachment upload/delete, category admin APIs.  
    - Player actions: flag submit, hint reveal, submissions/solves/stats/leaderboard.  
    - Auth/profile: `/api/v1/auth/me/`, onboarding/preferences endpoints (and existing user normalization) for user identity/profile data.  
    - Frontend services/components: `challengeService` get/list/submit/reveal/admin methods, challenge list/detail/hint/admin pages/components.

### 2.5 Security-relevant backend observations

- Flag plaintext is write-only in API flow; public/admin read serializers never expose it. Audit helper excludes keys containing `flag` (`audit.services.changed_fields` usage in challenge views; not fully reproduced here). `FLAG{...}` redaction in logs may not be covered if observability only targets `CTF{...}`.
- `ChallengePublicSerializer` is `AllowAny`; any new sensitive field added there becomes public.
- Draft/scheduled attachments are protected by 404 unless `challenges.view_challenge`. Published attachments are intentionally public to anyone who can access the ID URL.
- `config/urls.py` includes `static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)` (dev behavior depends on DEBUG/static helper); direct `/media/` exposure must be avoided in production deployment.
- Submission and solve logic are protected by uniqueness constraints/transactional service logic (`award_solve`, `unlock_hint`).

---

## 3. Frontend inspection

| Area | Verified implementation | Reuse notes | Source |
|---|---|---|---|
| Challenge listing | Loads challenges via `challengeService.getChallenges(filters)` with server filters (`category`,`difficulty`,`search`), applies client-side solved/sort/grouping and student-mode curation when defaults/no search. Mode toggle buttons call local `switchMode -> updateUser({userType})` only. | Reusable for Decode Me listing (Cryptography/Easy/static). No backend mode persistence/gating. | `ctf-platform/src/pages/Challenges.jsx`, `src/services/challengeService.js`, `src/components/ui/ChallengeFilter.jsx`, `src/components/ui/ChallengeCard.jsx` |
| Challenge details | Fetches challenge detail and active instance state, renders tabs: Description, Objectives, Cheatsheet, Hints, Files (if any), Connect (if `connectionInfo`). Supports artifact download links from `files[].url`, hint reveal via `HintCard`, flag submission via `submitFlag`, completion modal, instance start/stop/terminal UI for runtime challenges. Flag input placeholder/help hardcoded to `CTF{...}`. No solution display. | Core UI reusable; copy/format and optional mode-content rendering would need changes later. | `ctf-platform/src/pages/ChallengeDetails.jsx`, `src/components/ui/HintCard.jsx`, `src/components/ui/CheatsheetTab.jsx`, `src/components/ui/InteractiveTerminal.jsx` |
| Hint display | `HintCard` seeds from `hint.revealed`/`hint.text`, calls `challengeService.revealHint(challengeId,hintId)`, updates local state and user points from server response, refreshes stats. | Reusable as-is for paid progressive hints. | `ctf-platform/src/components/ui/HintCard.jsx`, `src/services/challengeService.js` |
| Student/Competitor UI | Landing `UserTypeSelector` links to challenges/register; Challenges has Student/Competitor toggle; Settings allows switching mode; Dashboard/About copy varies by `userType`; onboarding captures/stores user type in payload flow. All mode state is client/app-context normalized from stored user/onboarding. | Presentation reusable; secure separation not enforceable without backend. | `src/pages/Challenges.jsx`, `src/pages/Settings.jsx`, `src/pages/Dashboard.jsx`, `src/pages/Onboarding.jsx`, `src/components/ui/UserTypeSelector.jsx`, `src/context/AppContext.jsx`, `src/services/authService.js`, `src/services/onboardingService.js` |
| Admin challenge create/edit | Tabbed form for basic/content/flag-hints/files/deploy; loads categories and challenge (edit); validates required title/flag on create and requires `CTF{` prefix client-side; builds payload with tags/objectives/hints/connection/runtime fields; uploads selected files after save via `uploadAttachment` loop (note: selected file objects handling in form is limited). Edit fetches admin challenge and populates form including runtime/connection info. | Reusable base; flag prefix/UI and any future mode-content fields would need extension. | `src/pages/admin/CreateChallenge.jsx`, `src/pages/admin/ManageChallenges.jsx`, `src/services/challengeService.js` |
| Admin management | Lists/searches/filters challenges, status toggles/scheduling/duplicate/delete/preview/edit actions, export. Duplicate hardcodes `flag: 'CTF{duplicate_flag}'`. | Reusable admin operations. | `src/pages/admin/ManageChallenges.jsx` |
| Services/API layer | `challengeService` covers public list/detail/categories, submit, revealHint, instance ops, admin CRUD/status/attachments/categories. Auth/user state normalized in `authService`/`AppContext`; `statsService` refresh used after submit/reveal. | Reusable; no mode-content/solution/mode-persist APIs exist. | `src/services/challengeService.js`, `src/services/api.js`, `src/context/AppContext.jsx` |

---

## 4. Reusable existing functionality (verified)

- **Challenge/category CRUD and publication lifecycle:** admin challenge/category endpoints, status transitions, audit logging.
- **Flag security model:** write-only plaintext input, hashed storage (`ChallengeFlag`), case-sensitive verification, no public exposure.
- **Submission/solve pipeline:** authenticated published-only submit, attempt history without plaintext, unique solve awarding, points/hint-cost accounting, stats/history integration.
- **Hint system:** ordered costed hints, public metadata-only exposure, server-side paid reveal and unlock uniqueness.
- **Attachment system:** admin upload with size cap, authorized ID-based download, draft protection.
- **Static challenge support:** no Docker/runtime required (`runtime_enabled=false`).
- **Frontend shells:** challenge list/detail/tabs, file download links, hint cards, flag submit/completion flow, admin create/manage screens.

---

## 5. Missing functionality for Decode Me

| Gap | Why it matters | Current state |
|---|---|---|
| `FLAG{...}` acceptance | Decode Me requires `FLAG{...}` format. | Backend write validator `^CTF\{.+\}$`; frontend admin/create and detail copy assume `CTF{...}`. |
| Structured student mode content | Required: objectives/tasks/checkpoints/concepts/review questions/common mistakes/remediation/solution. | Only generic fields exist (`description/scenario/objectives/instructions/cheatsheet`); no task/checkpoint/progress/review/solution schema. |
| Backend-enforced mode separation | Competitor must not receive student-only content pre-solve; must not rely on frontend hiding. | No mode-aware challenge content API/serializer behavior; mode toggles client-only. |
| Post-solve gated solution | Student and competitor need solution explanation after successful solve only. | No solution storage or solve-gated delivery. |
| Mode-aware hint exposure | Competitor mode must not expose student progressive hints/guidance. | Public hint metadata returned regardless of mode; reveal flow exists but not mode-gated for visibility. |
| Server-persisted mode preference (recommended) | Backend gating requires authoritative mode. | `userType` lives in onboarding JSON; no narrow mode update endpoint observed. |
| Flag prefix redaction/log hygiene for `FLAG{}` | Prevent accidental plaintext flag leakage in logs/errors for new prefix. | Existing flag handling avoids storage/exposure; log redaction scope not verified to include `FLAG{}`. |

---

## 6. Assumptions requiring confirmation

1. **Flag prefix policy:** accept both `FLAG{...}` and legacy `CTF{...}` (recommended for compatibility) vs enforce only `FLAG{...}` globally.
2. **Database category availability:** `Cryptography` is defined by seed data in code; target DB state not queried in this stage.
3. **Mode authority:** whether user mode should be server-persisted and editable post-onboarding (required for secure gating) and default mode when unset.
4. **Competitor hint policy:** whether competitors see no hints at all, or a different non-guided hint set (spec assumes no student hints/solutions pre-solve).
5. **Solution content exposure:** exact post-solve fields allowed per mode and whether solution may include explanatory text only (must never include plaintext flag in public responses/logs/artifacts).
6. **Scoring/authoring metadata:** proposed points (e.g. 100), author label, tags, publish workflow, and whether hints deduct points.
7. **Deployment media exposure:** production must not publicly serve `MEDIA_ROOT` outside authorized download endpoint (especially given dev `static(MEDIA_URL)` wiring).
8. **"No external websites":** interpreted as solvable with local tools/knowledge only.

---

## 7. Evidence boundaries

- Findings are based on direct source inspection of listed files and frontend components/services.
- Database contents and runtime behavior were not executed or mutated.
- Existing challenge records were not inspected by query and not modified.
