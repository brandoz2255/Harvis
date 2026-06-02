# Handoff: OWUI-on-Harvis phases P1–P3 + chat-persistence debug (2026-06-01)

## Goal
Turn the OWUI-on-Harvis frontend (branch `harvis1.1`, live at `:9000` via the
`owui_compat` facade) into Harvis: route the agentic workspace in (P1), brand it
(P2), build settings (P3); and fix chat persistence + auto-titles.

## Shipped + deployed this session (all live on :9000)
- **P1 — workspace routed in (1A–1F):** facade auto-detects workspace tasks
  (`owui_compat/workspace_bridge.py`, confidence ≥ 0.8 OR the literal word
  `workspace`/`/workspace` forces it) → launches a run → emits a
  `<details type="workspace_run" workspaceid=…>` marker in the chat SSE →
  `WorkspaceRunCard.svelte` streams `/api/workspace/stream/{id}`; right-rail
  **Activity** tab (ChatControls + `WorkspaceActivity.svelte`); `/harvis/agent-studio`
  + `/harvis/vibecode` routes; sidebar pins **Agent Studio / Vibe Code / Library**
  (gated on `enable_harvis_studio`); top-bar **Research/Agent/Voice** pills
  (store-only — backend wiring is P4).
- **Chat 400 fix:** this OWUI build only sent the full conversation for *temporary*
  chats (it expects its own backend to rebuild history from the DB over a socket).
  Our stateless facade can't, so persisted chats arrived with empty `messages` →
  Ollama 400 `"[] is too short - 'messages'"`. Patched `Chat.svelte`
  `sendMessageSocket` to ALWAYS send the full conversation. **Chat works now.**
- **Auto-titles:** `persistence._derive_title` derives a short title from the first
  user message on create/update (strips `/workspace`, truncates to 60). Verified by
  curl: `/workspace write a python script…` → "write a python script that prints the
  first 10 fibonacci num…".
- **P2 — branding:** 2A logo copied to `static/static/harvis-logo.svg` (fixes the
  blank splash image — `/static/X` serves from `static/static/`); 2B `harvis-dark`
  theme (blue-black palette; `General.svelte` + `app.html` FOUC guard); 2C
  `common/HarvisMascot.svelte` (static teal robot) in the empty-chat placeholder;
  2D purged user-facing "Open WebUI" → "Harvis" (kept "Open WebUI Inc." attribution,
  the Community-platform refs, URLs, code comments).
- **P3 — settings:** `Settings/WorkspaceSettings.svelte` (OpenClaw provider/url/model
  + write-only API key + usage summary) wired into `SettingsModal` as a **Workspace**
  tab (entry + button + content branch, gated on `enable_harvis_studio`). API key is
  encrypted server-side and never returned by GET, so it is never echoed.

## ✅ RESOLVED 2026-06-02 — chat persistence + response + 404s (user-verified)
Four bugs fixed: (1) `update_chat` full-replace → JSONB **merge** `chat || $3::jsonb`;
(2) **stale build** — deployed `build/` was older than source, so fixes weren't live →
always rebuild+redeploy after frontend edits; (3) missing facade stubs (`functions/`,
`tasks/{active/chats,chat/{id},…}`) → 404s + an uncaught `functions/` that wedged New Chat;
(4) `chatCompletedHandler` now `await saveChatHandler(...)` on done (facade doesn't persist
server-side like native OWUI). See `project_owui_phases_status` memory for the full list.
Open: P1.5 approvals; pills wiring (P4); the `127.0.0.1:7808/ingest` telemetry in api clients.

## (historical) original debug target — chat persistence not saving
**Symptom:** new chats don't appear in the sidebar / no row in `owui_chats`
(only 1 old row, from a curl test).

**Confirmed working:** backend CRUD `/api/v1/chats/{new,/,{id}}` — a clean curl
`create → list → delete` all return 200 with a minted JWT. Facade routes +
`persistence.py` SQL are correct.

