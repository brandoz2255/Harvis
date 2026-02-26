# Workspace Session — 2026-02-25

Three problems fixed, one architectural decision documented.

---

## 1. Token spam in Logs tab

### Problem
OpenClaw's `chat` event with `state: "partial"` sends the **full accumulated text so far** every time it fires, not just the new characters. Our backend was yielding one `token` SSE event per partial, so the Logs tab showed 30+ entries like:

```
TOKEN  **Sub-agent spawned** (runId: `f92b41fe...`). The workspace agent is now g
TOKEN  **Sub-agent spawned** (runId: `f92b41fe...`). The workspace agent is now ge
TOKEN  **Sub-agent spawned** (runId: `f92b41fe...`). The workspace agent is now gen
...
```

### Fix — `python_back_end/workspace/openclaw_client.py`

Added `self._last_partial_text: str = ""` to `__init__` and reset it at the start of each `stream()` call. In the `partial` handler, compute the delta and emit only the new portion:

```python
# Before — sent the whole growing string each time
elif state == "partial":
    text = self._extract_text(content)
    if text:
        yield OpenClawEvent("token", {"content": text})

# After — emit only the new characters since last partial
elif state == "partial":
    text = self._extract_text(content)
    if text:
        delta = text[len(self._last_partial_text):]
        self._last_partial_text = text
        if delta:
            yield OpenClawEvent("token", {"content": delta})
```

The frontend joins all token events together, so it still assembles the full text correctly in the Dashboard AI Response block. The Logs tab now shows one compact line per token chunk instead of dozens of growing duplicates.

---

## 2. Sub-agent completion never received

### Problem
When the parent agent delegates work to a sub-agent it sends a `chat` event with `state: "final"` containing text like:

> "**Sub-agent spawned** (runId: `f92b41fe-1930-4e83-8d7a-ec9c4da92a34`). The workspace agent is now generating the filesystem report. It will **auto-announce** when complete."

Our code treated any `state: "final"` as task completion: it yielded a `done` event, broke out of the event loop, and closed the WebSocket. The sub-agent was still running but we had already disconnected. The frontend showed the workspace as `COMPLETE` with summary "Sub-agent spawned…" — the actual result never arrived.

### Fix — `python_back_end/workspace/openclaw_client.py`

Added a class-level tuple of delegation signals and a detection check inside the `final` handler. When detected, emit a log event and `continue` the loop instead of breaking — keeping the WebSocket open until the sub-agent posts its real result as a second `final` event:

```python
_DELEGATION_SIGNALS = (
    "sub-agent spawned",
    "auto-announce",
    "spawned agent",
    "spawning agent",
    "sub-agent is",
)

if state == "final":
    text = self._extract_text(content)
    text_lower = text.lower()

    if any(sig in text_lower for sig in self._DELEGATION_SIGNALS):
        # Parent delegated to a sub-agent — keep connection open.
        # Sub-agent will "auto-announce" by posting a second final event
        # to the same session key when it finishes.
        yield OpenClawEvent("log", {"message": "Sub-agent working — waiting for result…"})
        self._last_partial_text = ""   # reset for sub-agent's upcoming partials
        continue                        # keep the async-for loop alive

    yield OpenClawEvent("done", {"summary": text})
    break
```

OpenClaw's "auto-announce" mechanism posts the sub-agent's result back to the same session key as a second `state: "final"` event. That second event won't contain delegation signals, so we fall through to `yield OpenClawEvent("done", ...)` normally.

---

## 3. Background task architecture (pg-boss pattern)

### Problem — why pg-boss was considered
The sub-agent fix keeps the WebSocket open, but a second problem remained: the OpenClaw stream ran *inside* the SSE response generator. This meant:

- Browser disconnects (navigates away, Nginx 60s timeout, mobile backgrounding) → `asyncio.CancelledError` propagates → `client.cancel()` called → workspace killed mid-run
- Sub-agents taking 5+ minutes would die when the SSE timed out
- Pod restart → `_workspaces` dict wiped → in-flight tasks vanished
- Reconnecting browser gets a 404

