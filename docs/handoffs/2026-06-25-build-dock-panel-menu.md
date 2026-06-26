# Handoff — Build dock: panel exit/regain via a ⋯ menu (2026-06-25, IN PROGRESS)

Branch `harvis1.1`, uncommitted, **NOT pushed**. Stopped mid-task ("save for tomorrow").

## Goal (user's ask)
The Build workspace right **dock** (cockpit 2×2: TL Background · TR Explorer · BL Plan · BR File)
needs each panel to be **exitable AND regainable**. Today only *some* exit (PaneForge `collapse()`
fails when BOTH panes in a column are collapsed — no sibling to absorb the space), and regaining is
only the easy-to-miss bottom restore bar. Replace that with:
- A **3-dot (⋯) dropdown** next to the Open-Run/header actions → checkbox per panel (what's open).
- **Background tasks open by default.** **Plan open by default only when a plan exists.**
- Reliable exit (any panel) + regain from the menu.

## State — DONE this session
- **Obsidian log written:** `notes-vault/code/harvis/2026-06-25-build-workspace-dock-background-task-card.md`
  (documents the full BW2→BW3→dock arc + BackgroundTaskCard + the live background-tasks test).
- **`lib/agent-studio/PlanPanel.svelte`** — now emits `dispatch('steps', { count: steps.length })`
  reactively, so the page can know when a plan exists (auto-open the Plan panel).
- **`lib/agent-studio/build/BuildHeader.svelte`** — the old single dock-toggle button was REPLACED by
  a **⋯ menu**: new props `panels: Array<{key,label,visible}>` + `dockOpen`; local `panelsMenuOpen`;
  dropdown renders a checkbox row per `panels[]` (dispatches `togglePanel({key})`) + a divider + a
  "Hide/Show workspace dock" row (dispatches `toggleDock`). Compiles; menu is empty until the page
  passes `panels`.

## State — NOT done (resume here) — all in `routes/(app)/harvis/vibecode/+page.svelte`
The page still uses the OLD collapse mechanism. Convert it:
1. **Replace** `collapsed{}` + `paneTL/TR/BL/BR` refs + `collapsePane`/`expandPane`/`anyCollapsed`
   with `let panelVisible = { tl, tr, bl, br }` (load/persist localStorage `harvis.vibecode.panels`)
   + `const togglePanel = (k) => { panelVisible[k] = !panelVisible[k]; persist }`.
   - Defaults (no stored value): `tl=true, tr=true, br=true, bl=false`.
2. **Plan auto-open:** track `let planStepCount = 0; let blTouched = false;`. Wire the BL `<PlanPanel
   on:steps={(e) => planStepCount = e.detail.count}>`. Reactive: `$: if (planStepCount > 0 &&
   !blTouched) panelVisible.bl = true;`. `togglePanel('bl')` sets `blTouched = true`.
3. **Pass to BuildHeader:** `panels={[{key:'tl',label:'Background tasks',visible:panelVisible.tl},
   {key:'tr',label:'Files',visible:panelVisible.tr},{key:'bl',label:'Plan',visible:panelVisible.bl},
   {key:'br',label:'File',visible:panelVisible.br}]}` + `{dockOpen}` + `on:togglePanel={(e) =>
   togglePanel(e.detail.key)}` (keep `on:toggleDock={toggleDock}`).
4. **Conditional-render the dock panes** (this is the real fix — removes the collapse-both bug).
   In the dock region (`grep "RIGHT WORKSPACE DOCK"`, ~line 1608): wrap each quadrant Pane in
   `{#if panelVisible.x}`, drop `collapsible collapsedSize={0} bind:pane onCollapse/onExpand`, and
   gate the columns + resizers:
   - `$: leftHasAny = panelVisible.tl || panelVisible.bl; $: rightHasAny = panelVisible.tr || panelVisible.br;`
   - left column `<Pane>` only `{#if leftHasAny}`; right column only `{#if rightHasAny}`.
   - inner vertical resizer only `{#if panelVisible.tl && panelVisible.bl}` (and tr&&br).
   - the column resizer only `{#if leftHasAny && rightHasAny}`.
   - else (no panels): a centered hint "All panels hidden — use the ⋯ menu."
   PaneForge re-flows on conditional pane add/remove (verify no `order` error; add `order` props if it throws).
5. **Remove the bottom restore bar** (`grep "restore bar"` ~line 1684) — the ⋯ menu replaces it.
6. Build (`npm run build` in `front_end/owui`) → `docker restart nginx-proxy` → verify on `:9000`:
   each panel's ✕ hides it; ⋯ menu re-shows it; Background on by default; Plan auto-appears after a
   run produces a plan; dock toggle still works.

## Gotchas
- 1700-line `+page.svelte` defeats Edit on multi-line blocks → use **marker-based Python surgery**
  (`/tmp/bw3dock_surgery.py` is the template) for the dock-region rewrite; assert `{#if}`/component
  balance before writing.
- Dead code from earlier iterations (`startResize`/`leftW`/`rightW`) — harmless; can sweep.
- The user/linter set the cockpit dark theme (`bg-[#0a0e18]`, `border-white/8`) + removed
  `VibecodeSessionDiff` — keep both.

## Deploy state
`:9000` = the **last clean dock build** (the working main-chat + right-dock layout, per-panel ✕ +
bottom restore bar). The half-done ⋯-menu edits are source-only (PlanPanel + BuildHeader) and compile,
but the page doesn't pass `panels` yet → the ⋯ menu would render empty if rebuilt. Do NOT rebuild
until step 1–5 are done.
