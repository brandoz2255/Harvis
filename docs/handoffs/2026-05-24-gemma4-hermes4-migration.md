# Handoff — Default-route migration to hermes4:14b-q5, partial win (2026-05-24)

**Branch:** `feat/hermes-integration`
**Status:** Hash workflow regression PASSED 5/5 on hermes4 (better than prior 4/5 best). MCQ workflow is INCONSISTENT — sometimes works, sometimes regresses to JSON-in-markdown text emission. **No commits, no pushes.** All architectural improvements from the session are uncommitted on the working tree.
**Headline:** This session ran a planned migration of the `auto`-routed model from qwen3:14b → gemma4:e4b → hermes4:14b-q5, fixed multiple infrastructure bugs along the way, and surfaced a real architectural gap (B7) that won't be solved without an OpenClaw upgrade.

---

## What's COMMITTED (no new commits today)

```
3eae145 feat(messaging): inject persona+recall into fast-path SYSTEM role
04c2508 fix(resolver): rank-not-reject; KV-cache-aware effective size
85df7b2 feat(workspace): adopt Claude Code prompt patterns — tone, action-care, faithful reporting
df806cc feat(skills): creator — scaffold + write + verify helper
07ecc7a feat(scripts): data-driven local-model resolver with feedback memory
```

Today's work is on top, all uncommitted. Per the standing `no push until end-to-end verified` rule, hold on commits until you accept the partial-win verdict.

---

## What's UNCOMMITTED (live in working tree)

| File | Change |
|------|--------|
| `python_back_end/workspace/model_proxy.py` | (a) `_DESKTOP_PREFERRED_PREFIXES` const + `_prefers_desktop()` helper; (b) desktop-preferred branch in BOTH routing decision points (DB-cfg path ~224 and fallback path ~311); (c) per-model `hermes4` block with `options.stop = ["</s>", "<|im_end|>", "<|eot_id|>", "<|end_of_turn|>"]` + `num_predict: 1024` + `num_ctx: 16384` |
| `python_back_end/integrations/discord_workspace_bot.py` | (a) `_reset_epochs` (unix-timestamp values, NOT counter); (b) `_reset_pending` set for drop-on-first-message; (c) `_RESET_CTX_RE` regex + handler that bumps both and clears Discord chat-history |
| `python_back_end/workspace/openclaw_client.py` | (a) WEB ACCESS hint rewritten with self-check directives, repositioned from ~42% → ~95% of prompt; (b) `_REJECTION_RE` extended with declarative-correction patterns; (c) retry_hint prepended with explicit task-class split (scenario→search; tool-task→re-run-tool) |
| `python_back_end/workspace/workspace_router.py` | `_validate_hash_claims`: 3 hedged-language claim patterns + 2 markdown-bold positive patterns + 20 stopwords added to `_FALSE_POSITIVE_PLAINTEXT` |
| `openclaw/config/byo/openclaw.json` | `tools.web.search.enabled: false` — broken built-in Brave-only MCP tool disabled |
| `openclaw/skills/shared/hash-cracking/wordlists/` | `top1k.txt`, `top10k.txt`, `top100k.txt` (fresh-Kali baseline; no themed wordlists bundled) |
| `python_back_end/tests/test_hash_claim_validator.py` | 8 new tests covering hedged-language, markdown-bold, false-positive guard. **25/25 pass.** |
| `~/.claude/projects/.../memory/*.md` | 6 new memory entries + MEMORY.md index updates |

---

## Test results summary

| Test | Model | Outcome |
|------|-------|---------|
| MCQ #1 (prompt-injection scenario, OWASP-LLM-Top-10) | qwen3:14b | ❌ Confident wrong (API Gateway). Refused to search even with explicit hint. |
| MCQ #1 | gemma4:e4b | ❌ Safety-refusal (first try) OR RT2 silent-stop (later tries). Model called `web_search`, got search results back, then emitted `completion_tokens=1` — couldn't summarize. Architectural bug. |
| MCQ #1 (3rd phrasing, simplified) | hermes4:14b-q5 | ✅ **Got LLM Agent right** with reasoning citing search results. Stop-token fix held — `completion_tokens=321` (was 2,480 unfixed). |
| Hash regression (5 pokemon MD5s) | hermes4:14b-q5 | ✅ **5/5 verified** via `pokemon-species.txt` endpoint. `tool_calls=2` (write+exec), `Background task finished: status=done`. Better than the prior 4/5+basculin best. |
| MCQ #2 (vulnerability classification) | hermes4:14b-q5 | ❌ JSON-in-markdown text emission. `tool_calls=0, finish_reason=stop`. Same failure mode qwen had on earlier tests. |

