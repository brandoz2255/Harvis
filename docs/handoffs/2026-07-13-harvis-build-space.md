# Handoff — Harvis Build Space (v1 Foundation) + session state

**Date:** 2026-07-13 · **Branch:** `harvis1.1` (main tree `/home/user/Harvis`)
**Status:** 24 commits ahead of `origin/harvis1.1` + a large uncommitted working set. **Nothing pushed
(standing rule: no push until user verifies E2E).**

---

## Goal (current milestone)

Build the **Harvis Build Space** — a Codex-style coding cockpit where the human drives intent and the
AI owns file edits/shell/tests/commits/PR-prep. **v1 = Foundation (Phases 0-2).** Full plan:
`~/.claude/plans/gsd-ultraplan-phase-harvis-adaptive-ui-iridescent-lightning.md` + Obsidian
`notes-vault/code/harvis/2026-07-13-harvis-build-space-plan.md`. Gap analysis workflow: `wf_49ba0daf-a6b`.

**Locked decisions:** v1=Phases 0-2; AI = local commits + human push/PR; Discord = later; data model =
extend existing + 3 new tables (`code_projects`, `code_file_changes`, `code_pull_requests`).

**⚠️ Security note (do not lose):** native `exec` runs via `create_subprocess_shell` INSIDE the
backend process (`workspace/orchestration/tools.py:286`) in a container mounting the docker socket
(`docker-compose.yaml:313`) → approved shell = host-root. v1 leaves this in place; **Phase 3 (runner
isolation) is the real fix and #1 v2 priority.** Do NOT broaden exec exposure or enable Discord until
Phase 3 ships.

---

## Uncommitted work sitting on harvis1.1 (this + prior sessions)

Group A — **Multi-backend installer** (SHIPPED + config-verified; memory `project_multibackend_installer`):
- `?? install.sh`, `?? docker-compose.cpu.yml`, `?? docker-compose.amd.yml`
- `M build-and-run.sh`, `M README.md`, `M front_end/owui/.dockerignore` (added `/build`)
- `M docker-compose.yaml` — added `owui-builder` service (builds owui in Docker so a fresh clone
  needs no host Node; nginx `depends_on: owui-builder service_completed_successfully`). Runtime-verified.

Group B — **Hermes BYO external engine** (VERIFIED WORKING E2E; memory `project_hermes_byo_verify`):
- `M python_back_end/owui_compat/hermes_chat.py` — `hermes_chat_model_entry(pool,user_id)` shows the
  picker entry when flag on AND (verified external OR sidecar).
- `M python_back_end/owui_compat/router.py` — passes pool+user.id into the above.
- `M python_back_end/owui_compat/hermes_connect.py` — `_probe` hits authed `/v1/models` first (no more
  false-green Verify).
- `M python_back_end/owui_compat/workspace_bridge.py` — `set_workspace_model` skips `hermes-agent` so it
  never pollutes the OpenClaw→Ollama config. (Also did a one-row DB cleanup of `openclaw_llm_config`.)
- Needs `docker restart harvis-backend` to be live; user must add `HARVIS_OWUI_HERMES_AGENT_ENGINE=true`
  to top-level `.env` (safety layer blocks Claude editing `.env`).

Group C — earlier UI work (connectors/routines/sidebar/adaptive-hide/agents-auto): the remaining
`M front_end/owui/...` files (Automations, Customize, ConnectorsPanel, McpShop, McpWizard,
PluginsPanel, surfaces.ts, SettingsModal, Sidebar, ChatItem, VibeCodeNav, adaptive `+page.svelte`,
vibecode `+page.svelte`) and `M python_back_end/vibecoding/sessions.py` (orchestrate-suggest classifier).

> `M docs/handoffs/2026-07-12-connectors-3tier-phase2-schedules.md` is pre-existing; not from this task.

---

## Build Space v1 — status & next steps

