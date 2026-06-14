# Handoff — P5 Parallel Isolated Agent Orchestration (v1 spike) — 2026-06-13

Branch `harvis1.1`. Backend is **bind-mounted** (`python_back_end/workspace` → `/app/workspace`,
`main.py` → `/app/main.py`), so all of this applied via `docker restart harvis-backend` — **no image
rebuild**. Verified end-to-end on `:9000`.

## What shipped (P5.1–P5.4 + model badge)
A Harvis-native multi-agent orchestrator, built ALONGSIDE the existing OpenClaw / parallel paths. An
orchestrated run = parent orchestrator → 1 isolated sub-agent (its own model) in a git-tracked scratch
dir → native tool loop (path-safe) → diff collected → artifact stored → parent/child rendered in RunView.

- **`workspace/orchestration/`** (new package):
  - `isolation.py` — `WorkspaceIsolationManager`: scratch dir per agent + baseline snapshot; `collect_diff`
    / `collect_changed_files` via **difflib** (the backend image has no `git` binary — difflib gives the
    same additions/mods/deletions diff with no rebuild). `validate_agent_path` = the path-safety gate.
  - `model_router.py` — `ModelRouter.complete(...)`: wraps `model_proxy._resolve_route` → POSTs the
    completion to the resolved provider. Per-agent model, zero new provider code.
  - `profiles.py` — `AGENT_PROFILES` (orchestrator/backend/frontend/testing/security/docs) on Harvis-real
    models (Ollama/Kimi); `get_profile(role)`.
  - `tools.py` — native `read_file`/`edit_file`/`exec`/`run_tests`/`finish` + `parse_tool_calls`
    (message.tool_calls primary, fenced-JSON fallback). Each file op calls `validate_agent_path` first.
  - `runner.py` — `SubAgentRunner.run(...)`: the in-process agent loop, emits `OpenClawEvent`s tagged
    run_id/parent_run_id/agent_label/model. Tool results fed back as a user turn (robust for local models).
  - `orchestrator.py` — `run_orchestrated(...)`: parent agent_start → `simple_task_split` (spike: 1) →
    isolate + child run row → run sub-agent → collect diff → save artifacts → final `done`.
  - `__init__.py` — `ORCHESTRATION_SCHEMA_SQL` (idempotent migration).
- **DB** (`workspace_schema.sql` + lifespan migration in `main.py`): `workspace_runs` gained
  `parent_run_id, role, model_provider, model_name, workspace_path, branch_name`; new `workspace_artifacts`
  table. `_db_create_run` extended (sub-agents = first-class rows), `_db_save_artifact` added.
- **Wiring** (`workspace_router.py`): `agent_id == "orchestrated"` branch in `_run_workspace_bg`; added to
  the launch allowlist; endpoints `GET /run/{id}/tree`, `/run/{id}/artifacts`, `/artifact/{id}`.
- Frontend: RunView renders the parent/child/tool/done graph + model badges with **no change** (native
  events are compatible). The only un-built UI bit = an inline diff card (P5.5).

## Verified E2E (2026-06-13)
`POST /api/workspace/launch {agent_id:"orchestrated", model_name:"gemma4:e2b"}` →
parent `04813ae2` done, child `b6b2e5ca` (backend, gemma4:e2b, 6.5s) → artifact diff =
`+print('hello from the orchestrated agent')` in `hello.py`. RunView shows Orchestrator → Backend Agent →
edit_file ✓ → Done. Isolation unit test 8/8; path-safety blocks `../` + absolute.

## Bugs found + fixed during E2E
1. `agent_id="orchestrated"` was normalized to `"local"` by the launch allowlist → added "orchestrated".
2. `from .. import workspace_router` resolved to the re-exported **APIRouter instance** (shadowed by
   `workspace/__init__.py`), not the module → import the functions from the submodule path.
3. Parent-row **FK race**: launch starts the bg task BEFORE its own `_db_create_run` commits; every other
   stream has model latency, but the orchestrator emits `agent_start` instantly → it raced the insert.
   Fix: orchestrator idempotently ensures the parent row first.

## Manual recreation (do it yourself)

**Trigger an orchestrated run from the browser** (no UI button yet — that's a follow-up):
1. Open `http://localhost:9000`, log in.
2. DevTools (F12) → Console. Paste:
   ```js
   const r = await (await fetch('/api/workspace/launch', {
     method:'POST',
     headers:{Authorization:`Bearer ${localStorage.token}`,'Content-Type':'application/json'},
     body: JSON.stringify({
       task_brief: "Create a file hello.py that prints 'hi from the agent'.",
       chat_history: [], agent_id: "orchestrated", model_name: "gemma4:e2b", parallel: false
     })
   })).json();
   console.log('run:', r.workspace_id);
   location.href = '/harvis/agent-studio/run/' + r.workspace_id;
   ```
3. It launches and navigates to the run view → watch **Orchestrator Agent → Backend Agent → Using
   edit_file ✓ → Done**.
4. See the diff (replace `<id>`):
   ```js
   const t = localStorage.token;
   const arts = await (await fetch(`/api/workspace/run/<id>/artifacts`, {headers:{Authorization:'Bearer '+t}})).json();
   const diffId = arts.artifacts.find(a=>a.artifact_type==='diff').id;
   const diff = await (await fetch(`/api/workspace/artifact/${diffId}`, {headers:{Authorization:'Bearer '+t}})).json();
   console.log(diff.content);
   ```
5. Inspect the tree / DB:
   ```bash
   docker exec pgsql-db psql -U pguser -d database -c \
     "SELECT id,parent_run_id,role,model_name,status FROM workspace_runs WHERE id='<id>' OR parent_run_id='<id>';"
   ```

**The build/deploy process** (how it was applied): edit files under `python_back_end/workspace/` →
`docker restart harvis-backend` (bind-mounted, no rebuild). The schema self-migrates in the lifespan on
startup. Frontend (when the diff card lands) uses the usual rsync→`npm run build`→rsync→`docker restart
nginx-proxy`.

## Next / deferred (per minimal-spike scope)
- **P5.5** inline diff card in RunView (the diff is API-ready + shown in the Done node; this just renders it).
- A UI entry point for orchestrated mode (intent pill / mode toggle) instead of console/curl.
- Risk classifier + approval gate (`risk.py` stub exists) · true parallel fan-out (per-agent models in
  `stream_parallel_workspace`) · model-decided planning · worktree-of-attached-repo isolation (needs `git`
  in the image).
