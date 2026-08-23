# Handoff — 2026-08-13 · DE-1, DE-2, DE-5 (one source graph, and a rail that projects it)

Branch `harvis1.2`. Built, deployed (`npm run build` in `front_end/owui/` + `docker compose restart
nginx`; engine rebuilt with `docker compose --profile cad build cad-engine` + `up -d
--force-recreate cad-engine`), and verified in a real browser. **Everything is uncommitted, and none
of the three commit scripts covers any of it.**

Obsidian note:
`notes-vault/code/harvis/2026-08-13-the-section-that-would-not-close.md`

Probe surface: `http://localhost:9000/harvis/cad/session/f3e1c1a8-0543-44e8-bbf9-ff4c8104edac` —
project "create a jar", rev 1, Proposal.

## Where the design-environment tranche stands

The user's own implementation order, and what is real:

| # | Item | State |
|---|---|---|
| DE-1 | multi-file CadIR source + stable semantic ids | **done this pass** |
| DE-2 | parameter dependency graph + code source maps | **done this pass** |
| DE-3 | AI experiment / patch / check / preview tools | not started |
| DE-4 | real-time operation events + geometry checkpoints | not started |
| DE-5 | resizable left sidebar (tree · parameters · code · files) | **done this pass** |
| DE-6 | capability packages (CAD Modeling / Knowledge / Mechanical Eng.) | not started |
| DE-7 | toolbar commands with honest stable/experimental/unavailable | not started |

Everything from the earlier CS tranche (CS-1…CS-8) is still done and still uncommitted. CS-9, CS-10
and #173 (the loading state) remain open.

## DE-1 — the project decomposition moved into the engine

The important structural decision, because it is easy to undo by accident: **the backend cannot own
this.** `python_back_end/owui_compat/cad_ir.py` says so in its own docstring — it holds no geometry,
no formula evaluation, and no copy of the CadIR grammar, because the authority on what a document
means is `cad-engine/cadir`, which lives in the sidecar image and is not importable from a backend
that builds from `./python_back_end` alone.

So decomposition is an HTTP hop:

- `cad-engine/cadir/project.py` (new, 590 lines) turns a CadIR document into a project tree.
- `cad-engine/server.py` gains `POST /cad/project`.
- `python_back_end/owui_compat/cad_files.py` calls it and adds only what the backend itself knows —
  the `recipe` and `import` records — then sanitizes every path it got back.

File `kind` vocabulary, straight from `project.py`: `spec`, `main`, `assembly`, `part`,
`annotations`. Plus `recipe` and `import` from the backend. **There is no `model` kind** — the
frontend's TypeScript union used to declare one, and `CadCodeView`'s single-body fallback searched
for it, so a design with no per-part slice silently fell through to "whatever was open". Fixed: the
fallback now looks for `kind === 'main'`.

Route: `GET /api/cad/projects/{project_id}/revisions/{revision_id}/files`.

Tests: **43 pass** in the engine (`tests/test_project.py`, `tests/test_project_route.py`), **27** in
the backend (`tests/test_cad_files.py`, mostly path-boundary and traversal cases). Note the standing
gotcha — `python_back_end/tests` is not bind-mounted, so the backend suite needs a `docker cp` first
or pytest runs the image's older copy.

## DE-2 — the parameter graph is the join, and it already worked

`project.py` also returns a `source_graph` beside the files. Shape, probed live rather than read off
the source:

```
graph        { complete, features, parameters, source_version }
parameter    { name, kind: input|derived, value_type, value, default, resolved,
               min, max, unit, status, defined_in: {path, pointer, line, line_end}, used_by: [...] }
used_by edge { op_id, op, component, label, field, location, unit, formula, path, pointer, line, line_end }
feature      { op_id, op, mode, component, label, reads: [...], defined_in: {...} }
file         { path, kind, component, node_id, language, description, content, bytes, spans }
```

`spans` maps a JSON pointer to `[firstLine, lastLine]`, **1-based**, which is what makes a location
like `main.cadir.json:15` point at an actual line 15 in the gutter. `_range_status`
(`project.py:576`) speaks exactly five words: `unknown`, `out_of_range`, `at_min`, `at_max`, `ok`.

The part worth writing down: **the join key from a parameter to a feature-tree row already existed.**
`CadSceneNode.cadir_operation_id` is the same id as a parameter's `used_by[].op_id`. No new endpoint
was needed to make "features that use it" a highlight instead of a list — the frontend just had
never read it.

Two traps found the hard way, both silent:

- A CadIR `Parameter` **requires** `min` and `max`. Omit them and pydantic raises, `_formulas` ends
  up empty, and the graph comes back with zero consumer edges — a correct-looking response that
  says nothing uses anything.
- CadIR parameter names must match `^[a-z][a-z0-9_]*$`. See the open decisions below.

## DE-5 — the rail is six stacked sections, not five tabs

`front_end/owui/src/lib/cad/CadExplorer.svelte` was rewritten. It had been a five-tab strip; it is
now a column of collapsible, drag-resizable sections in the order the spec asks for, with two extras
on the end.

Order and default state: Feature Tree (open) · Parameters (open) · Code (open) · Project Files ·
History · Renders and Exports.

New: `front_end/owui/src/lib/cad/CadParametersPanel.svelte`. Read-only, and it evaluates nothing —
every number on it is the engine's. Per parameter it shows the value and unit, an `input`/`derived`
chip, `not evaluated` when the engine could not resolve it, range status, the bounds, the declaring
file and line, and `Used by: …`. When the revision on screen is a proposal it also shows `was N mm`
against the accepted head, computed client-side from that revision's own
`cadir.parameters` + `parameters` overrides — **inputs only**, because re-evaluating a formula on
the client could disagree with the engine that built the part.

