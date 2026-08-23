# Handoff — 2026-08-12 · CAD Focus Workspace, reviewed before building

Branch `harvis1.2`. **Assessment only — no code changed.** The spec below is the user's; the
findings under it are what the codebase says about it.

## The proposal

A **Harvis CAD Focus Workspace**. Nobody chooses "CAD mode": a user asks for a model in normal
chat, Harvis creates the project and shows a live result card, and the card offers **Open CAD
Workspace** while the model is still working. Opening it hides the global left rail, makes the
authorized GLB viewport the primary surface, and moves the *same* conversation into a resizable
right panel (380–460 px, collapsible; Model/Agent tabs on small screens). No duplicate chat. No
forced redirect — staying in normal chat stays valid. Closing returns to the conversation with
state intact.

| Area | Contents |
|---|---|
| Top bar | Back, project, revision, proposal/accepted, conformance, model badge, export |
| Main canvas | Interactive model; standard views, fit, orbit, pan, zoom, measure |
| Right panel | The agent conversation and design activity |
| Context panels | Design, Parameters, Validate, History, Compare, Renders, Artifacts |
| Bottom filmstrip | Iso, front, rear, side, four-view sheet, component renders |
| Status bar | Units, selection, geometry validity, design conformance |

**Design activity, not chain-of-thought.** Real persisted controller events — planning an assembly,
extracting dimensions, recording assumptions, selecting Opus through the subscription sidecar,
creating the DesignSpec, `cad_propose_revision`, building revision 4, validating six bodies and
twelve openings, *conformance failure: port measured 70 mm, expected 65 mm*, repairing, rendering
five views, proposal ready. Rows expand to sanitized args, measurements, duration, safe errors.
Never private prompts, credentials, paths, storage keys, or invented "skill activation".

**Renders** after each meaningful revision: hero iso, front, rear, side, four-view contact sheet,
component sheets where semantic bodies exist, cutaway/exploded only where the geometry supports it.
Each bound to its revision, camera preset and source hash; stored as an authorized artifact; cached;
labelled a *rendered inspection view, not dimensional proof*. Click to lightbox, one click to
download the JPEG/PNG. STEP/STL/GLB/3MF stay separate manufacturing downloads. Render final builds
and important repair checkpoints only; a provider-neutral `cad_render_views` tool lets the model ask
for more.

Proposed order: **UX-1** workspace shell · **UX-2** durable design activity · **UX-3** render
gallery · **UX-4** existing controls into panels · **UX-5** queue/steer/cancel (gated on #144) ·
**UX-6** browser proof (#145). Then Gate 7D vocabulary. Gate 8 stays closed until attachment
ownership is fixed, so no Zoo-style upload or camera controls yet.

## Findings

### Already built — do not rebuild

| Claim in the plan | Reality |
|---|---|
| "add the project-bound workspace transition" | `/harvis/cad` and `/harvis/cad/[id]` are live; the `[id]` route deep-links a project and 404s on one the caller does not own |
| "move the existing viewer into a split layout" | `lib/cad/CadWorkspace.svelte` is **59 lines** — a shell that constrains to `max-w-5xl` and keeps the sidebar. Becoming the focus surface is an edit, not a build |
| **UX-4** — move Parameters, Validate, Versions, acceptance, restore, exports into panels | `lib/cad/CadStudioPanel.svelte` is **1 182 lines** and already has all of them. UX-4 is re-layout, not new function |
| live result card | `CadResultCard.svelte` exists |
| **UX-5** cancel | `cad_cancel_build` is already one of the nine tools. #144 is about cancelling the *model* lane, not the geometry — the gate is placed correctly |

### Gap 1 — there is no live turn (the largest item, and it is not in the list)

`cad_agent.author()` returns one dict when it finishes. `cad_bridge._native_lane` then hands
`_sse_response()` a **pre-built list of lines**. Nothing reaches the browser until the entire
authoring turn completes — 21 s for the plate Opus 5 built on 08-11, and a multi-part speaker
assembly is a different order of magnitude.

So intended-experience step 3 — *the card offers Open CAD Workspace while Claude/Kimi is still
working* — is not a UI change. It requires the authoring turn restructured into a background job
with a durable id and a live stream. Everything in UX-1's live card and all of UX-2 sits on top of
it.

### Gap 2 — Design Activity is greenfield, and it depends on Gap 1

No `cad_events` table. No event writes in any `cad_*.py`. The `trace` list `author()` returns dies
with the request.

There *is* a real event log at `workspace/harvis_trace.py`, but its writer is
`_db_save_event(pool, workspace_id, seq, event)` — keyed on a workspace id, and CAD has no
workspace. Two honest options, neither free:

- a parallel `cad_events` table keyed on build or revision, or
- synthesizing a workspace id per CAD build, which puts CAD rows into the workspace run views

Decide before UX-2, not during. One reuse is straightforward: `workspace/secret_redaction.py`
already enforces the "no credentials, paths or storage keys" rule, so that constraint has an
existing choke point rather than needing a new one.

### Gap 3 — nothing can turn a GLB into an image, and the fix is a spike

Measured inside the running `harvis-cad`:

```
pyrender False   trimesh False   OpenGL False
PIL True         matplotlib True  vtk True
```

VTK can render offscreen — but it reads STL, not GLB, and the container is `read_only`,
`cap_drop: ALL`, no GPU, `mem_limit 2g`, `pids_limit 128`. Software rendering inside those limits is
unproven, and putting a renderer there widens exactly the surface Gates 1A and 1B were built to
narrow.

The cheap alternative is rendering client-side in the existing three.js viewer and uploading the
canvas: proven code, zero new dependencies. The cost is real, though — no renders when nobody has
the page open, none for the Discord lane, and *"generated from the exact revision's GLB"* becomes a
weaker claim than the spec states.

That is a fork, and it deserves what Gate 5's topological-naming question got: **a spike first, then
a schedule slot.**

### One instruction to reconsider

"Remove CAD Studio from the permanent Harvis left rail" deletes the only route to `/harvis/cad`,
which is the only project **list** (`Sidebar.svelte:1256-1272`, gated on `/api/cad/capability`). A
user whose conversation has scrolled away then has no way back to a part they built — and
`cad_projects.conversation_id` is nullable precisely because a project outlives its chat.

The stated principle is that nobody should have to *choose* CAD mode. Entry-through-chat satisfies
that on its own; it does not require deleting retrieval. Keep a parts list reachable somewhere
quiet.

### Already satisfied — needs no new work

"Do not silently accept failed-conformance geometry" is enforced today: 7C-2 makes a failed proposal
never become head, and `POST /revisions/{id}/accept` refuses a failed-conformance revision unless the
caller explicitly acknowledges the failure in the request.

## Revised order

0. **UX-0 — background job + live stream for the authoring turn.** New. Everything below needs it.
0b. **Render-path spike** — server-side VTK-from-STL inside the hardened container, vs client-side
    three.js canvas upload. Write it up before UX-3 is scheduled.
1. UX-1 — focus shell (edit `CadWorkspace.svelte`; keep a parts list reachable)
2. UX-2 — durable design activity (after the `cad_events` vs `workspace_id` fork is answered)
3. UX-3 — render gallery (after the spike)
4. UX-4 — controls into contextual panels (re-layout of `CadStudioPanel`)
5. UX-5 — queue/steer/cancel, gated on #144
6. UX-6 — browser proof, #145

## Next

Build UX-0. UX-1's live card and UX-2's timeline both depend on it, and it is the only item here
that cannot be started in parallel with anything else.
