# Handoff — 2026-07-16 (EOD) — next steps: push decision · media-ingestion · UI polish · GBrain

> Written to myself for the next session. David logged off tired after handing over an Instagram
> research batch. This is the resume point. Companion to the commit handoff
> `2026-07-16-review-system-buildspace-discord-commit.md` (that one documents WHAT shipped; this one
> is WHAT'S NEXT).

## Where things stand (one paragraph)
The entire Build/VibeCode working set is now **committed locally** as `3fd5d0a5` on **`harvis1.1` in the
MAIN tree** `/home/user/Harvis` (NOT the worktree — never build in the worktree).
Branch is **ahead 25 of origin, working tree CLEAN, NOTHING PUSHED**. The review system + Build Space v1 +
Discord `/harvis-code` + run/review UI were **E2E-verified 2026-07-16** on gemma4:12b (build ran, filename
lineup rendered, pirate thread-review settled APPROVED in 1 round, app stayed responsive, the removed
"Open Run" button confirmed gone). Then David handed over an Instagram clip batch which I ingested into the
notes vault and researched **GBrain**. No Harvis code was touched after the commit.

## THE decision waiting for David (ask, don't act)
**Push or keep holding?** The standing rule has been *"no push until the user verifies E2E"*
([[feedback_no_push_until_verified]]). David has now verified E2E. So the gate *may* be lifted — but he
never said "push," and pushing 25 commits to `origin/harvis1.1` is outward-facing + irreversible-ish.
**Do NOT push autonomously. Ask first**, and mention the open follow-ups below so he can decide whether to
fix any before pushing. Note also: JWT_SECRET's old value still lingers in git history (full purge deferred,
[[project_first_push_next]]) — not re-introduced by this commit, but relevant if the branch ever goes public.

## Next actionable work (ranked — all grounded in the real codebase this session)
1. **Media-in-chat ingestion (highest value / lowest build — ~80% already exists).** David's exact ask:
   Harvis chat should do "odd tasks" — read YouTube/Instagram links + mp3/mp4 files. The audit found the
   primitives already there: Whisper already takes **mp4** (ffmpeg auto-decodes) at
   `python_back_end/model_manager.py:1439` `transcribe_with_whisper_optimized`; a **YouTube transcript
   extractor exists twice** (`research/extract/youtube.py:33`, deps `youtube-transcript-api`+`yt-dlp`
   present); the web-article extractor is `research/extract/router.py` `ExtractionRouter.extract_url`; the
   chat injection choke point is `owui_compat/chat_completion.py:401` `run_chat_completion` (`_inject_files`
   at :87 is the pattern to copy); the SSRF guard is `tools/openclaw_proxy.py:146` `_validate_url`.
   **Phase 1 = add one `_inject_media(request, owui_body, user_id)` beside `_inject_files`**: detect
   audio/video attachments (owui_files.content_type) + http(s) URLs in the last user message → transcribe
   via existing Whisper / fetch article text via existing extractor → SSRF-guard every URL → threadpool,
   char-cap, fail-soft. Phase 2 = YouTube (wire the existing extractor). Phase 3 = Instagram (greenfield,
   flag-gated, public-only). Phase 4 = mp4 keyframes → existing vision path. Full spec + phases + gaps in
   the vault: `notes-vault/projects/Media-in-chat ingestion.md`.
2. **Harvis UI polish pass (cheap credibility — 7/9 already done).** The owui frontend audit found it's
   already substantially de-vibecoded (bespoke favicon, "Harvis" title `app.html:125`, self-hosted variable
   fonts `app.css:3-31`, Tooltip in ~167 files, blue/cyan not purple theme, restrained font-weight scale).
   Two real gaps: (a) loading states are spinners/pulse/live-lineup, **not content-shaped skeleton loaders**;
   (b) no external icon lib, but newer `agent-studio/build/*` hand-rolls inline `<svg>` instead of reusing the
   in-house **178-component icon set** — inconsistent in Harvis' own surfaces. Plus a live **devtools
   console/perf pass** at localhost:9000 (unknown, needs a real browser check via claude-in-chrome). Details:
   `notes-vault/projects/Harvis UI polish pass.md`.
3. **GBrain decision (strategic — no build yet).** Garry Tan's open-source **OpenClaw/Hermes agent memory
   brain** (`github.com/garrytan/gbrain`, MIT): markdown-backed, zero-LLM typed-edge graph from wikilinks,
   hybrid search + a `think` synthesis mode, MCP-native (`claude mcp add gbrain`), overnight consolidation.
   It's the productionized [[LLM-wiki pattern]] on Harvis' *exact* runtime (OpenClaw + Hermes). Decision to
   surface: **adopt** (wire it in as Harvis' memory layer over MCP) / **borrow** (steal the zero-LLM graph +
   `think` mode into notes-vault/ruflo) / **both**. Full writeup: `notes-vault/wiki/entities/GBrain.md`.

