# Handoff — Multi-Agent Parallel Orchestration (2026-06-14)

## Goal (this session)
Implement the **multi-agent function**: turn the single-sub-agent P5 orchestrator into true
**parallel fan-out** — split a task into N role sub-agents, run them concurrently, each in its own
isolated workspace on its own model, render as parallel lanes + per-agent diffs. Plus the per-run
**uniform-model toggle**. Both done + verified.

## State: SHIPPED + verified, committed `ca7451a` on `harvis1.1` (NOT pushed)
- One commit, 8 files. Tree clean except an unrelated untracked `front_end/newjfrontend/app/docs/`.
- `build/` is gitignored (deployed via rsync, not committed).

### What shipped
- **`workspace/orchestration/orchestrator.py`** — `simple_task_split` now rule-based MULTI-role
  (frontend/backend/testing/security/docs by keyword, cap 4; fallback 1 backend for atomic). `run_orchestrated`
  fans out CONCURRENTLY: `asyncio.Queue` + per-lane sentinel + `asyncio.Semaphore(HARVIS_ORCH_MAX_PARALLEL,
  default 3)`. Per-child diff artifact, aggregate `done` summary, `uniform_model` param.
- **`workspace/orchestration/profiles.py`** — per-role models lightened ≤8B + heterogeneous for the 8GB box:
  backend/security `llama3.1:8b`, frontend `gemma4:e4b`, testing/docs `gemma4:e2b`.
- **`workspace/workspace_router.py`** — `_start_workspace` gained `uniform_model` (stored in ws state);
  orchestrated branch passes `ws.get("uniform_model")` to `run_orchestrated`.
- **`owui_compat/workspace_bridge.py`** — reads `harvis_orchestrate_uniform` from the chat body → launch_kwargs.
- **Frontend** — `stores/index.ts` (`orchestrateUniformModel` store + persist `'orchestrate'` chatMode),
  `MessageInput.svelte` (Per-role↔1-model pill, Orchestrate mode only), `Chat.svelte` (body field),
  `RunArtifacts.svelte` (one labeled diff block per sub-agent).

### Verified live on :9000
- Heterogeneous: "backend API + frontend page + test" → 3 agents (gemma4:e4b / llama3.1:8b / gemma4:e2b),
  4 parallel graph lanes, 10 files, 3 diff blocks.
- Uniform: toggled "1 model" → "Planned 2 sub-agent(s) (uniform model): … on gemma4:12b" — both on chat model.

## Known v1 limitation (NOT a bug)
Sub-agents are **fully isolated** (separate scratch dirs) → interdependent roles flail: the Testing agent
can't import the Backend agent's `app.py`, churns on unittest import errors until it writes a self-contained
test. Completes, but slow (worse with model serialization on one GPU). Fix = P5.6 shared-workspace mode.

## Deploy (no rebuild)
- **Backend** (bind-mounted): `docker restart harvis-backend`.
- **Frontend**: edit MAIN `front_end/owui/src` → `rsync -a --delete --exclude node_modules --exclude build
  MAIN/src/ WT/src/` → `npm --prefix WT run build` → `rsync -a --delete WT/build/ MAIN/build/` →
  `docker restart nginx-proxy`. (MAIN = `~/Harvis/front_end/owui`;
  WT = the worktree's `front_end/owui`.) Cache-bust navigations with `?cb=N`.

## NEXT (in order) — auto-artifact is the next concrete build
### 1. Auto-artifact feature (fully specced)
On an orchestrated run finishing: pick the **primary changed file** by heuristic (`index.html` > largest >
first), **auto-pop the Artifacts tab** (reuse the `workspaceControlsTab` bridge; gate to
`agent_id=="orchestrated"`; only if ≥1 changed file), and **render by type** via a NEW **file-type router**
in `RunArtifacts.svelte`:
- **HTML** → **sandboxed iframe live preview**. ⚠ **NON-NEGOTIABLE: `sandbox="allow-scripts"`, NEVER
  `allow-same-origin`** — model-generated code is untrusted; that one attribute is the line between a safe
  preview and running model scripts against the live session.
- **Markdown** → reuse the existing `MarkdownTokens` renderer.
- **else** → code view.
- Preview is **additive ABOVE** the existing diff list. **Render-what-the-agent-wrote only** — no
  React/Mermaid/on-demand PDF generation (later runtime arc). Build it as a **router** so PDF/images/SVG
  slot in as cases later.

### 2. P5.6 — shared-workspace (or read-only-sibling) mode
So the testing agent can see the files it's testing (fixes the isolation churn above). Needs `git` in the
backend image OR a shared scratch root.

### 3. Cursor-inspired surfacing (vision)
Make **Orchestrate the prominent default surface in Agent mode** — but "default" = default *surface*, NOT
force-fan-out every message (⚠ the rule-based split still decides 1-vs-many, so simple tasks don't pay the
parallelism/VRAM cost). **Automations** becomes the agent-customization layer (define agents = edit
`AGENT_PROFILES` from the UI + schedule them; scheduling = deferred **P8**). Three layers: **profiles define
agents → Automations configure + schedule → Orchestrate runs them.**

## Parked
- **OpenClaw upgrade** (v2026.2.23 → current) for `defineToolPlugin` + custom `web_search` proxying
  `/api/tools/search`. Scenario/MCQ correctness is a known dead zone until then — NOT model failures.
- **Proactive web-search on knowledge gaps** (long-queued): model should `web_search` when uncertain
  instead of "I don't know" — tune WEB ACCESS directive + uncertainty→retry-with-search, NOT forced calls.

## Standing rules
Branch `harvis1.1`; **no push until verified**; commit only when asked; deploy via the full rsync→build→
rsync→restart-nginx flow; never fabricate benchmarks; model stays user-adjustable.

## Pointers
- Obsidian: `notes-vault/code/harvis/2026-06-14-multi-agent-parallel-orchestration.md` (+ spike note superseded).
- Memory: `project_p5_orchestration_spike` (updated), `project_autoartifact_next` (the spec above).
