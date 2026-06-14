# Handoff — Model Comparison + Analytics (2026-06-13)

Branch: `harvis1.1` · **all work below is uncommitted in the MAIN repo** (`/home/user/Harvis`). No push per standing rule. Deploy is live on `:9000` and verified.

## Goal
The navbar "+" multi-model selector conflates two intents → split them:
- **Compare** = same prompt → N independent models, side-by-side (this is what shipped).
- **Collaborate** = N models as parallel sub-agents on ONE task in a workspace (NOT built — needs per-agent models = the P5 finish).

Then: make the **Model Comparison** Agent-Studio surface a real live side-by-side, add an **Analytics** lane (theoretical open-source benchmarks + real measured runs), and on polish, **fold Analytics into the Comparison tab** as a right-side panel with the answer cards condensing when there are many models.

## State — SHIPPED + browser-verified
1. **Live Comparison surface** (`lib/agent-studio/ModelComparison.svelte`): one shared prompt → each picked model streams its own card via `/api/chat/completions` with `harvis_mode:"chat"` (forces plain chat — skips the workspace auto-detector, so Compare never fans out to OpenClaw). Captures per-run metrics (TTFT / tok-per-sec / latency / length) as it streams.
2. **Persistence** (`owui_compat`): runs saved to `owui_model_comparisons` (one row per `run_id, slot`) + `/api/owui/comparisons` {POST save, POST /judge, GET runs+stats}. Verified rows + answers land in the DB.
3. **On-demand judge**: a "Score answers" button (user picks the judge model) rates each answer 1–10 via the judge model, parses a `{"A":n}` JSON, displays ★ pills, and persists via `/judge`. Verified end-to-end (scores stored).
4. **Curated benchmarks** (`lib/agent-studio/benchmarks.ts`): family-keyed published scores. **ONLY `llama3.1` is seeded** (verified Meta figures: MMLU 69.4 / HumanEval 72.6 / GSM8K 84.5 / IFEval 80.4). Everything else shows "—". **Never fabricate numbers** — add verified ones manually or via the proactive-web-search task.
5. **Analytics = right-side panel inside Comparison** (folded in per user; standalone `Analytics.svelte` surface + its nav pill were REMOVED). Per-model cards: relative tok/s bar + this-run latency/judge + lifetime avg (from stats) + benchmark chips.
6. **Card condense**: answer cards auto-collapse to "View output" rectangles when `>2` models (`autoCollapse = activeCount > 2`); ≤2 stay expanded. Keeps the analytics its room.

Verified live: 2-model run → persist → judge (★ stored) → analytics shows llama3.1's 69.4 MMLU / 72.6 HumanEval next to its measured speed. 3-model run → all cards condensed + 3 analytics rows. Fresh load = clean 2 cards; "+ Add model" = +1.

## Files in flight (MAIN repo, uncommitted)
- Backend: `python_back_end/owui_compat/persistence.py` (table SQL + `save_comparison`/`save_comparison_judge`/`list_comparisons`/`comparison_stats`), `owui_compat/router.py` (3 endpoints), `owui_compat/__init__.py` (export), `python_back_end/main.py` (lifespan `CREATE_OWUI_COMPARISONS_SQL`).
- Frontend: `front_end/owui/src/lib/apis/comparisons/index.ts` (NEW), `lib/agent-studio/ModelComparison.svelte` (rewritten — answers grid + analytics panel + condense + judge), `lib/agent-studio/benchmarks.ts` (NEW), `lib/agent-studio/surfaces.ts` (Analytics entry removed), `routes/(app)/harvis/agent-studio/+page.svelte` (analytics icon removed). `lib/agent-studio/Analytics.svelte` was created then DELETED (never committed → just absent).
- (Also uncommitted from prior sessions on this branch: the Projects/folders work, sidebar tweaks, etc. — see `git status`.)

## Decisions & gotchas
- `harvis_mode:"chat"` is the bypass that keeps Compare as plain chat (gate at `owui_compat/workspace_bridge.py:162`).
- Table keyed by **(run_id, slot)** not (run_id, model_id) — so comparing the SAME model in two columns persists both.
- **Bursty delivery**: the facade sends the whole completion as one SSE chunk, so first-token ≈ done → TTFT≈total and tok/s would explode; `finalizeRun` falls back to total wall-time when the post-first-token window is <250ms. Columns "pop in" rather than type live.
- **Ollama tokens are estimated** (`~`, chars/4) — `model_proxy` only forwards `usage` in SSE for Kimi/NVIDIA. Server DOES log real usage to `proxy_usage_log`.

## Failed attempts / false alarms (don't re-chase)
- "Metrics swapped between models" — FALSE ALARM. Once a run finishes, the judge `<select>` appears in the header and shifts `document.querySelectorAll('select')` indices, which threw off my verification JS. The DB is internally consistent (each row's model_id ↔ its own answer ↔ metrics). gemma4:e2b genuinely runs ~3–4 tok/s on the 8GB box.
- "5 cards appeared" — test-state artifact from rapid scripted picks/adds, NOT a bug. Fresh load = 2, Add = +1 (confirmed).

## Next steps / leftover (tomorrow)
1. **Commit a checkpoint** of this whole arc on `harvis1.1` (no push until verified, per standing rule). It's a large verified body sitting uncommitted.
2. **`+` → Compare / Collaborate chooser** — wire the navbar multi-model `+` to a pick: Compare (→ this surface) vs Collaborate (→ workspace parallel sub-agents). Collaborate needs **per-agent models** in the orchestrator (`stream_parallel_workspace` takes a single model today; OpenClaw config has a `subagents.model` slot) = the P5 finish.
3. **Real Ollama token counts** — extend `model_proxy` to forward Ollama `usage` in the SSE so the `~` estimate goes away.
4. **Bursty-streaming fix** — make columns type live instead of popping in (facade currently emits the whole completion as one chunk).
5. **Populate `benchmarks.ts`** — add verified published numbers for the other model families (gemma4, qwen3.x, hermes, granite, gpt-oss, kimi). Ties into #6.
6. **Stronger default judge** — gemma4:e2b gives flat 10/10; consider a more capable default judge (keep user-adjustable per the standing constraint).

### Pre-existing queued task (still open from before this session)
- **Proactive web search on knowledge gaps** (`memory/project_proactive_websearch_todo.md`): model should `web_search` when it lacks info instead of saying "I don't know" — tune the WEB ACCESS directive in `openclaw_client.py` + uncertainty→retry-with-search (NOT forced tool calls).

## Deploy notes (for reference)
- Frontend: edit MAIN `front_end/owui/src` → `rsync -a --delete --exclude node_modules --exclude build MAIN/src/ WT/src/` → `npm --prefix WT run build` → `rsync -a --delete WT/build/ MAIN/build/` → `docker restart nginx-proxy` → hard reload. (WT = `.claude/worktrees/serene-driscoll-79137f/front_end/owui`.)
- Backend: `owui_compat/` + `main.py` are bind-mounted → `docker restart harvis-backend` (no rebuild). Table created in lifespan.
