# Start here — 2026-07-18

> Forward-facing worklist. Full detail of what shipped is in
> `docs/handoffs/2026-07-17-owui-ui-overhaul-eod.md`; the code-grounded per-phase plan is
> `docs/plans/2026-07-18-plan-of-action.md`. This doc is just: resume context → what to do → decisions.

## Resume context (read once)

- **Branch/tree:** `harvis1.1`, MAIN tree `/home/user/Harvis` (session cwd is a
  STALE worktree — edit via main-tree absolute paths only).
- **Locked rules:** blue = default accent; token-only (no raw hex; Warm/Airy/Midnight inherit);
  **Fable-5 subagents for build work** (Workflow, `model:'fable'`, build→verify); **no push until
  user verifies E2E, then ASK**. Nothing pushed — `harvis1.1` is ~25+ commits ahead.
- **Deploy:** owui = `npm --prefix front_end/owui run build` → `docker restart nginx-proxy`;
  notebook = `docker compose -f docker-compose.yaml up -d --no-deps --force-recreate --build open-notebook-ui`
  (the `--no-deps` is REQUIRED). Verify at `:9000` via claude-in-chrome (extension is flaky — retry).
- **Prototype** for cross-reference: `npm --prefix front_end/harvis-ui-prototype run dev` → `:5180`
  (Warm/coral; compare LAYOUT not accent — shipped owui is blue).

## State in one line

All UI-heavy work SHIPPED to real owui (launcher merge, blue sidebars, notebook theme, Skills manager +
multi-source Browse/import, HARVIS chat identity, Settings shell reskin) — built, deployed, E2E-eyeballed,
**not pushed**. What remains is functional/backend-touching or greenfield.

## Tomorrow's worklist (recommended order)

**A. New mascot (#3 on the grand list) — start here.** Quick, visual, unblocks the main website.
   Produce 2–3 themeable `HarvisMark`-style sketches → user picks one. Token-driven; must render in
   Midnight/Airy/Warm.

**B. Build functionality + Settings bug sweep (#1/#2 grand list) — the meatiest UI item.**
   From `docs/plans/2026-07-18-plan-of-action.md` (verify each against live code — it may have drifted):
   - Settings: `presence_penalty`/`repeat_penalty` copy-paste bug (`General.svelte` ~84-85, saved from
     frequency_penalty); dead Account-save + DataControls facade routes; strip dead Personalization/
     Connections weight. (Theme-divergence bug already fixed; the shell reskin already landed.)
   - Notebook: the ORPHANED native notebook page (nothing routes to it) — **lane decision** (promote
     native vs keep `/onb` iframe); fix silent error-swallowing.
   - Build cockpit: real degraded/error states; port `PlanPanel` off its own SSE → shared `subscribeRun`;
     decide `WorkspaceRightRail` (delete vs resurrect). Then the parked composer/header token restyle
     (`docs/research/2026-07-17-build-restyle-research.md`) — retire sky/violet, 3 flagged decisions.

**C. Loading skeletons + workspace polish (#4).** Generalize the `ChatItemSkeleton` I built to other
   cold-load blank states (knowledge/notebooks/model grids); fix the `app.html` splash `harvis-dark`
   rule mismatch causing a color flash on every load.

**D. Deploy test (#5) → Push (#6, GATED).** Full cache-busted pass over Chat/Settings/Notebook/Build in
   all three themes; then **ask the user for an explicit push go** before pushing `harvis1.1`.

**E. Greenfield (#7–9), after the above:** main website (static landing, Warm-paper + new mascot);
   Adaptive Space (resume ringed-HUD `b0963d3a`); `install.sh` help/UX pass (`--help`, preflight, `.env`
   scaffolding incl. OPENCLAW_GATEWAY_TOKEN/JWT_SECRET generation — hardening, not greenfield).

## Late additions (shipped after the first draft of this handoff — all verified live)

- **Explore-ideas REMOVED** from the launcher (was unfinished) + the "Powerful local-first capabilities"
  caption dropped; the carousel cards stay. Dead `exploreIdeas`/`exploreRow`/`.explore-scroll`/`starters`
  cleaned out of `chat/Placeholder.svelte`.
- **Build composer split** (`vibecode/+page.svelte`): a raised **chat card** (`dark:bg-gray-850`, border +
  shadow — brighter than the `gray-900` shell) holding chips/banners/textarea/send, and BELOW it a
  **transparent control strip** (no bg/border/shadow, muted icons) holding run-mode · Agents · attach ·
  mic · model picker · usage meter. DOM-verified: card `oklch(0.14…)`, strip `rgba(0,0,0,0)`.
- **Global model list self-refreshes** — `routes/(app)/+layout.svelte` was load-once (why chat/Cookbook
  went stale). Now a shared `refreshModels(force)` on a 60s interval + focus/visibilitychange, with an
  in-flight guard, hidden-tab skip, signature compare (no picker churn), fail-soft on error, and
  `onDestroy` cleanup. Cookbook also got a 60s silent Installed-tab refresh + re-check on tab entry.
- **Appearance** theme picker added to the user menu (between Settings and Archived Chats), generated
  from `THEMES`, active theme checked, applying via the canonical
  `theme.set + localStorage.theme + applyThemeById` path (so notebook theme-sync follows).

## Parked backlogs (NOT on the original list — surface when relevant)

- **Main UI launcher wiring** (`project_launcher_functional_todos`): connect-tray → real button to
  `/harvis/integrations`; capabilities carousel → real redirects (GitHub/publicity). NOTE: the third
  item (explore-ideas branching + auto-prompt) is now MOOT — the block was deleted as unfinished; if it
  returns it should be built branching-first.
- **Build composer/header restyle** (folded into B above).
- Small flags from the Skills work: imports arrive enabled (draft=unaudited, not toggled Off — needs a
  backend create field); `github.com/<o>/<r>/raw/` URL variant unparsed; shared `Dropdown` Escape closes
  the modal (app-wide, pre-existing); multi-model compare columns all read "HARVIS".
- Icon normalization: agent-studio inline SVGs → `icons/` components (per `front_end/owui/ICONS.md`).

## Decisions the user owns (blockers)

1. **Push go** (explicit) — required before #6.
2. **Notebook lane:** promote the orphaned native page vs keep the un-themeable `/onb` iframe.
3. **`WorkspaceRightRail`:** delete vs resurrect as inline approvals.
4. **Mascot pick** (from 2–3 sketches).
5. **Build composer restyle flags:** violet on orchestrate/agents (retire vs keep semantic); Discord-chip
   indigo (keep as brand exception vs blue); mic placeholder (remove vs keep muted).

## Pointers

- Handoff (full): `docs/handoffs/2026-07-17-owui-ui-overhaul-eod.md`
- Plans: `docs/plans/2026-07-18-plan-of-action.md`, `docs/plans/2026-07-17-proto-merge-sidebars-plan.md`,
  `docs/research/2026-07-17-build-restyle-research.md`
- Obsidian: `notes-vault/code/harvis/2026-07-17-prototype-merge-sidebar-restyle.md`, `notes-vault/projects/Harvis UI polish pass.md`
- Memory: `project_launcher_functional_todos`, `project_skills_manager_settings`,
  `project_proto_merge_sidebars_shipped`, `project_build_restyle_research`, `reference_harvis_icon_system`
