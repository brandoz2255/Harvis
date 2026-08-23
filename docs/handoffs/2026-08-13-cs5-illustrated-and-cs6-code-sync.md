# Handoff — 2026-08-13 · CS-5 (illustrated renderer) and CS-6 (tree↔model↔code sync)

Branch `harvis1.2`. Built, deployed (`npm run build` in `front_end/owui/` + `docker compose restart
nginx`), and verified in a real browser. **Everything is uncommitted.**

Obsidian note:
`notes-vault/code/harvis/2026-08-13-the-tree-knew-which-part-the-code-did-not.md`

## Where the CS tranche stands

| Item | State |
|---|---|
| CS-1 dedicated session + `/cad/session/{id}` | done |
| CS-2 semantic part ids + named GLB nodes | done |
| CS-3 virtual per-part CadIR files + read-only code view | done |
| CS-4 three-panel workspace shell | done |
| CS-5 illustrated renderer | **done this pass** |
| CS-6 tree ↔ model ↔ code sync | **done this pass** |
| CS-7 floating viewport toolbar (v1 set) | **not started** |
| CS-8 move/rotate as a CadIR proposal | not started |
| CS-9 right-panel conversation + summarized thinking | not started |
| CS-10 browser E2E (bottle and pencil) | not started |

Probe surface for all of it:
`http://localhost:9000/harvis/cad/session/11111111-2222-4333-8444-555555555555`, project
`cs2-colour-probe-u2` rev 3. The session row and probe projects are deliberately retained.

## CS-6 — what was actually missing

Three of the four sync arrows already existed: tree→viewport, viewport→tree, and code→tree (as a
reveal, not a selection). **tree/viewport→code did not exist at all** — selecting a body gave no
route to `parts/<name>.cadir.json`.

No backend change was needed. `owui_compat/cad_files.py` has been emitting `node_id` on every part
file since CS-3, sourced from the last successful build's scene manifest (`_manifest_nodes`). The
frontend simply never read it.

Three files:

- `front_end/owui/src/lib/cad/CadCodeView.svelte` — new `focusNodeId` / `onFocusApplied` props. The
  matching part file opens; when a design names no components there are no part files and
  `model.cadir.json` **is** the part, so that fallback is honest rather than a guess. The host clears
  the request the moment it lands, which is what stops a hand-picked file being stomped on the next
  visit to the Code tab.
- `front_end/owui/src/lib/cad/CadExplorer.svelte` — `pendingCodeNode`, set reactively from
  `selectedNodeId`, plus an exported `openCode(id)`. `CadCodeView` is only mounted on the
  Files/Code tabs, so a selection made while the Hierarchy is showing has nowhere to land; holding
  it means it lands when the code is actually looked at. Exported method rather than a prop, same
  reason as `revealNode` — asking twice for the same body has to work.
- `front_end/owui/src/lib/cad/CadFocusWorkspace.svelte` — an `openCode(nodeId)` helper (show
  explorer → `await tick()` → delegate) and a `code` action on the status-bar selection chip beside
  `clear`.

**Label correction.** `CadCodeView`'s per-file button said "Show in scene" but only scrolls and
rings the hierarchy row — it has never touched the viewport. It now says **"Show in tree."**
Code→viewport stays deliberately unwired: a real selection would put a chip on the composer that the
user never picked in the viewport.

### Verified

- tree `pencil` → chip `code` → *"Only the operations that build pencil."*
- tree `cap` → click the **Code tab itself** → *"Only the operations that build cap."* (the sync
  does not need the chip)
- hand-picked `parts/bottle.cadir.json` → Scene → back to Code → still bottle
- file tree: `design.spec.json 3 B`, `model.cadir.json`, `assembly.cadir.json`, three part slices

### Not verified live — read this before claiming otherwise

A real mouse click **inside the 3D canvas** could not be landed this session. Clicks at screenshot
coordinates and at DOM coordinates both did nothing, and a control click on the "Wireframe" button
at its screenshot position also did nothing — which is what proves it is the harness, not the code.
Screenshot 1356×739 vs DOM 1862×1014, ~0.73 scale.

