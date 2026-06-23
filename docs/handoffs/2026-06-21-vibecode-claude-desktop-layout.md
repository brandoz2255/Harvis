# 2026-06-21 — VibeCode page → Claude-Code-desktop layout

Turned the `/harvis/vibecode` ~19-line stub into the **Claude-Code-desktop Code interface**, assembled from components shipped during the real-repo-attach arc + one genuinely-new slice (human-gated local-attach Create-PR). Browser-verified end-to-end on `:9000`. Branch `harvis1.1`, **uncommitted, NOT pushed**.

Memory: `project_vibecode_claude_desktop` (+ builds on `project_real_repo_attach`). Diagnosis-first recon mapped every reusable piece before wiring (the relay's discipline: reuse, don't rebuild).

## Goal
The attach-repo engine wasn't the destination — it was the engine. This page is where it becomes the thing pointed at: attach a local repo → orchestrated agents work on a clone → review per-repo diffs → **open a PR**, in one 3-region page like the Claude Code desktop app.

## State — DONE + browser-verified
- **3-region layout** (gated `enable_harvis_vibecode`, Harvis tokens, stub fallback when off):
  - LEFT session list (`WorkspaceActivity` reused + "New"); page owns one `/history` poll feeding both rails.
  - CENTER repo selector + `repo · branch` header + minimal composer (→ `/api/workspace/launch` orchestrated + `repo_path`) / `RunView mode="dock"` (bundles stream + diffs + Create-PR).
  - RIGHT `PlanPanel` (NEW — streams the structured `plan` event) + Background tasks (`WorkspaceActivity statuses=['running']`).
- **Backend**: persisted `repo_path`/`base_branch` on runs; `GET /run/{id}/repo` (`has_github` gate); structured `plan` event (added `"steps"` to `_db_save_event` keys so it survives replay); **`POST /run/{id}/create-pr`** — local-attach PR.
- **Verified live**: attach `harvis · master` → run → center streams, Plan fills ("Backend Agent · llama3.1:8b"), background + session list update; real per-repo diff (`harvis · master · +2 −2`, modify `-def hello`→`+def double`); **Create-PR button appears only when the repo has a GitHub origin**; the confirm is human-gated ("refuses main/master"); **did NOT open a real PR** (the user's deliberate click). Source repo pristine + clones torn down.

## The Create-PR decision (user-chosen: Local-attach PR)
`repo_manager.push-changes` can't drive Create-PR for a local-attach (it needs a GitHub-cloned `workspace_repos` row + token; the attach clone is a read-only local bind-mount with no GitHub remote + is torn down at run end). So the new endpoint: read the run's `repo_path` → resolve the SOURCE's GitHub origin + the user's token → fresh `git clone --local` → checkout base → feature branch → `git apply` the SAVED diff artifact → commit → push (`x-access-token`) → open PR. Human-only, refuses main/master, never agent-triggered.

## Failed attempt → fix
The page first rendered with its left rail UNDER the OWUI sidebar. Fix = the run page's content-column wrapper: `{$showSidebar ? 'md:max-w-[calc(100%-var(--sidebar-width))]' : ''}` on the page's top-level div.

## Files in flight (uncommitted, harvis1.1)
- NEW: `front_end/owui/src/lib/agent-studio/PlanPanel.svelte`; rewritten `routes/(app)/harvis/vibecode/+page.svelte`.
- EDIT backend: `workspace/workspace_router.py`, `workspace/orchestration/{__init__,orchestrator}.py`, `owui_compat/config.py`.
- EDIT frontend: `lib/apis/agent-runs/index.ts`, `lib/agent-studio/RunArtifacts.svelte`.
- Deploy state: backend restarted (schema ALTER on lifespan), owui built, nginx restarted. Test repo mounted at `/data/attached-repos/harvis` (= host `/tmp/harvis-attach-test`, given a demo GitHub origin so the Create-PR button lights up).

## Next steps
- User browser-verify + decide whether to point `HARVIS_ATTACH_REPO` at a real repo and actually open a PR (the only real external action — held for the user).
- Future (not built): in-page **terminal** (PTY `/ws/vibecoding/terminal` already exists) + Monaco editor + AI assistant pane (`project_vibecode_stranded`); multi-repo; Create-PR base-branch precision; rename `orchestrateRepoPath` → a shared `selectedRepoPath` if the chat + vibecode selections should diverge.
- Standing: no push until the user says go.
