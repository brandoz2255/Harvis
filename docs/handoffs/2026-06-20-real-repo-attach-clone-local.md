# 2026-06-20 — Real-repo attach (clone-local isolation + diff-vs-HEAD)

Built + verified E2E the Claude-Code-desktop "attach a real repo → per-repo diff vs HEAD" loop into Harvis's P5 orchestration. v1 = **diff-only, single repo, clone-local + read-only source**. Create-PR deferred. Branch `harvis1.1`, **uncommitted, NOT pushed**.

Plan: `~/.claude/plans/noble-noodling-pnueli.md`. Memory: `project_real_repo_attach`.

## Goal
An orchestrated run can attach a real local git repo. Each sub-agent runs in a `git clone --local` of that repo (read-only source, throwaway clone) and produces a **real `git diff` vs HEAD** — not the scratch-dir/difflib spike. The source repo is never written (containment by the RO mount, since `exec` can't be path-bounded).

## State — DONE + verified
- **Backend core** (`workspace/orchestration/isolation.py`): additive `isolation_mode="attached"` + `repo_config`. `_create_attached` = `git clone --local --no-hardlinks` + `checkout -B <branch>`; `collect_diff`/`collect_changed_files` = real `git diff --cached` vs HEAD; `collect_file_contents` reads changed files; `cleanup` = rmtree (unchanged). Scratch/difflib path byte-identical.
- **Threading** (`workspace_router.py` + `orchestration/orchestrator.py`): `LaunchRequest.repo_path` → `_start_workspace` → `_workspaces` dict → `_run_workspace_bg` orchestrated branch passes `isolation_mode="attached"`+`repo_config` → `run_orchestrated` → manager ctor. Mode literal `"attached"` consistent in branch + call.
- **OWUI UI** (`owui_compat/workspace_bridge.py` + `front_end/owui`): bridge launch_kwargs `repo_path=owui_body["harvis_repo_path"]`; `Chat.svelte` sends `harvis_repo_path: $orchestrateRepoPath`; new store `orchestrateRepoPath`; composer **repo dropdown** in MessageInput's orchestrate sub-menu, populated from `getAttachedRepos()`.
- **Endpoint**: `GET /api/workspace/attached-repos` → `{repos:[{path,name,branch}]}` from `HARVIS_ATTACHED_REPOS`.
- **Diff UI**: `RunArtifacts.svelte` per-diff `+N −M` stats + always-shown label header.
- **Infra**: `git` in `python_back_end/Dockerfile` (late docker.io apt block → pip-wheel cache preserved); `docker-compose.yaml` RO bind-mount `${HARVIS_ATTACH_REPO:-…}:/data/attached-repos/harvis:ro` + `HARVIS_ATTACHED_REPOS` env.

## Verification (all green)
git in container; RO mount + **exec write to source fails**; `MODE: attached` real git diff; scratch regression (difflib, no clone); 4-lane concurrency clean; `/attached-repos` → `harvis · master`; **full `/launch` orchestrated run with `repo_path` → ATTACHED clone log → real git-diff artifact (gemma4:e2b rewrote cloned app.py) → run `done`, clone torn down, source pristine**; OWUI build compiles.

## Failed attempts → fixes (the two real gotchas)
1. `-c safe.directory=*` and `GIT_CONFIG_COUNT` env both FAILED dubious-ownership (cross-uid bind: host 1000 vs backend 1001). **git ignores command-line `safe.directory` by design** — only a config FILE works. Fix: `_run_git` writes `.harvis-gitconfig` (`[safe] directory=*`) + sets `GIT_CONFIG_GLOBAL`. (`*` wildcard works on git 2.34.1 only via a file.)
2. `git clone --local` failed "Invalid cross-device link" — source `/data` bind vs workspace root `/tmp` bind are different filesystems. Fix: `--no-hardlinks` (copy; Docker binds are always cross-device so hardlinks never apply — the plan's accepted same-fs fallback).

## Files in flight (uncommitted on harvis1.1)
- `python_back_end/Dockerfile`, `docker-compose.yaml`
- `python_back_end/workspace/orchestration/isolation.py`, `orchestrator.py`
- `python_back_end/workspace/workspace_router.py`
- `python_back_end/owui_compat/workspace_bridge.py`
- `front_end/owui/src/lib/apis/agent-runs/index.ts`, `lib/stores/index.ts`, `lib/components/chat/Chat.svelte`, `lib/components/chat/MessageInput.svelte`, `lib/agent-studio/RunArtifacts.svelte`
- (deploy state) backend image rebuilt + recreated; owui built; nginx restarted. Currently mounting test repo `/tmp/harvis-attach-test`.

## Next steps
- User browser-verify the composer "Attached repo" dropdown + an orchestrated run's per-repo diff at `:9000`.
- Decide which repo to mount (`HARVIS_ATTACH_REPO`) — small test repo vs the real Harvis repo (cloning a large `.git` with `--no-hardlinks` copies it per sub-agent).
- DEFERRED (later modes): Create-PR (human-only via `repo_manager.push-changes`), RW-worktree in-place commits, multi-repo, persisted base/head SHAs.
- Then per the roadmap (`project_post_onb_roadmap`): #1 podcast voice, VibeCode IDE.
