# Decode Me — Challenge Specification

**Stage:** 2 — Artifact and content preparation  
**Status:** Content prepared; not registered or published  
**Date:** 2026-11-19

> Internal authoring document. It contains the expected flag and decoded clue. Do not expose this file or `SOLUTION.md` to players.

---

## 1. Challenge identity

| Property | Value |
|---|---|
| Name | Decode Me |
| Proposed slug | `decode-me` |
| Category | Cryptography |
| Difficulty | Easy |
| Points | **100** |
| Runtime | Downloadable artifact |
| Docker | Not required; runtime must remain disabled |
| Flag format | `FLAG{...}` |
| Expected flag | `FLAG{base64_is_not_a_lock}` |
| Modes | Student Mode and Competitor Mode |
| Suggested competitor time | 5–10 minutes |

**Scoring rationale:** 100 matches the platform's existing Easy/default challenge value and keeps this beginner encoding challenge below intermediate cipher or exploitation tasks. No hint penalty is proposed for Competitor Mode.

---

## 2. Artifact

### File

- **Name:** `decode-me-message.txt`
- **Format:** ASCII plain text, LF line ending, one Base64 line plus a trailing newline.
- **Size:** 169 bytes.
- **Dependencies:** none. No Docker, service, package, or external website is required.

### Artifact contents

```text
RklFTEQgTk9URSAwNwpOYW1lIHRoZSBjYXJyaWVyLCB0aGVuIHNheSB3aGF0IGl0IGlzIG5vdC4KTm8ga2V5IGV4aXN0czsgam9pbiB3aXRoIHVuZGVyc2NvcmVzIGFuZCB1c2Ugc3RhbmRhcmQgZmxhZyBicmFjZXMuCg==
```

### Subtle clue

The line uses the standard Base64 alphabet and ends with `==` padding. This is visible without any additional note and helps a beginner identify the encoding technique after inspecting the artifact.

### Decoded message (internal)

```text
FIELD NOTE 07
Name the carrier, then say what it is not.
No key exists; join with underscores and use standard flag braces.
```

The decoded message does **not** contain the plaintext flag and does not name the encoding. It leads the player to:

1. identify the carrier/encoding: `base64`;
2. use the phrase “not a lock”: `is_not_a_lock`;
3. join with underscores;
4. wrap in the standard `FLAG{...}` format.

---

## 3. Intended solving path

1. Download `decode-me-message.txt`.
2. Observe the character set and trailing `==`.
3. Recognize standard Base64.
4. Decode locally with `base64 -d`, PowerShell `[Convert]::FromBase64String`, Python `base64.b64decode`, or an equivalent local tool.
5. Read the decoded field note.
6. Form the flag from the carrier name and the “not a lock” phrase.
7. Submit the exact flag, preserving lowercase and underscores.

---

## 4. Mode content summary

### Student Mode

- Guided objectives, introduction, and independent first-attempt instructions.
- Four tasks with checkpoints.
- Four progressive hints, each revealing more than the previous one.
- Base64 concept explanation: mapping, padding, and why it is encoding rather than encryption.
- Complete solution walkthrough, review questions, and common mistakes.
- The final solution is internal/gated content and must not be shown before a successful solve during later integration.

Full content: `STUDENT_MODE.md`.

### Competitor Mode

- Independent scenario and objective.
- Artifact download and submission instructions.
- Rules, suggested time limit, and scoring recommendation.
- No hints, learning tasks, checkpoints, walkthrough, solution, or plaintext flag.

Full content: `COMPETITOR_MODE.md`.

---

## 5. Confidentiality and publication constraints

- The only player-facing artifact is `decode-me-message.txt`.
- `CHALLENGE_SPECIFICATION.md`, `SOLUTION.md`, and `TEST_CASES.md` are internal.
- The plaintext flag must be stored only through the platform's hashed flag mechanism during later backend integration.
- Do not place the flag in artifact metadata, hint text, challenge description, scenario, objectives, cheatsheet, solution text, or logs.
- Do not register or publish this challenge in Stage 2.
- Do not modify existing challenges.

---

## 6. Directory inventory

This challenge directory contains:

- `decode-me-message.txt`
- `CHALLENGE_SPECIFICATION.md`
- `STUDENT_MODE.md`
- `COMPETITOR_MODE.md`
- `SOLUTION.md`
- `TEST_CASES.md`

No hidden files, sidecar files, scripts, archives, or dependency manifests are included.

---

## 7. Assumptions requiring confirmation

1. The Cryptography category already exists in the target deployment.
2. 100 points is acceptable for an Easy introductory encoding challenge.
3. `FLAG{...}` will be accepted by the platform after the planned validator update.
4. Student Mode hints remain opt-in and the solution remains post-solve only.
5. Competitor Mode receives no hints before or after solve beyond the independent description.
