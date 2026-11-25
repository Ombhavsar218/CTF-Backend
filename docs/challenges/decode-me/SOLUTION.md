# Decode Me — Internal Solution

**Stage:** 2 — Content preparation  
**Classification:** Confidential authoring content.

> Do not expose this document or its contents to players. During later backend integration, the plaintext flag must exist only as a hashed `ChallengeFlag` value. Do not copy the flag into challenge descriptions, hints, solution UI text before solve, artifact metadata, or logs.

---

## 1. Exact decoding process

### Artifact

`decode-me-message.txt` contains one Base64 line:

```text
RklFTEQgTk9URSAwNwpOYW1lIHRoZSBjYXJyaWVyLCB0aGVuIHNheSB3aGF0IGl0IGlzIG5vdC4KTm8ga2V5IGV4aXN0czsgam9pbiB3aXRoIHVuZGVyc2NvcmVzIGFuZCB1c2Ugc3RhbmRhcmQgZmxhZyBicmFjZXMuCg==
```

### Decode commands

Linux/macOS:

```bash
base64 -d decode-me-message.txt
```

PowerShell:

```powershell
$line = (Get-Content .\decode-me-message.txt).Trim()
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($line))
```

Python:

```python
import base64
from pathlib import Path

raw = Path("decode-me-message.txt").read_text(encoding="ascii").strip()
print(base64.b64decode(raw).decode("utf-8"))
```

No external website or network service is needed.

---

## 2. Expected decoded output

```text
FIELD NOTE 07
Name the carrier, then say what it is not.
No key exists; join with underscores and use standard flag braces.
```

The decoded note is a clue, not the flag. It does not contain the literal flag or the word `base64`.

---

## 3. Expected flag

```text
FLAG{base64_is_not_a_lock}
```

### Derivation

1. “The carrier” is the encoding used to represent the note: `base64`.
2. “What it is not” is a `lock`, giving the phrase `is_not_a_lock`.
3. Join with underscores: `base64_is_not_a_lock`.
4. Apply standard flag braces: `FLAG{base64_is_not_a_lock}`.

---

## 4. Verification steps

1. Confirm the artifact has one line, no BOM, LF ending, and only ASCII Base64 characters.
2. Decode the whole line using at least one local method.
3. Confirm the decoded output exactly matches section 2.
4. Confirm the decoded output does not contain `FLAG{` and does not contain the word `base64`.
5. Derive the flag as in section 3.
6. Confirm the derived flag matches the expected flag exactly, including lowercase letters and underscores.
7. During later integration, confirm the API never returns this plaintext value.

---

## 5. Common alternative solving paths

| Path | Description | Result |
|---|---|---|
| CLI `base64 -d` | Decode the file directly on Linux/macOS. | Same decoded note. |
| PowerShell `[Convert]::FromBase64String` | Decode locally on Windows without dependencies. | Same decoded note. |
| Python `base64.b64decode` | Decode programmatically. | Same decoded note. |
| Node.js `Buffer.from(line, 'base64')` | Decode with Node's built-in buffer API. | Same decoded note. |
| Manual Base64 table decoding | Decode groups of four characters by hand. | Same decoded note; slower but valid. |
| Recognize `==` padding first | Identify the encoding before decoding, then choose a decoder. | Same solving path with faster identification. |

No path requires an online decoder, Docker, a hint purchase, or any network access.

---

## 6. Submission test cases

These are authoring expectations for later submission validation, not changes to the platform.

| ID | Submitted value | Expected outcome | Reason |
|---|---|---|---|
| S1 | `FLAG{base64_is_not_a_lock}` | Correct | Exact expected flag. |
| S2 | `  FLAG{base64_is_not_a_lock}  ` | Correct if surrounding whitespace is trimmed by the API | Existing flag normalization strips outer whitespace. |
| S3 | `flag{base64_is_not_a_lock}` | Incorrect | Flag verification is case-sensitive. |
| S4 | `FLAG{Base64_is_not_a_lock}` | Incorrect | Capitalization changed. |
| S5 | `FLAG{base64_is_not_lock}` | Incorrect | Missing article `a`. |
| S6 | `FLAG{base64_is_not_a_Lock}` | Incorrect | Changed case in final word. |
| S7 | `CTF{base64_is_not_a_lock}` | Incorrect / invalid prefix | This challenge uses `FLAG{...}`. |
| S8 | `FLAG{base64_is_not_a_lock` | Incorrect / invalid format | Missing closing brace. |
| S9 | `base64_is_not_a_lock` | Incorrect | Missing flag wrapper. |
| S10 | empty string | Rejected | Submission serializer requires nonblank flag. |
| S11 | very long string over 256 characters | Rejected | Existing `MAX_FLAG_LENGTH` limit. |

Repeat submissions of S1 by the same user should report already-solved and award no additional points.
