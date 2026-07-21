# EOD Handoff — 2026-07-17 · Launcher prototype done, tomorrow's list locked

## Where we are

**The main-chat redesign is being iterated in an ISOLATED prototype** — `front_end/harvis-ui-prototype/`
(Vite+React, visual-only), served at **localhost:5180** (`npm run dev`; server likely still running).
The real app on :9000 is untouched. Nothing committed or pushed today; all work is on `harvis1.1` main
tree + the prototype dir.

### Prototype state (reviewed live with the user, all verified 0 console errors)

Calm **Warm-paper** default (Claude-shell + Manus-launcher direction; user rejected the earlier
dark/neon/dense pass). Theme system: `[data-theme]` token maps in `src/styles.css` + `src/overrides.css`
(overrides = numbered dev labels + launcher restyles; loaded after styles.css). Themes: Warm (default) /
Airy / Midnight + Slate/OLED/Light. Appearance submenu on the account menu, generated from THEMES[].

**Numbered dev-label overlay** (red badges, "Hide labels" toggle top-right) so the user can reference
regions: 1 logo · 2 mode switcher · 3 New chat · 5 Projects section · 6 Schedules · 7 Agent Studio ·
8 Pinned · 9 Recent chats · 10-13 Cookbook/Providers/Skills/Settings · 14 More · 15 stack status ·
16 account · 17 navbar (DEMO Home/Chat/Build switch) · 19 hero · 20 composer · 21 connect strip ·
22 setup chips (Build mode) · 23 Explore ideas · 24 capability carousel · 25 controls drawer.

**Home = Manus-style task launcher** (final state after today's review rounds):
- Hero: themed robot (`HarvisMascot accent=ROBOT_ACCENT[resolved]`) + mode-aware headline.
- Composer (#20): large glassy card; toolbar = `+` / puzzle(integrations) / monitor(screen) left,
  mic + send right. NO mode chip, NO chat icon, NO status pill (#18 removed), NO mode-pills row
  (Chat/Build/Research/Code/Image/Cookbook pills removed at user request — mode switching now only
  via the internal `launchMode` state; UI entry TBD).
- #21 connect strip sits DIRECTLY under the composer: "Connect your tools to Harvis" + real brand
  logos (`src/brands.tsx`: GitHub/Discord/Notion/Slack/Drive/Gmail — best-effort SVGs, swap for
  official assets for pixel fidelity) + dismiss X.
- #23 Explore ideas: horizontal-scroll pill row + right scroll-arrow, width lines up with composer (760px).
- #24 capability carousel: auto-cycles 4.5s, prev/next arrows, dots; sits LOW (margin-top 96px).
- Reverse-pyramid taper: composer 760 → strip/banner 700 → setup 700 → explore 760(aligned) → carousel 560.
- Sidebar: single themed mark+wordmark (both tint to accent), real owui ModeSwitcher look (active grows
  icon+label, inactive icon-only), New chat accent row, Schedules, Agent Studio, PINNED, **PROJECTS section**
  (Harvis Build Space / OpenClaw integration / Media ingestion), RECENT CHATS, bottom Cookbook/Providers/
  Skills/Settings + More flyout (Neural Map/Model Comparison/Artifacts), footer stack-status + account.
  "Starred"→"Pinned" (no star icons). "Recent build runs" REMOVED. "New build" row REMOVED.
- Chat view (DEMO switch): user bubbles right / assistant full-width; Build view = STUB (see pending).

### Specs & docs written
- `front_end/owui/docs/SPEC-main-chat-redesign.md` — chat-shell spec (sidebar/appearance/home/drawer/surface).
- `front_end/owui/docs/SPEC-harvis-ui-iteration.md` — full 8-section spec (Home, Build workspace,
  preview toolbar, drawers, provider empty states, publish/share gated flow, completion modal,
  task-completed follow-ups) + 6-phase implementation plan + grounding sources (Claude/Manus/Refero).

### Pending / cut off by yesterday's session limit
1. **Build view in prototype** must mirror the REAL harvis1.1 Build cockpit (BuildHeader branch-lock,
   FileRail, tabbed MainPanel [Editor·Diff·Plan·Shell·Browser·Overview·Artifacts], PlanPanel/RunView,
   BrowserPanel preview, gated PrDrawer). Corrected prompt already baked into the rework workflow script
   (`harvis-chat-prototype-rework-wf_935d1f0d-f76.js`) — relaunch fresh or build directly.
2. **`skills/Harvis/harvis-ui-craft/SKILL.md`** house-style skill: 3 research agents CACHED in
   wf_fde884d0-015; author+verify failed on the limit. Resume with `resumeFromRunId`.
3. **owui loading**: user wants content skeletons during first load, not just the logo splash circle
   (`app.html #splash-screen`); `ChatItemSkeleton.svelte` exists — wire skeletons in.
4. Verify launcher in Airy + Midnight (token-driven, should inherit; not re-screenshotted).
5. Refero MCP for design grounding: `claude mcp add --transport http refero https://api.refero.design/mcp
   --header "Authorization: Bearer <token>"` — needs the user's interactive OAuth once.

## TOMORROW'S LIST (user-dictated, in order)
1. Go through **Settings, Notebook, Code/Build UI** — ensure functionality.
2. **Fix the Settings UI.**
3. Make **another mascot**.
4. Adjust the UI for **loading** (skeletons, above) and **workspace** stuff.
5. **Deploy test** again (owui build → restart nginx; backend restart if touched).
6. **Push** (only after user verifies E2E — standing rule), then **test again**.
7. Create the **main website**.
8. Then **Adaptive Space**.
9. **`install.sh` help / installer UX** — so a new (open-source) user can get deployed properly.
   NOTE: `install.sh` EXISTS at repo root (README "Choose your backend & run — ./install.sh") — this is a
   hardening+help pass (`--help`, preflight checks for docker/GPU/env, .env scaffolding incl.
   OPENCLAW_GATEWAY_TOKEN/JWT_SECRET generation, backend choice, clear failure messages), not greenfield.
   Slots naturally around step 5-6 (deploy/push) since pushing makes the repo the user-facing entry.

This is the overall goal list — treat as the roadmap ordering.

**→ FULL PLAN OF ACTION (code-grounded, per-phase verify gates + blocking decisions):**
`docs/plans/2026-07-18-plan-of-action.md` — built from a 3-agent mapping pass over the real Settings/
Notebook/Build code. Headline finds: `presence_penalty`/`repeat_penalty` copy-paste bug (General.svelte:84-85),
dead Account save + dead DataControls routes (facade gaps), Settings theme-divergence bug, the ORPHANED
native notebook page (652L, nothing routes to it — lane decision needed), PlanPanel bypassing the shared
SSE store, dead WorkspaceRightRail (303L), Build cockpit hardcoded dark (raw hex), splash-screen
harvis-dark rule mismatch causing a flash on every load.

## Standing constraints (unchanged)
Work on `harvis1.1` in the MAIN tree `/home/user/Harvis` (session cwd is a stale
worktree — never build there). No push until user-verified E2E. Deploy: owui `npm run build` → restart
nginx-proxy (hard-refresh/cache-bust index.html); backend `docker restart harvis-backend`. Test model
gemma4:12b. Prototype gotcha: launcher pills use `.pill` (`.chip` collides with WorkCard's 32px icon chip).
