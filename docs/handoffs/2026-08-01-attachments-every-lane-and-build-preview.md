# Handoff — attachments on every Build lane, and the Build preview that was never wired

**Date:** 2026-08-01 · **Branch:** `harvis1.2` (main tree) · **State:** built, deployed, verified
live, **nothing committed** (82 dirty paths)

---

## What the user asked for

Three asks, in order, across two sessions:

1. *"can you just make it so the engine models like anthropic and kimi can do the task too it has to
   run on everything"* — an attachment (a screenshot) had to reach the model on **every** Build
   engine, not just the native Ollama runner.
2. *"so it still did the same issue, saying the screenshot could not be read. also it says still
   working when its finished so fix that too."*
3. *"still says the working icon above the task that is finished ... the preview did not move to the
   side like how it should have but instead in the main chat, and when i press full it doesnt move
   over to the side like it should or take over the whole screen"*

---

## 1. Attachments on every lane

Before this, only the native lane could see an attachment. The CLI lane (`engine_adapter.py`) had
**zero** attachment handling, so a screenshot arrived at the model as the literal text
`/api/v1/files/<id>/content` — and run `67155356` burned 90 seconds and 10 tool calls hunting for it
(`curl` exit 127, `ECONNREFUSED 127.0.0.1:80`, a port scan) before honestly reporting blocked.

**Two delivery mechanisms over one audited byte resolver.**

- `vision_to_code/attachments.py` — `resolve_attachment_bytes` is the single byte path:
  `data:` URI · `file_id` · `path` inside `IMAGES_DIR` only · Discord CDN allowlist only.
  `build_image_parts` was refactored onto it (−30 duplicated lines). New: `materialize_attachments`
  and `staged_attachment_brief`.
- **API lanes** (Moonshot, Ollama local/cloud, subagents, parallel) get real
  `{"type":"image_url","image_url":{"url":"data:…"}}` parts via `kimi_workspace._user_message`.
- **CLI lanes** (`run_external_engine_adapter`, `run_claude_chat_workspace`) get **real files on
  disk** under `harvis-attachments/` in the workspace, with their relative paths at the top of the
  brief.
- **Native lane** (`session_turn.run_vibecode_turn`) additionally stages **non-image** attachments
  (PDF/CSV/source) into the working tree, where `read_file` actually reaches them.

**Why files rather than URLs for the CLI lanes.** An engine sidecar mounts `/data/artifacts` and
nothing else — no route to the Harvis API, no uploads volume, often no `curl`. The shared
`artifact_data` volume *is* the delivery mechanism: bytes the backend writes appear to the CLI at the
identical path.

### The bug that survived the first pass — Harvis has TWO upload stores

`POST /api/uploads` writes `IMAGES_DIR` (`/app/images`) with a `<file_id>.meta.json` sidecar. The
**chat/Build composer** uploads through the OWUI-compat `POST /api/v1/files/` (`main.py:5647`), which
writes `OWUI_FILES_DIR` (`/app/owui_files`) as `<uuid><ext>` and keeps the authoritative row in the
Postgres `owui_files` table.

The resolver knew only the first. So a real Build attachment reported *"no longer on disk"* while its
bytes sat in the other directory. `_resolve_file_id` now falls back to `_owui_stored_file`, which
regex-validates the id and confirms the resolved path is a direct child of the directory — the id is
client-supplied and would otherwise be a traversal primitive.

A second, quieter defect made this take a whole extra round: the staging status line said only
*"No attachment could be staged · 1 unavailable"* — the count without the reason. That is what sent
the investigation into CLI behaviour when the cause was already known at that point. It now names the
reason.

### Verified

- Staging defangs traversal (`../../../../etc/evil.png` → `harvis-attachments/evil.png`), refuses
  SSRF (`169.254.169.254`), refuses paths outside `IMAGES_DIR`, and reports each refusal in English.
- All four sidecars — `harvis-claude-code`, `harvis-codex`, `harvis-opencode`, `harvis-hermes-agent`
  — read the staged PNG at the exact briefed path, correct size, PNG magic `89 50 4e 47`.
- The exact failing `file_id` now resolves in-container to 95,641 bytes / `image/png` / no error.
- **Live:** run `66661e05` (kimi-code/k3, done) ended with the model saying *"I can see the
  screenshot clearly"* and rebuilding the page from it. That is the E2E proof.

---

## 2. "Working…" over a finished task

The backend was honest the whole time — `workspace_runs.status = 'done'`, `completed_at` set, and
`GET /vibecode/session/{id}` returns it verbatim. Three client-side defects, fixed in two rounds:

1. `schedule()` in the Build page read the reactive `anyRunning`, which is a frame behind right after
   `loadSession()`. A just-started turn armed its next poll 30 s out instead of 2 s. Now it computes
   from `turns` directly.
