# Handoff — Hash-cracking validator hardening + Tier-3 PokeAPI fix (2026-05-23)

**Branch:** `feat/hermes-integration`
**Status:** End-to-end verified via Discord. Hash `54c10b9736b70e75c6e505f340b6e2f1` (basculin) cracks correctly through the full pipeline: model writes script → urllib-fetches `/pokemon-species` → cracker.py finds basculin → summary states verified plaintext. **Nothing committed. Nothing pushed.** Per the user's standing rule.
**Key insight:** The architectural plumbing (write+exec tool_calls, real cracker output, honest summaries) was already working from the prior session. Today's work was content/coverage gaps — wrong PokeAPI endpoint, validator regex false-positives, missing CodeAct marker, hedged-guess hallucinations.

---

## What's COMMITTED (no new commits today)

```
3eae145 feat(messaging): inject persona+recall into fast-path SYSTEM role
04c2508 fix(resolver): rank-not-reject; KV-cache-aware effective size
85df7b2 feat(workspace): adopt Claude Code prompt patterns — tone, action-care, faithful reporting
df806cc feat(skills): creator — scaffold + write + verify helper
07ecc7a feat(scripts): data-driven local-model resolver with feedback memory
```

All on `feat/hermes-integration`, none pushed. Today's work is on top, uncommitted.

---

## What's UNCOMMITTED (live in working tree)

| File / path | Change |
|---|---|
| `openclaw/skills/shared/hash-cracking/wordlists/top1k.txt` (new, 7.2K) | First 1,000 of SecLists 10k. Fresh-Kali baseline. |
| `openclaw/skills/shared/hash-cracking/wordlists/top10k.txt` (new, 73K) | SecLists 10k-most-common.txt. |
| `openclaw/skills/shared/hash-cracking/wordlists/top100k.txt` (new, 836K) | SecLists 100k-NCSC.txt. |
| `python_back_end/workspace/openclaw_client.py` | Tier-3 PokeAPI endpoint `/pokemon` → `/pokemon-species`. Few-shot Tier-2 SecLists-curl removed (now redundant — bundled lists handle via auto-discovery). CodeAct marker `"First call MUST be write"` restored to Rules block (so model_proxy skips forced `tool_choice=exec`). No-hedging rule expanded with explicit forbidden phrasings: `"might be X"`, `"could be X"`, `"intended answer might be Y"`, `"likely X"`, `"probably X"`, `"my guess is Z"`. |
| `python_back_end/workspace/workspace_router.py` | `_validate_hash_claims`: added 3 hedged-language claim_patterns (`answer might be X`, `plaintext might be X`, `might be the password Y`). Added 1 quoted hedge pattern (`likely 'X'` / `probably 'X'`). Added 2 markdown-bold positive patterns (`plaintext is: **X**` and `plaintext is **X**`). Extended `_FALSE_POSITIVE_PLAINTEXT` from 19 → 39 stopwords (added `is`, `be`, `are`, `was`, `were`, `this`, `that`, `it`, `they`, `we`, `you`, `may`, `might`, `could`, `would`, `should`, `result`, `results`, `match`, `matches`). |
| `python_back_end/tests/test_hash_claim_validator.py` | Added 8 new tests: hedged-charizard-caught, plaintext-might-be-hedge, might-be-password, honest-unverified-passes, generic-might-be-no-FP, basculin-markdown-bold-passes, likely-quoted-guess-caught, likely-quoted-real-match-passes. **25/25 pass** (was 17/17). |
| `docker-compose.yaml` | `DISCORD_WORKSPACE_MAX_WAIT_SECONDS: 600 → 900` (user request — 15-min cap). |
| `python_back_end/integrations/discord_workspace_bot.py` (small) | (untouched today; just listed because git status shows it from earlier work). |
| `front_end/newjfrontend/components/workspace/WorkspacePanel.tsx` (small) | (untouched today; carried over). |

**Wordlists explicitly NOT bundled** (fresh-Kali rule): pokemon.txt, marvel.txt, cities.txt, any theme-specific list, rockyou.txt. Test: *"would a human pentester have this file on a fresh Kali box without knowing the target?"* — if no, don't bundle.

