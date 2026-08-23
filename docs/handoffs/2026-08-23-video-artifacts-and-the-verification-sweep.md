# Generated video reaches the user, and the black sidebar is gone

**Date:** 2026-08-23
**Branch:** `harvis1.2` in the main checkout at `/home/user/Harvis`
(**not** the `jolly-dhawan-5babcd` worktree — the deployed code is the main checkout)
**Head:** `b7f70eb5`. **Nothing from this pass is committed.** Everything below is on disk and
deployed to the running stack at `http://localhost:9000`.

---

## Pick up here (in order)

1. **Play the MP4.** Open run `1f62a021` ("using comfy ui use make a video of a tree that changes
   through the weather of seasons") and confirm the clip plays in the artifact panel with working
   controls. This is the only link in the chain a human still has to eyeball — every other step is
   verified below. **Known limit:** `get_artifact_raw` returns a plain `Response` with no
   `Accept-Ranges`, so a long clip cannot be seeked. Short clips play fine.

2. **If it plays, decide on the `model_name` telemetry fix** (§"The one real gap", below). Small,
   isolated, unrelated to anything here.

3. **Two of the seven files in this pass are UNTRACKED** — see §"What to commit". A sweep that
   only stages modified files will ship a backend that imports a module that isn't in the repo.

---

## What got built

Two tasks, both done. A third was diagnosed and then deferred by you.

### 1. The black right sidebar after "New Chat" (fixed, you confirmed it live)

Starting a new chat while an artifact was open left a solid black bar down the right side that only
a page refresh cleared. Two independent defects stacked:

**A Svelte store skips its subscribers when the value doesn't change.** The dock was only ever
collapsed by a subscription over in `Chat.svelte`, so `showControls.set(false)` on an
already-`false` store notified nobody and the pane never collapsed. The fix owns the collapse in
`ChatControls.svelte`, where `pane` actually lives, so the width follows the flag no matter who set
it or how:

```js
$: if (paneReady && !$showControls && pane?.isExpanded?.()) collapsePane();
```

`collapsePane()` also cancels any in-flight open animation first — otherwise a still-stepping
animation resizes the pane straight back open — and wraps `pane.collapse()` in a try/catch because
paneforge throws if the group is mid-teardown.

**The `<Pane>` element renders whether or not the dock is open.** Only its *contents* were gated on
`{#if $showControls}`, so an expanded-but-empty pane painted an unconditional background — a solid
black bar in dark mode. Its class now paints only when there is content to paint behind:

```svelte
class="z-10 {$showControls ? 'bg-white dark:bg-gray-850' : ''}"
```

One trap worth knowing: **Svelte does not allow comments inside an attribute list.** The
explanatory comment sits above the `<Pane>` tag, not among its attributes.

### 2. Generated video reaches the user (verified live)

ComfyUI *can* render video — PyAV 18.1.0 with h264/libx264/vp9 is present. The earlier
"No module named 'av'" was a false negative from probing the wrong interpreter: **ComfyUI runs in a
venv at `/comfy/mnt/venv`, not `/usr/bin/python3`.** (Also note `harvis-comfyui` is **not** in
`docker-compose.yaml` — it was started with a bare `docker run` from
`mmartial/comfyui-nvidia-docker:latest`.)

The bytes existed; nothing downstream knew what to do with them. Four layers were fixed:

**The mirror** (`plugins/mcp/media_capture.py`) only recognised image extensions, so an `.mp4`
never mirrored at all. It now carries `_VIDEO_EXT` and `_AUDIO_EXT` alongside `_IMAGE_EXT`, merged
into `_MEDIA_EXT`, with video-scaled limits — 128 MB and 120 s instead of 20 MB and 20 s, because a
few seconds of rendered video is legitimately tens of megabytes and a still's cap would throw away
exactly the results that took longest to produce. The content-type check now allows
`application/octet-stream` on a known media extension; refusing there would drop real files.

**The classifier** (`workspace_router.py`) fell through to octet-stream and — worse — to
`is_binary=False`, so the frontend tried to read a megabyte of h264 as text. `_ARTIFACT_MIME` and
`_ARTIFACT_CATEGORY` gained the video/audio extensions, and:

```python
is_binary = category in ("image", "video", "audio", "pdf", "office", "archive") and ext != "svg"
```

`get_artifact_raw` needed no change — it only rewrites `text/html` and `image/svg+xml` to
octet-stream, so video passes through with its real type.

**The artifact panel** (`Artifacts.svelte`) got a `video` branch rendering `<video controls loop
playsinline>`. It plays in *this* document, not the sandboxed iframe, for the same reason images do:
the src is an object URL owned by this origin. Download was also wrong for both — an image's or
video's `content` is *already* an object URL holding the real bytes, and wrapping that string in a
fresh Blob saved the URL as text instead of the file.

**The run cards** (`RunFileCards.svelte`) opened every binary as an image, so a generated clip
rendered as a broken picture. It now reads the backend's own `category` rather than re-guessing
from the extension — a second, drifting copy of that table is how these things go wrong — and hands
video to the player. `ArtifactPreview.svelte` and `RunArtifacts.svelte` got the matching treatment
in the studio.

### 3. "ComfyUI can't make a video" — diagnosed, then deferred by you

Not context poisoning, and a new session will not fix it. From run `99287269` (Claude Sonnet 5): the
model called `list_workflows` → "Built-in workflows (5): txt2img, img2img, upscale, controlnet,
ip_adapter", called `list_workflow_templates` → "No templates saved yet.", and concluded ComfyUI is
image-only.

**All 15 ComfyUI tool descriptions say "image". The word "video" appears nowhere** — including
`generate_with_workflow`, which is the one tool that can actually produce video and whose
description says it will "return the resulting **image** URLs". `mcp_tool_specs` prefixes each
description with `[server_name]` but otherwise passes upstream text through verbatim; there is no
Harvis-side augmentation layer today. Any model, in any session, will reach the same conclusion.
Templates also don't persist, because they're written inside the reaped MCP sandbox.

**Your call was to leave it and route video through Higgsfield instead.** Higgsfield has 73 tools
including `generate_video`, `generate_video_batch`, `upscale_video`, `reframe`, `motion_control`.
**One caveat that is not a bug:** Higgsfield returns *public* URLs, and the mirror deliberately
leaves those alone, so Higgsfield video shows up as a chat link and does **not** land in the
Artifacts rail. Changing that means mirroring by media type rather than only by unreachable host —
a storage decision, so it wasn't touched.

---

## Verification

**Backend regression: 32 checks, zero failures.** Pre-existing artifact types classify exactly as
before (png/jpg/webp/pdf/html/md/csv, and svg still `is_binary=False` so it renders as markup). New
video/audio types classify correctly. Unknown extensions still degrade to `unknown` + octet-stream
rather than guessing. Mirror SSRF and duplication rules intact: public hosts never mirrored,
loopback/private mirrored, non-media extensions and `file://`/`ftp://` refused.

**Live end-to-end, run `09158228`**, `agent-native` lane on `gemini/gemini-3.5-flash`:

- `[128 connector tool(s) available]` — MCP connector tools reached the model
- it called `mcp__comfyui__generate_image`; the lane gate allowed it
- the mirror fired and saved 317,367 bytes
- the tool result URL came back rewritten to `/api/workspace/artifact/…/raw` instead of the
  unreachable Docker hostname
- that endpoint serves `200 image/png`, 317,367 bytes, intact PNG header
- the list endpoint reports `category: image, mime: image/png, is_binary: true`

**Video specifically** was proven earlier on your own run `1f62a021`: 727,826 bytes in
`content_bytes` with an intact `ftypisom` header, `category: video, mime: video/mp4,
is_binary: true`, and the raw endpoint serving all bytes as `video/mp4`.

**Deployment clean.** Video UI compiled into the shipped bundle, build timestamp newer than the
newest edited source, nginx serving all 54 chunks, `/health` 200, zero backend error lines since
restart, all containers up.

---

## The one real gap found (pre-existing, unrelated to this pass)

`model_name` and `model_provider` are NULL on **747 of 908** `workspace_runs` rows. The split is
clean:

| rows | have `model_name` |
|---|---|
| sub-agent (`parent_run_id NOT NULL`) | **98 / 98** |
| parent (`parent_run_id IS NULL`) | **63 / 810** |

`_db_create_run` never writes either column. Since the runs list returns both to the UI
(`workspace_router.py:3221`), most runs show a blank engine/model. **Telemetry only** — the runs
themselves execute on the correct lane. Run `09158228` above did everything right with NULL in both
columns.

---

## Traps this pass cost time on — don't re-learn them

- **`agent_id` picks the lane, not `model_name`.** `agent_id: "main"` falls through to the OpenClaw
  `else` branch at `workspace_router.py:1450`, and OpenClaw has no MCP connector tools. A test that
  sets `model_name` but leaves `agent_id` at its default lands on OpenClaw, where the model
  improvises a script, fails, and web-searches its own task name. That is working as designed. Use
  `agent-native`.
- **`docker exec` needs `-i` to accept a heredoc.** Without it the container reads empty stdin and
  the edit silently doesn't apply, while the command still exits 0.
- **Never name a container helper script after a stdlib module.** `/tmp/re.py` shadows `re` and
  crashes Python with a circular import. Prefix them `hv_*.py`.
- **DB schema, from memory that was wrong the first time:** `workspace_runs` keys on `id` (not
  `run_id`) and has `task_brief` (not `task`). `workspace_events` is exactly
  `id, workspace_id, seq, event_type, payload, ts` — **no `created_at`**; order by `seq`.
  `workspace_artifacts` stores binary in **`content_bytes`**; `content` is NULL for those, so
  `octet_length(content)` returns None and looks like an empty file.
- **`python_back_end/tests` is not bind-mounted** — pytest runs the image's old copy unless you
  `docker cp` it in.

---

## What to commit

**Two of these are untracked.** A commit script that stages only modified files ships a backend
importing a module that isn't in the repo.

```
?? python_back_end/plugins/mcp/media_capture.py                        (249 lines, NEW)
?? front_end/owui/src/lib/components/chat/Messages/RunFileCards.svelte (252 lines, NEW)
 M python_back_end/workspace/workspace_router.py
 M front_end/owui/src/lib/components/chat/ChatControls.svelte
 M front_end/owui/src/lib/components/chat/Artifacts.svelte
 M front_end/owui/src/lib/agent-studio/ArtifactPreview.svelte
 M front_end/owui/src/lib/agent-studio/RunArtifacts.svelte
```

The five modified files carry **accumulated uncommitted work from several earlier sessions**, not
just this pass — `Artifacts.svelte` alone is 439 changed lines. Read the actual staged hunks before
committing; don't assume the diff is only what this handoff describes.

**Keep all CAD out of any commit:** 16 untracked `owui_compat/cad_*.py`, 29 untracked
`cad-engine/` files, the dirty `cad-*` / `Cad*.svelte` files, and the CAD hunk at
`router.py:768-771`.

**Still needs rotating by you:** the Kimi/Anthropic key, `OPENCLAW_GATEWAY_TOKEN`, the Gemini key,
and the pasted OpenRouter key.

---

## Deploy

```bash
cd /home/user/Harvis && docker compose restart backend
```

Frontend:

```bash
cd /home/user/Harvis/front_end/owui && npm run build && cd /home/user/Harvis && docker compose restart nginx
```
