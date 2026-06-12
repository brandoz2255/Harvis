# Handoff — right-rail Cowork revamp + Neural Map (2026-06-11)

**Branch:** `harvis1.1` · **Status:** SHIPPED + regression-gate green on :9000 · **Uncommitted**
(standing no-push-until-verified; the checkpoint commit is now the top next action).

## Goal
Make the chat right-rail look like Claude Cowork's panel (stacked rounded collapsible cards),
add a **View** tab (background tasks), revamp **Controls / Artifacts / Brain**, rename the Global
Map to **Neural Map**, restyle it Obsidian-graph-view-style, nest it under Brain, and **document**
(not build) the memory + Open-Notebook graph tie-ins.

## State — everything shipped + verified
- **RailCard** primitive: `front_end/owui/src/lib/components/common/RailCard.svelte` (icon/title/
  count header, actions slot, chevron, slide body, localStorage `persistKey`).
- **View tab**: `lib/components/chat/ChatControls/ViewPanel.svelte` — Progress card (running runs,
  Stop → `POST /api/workspace/cancel/{id}`, refresh) + Recent card. Polls `GET /api/workspace/active`
  FIRST (server orphan-cleans stale `running` rows) then `/history`; 5s cadence while running, 30s idle.
- **Controls**: `Controls/Controls.svelte` → Quick settings card (system prompt + temperature with
  AdvancedParams' exact null-semantics) + Advanced/Valves/Files cards. Contract preserved
  (`{models, chatFiles, params bind, embed}`, permission gates, `chatControls.*` keys).
  **Controls restored to its dock tab** — the uncommitted Wave-2 state had left `<Cookbook mode="dock">`
  there; Cookbook is now the dock fallback + full page (`/harvis/agent-studio/cookbook`).
  (Cookbook rename to "Loadout" liked-but-parked, user 2026-06-10.)
- **Brain**: `lib/agent-studio/Brain.svelte` → RailCard stack (OpenClaw/Skills/Memory/**Neural
  Map**/Tuning). Neural Map card default-closed (= unmounted = no fetch), "Open full" action.
- **Neural Map**: `lib/agent-studio/workflow/sessionsToGraph.ts` (session hubs + run spokes +
  session→run edges; **static d3-force**, 300 ticks, positions only; edge id strings captured
  BEFORE simulating — forceLink mutates endpoints) + `NeuralMapNode.svelte` (dot nodes; **hidden
  1px Handles centered on the dot** so straight edges run center-to-center; status colors; hover
  label pill). `WorkflowFlow.svelte`: `nodeTypes += neural`, session-hub click → `/c/{id}`
  (`discord-*` inert). `GlobalMap.svelte`: `sessionsToGraph` + `embedded` prop + "Neural Map"
  header. Registry: **key `global-map` KEPT** (bridge/route safety), label renamed,
  `surfaceByKey` alias `neural-map`; Agent Studio nav pill removed (filter += `'global-map'`).
- **Gated ChatControls.svelte**: exactly **11 additive hunks** (savedTab union += 'view'; import;
  studio-gate guard; `$: if (activeTab==='global-map') activeTab='brain'` redirect; both tab bars
  Global-Map→View; both if-chains + view branch + restored
  `<Controls embed={true} {models} bind:chatFiles bind:params />` before the Cookbook fallback;
  wrapper class). Bridge/gates/pane/ResizeObserver byte-identical. Pre-edit snapshot:
  `/tmp/ChatControls.pre-view-tab.svelte` (gone after reboot — git diff vs HEAD also captures it).
- **Dep**: `package.json` += `"d3-force": "^3.0.0"` (deduped to the copy already in node_modules
  via vega — zero install cost). `npm install` run in main + build worktree.
- **Design doc (THE documented ideas)**: `docs/design/neural-map-knowledge-graph.md` —
  v1 (shipped) · **v1.5 project-scoped memory layer NOT BUILT** with the resolved finding
  (memory = global per-user, untagged: `harvis_user_memory(user_id, content, source, metadata)`;
  UI writes no metadata; `extract_from_session` is invoked by `plugins/messaging/dispatcher.py:376`
  WITH session_id but the builtin provider inherits the base **no-op**) + the scoped prerequisite
  (tag `metadata.session_id` at write; implement `extract_from_session`; GET filter; per-project
  opt-in toggle — never auto-wired into account-wide) · **v2 Open-Notebook tie-in idea**
  (`/api/notebooks` = real backend: sources/chunking/embeddings/RAG-chat/podcasts via LangGraph;
  notebook sources/notes become project-map nodes; open questions: project⇄notebook association
  model, node caps, containment-vs-similarity edges).

## Regression gate (all green, live on :9000)
Workspace hash-crack E2E (auto-detect → WorkspaceRunCard → stream → **"cracked as 'hello'"
14s/1-tool** → hard-reload persists) · chat persistence · dock bridge (card "View" → docked run
view, canvas + thought stream) · View tab picked the run up next poll · Neural Map renders
hubs+spokes+**edges** with **zero xyflow error008** (full page + `/neural-map` alias + Brain card
embed) · Agent Studio pill gone · run-view canvas + Artifacts tab unaffected · console clean
(only pre-existing audio-autoplay exceptions from the earlier voice session).

## Known caveats / not done
- "Account-wide" graph = `/api/workspace/history` LIMIT-20 window. Backend `?limit=` param =
  later tweak (explicit non-goal of this frontend change).
- **Mobile drawer** got the identical hunks but was not visually exercised — glance at it on a
  narrow window sometime.
- Controls payload spot-check (network tab: `params.system` in the request body) reasoned-correct
  (same bound object as before) but not network-inspected.
- d3-force layouts stable but not bit-identical across refetches (fitView once per mount → no jump).
- Earlier session (same day window): voice fully fixed (Piper default, muted-element root cause,
  sticky mute, mute-to-send, autoplay unlock) — see
  `notes-vault/code/harvis/2026-06-10-voice-playback-and-overlay-ux.md`.

## Next steps (in order)
1. **Checkpoint commit of `harvis1.1`** (NO push) — the pile now spans: blue redesign, files API,
   the whole voice/Piper arc, GPU torch-2.8/CUDA-12.8 infra, telemetry strip, and this rail
   revamp. Overdue and growing.
2. S3 live file-attach round-trip test (built, UI-untested).
3. v1.5 memory-scoping backend prerequisite (small, scoped in the design doc) when the user wants
   project memory maps; then the notebook tie-in (v2).
4. S5 shell dock · Agent Studio polish (#71) · Cookbook→Loadout rename (parked).

## Deploy flow used (unchanged)
Edit MAIN `front_end/owui/src` → rsync src (+package.json on dep change) → build worktree
`npm install && npm run build` → rsync `build/` back → `docker restart nginx-proxy` → hard reload.
