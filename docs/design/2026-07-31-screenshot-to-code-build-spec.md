# Screenshot-to-code as a Build capability — spec

Date: 2026-07-31 · Status: **Phase 1 code complete, flag OFF, not yet committed** (2026-08-01) ·
Supersedes the Phase-1 shape in `docs/research/2026-07-30-screenshot-to-code.md`
Upstream source: `https://github.com/abi/screenshot-to-code` (MIT, © 2023 Abi Raja), pinned at
commit `d026163f586dfa8c5c10d28c36edd59a9d3b0e88`

Status detail, so the header isn't read as more than it is: the module, the method pack, the
`screenshot_preview` tool, the container mounts, the locked-down renderer, and the multimodal path
are all in the tree and live-verified. `HARVIS_VISION_SELF_CHECK_ENABLED` still defaults to
**false**.

## The multimodal path (implemented 2026-08-01)

Before this, an attached screenshot reached the model as a *line of text* naming the file
(`1. shot.png — image/png — file_id=…`). Nothing carried the pixels, so "screenshot to code" on any
model produced a page invented from the filename. Two pieces close it:

- `vision_to_code/attachments.py` — `build_image_parts()` resolves attachment refs to bytes and
  returns OpenAI-style `{"type": "image_url", "image_url": {"url": "data:…;base64,…"}}` parts,
  resized to ≤1024px on the longest side (the `tools/openclaw_proxy.py` precedent). Byte resolution
  is narrow on purpose: `file_id` via the `/api/uploads` sidecar metadata, `path` only if it resolves
  **inside** `IMAGES_DIR`, `url` only for inline `data:` URIs or Discord's own CDN. An arbitrary URL
  here would be an SSRF primitive reachable from any chat message. Every attachment that can't be
  turned into a part yields a skip reason that is emitted as a run log — a silently dropped image is
  indistinguishable from a model that ignored it.
- `vision_to_code/vision_gate.py` — `model_can_see()` returns True / False / **None**. It blocks only
  on *positive* evidence: an installed Ollama tag whose `/api/show` capabilities omit `vision`.
  Unreachable server, cloud model with no declared capabilities, unknown name → allowed with a
  warning, because inferring "no vision" from silence breaks working setups.

Threading: `workspace_router._start_workspace(attachments=…)` → `_workspaces[id]["attachments"]` →
`run_vibecode_turn(attachments=…)` → `SubAgentRunner.run(task_images=…)`, where the first user turn
becomes a parts list. **`task` stays a string** everywhere else — `_db_create_run` swallows
exceptions, so a list there would silently produce a missing run row and break the FK for every
event on the run.

### What live testing changed

The refusal's "pick one of these instead" list originally came from `list_vision_models()`. Driving
it for real showed that recommends dead ends: `gemma3:12b` has vision but **no tool support**, and
the Build runner always offers a tool schema, so Ollama answers `400 — gemma3:12b does not support
tools` before the image matters. The suggestion filter now requires **vision AND tools**.

### What is verified, and what isn't

Verified on this box: parts built from a real upload (1800×1200 → 1024×683); path traversal,
non-allowlisted hosts, localhost, missing uploads and location-less attachments all refused *with a
reason*; the `max_images` cap announced rather than silent; capability verdicts correct against all
14 installed tags; the refusal firing for `llama3.1:8b`+image, staying silent for `llama3.1:8b`
with no image, and passing for a vision model. The outbound HTTP body was captured mid-flight: the
first user message is a two-part list whose image part decodes back to the exact source pixels.

**Not verified:** a model actually *reading* the image. Ollama on this box cannot load any model —
every request 500s with `llama runner terminated`, including a no-image control, because ~5.5 GB of
the 8 GB GPU is held by another project's services. That last leg needs a free GPU or a cloud key.