**Fix present but not landing rows:** `Chat.svelte` `sendMessageSocket` now does
`_chatId = await initChatHandler(_history)` for persisted new chats (markers near
lines ~2131/2135). `initChatHandler` → `createNewChat` (POST `/api/v1/chats/new`,
body `{chat, folder_id}` — matches the facade's `OwuiChatNewBody`). So the path
*should* fire, but rows still aren't created.

**Suspects / next checks (in order):**
1. **Your session-loop edits** to `front_end/owui/src/lib/apis/chats/index.ts`
   (+ `configs/index.ts`, `tools/index.ts`, `utils/index.ts`): did they change
   `createNewChat`'s URL/body/response handling? → `git diff` that file.
2. **Is `initChatHandler` reached at runtime?** Add a `console.log` in the new
   `else` branch of `sendMessageSocket` (the `_chatId = await initChatHandler(...)`)
   and inside `initChatHandler`; send a message; watch the browser console.
3. **Network tab:** send a message → does `POST /api/v1/chats/new` fire, and what
   status? (no fire → frontend path/temp-mode; 4xx → body/auth; 200 + no row →
   user-id mismatch).
4. After a send: `docker exec pgsql-db psql -U pguser -d database -c "SELECT id,user_id,title,updated_at FROM owui_chats ORDER BY updated_at DESC LIMIT 3;"`.
   - Mint a token to curl as a user: `docker exec harvis-backend python3 -c "import sys;sys.path.insert(0,'/app');from main import create_access_token;from datetime import timedelta;print(create_access_token({'sub':'<uid>'},timedelta(minutes=30)))" 2>/dev/null | grep '^eyJ'`

## Deferred (NOT built)
- **P1.5 approvals** — backend emit `approval_request` on the workspace stream when
  a tool needs gating (Tier-3 is force-granted today, `workspace_router.py` ~1536/1653)
  + POST `/api/workspace/{id}/approve|deny` + pause the run; card approval state +
  Approvals rail tab. **Risky** (touches the working OpenClaw tool-exec path) — do in a
  focused session, not while persistence is unstable.
- Top-bar pills (Research/Agent/Voice) are store-only — wire to `/api/research-chat`,
  `/api/mic-chat` in P4.
- Activity tab is desktop-only (mobile drawer pending).

## Deploy workflow (read before redeploying)
- **Full stack:** `docker compose up -d` from the repo root (auto-loads
  `docker-compose.yaml` + `docker-compose.override.yml`). Do NOT use single-container
  ops — they leave the multi-service stack inconsistent → `:9000` errors.
- **Backend** (`owui_compat`, model_proxy, etc.): now **bind-mounted**
  (`./python_back_end/owui_compat:/app/owui_compat:ro` was ADDED to docker-compose.yaml)
  → `docker compose restart backend` picks up edits, no image rebuild.
- **OWUI frontend:** no compose service builds it. Edit source in the MAIN repo →
  `rsync -a <main>/front_end/owui/src/ <worktree>/front_end/owui/src/` →
  `npm run build` in the worktree (`.claude/worktrees/serene-driscoll-79137f/front_end/owui`,
  has node_modules) → `rsync -a --delete <worktree>/…/build/ <main>/front_end/owui/build/`
  → `docker compose restart nginx` (nginx bind-mounts `./front_end/owui/build`; inode swap → restart).

## Branch / commit state
- Branch `harvis1.1`. Everything this session is **uncommitted** (standing rule:
  no push until verified). `docker-compose.yaml` carries the new `owui_compat` mount
  (uncommitted).
- New files: `owui_compat/workspace_bridge.py`; `front_end/owui/src/lib/components/chat/Messages/WorkspaceRunCard.svelte`,
  `chat/WorkspaceActivity.svelte`, `chat/Settings/WorkspaceSettings.svelte`,
  `common/HarvisMascot.svelte`, `apis/streaming/workspace-stream.ts`, `routes/(app)/harvis/*`,
  `static/static/harvis-logo.svg`.
- Edited: `owui_compat/{router.py,config.py,persistence.py}`, `front_end/owui/src/...`
  (`Chat.svelte`, `Placeholder.svelte`, `Navbar.svelte`, `Sidebar.svelte`,
  `ChatControls.svelte`, `SettingsModal.svelte`, `Settings/General.svelte`,
  `stores/index.ts`, `app.html`, `MarkdownTokens.svelte`) + your
  `apis/{chats,configs,tools}/index.ts`, `utils/index.ts`.