### Decision — why not pg-boss
pg-boss is a **Node.js library** and cannot be used in the Python FastAPI backend. The Python equivalents (`procrastinate`, `arq`) add a separate worker process and additional infrastructure. For a single-replica backend with PostgreSQL already in place, native asyncio + the existing `workspace_events` table achieves the same guarantees without new dependencies.

### Fix — `python_back_end/workspace/workspace_router.py` (full rewrite)

**New in-memory state:**
```python
_workspaces: dict[str, dict] = {}
_workspace_queues: dict[str, asyncio.Queue] = {}   # (seq, event) | None per workspace
_workspace_tasks: dict[str, asyncio.Task] = {}      # background task references
```

**New `_run_workspace_bg()` background function:**

Drives the OpenClaw stream independently of any HTTP connection. Every event is:
1. Saved to `workspace_events` (DB is the authoritative log)
2. Pushed to the per-workspace `asyncio.Queue` as `(seq, event)` for the active SSE consumer

On `asyncio.CancelledError` (user hit Cancel) or unhandled exception, saves a terminal event to DB and queue before finishing. Puts a `None` sentinel when done so the SSE generator knows to close.

```
/launch or /rerun
  └─ asyncio.create_task(_run_workspace_bg(...))   ← independent of SSE
       ├─ client.stream() — drives OpenClaw WebSocket
       ├─ _db_save_event() for every event
       ├─ queue.put((seq, event)) for live SSE
       └─ queue.put(None) when done (sentinel)
```

**New `/stream` generator — two phases:**

```
Phase 1: DB replay
  └─ SELECT * FROM workspace_events WHERE workspace_id = $1 ORDER BY seq
       ├─ yields each event as SSE
       └─ if terminal event found → yield stream_end, return (fully replayed)

Phase 2: Live queue (only reached if workspace still running)
  └─ asyncio.wait_for(queue.get(), timeout=25)
       ├─ TimeoutError → yield SSE comment heartbeat (": ping") to keep Nginx alive
       ├─ None → break (background task ended)
       ├─ (seq, event) where seq <= last_seq → skip (already replayed from DB)
       └─ (seq, event) where seq > last_seq → yield as SSE
```

**SSE disconnect no longer kills the task:**
```python
except asyncio.CancelledError:
    # DO NOT cancel the background task — sub-agents keep running
    logger.info("[workspace:%s] SSE stream cancelled by client", workspace_id)
    return
```

**Cancel button still works** via `/cancel`:
```python
ws["client"].cancel()          # signals OpenClaw WebSocket loop to stop
task = _workspace_tasks.get(workspace_id)
if task and not task.done():
    task.cancel()              # raises CancelledError inside _run_workspace_bg
```

**`_start_workspace()` helper** — shared by `/launch` and `/rerun` so both get the same background-task setup:
```python
def _start_workspace(workspace_id, session_id, task_brief, chat_history,
                     agent_id, user_id, pool, started_epoch) -> OpenClawClient:
    # creates client, registers in _workspaces, creates Queue, creates Task
    ...
```

### Behaviour comparison

| Scenario | Before | After |
|----------|--------|-------|
| Browser navigates away mid-run | Task killed | Task continues |
| Nginx 60s timeout on quiet stream | Task killed | Heartbeat `": ping"` keeps connection alive; task continues |
| Browser reconnects after disconnect | 404 | Phase 1 replays all DB events; Phase 2 picks up live |
| Sub-agent takes 10 minutes | Task killed when SSE timed out | Background task waits; reconnect gets full replay |
| Pod restart | Task lost (in-memory only) | `workspace_events` table has full history; status queryable via DB |
| User hits Cancel | `client.cancel()` only | `client.cancel()` + `task.cancel()` + terminal event saved to DB |

---

## Files changed

