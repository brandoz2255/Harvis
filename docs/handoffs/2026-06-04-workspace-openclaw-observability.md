# Handoff: Workspace → OpenClaw routing + observability (2026-06-04)

## Goal
Two problems the user raised about web-UI (:9000) **workspace** runs:
1. **Can't verify OpenClaw is being used / executing / following directions.**
2. **No thought process shown** — the run card jumps from the "starting task" notif straight to a quick final output; no live thinking/tool execution.

User's framing for the fix (verbatim intent):
- **The main thing is making sure OpenClaw works** (be the real executor, with tools).
- **NOT Kimi-centric** — do not design around Kimi K2.5.
- **Keep options open** for people who want to route specific tools/executors (don't rip out the multi-executor mechanism — just stop defaulting away from OpenClaw).

This is investigation-only for now; build continues tomorrow.

## ROOT CAUSE (confirmed) — OpenClaw is never used from the web UI

`python_back_end/owui_compat/workspace_bridge.py:171` hardcodes the executor on every
web-UI workspace launch:
```python
launch_kwargs = dict(
    ...
    agent_id="local",      # ← THIS. every OWUI workspace task.
    parallel=True,
    interactive_context=interactive_context,   # ← note: tools ARE set up, then routed away
)
```

In the launcher (`workspace_router.py` ~566–636) the executor is chosen by `agent_id`:
| agent_id | executor | tools? | OpenClaw? |
|---|---|---|---|
| `local` | `stream_parallel_workspace(provider="local")` / `stream_local_ollama_workspace` | **NO** | NO |
| `kimi` | `stream_kimi_workspace` (Moonshot) | NO | NO |
| `nvidia-kimi` | Kimi via NVIDIA NIM | NO | NO |
| `cloud-ollama` / `gpt-oss` | `stream_ollama_cloud_workspace` | NO | NO |
| **anything else (e.g. `"main"`, the `LaunchRequest` default) → `else`** | **`client.stream(...)` = OpenClaw tool-loop** | **YES** | **YES** |

So the web UI **always** lands on the tool-less local path. OpenClaw's tool-loop (`else`
branch) is **only reachable when agent_id ∉ {local, kimi, nvidia-kimi, cloud-ollama, gpt-oss}**,
which the facade never does.

### Consequences (all observed)
- A web-UI task that needs tools → local model with no tools → it **refuses**. Real DB
  evidence (most recent run, `batiai/qwen3.5-9b`): logs `Planning task decomposition…` →
  `Single agent executing task directly.` → `Starting task on local model: batiai/qwen3.5-9b`
  → tokens: *"I cannot directly run a Google search… I am a text-based AI without built-in
  tools…"*. **Zero `tool_call` events in that run.**
- `kimi_workspace.py` is the home of these direct executors — its own docstring: *"Run a
  workspace task using Kimi K2.5 directly (**bypasses OpenClaw**)"*.

