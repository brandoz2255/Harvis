# Workspace Feature — Context Dump
_Last updated: 2026-02-25_

---

## Current Status

The workspace feature is working end-to-end:
- Frontend banner → `/api/workspace/launch` → OpenClaw session created
- SSE stream → `WorkspacePanel` renders events
- Model selector: **Local AI** (`agent_id="main"` → `ollama/gpt-oss:latest`) or **Kimi K2.5** (`agent_id="kimi"` → proxy → `api.moonshot.ai`)
- SKILL.md rewritten: model now says "I use tools to do the work" ✅

## Remaining Problem (tackle next)

**OpenClaw agent asks "what task?" instead of reading the chat history.**

Current response after SKILL.md fix:
> "I'm ready to execute tasks in the Harvis Workspace. I've read the skill guidelines — I use tools (exec, write, read) to actually do the work. **What task would you like me to complete?**"

This means the agent is NOT reading the `[CONVERSATION CONTEXT]` + `[TASK]` block we send it.

### Root Cause

In `openclaw_client.py`, the task message is sent as a single `chat.send` string:

```python
full_message = (
    f"[CONVERSATION CONTEXT]\n{context_block}\n\n"
    f"[TASK]\n{task_message}\n\n"
    "Use your tools to complete this task. ..."
)
```

The `task_message` = `task_brief` from the suggestion detector. The `context_block` = last 20 messages formatted as `USER: ... / ASSISTANT: ...`.

**Two sub-issues:**

1. **`task_brief` may be vague** — `detect_workspace_task()` in `task_detector.py` returns a short AI-generated brief like "Write a Python script to sort files". The `_resolve_task_brief()` in `workspace_router.py` falls back to the last user message if the brief is generic. But what the model needs is the *entire conversation* about what to build, not just a one-liner.

2. **Context format isn't compelling enough** — The agent sees the context block but interprets the SKILL.md "I'm ready, what task?" as its opening message rather than diving in. The message needs to be more directive: lead with the task, make it impossible to ask back.

### Fix Needed

**In `python_back_end/workspace/openclaw_client.py`** — rewrite the message construction:

```python
# Current (weak — model asks back)
full_message = (
    f"[CONVERSATION CONTEXT]\n{context_block}\n\n"
    f"[TASK]\n{task_message}\n\n"
    "Use your tools to complete this task. ..."
)

# Better — imperative, no room to ask back
full_message = (
    "EXECUTE THIS TASK NOW. Do not ask for clarification. Use your tools immediately.\n\n"
    f"TASK: {task_message}\n\n"
    f"CONTEXT (what was discussed in chat):\n{context_block}\n\n"
    "Start with a tool call. exec, write, or read something right now."
)
```

The key insight: OpenClaw's `chat.send` opens a NEW session each time (fresh `ws-{workspace_id}` session key). The model has no prior context — it only knows the SKILL.md and the single message we send. So the message must be completely self-contained and imperative.

**Also consider**: instead of formatting chat history as a flat text block, extract the most relevant part — the last user message that triggered the workspace suggestion — and put it front and center as the task. The full conversation context is secondary.

### Suggested message format:

```python
# Extract the last user message specifically
last_user_msg = next(
    (m["content"] for m in reversed(chat_history) if m.get("role") == "user"),
    task_message
)

# Build focused message
if context_lines:
    full_message = (
        f"TASK: {last_user_msg}\n\n"
        "Execute this task using your tools now. Do not ask for clarification.\n\n"
        f"CHAT CONTEXT (recent conversation for reference):\n{context_block}"
    )
else:
    full_message = (
        f"TASK: {last_user_msg}\n\n"
        "Execute this task using your tools now. Do not ask for clarification."
    )
```

---

## Model Proxy — Moonshot 401 History

