---
name: forensics-basics
description: Wrap common file-analysis CLI tools (file, strings, exiftool, binwalk, xxd) for "what's in this file" / CTF-flag-hunting tasks. Trigger when the user attaches or references a file (image, archive, binary, document) and asks to inspect / find a flag / pull metadata / look for embedded data. Looks for CTF flag patterns (flag{}, CTF{}, HTB{}, picoCTF{}, NCAE{}), URLs, emails, base64-like blobs, and common hash patterns inside the output.
metadata:
  {
    "openclaw":
      {
        "emoji": "🔍",
        "os": ["linux", "darwin"],
        "requires": { "bins": ["python3"] },
        "install":
          [
            {
              "id": "apt-forensics",
              "kind": "apt",
              "packages": ["binutils", "libimage-exiftool-perl", "binwalk", "xxd"],
              "bins": ["strings", "exiftool", "binwalk", "xxd"],
              "label": "Install forensics tools (apt) — recommended"
            }
          ]
      }
  }
---

# 🔍 forensics-basics

Layered file analysis: `file` → `strings` (with flag-pattern hunting) →
`exiftool` → `binwalk` → `xxd`. Each tool's output is captured as a
sub-result; recognized patterns (CTF flags, URLs, emails, hash-shaped
hex, base64-likely blobs) are surfaced as structured `findings`.

## Hard rule: no claim without verification

Every "the flag is X" / "the metadata contains Y" / "there's an
embedded file at offset Z" claim MUST come from this tool's output. Do
NOT invent flag values, do NOT speculate about embedded files without
binwalk confirming.

## How to call

```bash
# Single file:
python3 ~/.openclaw/workspace/skills/forensics-basics/analyze.py /path/to/file

# Multiple:
python3 ~/.openclaw/workspace/skills/forensics-basics/analyze.py file1 file2 file3

# Skip a tool (e.g. binwalk is slow on huge files):
python3 ~/.openclaw/workspace/skills/forensics-basics/analyze.py --no-binwalk /path/to/file
```

Returns JSON list, one entry per file:

```json
[{
  "path": "/path/to/file",
  "size_bytes": 12345,
  "tools": {
    "file": "PNG image data, 800 x 600",
    "strings_total_lines": 142,
    "strings_first_30": [...],
    "exiftool": {"File Type": "PNG", "Image Size": "800x600", "Comment": "flag{...}"},
    "binwalk": [{"offset_dec": 1024, "offset_hex": "0x400", "description": "Zip archive"}],
    "hexdump_head": "00000000: 89 50 4e 47 ..."
  },
  "findings": [
    {"type": "CTF flag (flag{})", "value": "flag{...}", "source": "exiftool:Comment"},
    {"type": "URL", "value": "https://...", "source": "strings"}
  ]
}]
```

Read `findings` first — these are the high-signal hits. Then drill
into specific `tools` outputs if the user wants more.

## Flag patterns hunted

- `flag{...}`, `CTF{...}`, `HTB{...}`, `picoCTF{...}`, `NCAE{...}`
- URLs (http/https)
- Emails
- Long base64-like blobs (40+ chars `[A-Za-z0-9+/]={0,2}`)
- md5/sha1/sha256-shaped hex strings (32/40/64 chars)

If a finding looks like base64 or a hash, pipe it into the `decode` or
`hash-cracking` skill respectively.

## Tools degrade gracefully

If a CLI is missing (e.g. no `binwalk` installed), that tool's output
is omitted; the rest still runs. The result includes
`tools_unavailable: ["binwalk", ...]` so the agent knows what
capabilities were missing.

To install all of them on Debian/Ubuntu:

```bash
sudo apt install binutils libimage-exiftool-perl binwalk xxd
```

## Anti-hallucination guidance for lightweight models

> You are running the forensics-basics skill. You CANNOT see file
> contents directly — every claim about a file's contents (flag,
> metadata, embedded data) MUST come from `analyze.py`'s JSON output.
> If `findings` is empty for a file, the file did not contain any of
> the patterns this skill hunts for; say that, do NOT make up a flag.
> For deeper analysis (carving with foremost, polyglot extraction,
> stego LSB) note that this skill does not cover those — defer to a
> stego or steg-aware skill.