### NOT the blocker
- **OpenClaw is UP and connectable from the backend right now** — live `OpenClawClient._connect()`
  returned `CONNECT: OK` (ws://openclaw:18789). It's not down; it's just never invoked.
- The facade even provisions `interactive_context` (a capability token for interactive tools),
  then routes to the path that can't use it → reads as an **oversight**, not a deliberate choice
  (no comment justifies `agent_id="local"`).

## OBSERVABILITY GAP (confirmed) — the model's thinking is dropped everywhere

The backend streams plenty (DB `workspace_events` totals: **token 78,566**, log 2,193,
tool_call 804, tool_result 800, agent_start 506, done 431, agent_end 375). The OpenClaw
path (`openclaw_client.py`) emits the full set too: `token`, `tool_call`, `tool_result`,
`agent_start`, `agent_end`, `log`, `done`, `error`, `cancelled`.

But the UI throws the reasoning away:
- **`WorkspaceRunCard.svelte`** `handle()` switch has cases for `agent_start`/`log`/`tool_call`/
  `tool_result`/`done`/`error`/`cancelled` — **no `token` case.** It shows a one-line
  `currentStep` + the last-4 tool phrases + a count → then the final `summary`. The model's
  streamed reasoning/output is never rendered.
- **`lib/agent-studio/workflow/ThoughtStream.svelte`** (the run-view feed) — **also no `token`
  case.** Same gap.

So even when a run streams thousands of tokens, the user sees: phase label → summary. That is
exactly "starting notif → quick output, no thinking."

## THE FIX (plan for tomorrow)

### Part A — Routing: make OpenClaw the executor (the main thing)
- Change the web-UI launch path so workspace tasks run through **OpenClaw** (the `else` →
  `client.stream`) by default, so the agent actually has tools (exec, web_search, repo_read/write…).
  Minimal change: `workspace_bridge.py:171` `agent_id="local"` → an OpenClaw-routing id
  (the `LaunchRequest` default is `"main"`, which hits the `else` branch).
- **KEEP the agent_id options** (`local`/`kimi`/`nvidia-kimi`/`cloud-ollama`) — they're the
  "route specific tools/executors" flexibility the user wants to preserve. Don't delete them;
  just change the DEFAULT to OpenClaw and (later) expose a selector so a user/task can opt into
  a specific executor. Consider an env/user-config default rather than a second hardcode.
- **Model reliability is the real risk** (the user's "following directions" worry). The OpenClaw
  tool-loop needs a model that reliably tool-calls. `batiai/qwen3.5-9b` (current OWUI default)
  refused even a plain task. The Discord side already drove OpenClaw successfully with specific
  models — see memory: hermes4:14b was the auto-routed Discord model; qwen3=hash/CodeAct,
  gemma4=decode/crypto; qwen3.5-9b had reliability issues. `openclaw/config/bundled/openclaw.json`
  lists the candidates (Auto, qwen3.5-9b, gemma4:e4b, hermes-3-llama-3.1:8b, qwen3:4b).
  **Decide the OWUI OpenClaw default model before flipping**, or the flip just trades "refuses
  because no tools" for "garbles the tool calls."

### Part B — Observability: show the agent working + which executor
- Add a **`token` case** to BOTH `WorkspaceRunCard.svelte` and `ThoughtStream.svelte` →
  render the streaming reasoning/output (a live, scrolling thought area), not just a phase label.
  (Mind the reasoning vs final-answer split — Harvis already separates `<think>…</think>`; decide
  whether the card shows reasoning inline or collapsed.)
- Surface the **executor + model + agent** on the card: e.g. a small "OpenClaw · <model>" chip,
  tool-call count (distinguish executing vs retrieval-only — the launcher already tracks
  `executing_tool_call_count` vs `tool_call_count`), so the user can *verify* OpenClaw ran it.
- Show **tool calls with detail** (args/output snippet), not just a humanized phrase, so
  "following directions" is auditable.

## Decisions to make tomorrow (before building)
1. **Default OpenClaw model** for the OWUI workspace path (tool-reliable — NOT qwen3.5-9b).
2. **How to keep executor options exposed** — a UI selector (per chat / per task), a user-config
   default, or an env default? (Keep `local`/`cloud`/`kimi` selectable; just not the default.)
3. **Card thinking-stream UX** — show reasoning inline (live) vs collapsed-by-default; how much
   token text to keep before the final summary.
4. Whether to also flip the **native** `/api/chat` auto-launch (main.py + chat_bridge.py) or only
   the OWUI facade.

## Key files
- `python_back_end/owui_compat/workspace_bridge.py:171` — the `agent_id="local"` hardcode (the bug).
- `python_back_end/workspace/workspace_router.py` ~540–636 — the agent_id→executor branch (the `else`
  = OpenClaw `client.stream`); ~640–644 tracks `executing_tool_call_count`.
- `python_back_end/workspace/kimi_workspace.py` — the direct (non-OpenClaw) executors: `stream_kimi_workspace`,
  `stream_local_ollama_workspace`, `stream_ollama_cloud_workspace`, `stream_parallel_workspace`. **Keep**
  (they're the routing options), just not the default.
- `python_back_end/workspace/openclaw_client.py` — `client.stream` (the OpenClaw path); emits token +
  tool_call/result + agent_start/end + log + done; `_connect()` verified OK.
- `front_end/owui/src/lib/components/chat/Messages/WorkspaceRunCard.svelte` — `handle()` switch, **add `token`**.
- `front_end/owui/src/lib/agent-studio/workflow/ThoughtStream.svelte` — feed, **add `token`**.
- `front_end/owui/src/lib/apis/streaming/workspace-stream.ts` — event types (confirm `token` carries `content`).
- `openclaw/config/bundled/openclaw.json` — model list for the OpenClaw path.

## Verify (when built)
- Launch a tool-needing task from :9000 → DB `workspace_events` for that run shows `tool_call`/
  `tool_result` (OpenClaw actually executed), NOT a bare token refusal.
- The run card shows live thinking (tokens) streaming + tool calls + an "OpenClaw · <model>" chip.
- A non-tool chat still answers cleanly; the `local`/`cloud` executors still work when selected.

## Status
Investigation only — nothing changed in code this session. Cookbook work (multi-device, GGUF
resolver, Odysseus table, capability pills, dock fit) all shipped + deployed but **uncommitted**
on `harvis1.1`, same as the rest of the pile.