Design decisions inside the rewrite:

1. **One fetch.** A single `CadCodeView` (with `show='document'`) lives in the Code section and hands
   its tree up through `onTree`; Parameters and Project Files read that same object. Two instances
   would each own their own cache and fetch the same revision twice.
2. **Sections hide, they do not unmount.** `class:hidden` rather than `{#if}`, so collapsing Code
   does not throw away the fetch the other two sections are drawn from, and every section keeps its
   scroll position.
3. **Weights are relative, never pixels.** `flex-grow` per open section, persisted to
   `localStorage.cadExplorerWeights`; a saved pixel height is wrong on the next window.
4. **`tab` means "bring this forward now."** It is a live nomination, not a stored preference.

Verified in the browser: six sections with live counts (5 · 6 · — · 3 · 1 · 4); clicking
`outer_d_mm` opens `main.cadir.json` and highlights lines 15–21; clicking `height_mm` highlights
line 22 **and** turns the "Body" feature row amber; a divider drag moved the boundary by exactly the
pointer travel (259→349 px) and persisted; collapsing Code left all six parameter rows rendered.

## Three defects found while verifying, all invisible to a screenshot

**Drag-to-resize did nothing.** `setPointerCapture` on a 4px handle: the pointer leaves the strip on
the first frame of any real drag, and capture is the only thing that would keep the events coming —
and it silently does nothing when the pointer id is synthetic. Fixed by putting `pointermove` /
`pointerup` / `pointercancel` on the `window` in `pointerdown` and removing them on release, plus
`preventDefault()` so the drag stops selecting the text it passes over.

**Header counts were frozen.** They were a `const` arrow function called from the markup as
`{countOf(id)}`. Svelte tracks the identifiers in the expression — `countOf` and `id` — and neither
ever changes, so the counts would have kept printing a revision-ago number. Now derived with `$:`.

**The section the host last pointed at could not be closed.** Three separate causes, stacked:

- `$: if (isCadExplorerTab(tab) && open && !open[tab]) open = {...open, [tab]: true}` depends on
  `open`, so collapsing the nominated section re-fired it and reopened it on the same tick — after
  `persistLayout()` had already written `false`. The stored state and the drawn state disagreed.
  Now guarded on `tab` having *changed*, via an `applied` marker.
- The rail's `onMount` force-opened `tab` again on every load, resurrecting a section the reader had
  deliberately closed. Removed; the saved layout wins.
- `CadFocusWorkspace.svelte` restored `localStorage.cadExplorerTab` into `explorerTab` in its own
  `onMount` — which fires *after* the child's — so the restored value arrived as a fresh request and
  reopened the section a third time. That restore is gone. `isCadExplorerTab` is no longer imported
  there.

Verified after the fix: collapsed Code survived a full reload, and clicking a parameter still brings
it back and highlights the declaration.

## Open decisions for the user

**Six sections, not four.** The spec lists four. History and Renders-and-Exports have lived only in
this rail since UX-C, so honouring the list literally would delete two working surfaces. They are
stacked below Project Files, collapsed by default. Say the word if they should move elsewhere.

**Parameter names are snake_case and the grammar enforces it.** CadIR requires
`^[a-z][a-z0-9_]*$`, so the mock-up's `pencilLength`, `shaftWidth`, `woodTipLength` and
`graphiteDiameter` are rejected at parse time. The live jar reads `outer_d_mm`, `height_mm`,
`wall_t_mm`, `base_round_mm`. Changing this means changing the engine's grammar and every stored
document — a real migration, not a display tweak.

## Files touched this pass

Engine:
- `cad-engine/cadir/project.py` (new)
- `cad-engine/cadir/__init__.py`, `cad-engine/server.py`
- `cad-engine/tests/test_project.py`, `cad-engine/tests/test_project_route.py` (new)

Backend:
- `python_back_end/owui_compat/cad_files.py` (new), `cad_router.py`, `fab_cad.py`
- `python_back_end/tests/test_cad_files.py` (new)

Frontend:
- `front_end/owui/src/lib/apis/cad/index.ts` — `CadSourceGraph`, `CadParameter`, corrected file kinds
- `front_end/owui/src/lib/cad/CadExplorer.svelte` (rewritten)
- `front_end/owui/src/lib/cad/CadParametersPanel.svelte` (new)
- `front_end/owui/src/lib/cad/CadCodeView.svelte` — `onTree`, `highlight`, `main` fallback fix
- `front_end/owui/src/lib/cad/CadFocusWorkspace.svelte`

## Next

DE-3 is the next item in the user's order: the experiment / patch / check / preview tools that let a
model edit the real CadIR source in a disposable experiment before anything becomes a proposal. It
is the first DE item that needs backend work rather than projection work, and it is what the whole
"failed experiments should not fill permanent revision history" requirement rests on.

Still blocking on the user, unchanged: run `./scripts/commit-groups-2026-08-01.sh` first, then
`./scripts/commit-gate7a-cadir.sh`, then `./scripts/commit-gate7bc-authoring.sh` — and note again
that **none of the three covers the CS or DE work**, which is now a large uncommitted surface.
Credentials (the Kimi/Anthropic key and `OPENCLAW_GATEWAY_TOKEN`) still need rotating.
