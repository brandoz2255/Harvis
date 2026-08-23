# Research: abi/screenshot-to-code — adopt, harvest, or skip?

Date: 2026-07-30 · Researcher: Fable 5 research agent · Method: shallow clone of
`https://github.com/abi/screenshot-to-code` at commit `d026163f586dfa8c5c10d28c36edd59a9d3b0e88`
(2026-07-30) + GitHub API + Harvis source reads. Every claim below is from the repo's own
files or the GitHub API unless marked *estimate* or *unverified*.

---

## 1. What it actually is

**License: MIT** (`LICENSE`, © 2023 Abi Raja). No AGPL, no non-commercial rider. Clean for
an open-source project shipped to users; MIT requires keeping the copyright/permission
notice on "substantial portions" — so harvested prompt files need an attribution header.

**Metadata** (GitHub API, fetched 2026-07-30):
- 73,748 stars, 9,067 forks, 126 open issues.
- Last push: 2026-07-30 (same day) — actively maintained, 1,455 commits on `main`.
- **Zero GitHub releases.** No tags/versioning; consumers pin a commit. Harvest should
  record the source commit hash (`d026163f`).

**Architecture** (from source):
- `frontend/`: React 18 + Vite + Radix UI + CodeMirror, dev server on :5173. The shipped
  frontend Dockerfile is **broken as of this commit**: it does `COPY package.json yarn.lock`
  but the repo only contains `pnpm-lock.yaml` (verified — no yarn.lock exists), and the
  container runs `yarn dev` (a Vite dev server, not a production build).
- `backend/`: FastAPI + Poetry, Python ^3.10, port 7001. Streaming is **WebSocket**
  (`routes/generate_code.py`), emitting per-variant `chunk`/`status`/`variantComplete`/
  `variantError` messages.
- Images arrive as base64 data URLs from the browser; video likewise (passed straight to
  the model as an `image_url` part — video mode is **Gemini-only**, enforced in
  `_get_variant_models`).
- Providers: OpenAI, Anthropic, Gemini (`agent/providers/`). The model enum (`llm.py`) is
  hard-coded to current frontier models (gpt-5.4/5.5/5.6, claude-sonnet-4-6, claude-opus-5,
  claude-fable-5, gemini-3.x). No Ollama/local support, though `OPENAI_BASE_URL` is read
  from env — an OpenAI-compatible endpoint could be pointed at, but the model names would
  still need code changes.
- **API keys: env vars OR typed into a browser settings dialog and sent over the
  WebSocket** — `routes/generate_code.py:302` `_get_from_settings_dialog_or_env(params,
  "openAiApiKey", OPENAI_API_KEY)`. The backend uses whichever it gets. So server-side-only
  config is *possible*, but the stock frontend ships a key-in-browser path that directly
  violates Harvis's `model_proxy` boundary and would have to be ripped out for adoption.
- Optional external services: Replicate (image generation key), and the URL-screenshot
  feature calls **`https://api.screenshotone.com/take`** (`routes/screenshot.py:48`) — a
  third-party hosted API with its own key/ToS.
- Cost guard: `GENERATION_MAX_COST_USD = 3.0` hard ceiling per variant (`config.py`),
  enforced in the agent engine (`BudgetExceededError`). Langfuse telemetry is a dependency.
- An eval harness exists (`Evaluation.md`, `run_evals.py`, `routes/evals.py`, eval sets,
  prompt reports viewable at `/evals/prompt-reports`).

