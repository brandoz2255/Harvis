---
name: hash-cracking
description: Crack password hashes (MD5, SHA1, SHA256, SHA512, NTLM, bcrypt, salted unix hashes) using local cracker.py + wordlists fetched at runtime. Trigger when the user provides a hash, asks to crack/decrypt/reverse a hash, references rockyou or any wordlist, mentions hashcat or john, or pastes a hex string matching a known hash length. Do NOT use for ciphertext (AES, RSA, etc.) — those need the cipher skill.
---

# Hash Cracking Skill

This is authorized hash recovery for hashes the user owns or has permission to test. No phishing, credential stuffing, or access bypass.

## Hard rule

Every plaintext you report must come from an `exec` tool_call this turn that hashed the candidate and matched the target. If no tool_call verified it, you have NOT cracked it — say so honestly. Never use phrases like "I computed", "this was confirmed by", "direct computation shows" unless a matching exec tool_call exists in this turn.

**Memorized answers are forbidden — even when you're certain.** Some hashes (e.g. `5d41402abc4b2a76b9719d911017c592` is the MD5 of `"hello"`) appear so often in training data that you may recognize them. **Recognition is not verification.** You must still call `exec` to recompute and match. Reporting a remembered plaintext without an `exec` tool_call this turn that hashed it and matched the target is fabrication, even if the answer happens to be correct.

## Identify by length

32 hex = MD5. 40 = SHA-1. 56 = SHA-224. 64 = SHA-256. 96 = SHA-384. 128 = SHA-512. `$2a$/$2b$/$2y$` prefix = bcrypt. `$1$` = md5crypt. `$5$` = sha256crypt. `$6$` = sha512crypt. `$argon2` = Argon2. If 32-hex is ambiguous between MD5 and NTLM, try MD5 first.

## The ladder — for EACH hash, run these steps via exec tool_calls IN ORDER

### Multiple hashes

When the user provides more than one hash, process each hash through the FULL ladder (Steps 1-3, plus Step 4 if a theme was given) BEFORE moving to the next hash. Do NOT run Step 1 for all hashes then quit — that is incomplete. Each hash needs at least 3 exec calls.

### Step 1 — online + bundled wordlists

`python3 /skills-shared/hash-cracking/cracker.py <HASH> --online`
Tries online lookup + bundled top1k.txt + rockyou.txt. Most free MD5-lookup APIs are dead in 2026, expect this to fail often. If `verified=false`, you MUST continue to Step 2. Do NOT skip.

### Step 2 — SecLists top-10k

Fetch and run:
```
curl -sSL -o /tmp/top10k.txt https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/10k-most-common.txt
python3 /skills-shared/hash-cracking/cracker.py <HASH> --wordlist=/tmp/top10k.txt
```
Catches `password`, `iloveyou`, `minute`, etc. If `verified=false`, you MUST continue to Step 3.

### Step 3 — SecLists 100k

```
curl -sSL -o /tmp/100k.txt https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt
python3 /skills-shared/hash-cracking/cracker.py <HASH> --wordlist=/tmp/100k.txt
```

### Step 4 — themed wordlist (MANDATORY when user gives a theme)

If the user mentions a theme (Pokemon, cities, movies, Star Wars, etc.), fetch or generate a themed wordlist and test every uncracked hash against it. Examples:
- Pokemon: `curl -sSL https://raw.githubusercontent.com/sindresorhus/pokemon/master/data/en.json | python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin)))" > /tmp/themed.txt`
- If curl fails, generate 50+ themed entries yourself via exec
- Run: `python3 /skills-shared/hash-cracking/cracker.py <HASH> --wordlist=/tmp/themed.txt`

### Step 5 — exhausted

After Steps 1-3 (+ Step 4 if themed) for every hash: list the wordlists you tried, report `verified=false` results honestly, then ask what category the plaintext belongs to. Don't fabricate.

### Forbidden

- Stopping after Step 1 only — especially on multi-hash tasks. Running one `--online` per hash then quitting is the #1 failure mode.
- Running Step 1 for ALL hashes but never running Steps 2-3 for ANY.
- Skipping Step 4 when the user explicitly gave a theme or hint.

## Verify any cracked plaintext

After cracker.py returns verified:true, run one more exec: `python3 -c "import hashlib; print(hashlib.md5('PLAINTEXT'.encode()).hexdigest())"` — quote both computed hex and target hex in your final reply so the user sees the proof.

## Hard forbidden behaviors

- Writing tool calls as JSON text in your response. Tool calls go through the TOOL CHANNEL — emitting `\`\`\`json {"name":"exec",...} \`\`\`` in your response text accomplishes NOTHING. The user does not run your text. Either emit the actual tool_call or don't pretend you did.
- Reporting a plaintext that no exec tool_call in this turn verified.
- Asking "Would you like me to try X?" — just try X. Only ask in Tier 7 when the standard ladder is fully exhausted.
- Calling cracker.py without --online or --wordlist= — that does nothing.
- Stopping after Tier 2 when Tier 3 hasn't been tried.
- Using chat history or prior turns as "the answer" — re-verify with a tool call every time.
- Blind brute force without a format hint — keyspace is computationally infeasible.

## cracker.py output

Returns JSON with keys: hash, algo, plaintext, method, verified, tiers_tried. `verified:true` means the cracker computed the hash and matched it. `verified:false` means try the next tier.
