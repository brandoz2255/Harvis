---
name: classical-crypto
description: Classical-cipher solver. Caesar (brute-force all 26 shifts), Vigenere (auto-detect key length via index of coincidence, then chi-squared per stripe), Atbash, and decryption with a known key. Trigger when the user mentions Caesar, Vigenere, Atbash, "shift cipher", "rotation cipher", or pastes ciphertext with an obvious classical pattern (long alphabet-only run with no spaces, or familiar phrasing patterns). For unkeyed encoding blobs (base64/hex/etc.) prefer the decode skill.
metadata:
  {
    "openclaw":
      {
        "emoji": "🗝️",
        "os": ["linux", "darwin"],
        "requires": { "bins": ["python3"] }
      }
  }
---

# 🗝️ classical-crypto

Classical-cipher solver. Caesar / Vigenere / Atbash / known-key
Vigenere. English-likeness scored via chi-squared distance from
standard letter frequencies — lower score is more English-like.

## Hard rule: no claim without verification

The LLM cannot solve classical ciphers reliably by inspection; even
ROT13 trips small models on novel ciphertext. Every plaintext you
report MUST come from a tool call that returns `verified: true`. If
you guess a plaintext without running `cipher.py`, you're wrong.

## How to call

```bash
# Auto-solve everything (Caesar brute, Atbash, Vigenere auto-key):
python3 ~/.openclaw/workspace/skills/classical-crypto/cipher.py "<ciphertext>"

# Or pipe in:
cat ciphertext.txt | python3 ~/.openclaw/workspace/skills/classical-crypto/cipher.py

# Explicit cipher:
python3 ~/.openclaw/workspace/skills/classical-crypto/cipher.py --cipher caesar "<text>"
python3 ~/.openclaw/workspace/skills/classical-crypto/cipher.py --cipher vigenere --key SECRET "<text>"
python3 ~/.openclaw/workspace/skills/classical-crypto/cipher.py --cipher atbash "<text>"
```

Returns JSON:

```json
{
  "input_preview": "...",
  "candidates": [
    {"cipher": "caesar", "shift": 3, "plaintext": "...", "score": 12.83, "verified": true},
    {"cipher": "vigenere", "key": "SECRET", "key_length": 6, "index_of_coincidence": 0.067,
     "plaintext": "...", "score": 11.2, "verified": true},
    {"cipher": "atbash", "plaintext": "...", "score": 14.0, "verified": true}
  ]
}
```

Top candidate is the most-English-likely solution. Pick the one that
makes sense for the user's challenge context.

## Tier order (auto-solve)

1. **Caesar** — brute force all 26 shifts, return top 3.
2. **Atbash** — deterministic A↔Z swap.
3. **Vigenere** — auto-detect key length 2..12 via average index of
   coincidence per stripe, then minimize chi-squared per stripe to
   recover the key. Needs ≥30 letters of ciphertext to be reliable.

## When Vigenere needs more help

The auto-solver works on ≥30 letters. For shorter ciphertext or weird
keys (longer than 12), supply `--key <KEY>` if known, or fall back to
manual Kasiski analysis (not in this skill yet).

## When to use vs not

| Case | This skill | decode |
|---|---|---|
| `Khoor` (Caesar shift 3, no key supplied) | ✅ | also works (rot brute) |
| `Lxfopv ef rnhr fwfwfffhfvxe ml fpzlh` (Vigenere) | ✅ | — |
| `SGVsbG8h` (base64) | — | ✅ |
| Long encoded blob with unclear cipher | start with `decode`, then this | — |

## Anti-hallucination guidance for lightweight models

> You are running the classical-crypto skill. You CANNOT solve Caesar /
> Vigenere by sight even on familiar phrases — every plaintext you
> report MUST come from running `cipher.py`. Do NOT guess shifts or
> keys. If the auto-solver doesn't return a high-score (low chi-squared)
> candidate, the cipher might be longer-key Vigenere or substitution —
> say so and report what was tried, do not fabricate.