- [x] **Phase 0 — integrations status fix. SHIPPED + DEPLOYED (2026-07-13).** Added
  `if (reason.includes('external')) return 'connected';` in `normalizeStatus`
  (`front_end/owui/src/lib/integrations/status.ts`, before the keyword block). owui rebuilt +
  `nginx-proxy` restarted. User visual-confirm: the external Hermes card should now read "Connected"
  (detail drawer still shows the Build-unavailable caveat). Root cause: `capabilities.py:246` emits
  `reason:"external_no_workspace"`; the `status.ts` `includes('no_')` heuristic mis-caught it.

- **Phase 1 — SHIPPED + DEPLOYED + backend-verified (2026-07-13).** Built via Fable workflow
  `wf_aa720cc4-e18` (backend + frontend parallel, verify PASS). Deployed: backend restarted (schema
  DDL applied — `code_projects` + the 5 session columns confirmed present; no startup errors; CRUD
  routes live at `/api/workspace/vibecode/projects`, 401 auth-gated), owui rebuilt + nginx restarted.
  `run_preflight` functionally proven in the live backend (clean+SSH↔HTTPS-match → ok; dirty+require_clean
  → dirty_tree blocker). REMAINING = user visual-confirm the BuildHeader chips on a real Build session +
  an authenticated session-create exercising preflight persistence (can't do authed browser flow headless).
  Deviations (deliberate): local-folder sessions skip preflight; in-place block rolls back its branch;
  lifecycle→ready reset lives in the bg task's completion `finally`. Files: workspace_router.py,
  orchestration/__init__.py, orchestration/preflight.py (new), apis/agent-runs/index.ts,
  agent-studio/build/BuildHeader.svelte, vibecode/+page.svelte.

  Historical (superseded by the line above):
  - [x] **Schema** (`python_back_end/workspace/orchestration/__init__.py`, ORCHESTRATION_SCHEMA_SQL):
    added `code_projects` table (repo registry: repo_url, provider, default_base_branch,
    allowed_base_branches JSONB, branch_prefix) + `uq_code_projects_user_repo`; added
    `vibecode_sessions` columns `project_id`, `work_branch`, `head_sha`, `lifecycle`(DEFAULT
    'created'), `preflight`(JSONB). **NOTE:** used a SEPARATE `lifecycle` column — did NOT touch
    `status` (active/deleted) because `uq_vibecode_active_inplace` keys on `status='active'`.
  - [x] **`orchestration/preflight.py`** (NEW): `run_preflight(repo_path, expected_remote, base_branch,
    require_clean)` → `{repo_ok, remote_ok, remote_url, base_branch, current_branch, head_sha, clean,
    dirty_count, blockers[], ok}`, built on `isolation._run_git`; `normalize_remote()` collapses
    SSH↔HTTPS. **Verified:** ast-parses; `normalize_remote` unit-checked (SSH/HTTPS/.git/ssh:// all
    equal; mismatches→False). Not yet exercised end-to-end (unwired).
  - [ ] **Wire into session create** — in `workspace/workspace_router.py` session-create + turn + PR
    endpoints: call `run_preflight` (expected_remote from the `code_projects` row), block on
    `blockers`, persist `preflight`/`work_branch`/`head_sha`, set `lifecycle` transitions
    (created→preflighting→planning→running→…). Add `code_projects` CRUD endpoints.
  - [ ] **Frontend** — `BuildHeader.svelte` meta strip: `repo · base→work branch · SHA · clean/dirty`
    chips + lifecycle stepper; add `work_branch`/`head_sha`/`lifecycle`/`preflight` to the
    `VibecodeSession` type in `apis/agent-runs/index.ts`.
  - **Deploy:** `workspace/` IS bind-mounted → `docker restart harvis-backend` applies both the code
    AND the idempotent schema DDL (runs on lifespan). Frontend = `npm run build` → restart nginx.
- **Phase 2 — SHIPPED + DEPLOYED + backend-verified (2026-07-13).** Fable wf `wf_dc825063-851`.
  READ-ONLY browse endpoints `/vibecode/session/{id}/files` + `/file` (ownership-scoped, traversal-guarded
  via `validate_agent_path` — proven: `../../../etc/passwd` rejected; secret files masked); git-status diff
  (`collect_changed_files_status` in isolation.py, adds D/??); durable approvals (`workspace_pending_approvals`
  table + `vibecode_sessions.approved_patterns`; reason in the approval_request event; approve-for-session
  consulted in authz gate). Frontend: full RO tree fed to WorkspaceFileRail, real content viewer in
  WorkspaceMainPanel, modal shows reason + Approve-for-session. **Verify caught + I fixed** a real bug:
  resolveAction sent `scope` in the body but backend reads it from the query string (`?scope=session`) —
  fixed in agent-runs/index.ts. Deployed: schema applied (table + column confirmed), endpoints 401-wired,
  owui rebuilt + nginx restarted. Remaining = user visual-confirm (browse/view/approve-for-session in a
  real authed session). Deviation: secret-named files return content:'' + secret:true.

  Build Space v1 (Phases 0-2) COMPLETE. Now going through v2 phases 3→4→5→6 (user: "go through all").
- **Phase 3 (SECURITY) — SHIPPED + DEPLOYED + live-smoked (2026-07-13).** Fable wf `wf_f928e90a-356`,
  VERDICT PASS. AI session exec now runs in a hardened per-session container via
  `terminal_container.exec_isolated` (image `harvis-repo-sandbox:local`, net `harvis_repo-sandbox`,
  cap_drop=ALL, no-new-privileges, pids=256, user 1001:1001, single mount, **NO docker.sock** — confirmed
  in-container). Flag **`HARVIS_BUILD_ISOLATED_RUNNER` (default ON, instant rollback)**; **fail-closed** (no
  silent in-process fallback; missing image/workspace → clear EXEC ERROR). Scoped to vibecode sessions only
  (runner.py passes session_id only from session_turn.py; orchestrator unchanged). permission_mode wired into
  harvis_exec.py + harvis_jobs.py. Files: terminal_container.py, orchestration/{tools,runner,authz}.py,
  harvis_exec.py, harvis_jobs.py. Deployed via backend restart (runner image + network present → no
  fail-close). **⚠ BEHAVIOR CHANGE (always-on, not flag-gated):** `/api/harvis/exec` + `/api/harvis/jobs`
  now 403 med/high commands under default 'ask' (was: bypassed the gate) — may regress Dev Console one-shot
  exec; relax by gating only 'high' or defaulting that path to auto-accept if needed.
- **Phase 4 — SHIPPED + DEPLOYED + verified (2026-07-13).** Fable wf `wf_3ac09f35-e03` (interrupted by a
  session limit — build agents landed edits but died before verify; a follow-up Explore verify + my fixes
  completed it). Backend: apply_patch (tracked → `code_file_changes`, path-guarded), git_commit (LOCAL-only,
  refuses main/master, never pushes — in tools.py; risk-gated), PR persistence UPSERT into `code_pull_requests`
  (by session_id+head_branch), GET `/changes` + `/pull-requests`, repo_manager `_resolve_pr_base`
  (code_projects.default_base_branch → GitHub default → main). Frontend: PrDrawer.svelte (checklist-gated,
  human-submit) NOW wired into +page.svelte (import/state/headerCreatePR/BuildActions onCreatePr/mount). **Fixed
  2 bugs the interrupted build left:** BuildActions.svelte orphaned inline-PR-form (deleted — was breaking vite
  build), and `base` missing from VibecodeCreatePrRequest (drawer target-branch was dropped — added + wired).
  Deployed: both tables applied, endpoints 401-wired, owui rebuilt + nginx restarted, no startup errors.
- **Phase 5 — BACKEND SHIPPED + DEPLOYED; frontend card corrected; ONE surfacing follow-up open.** Fable wf
  `wf_599e3d23-30a`. Backend (verified live): `POST /api/harvis/jobs/{id}/retry` (ownership-scoped, 409 on running,
  re-gates via authorize_action, relaunches same command as new job), `workspace_jobs.timeout_secs` column
  (idempotent ALTER in main.py + workspace_schema.sql), `list_jobs`/`GET /jobs/{id}` return command+exit_code+
  timeout_secs+log_tail (rebuilt from workspace_events), `tool_result` events now carry `tool` name. Card fixes I
  applied post-verify: BackgroundTaskCard rollup now reads `tool_result.output.exit_code` + `text||content` (was
  only terminal_output/content → never populated); canRetry now includes exited/reaped/killed. **OPEN FOLLOW-UP
  (#1, a UX decision — NOT a bug):** BackgroundTaskCard in the Build panel is fed session TURNS, not
  `/api/harvis/jobs` records, so the new command/exit/retry surface is unreachable THERE (jobs render in the
  Console with its own markup). To light it up: either feed `/api/harvis/jobs` into the Build Tasks panel, or port
  these enhancements to the Console page. Also minor: runFormat.ts statusDot/statusLabel don't map exited/reaped/
  killed (show gray/"Pending") — cosmetic.
- **Phase 6 — SHIPPED + DEPLOYED + LIVE (2026-07-13).** Fable wf `wf_6117d927-7d9`, VERDICT PASS. `/harvis-code`
  command group (start/status/prompt/diff/tests/stop/commit/pr) in `python_back_end/integrations/discord_workspace_bot.py`
  (+790 lines, ONE file; /model /engine /agents byte-identical — no regression, proven by live module exec).
  Thread-per-session (id embedded in thread name → survives restart), PERSISTENT custom_id-routed buttons
  (Approve/Deny/Diff/Commit/PR/Stop), REAL user mapping (`resolve_user_id`, never DISCORD_DEFAULT_USER_ID),
  reuses the vibecode backend (create/turn/diff/create-pr/approve). Runs in the BACKEND (DISCORD_WORKSPACE_BOT_LEGACY_ENABLED=true,
  main.py:854). Config in docker-compose.yaml backend env (IDs not secret, `${VAR:-default}`):
  HARVIS_CODE_CHANNEL_ID=1526412856990502923, HARVIS_CODE_GUILD_ID=1491563310699516044, no approver role (anyone).
  Deployed via `docker compose up -d backend` (env change needs recreate, not restart). Logs confirm:
  "harvis-code: enabled … synced". **Remaining = user E2E test `/harvis-code start` in the channel** (can't drive Discord headless).
  Deviations: approver-role holders still need session ownership to approve (backend endpoints are ownership-scoped);
  commit/PR buttons open a Discord modal (doesn't survive restart mid-open; slash cmds always work); `tests` = a turn with a fixed brief.

**+ Agent Review Conversation (opt-in) SHIPPED + DEPLOYED (2026-07-13).** Fable wf `wf_52d51972-e0c`
(session limit killed the backend agent mid-run — but it landed most of it; frontend agent finished; I
completed the tail). `orchestration/review.py::run_review_conversation` = coder↔reviewer alternate ≤3
rounds, reviewer VERDICT: APPROVED ⇒ `review_status='agreed'`, cap/error ⇒ 'needs_human' (fail-open).
New session cols `review_enabled`(default FALSE)/`review_status`(default 'off'); new `agent_message` event
(runner ev()) rendered as chat bubbles in AgentTimeline + Discord thread. Trigger: web `startVibecodeSessionReview`
(POST /vibecode/session/{id}/review) + `/harvis-code review`. PR gate: create_pr 409s when review_enabled AND
status∉('agreed','off') UNLESS `override:true` (human always wins); review_enabled=FALSE ⇒ zero change.
**Gotcha I hit + fixed:** I added a duplicate `/harvis-code review` command (agent already added `code_review`
as `code_review`, which my `async def review` grep missed) → `CommandAlreadyRegistered` DISABLED all of
/harvis-code for one restart → removed my dup, re-registered clean. Deployed + bot re-synced OK. Remaining =
user E2E test (`/harvis-code review` or web Start-review).

**+ Review round cap → 5** (env `HARVIS_REVIEW_MAX_ROUNDS`, default 5) — review.py.

**+ Review-on-GitHub mode SHIPPED + DEPLOYED (2026-07-13, hand-built on OPUS — Fable credits ran out).**
New `orchestration/review_github.py` (fail-soft GitHub adapter: resolve_owner_repo, push_session_branch
[token scrubbed from logs + remote reset to token-less URL], open_or_reuse_draft_pr [draft:true, 422→reuse],
post_comment, mark_ready [GraphQL markPullRequestReadyForReview]). `review.py::run_review_conversation` gains
`mode='thread'|'github'` + `_setup_github_review`/`_upsert_review_pr` helpers + 4 hooks (draft-PR open →
reviewer critique posts a labeled PR comment → coder pushes fix + posts a PR comment → on APPROVE mark ready +
persist code_pull_requests 'open', else needs_human comment). Uses labeled PR comments NOT formal reviews
(GitHub forbids self-approve). `VibecodeReviewRequest.mode` threaded via `_start_workspace(vibecode_review_mode)`
→ `_run_workspace_bg` call. github mode rejects sessions w/o repo (400). Discord `/harvis-code review-github`
(via `_code_run_review(mode='github')`). Frontend: `startVibecodeSessionReview(mode)` + PrDrawer "Review on
GitHub" button (were on disk from the credit-killed Fable frontend agent — built + deployed). VERIFIED: all
parse, imports clean in live backend, /harvis-code registers clean, no worktree leak. REMAINING = user E2E:
`/harvis-code review-github` on a session with changes → watch the agents converse on a real draft PR.

**✅ ALL 6 PHASES (0-6) SHIPPED + DEPLOYED this session.** Nothing pushed (harvis1.1). Open: user visual/E2E confirms;
Phase 5 #1 (jobs-into-Build-panel UX decision); commit/push the whole harvis1.1 tree when ready (untracked new files:
preflight.py, PrDrawer.svelte + the Phase 6/etc. edits — `git add` them).

  ⚠ NOTE: a session limit can kill a workflow mid-run; the edits usually PERSIST on disk but the agent's
  self-report + verify are lost → always re-verify the on-disk state (git status + a fresh Explore verify) before
  deploying an interrupted phase. Untracked new files (PrDrawer.svelte, preflight.py) must be `git add`ed at commit.

v2+ roadmap (NOT now): Phase 3 isolated runner (security), Phase 4 commit/patch/PR-drawer, Phase 5
tasks polish, Phase 6 Discord. See plan file.

---

## How to resume / deploy / verify

- Work on the **main tree** `/home/user/Harvis` (branch harvis1.1), NOT the
  worktree (stale). Each phase = one Fable-5 build→verify Workflow (`model:'fable'`).
- Deploy owui UI: `cd front_end/owui && npm run build` (or the new `owui-builder`) → `docker restart
  nginx-proxy`. Backend (bind-mounted `owui_compat`): `docker restart harvis-backend`. Access
  `http://localhost:9000`.
- After a phase lands, user runs `/code-review ultra` on the branch (billed, user-triggered — Claude
  can't launch it).
- DB: `docker exec pgsql-db psql -U pguser -d database`.

## Gotchas / failed attempts (don't repeat)

- Explore agents may report **worktree** paths (`.claude/worktrees/...`) — always re-verify against the
  **main tree**; line numbers can drift.
- Editing top-level `.env` is **blocked** by the safety layer (holds secrets) — hand `.env` edits to the
  user.
- `docker compose config`: a plain `devices: []` does NOT clear a base nvidia reservation — needs
  `!reset` (that was the multi-backend gotcha).
- Approval state lives in an **in-memory `_workspaces` dict** (`risk.py`) — restarts silently deny;
  Phase 2 must persist it.

## Standing constraints

No push until user verifies E2E · never commit secrets/`.env` · skills need human `supported` verdict ·
`authorize_action` is the sole dispatch authority · each build phase = one Fable-5 build→verify Workflow ·
no keyword-based auto model routing / no silent orchestration.
