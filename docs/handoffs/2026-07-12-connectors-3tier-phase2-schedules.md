# Handoff — 2026-07-12: 3-tier Connectors + Phase 2 Routines/Schedules + connector logos

## Goal of the session
Finish the IA-redesign track: (a) Phase 2 — split Routines (coding) / Schedules (chat) over the one
cron store with a chat-delivery path and a basic local-time picker; (b) brand logos on every
connector; (c) the Claude-style **3-tier connector UX** (composer "+" submenu → Manage → Browse with
the live MCP registry). Then commit everything on `harvis1.1`.

## State: everything below is BUILT, DEPLOYED locally, BROWSER-VERIFIED, and COMMITTED on `harvis1.1`
(main tree `/home/user/Harvis`). **Nothing pushed** — the standing rule is no
push until the user verifies E2E themselves.

### 1. 3-tier connector UX (this session's main build; Fable build→verify workflow, verdict pass-with-nits)
- **Tier 1 — composer "+" → Connectors submenu** (`InputMenu.svelte`): lists saved MCP connections
  with live ON/OFF pills (POST `/api/owui/mcp/connections/{id}/toggle`; state updates from the
  response, menu stays open), then "Manage connectors" (→ Settings modal, Connectors tab) and
  "Browse connectors" (→ `/harvis/agent-studio/mcp-shop`). Mirrors the Claude popup exactly.
- **Tier 2 — Manage** (`ConnectorsPanel.svelte` reshaped): All / Connected / Not-connected pills;
  POPULAR row (GitHub/Slack/Notion + Connect); Connector/Type/Status table merging saved connections
  (✓ Connected / Turn off / delete) with not-yet-connected catalog templates (Connect button).
  McpShop stays embedded below (`bind:query` is the hook the Connect buttons use).
- **Tier 3 — Browse + live registry**: new backend `GET /api/owui/mcp/registry` in `mcp_wizard.py`
  proxies `registry.modelcontextprotocol.io/v0/servers?search=` (httpx, 8s timeout, auth required,
  user's auth header NEVER forwarded upstream, 300s TTL cache capped at 64 entries, fail-closed →
  200 `{items:[],error}`). `McpShop.svelte` debounce-searches it (350ms + stale-response seq guard)
  and renders a "From the MCP registry" section; **Add** prefills the existing BYO
  custom-url/custom-stdio confirm flow (`fieldValues`/`prefillName`/`prefillTransport`) — user still
  clicks "Confirm connect", no auto-connect, no package execution.
- **Bugs found & fixed during verify**: (1) stale registry prefill leaked into unrelated one-click
  connects — `attach()` now clears prefill when attaching a different card (verifier's fix);
  (2) `each_key_duplicate` crash — the registry lists every VERSION of a server so ids repeat;
  backend now dedupes by id (first occurrence) and the `{#each}` key is `id::index` (found live via
  console, fixed main-loop). E2E re-verified: search "weather" → 8 unique connectors with transport
  badges; Add → custom-url card prefilled with the registry URL.

### 2. Phase 2 — Routines/Schedules split (Fable workflow, pass-with-nits; tz must-fix applied)
- One cron store, two lenses tagged `metadata.context` (`'coding'` default | `'chat'`):
  `routes.py` stamps context + whitelists GET `?context=` (400 on bogus); `store.py` filter is
  parameterized; `runtime.py` chat branch is fail-closed and posts the fired reply into an
  `owui_chats` conversation. `Schedules.svelte` = wrapper mounting `<Automations context="chat"/>`;
  Schedules row in the chat-mode sidebar; basic picker Daily/Weekly/Every-N-hours/Advanced.
- **Timezone fix, E2E-proven**: picker converts local→UTC on save; `scheduleSummary` converts back
  for display. On this UTC-7 box, "Daily at 09:00" stored `0 16 * * *` / next_run 16:00 UTC = 09:00
  PDT and displays "Daily at 09:00". Weekly handles day rollover across midnight.

### 3. Connector logos
`customize/ConnectorLogo.svelte` — 13 marks keyed by catalog id (simple-icons fill for
git/github/postgres/sqlite/puppeteer/notion/slack; lucide-style stroke generics for the rest;
neutral plug FALLBACK so unknown ids can't crash). Slack renders in its real 4 brand colors via an
optional per-path `fills[]`. Verified on cards, in the Settings modal, and in the manage table.

### 4. Also in this commit (earlier sessions' uncommitted work on harvis1.1)
Image generation v0 + create-image button + `generate_image` native-runner tool; typed ```canvas
blocks (CanvasRenderer + rail); Settings modal IA (grouped nav, Customize panels extracted);
MCP→Connectors reskin + publisher tiering; custom sub-agents; model profiles + effort slider;
Dev Console; chat sandbox-file previews; croniter fix. See memory index + prior handoffs.

## Deploy notes
- Frontend: `cd front_end/owui && npm run build` then `docker restart nginx-proxy`.
- Backend (bind-mounted): `docker restart harvis-backend`. Boot log must show
  `⏰ cron tick loop started (interval=60.0s)`.
- **13GB `image-comfy/` is now gitignored** (ComfyUI runtime + SD models — provider build context,
  never repo content).

## Known follow-ups (ranked)
0. **TOMORROW — adjust the UI for connectors** (user flagged end of 2026-07-12 session, no detail
   given yet — ask what specifically before touching code). Candidates already visible from tonight's
   build to raise as options: Tier-1 submenu has no logos/empty-state CTA (see #2 below); the Tier-2
   Manage table is dense/unstyled for a first pass (row spacing, sticky header, maybe collapse the
   POPULAR row once >0 connectors exist); Tier-3 registry cards are plain text rows vs the catalog's
   fuller cards (no logo variety — every registry hit uses the same generic mark); the sync banner
   "N connector(s) connected — not yet live in OpenClaw" competes visually with the new registry
   section. Get the user's actual complaint/reference first — don't guess a direction.
1. **Registry connectors that need auth headers**: many registry remotes (e.g. Smithery) require
   `Authorization: Bearer <key>` at use time; the BYO custom-url flow has no header field yet, so an
   added registry connector can save but fail at connect. Add an optional headers/secret field to
   the custom-url wizard (goes through the existing pending-review secret gate).
2. **Tier-1 polish**: submenu could show a logo per connection (match server_name → ConnectorLogo id)
   and a "no connectors" CTA that deep-links to Browse.
3. Cosmetic nits deferred: DST-boundary picks are ±1h (picker uses today's offset); weekly summary
   says "Sun" not "Sunday"; a reachable-but-empty registry search vs unreachable now have distinct
   copy (fixed), but the registry section could also show result counts.
4. Phase 2 chat-delivery uses the user's default Ollama model — consider a per-schedule model picker.
5. `verify:3-tier` noted the manage table excludes BYO custom tiles by design (they live in the shop
   below) — revisit if users expect them in the table.

## Failed attempts / gotchas (don't re-hit these)
- Svelte 5 **throws** on duplicate `{#each}` keys (`each_key_duplicate`) and the surrounding render
  dies mid-update — the symptom was a stuck "Searching the MCP registry…" state, root cause was
  duplicate server ids from the registry (one entry per published version).
- After an owui rebuild the browser can keep running the OLD immutable chunks — hard-reload
  (Ctrl+Shift+R) before concluding a frontend fix didn't work.
- `compute_next_run` is keyword-only for `now`/`last_run_at`.
- The session's Claude Code cwd is a STALE worktree; always build in the main tree.
