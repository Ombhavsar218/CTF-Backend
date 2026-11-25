# Decode Me — Challenge Specification

**Stage:** 1 (Design/specification only; not implemented)  
**Date:** 2026-11-19  
**Status:** Original Flaghunt challenge design prepared from verified architecture inspection.

> **Confidential design note:** This document contains the intended flag and solution path for internal implementation/publication use. Do not expose this content to players or in public challenge APIs before authorized publication and solve-gating controls are in place.

---

## 1. Challenge definition

| Property | Value |
|---|---|
| Name | Decode Me |
| Slug (proposed) | `decode-me` |
| Category | Cryptography |
| Difficulty | Easy |
| Points (proposed) | 100 |
| Runtime | Downloadable artifact (static) |
| Docker required | No (`runtime_enabled = false`) |
| Primary concept | Encoding and decoding |
| Flag format | `FLAG{...}` |
| Supported modes | Student Mode and Competitor Mode |
| Tags (proposed) | `cryptography`, `encoding`, `base64`, `beginner` |
| Author (proposed) | `FlagHunt Team` |

### Design goals

- Original, beginner-friendly, and logically consistent.
- Solvable with local reasoning/tools only (no external websites required).
- No Docker instance, no service connection, no runtime dependency.
- Student Mode teaches progressively; Competitor Mode remains independent.
- Flag and solution are never exposed in public challenge responses or artifact metadata.

---

## 2. Artifact specification

### A. File details

| Item | Specification |
|---|---|
| File name | `decode-me.txt` |
| Format | UTF-8 plain text, single line (optionally final newline) |
| Size | Small (< 1 KB) |
| Delivery | Admin-uploaded `ChallengeAttachment` on the challenge; downloaded via existing authorized attachment download endpoint |
| Packaging | No archive required; do not include extra hidden files |

### B. Encoded message (exact content)

```text
RkxBR3tiNjRfaXNfbm90X2VuY3J5cHRpb259
```

### C. Encoding technique

- **Technique:** Base64 encoding (standard Base64 alphabet, padded output).
- **What is encoded:** the final flag string.
- **Concept:** Base64 is an encoding/representation transform, not encryption and not a hash.

### D. Clues available to the player

- Artifact contains a single compact alphanumeric string ending with `=` padding.
- Character set and padding are consistent with Base64.
- Challenge states the task is to identify and decode an encoded message (no brute-force service, no key exchange).
- No password, cipher key, container password, or network service is provided/needed.

### E. Intended solving path

1. Download `decode-me.txt` from the challenge Files tab/attachment link.
2. Inspect the content and recognize likely Base64 (length/padding/charset).
3. Decode locally using any offline/local method, e.g.:
   - PowerShell: `[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((Get-Content .\decode-me.txt -Raw).Trim()))`
   - Python (local): `python -c "import base64; print(base64.b64decode(open('decode-me.txt').read().strip()).decode())"`
   - Linux shell (local): `base64 -d decode-me.txt`
4. Read the decoded plaintext flag.
5. Submit the exact flag string in the platform submission form.

### F. Expected flag

```text
FLAG{b64_is_not_encryption}
```

**Validation characteristics:** case-sensitive; exact content inside braces required; leading/trailing whitespace around submission may be trimmed by existing submission normalization but flag characters/case must match.

### G. Artifact integrity / anti-leak requirements

- The plaintext flag must **not** appear in: file contents, filename, file metadata/comments, alternate streams, extra files, archive members, challenge description/instructions/hints shown pre-solve, or solution text exposed before solve.
- The artifact should contain only the encoded string (and optional newline).
- No steganography, no hidden archive layers, no misleading fake flags.

---

## 3. Student Mode design

Student Mode provides guided learning while preserving an initial independent attempt.

### A. Learning objectives

