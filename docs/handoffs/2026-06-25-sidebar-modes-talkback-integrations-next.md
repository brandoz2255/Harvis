# Handoff — 2026-06-25 — Sidebar mode switcher · agent talk-back · tool audit (NEXT: Integrations live status)

## Goal (this session)
Polish the OWUI-on-Harvis shell: make the agent narrate status/results, give the run card a
title + a main-chat inspector overlay, and rebuild the sidebar into a Claude-style
**Chat | Notebook | Code** mode switcher. Then audit every sidebar tool for "meaning" and
commit. **NEXT session: make the Integrations page show LIVE status (it's the one stub).**

## State (where things are)
- Branch `harvis1.1`. **Committed `ebe9497`** ("feat(owui): Chat|Notebook|Code sidebar mode
  switcher + agent talk-back + verified arc", 74 files). **NOT pushed** (standing rule).
- Live + verified on `:9000` (all three modes, More pop-out island, Integrations footer row,
  agent talk-back, inspector overlay).
- Nexsys changelog: `notes-vault/code/harvis/2026-06-25-sidebar-mode-switcher-talkback-and-tool-audit.md`.
- Memory updated: `project_sidebar_mode_switcher.md`, `project_workflow_inspector.md`,
  `reference_owui_chat_bubble_layout.md`.

### Deploy flow (unchanged)
- Frontend: edit MAIN `front_end/owui` → `npm run build` → `docker restart nginx-proxy`.
- Backend: bind-mounted → `docker restart harvis-backend` (schema ALTERs run on lifespan).

## Files in flight (this session's shipped work, all committed)
- `front_end/owui/src/lib/components/layout/Sidebar.svelte` — ModeSwitcher render, per-mode
  chat actions, Integrations footer row.
- `front_end/owui/src/lib/components/layout/Sidebar/ModeSwitcher.svelte` — already existed
  (3-pill), now rendered.
- `.../Sidebar/SidebarMore.svelte` (NEW) — pop-out island (portaled `<body>` + fixed), icons.
- `.../Sidebar/NotebookNav.svelte` (rewritten) — New notebook/Sources/Ask&Search/
  Transformations/Customize + notebook recents (`listNotebooks()`).
- `.../Sidebar/VibeCodeNav.svelte` — added Routines/Customize/More.
- `.../Sidebar/HarvisNav.svelte` — DELETED (dead flat nav).
- `front_end/owui/src/app.css` — `.harvis-wordmark` (prototype Inter wordmark).
- `front_end/owui/src/lib/agent-studio/RunView.svelte` — `title` prop + `liveStatus`.
- `front_end/owui/src/lib/components/chat/Messages/WorkspaceRunCard.svelte` — inspector overlay (portaled).
- `python_back_end/workspace/orchestration/orchestrator.py` — conversational recap summary.

## Failed attempts / gotchas (don't relearn)
- A nested `fixed inset-0` overlay/flyout in the chat column or sidebar gets **clipped by a
  transformed/overflow ancestor** → must **portal to `<body>`** (WorkspaceRunCard overlay +
  SidebarMore island both do this). The SidebarMore island is positioned `fixed` from the
  button's `getBoundingClientRect().right`.
- Mode-switcher **pill geometry shifts**: the active segment widens (icon+label), inactive
  ones collapse to icon-only — a segment's x-position changes with the active mode (matters
  when scripting clicks).
- Old `liveStatus`/recap only affect NEW runs; historical runs keep baked-in summaries.

## Sidebar-tool audit result (4-agent workflow)
**15/16 meaningful (real backend). 1 partial:**
- ⚠ **Integrations** = the only stub → the NEXT task below.
- All others confirmed real: New Chat, Projects (owui_folders), Artifacts (workspace_artifacts),
  Customize (owui_skills + MCP + orchestration pool), New notebook/Sources/Ask&Search/
  Transformations (onb_compat facade), New session (VibeCode IDE), Routines (cron + 7d stats),
  Settings (9 tabs), Agent Studio, Neural Map (workspace_runs graph), Model Comparison
  (parallel + LLM-judge), Cookbook (llmfit-serve + Ollama pull/swap).

---

## NEXT: make Integrations show LIVE status (real, not hardcoded)

### Current stub (the whole problem)
`front_end/owui/src/routes/(app)/harvis/integrations/+page.svelte` — a **hardcoded** array of 6
cards (lines 21-62), states baked in. No fetch. Actions route to Settings / VibeCode /
`/workspace/tools`. It's a nav hub, not a live integration manager.

The 6 cards: OpenClaw (Agent runtime), Hermes (Model router), Ollama (Local models), Discord
(Messaging bot), GitHub (Repos & PRs), Custom Tool (Plugin bridge / MCP).

### Plan
**1. Backend — new facade endpoint `GET /api/owui/integrations`** (in `owui_compat/router.py`,
auth = `get_current_user`). Probe each integration's REAL status, return
`[{key,title,type,desc,state:'connected'|'available'|'disconnected'|'add',detail}]`:
- **Ollama** — `GET {OLLAMA_URL}/api/tags` (env `OLLAMA_URL` = http://ollama:11434). Reachable +
  models → connected (detail = N models); else disconnected.
- **OpenClaw** — probe the gateway. Reuse the existing OpenClaw health/config path (the backend
  already talks to `ws://openclaw:18789`; check `workspace/openclaw_client.py` or the
  `/api/workspace/config/openclaw` route for a reachability signal). Connected iff the gateway
  responds.
- **GitHub** — query `github_tokens` for the current user (table from the VibeCode OAuth work).
  Row present → connected (detail = username); else available (action 'connect' → /harvis/vibecode).
- **Custom Tool / MCP** — count `mcp_servers`/owui MCP connections for the user (the
  `/api/owui/mcp/connections` GET already exists — reuse it). N>0 → connected (detail = N); else add.
- **Hermes** — model router. v1: report connected iff the hermes model (`hermes4*`) is present in
  the Ollama tag list, OR based on config; else available. (Hermes lives in `model_proxy`/routing,
  not a separate service — keep the probe simple.)
- **Discord** — the bot is a SEPARATE process (`integrations/discord_workspace_bot.py`). Hardest
  to probe live. v1 options: (a) report 'connected' iff `DISCORD_BOT_TOKEN` env is set
  (configured, not necessarily running); (b) a lightweight heartbeat (bot writes a `last_seen`
  row periodically; endpoint reads it). Pick (a) for v1, note (b) as the real version.

**2. Frontend — repoint the page** to fetch `/api/owui/integrations` on mount and render the
returned list (drop the hardcoded array). Keep the card layout + the action buttons
(Manage→Settings, Connect→/harvis/vibecode, Add→/workspace/tools). Show the live `state` badge +
the `detail` line (e.g. "12 models", "3 MCP servers", the GitHub username). Add a small API
client (e.g. `lib/apis/integrations/index.ts`) or fold into an existing one.

**3. Verify on :9000** — page shows REAL states: Ollama connected w/ model count; GitHub
connected/available per token; MCP count; OpenClaw reachable/not; toggle a token / stop a service
and confirm the badge changes on reload.

### Scope guards
- Read-only probes only (no side effects). Private-IP/localhost is fine (these are internal
  services). Don't leak tokens/hostnames in the response — return booleans + safe details only.
- Flag-gated under the existing Harvis flags; degrade gracefully if a probe throws (→ unknown,
  not a 500).

## Standing rules
Branch `harvis1.1`; build in MAIN `front_end/owui` → restart `nginx-proxy`; backend bind-mounted
→ `docker restart harvis-backend`; Harvis OKLCH dark tokens; never say "Claude" in user copy.
**No push until the user says go.** Reviews ≤3 agents, single pass.
