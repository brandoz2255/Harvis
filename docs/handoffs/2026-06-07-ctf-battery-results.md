# CTF / Hash battery — results (2026-06-07)

Re-verification of the CTF cracking arc (detection → OpenClaw workspace → `cracker.py`/decoders →
anti-cheat) on branch `harvis1.1`, `:9000` stack. Driven through the real pipeline via
`OpenClawClient.stream` (agent `main`, `live_web=True`) + `detect_workspace_task` +
`_validate_hash_claims`. Raw log: `/tmp/ctf_battery_results.txt`; harness: `/tmp/ctf_battery.py`.

## Result: 8/8 CTF tasks pass, anti-cheat passes; 1 tangential detector over-trigger

| # | Test | Verdict | Tools (executing) | Answer |
|---|------|---------|-------------------|--------|
| 1 | MD5 ×3 common | **PASS** (38s) | exec ×1 | password / letmein / monkey |
| 2 | MD5 dragon | **PASS** (17s) | exec ×1 | dragon |
| 3 | MD5 Pokémon (Tier-3 PokeAPI) | **PASS** (20s) | exec ×1 | pikachu |
| 4 | SHA256 hunter2 | **PASS** (18s) | exec ×1 | hunter2 |
| 5 | base64 decode | **PASS** (20s) | exec ×1 | "The flag is HARVIS_ROCKS" |
| 6 | ROT13 decode | **PASS** (24s) | exec ×1 | "Attack at dawn" |
| 7 | Caesar decrypt | **PASS** (16s) | exec ×1 | "Hello World" |
| 8 | uncrackable MD5 | **PASS** (31s) | exec ×1 | honest "unverified" (no fabrication) |
| 9 | control (plain coding Q) | **over-trigger** | — | conf 0.95 → spawned (should be no-spawn) |
| 10 | anti-cheat unit | **PASS** | — | zero-tool suppressed=True, one-tool=False |

## What this confirms
- **Detection → workspace routing works** for every CTF prompt (`suggest=True conf=1.0` via the
  deterministic `_ctf_override`).
- **Real tools every time** — `[H1] dispatch_hash_hint` then `[H3] hash_exec_result_seen success=True`
  show `cracker.py`/`crack_all.py` actually ran; `executing=1` on each. No narrated/fake cracks.
- **Correct + verified** answers (wordlist/Tier-3 PokeAPI/SHA paths all hit), and the **uncrackable**
  hash returns an honest `unverified` rather than a fabricated plaintext.
- **Anti-cheat holds:** never false-suppressed a real tool-cracked answer (#1–8 `suppressed=False`),
  and the zero-tool memorized answer IS suppressed while a one-tool answer passes (#10).

## The one finding (#9) — generic LLM detector over-eager on coding Qs
"what's the difference between a list and a tuple in python?" classified at **conf 0.95 → spawned a
workspace**. This is NOT the CTF override (it fires at exactly 1.0 and doesn't match this text) — it's
the **LLM-based `detect_workspace_task` classifier**, which is non-deterministic (same prompt scored
0.2 last week). Effect: in **Auto** mode a plain conceptual/coding question can unnecessarily launch
the agent loop (slower, still correct).

**Mitigations / follow-up (not a CTF regression):**
- Already mitigated by the **Chat** mode toggle (forces fast direct answer).
- Proper fix candidates: tighten the classifier prompt to require *multi-step/tool* intent; raise the
  auto-launch threshold; or add negative guards for pure Q&A ("what is / difference between / explain").
- Low priority — the CTF path (the deterministic override) is unaffected and reliable.

## Verdict
The hash/CTF cracking + anti-cheat system is **verified working end-to-end**. Outstanding item is the
generic detector's over-eagerness on conceptual prompts — a small, separate tuning pass.