1. Distinguish encoding from encryption and hashing.
2. Recognize common Base64 characteristics (alphabet and padding).
3. Decode Base64 data locally to recover original text.
4. Submit flags accurately using the platform's required format and case sensitivity.

### B. Challenge introduction (student-facing)

> **Decode Me (Student Mode):** You've recovered a short message left behind in an investigation, but it isn't readable yet. Your task is to identify how the message was transformed, reverse it safely on your own machine, and recover the flag. Start by examining the downloaded file before using hints.

### C. Progressive tasks

| Task | Goal | Learner action | Expected outcome |
|---|---|---|---|
| T1. Inspect the artifact | Understand the data shape | Open `decode-me.txt` and note charset/length/padding | Learner observes Base64-like string ending with `=` |
| T2. Identify the transform | Choose the right technique | Match observations to common encodings | Learner hypothesizes Base64 (not encryption) |
| T3. Decode locally | Recover plaintext | Decode the full string with a local tool/command | Learner obtains readable text in `FLAG{...}` format |
| T4. Verify and submit | Practice precision | Confirm full flag, case, and braces, then submit | Correct solve recorded once |

### D. Checkpoints

- **CP1:** "I can describe the artifact format." (single encoded line, Base64-like characters/padding)
- **CP2:** "I selected a decoding method, not a cracking method." (no key/password brute force)
- **CP3:** "I decoded the complete value." (no truncation, padding preserved in input)
- **CP4:** "I submitted the exact flag." (correct prefix/case/content)

### E. Progressive hints (low to high guidance)

| Order | Cost (proposed) | Hint text (to be stored as normal `ChallengeHint` text, revealed server-side) |
|---:|---:|---|
| 1 | 5 | Look closely at the characters in the file. The set of letters/numbers and the trailing `=` are strong clues about the encoding. |
| 2 | 10 | This is Base64 encoding. Base64 changes representation; it does not require a secret key. |
| 3 | 15 | Decode the entire contents of `decode-me.txt` using a local Base64 decoder/tool. Keep the output exactly as produced. |
| 4 | 20 | The decoded message is the flag itself and uses the `FLAG{...}` format. Check capitalization and underscores before submitting. |

**Hint policy:** hints are optional, point-costed (existing unlock mechanism), and should not reveal the plaintext flag.

### F. Conceptual explanations (learning panel content)

- **Encoding vs encryption:** encoding makes data portable/representable (reversible by anyone who knows the scheme); encryption protects confidentiality using keys.
- **Base64 basics:** maps binary/text bytes into ASCII characters (`A-Z`, `a-z`, `0-9`, `+`, `/`) with `=` padding; commonly seen in tokens, attachments, and data transport.
- **Why this matters in CTFs:** quick identification prevents wasting time on decryption/password attacks.

### G. Final solution explanation (post-solve, gated)

**Prerequisite:** visible only after the requesting user has a successful solve for this challenge.

Proposed explanation (no plaintext flag shown):
- The artifact string is Base64-encoded data.
- Decoding the full Base64 value restores the original plaintext message.
- The recovered message is the challenge flag in `FLAG{...}` format.
- Key lesson: Base64 can be reversed without secrets, so it should not be mistaken for encryption.

### H. Review questions

1. What clues in `decode-me.txt` suggested Base64?
2. Why is Base64 decoding different from decrypting a cipher?
3. What happens if padding or characters are removed before decoding?
4. Why must flag submissions match the exact required format/case?

### I. Common mistakes and remediation

| Mistake | Why it happens | Remediation |
|---|---|---|
| Treating Base64 as encryption | "Looks scrambled" assumption | Ask: is there a key? If no key and format is recognizable, try decoding first. |
| Dropping trailing `=` padding | Copy/paste/editing error | Decode the exact file contents; preserve padding. |
| Submitting wrong case/prefix | Manual retyping | Copy decoded output carefully; verify `FLAG{...}` format and case. |
| Trying random ciphers/bruteforce | Overcomplicating an easy challenge | Use observation-first workflow: inspect → identify → decode. |
| Using untrusted online decoder sites | Habit/convenience | Use local/offline tools available on the machine (PowerShell/Python/base64 utility). |

