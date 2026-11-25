# Decode Me — Test Cases and Verification Record

**Stage:** 2 — Content preparation  
**Date:** 2026-11-19

This file records the checks performed on the Stage 2 artifact and defines the test cases to use during later backend/frontend integration. No application test suite or database was used for Stage 2.

---

## 1. Artifact quality checks — executed

| ID | Check | Method | Expected | Result |
|---|---|---|---|---|
| A1 | File exists at expected path | Directory listing | Single `decode-me-message.txt` | **PASS** |
| A2 | Artifact is small | Byte count | Well under 25 MiB attachment cap | **PASS — 169 bytes** |
| A3 | Portable encoding | Byte inspection | ASCII only, no BOM | **PASS** |
| A4 | Portable line ending | Byte inspection | LF only, no CR | **PASS — 0 CR, 1 LF** |
| A5 | Single readable line | Line count | One line plus trailing newline | **PASS** |
| A6 | Valid Base64 | .NET and Node.js decode | Decode succeeds | **PASS** |
| A7 | Decoded output matches internal note | Independent decode | Exact three-line field note | **PASS** |
| A8 | No plaintext flag in artifact | Literal search for `FLAG{base64_is_not_a_lock}` and `FLAG{` | Absent | **PASS** |
| A9 | No plaintext flag in decoded note | Literal search | Absent | **PASS** |
| A10 | No explicit technique name in decoded note | Search for `base64` | Absent | **PASS** |
| A11 | No hidden/sidecar files | Directory listing with hidden files | Only the six deliverables after this file is written | **PASS at artifact creation** |
| A12 | No external dependency | Content inspection | No URL, package, service, or Docker reference | **PASS** |
| A13 | No unnecessary metadata | File content and directory inspection | No archive, README, script, or metadata file | **PASS** |

### Independent decode evidence

Node.js decode of the written file produced:

```text
FIELD NOTE 07
Name the carrier, then say what it is not.
No key exists; join with underscores and use standard flag braces.
```

PowerShell `[Convert]::FromBase64String` produced the same output. The two independent decoders agreed.

---

## 2. Artifact content assertions

| ID | Assertion | Expected |
|---|---|---|
| AC1 | Artifact ends with Base64 padding | `==` |
| AC2 | Decoded note names a carrier without naming the encoding | True |
| AC3 | Decoded note states it is not a lock | True |
| AC4 | Decoded note instructs joining with underscores | True |
| AC5 | Decoded note instructs use of standard flag braces | True |
| AC6 | Decoded note gives no key, password, or URL | True |

---

## 3. Submission test cases for later integration

| ID | Submitted value | Expected result |
|---|---|---|
| S1 | `FLAG{base64_is_not_a_lock}` | Correct; first solve awards points once. |
| S2 | `  FLAG{base64_is_not_a_lock}  ` | Correct if outer whitespace is trimmed. |
| S3 | `flag{base64_is_not_a_lock}` | Incorrect; case-sensitive. |
| S4 | `FLAG{Base64_is_not_a_lock}` | Incorrect; changed capitalization. |
| S5 | `FLAG{base64_is_not_lock}` | Incorrect; missing `a`. |
| S6 | `FLAG{base64_is_not_a_Lock}` | Incorrect; changed final-word case. |
| S7 | `CTF{base64_is_not_a_lock}` | Incorrect / invalid for this challenge. |
| S8 | `FLAG{base64_is_not_a_lock` | Incorrect / invalid format. |
| S9 | `base64_is_not_a_lock` | Incorrect; missing wrapper. |
| S10 | empty string | Rejected by request validation. |
| S11 | string longer than 256 characters | Rejected by `MAX_FLAG_LENGTH`. |
| S12 | repeat of S1 by same user | Already solved; no additional points. |

---

## 4. Mode content test cases for later integration

| ID | Test | Expected result |
|---|---|---|
| M1 | Student opens challenge before solving | Objectives, tasks, checkpoints, and concept explanation visible; full solution hidden. |
| M2 | Student reveals hints in order | Hint 1 → 4 each reveal progressively more; each unlock charged once. |
| M3 | Competitor opens challenge | Independent scenario, objective, download instructions, rules, time, and scoring only. |
| M4 | Competitor view for student scaffolding | No tasks, checkpoints, hints, walkthrough, review answers, or common mistakes. |
| M5 | Client changes local mode to student | Backend still returns competitor content. |
| M6 | Any user before solve | No solution or review answer key. |
| M7 | User after solve | Solution visible only in the user's own mode. |
| M8 | Artifact download | Same single file in both modes, via authorized download endpoint. |

---

## 5. Backend compatibility assumptions to verify later

1. Admin create accepts `FLAG{...}` after the planned validator change.
2. Flag is stored only as a hash; plaintext never appears in API reads, logs, or audit metadata.
3. Hint reveal remains server-authoritative and one unlock per `(user, hint)`.
4. Solve tracking remains one solve per `(user, challenge)`.
5. Challenge has `runtime_enabled = False` and no connection info.
6. Category is Cryptography and difficulty is Easy.
7. Points are 100.

---

## 6. Stage 2 limitation

Stage 2 prepared and verified content only. It did not create a challenge record, upload the artifact, register hints, change application code, or publish anything. Tests in sections 3–5 are definitions for later implementation stages, not results claimed here.
