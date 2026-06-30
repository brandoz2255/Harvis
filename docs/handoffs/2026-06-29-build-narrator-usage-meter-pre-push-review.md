# Build Result Narrator + Usage Meter — pre-push gap/security review (2026-06-29)

Branch `harvis1.1` (last commit `89ec5326`). Standing rule: **NOT pushed — awaiting explicit go.**

## What shipped this session (all live-verified on :9000, uncommitted)

1. **Build Result Narrator** — after a Build run, the assistant message is a full written analysis
   (Build complete · What you asked · What I did · Files changed *explained* · How to test · Review
   notes) + a `BuildActions` row (View run details · Create PR · Download), raw diff collapsed.
   Backend `build_narrator.py` composes markdown at the `_run_workspace_bg` done-hook → new
   `workspace_runs.analysis_md` (deterministic; AI pass `HARVIS_OWUI_BUILD_NARRATOR_AI` default OFF).
   Renders in the VibeCode thread + the main-chat `WorkspaceRunCard`. Terminal event now persists
   AFTER enrichment (reload-safe; also fixed the pre-existing validator replay gap).
2. **Build usage meter + engine-aware models** — composer model picker filters by `selectedEngine`
   (Claude Code → Claude only, OpenCode/Native/Hermes → Ollama, Codex → GPT/Ollama). Meter shows
   real-time context-window % + tokens + estimated $ (real for API keys; "≈ at API rates" for a
   subscription; "Free · local" for Ollama). `cloud_chat.py` carries ctx/price; `engine_adapter.py`
   `_extract_usage` captures Claude's `result.usage` → persists tokens; the frontend live-ticks via a
   2nd `createWorkspaceStream` token counter. VERIFIED: Claude Code turn → 44,442/200,000 · 22% · $0.136.
3. Earlier same-day: BuildAnalysis facts card (superseded/deleted), `engine` on the session response,
   detector model `qwen3:4b → llama3.1:8b` (compose env, the only compose change).

## Security review — CLEAN (no vulnerabilities)

- **No hardcoded secrets** anywhere in the diff or new files. Compose diff = only the detector model.
- **Credentials**: fetched per-user via `get_verified_engine_auth` (verified-only), injected per-exec
  via `docker exec -e` (list-form subprocess, no shell), killed in `finally`. Never logged.
- **Narrator**: deterministic output embeds only file *names* + line stats — NEVER raw file contents
  or the diff verbatim. The AI pass (off) calls **only local Ollama** (`OLLAMA_URL`), diff truncated
  to 6000 chars — no SSRF/exfiltration. Diff parsing is regex-only (no injection).
- **Live token counter**: the 2nd stream is **ownership-checked** (`workspace_router.py:~2521`,
  `current_user.id` vs DB `user_id`) — a user can't watch another user's run.
- **BuildActions**: Create-PR is human-gated + refuses main/master; Download serves by artifact UUID,
  ownership-checked, and **secret files are denied at write time** (`_is_secret_artifact`,
  `isolation.py:73`) — a captured `.env` can't be downloaded.
- Prices are public list rates — no key leak.
- **Keep `HARVIS_OWUI_BUILD_NARRATOR_AI` OFF by default** (it is).

## Gap/correctness review — no bugs; fail-soft throughout

- No debug cruft (no `DBG`/`console.log`/`print(`/TODO in the new code). No stubs.
- **Terminal-event save reorder is SAFE across ALL lanes** (native/Hermes/orchestrated/OpenClaw-CTF/
  cloud-chat/Kimi): non-terminal events still persist-first; the terminal event is always saved (never
  skipped on error); `_db_complete_run` uses COALESCE so it never clobbers a persisted summary. The
  `analysis_md` two-layer persist (done event + run row) is intentional for replay fidelity.
- Live `_watchLive` counter: aborts the prior stream on run change + `onDestroy` — no leak/double-count.
- Engine model-filter reset (`selectedModel` cleared when invalid for the engine) is correct; no sticky
  recall (acceptable UX).
- Narrator gate `changed_files or diff_text or vibecode_session_id or (agent_id=='claude' and file_count>0)`
  correctly scopes to Build-like runs; CTF/research keep their existing output (intentional).

## Push readiness — READY, after housekeeping

| Item | Status |
|---|---|
| Security | ✅ clean |
| Correctness / regressions | ✅ safe (no bugs, reorder safe) |
| Debug cruft / stubs | ✅ none |
| `front_end/harvis-ui-prototype/` (68M scratch) | ✅ **now gitignored** (was the only real blocker) |
| `front_end/newjfrontend/app/docs/byo-openclaw-setup/page.tsx` (12K) | ⚠️ **DECIDE**: deliverable (commit) or scratch (gitignore)? newjfrontend is still in compose/nginx, so plausibly intentional. |

### Caveats to know (not blockers)
- The whole **uncommitted pile is 21 files spanning several sessions** (cloud-Claude, Hermes-BYO,
  engine adapters, this session). A push commits ALL of it. The reviews found no new problems in it.
- Known pre-existing open item (separate): **cloud-Claude 404/500 partials** (see
  `2026-06-29-hermes-byo-reframe-and-cloud-claude-issues.md`) — not a regression from this work.
- Optional nice-to-haves: `HARVIS_OWUI_BUILD_NARRATOR_AI_TIMEOUT_S` env (default 45s) for slow boxes;
  a comment on the terminal-save reorder. Neither blocks a push.
- **Still recommended before/with a public push: rotate the public `JWT_SECRET`** (carried-over item).

### Verdict
The new code is **production-ready and secure**. With `harvis-ui-prototype/` excluded (done) and a
decision on the one `newjfrontend` docs page, the pile is safe to push **when the user says go**.

## Discord — UP and current
The bot runs **inside the backend container** (started by `main.py` lifespan, legacy path on
`DISCORD_BOT_TOKEN`, len 72). It restarted with the latest code each time the backend was restarted this
session; logs confirm `Discord workspace bot online as Harvis-Bot — slash commands synced · connected to
Gateway`. The detector-model fix also speeds up Discord workspace-task detection. **Message Harvis-Bot to
resume.**