The `/home/ommblitz/.claude/plans/noble-noodling-pnueli.md` plan file has the full session plan with rationale + verification steps + rollback paths.

---

## Failure modes seen + fixes (chronological)

### 1. `tool_calls=0`, model emitted JSON-in-markdown
**Symptom:** workspace `fd32c984` returned `tool_calls=0, finish_reason=stop` with 681 completion tokens of `**Step 1** \`\`\`json {"name":"write",...} \`\`\``. Model textually mimicked the tool protocol then HALLUCINATED results.
**Cause:** Few-shot was fully-instantiated with all 5 hashes → model treated it as the finished answer and echoed it as text.
**Fix:** Pre-example imperative + WRONG/RIGHT contrastive + 1-concrete-hash + placeholder pattern (forces substitution work that can only happen via `write` tool_call). Landed in prior session; held this time.

### 2. PokeAPI endpoint missed `basculin`
**Symptom:** Cracker returned `verified=false` for `54c10b9...` even after the model fetched a Pokemon wordlist.
**Cause:** Few-shot fetched `/api/v2/pokemon?limit=2000` which returns form-variants (`basculin-red-striped`, `basculin-blue-striped`) — NOT plain species name.
**Fix:** Endpoint swap to `/api/v2/pokemon-species?limit=2000`. Returns 1,025 canonical base names including `basculin`. Confirmed via curl inside container.

### 3. Hedged-guess hallucination ("might be charizard")
**Symptom:** workspace `63a4bf23` — cracker honestly returned `verified=false`, then model summary said *"the intended answer might be 'charizard'"*.
**Cause:** Validator regexes only matched definitive phrasing (`plaintext is X`, `Answer: X`). The hedged form slipped through.
**Fix:** 3 new `claim_patterns` for hedged language + 1 quoted-hedge pattern. Generic prose (`the wordlist might be in /tmp`) doesn't false-positive because patterns require anchor noun (`answer`/`plaintext`/`password`/`key`) OR quoted candidate.