**Hermes4:14b-q5 is solid on the CodeAct flow (hash/decode/crypto/forensics) but inconsistent on free-form MCQ.** The hash workflow worked because the `hash_hint` block has CodeAct + WRONG/RIGHT contrastive that forces shape. Free-form MCQ only has the generic `WEB ACCESS:` prose, which hermes follows on some phrasings and ignores on others.

---

## The bigger picture (the architectural finding)

Multiple models in sequence (qwen3:14b → gemma4:e4b → hermes4:14b-q5) all failed MCQ in different ways. **The pattern across all three:** the model treats schema-registered MCP tools as authoritative; prose-described tool paths (the `exec(curl /api/tools/search)` pattern in WEB ACCESS) are followed inconsistently or ignored. When the broken built-in `web_search` MCP tool was *enabled*, qwen reached for it (got Brave-key error). When it was *disabled*, qwen stopped searching at all.

**The real fix is Path B7:** upgrade OpenClaw to v2026.5.17+ to get `defineToolPlugin` SDK, then register a custom `web_search` MCP tool that wraps our working DDG-backed `/api/tools/search` proxy. Then any model — qwen, gemma, hermes — sees a working tool in the schema and uses it.

Tracked in [[project_openclaw_b7_blocked]] memory.

---

## Bugs/issues solved this session

1. **MCQ "model won't search" — wrong root cause first.** Originally diagnosed as hint-position / hint-strength. Real cause: tool absent from schema. Multiple fix attempts (self-check directives, repositioned WEB ACCESS, contrastive WRONG/RIGHT) made marginal differences but the real fix required either a working schema-registered tool or model swap.
2. **Session contamination — two sources, not one.** OpenClaw session storage (persistent, keyed by session_id) + Discord chat-history fetch (separate code path). First reset implementation only addressed OpenClaw. Final implementation handles both: unix-timestamp epoch in session_id + `_reset_pending` set drops Discord history on first post-reset message.
3. **gemma4:e4b post-tool-result silent stop.** Chat-template bug in Ollama 0.24.0. Documented in memory; gemma4 family avoid as primary tool-use until upgrade.
4. **hermes4:14b-q5 EOS not honored.** `</s>` and `<|im_end|>` ignored by template; explicit `options.stop` + `num_predict` cap in model_proxy per-model block fixes it. Pre-fix completion was 2,480 tokens on summary turn (system-prompt echoing); post-fix is 321 tokens clean.
5. **Routing prefers laptop even when laptop has 8GB GPU and rig has the capable one.** New `_prefers_desktop()` helper + `HARVIS_DESKTOP_PREFERRED_MODELS` env (default `gemma4`) forces GPU-heavy families to rig.

---

## Failed attempts (saved here so we don't repeat them)

- **`tools.webSearch.enabled = false`** — wrong path. Correct path is `tools.web.search.enabled = false`. The plugin-SDK type definitions are nested differently than the main config schema.
- **`BRAVE_SEARCH_ENDPOINT` env-var override** — proposed as Path B2 (point built-in `web_search` at our proxy). Probe revealed it's a HARDCODED CONSTANT in the bundled JS, not an env var. Can't redirect upstream via config.
- **DuckDuckGo as native OpenClaw provider** — proposed based on docs from a newer version. Probe revealed OpenClaw v2026.2.23 enum is `brave|perplexity|grok|gemini|kimi` only. No DDG.
- **`gemma4:26b` as fallback if e4b fails MCQ** — registry probe confirmed it exists (18GB download), but VRAM math (~20GB with 24K ctx) doesn't fit RTX 5080's 16GB. CPU offload would be unacceptably slow. Not a viable fallback on this rig.
- **Counter-based reset epoch** — collided with prior OpenClaw session files after backend rebuilds reset the in-memory counter to 0. Replaced with `int(time.time())`.

