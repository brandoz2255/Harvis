# Handoff — VibeCode cumulative multi-turn sessions (Phases 1–3 SHIPPED) — 2026-06-21

## Goal
Rebuild `/harvis/vibecode` into a Claude-Code-desktop **cumulative multi-turn coding
conversation** (user decisions: "Multi-turn" + "Cumulative"). Plan = the 4-phase design in
`.claude/plans/noble-noodling-pnueli.md` (top entry). Memory pin =
`project_vibecode_cumulative_sessions` (full file list + gotchas there). SUPERSEDES the
single-run model (`project_vibecode_claude_desktop`).

## State: Phases 1+2+3 = the WHOLE clone-mode feature — DONE, verified E2E, DEPLOYED on :9000
Uncommitted on `harvis1.1`, **NOT pushed** (standing rule: no push until the user says go).
Backend bind-mounted (`docker restart harvis-backend`, schema on lifespan); owui = `npm run
build` in MAIN `front_end/owui` → `docker restart nginx-proxy`. Test sessions + the temp demo
origin on `/tmp/harvis-attach-test` were cleaned up (0 sessions, 0 on-disk dirs, origin=none).

- **Phase 1** — persistent per-session git clone under `/data/artifacts/harvis-vibecode-sessions/<id>`,
  turns accumulate vs a fixed `base_sha`, conversation thread, `source='vibecode'` kind, per-session
  `asyncio.Lock`. Verified: cumulative read (turn2 builds on turn1), reload-from-DB, deterministic
  one-clone-per-session.
- **Adversarial review** (29-agent workflow) — 8 real bugs, 7 FIXED + verified: HIGH attached-repo
  allowlist gap (now `_is_allowed_repo` 403 in BOTH `create_vibecode_session` AND `/launch`); R2 leak
  ×2 (`/history` + `/artifacts` now `source IS DISTINCT FROM 'vibecode'`); disk+lock leak (the new
  `DELETE` endpoint); 2 frontend (stranded-user goto-in-catch + `loadSession` staleness guard).
  DEFERRED: ~4s composer re-enable lag (self-heals; serialization intentional).
- **Phase 2** — autoname (`POST /vibecode/session/{id}/autoname`, copies `onb_autoname_notebook`,
  LLM title+emoji from first turn, deterministic fallback), rename (`PATCH`), delete (`DELETE` =
  clone teardown + lock release + soft-delete), VibeCodeNav global-nav block (New session / Agent
  Studio / Automations / Customize) above the session list, generic pins hidden in code mode
  (`Sidebar.svelte:1177`). Verified: 🔒/🌓 autonames, inline rename, nav, hide-pins.