2. The page subscribed to the run stream but only read `verify_preview`, ignoring the authoritative
   terminal `done`/`error`/`cancelled` phase that `runStream.ts` already sets and flushes
   immediately. Now the subscription calls `loadSession().then(schedule)` once per run id.
3. **The one that actually survived to the user.** `RunView.svelte` derived
   `running = phase === 'connecting' || phase === 'running'`, and `phase` starts at `'connecting'`.
   A view mounted on an *already-finished* run whose SSE replay closes without a terminal event never
   leaves `'connecting'` — it pulses forever. `loadMeta()` had the authoritative `status` the whole
   time and never fed it in. `running` is now false whenever the server status is terminal.

---

## 3. The Build preview

**It was never implemented.** `WorkspaceMainPanel.svelte` carried `const BUILD_FILE_PREVIEW = false`
and a body reading "No preview available yet." — so a run's artifact only ever rendered inline in the
chat thread via `RunArtifacts`.

Now:

- `WorkspaceMainPanel` takes a `hasPreview` prop and a `preview` slot. The tab appears only when a
  preview exists, so it is never a permanent empty promise.
- The Build page derives `hasPreview` from `artifacts.some(a => a.artifact_type === 'file')` and
  renders `RunArtifacts mode="preview" bare fill` into the slot.
- Rising-edge auto-surface: the first time a run produces a preview, the dock opens, the File panel
  turns on, and the Preview tab comes forward. After that the dock is left alone so switching tabs by
  hand isn't undone on the next poll.
- The thread's run views now pass `artifactsMode="changes"`, so the preview stops appearing twice.

**⤢ Full was guaranteed inert.** That button is only rendered on *running* turns, and
`headerOpenRunId` refuses running turns outright — the run inspector pegs the main thread on a live
run (a pre-existing gate, cause still unknown). So in the chat it could only ever produce a toast.
It now docks the live run's output to the side instead. The Preview tab has its own ⤢ Full that
blows the artifact up over the whole page, closable with Esc or ✕.

---

## Files touched

| File | Change |
|---|---|
| `python_back_end/vision_to_code/attachments.py` | single byte resolver; OWUI upload store; materialize + brief |
| `python_back_end/workspace/orchestration/engine_adapter.py` | `_stage_attachments`; honest skip reasons |
| `python_back_end/workspace/orchestration/session_turn.py` | non-image staging on the native lane |
| `python_back_end/workspace/kimi_workspace.py` | `_user_message` multimodal parts |
| `python_back_end/workspace/workspace_router.py` | threads `attachments` through every dispatch |
| `front_end/owui/src/lib/agent-studio/RunView.svelte` | server status beats stream phase; `artifactsMode` prop |
| `front_end/owui/src/lib/agent-studio/build/WorkspaceMainPanel.svelte` | real Preview tab (`hasPreview` + slot) |
| `front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte` | terminal-phase refresh, poll fix, preview wiring, fullscreen overlay, `openRunSide` |

**Deploy:** mounted Python → `docker compose restart backend`. Frontend → `npm run build` in
`front_end/owui`, then `docker compose restart nginx`.

---

## Known limits (stated, not hidden)

- The side Preview always shows the **latest** run's artifact, not the artifact of whichever older
  turn you expand. Fixing that means threading a per-turn run id into the dock.
- ⤢ Full still cannot open the run inspector on a *live* run. That gate predates this work and its
  cause (the inspector freezing the main thread on a live run) is unresolved.

## ⚠ Still open — security

Run `67155356` seq 14 ran `env | grep -iE "api|host|url|port|file"` and that `tool_result` is stored
**in plaintext** in `workspace_events`, including a live `ANTHROPIC_API_KEY=sk-kimi-…` and
`ANTHROPIC_BASE_URL`. **Rotate that key**, and redact env output from persisted CLI events.

---

## Next direction (user, 2026-08-01)

> *"in the future were gonna work on getting full recordings working so it can do multiple areas of
> code like how the screenshot to code repo really works"*

Screen **recordings** as input, not just a single screenshot — so one capture can drive several
areas of a codebase rather than one page. Nothing is designed or scoped for this yet.

**Do not count `mcp-servers/sentrysearch` as a head start.** Verified 2026-08-01 by building and
running it: `server.py` prints one JSON status line and then `sleep(3600)` forever. It exposes **zero
MCP tools**, has no embed pipeline, no index, no query path. Its only wiring into Harvis is a
storefront catalog card (`owui_compat/mcp_catalog.py:551`). It is a placeholder reserving a name, not
a video-search implementation — a recordings feature starts from nothing there.

The real adjacency is `HARVIS_VISION_SELF_CHECK_ENABLED`, which gates the iterate-and-verify loop
(render → screenshot → compare → fix) that a multi-area generator would want. It is off and has never
run.
