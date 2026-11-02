---
name: decode
description: Multi-format string decoder. Try base64, base64url, base32, hex, binary, octal-decimal, URL-encoded, ROT-N (1..25), ROT47, atbash, and morse. Trigger when the user pastes an opaque blob and asks "what does this say" / "decode this" / "decrypt this" (no key supplied), when a string looks like base64/hex/binary, or when a CTF challenge involves encoded data. For keyed/classical ciphers (Caesar with hint, Vigenere) prefer the classical-crypto skill.
metadata:
  {
    "openclaw":
      {
        "emoji": "🔤",
        "os": ["linux", "darwin"],
        "requires": { "bins": ["python3"] }
      }
  }
---

# 🔤 decode

Multi-format decoder for CTF / quick-decode tasks. Tries every common
encoding scheme on the input and returns ranked candidates (lower
`score` = more English-like).

## Hard rule: no claim without verification

LLMs cannot reliably reverse-decode by sight; they hallucinate
plaintexts. Every plaintext you report MUST come from a tool call that
returns `verified: true`. If you produce a decoded value without
calling `decoder.py`, that output is wrong by default.

## How to call

```bash
python3 ~/.openclaw/workspace/skills/decode/decoder.py "<encoded blob>"

# Or pipe in:
echo -n "<blob>" | python3 ~/.openclaw/workspace/skills/decode/decoder.py

# Show all candidates regardless of score:
python3 ~/.openclaw/workspace/skills/decode/decoder.py --all "<blob>"
```

Returns JSON:

```json
{
  "input_preview": "...",
  "input_length": 16,
  "candidates": [
    {"method": "base64", "plaintext": "Hello World!", "score": 12.83, "verified": true},
    {"method": "rot13",  "plaintext": "...",          "score": 23.4,  "verified": true}
  ]
}
```

`candidates` are sorted by `score` ascending — top entry is the most
English-likely decode. Read the top 1-3 and pick the one that
linguistically makes sense for the user's challenge context.

## Decoders covered

| Method | When it triggers |
|---|---|
| `base64` / `base64-padded` / `base64url` | input is mostly `[A-Za-z0-9+/=]` (or `-_=`) |
| `base32` | input is mostly `[A-Z2-7=]` |
| `hex` | input is mostly `[0-9a-fA-F]` (with optional spaces/colons), even-length |
| `binary` | input is `[01\s]+`, length divisible by 8 |
| `ascii-decimal` | input is space-separated decimal numbers (e.g. `72 101 108 108 111`) |
| `url` | input contains `%XX` sequences |
| `rot1..rot25` | input has letters; brute-force all shifts, return top 3 |
| `rot47` | input is printable ASCII; ROT47 (mix of letters/symbols) |
| `atbash` | input has letters (A↔Z swap) |
| `morse` | input is only `. - / and whitespace` |

## When to use vs not

| Case | This skill | classical-crypto |
|---|---|---|
| `SGVsbG8h` (b64) | ✅ | — |
| `48656c6c6f` (hex) | ✅ | — |
| `Khoor Zruog` (Caesar without hint) | ✅ (rot brute) | also works |
| Caesar with stated shift, Vigenere, atbash with explicit instruction | — | ✅ |
| Long ciphertext (Vigenere-likely) | — | ✅ |
| `forensics-basics` already has the file open and shows base64 in strings | ✅ pipe to decode | — |

## Anti-hallucination guidance for lightweight models

> You are running the decode skill. You CANNOT decode encoded strings by
> sight or memory — every plaintext you report MUST come from running
> `decoder.py`. Do NOT invent plaintexts. If `decoder.py` returns no
> candidates, say "could not decode" and list what was tried (the
> stdout of `--all` shows every attempted method).