- **Phase 3** — shared `_open_pr_from_diff(...)` helper (refactored `create_pr_for_run` to it);
  `GET /vibecode/session/{id}/diff` (live accumulated diff vs base_sha + `has_github`);
  `POST /vibecode/session/{id}/create-pr` (ONE PR from the live session diff, HUMAN-only, refuses
  main/master); `lib/agent-studio/VibecodeSessionDiff.svelte` card (accumulated diff + +N/−M +
  human-gated Create-PR confirm). Verified in UI on an attached `harvis · master` session — card +
  Create-PR button + confirm UI; **did NOT open a real PR** (the user's deliberate click).

## Files (all main repo)
- Backend: `python_back_end/workspace/orchestration/{isolation,__init__,runner,session_turn}.py`,
  `python_back_end/workspace/workspace_router.py`.
- Frontend: `front_end/owui/src/routes/(app)/harvis/vibecode/+page.svelte`,
  `front_end/owui/src/lib/components/layout/Sidebar/VibeCodeNav.svelte`,
  `front_end/owui/src/lib/components/layout/Sidebar.svelte` (line ~1177 hide-gate),
  `front_end/owui/src/lib/apis/agent-runs/index.ts`,
  `front_end/owui/src/lib/agent-studio/VibecodeSessionDiff.svelte` (new).

## Phase 4 — DONE (in-place + permission ladder) — SHIPPED + verified + reviewed 2026-06-21
ALL FOUR PHASES COMPLETE. In-place isolation (opt-in) + the Claude permission ladder are built,
verified E2E (backend + UI), and adversarially reviewed (7 findings, all fixed). Details now live in
the memory pin `project_vibecode_cumulative_sessions` (Phase 4 + review-fixes + deploy-gotchas sections).
Key deploy notes for in-place: `HARVIS_ATTACH_REPO` must be set in `.env` (else mounts default to the
main repo); the RW-mounted repo must be writable by container uid 1001 (chmod/group-own); recreate the
backend (not just restart) when the `:rw` mount changes. Still uncommitted on `harvis1.1`, NOT pushed.

### (Original Phase 4 plan — for reference; now implemented)
- **4A backend** — `"inplace"` isolation mode (`create_inplace_session_workspace`: clean-tree check →
  `git checkout -b vibecode/<session>` on the REAL repo at a parallel `:rw` mount; `workspace_path` =
  the real repo; `base_sha` = HEAD; teardown = checkout base + `branch -D`, NEVER rmtree the repo).
  `collect_diff` reuse: extend the `in ("session","inplace")` branches (diff vs base_sha). `docker-
  compose.yaml:250`-area: add a parallel `${HARVIS_ATTACH_REPO}:/data/attached-repos-rw/harvis:rw` +
  `HARVIS_ATTACHED_REPOS_RW`. `_is_allowed_repo_rw` allowlist. `create_vibecode_session` accepts
  `isolation_mode`('session'|'inplace') + `permission_mode`. **One-active-inplace-session-per-repo
  guard** (two in-place sessions on one repo fight over the working tree). NOTE: Create-PR needs NO new
  code — the existing `/vibecode/session/{id}/create-pr` works for inplace (collect_diff + `_open_pr_
  from_diff` clones the real repo + applies the live diff).
- **4B backend** — greenfield `orchestration/risk.py`: `classify_action_risk(tool,args)->low|med|high`
  (read=low, edit=med, exec→`rm -rf`/`git reset --hard`/`git checkout .`/push/`.env`/deploy=high else
  med); `should_gate(tier, mode)`; `_PENDING_ACTIONS` dict + `await_action_decision`/`resolve_action`.
  `runner.py`: optional gate before `dispatch_tool` (line ~138) — classify → if the rung gates it, YIELD
  an `approval_request` event + block on an `asyncio.Event` → resume/skip on resolve. Default off (clone
  + orchestrator unchanged). `session_turn.py` passes the permission context for inplace turns; **Plan
  rung = read-only** (block edit/exec). Endpoints `POST /run/{id}/action/{action_id}/approve|deny`.
- **4C frontend** — composer: isolation toggle (Clone/In-place, at create) + permission-mode pill
  (Plan/Ask/Auto-accept/Full-auto, in-place only); the thread handles the `approval_request` event → an
  **acknowledge-popup** modal (Approve/Deny; DISTINCT styling + names the consequence for high-risk +
  Full-auto entry). API client `approveAction`/`denyAction`.
- **Verify** then run an adversarial-review workflow (like Phase 1).

## Gotchas (carry forward)
- **UI is logged in as `cisco` = user id 2**; backend test tokens default to user 1. Sessions are
  user-scoped → make test sessions with a user-2 token (or via the UI) to see them in cisco's UI.
- `llama3.1:8b` is flaky at file edits (sometimes overwrites vs appends, sometimes produces nothing) —
  it's MODEL behavior, not an arch bug; use very explicit briefs ("Create notes.txt containing exactly
  one line: alpha") for deterministic verification. A coding model / model-picker fixes it later.
- `git` in the container hits cross-uid dubious-ownership on bind-mounts — only `_run_git` (sets
  `GIT_CONFIG_GLOBAL` safe.directory=*) works; a bare `docker exec git` returns empty. `--no-hardlinks`
  for clone-local (Docker binds are cross-device).
- To light up Create-PR in the UI you need an attached repo WITH a GitHub origin — add a temp demo
  origin on the host (`/tmp/harvis-attach-test`), then remove it after.

## Standing rules
Branch `harvis1.1`; uncommitted; **no push until the user says go**. Verify on the laptop :9000.
Create-PR is the one irreversible action — human-only, refuses main/master, never agent-fired.
