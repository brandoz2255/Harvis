# Findings — CTF benchmark + agent UX session (2026-05-17)

**Branch:** `feat/hermes-integration`
**Status:** infrastructure wins applied + committed; one experimental change (CTF preamble) reverted; agent-quality work blocked by hardware ceiling and model-alignment friction.
**Hardware constraint throughout:** 8 GB consumer GPU (no upgrade option), 30 GB RAM, Linux.

---

## What landed (kept)

| Change | File(s) | Verified |
|---|---|---|
| `OLLAMA_CONTEXT_LENGTH: 32768 → 16384` | `docker-compose.yaml` | Container env confirmed; KV cache halved (was preallocating ~1.2 GB on 8 GB GPU at q8_0 → ~600 MB now) |
| `OLLAMA_KEEP_ALIVE: 30m → -1` | `docker-compose.yaml` | Models stay resident; prefix cache should hit on identical brief prefixes between turns |
| `qwen3:4b` pulled | local Ollama | **100% GPU residency** at 4.30 GB. Decode ~100 tok/s. Tool-call discipline good. |
| AGENT.md trim (8472 → 2785 chars, 67% cut) | `openclaw/config/AGENT.md` | Identity-bundle source — removed sections that duplicated the directive's RULES / PYTHON / ANSWER CONTRACT / TONE blocks. Workspace memory pattern, skills index, install/project sections retained. |
| Per-gateway `SKILLS_BASE` resolution | `openclaw_client.py` | Dockerized openclaw → `/skills-shared/<skill>` (correct); host BYO → `$OPENCLAW_HOME/.openclaw/skills/<skill>`. Fixes earlier path-mismatch bug where directive named `$OPENCLAW_HOME/.openclaw/workspace/skills/...` (didn't exist in container). |
| Cancel surface in Discord | `discord_workspace_bot.py`, `workspace_router.py` | `@bot cancel` text command + `⛔ Cancel` button on progress message + auto-cancel-on-timeout. All routed through single `cancel_workspace_internal()`. |
| Default workspace timeout `1200 → 600s` | `docker-compose.yaml`, `discord_workspace_bot.py` | 10-min cap. At deadline, both wait functions now call `cancel_workspace_internal` so the underlying agent actually stops (was previously reporting failure while the agent kept burning compute). |
| Meta-question fast-path | `fast_path.py` | Regex short-circuit for "what model are you" / "who are you" / etc. — sends them to fast-path instead of through the LLM-based workspace detector (which has a "err toward workspace" bias). |
| Richer synth narration + Discord label inline-args | `openclaw_client.py`, `discord_workspace_bot.py` | `web_search` / `web_fetch` / `memory_*` now show actual query/URL inline instead of bare "Using <tool>". |
| Stronger narration directive | `openclaw_client.py` | GOOD/BAD example pairs in the RULES section explicitly contrast "Writing the helper script first" (BAD — mechanical) vs "Writing a Python script to brute-force SKY-HQNT-NNNN against the 5 MD5 hashes" (GOOD — names goal). |

---

## What was reverted

**CTF authorization preamble in `hash_hint`** (added then reverted in the same session, no commit).

- **Hypothesis:** Models were emitting "NO" as the final summary because safety-aligned training was refusing the brief on keywords like *password dumps*, *hacker passwords*, *Cyber Command*. Three runs in a row ended with `final_summary: "NO"`, one with **zero tool calls** in 32s — indicating the model refused immediately.
- **Attempted fix:** Prepended a ~25-line "AUTHORIZED CTF / SECURITY TRAINING TASK" block + iteration reminder + themed-wordlist fallback strategy to the existing `hash_hint`.
- **Result:** The new brief made it *worse* — model produced no answer AND no tool calls. The longer hint either (a) overwhelmed the small model's instruction-following window, or (b) triggered a *different* safety reflex (some models refuse harder when the prompt loudly insists "this is authorized"). User flagged it as too constrictive; reverted to the previous shorter hint.
- **Lesson:** Long defensive preambles don't help small models. The simpler `HASH-CRACKING DETECTED…` hint that's been there for a while was the better baseline; we kept it.

---

## What's still open (next session)

### 1. The "NO" / refusal problem on CTF prompts is unresolved
Three models (qwen3:4b, granite4.1:8b, and at least one other based on observed behavior) returned `"NO"` as the final summary on the Pokemon CTF prompt — sometimes with zero tool calls. The CTF preamble experiment didn't help; if anything it made it worse. **Hypotheses to try in order of cheapness:**

- **Reframe the user-supplied prompt itself** at intake — strip the "Cyber Command / analysts / password dumps" framing client-side before it reaches the model. The actual task is *"hash these inputs and find which match the targets"*, which has no alignment signature. The CTF flavor text is decoration the user wants for the *display* but the model doesn't need it.
- **Try a different model lineage.** Qwen / Granite share training data heritage. A model from a different family — `llama3.1:8b` (already installed), `mistral:7b`, `Hermes-3-Llama-3.2-3B` (not yet pulled but research-recommended) — may not have the same refusal pattern.
- **Use the model's own "thinking mode" off-by-default.** Qwen3 has both thinking and non-thinking modes. Non-thinking might output faster without the internal monologue concluding "I shouldn't help with this."
- **The 32s/0-tool-call run is the cleanest signal** — model decided "no" before doing anything. That's pure alignment refusal, not a latency or capability issue. Worth isolating: send the bare hash list with NO surrounding context and see if it still refuses.

### 2. 8-9B Q4 models still don't fully fit on 8 GB GPU
Even after the 16k context cap:
- `batiai/qwen3.5-9b:latest` → 61% GPU / 39% CPU offload (4.59 / 7.58 GB)
- `granite4.1:8b` → 46% GPU / 54% CPU offload (4.4 / 9.6 GB)

This is a **hardware ceiling**, not a config one. Q4 weights of ~5.5 GB + KV cache + activations + Ollama overhead reservation exceeds 8 GB. Only models ≤ ~4B-ish in expanded memory footprint fully fit. `qwen3:4b` (2.5 GB disk, 4.3 GB resident) is the current local sweet spot.

### 3. Prefix-cache hit verification
`OLLAMA_KEEP_ALIVE=-1` is set, and the brief prefix (identity bundle + most of directive) is theoretically stable across turns of the same workspace. **Not yet verified empirically** that the second turn's prefill is dramatically faster than the first. Worth measuring: tail Ollama's `prompt_eval_count` between turn 1 and turn 2 of the same run.

### 4. Directive still ~13k tokens
AGENT.md trim cut ~1400 tokens. The next biggest levers are:
- **Disable openclaw tools the agent doesn't need** (`sessions_*`, `gateway`, `agents_list`, `subagents`, `memory_get` for CTF workloads). Tool schemas are auto-injected by OpenClaw and consume ~2500-3000 tokens. Saving 1500+ tokens means another ~30s prefill cut on partially-offloaded models.
- **Audit RULES / PYTHON / TONE / EXECUTING sections** of the directive for redundancy. Combined ~2500 tokens, probably 500-1000 trimmable.

### 5. Frontend WorkspacePanel phase fix is committed to source but not deployed
`WorkspacePanel.tsx` phase logic now promotes `'connecting' → 'thinking'` on `agent_start` event (instead of staying yellow until the first `tool_call`). And the spinner text differentiates "Connected, model loading…" vs "Agent is thinking…" vs "Agent is executing…". Frontend container has `/app` baked into the image, so this needs `docker compose up -d --build frontend` to be visible.

---

## Useful pointers

- Backend identity bundle source: `/home/user/Harvis/openclaw/config/AGENT.md`
- AGENT.md pre-trim backup: `openclaw/config/AGENT.md.before-trim-1779053545` (gitignored / not yet committed)
- Per-mode openclaw configs: `openclaw/config/{byo,bundled}/openclaw.json`. Currently both point at `harvis-proxy/qwen3:4b` (or whatever the user last set via `/model` in Discord — auto-resolver substitutes).
- Workspace event trace query template:
  ```sql
  SELECT seq, event_type, EXTRACT(EPOCH FROM (ts - LAG(ts) OVER (ORDER BY seq)))::int AS gap_s,
         substring(payload::text, 1, 150) AS preview
  FROM workspace_events WHERE workspace_id LIKE '<id-prefix>%' ORDER BY seq;
  ```
- `ollama ps` (curl `/api/ps`) shows VRAM residency per loaded model — use to verify full-GPU fit.

---

## TL;DR for the next session

1. The latency problem is solved-ish — qwen3:4b at 100% GPU runs the same workload in ~3 min vs ~10 min before. Subsequent turns should be much faster once prefix caching kicks in (un-verified).
2. The *agent quality* problem is now the bottleneck. The "NO" refusal pattern on CTF prompts is the next thing to crack. **Best first experiment:** strip the CTF flavor text from the brief client-side and see if the bare hash list cracks cleanly.
3. Everything in the "What landed" table is committed-or-staged and live in the backend. The frontend phase fix is committed to source but needs a frontend rebuild to render.