### 4. CodeAct marker missing → forced exec
**Symptom:** workspace `adf732b4` — `tool_calls=0, finish_reason=stop` with 1,108 completion tokens of pure text. H2 debug showed `codeact=False`.
**Cause:** During an earlier rewrite of the hint's Rules block I removed the line containing `"First call MUST be write"`. `model_proxy` checks for that exact phrase to decide whether to skip forced `tool_choice=exec` for CTF tasks. With the phrase missing, model_proxy forced exec, which fought qwen3:14b's natural write-first flow. (qwen3 also doesn't strictly obey forced tool_choice, unlike granite.)
**Fix:** Restored `"First call MUST be write..."` as the first rule in the Rules block.

### 5. False-positive on a SUCCESSFUL crack ("is")
**Symptom:** workspace `0f8d6c3f` — model correctly cracked basculin AND wrote a clean summary (`"verified plaintext is:\n\n**basculin**"`), but the validator extracted `"is"` as the candidate plaintext, md5("is") ≠ target, summary got suppressed with "Could not determine plaintext" template.
**Cause:** Pattern `r"verified plaintext[\s:]+[\`'\"\*]*([A-Za-z0-9_...]+)..."` matched `"verified plaintext is"` and captured `"is"` (greedy alphanumeric stops at `:`). `"basculin"` was on the next line after `**` markdown bold, no existing pattern caught it.
**Fix (this is the most important one — the system was lying about successful runs):**
1. Added `is`, `be`, `are`, `was`, `were`, `this`, `that`, etc. to `_FALSE_POSITIVE_PLAINTEXT`. The greedy regex still grabs `"is"`, but it gets filtered.
2. Added two positive patterns to capture markdown-bolded plaintexts: `r"plaintext\s+(?:is\s*)?[:=]\s*[\s\n\r]*\*\*([A-Za-z0-9_...]+)\*\*"` and the no-colon variant.
3. The downstream `any_verified` short-circuit (existing logic at line 1013) lets the real crack through when `md5(basculin) == target`.

---

## End-state proof (final Discord run, workspace `0f8d6c3f`)

```
[H1] codeact_hash_hint workspace=0f8d6c3f hashes=1 theme=True example=['54c10b9736b70e75c6e505f340b6e2f1']
[H2] hash_prompt_dispatched ... codeact=True   ← marker restored, model_proxy will SKIP forced exec
model_proxy: CTF-task detected on first call — forcing tool_choice=exec    ← OLD run; not this one
model_proxy: SSE-wrapping non-streamed Ollama response (tool_calls=1, finish_reason=tool_calls)   ← write
model_proxy: SSE-wrapping non-streamed Ollama response (tool_calls=1, finish_reason=tool_calls)   ← exec
[H3] hash_exec_result_seen workspace=0f8d6c3f success=True output={...
       "plaintext": "basculin", "method": "wordlist:pokemon.txt", "verified": true ...}
model_proxy: SSE-wrapping non-streamed Ollama response (tool_calls=0, finish_reason=stop)   ← summary
Background task finished: status=done events=12 tool_calls=2
```

**Provenance of `/tmp/pokemon.txt` (the runtime-built wordlist):**

```
openclaw/skills/shared/hash-cracking/wordlists/  →  top1k/10k/100k ONLY (no pokemon.txt bundled)
/tmp/pokemon.txt (container)  →  18,148 bytes, mtime 2026-05-23 08:02 UTC (matches run)
First lines: bulbasaur, Bulbasaur, ivysaur, Ivysaur, ..., charizard, Charizard, ...
             ↑ matches PokeAPI /pokemon-species response ordering exactly
```

Model genuinely ran `urllib.request.urlopen('https://pokeapi.co/api/v2/pokemon-species?limit=2000')` and wrote that file. Cracker.py's `method: "wordlist:pokemon.txt"` output is just the basename — it's the runtime `/tmp/pokemon.txt`, NOT the (deleted) bundle.

Final Discord reply (the model's own words):
> *The hash 54c10b9736b70e75c6e505f340b6e2f1 was successfully cracked.
> Plaintext: basculin
> Method: Wordlist pokemon.txt (Pokémon species names)
> This matches the Pokémon "Basculin," which aligns with the themed hash request.*

---

## What still has gaps / known issues

### 1. Model auto-routing surprise
The user used `model=auto` and the proxy auto-routed to **qwen3:14b** (on the desktop rig at `192.168.20.58:11434`), not granite4.1:8b. Log: `auto-routing 'auto' → 'qwen3:14b'`. qwen3 behaves DIFFERENTLY from granite — notably it ignores forced `tool_choice` more readily. This is why issue #4 ("forced exec did nothing") manifested only after the CodeAct marker was missing. Watch for cross-model differences. The CodeAct marker fix is robust across models (avoids fighting the proxy).

### 2. `method` field provenance is ambiguous
`cracker.py` outputs `method: "wordlist:<basename>"`. For runtime-fetched lists like `/tmp/pokemon.txt`, this collides with bundled-list basenames in look. User asked about this, then chose "leave as-is" — they can now distinguish `/tmp/*` (runtime) vs `/skills-shared/.../wordlists/*` (bundled). Could revisit if confusion repeats; would be a ~3-line tweak in `cracker.py` to emit the full path.

### 3. Discord progress timeout was raised but no run hit it
User asked for 15-min cap; landed via `DISCORD_WORKSPACE_MAX_WAIT_SECONDS: 600 → 900`. Today's successful runs all finished in well under 60s. Cap is in place if needed.

### 4. The `_validate_hash_claims` regex set is getting long
6 hedged + 2 markdown-bold + 9 definitive = 17 patterns now, plus a 39-entry false-positive set. Maintainable but the cumulative false-positive surface grows. Each new regex should run against the existing 25 fixtures. If we add another, also add at least one negative fixture (input that should NOT trigger).

### 5. dcode.fr cipher-identifier integration was scoped but punted
User raised this earlier today as a separate request. They want HARVIS to handle CTF cipher challenges with unknown cipher types. dcode.fr has no public API and forbids scraping; options scoped were headless browser, ciphey/ares pip install, or custom skill. User did not pick a path today. **Tracked in the plan file's "Out-of-scope follow-up" section.**

---

## Next steps for next session

1. **Decide whether to commit + push.** Five files modified today (3 bundled wordlists count as new + 2 source files + 1 test + 1 compose + 1 plan-doc). Per the standing "no push until end-to-end verified" rule — Discord retest worked, so user CAN push if they want. They didn't ask for it today.
2. **dcode.fr / cipher-identification skill.** Open question from earlier in the session. Likely path: ciphey pip install + wrap as a skill. Alternative: headless browser via `harvis-browser` skill. Needs user input on scope.
3. **Memory writes worth considering** (the user has been deferring on these, but they're load-bearing patterns for future sessions):
   - "Fresh-Kali rule for cracker wordlists" — bundled top1k/10k/100k OK, themed lists NOT OK
   - "CodeAct marker is `'First call MUST be write'`" — any future hint refactor must preserve this string verbatim or `model_proxy` reverts to forced exec
   - "Validator markdown-bold positive patterns" — model summaries that include `**plaintext**` need explicit regex coverage; greedy alphanumeric stops at `:` and grabs stopwords
4. **Cross-model behavior matrix.** qwen3:14b vs granite4.1:8b on the same hint elicit different tool-call behaviors. Worth a short benchmark table: which models follow CodeAct marker, which need forced tool_choice, which hedge under "verified=false".

---

## Diagnostic / replay commands

If anything regresses, these are the fastest grep recipes:

```bash
# Latest workspace activity
docker compose logs backend --since 10m 2>&1 | grep -aE \
  "Workspace launched|tool_calls=|finish_reason|BUDGET|ACTUAL|hash_exec_result_seen|Background task finished|Hash-claim fabrication|forcing tool_choice|CodeAct marker"

# Check whether bundled wordlists are intact + container sees them
docker exec harvis-openclaw ls -la /skills-shared/hash-cracking/wordlists/

# Smoke-test cracker auto-discovery (should find "hello" via top1k.txt)
docker exec harvis-openclaw python3 /skills-shared/hash-cracking/cracker.py \
  5d41402abc4b2a76b9719d911017c592 --online

# Sanity-check PokeAPI species endpoint
docker exec harvis-openclaw curl -sSL 'https://pokeapi.co/api/v2/pokemon-species?limit=2000' \
  | python3 -c "import sys,json; print('basculin' in [p['name'] for p in json.load(sys.stdin)['results']])"
# Expect: True

# Verify the runtime-built pokemon.txt provenance
docker exec harvis-openclaw bash -c "ls -la /tmp/pokemon.txt && head -10 /tmp/pokemon.txt"

# All validator tests
python3 python_back_end/tests/test_hash_claim_validator.py
# Expect: 25 passed, 0 failed out of 25

# Inspect the model's most recent script (basculin run was 5411d1a7-...)
docker exec harvis-openclaw bash -c "ls -lt /home/node/.openclaw/agents/main/sessions/*.jsonl | head -3"
```

---

## What worked / what to keep doing

- **Reading actual log evidence before forming hypotheses.** Every fix today started from a specific log line (BUDGET, ACTUAL, H3 hash_exec_result_seen, Hash-claim fabrication). The session's worst moment was when the validator suppressed a successful crack and the user thought it failed — without reading the H3 line we would have re-hardened the prompt instead of fixing the validator.
- **Plan mode for non-trivial changes.** The 4-step plan file caught the wordlist-restoration scope decision before I would have plowed through, and the user's strict "fresh-Kali" principle sharpened the bundling rule cleanly.
- **`docker exec` for ground-truth verification.** The "is this wordlist runtime-built or bundled?" question collapsed in 3 commands once we shelled into the container. Don't infer from logs when `ls` + `mtime` settles it.

— Claude (Opus 4.7), 2026-05-23
