# Handoff — 2026-07-14 — Build batch (9/10 shipped) + remaining #5 customizable review agents

## Goal (this session)
The user gave a **10-item batch** of Build-area adjustments (plus two features earlier the same day:
Discord↔Build mirror, and the model-selector realtime refresh + engine-filter fix). Then said
**"just run through everything."** All work is on branch **`harvis1.1` in the MAIN tree**
`/home/user/Harvis` — the session cwd is a STALE worktree; never build there.
**Standing rule: NOTHING is pushed** (24 commits ahead of origin + 52 modified + 9 untracked, all local).

## Current state — 9 of 10 shipped + verified live, #5 remaining

Verified **live on the Pop!_OS laptop** via the **claude-in-chrome MCP** (NOT computer-use — that drives
the user's Windows box; the laptop browser shows up in `list_connected_browsers` as `osPlatform:"Linux"`,
deviceId `57051ccd-e1de-4aa9-9e9f-795b6925da16`; `select_browser` it → navigate/screenshot/read_page).

| # | Item | Status |
|---|---|---|
| 1 | Remove Integrations "Default model" dropdown | ✅ shipped+verified (per-card "Set as default model" buttons left intact) |
| 2 | Repo attach → pick DETECTED branch/worktree | ✅ shipped+verified (backend `GET /api/workspace/repo-branches`; two-phase `GitHubRepoModal` → "Choose a branch"; brandoz2255/Harvis → 63 branches) |
| 3 | Discord session live in Build | ✅ already fully wired (a `/harvis-code` turn streams into the Build thread every 2s) |
| 4 | Show coder↔reviewer negotiation IN Harvis | ✅ shipped — `ThoughtStream.svelte` now renders `agent_message` (amber reviewer / gray coder bubbles). *Needs a live review run to observe the bubbles.* |
| 5 | **Customizable review agents** | ⏸️ **DEFERRED — the only remaining item.** Plan below. |
| 6 | Anthropic + Hermes in model picker → engine-pill removed → engine-enablement | ✅ shipped+verified (see below) |
| 7 | Routines → full-page in Build | ✅ shipped+verified |
| 8 | Customize → centered modal | ✅ shipped+verified |
| 9 | Adjustable/rearrangeable dock panels | ✅ shipped (persisted `dockOrder` + HTML5 drag-to-reorder tab strip) |
| 10 | "Browse and verify" browser panel | ✅ shipped+verified (loaded localhost:9000 → live Harvis rendered in the iframe) |

### #6 detail (model picker + engine)
- Picker now shows ALL providers **grouped** (Local / Claude / Hermes / OpenAI) — `modelOptions` = all `$models`.
- The **engine pill was REMOVED**; the model dropdown is the single control. `selectedEngine` is now a
  REACTIVE derivation from `selectedModel` (`engineForOwner` → ready engine, else native). Picking Claude →
  "Claude Code runs autonomously…" descriptor; local → native. (`+page.svelte`; guards 895-896 deleted.)
- **Engine-enablement:** `docker-compose.yaml` `HARVIS_OWUI_EXTERNAL_ENGINES` default flipped `:-}` → `:-true}`
  + `docker compose up -d backend` (recreate). `engine_readiness` now: **claude-code=ready, opencode=ready**
  (codex=missing_auth, hermes-agent=external_no_workspace by design). Claude is now RUNNABLE in Build.

## Files in flight (all uncommitted on harvis1.1)
**Frontend** — `front_end/owui/src/`:
- `routes/(app)/harvis/vibecode/+page.svelte` (biggest: model picker grouping + engine-follow reactive +
  engine-pill removal + Routines full-page + Customize modal + dockOrder/drag + Browser panel wiring +
  Discord chip + model-sync poller + realtime model refresh)
- `lib/agent-studio/build/BrowserPanel.svelte` (**NEW**, untracked)
- `lib/agent-studio/build/BuildHeader.svelte` (Discord "session live" chip)
- `lib/agent-studio/workflow/ThoughtStream.svelte` (agent_message render)
- `lib/agent-studio/GitHubRepoModal.svelte` (two-phase branch picker)
- `lib/apis/agent-runs/index.ts` (getActiveDiscordSession, get/setWorkspaceModel, getRepoBranches)
- `routes/(app)/harvis/integrations/+page.svelte` (removed default-model toggle)