Viewport→code is therefore **verified by code path, not verified live**: `pickNode` sets the same
`selectedNodeId` the tree sets, and that single value is what CS-6 reads. Viewport picking itself was
verified live in UX-D and was not touched. Report it that way.

## CS-5 — illustrated renderer

All inside `front_end/owui/src/lib/cad/CadViewer.svelte`. Presentation only; STEP/STL geometry is
untouched, per the spec.

- `displayMode` prop (`illustrated` / `realistic`), an **Illustrated** viewport toggle, persisted to
  `localStorage` and shared across both viewports
- toon shading with a gradient ramp, silhouette + feature-line decorations per body mesh
- decorations hidden while wireframe is active
- theme-aware silhouette colour via a `MutationObserver` on the root element, with `onDestroy`
  teardown and `toonGradient.dispose()`
- fixed a real corruption bug: `clearDecorations` disposed geometry the live part still referenced,
  garbling the viewport on the next load

### Correction — the silhouette was too thick, and that was the "planes"

An earlier draft of this handoff said the averaged-normal hull was "visually inert" on box geometry.
That was wrong, and the user caught it: *"theres like planes around the models."*

The hull's offset was a magic view-space constant, `thickness = 0.008`. The shader moves each vertex
`t · d` along its view-space normal, which lands `t · (h/2) / tan(fov/2)` pixels away after projection
— depth cancels, which is what makes the outline depth-independent. On a 42° camera over a ~700 px
canvas that is **7.3 px**, and seven pixels of back-face on a flat CAD face reads as a slab beside the
part, not a line.

Fixed in `CadViewer.svelte`: `OUTLINE_PX = 1.6` states the target in pixels, `outlineThickness()`
inverts the formula using `camera.fov` and `container.clientHeight`, and `resize()` calls a new
`syncOutlineThickness()` so the uniform is re-derived when the canvas changes height (the view-space
value is only pixel-constant for the height it was computed against). Built, deployed, and verified in
the browser at the same zoom that showed the slabs — clean thin outlines now.

The averaged-normal construction is unchanged and still correct: it is what stops the expanded shell
tearing at hard edges. Only the number was wrong.

## What the next session should do first

1. **CS-7** — the floating Blender-style viewport toolbar, **v1 set only**. Scaling stays out
   ("arbitrary scaling can violate exact dimensions") and selection stays at part/body level until
   stable face/edge naming exists.
2. Then CS-8 (move/rotate as a CadIR proposal — drag is a local preview, Apply creates a proposal,
   Escape cancels without a revision), CS-9, CS-10.

## Blocking on the user (not on the work)

- **Commit scripts, in this order:** `./scripts/commit-groups-2026-08-01.sh` **first** (it owns
  `engine_adapter.py`, which two scripts both claim), then `./scripts/commit-gate7a-cadir.sh`, then
  `./scripts/commit-gate7bc-authoring.sh`. `git commit` is blocked for the assistant. **None of the
  three covers UX-0…UX-G or CS-1…CS-6** — that whole tranche still needs a commit home.
- Rotate both leaked credentials (the Kimi/Anthropic key and `OPENCLAW_GATEWAY_TOKEN`).
- Open forks unchanged: #137 multi-engine, #138 Ollama VRAM levers, #139 deep-research symptom,
  #161 Gate 7D assembly relationships.

## Still-open defects surfaced, not fixed

- `design.spec.json` is `{}` (3 bytes) for revisions created by POSTing a document directly (CS-3).
- `head_revision` can still point at a failed build, so History shows "Accepted" on a red revision.
- The subscription/CLI lane emits no thinking events, so the loading state is static with no
  reasoning tree (#173).
- The recipe path opens no CAD session; only the authoring lane does.
- CS-2 changed body node ids, so a selection saved in an older session's `view_state` will not match
  a freshly built manifest.
- The persisted explorer-tab allowlist silently drops any tab added after UX-C — patched for
  `files`/`code`, and it will rot again.

## Answered this arc

The **jar fork** is closed. "Perfect" meant perfect *execution*, not the parameter sliders — those
did nothing, which is why they were removed. Real-time parameter control is acceptable only if it is
genuinely real-time; the preferred path is that the model designs better in the first place.
Deferred with one standing note: *"we do need to build a guide and path for the models to actually
build out things properly."* No task number yet.