**CDN / offline policy — DECIDED 2026-08-01: no CDNs by default.** Generated HTML is
self-contained (inline `<style>`, no `<script>`, no remote font or image). The renderer runs with
JavaScript disabled and no network, so CDN-dependent output would render unstyled and the verify
loop would "fix" damage that only the missing stylesheet caused. `HARVIS_PREVIEW_ALLOW_CDN=1`
restores upstream's CDN recipes for anyone who wants them, and requires a preview runner with JS
and network — i.e. it trades the sandbox away deliberately. Verify loop uses `data:` URLs only
(no SSRF in that path). Verify loop default OFF via `HARVIS_VISION_SELF_CHECK_ENABLED`.

---

## The correction this spec makes

The research doc proposed Phase 1 as a standalone `POST /api/vision-to-code` endpoint. **That is
wrong now that this is a Build/Code capability**, and it's worth being explicit about why: a
separate endpoint forks the code-generation path. It would not get the Build file panel, the plan
panel, the run ladder (Auto / Accept edits / Ask / Plan), approvals, the artifact store, the run
event stream, or `authorize_action()`. Every one of those would need re-implementing or would
silently not apply. Two code-gen paths in one product is the thing to avoid, not the thing to build.

**Screenshot-to-code is a session shape, not a new subsystem.** An image attached to a Build
session, plus a method pack, plus exactly one new tool.

## Why the harvest fits Harvis's Build loop unusually well

The native Build tool loop is `python_back_end/workspace/orchestration/tools.py` (632 lines), whose
`TOOL_SCHEMA` already advertises nine tools with per-tool permission lanes:

| Tool | Line | Lane |
|---|---|---|
| `read_file` | 169 | workspace files |
| `edit_file` | 182 | workspace files |
| `str_replace` | 202 | workspace files |
| `exec` | 226 | container terminal |
| `propose_skill` | 239 | UI/mock |
| `generate_image` | 262 | UI/mock |
| `apply_patch` | 284 | — |
| `git_commit` | 310 | — |
| `finish` | 328 | — |

Upstream's loop contract is *"create with `create_file`, revise with exact-string `edit_file`, never
regenerate the whole file."* Harvis already has both halves of that, with the discipline written
into the tool descriptions themselves — `edit_file`'s description warns it overwrites everything and
says to prefer `str_replace`; `str_replace` demands whole-line exact matches.

**So the loop needs exactly one tool that doesn't exist: `screenshot_preview`.** That is the entire
mechanical gap between what Harvis has and what upstream ships.

## Architecture

```
Build session (existing)
  └── started with an image attachment
        ├── method pack injects the ported prompts (replication rules + stack policy)
        ├── model calls edit_file → writes index.html            [exists]
        ├── model calls screenshot_preview                        [NEW — one tool]
        │     └── browser-runner: render data: URL @ desktop + mobile, full-page
        │           → PNGs returned to the model as vision parts, never persisted
        ├── model compares against the input screenshot, calls str_replace to fix  [exists]
        └── finish → artifact preview auto-opens                  [exists]
```

Rendering already works. `python_back_end/integrations/discord_workspace_bot.py:1264-1312` renders
arbitrary HTML/SVG to PNG through `browser-runner` via a `data:` URL today — session → navigate →
screenshot → close, against `HARVIS_BROWSER_RUNNER_URL` (default `http://browser-runner:8765`).
That code gets extracted into a shared helper so both callers use one path.

### Where it lives in the UI

Build's dock already has a `bw` panel labelled **"Browse & verify"**
(`front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte:553`). The desktop and mobile renders
belong there — the panel exists, it just has nothing feeding it for this flow.

Entry point: image attachment on a Build session. No new engine id, no new route, no new picker.

## What browser-runner is missing

`browser_runner/app.py` is 144 lines with six routes — `/health`, `/session`, `/navigate`, `/act`,
`/close`, `/screenshot`. Verified absent (zero occurrences): `viewport`, `set_window_size`,
`full_page`, `expire`, `MAX_SESSION`.

Two changes, both small:

1. **Viewport on `/session`.** `CreateSessionRequest` takes width/height; the driver calls
   `set_window_size`. Needed because "desktop and mobile" is the whole point of the verify step.
2. **Full-page capture on `/screenshot`.** Today it is four lines returning
   `d.get_screenshot_as_png()` — viewport-only. A page that overflows the fold gets verified on its
   top third, which quietly defeats the loop.

Two more that are hygiene, not blockers, and should ride along:

3. **Session expiry / cap.** Nothing bounds session count or lifetime. A loop that dies between
   `/session` and `/close` leaks a Firefox process, and this feature creates sessions per iteration.
4. **Bake geckodriver into the image.** Line 70 is
   `FirefoxService(executable_path=GeckoDriverManager().install())` — it downloads the driver from
   the internet on first use. That makes a default-install service silently egress-dependent and
   breaks on the DNS-blocked cluster.

**No SSRF work is required here.** This path never navigates to a remote URL — only to `data:` URLs
carrying HTML the system itself just wrote. That is the entire security difference between this and
the render-and-extract capability, and it's why the two should not be built in one pass.

## Phases

### Phase 1 — prompts + the verify loop, one engine, flag-gated

- `python_back_end/vision_to_code/prompts.py` — port with an MIT attribution header naming commit
  `d026163f`. Prompts are "substantial portions"; the notice is required, not optional.
  - replication discipline: "looks exactly like the screenshot", use the exact text, no device frame
    or browser chrome on mobile inputs, multi-screenshot organization rules
  - per-stack CDN recipes with the one-line selector (`build_selected_stack_policy`)
  - the image-generation-disabled policy branch (placehold.co / CSS effects) — upstream ships this
    as a first-class mode, so Phase 1 needs no image tooling
- `python_back_end/vision_to_code/preview.py` — the shared browser-runner render helper, extracted
  from the Discord bot path, with `discord_workspace_bot.py` switched to call it.
- `screenshot_preview` added to `TOOL_SCHEMA`. It renders model-authored HTML in a browser
  container, so it goes through `authorize_action()` behind its own per-capability flag, default
  OFF, matching the lane-5 pattern. Not lane 2 — nothing about it is a file write.
- Returned PNGs are vision parts for the model, explicitly not artifacts. Upstream's phrasing is
  "for seeing, not keeping" and that's the right rule: these are intermediate renders, and
  persisting them would bloat every run.
- Iteration cap of 1–2, plus a per-run ceiling. Upstream enforces `GENERATION_MAX_COST_USD = 3.0`
  per variant; the equivalent here is a bounded iteration count, since Harvis meters differently.
- Model: Kimi K2.5 vision through `model_proxy`. The key never leaves the backend — upstream's
  key-in-browser settings-dialog path is not ported and must never be.

### Phase 2 — targeted element edits

The user clicks an element in the artifact preview iframe; its `outerHTML` is posted back as a
*locator*, with upstream's explicit warning that live DOM differs from source (runtime-injected
classes, framework directives) — the model finds the producing code and changes only that. Mostly
frontend work in the owui preview iframe.

### Deferred, explicitly

Asset extraction, image generation, background removal, and video-to-app are all Gemini-key
dependent upstream, and `model_proxy` has no Gemini lane. Multi-variant comparison duplicates the
existing Multi-model Compare surface. None of these are in scope without a separate decision.

**Do not port:** the React frontend, the WebSocket protocol, the provider clients, the
settings-dialog key path, `api.screenshotone.com` URL capture, Playwright, Langfuse.

## Size

**~0 MB.** Pure Python on the existing 2.42 GB torch-free core. `browser-runner` (864 MB) is already
in the default service set. No new service, no new volume, no new dependency. The 6.28 GB
fresh-install figure is unaffected.

## CDN dependency — resolved 2026-08-01

Upstream's output pulls Tailwind, Babel, or Vue from public CDNs. On an offline or egress-blocked
box the page renders unstyled, and **the verify loop then screenshots the unstyled page and tries
to "fix" it** — a correctness problem for the loop, not a cosmetic one for the user.

Neither of the two options originally listed (vendor Tailwind behind nginx, or document that the
output needs internet) survived the security review, because the renderer had a bigger problem than
fidelity: it was executing arbitrary model-authored JavaScript with a live network. The decision is
to make the sandbox the default and the stack follow it.