---

## End-state recommendation (when you pick this up)

**Option A — Accept the partial win.** Hash works 5/5, MCQ works sometimes. Commit the changes, write a "known limitation" note for MCQ in the README, plan B7 as a follow-up.

**Option B — Revert hermes4, keep the infrastructure.** The model_proxy/discord_bot/openclaw_client/validator improvements are all model-agnostic wins. Reverting only the saved-pick (`@bot set-model qwen3:14b`) and the per-model hermes4 block leaves the rest intact. Trade-off: lose the 5/5 hash crack improvement and the OWASP MCQ win, gain nothing on the new MCQ failure mode (it would have been confidently-wrong on qwen instead of JSON-in-markdown).

**Option C — Do Path B7 properly.** Upgrade OpenClaw, register a custom `web_search` MCP tool wrapping `/api/tools/search`. Solves the MCQ class of failures across all models. Bigger scope; needs a careful evaluation of whether the OpenClaw upgrade breaks anything else.

My honest recommendation: **Option A**. Ship the partial win, document the limitation, queue B7 for when you have a weekend.

---

## Next steps for next session

1. **Decide commit/push.** End-to-end verified for hash crack (the critical gate). MCQ is partial. Path B7 is the real fix. User-call on whether this rises to the "no push until verified" bar.
2. **B7 — OpenClaw upgrade.** Pull v2026.5.17+, register custom `web_search` MCP tool, point at `/api/tools/search`. Solves MCQ class permanently.
3. **MCQ #2 retry on hermes4** with stronger directive. If WRONG/RIGHT contrastive in WEB ACCESS hint (like hash_hint has) helps, that's a 15-min fix and might patch the JSON-in-markdown emission. Cheap test before committing to B7.
4. **Smoke-test decode + crypto + forensics on hermes4.** Hash regression passed but we didn't retest the other skill workflows.

---

## Diagnostic command recipes

```bash
# Latest workspace events
docker compose logs backend --since 10m 2>&1 | grep -aE \
  "Workspace launched|BUDGET|ACTUAL|tool_calls=|finish_reason|Background task finished|host=desktop|host=laptop|reset-context|dropped.*prior history"

# Check active model + routing
docker compose logs backend --since 5m 2>&1 | grep -aE "auto-routing|desktop-preferred"

# Probe what's loaded on the rig
curl -s http://192.168.20.58:11434/api/ps | python3 -m json.tool

# Smoke-test gemma4 (RT2 silent stop check)
curl -s http://192.168.20.58:11434/api/chat -d '{
  "model": "gemma4:e4b", "messages": [...], "think": false, "stream": false,
  "tools": [...]
}'

# Verify reset-context works
@Harvis-Bot reset-context
# log should show: epoch_ts=<unix-ts>, dropped N prior history turns

# Run validator tests
python3 python_back_end/tests/test_hash_claim_validator.py
# expected: 25 passed, 0 failed out of 25
```

---

## What worked / what to keep doing

- **Read the actual log evidence first.** Every misdiagnosis this session got corrected by re-reading the BUDGET/ACTUAL/tool_calls log lines. The "model won't search" turned out to be "schema lacks the tool" only after reading the JSON tool_result that said `missing_brave_api_key`.
- **Plan mode for non-trivial changes.** The gemma → hermes pivot got drafted, reviewed (with three flags from advisor), updated, and approved before any code change. Caught the 26B-VRAM-fit issue before wasting time on a download.
- **Memory writes BEFORE wrap-up.** Per the standing rule. Six entries are now in `memory/` — future-you opening this codebase in two weeks will see the gemma4 RT2 bug, the hermes4 EOS quirk, the desktop-preferred routing, and the B7 block without reconstructing them.

— Claude (Opus 4.7), 2026-05-24