**Backend** — `python_back_end/`:
- `workspace/workspace_router.py` (`/active-discord`, `GET/POST /workspace-model`)
- `workspace/repo_manager.py` (`GET /repo-branches`)
- `workspace/orchestration/__init__.py` (`discord_channel_id` column)
- `owui_compat/router.py` (`?refresh=true` busts native+cloud model caches)
- `owui_compat/cloud_chat.py` (`invalidate_models_cache`)
- `integrations/discord_workspace_bot.py` (mark session discord-launched)
- `workspace/orchestration/review.py` (**untracked** — from earlier Agent Review work; the file #5 edits)
- `docker-compose.yaml` (engine flag)

## NEXT (tomorrow) — #5 Customizable review agents
Make the coder↔reviewer "negotiation" agents user-customizable (define sub-agents in Customize →
Sub-agents; route them into the review, support >2 agents with different skills/models). **Build it
default-safe so the current review behavior is unchanged when no custom ids are supplied.**

Precise plan (from workflow `wf_47e98709`; reuse the orchestrator pattern, don't invent machinery):
1. **Storage exists:** per-user `owui_subagents` table (`owui_compat/subagents.py`, DDL L25-42: name,
   description, system_prompt, allowed_tools, skill_ids, mcp_ids, model[local-only], enabled). CRUD at
   `/api/owui/subagents`; UI = `agent-studio/customize/SubAgents.svelte`.
2. **review.py** (`workspace/orchestration/review.py`): `run_review_conversation` (L174) hardcodes
   `_REVIEWER_SYSTEM`/`_CODER_REVIEW_SYSTEM` (L59-84) + a single `model` (L204), single-reviewer loop (L277).
   - Add params `reviewer_ids: list[str] = None`, `coder_id: str = ""`.
   - `from .subagent_defs import load_subagents, resolve_profile`; index by id; resolve each reviewer +
     the coder to a profile (its model + system_prompt + allowed_tools + skill_ids). Fall back to the
     hardcoded personas + shared `model` when no id → **zero behavior change default.**
   - Generalize the loop to iterate ALL reviewers per round (outcome 'agreed' only when EVERY reviewer's
     last verdict == approved). **Append the VERDICT contract to custom reviewer prompts** so `_parse_verdict`
     / `_VERDICT_RE` keep working. `agent_message` already carries free-form role/label → N distinct
     reviewers render with no schema change (ThoughtStream already renders them after #4).
   - Coder step: pass `system_prompt`/`model`/`disabled_tools = wire_tool_names() - allowed - {finish}` /
     `skill_blocks = await gated_skill_blocks(pool,user_id,skill_ids)` — copy `orchestrator.py` L248-269.
3. **Wire the ids:** `VibecodeReviewRequest` (`workspace_router.py` ~L3475) add `reviewer_ids`/`coder_id`
   (validate they belong to the user + enabled) → `start_vibecode_review` (~L4194) → `_start_workspace`
   ws keys (mirror `vibecode_review_mode`) → vibecode-review dispatch (~L1303-1318) → `run_review_conversation`.
4. **Frontend:** extend `startVibecodeSessionReview` (agent-runs `index.ts` ~L806) body with the ids; add a
   participant picker (reuse the `/api/owui/subagents` list from `SubAgents.svelte`) at the review-trigger
   surface (RepoRunnerSurface / wherever the review button lives).
Constraints to preserve: fail-open ('needs_human' on error), per-session lock, local-model-only
(`resolve_profile` enforces), the VERDICT contract. **Verify with a live multi-round review** (that's why
it wasn't rushed today).

## Also open / decisions for the user
- **The unpushed pile:** 24 commits + 52 modified + 9 untracked, all on harvis1.1. When the user has
  verified enough, stage+commit locally (still HOLD the push per the standing rule; keep `.env`/secrets out;
  the untracked `review.py`, `BrowserPanel.svelte`, `docker-compose.{amd,cpu}.yml` need `git add`).
- Per-card "Set as default model" buttons in Integrations still exist (user only asked to remove the
  standalone toggle) — confirm if those should go too.
- Discord "session live" chip needs a real `/harvis-code start` run to observe illuminating.
- #4 negotiation bubbles need a live review run to observe.

## Deploy / verify quickref
- Backend (bind-mounted code) = `docker restart harvis-backend`; ENV change = `docker compose up -d backend`.
- Frontend = `cd front_end/owui && npm run build` → `docker restart nginx-proxy`. App at `http://localhost:9000`.
- Auth for API tests: mint a user-2 JWT in-container: `docker exec harvis-backend python3 -c "import os,jwt,datetime;print(jwt.encode({'sub':'2','exp':datetime.datetime.utcnow()+datetime.timedelta(hours=1)},os.getenv('JWT_SECRET','key'),algorithm='HS256'))"`.
- View the laptop UI: claude-in-chrome (Linux browser), NOT computer-use.
Memory: `project_build_model_selector_realtime`, `project_discord_build_mirror`, `feedback_computer_use_targets_windows`.
