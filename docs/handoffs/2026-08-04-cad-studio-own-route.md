# CAD Studio moved out of the chat rail — Gate 6, and where the whole lane stands

**Date:** 2026-08-04 · **Branch:** `harvis1.2` · **HEAD:** `b82521f4` (Gate 5)
**Status:** Gate 6 is built, deployed and verified in a browser. **Nothing from Gate 6 is committed.**

This handoff picks up where `2026-08-03-local-cad-gates-0-1a-1b.md` stops. That one covers the
measurement and the hardening; everything from Gate 2 onward is here.

---

## Where the lane is

Seven of the plan's ten gates are done. Five are committed; the sixth is on disk.

| Gate | What it delivered | Commit |
|---|---|---|
| 0 | Baseline measurement + contract freeze | `e2e63d6f` |
| 1A | Reject bad input, cap the container | `e2e63d6f` |
| 1B | A started build can actually be killed | `e2e63d6f` |
| 2 | Studded brick, GLB/3MF exporters, measured determinism, warm worker pool | `39b7eb02` |
| 3 | Projects, revisions, builds, artifacts, quotas — survives a restart | `bb85d23b` |
| 4 | The vertical slice: build → viewer → revision → restore → export | `17a6698f` |
| 5 | Topological-naming spike + CadIR (schema, restricted-ast formulas, budget, interpreter) | `b82521f4` |
| **6** | **CAD Studio on its own route; Adaptive Space retired** | **uncommitted** |

Remaining: Gate 6's inspector tabs and composer entry (the parts beyond the route move), Gate 7
(prompt → CadIR), Gate 8 (attachments/imports/markup), Gate 9 (downstream fabrication).

170 tests back the lane: 112 in `cad-engine/tests/`, 58 in `python_back_end/tests/test_cad_*.py`.

---

## What Gate 6 changed

The studio was living in a 300 px chat-controls rail, which is the wrong shape for a viewport, a
parameter list, a version history and an export row at once. It now has a page.

**Moved** (recorded as renames, so history follows):

- `lib/components/chat/ChatControls/CadStudioPanel.svelte` → `lib/cad/CadStudioPanel.svelte`
- `lib/components/chat/ChatControls/CadViewer.svelte` → `lib/cad/CadViewer.svelte`

**New:**

- `lib/cad/CadWorkspace.svelte` — the page shell. Both routes are thin mounts of it, so the deep-link
  route never has to import a sibling `+page.svelte` as a component.
- `lib/cad/CadTabLauncher.svelte` — the temporary rail tab. Probes capability, lists up to six recent
  parts, navigates to `/harvis/cad` or `/harvis/cad/{id}`.
- `routes/(app)/harvis/cad/+page.svelte` and `routes/(app)/harvis/cad/[id]/+page.svelte`.

**Changed:**

- `CadStudioPanel.svelte` gained `initialProjectId` and `viewerHeight` props. The panel is now
  host-independent — it does not know whether it is in a rail or a page.
- `ChatControls.svelte` gates the `'cad'` arm behind `const CAD_TAB_IS_LAUNCHER_ONLY = true`, in
  **both** the desktop pane and the mobile drawer. Flipping it to `false` puts the whole panel back
  in the rail; the component is unchanged and still mounted below. Once the route has lived a while,
  delete the `'cad'` arm and `CadTabLauncher.svelte` rather than leaving a dead switch.
- `Sidebar.svelte` has a CAD Studio entry, shown only when `/api/cad/capability` reports the lane
  enabled. That endpoint reads the same server-side flag every `/api/cad/*` route enforces, so the
  nav link can never outlive the feature.
- `ArtifactPreview.svelte` imports `CadViewer` from its new path.

**Retired, not deleted.** Both `/harvis/adaptive` routes now redirect to `/harvis/cad`, and the
"coming soon" placeholder is gone. The ~2,818 lines in `lib/agent-studio/adaptive/` are still in the
tree: nothing imports them, so they cost nothing at runtime, and `RepoRunnerSurface.svelte` alone is
672 lines of working Repo Runner code. Bringing Adaptive Space back is two edits — mount
`AdaptiveSpaceShell` in the adaptive route instead of redirecting, and restore the sidebar link.

The `[id]` adaptive route redirects to `/harvis/cad`, **not** to a CAD project: an adaptive-space id
is not a `cad_projects` id, and quietly opening "some part" for a link that named a different thing
would be worse than landing one level up.

---

## One defect found and fixed during verification

Deep-linking to a project you do not own returns a "Not Found" toast — correct, the ownership check
in `getCadProject` does its job. But the panel then rendered the project selector as an **empty box**
even though the user had their own parts: `value={project?.id ?? ''}` matched no `<option>`, so the
browser showed nothing, which reads as "you have no parts."

Fixed in `lib/cad/CadStudioPanel.svelte` — when parts exist but none is open, a `Select a part`
placeholder option renders. The list underneath was always correct; only the label was missing.

---

## What was verified live, and what was not

Verified in a browser at `http://localhost:9000`, not inferred from HTTP status codes:

- `/harvis/cad` renders the full workspace — brick in the viewport, bbox 39.8 × 19.8 × 12.0 mm,
  volume 3823 mm³, parameter sliders, Versions tab, GLB/STEP/STL export row, storage meter.
- `/harvis/cad/{id}` opens that specific part.
- A deep link to another user's project returns "Not Found" and leaks nothing.
- The Controls CAD tab renders the launcher; clicking a recent part navigates to its deep link and
  the part opens.
- The sidebar CAD Studio entry appears and highlights.
- `/harvis/adaptive` redirects to `/harvis/cad`.

**Not verified:** the mobile drawer arm of the launcher (desktop only), and anything on a narrow
viewport. `npm run build` passes clean ("✓ built in 1m 15s"); the deploy was `docker compose restart
nginx`, required because `npm run build` does `rm -rf build` and replaces the inode the bind mount
pinned.

---

## Standing hazards

1. **The lane is on only via a shell-exported `HARVIS_ADAPTIVE_CAD_ENABLED=true`.** `.env` is still
   empty, and compose env bakes at container **create** — the next plain `docker compose up -d
   backend` turns CAD off. Persisting it is a `.env` edit only the operator should make.
2. **Nothing from Gate 6 is committed**, and five MCP files are pre-staged in the index that must not
   be swept into a CAD commit. Use an explicit pathspec:
   `git commit -F msg -- front_end/owui/src/lib/cad front_end/owui/src/routes/'(app)'/harvis/cad ...`
   and confirm with `git archive HEAD <paths> | tar t` that nothing was silently gitignored —
   `git check-ignore` lies about this repo.
3. Two test CAD projects named "Gate 4 brick" belong to user 1 and one "Untitled part" to user 2.
   They are scratch data, safe to delete.

---

## Next

Commit Gate 6 as its own commit. Then the open question is whether to keep pushing gates (7 is
prompt → CadIR, and its stop rule is "no locally-installed model clears the benchmark — report the
numbers, do not paper over it") or to finish Gate 6's remaining surface work: the inspector tabs
(Features, Inspect, Validate, Source, Files), the composer `+ → Create → 3D / CAD` entry, the result
card, and the settings panels.

Docs: `docs/plans/2026-08-03-local-cad-zoo-parity-plan.md` (the approved plan),
`docs/plans/2026-08-03-local-cad-baseline.md` (Gate 0 numbers),
`docs/design/2026-08-03-cad-topological-naming-spike.md` (Gate 5a).
