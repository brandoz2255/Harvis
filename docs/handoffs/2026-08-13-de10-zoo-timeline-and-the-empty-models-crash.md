# DE-10 — the Zoo-style timeline reaches the chat, and the crash that was hiding it

`harvis1.2`, **uncommitted**, built and deployed (frontend via `npm run build` + `docker compose
restart nginx`; backend via `docker compose restart backend`). Everything below except the last
item was verified in a browser.

## What was asked

Four things, in the user's words:

> i still want the the tree timeline thing showing in the chatspace just like how i asked earlier
> and in the cad area showing the images too
>
> cuase it only shows some of the process but doesnt get anywhere
>
> also when pressing open studio it should count that as the full studio not tell the user theres
> another full studio
>
> and then it should move the chat area over to the right side like i asked

All four are done. Two of them were finished days ago in the *workspace* and had simply never
reached the *chat card*, which is the surface the user actually looks at first.

## A. The timeline is in the chat card now

`CadResultCard.svelte` (756 lines) renders the same Zoo-style presentation the workspace's Activity
panel does: a per-kind icon at every stop, visible branch lines with indentation, per-row durations,
error codes tinted amber, and the captured render images inline.

The presentation is shared rather than duplicated. Two new modules:

- **`lib/cad/activityIcons.ts`** (82 lines) — `activityIcon`, `activityTint`, `formatDuration`.
  Its own docstring states the reason: *"a wrench that means 'tool' in one place and something else
  in the other is worse than no icon at all."*
- **`lib/cad/activityTree.ts`** (157 lines) — `buildActivityTree` / `flattenActivityTree`.

`CadFocusWorkspace.svelte` was changed to import from `activityIcons.ts` instead of holding its own
copies, so the two surfaces cannot drift.

## B. "only shows some of the process" — the card was reading the wrong stream

This was a real defect, not a rendering gap.

The card read **one job's** `activity` array. A job's activity stops at the model's last tool call,
because that is where the model's turn ends. Everything after it — the geometry build, the built
revision, the proposal going ready, and **every captured render** — is recorded elsewhere.

`cad_store.project_activity()` is **derived, not stored**: synthesized on every read from
`cad_jobs.activity`, `cad_revisions`, `cad_builds` and the `cad_artifacts` render rows. It is a
strict superset of any single job's stream, and it is the only place the images exist at all.

The card now fetches project-scoped activity. Normalizing is one line, because `CadJobEvent` is a
structural subset of `CadActivityEvent` minus `id`:

```ts
const asRow = (e) => ({ ...e, id: `job:${e.seq}` });
```

**Verified on `/c/90203b35-…`:** the card reads **"Design activity · 17"** — the same count the
workspace's own Activity panel shows — with 6 inline render images loaded as authorized blob URLs
via `fetchCadRenderObjectUrl`. The rows run end to end: model selection, schema read, a refused
project creation, revision proposal, project ready, geometry build, built revision, build result
read, proposal ready (56.6 s), then the six captured views.

A `projectActivitySettled` flag guards the poll — without it the poll restarted itself in a loop.

## C. One studio

The "Full studio →" link and its now-unused `goto` import are gone from
`CadFocusWorkspace.svelte`. The session room routes through the **same** Chat overlay the card's
"Open Studio" button opens, so there is only ever one studio to be on. Its header reads
"← Back to the chat".

Two new fields on the `cadFocus` store (`stores/index.ts:186-193`) carry where the exit leads:

```ts
closeTo?: string;
closeLabel?: string;
```

`CadSessionWorkspace.svelte` (234 lines) is the thin route wrapper that pushes the session into the
overlay instead of mounting a second standalone workspace.

## D. Chat on the right

The overlay path is what does it. In `Chat.svelte`'s `<style>`:

```css
:global(#chat-container.cad-focus-on .chat-main-pane) {
  position: absolute; top: 0; right: 0; bottom: 0;
  width: var(--cad-chat-w, 420px) !important;
  flex: 0 0 auto !important; z-index: 30;
}
:global(body.cad-focus-active #sidebar) { display: none !important; }
```