## Open follow-ups surfaced by the commit's diff analysis (noted, NOT fixed)
- **Schema is idempotent-init, not a versioned migration.** 4 new tables (`code_projects`,
  `workspace_pending_approvals`, `code_file_changes`, `code_pull_requests`) + ~9 `vibecode_sessions` columns
  come from init strings in `orchestration/__init__.py` (+ `main.py` for `workspace_jobs.timeout_secs`).
  **Confirm they apply on the deploy target before those endpoints are exercised** or `workspace_router`/
  `review.py` 500 on a fresh DB.
- **`review_github.push_session_branch`** uses plain `git push -u --force` (not `--force-with-lease`) and
  refuses only literal `main`/`master`; the auth token is embedded in the origin URL and reset right after,
  but the reset is **not in a `finally`** (exception between set-url and reset could leave the authed remote
  URL on disk). Worth hardening before the GitHub review mode sees real repos.
- **Default-ON surface changes:** `HARVIS_OWUI_EXTERNAL_ENGINES` now defaults `true`; `docker-compose.yaml`
  ships non-empty default Discord IDs (channel effectively "set", approver role empty = anyone in channel) —
  the `/harvis-code` path could be live against real IDs unless overridden. Accept consciously.
- **Dead/unmounted code:** `PluginsPanel.svelte` rewritten 56→644 lines but both mounts removed (0 refs now);
  `McpShop`/`McpWizard` orphaned; Adaptive Space hidden behind a placeholder; `liveCompletionTokens`
  permanently 0. Decide keep-vs-remove.
- **Minor:** verdict-parse regex duplicated in `ThoughtStream` + `AgentTimeline` (extract a shared helper);
  `list_jobs` computes `log_tail` with an N+1 query; `BrowserPanel` iframe uses `allow-scripts
  allow-same-origin` on an arbitrary user URL (fine as a local preview, noted).
- **Telemetry mislabel (cosmetic):** custom reviewer per-agent models ARE honored (`review.py:252-272`,
  `:383`), but `root_ev` (`review.py:280`) stamps the run's base-default model (`llama3.1:8b`) onto every
  event envelope — so a custom reviewer's `agent_message` mislabels its model in telemetry/UI. Clean fix =
  stamp the emitting reviewer's `_rv["model"]`.

## Parked (David said "push to the side")
- **Remote dev control** — `claude --remote-control` already does phone-driven same-session control (zero
  build); `stream-json` bridge for Discord; session-resume for durability. Plan:
  `notes-vault/code/harvis/2026-07-15-remote-dev-control-omnirouter-nexus-plan.md`.
- **OmniRouter** — free rotating OSS API keys behind Harvis `model_proxy`. Vault spark `notes-vault/projects/OmniRouter.md`.
- **Nexus** ("nexus os") as the productization/hosting home for the above.

## Where the research lives (notes vault, `notes-vault`)
- Raw (immutable): `raw/clips/2026-07-15-instagram-jarvis-ui-agent-clips.md` (**batch 1 of N — more clips
  coming**; new batches append here + extend the digest).
- Digest: `wiki/sources/instagram-agent-ui-clips-2026-07-15.md`. Topic synthesis: `wiki/topics/Chatbot vs
  agentic OS.md`. Concepts + entities under `wiki/`. Two sparks + GBrain under `projects/`/`wiki/entities/`.
- `index.md`, `projects/_Pipeline.md`, `log.md` all updated 2026-07-16.

## Operational reminders (don't relearn these)
- **Main tree** `/home/user/Harvis`, branch `harvis1.1`. The session cwd is a **stale
  worktree** — never build there. All git via `git -C <main-tree>`.
- **Deploy to test:** backend (bind-mounted) = `docker restart harvis-backend`; owui frontend = `cd
  front_end/owui && npm run build` → `docker restart nginx-proxy`. App at **http://localhost:9000** (nginx).
- **Test model = gemma4:12b** (it's a THINKING model — reasoning + content channels; never cap a
  review/critique call below ~4k tokens).
- **See the laptop UI = claude-in-chrome** (the Pop!_OS box). **computer-use MCP = David's WINDOWS box** —
  don't screenshot the Harvis UI with it.
- **DB:** `docker exec pgsql-db psql -U pguser -d database` (container `pgsql-db`). Useful tables:
  `vibecode_sessions`, `workspace_runs`, `workspace_events` (FK `workspace_id`→`workspace_runs.id`),
  `owui_subagents` (pirate-agent id `71537ef1-5c7f-45de-a047-c01353553e40`, gemma4:12b).
- **Credential guard** blocks reading the raw JWT into the transcript — probe the backend via in-page
  `fetch` (claude-in-chrome `javascript_tool`, uses `localStorage.token`) instead.
- Review start endpoint (thread mode = no PR side-effect): `POST /api/workspace/vibecode/session/{id}/review`
  body `{mode:'thread', reviewer_ids:[...]}`.

## First move next session
Greet David, confirm which of the three ranked items (or the push decision) he wants first. If he says
"keep going" with no steer, **start Media-in-chat ingestion Phase 1** (highest value, mostly wiring) — but
ask about the push first, since E2E is now verified and 25 commits are sitting local.
