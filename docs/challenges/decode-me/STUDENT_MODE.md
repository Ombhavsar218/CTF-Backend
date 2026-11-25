# Decode Me — Student Mode Content

**Stage:** 2 — Content preparation  
**Audience:** Student Mode players, except the explicitly marked internal/gated solution section.

---

## 1. Learning objectives

By completing Decode Me, the student should be able to:

1. Recognize common Base64 characteristics: a restricted printable alphabet and `=` padding.
2. Decode a Base64 message using a local tool.
3. Explain why Base64 is an encoding, not encryption.
4. Build the flag from a decoded clue while preserving required capitalization and separators.
5. Submit a flag in the exact `FLAG{...}` format.

---

## 2. Challenge introduction

> A field note arrived as a single line of text. It looks harmless, but the words are not directly readable. Nothing here is encrypted and no service is running. Your job is to identify how the note was represented, reverse that representation, and use the clue inside to recover the flag.

The artifact is `decode-me-message.txt`.

---

## 3. Initial attempt instructions

Before opening any hint:

1. Download the artifact.
2. Read it as plain text.
3. Write down what you notice about its characters and the final characters on the line.
4. Make one prediction about the technique before decoding.
5. Try to decode it using a local tool only.

Hints are intentionally opt-in. Opening a hint costs points during later platform integration, so attempt the challenge independently first. The full solution is withheld until after a successful solve.

There is no independent-solving analytics in this initial content scope.

---

## 4. Task 1 — Inspect the artifact

**Action:** Open `decode-me-message.txt` and inspect the single line without decoding it.

Look for:

- the characters used;
- whether the text contains spaces;
- the final characters on the line;
- whether it looks like natural language, a cipher, or a representation of bytes.

**Checkpoint 1:** I can describe the line's alphabet and notice that it ends with padding characters.

---

## 5. Task 2 — Identify the encoding

**Action:** Use your observations to name the representation.

Guiding questions:

- Does the line use only letters, digits, `+`, `/`, and `=`?
- Does the trailing `=` padding look like part of a message or part of an encoding scheme?
- Does reversing this representation require a secret key?

**Checkpoint 2:** I can identify the encoding technique and explain that no key is required.

---

## 6. Task 3 — Decode the message

**Action:** Decode the entire line with a local tool.

Acceptable local approaches include:

- Linux/macOS: `base64 -d decode-me-message.txt`
- PowerShell: `[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((Get-Content decode-me-message.txt).Trim()))`
- Python: `base64.b64decode(...)` followed by UTF-8 decoding

Use the whole line, including padding. Do not use an external website.

**Checkpoint 3:** I have a readable field note that asks me to name the carrier and say what it is not.

---

## 7. Task 4 — Retrieve and submit the flag

**Action:** Use the decoded note to build the flag.

The note asks you to:

1. name the carrier/encoding;
2. say what it is not;
3. join those ideas with underscores;
4. use the platform's standard flag braces.

Then submit the complete flag exactly, using lowercase and underscores as produced by your reasoning.

**Checkpoint 4:** My submitted value has the correct prefix, lowercase words, underscores, and closing brace.

---

## 8. Checkpoints and expected outcomes

| Checkpoint | Student action | Expected outcome |
|---|---|---|
| C1 | Inspect artifact | Student notices a restricted alphabet and trailing `==`. |
| C2 | Identify encoding | Student names Base64 and states that no key is needed. |
| C3 | Decode locally | Student reads a three-line field note, not the flag itself. |
| C4 | Build and submit flag | Student forms `FLAG{<carrier>_is_not_a_<opposite>}` and submits it exactly. |

Checkpoints are learning guidance only. There is no progress tracking or analytics in this scope.

---

## 9. Progressive hints

### Hint 1 — Cost 5

Look at the final characters of the line. A trailing `=` or `==` is common padding in binary-to-text representations. Ask yourself what kind of encoding uses that padding.

### Hint 2 — Cost 10