| File | What changed |
|------|-------------|
| `python_back_end/workspace/openclaw_client.py` | Token delta (partial events emit only new chars); sub-agent delegation detection in `final` handler; `_last_partial_text` instance var; `_DELEGATION_SIGNALS` class var |
| `python_back_end/workspace/workspace_router.py` | Full rewrite: `_run_workspace_bg()` background task; `_workspace_queues`/`_workspace_tasks` registries; `_start_workspace()` helper; `/stream` two-phase (DB replay + live queue); `/cancel` cancels asyncio.Task; `/launch` and `/rerun` use `_start_workspace()` |

---

## Context — earlier in this session (before compaction)

Prior to the above three fixes, earlier work in this session included:

### activeTab type fix
`WorkspaceSuggestionBanner.tsx` was calling `setActiveTab('progress')` but the store type had been updated to `'dashboard' | 'playbooks' | 'logs'`. Fixed to `setActiveTab('dashboard')`.

### Playbooks rerun
- Added `POST /api/workspace/run/{source_id}/rerun` — fetches `task_brief` from DB (survives pod restarts), creates fresh `workspace_id + session_id`, returns same shape as `/launch`
- `WorkspacePanel.tsx` — `HistoryRunCard` refactored from single `<button>` to `<div>` wrapper with nested select button + rerun button; `HistoryTab` gets `handleRerun` with inline SSE connection logic

### gpt-oss 120B routing fix
`gpt-oss 120B` was using the local Ollama model instead of the cloud instance. Root cause: `ollama-cloud` provider's `EXTERNAL_OLLAMA_URL` env var wasn't set in the OpenClaw pod, and the NetworkPolicy blocks OpenClaw from reaching external URLs directly regardless. Fixed by routing `gpt-oss` through the `harvis-proxy` provider (same pattern as Kimi K2.5) — OpenClaw → `harvis-ai-merged-backend:8000/v1` → external Ollama. `model_proxy.py` extended to route both Kimi and gpt-oss prefixes.

### gpt-oss removed from workspace selector
`gpt-oss 120B` responded with "NO" after 38 seconds of inference — it is not fine-tuned for tool calling. Removed from `MODEL_OPTIONS` in `WorkspaceSuggestionBanner.tsx`.

### Qwen3 235B added as third workspace model
`qwen3:235b-a22b-q8_0` from cloud Ollama added as the replacement third option. Changes across: `model_proxy.py` (`_OLLAMA_CLOUD_PREFIXES` tuple), `openclaw.yaml` (harvis-proxy models + qwen3 agent), `openclawStore.ts` (type changed from `'gpt-oss'` to `'qwen3'`), `WorkspaceSuggestionBanner.tsx` (MODEL_OPTIONS), `workspace_router.py` (valid agent_ids), `WorkspacePanel.tsx` (display label).

### Local model switched to qwen3:4b
`openclaw.yaml` ollama provider and `main`/defaults agents changed from `gpt-oss:latest` → `qwen3:4b`. Requires `ollama pull qwen3:4b` before pod restart.

### vLLM migration plan
`VLLM_MIGRATION.md` written at project root. Covers: why vLLM over Ollama (PagedAttention, `--tool-call-parser hermes` for structured tool calls, continuous batching), annoyance assessment per component, model installation (`vllm serve Qwen/Qwen3-4B --served-model-name qwen3:4b --port 8001 --enable-auto-tool-choice --tool-call-parser hermes`), 4-phase migration plan, full K8s vLLM sidecar spec, exact `openclaw.yaml` diff, risks (streaming format hard break on Phase 3, VRAM budget, HuggingFace DNS on campus network).

---

## Pending / deferred

| Item | Status |
|------|--------|
| `ollama pull qwen3:4b` on the Ollama pod | Run before next OpenClaw pod restart |
| vLLM migration (Phases 1–4) | Planned in `VLLM_MIGRATION.md`, not started |
| Agents tab in workspace sidebar | Explicitly deferred |
| HuggingFace DNS entry for vLLM model pull | Documented in `VLLM_MIGRATION.md` |