- The proxy (`python_back_end/workspace/model_proxy.py`) was already written and registered in `main.py`
- It uses `MOONSHOT_API_KEY` from **env var**, NOT from the DB
- The DB-stored key (in `user_api_keys` table, Fernet-encrypted) is used by the main chat (`moonshot_api.py`), NOT by the proxy
- The 401 errors seen in logs were from **before** the SKILL.md fix deployment (old pod)
- **If Kimi K2.5 401s again**: add `MOONSHOT_API_KEY` to the `harvis-backend-env` K8s secret:
  ```bash
  kubectl patch secret harvis-backend-env -n ai-agents \
    --type='json' \
    -p='[{"op":"add","path":"/data/MOONSHOT_API_KEY","value":"'$(echo -n "sk-YOUR-KEY" | base64)'"}]'
  kubectl rollout restart deployment/harvis-ai-merged-ollama-backend -n ai-agents
  ```
  The proxy reads `MOONSHOT_API_KEY` env var. The system key (not per-user) goes here.

---

## Files Changed This Session

| File | Change |
|------|--------|
| `python_back_end/workspace/model_proxy.py` | Fixed `moonshot.cn` → `moonshot.ai` (reads from env) |
| `python_back_end/workspace/workspace_router.py` | Added `agent_id` field to `LaunchRequest`, passed to `OpenClawClient` |
| `python_back_end/workspace/openclaw_client.py` | Removed "report what you did" → "use your tools", cleaned message format |
| `front_end/newjfrontend/stores/openclawStore.ts` | `workspaceModel` type restored to `'local' \| 'kimi'` |
| `front_end/newjfrontend/components/workspace/WorkspaceSuggestionBanner.tsx` | Restored model selector (Local AI / Kimi K2.5), sends `agent_id` |
| `k8s-manifests/overlays/prod/openclaw.yaml` | SKILL.md completely rewritten — removed JSON response format requirement, added "call tools, don't describe actions" |

---

## Architecture Summary (for reference)

```
User clicks Launch
  → WorkspaceSuggestionBanner sends:
      { task_brief, chat_history, agent_id: "main"|"kimi" }
  → workspace_router.py creates OpenClawClient(agent_id)
  → /stream/{id} SSE connects → client.stream(task_brief, chat_history)
  → openclaw_client.py:
      1. WebSocket to ws://harvis-ai-openclaw:18789
      2. Ed25519 handshake + OPENCLAW_GATEWAY_TOKEN auth
      3. chat.send with formatted message (task + context)
      4. Streams back tool_call / tool_result / log / done events
  → WorkspacePanel renders each event type

Model routing (all go through OpenClaw — no bypass):
  main  → ollama/gpt-oss:latest (local, already pulled)
  kimi  → harvis-proxy/kimi-k2.5 → http://backend:8000/v1 → api.moonshot.ai
           (API key stays in backend env, never in OpenClaw)
```

## Ollama Discovery Timeout

OpenClaw logs: `Failed to discover Ollama models: TimeoutError`
- This is a **startup warning only** — not fatal
- `gpt-oss:latest` IS pulled and listed in Ollama
- Model is statically configured in openclaw.json so discovery failure doesn't break it
- OpenClaw tries to auto-list Ollama models at startup; the request times out (Ollama may be slow)
- No action needed unless the `main` agent starts failing

---

## Next Session — What To Do

1. **Fix `openclaw_client.py` message format** (described above) — make the task imperative, lead with `TASK:`, extract the last user message as the primary instruction
2. **Test**: launch workspace from a conversation where you discussed a specific thing to build, verify the agent dives in with tool calls
3. **(Optional) Add `gpt-oss` cloud agent** — if you want a third model option (Ollama cloud / GPT-OSS via Moonshot API), add it to openclaw.json as a third agent pointing to the proxy with a different model id, add it to the model selector in the banner
4. **(Optional) Moonshot system key** — add `MOONSHOT_API_KEY` to `harvis-backend-env` K8s secret if you want the proxy to work with a system-level key independent of per-user DB keys