The workspace root takes `style="right: {chatWidth}px"` when `standalone` is false, and `chatWidth`
persists to `localStorage.cadChatWidth`.

**Measured from the DOM** (`getBoundingClientRect`, viewport 1862×1014, dpr 1.375):

```
workspace root  style="right: 420px"   {x: 0,    w: 1442}  z-index 30
.chat-main-pane                        {x: 1442, w: 420}
--cad-chat-w = 420px
pane text  = "Chat Conversation / create a jar"
composer (contenteditable) {x: 1471, y: 915, w: 362, h: 28}
```

## The blocker: an empty models array took the whole chat down

None of the above could be verified at first, because the session room rendered as a black page with
a permanent spinner. One console line was the only evidence:

```
TypeError: Reduce of empty array with no initial value
```

`MessageInput.svelte:713` computed the intersection of every selected model's filters with an
**initial-less** `.reduce()`. With `selectedModels === []` the map produces `[]`, the reduce throws,
and Svelte's error propagation takes the entire `Chat` component down with it.

This was **not** a CAD bug. Any conversation with `models: []` was unopenable on any surface.

Fixed with a guarded IIFE that returns `[]` when nothing is selected. After the rebuild, a reload
with a cleared console buffer produced **zero errors** and a fully rendered room.

### The backend half

CAD child conversations were created with no model on record. `_open_cad_chat` in
`owui_compat/cad_bridge.py` wrote `"models": []` at two sites (the chat object and its seeded first
message), and `Chat.svelte:1648-1653`'s `loadChat()` has no empty-array fallback:

```js
selectedModels =
  (chatContent?.models ?? undefined) !== undefined
    ? chatContent.models
    : [chatContent.models ?? ''];
```

So even with the crash fixed, the room opened with nothing selected and no way to send a follow-up.

A DB probe made the pattern plain — CAD *source* chats carry a model, CAD *child* rooms do not:

```
90203b35 | create a jar in cad          | ["anthropic/claude-opus-5"]
182af0db | create a jar                 | []
e6d7f5e6 | CAD Design for Jar Creation  | ["anthropic/claude-opus-5"]
279f1e2f | create a jar                 | []
7c5b8281 | a rectangular mounting plate | []
```

`_open_cad_chat` now takes `model_id` and the call site passes the lane that is about to author the
part:

```python
model_id=f"{lane.provider}/{lane.model}" if lane.provider else lane.model,
```

which produces exactly the `anthropic/claude-opus-5` shape the source chats already use.

**This is the one item not verified end to end.** The code path is confirmed and the running
container has the new line (`docker exec harvis-backend grep -n … /app/owui_compat/cad_bridge.py`
→ line 601), but proving it needs a fresh CAD authoring turn, which was not run.

## Gotchas worth keeping

- **Never measure layout from the screenshot.** Chrome's capture came back 1356×739 for a
  1862×1014 viewport — roughly the right 170 CSS px are clipped, and `resize_window` did not change
  it. I read the chat pane as missing when it was correctly placed. `getBoundingClientRect` is the
  only honest source.
- **OWUI's composer is a `contenteditable`, not a `textarea`.** `querySelector('textarea')` returns
  null in the chat pane.
- **Multi-line Svelte text interpolation survives into the DOM as newlines.** A three-line caption
  template broke across three rendered lines under an inherited `pre-wrap`. Collapsing it to one
  template-literal expression plus `whitespace-normal` fixed it; verified as
  `height 18px / line-height 17.5px` = one line.
- **These Svelte files are tab-indented 3–13 deep.** Print the target lines with `repr()` before
  writing an edit; guessing the depth fails the match.

## State

Nothing is committed. The existing commit scripts (`commit-groups-2026-08-01.sh`,
`commit-gate7a-cadir.sh`, `commit-gate7bc-authoring.sh`) cover **none** of the CS or DE work,
including this.

## Next

Open a fresh CAD request in chat and confirm the room's composer comes up with Opus 5 already
selected — the one piece that could not be verified without spending a real authoring turn.