**It is no longer "one big prompt."** The current pipeline is an **agentic tool loop**
(`backend/agent/engine.py` + `agent/tools/`): the model drives `create_file`, `edit_file`
(exact-string replacement, like Claude Code's Edit), `screenshot_preview`,
`extract_assets`, `generate_images`, `edit_images`, `remove_backgrounds`, and
`retrieve_option`. Output is always a **single self-contained HTML file** ("index.html")
that pulls its stack from CDNs.

## The quality edge — concrete techniques (the harvest inventory)

These are the things Harvis's vision path does **not** have today:

1. **The screenshot-the-result-and-verify loop** (`agent/tools/screenshot_preview.py` +
   `preview_screenshot/playwright_backend.py`). After every `create_file`/`edit_file`, the
   system prompt instructs: *"always call screenshot_preview once … to see the full-page
   desktop and mobile renderings … verify they match the requested design. If you spot
   visual problems (broken layout, overlapping elements, wrong spacing or colors), fix
   them with edit_file."* The tool renders the current HTML in headless Chromium at **two
   viewports (desktop + mobile), full-page**, and returns the PNGs to the model as
   multimodal parts (explicitly "for seeing, not keeping" — never persisted as assets).
   This is a real, shipping self-correction loop, not a claim.
2. **Edit-not-regenerate updates.** Two update strategies (`prompts/plan.py`):
   `update_from_history` (replay conversation, stack policy prefixed into the *first* user
   message only) and `update_from_file_snapshot`. Edits go through exact-string
   `edit_file` — "Do NOT regenerate the entire file."
3. **Targeted element edits** (system prompt, "Targeted element edits" section): the user
   clicks an element in the live preview; its `outerHTML` is sent as a *locator*, with an
   explicit warning that live DOM differs from source (JSX `className`, Vue directives,
   runtime-injected classes) — the model must find the producing code and change only that.
4. **Replication discipline** (`prompts/create/image.py`): "looks exactly like the
   screenshot," "use the exact text," extract real assets rather than approximating,
   multi-screenshot organization rules (pages→linked pages, tabs→navigation,
   unrelated→scaffold), and "for mobile screenshots, do not include the device frame or
   browser chrome."
5. **Asset pipeline policy**: `extract_assets` crops genuine image assets out of the input
   screenshot (**requires a Gemini key** — `agent/tools/extract_assets.py` refuses without
   one); `generate_images` only for non-extractable assets; `remove_backgrounds` for
   transparency (gen models can't do alpha); `edit_images` for upscaling instead of CSS
   stretching; and a clean degradation policy when image gen is off: "use provided media,
   CSS effects, or placeholder URLs (https://placehold.co)" (`prompts/policies.py`).
6. **Stack handling = one system prompt, per-stack sections + a one-line selector.** Not a
   template per stack: `system_prompt.py` carries CDN recipes for Tailwind / plain
   html_css / Bootstrap / React (UMD + babel-standalone **pinned to 7.25.6** with a
   comment explaining Babel 8 breakage) / Ionic / Vue (global build), and
   `build_selected_stack_policy()` injects just `"Selected stack: {stack}."`
7. **Optional design-system injection** (`prompts/design_system.py`): a `<design_system>`
   block with "if it conflicts with other instructions, prioritize the design system" —
   plus CRUD routes for saved design systems.
8. **Multi-variant comparison**: 4 parallel generations for create (2 for update/video),
   models cycled based on which provider keys exist; the `retrieve_option` tool lets a
   later agent run pull another variant's full HTML when the user says "like option 2."
9. **Video-to-app prompt** (`prompts/create/video.py`): watch the interaction video,
   reproduce the app *functionally* ("MAKE THE APP FUNCTIONAL using JavaScript … mock
   backend calls"), match colors/sizes exactly.
10. **Failure honesty in the engine**: `EmptyOutputError` (a run that used tools but never
    produced HTML is a retryable failure, not a green run) and the per-variant spend
    ceiling.

## 2. What problem it solves for Harvis — overlap analysis

What "vision-to-code" in Harvis actually is today (verified in source): **generic vision
chat plumbing, not a pipeline.** `owui_compat/chat_completion.py` converts uploaded images
into OpenAI `image_url` vision parts; `moonshot_api.py` passes multimodal content through
to Kimi. There is **no** screenshot→code prompt, no stack policy, no update/edit strategy,
no self-correction loop, and no asset handling anywhere in `python_back_end/`. The
CLAUDE.md claim "vision-to-code tasks (image → React/Tailwind component)" is aspirational
as a *pipeline* — the transport exists, the craft does not.

What Harvis already has that s2c would duplicate:
- **Rendering/preview**: chat auto-opens artifact previews for renderable HTML/SVG; the
  Repo Runner has a live preview iframe.
- **The screenshot half of the loop — already in the DEFAULT install.** `browser_runner/`
  (firefox-esr + Selenium, FastAPI on :8765, **864 MB**, deliberately kept default per its
  own Dockerfile comment) exposes `POST /screenshot`, and
  `integrations/discord_workspace_bot.py:1264-1312` **already renders arbitrary HTML/SVG
  strings to PNG via a `data:` URL** through it. So the "generate → screenshot → compare →
  revise" loop needs zero new services in Harvis — only the loop logic and prompts.
  This confirms the hypothesis in the assignment: Harvis is unusually well-positioned.
- **Engines/keys**: `model_proxy` already fronts Anthropic, Moonshot/Kimi, Ollama —
  strictly better than s2c's key handling.
- **Multi-model comparison**: Harvis already has a Multi-model Compare surface.

What s2c adds that Harvis lacks: items 1–9 above — i.e., the prompts and the loop
contract. Its plumbing (React frontend, WS streaming, provider clients, Playwright) is all
redundant with Harvis, and its frontend is currently un-buildable as shipped.

## 3. Verdict

**HARVEST-PROMPTS** (plus the loop contract). Adopting the app would add an estimated
2–3 GB of images (a second Chromium next to browser-runner's Firefox, a second React
frontend on a broken Dockerfile, a key-in-browser path to rip out) to buy plumbing Harvis
already has; the entire verifiable value — the prompt discipline and the
screenshot-verify-fix loop — is ~700 lines of MIT-licensed prompt/loop code that maps
directly onto browser-runner + model_proxy + the artifact preview Harvis already ships.

## 4. Integration plan (phased)

**Phase 1 — prompt harvest + endpoint (lane 1/2, no new flag, no new deps).**
- New module `python_back_end/vision_to_code/` (keeps files <500 lines, DDD-bounded):
  - `prompts.py` — port, with MIT attribution header + source commit hash:
    `SYSTEM_PROMPT` (persona, tool discipline, per-stack CDN recipes, targeted-element-edit
    rules), `build_image_prompt_messages` (replication + multi-screenshot rules),
    `build_selected_stack_policy` / `build_user_image_policy` / design-system block, and
    the two update builders (`from_history`, `from_file_snapshot`).
  - `pipeline.py` — create/update plan derivation (port of `prompts/plan.py`, 35 lines).
  - `router.py` — `POST /api/vision-to-code` (JWT-authed like every endpoint, SSE
    streaming like the existing workspace lanes), model via **model_proxy** (Kimi K2.5
    vision or cloud Claude; key never leaves the backend). Output = single-file HTML →
    existing chat artifact preview auto-open. Wire into `python_back_end/main.py` +
    nginx `/api/` (already proxied).
- Adaptation required (not copy-paste): drop the Gemini-only tools (`extract_assets`,
  `generate_images`, `edit_images`, `remove_backgrounds`) — Phase 1 uses the "image
  generation disabled" policy branch (placehold.co / CSS effects), which s2c already
  ships as a first-class mode.
- Honest effort: **2–4 days** including live verification against Kimi vision.

**Phase 2 — the screenshot-verify-fix loop (flag-gated, lane 3 semantics).**
- Reuse the Discord bot's data-URL render path: extract
  `discord_workspace_bot.py:1264-1312`'s browser-runner rendering into a shared helper
  (e.g. `python_back_end/vision_to_code/preview.py`) so both callers use it. Add a mobile
  viewport option to `browser_runner/app.py` if `/session` doesn't already accept one
  (*unverified — check `CreateSessionRequest`*).
- Loop: generate → render desktop+mobile PNGs → feed back with the input screenshot →
  targeted `edit_file`-style revision → cap at 1–2 iterations and port the per-run cost
  ceiling idea from `config.py`.
- Gate: generated (model-authored) HTML executing in a browser container is lane-3-like;
  route the loop through `authorize_action()` in
  `python_back_end/workspace/orchestration/authz.py` behind a per-capability flag
  (e.g. `vision_to_code.self_check`), default OFF, matching the lane-5 per-capability
  pattern. Effort: **3–5 days**.
- Note: Firefox-ESR screenshots vs s2c's Chromium — rendering differences are cosmetic
  for verification purposes; no new browser needed.

**Phase 3 (optional, ask first) — element-targeted edits + design systems.**
- The targeted-element-edit contract needs a click-to-select affordance in the owui
  artifact preview iframe (postMessage the outerHTML). Design-system block is trivial to
  accept as a request field. Effort: ~1 week, mostly frontend.

**Phase 4 (explicitly deferred) — asset extraction, video input, variants.**
- Asset extraction and video mode are Gemini-key-dependent upstream; Harvis has no Gemini
  lane in model_proxy today. Variants duplicate Multi-model Compare. Skip unless asked.

**Do NOT port**: the React frontend, the WebSocket protocol, the provider clients, the
settings-dialog key path, the screenshotone URL-capture, Playwright, Langfuse.

## 5. Size cost

- **Harvest (recommended): ~0 MB.** Pure Python prompt/loop code on the existing 2.42 GB
  torch-free core image; Pillow is already in `requirements-core.txt`; browser-runner
  (864 MB) is already in the default set. No new volume. **DEFAULT service set — nothing
  new to gate for Phase 1; Phase 2 is a runtime flag, not a service.**
- **Adoption (rejected), for the record — *estimates*, not built:** backend =
  `python:3.12.3-slim` (~125 MB) + Poetry deps (openai, anthropic, google-genai,
  moviepy+numpy+imageio-ffmpeg, pillow, playwright, langfuse…) + `playwright install
  --with-deps chromium` (Chromium ~170 MB + OS libs several hundred MB) ≈ **1.3–1.8 GB**;
  frontend = node:22-slim + node_modules under a dev server ≈ **0.7–1 GB** (after fixing
  the broken yarn.lock COPY). Total ≈ **2–2.8 GB** against ~0.7 GB of remaining budget
  headroom (6.28 GB used / 7 GB cap, CI fail at 7.5 GB). Even profile-gated it ships a
  second headless browser beside browser-runner. This alone kills adoption.

## 6. Distro notes

- **Linux/compose (harvest)**: no compose changes for Phase 1; Phase 2 talks to
  `http://browser-runner:8765` on networks the backend already joins. Backend restart via
  the standing rule (`docker compose restart harvis-backend`); mind the bind-mount inode
  trap for `python_back_end/*.py` live edits.
- **Windows / Docker Desktop / WSL2 (harvest)**: nothing new — no GPU, no host paths, no
  Docker socket, no host networking; browser-runner already runs there. One caveat:
  generated artifacts load Tailwind/Babel/Vue from public CDNs, so an offline Windows lab
  box will render unstyled previews *and* the Phase 2 loop will screenshot the unstyled
  page — either vendor `cdn.tailwindcss.com`'s script behind nginx or document the
  internet requirement (remember the nginx `.mjs` MIME/silent-CDN-fallback gotcha).
- **K8s**: Phase 1 is just backend code. Phase 2 requires the `browser-runner` Deployment
  in the default manifest set and a NetworkPolicy permitting backend→browser-runner:8765;
  browser-runner itself needs **no** egress (data: URLs render locally, minus the CDN
  caveat above — if CDN styling matters in-cluster, allow egress 443 from browser-runner
  or vendor the assets).

## 7. Risks, license and ToS traps

- **License**: MIT — clean. Keep the copyright + permission notice in every harvested
  file (prompts are "substantial portions"); cite commit `d026163f`.
- **Key-in-browser**: only a risk under adoption (stock frontend sends provider keys over
  the WS). Harvest via model_proxy eliminates it. Never wire s2c's settings-dialog
  pattern into owui.
- **Third-party ToS**: `api.screenshotone.com` (URL screenshots) and Replicate (image
  gen) are external hosted services — not harvested, so no exposure; flagging so nobody
  ports them casually into the no-egress lanes.
- **Prompt portability**: these prompts are tuned on frontier models (fable-5, gpt-5.x,
  gemini-3.x). Quality on local Ollama vision models (8 GB dev GPU) is **unverified** —
  the tool-loop discipline (`edit_file` exact-match, "always screenshot once") may exceed
  small local models; recall the Ollama `tool_choice` ceiling gotcha. Verify live per the
  "live test beats stubs" rule before claiming the feature works on local models.
- **CDN dependency** in every generated artifact (single-file HTML by design) vs Harvis
  local-first: decide vendoring vs documented internet requirement.
- **No upstream releases**: future re-syncs are commit-diffs, not version bumps; treat
  the harvest as a fork-and-own of ~700 lines, not a dependency.
- **Verify before trusting**: (a) browser-runner data-URL rendering of a large
  Tailwind-CDN page (the Discord path proves SVG/HTML basics, not CDN-heavy pages);
  (b) whether browser-runner supports a mobile viewport; (c) Kimi K2.5's fidelity on the
  ported replication prompt vs the models it was tuned on.

## 8. Open questions (user-only)

1. Should the Phase 2 self-check loop be on by default for cloud engines (adds ~1 extra
   model round-trip + a render per generation, i.e. latency + token cost), or an explicit
   per-request toggle like Web Research?
2. Is adding a Gemini lane to model_proxy on the table? It unlocks upstream's asset
   extraction and video-to-app modes; without it those stay out of scope.
3. For offline installs: vendor the Tailwind play-CDN script (~100s of KB, served by
   nginx) into generated artifacts, or accept "vision-to-code output needs internet"?
4. Where should the entry point live in the UI — a chat mode (image upload → artifact),
   a Build Space engine option, or both? (Phase 1 backend supports either.)