The characters come from `A-Z`, `a-z`, `0-9`, `+`, and `/`, with `=` padding. That is the Base64 alphabet. It is a representation of bytes, not a cipher with a secret key.

### Hint 3 — Cost 15

Decode the whole line locally. The readable note asks you to name the carrier and then say what it is not. The answer is not printed directly; you must assemble it.

### Hint 4 — Cost 20

The carrier is Base64. The note says it is not a lock. Join those two ideas with underscores, in that order, and wrap the result in the standard flag braces. Preserve lowercase letters.

Each hint intentionally reveals slightly more than the previous one. Hint 4 is the last nudge before the post-solve walkthrough.

---

## 10. Conceptual explanation — Base64

Base64 converts bytes into 24 **A–Z a–z 0–9 + /** characters. It processes input in three-byte groups; each group becomes four output characters. When the final input group is shorter than three bytes, `=` padding is added so the output length is a multiple of four.

This is why Decode Me's artifact ends with `==`. The padding is part of the representation, not part of the hidden message.

Base64 is **encoding**, not encryption:

- the alphabet and mapping are public;
- anyone can reverse it without a key;
- it exists so binary data can travel through text-only channels safely.

Encryption, by contrast, requires a key and aims to provide confidentiality. Decoding Base64 only changes representation; it does not prove that the content was protected.

---

## 11. Complete solution walkthrough *(internal / gated until solve)*

> Do not expose this section in Student Mode before a successful solve.

1. Read the artifact line.
2. Decode it as standard Base64. Decoded output:

   ```text
   FIELD NOTE 07
   Name the carrier, then say what it is not.
   No key exists; join with underscores and use standard flag braces.
   ```

3. “The carrier” is the encoding used by the artifact: `base64`.
4. “What it is not” is a `lock`, so the second phrase is `is_not_a_lock`.
5. Join with underscores: `base64_is_not_a_lock`.
6. Wrap in standard flag braces:

   ```text
   FLAG{base64_is_not_a_lock}
   ```

7. Submit that exact value.

Why this works: Base64 is reversible without a key, and the decoded note is a clue rather than the flag. The final step is reasoning from the clue, not another decoding layer.

---

## 12. Review questions

1. What two features of the artifact suggested Base64?
2. Why is the trailing `==` not part of the flag?
3. Why does decoding Base64 not require a key?
4. What is the difference between encoding and encryption?
5. Why must the submitted flag preserve lowercase letters and underscores?

### Review answer key *(internal / gated with solution)*

1. Restricted Base64 alphabet and `==` padding.
2. It is padding used to complete the final Base64 group.
3. Base64 is a public, deterministic representation, not a secret-key system.
4. Encoding changes representation for compatibility; encryption provides confidentiality using a key.
5. Flag verification is exact and case-sensitive.

---

## 13. Common mistakes and remediation

| Mistake | Why it happens | Remediation |
|---|---|---|
| Treating the line as ROT13 or a substitution cipher | The text looks like scrambled letters. | Check the character set and padding; mixed-case Base64 alphabet plus `=` indicates Base64. |
| Adding or removing `=` before decoding | Assuming padding is a typo. | Decode the exact artifact line; padding belongs to the encoding. |
| Decoding only part of the line | Copying a visual subset. | Select the whole line and decode it as one value. |
| Expecting the decoded text to be the flag | Assuming one decode always reveals the answer. | Read the field note as a clue and assemble the flag as instructed. |
| Using `Base64` with a capital B in the flag | Natural capitalization of the technique name. | Use lowercase `base64` exactly as the encoding's conventional name. |
| Writing `is_not_lock` instead of `is_not_a_lock` | Dropping the article from the clue. | Keep the phrase “not a lock” from the decoded note. |
| Using an external decoder website | Convenience. | Local tools are sufficient and keep the challenge self-contained. |
| Looking for Docker or connection details | Assuming every challenge has an instance. | This is a static artifact challenge; no runtime is needed. |