**Default mode:** self-contained HTML + CSS. `DEFAULT_STACK = "html_css"`. The `html_tailwind`,
`bootstrap`, `react`, `vue`, and `ionic` recipes still exist and still respond to a user asking for
them by name, but each now tells the model that framework is unavailable here and to produce the
equivalent layout as one self-contained file. `OUTPUT_RULES` states plainly that the renderer has no
JavaScript and no network, so anything remote silently does not load — including remote placeholder
images, which is why `REPLICATION_RULES` now asks for CSS effects or an inline SVG `data:` URI.

**Opt-in mode:** `HARVIS_PREVIEW_ALLOW_CDN=1` restores the upstream recipes verbatim. It also
requires pointing `HARVIS_BROWSER_RUNNER_URL` at a runner with JavaScript and network — the sandbox
is the thing being given up, and the flag name should not disguise that.

### The renderer lockdown (implemented 2026-08-01)

Two fences, because the HTML is model-authored from a user's screenshot and neither fence alone is
convincing:

1. **Browser profile** (`browser_runner/app.py`, `_apply_safe_mode_prefs`): `javascript.enabled` off;
   every proxy protocol pointed at `127.0.0.1:1` with `no_proxies_on=""` and
   `allow_hijacking_localhost=true`, which is a browser-level kill switch for http, https, ftp, and
   socks alike; DNS disabled; service workers, push, WebRTC, and WebGL off. `data:` URLs are not
   network loads, so the preview itself still renders. Firefox's own
   `get_full_page_screenshot_as_png()` needs no JavaScript, so full-page capture survives — and
   `/screenshot` now returns `captureMode` (`native` / `resize` / `viewport`) so a cropped capture
   can't pass as a full-page one.
2. **Container** (`preview-runner` in `docker-compose.yaml`): same image as `browser-runner`, so it
   costs no extra disk (both services declare `image: harvis-browser-runner:latest`). It sets
   `HARVIS_PREVIEW_SAFE_MODE_FORCED=1`, so a caller cannot request JavaScript whatever it puts in
   the request body, and it sits alone with the backend on `preview-net` (`internal: true`) with no
   `ports:`. `HARVIS_BROWSER_RUNNER_URL` points here; `browser-runner` stays unchanged for the
   trusted browsing lane, which genuinely needs JS and the internet.

Honest limit: `preview-net` is a Docker bridge, and bridges are bidirectional — `preview-runner`
can reach `backend:8000` (measured), because that is the same link the backend uses to drive it.
Docker has no one-way network isolation. It cannot reach the internet, `pgsql`, `ollama`, or
`openclaw` (all measured as refused), and the rendered page cannot make any request at all.

Measured on 2026-08-01, driving both runners with the same probe page from inside `harvis-backend`:

| | preview-runner | browser-runner |
|---|---|---|
| requested `safeMode: false` | overridden to `true` | n/a |
| inline `<script>` appended a DOM node | **no** | yes |
| public CDN `<img>` loaded | **no** (alt text only) | yes |
| self-contained CSS rendered | yes | yes |
| `captureMode` | `native` | `native` |

The Discord preview path (`render_html_to_png` / `render_html_dual_viewport`) was re-run through
the new container and produces a real, correctly styled PNG — checked by looking at the image, not
by trusting `ok: true`. `preview.py` also now status-checks the `/navigate` response: a failed
navigation used to be ignored, and the screenshot that followed captured `about:blank` and came
back as a successful render.

## Verification gates — none of this is "done" until these run

1. ~~`browser-runner` renders a CDN-heavy Tailwind page through a `data:` URL.~~ **Moot** — the
   default output no longer uses a CDN, and the renderer deliberately refuses to fetch one. What was
   verified instead is the inverse: a CDN reference does *not* load, and a self-contained page does.
2. **Done** — `get_full_page_screenshot_as_png()` returns `captureMode: "native"` in safe mode, so
   below-the-fold content is captured without JavaScript.
3. Kimi K2.5 fidelity on the ported replication prompt. These prompts were tuned on frontier models
   (fable-5, gpt-5.x, gemini-3.x); portability is unverified.
4. Local Ollama vision models on an 8 GB GPU — expected to struggle with the tool-loop discipline.
   Recall the Ollama `tool_choice` ceiling. Verify before claiming local support; don't assume it.
