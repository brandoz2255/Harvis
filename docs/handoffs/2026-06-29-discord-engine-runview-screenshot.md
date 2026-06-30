# Discord engine/model separation + run-view revamp + preview screenshots (2026-06-29)

Branch `harvis1.1` (23 commits ahead of origin + ~29 uncommitted files). Standing rule: **NOT pushed — awaiting explicit go.** Everything below is live + verified on the laptop `:9000` / Discord unless marked *engineered (verified later)*.

## Session arc (what shipped today)

### 1. Pre-push gap + security review (of the prior Build-Narrator / usage-meter pile)
Clean: no hardcoded secrets; narrator embeds only file names+stats; live token stream ownership-checked; Download denies secret artifacts; terminal-save reorder safe across all lanes. Gitignored the 68M `front_end/harvis-ui-prototype/` (was the only push blocker). Discord bot confirmed up (runs inside the backend). Doc: `2026-06-29-build-narrator-usage-meter-pre-push-review.md`.

### 2. Cloud Claude + gemma in the Discord model list
`/model` + `/set-model` now offer the user's cloud **Claude** models (cred-gated) + **gemma3:12b** (gemma4:12b needs a newer Ollama → 412). Selecting Claude → in-process `proxy_cloud_chat` reply on cisco's subscription. `discord_workspace_bot.py`: `_selectable_models`, `_cloud_chat_reply`. Memory: `project_discord_claude_models`.

### 3. Discord Engine/Model separation + Path A/B + "Running on Discord" indicator
- **Regression fix**: a Claude pick made EVERY Discord message chat-only; now the cloud reply is fast-path-only and complex tasks reach the workspace lane. Cloud→local fallback is **transparent** ("X is a cloud model … running with a local model instead") and restores the user's **last local model** (`last_local_model_id` col).
- **`/engine`** (Native/OpenClaw | Claude Code), separate from `/model`. claude-code → `agent_id="claude"` scratch lane (runs on subscription).
- **Path A** (engineered, **unverified — no API key**): `model_proxy_anthropic.py` = full OpenAI↔Anthropic tool-calling bridge (request schema + tool_use/tool_result + streaming tool-call deltas); `model_proxy.py` routes a Claude model to Anthropic when `openclaw_llm_config.provider_type=='anthropic'` + **api_key** (oauth rejected). Inert without a key. Unit-verified the transforms.
- **Web indicator**: blinking "Harvis on Discord is running" chip in the Navbar (polls `/api/workspace/active` → `source:"discord"`) → click opens the live run. Memory: `project_discord_agent_engine_paths`.

### 4. Run-view revamp + Discord `/agents` multi-agent
- `RunView.svelte` (mode=full): **claw mascot** in the header (state by phase), a **context/token meter** (`UsageMeter.svelte`, props-driven), and a **preview-primary tabbed layout** (Preview · Workflow · Table; big `fill` preview; narrow left rail = thought stream + changes).
- **`/agents` toggle** (default off; auto-orchestrates multi-part tasks when on) → Discord task runs `agent_id="orchestrated"` + `uniform_model=True` on scratch dirs; run view lanes the agents. Memory: `project_runview_revamp_discord_agents`.

### 5. Three follow-up fixes
- **Per-guild slash sync** — `on_ready` now `copy_global_to(guild)`+`sync(guild)` per guild (instant) + global; `/agents`,`/engine` appear immediately (global sync took ~1h).
- **Meter now calculates** — `/api/workspace/history` SELECT returns `model_name`/`prompt_tokens`/`completion_tokens`; the frontend live estimate counts ALL streamed event content → the gauge moves with AI actions.
- **Discord screenshot of the preview** — on run done with a previewable artifact (image direct; HTML/SVG rendered via the headless **`browser-runner`** service over a `data:` URL → `/screenshot` pngBase64) → posted as a `discord.File`. Render pipeline verified (47KB PNG).

## State of the pile
- **23 commits ahead** of origin + **~29 uncommitted files** (~1,619 insertions). A push needs the uncommitted work committed first.
- **Untracked new**: `model_proxy_anthropic.py`, `UsageMeter.svelte`, `build_narrator.py`, `BuildActions.svelte`, `RunProgressCard.svelte`, `runStages.ts`, 2 handoff docs, `front_end/newjfrontend/app/docs/` (**decide**: deliverable vs scratch). `harvis-ui-prototype/` gitignored ✓.

## Known open / gaps
- **Path A unverified** — needs an Anthropic API key to live-test the OpenClaw→Claude bridge.
- **The web Build UI "Native engine + Claude model" picker** was deferred (needs the api_key to be meaningful).
- ~~**Cloud-Claude 404/500 partials**~~ — **FIXED** (user-confirmed 2026-06-29; chat works E2E on the subscription).
- **Standing**: rotate the public `JWT_SECRET` before/with a public push.
- ~~**Debug logging**~~ — **REMOVED** (2026-06-29 cleanup pass): stripped all `# region agent log` `/tmp/debug-d007eb.log` + `.cursor/debug-*.log` writers across 6 files + neutered the 5 debug-logger helpers. See `2026-06-29-pre-push-repo-cleanup.md`.
- Run-view + screenshot are "a little rough" (user's words) — tweak the layout/results later.

## Deploy
owui build in MAIN `front_end/owui` → `docker restart nginx-proxy`; backend bind-mounted → `docker restart harvis-backend`. Schema ALTERs self-heal in `model_proxy._get_openclaw_config` + `main.py`. **No push until the user says go.**