---

## 4. Competitor Mode design

Competitor Mode is an independent challenge experience with minimal guidance.

### A. Challenge description (competitor-facing)

> **Decode Me:** An intercepted message was stored in encoded form. Download the artifact, determine the encoding, decode it, and submit the recovered flag.

### B. Artifact download

- Same file: `decode-me.txt` with the same encoded message.
- Accessed through existing challenge attachment download flow.
- No additional bundled files or runtime endpoints.

### C. Challenge rules

- No Docker instance is provided or required.
- Solve locally; do not rely on external websites/services.
- Submit the exact flag in `FLAG{...}` format (case-sensitive).
- Standard platform submission/attempt rules apply (authenticated user, published challenge).

### D. Flag submission instructions

- Open the challenge detail page, download the artifact, decode locally, and submit the recovered flag in the flag field.
- Correct submissions follow existing platform behavior: first correct solve awards points once; repeated correct submissions report already solved with no additional points.

### E. Scoring configuration (proposed)

| Item | Proposed value |
|---|---|
| Points | 100 |
| Difficulty | Easy |
| Hints | Not exposed in Competitor Mode (recommended); if any exist administratively, they must not be visible before solve |
| Penalty model | Reuse existing hint-unlock cost mechanism only for Student Mode hints; no extra penalties introduced |
| Solve behavior | Reuse existing `Solve` uniqueness and point award logic |

### F. Competitor-visible content boundary

Competitor Mode must **not** expose (before or after solve, except concise post-solve solution as allowed by policy): student introduction text, progressive tasks, checkpoints, progressive hints, conceptual explanations, review questions, common mistakes/remediation. Any post-solve solution shown to competitors must be minimal and must not leak the plaintext flag.

---

## 5. Flag handling specification

| Item | Specification |
|---|---|
| Intended flag | `FLAG{b64_is_not_encryption}` |
| Storage approach | Store only hashed value via existing `ChallengeFlag.set_flag()` / Django password hash mechanism. Never store plaintext in DB fields, logs, attachments, docs exposed publicly, or API responses. |
| Existing validation mechanism to reuse | `ChallengeFlag.set_flag()` + `ChallengeFlag.verify()` / `Challenge.verify_flag()` and submission flow in `submissions.views.FlagSubmitView` + `services.award_solve`. Case-sensitive, whitespace-trim normalization as currently implemented. |
| Validator changes needed | **Yes (input/authoring format only):** backend `FLAG_PATTERN` and frontend admin/create validation/UI copy currently enforce `CTF{...}` and must be updated to accept `FLAG{...}` (recommend dual-accept `CTF{` or `FLAG{` for compatibility, with confirm). Verification logic itself is prefix-agnostic and reusable. |
| Public API exposure risks | Public challenge serializers/endpoints must not include flag, flag hash, flag note (except admin-only contexts already gated), pre-solve solution, or student-only content when in competitor context. Attachment download is public for published files by design; artifact must not contain plaintext flag. |
| Solution access restrictions | If implemented, solution content must be returned only by backend after verifying authenticated user has a `Solve` for the challenge (and only for allowed mode/content). No client-side-only gating. |

---

## 6. Registration metadata (proposed for later stage)

- **Title:** Decode Me
- **Category:** Cryptography
- **Difficulty:** Easy
- **Points:** 100
- **Status flow:** create as draft, verify, then publish
- **Runtime:** disabled, no connection info
- **Attachments:** exactly `decode-me.txt`
- **Hints:** 4 progressive student hints as specified (costs 5/10/15/20) if student mode hinting is implemented
- **Solution:** post-solve explanatory text only (no plaintext flag)

All registration/publication actions are deferred to later stages and require explicit authorization.
