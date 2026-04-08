# OpenClaw Provider-Agnostic Workspace — Master Prompt

> **Goal:** Make the OpenClaw workspace run out-of-the-box on ANY system — from a
> beefy GPU workstation with local Ollama to a mid-tier laptop with only a cloud
> API key, to a zero-config first-time user. No single variable should be required
> for the workspace to boot. If no API keys are detected, fall back to local
> Ollama. Errors must be human-readable and point to a fix.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Phase 1 — Backend: Provider Discovery Endpoint](#2-phase-1--backend-provider-discovery-endpoint)
3. [Phase 2 — Backend: Local Ollama Workspace Stream](#3-phase-2--backend-local-ollama-workspace-stream)
4. [Phase 3 — Backend: Smart Routing in `_run_workspace_bg`](#4-phase-3--backend-smart-routing-in-_run_workspace_bg)
5. [Phase 4 — Backend: Actionable Error Events](#5-phase-4--backend-actionable-error-events)
6. [Phase 5 — Frontend: Model Selector Dropdown (Header Bubble)](#6-phase-5--frontend-model-selector-dropdown-header-bubble)
7. [Phase 6 — Frontend: Dynamic Suggestion Banner](#7-phase-6--frontend-dynamic-suggestion-banner)
8. [Phase 7 — Frontend: Agent Graph Label Sync](#8-phase-7--frontend-agent-graph-label-sync)
9. [Phase 8 — Store & Type Updates](#9-phase-8--store--type-updates)
10. [Phase 9 — Validation & Testing](#10-phase-9--validation--testing)
11. [File Change Summary](#11-file-change-summary)
12. [Non-Goals / Anti-Patterns](#12-non-goals--anti-patterns)

---

## 1. Architecture Overview

### Current State

The workspace currently has four hardcoded model options in the frontend:

```
kimi → Moonshot API (requires MOONSHOT_API_KEY or per-user DB key)
nvidia-kimi → NVIDIA NIM (requires NVIDIA_API_KEY)
local → Local Ollama (requires running Ollama instance)
qwen3 → Cloud Ollama (requires EXTERNAL_OLLAMA_URL)
```

The problem: if no Moonshot API key is configured, the default `kimi` path
errors out with a cryptic message. There's no runtime discovery of what's
actually available, and the UI shows model names that may not be reachable.

### Target State

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend                              │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Model Dropdown (replaces static bubble)          │   │
│  │ ┌───────────────────────────────────────────┐   │   │
│  │ │ ▼  qwen2.5:7b (Local Ollama)        ● online│   │   │
│  │ │    Kimi K2.5 (Moonshot)            ○ no key│   │   │
│  │ │    Qwen3 235B (Cloud Ollama)       ● online│   │   │
│  │ └───────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  Agents Tab: shows actual model name, not "Kimi"        │
└───────────────────────┬─────────────────────────────────┘
                        │ POST /api/workspace/launch
                        │ { agent_id: "local", model_name: "qwen2.5:7b" }
                        ▼
┌─────────────────────────────────────────────────────────┐
│                    Backend                               │
│                                                         │
│  GET /api/workspace/providers                            │
│  → probes Ollama, checks env vars, returns availability │
│                                                         │
│  _run_workspace_bg():                                    │
│    agent_id == "local"                                   │
│      → stream_local_ollama_workspace(model_name)        │
│    agent_id == "kimi" && api_key present                 │
│      → stream_kimi_workspace(api_key)                   │
│    agent_id == "kimi" && NO api_key                      │
│      → auto-fallback to local Ollama + emit warning     │
│    agent_id == "qwen3"                                   │
│      → stream_ollama_cloud_workspace()                  │
│    NOTHING available                                     │
│      → emit actionable error with setup instructions    │
└─────────────────────────────────────────────────────────┘
```

### Key Principles

- **No single dependency.** The workspace must launch with zero env vars if a local Ollama instance is running.
- **Discovery, not assumption.** A `/providers` endpoint probes what's live and reports it to the frontend.
- **Fallback chain:** Cloud API → Local Ollama → Actionable error. Never a silent failure.
- **UI reflects reality.** The model dropdown only shows reachable providers. Unreachable ones are grayed out with a reason.
- **Errors are fixable.** Every error event includes a `fix_hint` field the frontend can display.

---

## 2. Phase 1 — Backend: Provider Discovery Endpoint

### File: `python_back_end/workspace/workspace_router.py`

Add a new endpoint that probes all available LLM providers at runtime.

```python
# ─── Provider Discovery ────────────────────────────────────────────────────────

@workspace_router.get("/providers")
async def list_providers(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Probe all configured LLM providers and return their availability.
    
    The frontend calls this on mount and before showing the model selector.
    Each provider includes: id, label, status ("online"|"offline"|"no_key"),
    available models (for Ollama), and a reason string if unavailable.
    """
    providers = []
    pool = getattr(request.app.state, "pg_pool", None)

    # 1. Local Ollama
    local_ollama = await _probe_local_ollama()
    providers.append(local_ollama)

    # 2. Kimi K2.5 (Moonshot) — check per-user DB key first, then env var
    kimi_status = await _probe_kimi(pool, current_user["id"])
    providers.append(kimi_status)

    # 3. NVIDIA Kimi
    nvidia_status = _probe_nvidia()
    providers.append(nvidia_status)

    # 4. Cloud Ollama (external)
    cloud_ollama = await _probe_cloud_ollama()
    providers.append(cloud_ollama)

    return {"providers": providers}
```

### Probe Functions (same file, above the endpoint)

```python
import httpx as _httpx  # if not already imported

# ─── Ollama probe URLs ─────────────────────────────────────────────────────────
_LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
_EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
_EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")
_MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
_NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")


async def _probe_local_ollama() -> dict:
    """Ping local Ollama and list available models."""
    try:
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{_LOCAL_OLLAMA_URL}/api/tags")
        if resp.status_code == 200:
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            return {
                "id": "local",
                "label": "Local Ollama",
                "status": "online" if models else "online_no_models",
                "models": models,
                "reason": None if models else "Ollama is running but no models are pulled. Run: ollama pull <model>",
            }
    except Exception as exc:
        logger.debug("Local Ollama probe failed: %s", exc)
    return {
        "id": "local",
        "label": "Local Ollama",
        "status": "offline",
        "models": [],
        "reason": "Local Ollama is not reachable. Ensure Ollama is running (ollama serve) or the OLLAMA_URL env var is correct.",
    }


async def _probe_kimi(pool, user_id: str) -> dict:
    """Check Moonshot API key — per-user DB row first, then env var."""
    has_key = bool(_MOONSHOT_API_KEY)

    # Check per-user key in DB
    if not has_key and pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT moonshot_api_key FROM user_settings WHERE user_id = $1",
                    user_id,
                )
            if row and row.get("moonshot_api_key"):
                has_key = True
        except Exception:
            pass

    if has_key:
        return {
            "id": "kimi",
            "label": "Kimi K2.5",
            "description": "Moonshot API",
            "status": "online",
            "models": ["kimi-k2.5"],
            "reason": None,
        }
    return {
        "id": "kimi",
        "label": "Kimi K2.5",
        "description": "Moonshot API",
        "status": "no_key",
        "models": [],
        "reason": "No Moonshot API key found. Add one in Settings or set MOONSHOT_API_KEY env var.",
    }


def _probe_nvidia() -> dict:
    """Check NVIDIA NIM API key."""
    if _NVIDIA_API_KEY:
        return {
            "id": "nvidia-kimi",
            "label": "Kimi K2.5 (NVIDIA NIM)",
            "description": "NVIDIA NIM",
            "status": "online",
            "models": ["nvidia-kimi"],
            "reason": None,
        }
    return {
        "id": "nvidia-kimi",
        "label": "Kimi K2.5 (NVIDIA NIM)",
        "description": "NVIDIA NIM",
        "status": "no_key",
        "models": [],
        "reason": "NVIDIA_API_KEY not configured.",
    }


async def _probe_cloud_ollama() -> dict:
    """Probe external/cloud Ollama instance."""
    if not _EXTERNAL_OLLAMA_URL:
        return {
            "id": "cloud-ollama",
            "label": "Cloud Ollama",
            "status": "offline",
            "models": [],
            "reason": "EXTERNAL_OLLAMA_URL not configured.",
        }
    try:
        headers = {}
        if _EXTERNAL_OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {_EXTERNAL_OLLAMA_API_KEY}"
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(5.0)) as client:
            resp = await client.get(
                f"{_EXTERNAL_OLLAMA_URL.rstrip('/')}/api/tags",
                headers=headers,
            )
        if resp.status_code == 200:
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            return {
                "id": "cloud-ollama",
                "label": "Cloud Ollama",
                "status": "online" if models else "online_no_models",
                "models": models,
                "reason": None if models else "Cloud Ollama reachable but no models available.",
            }
    except Exception as exc:
        logger.debug("Cloud Ollama probe failed: %s", exc)
    return {
        "id": "cloud-ollama",
        "label": "Cloud Ollama",
        "status": "offline",
        "models": [],
        "reason": f"Could not reach {_EXTERNAL_OLLAMA_URL}. Check EXTERNAL_OLLAMA_URL and network.",
    }
```

### IMPORTANT: DB Schema Note

The `_probe_kimi` function references `user_settings.moonshot_api_key`. If your
schema stores the key differently (e.g., encrypted in a different table), adapt
the query accordingly. The pattern is: check DB first, then fall back to env var.

---

## 3. Phase 2 — Backend: Local Ollama Workspace Stream

### File: `python_back_end/workspace/kimi_workspace.py`

Add a new `stream_local_ollama_workspace` function. This is distinct from
`stream_ollama_cloud_workspace` because it targets the **local** Ollama instance
(Docker service `ollama:11434` or user's local machine), not the external cloud URL.

```python
# ─── Local Ollama URL (same as chat/research uses) ────────────────────────────
_LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")

_LOCAL_OLLAMA_SYSTEM_PROMPT = (
    "You are the Harvis Workspace Agent running on a local model. "
    "You have been given a specific task by the user. "
    "Execute the task completely and thoroughly. "
    "Provide a detailed, well-structured response. "
    "If the task involves analysis, provide step-by-step reasoning. "
    "If it involves writing or code, provide the complete output. "
    "Do not ask clarifying questions — make reasonable assumptions and proceed."
)


async def stream_local_ollama_workspace(
    task_message: str,
    chat_history: list[dict],
    model: str = "",
) -> AsyncGenerator[OpenClawEvent, None]:
    """
    Run a workspace task using the LOCAL Ollama instance.

    If `model` is empty, we auto-detect the first available model.
    Yields OpenClawEvent objects matching the standard workspace format.
    """
    base_url = _LOCAL_OLLAMA_URL.rstrip("/")

    # ── Step 1: Resolve model name ────────────────────────────────────────────
    if not model:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                if models:
                    model = models[0]["name"]
                    yield OpenClawEvent("log", {
                        "message": f"Auto-selected local model: {model}",
                    })
                else:
                    yield OpenClawEvent("error", {
                        "message": "Ollama is running but has no models pulled.",
                        "fix_hint": "Run `ollama pull qwen2.5:7b` (or any model) then retry.",
                    })
                    return
        except Exception as exc:
            yield OpenClawEvent("error", {
                "message": f"Cannot reach local Ollama at {base_url}: {exc}",
                "fix_hint": (
                    "Ensure Ollama is running (`ollama serve`) and reachable. "
                    "If running in Docker, check that the `ollama` service is up "
                    "and OLLAMA_URL is set correctly."
                ),
            })
            return

    # ── Step 2: Build messages ────────────────────────────────────────────────
    messages = [
        {"role": "system", "content": _LOCAL_OLLAMA_SYSTEM_PROMPT},
        {"role": "user", "content": _build_context_message(task_message, chat_history)},
    ]

    yield OpenClawEvent("log", {
        "message": f"Starting task on local model: {model}",
    })

    # ── Step 3: Stream via Ollama's OpenAI-compatible endpoint ────────────────
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }

    full_text_parts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                json=payload,
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    yield OpenClawEvent("error", {
                        "message": f"Ollama returned HTTP {response.status_code}: {body.decode()[:500]}",
                        "fix_hint": f"Check that model '{model}' is pulled and Ollama has enough memory.",
                    })
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_text_parts.append(content)
                            yield OpenClawEvent("token", {"content": content})
                    except json.JSONDecodeError:
                        continue

        full_text = "".join(full_text_parts)
        summary = full_text[:500].rstrip() if full_text else "Task completed."
        yield OpenClawEvent("done", {"summary": summary})

    except httpx.ConnectError as exc:
        yield OpenClawEvent("error", {
            "message": f"Connection to local Ollama lost: {exc}",
            "fix_hint": "Ollama may have crashed or run out of VRAM. Check `ollama logs` and GPU memory.",
        })
    except httpx.ReadTimeout:
        yield OpenClawEvent("error", {
            "message": "Local Ollama timed out (>5 min). The model may be too large for your hardware.",
            "fix_hint": "Try a smaller model (e.g., qwen2.5:7b instead of 70b) or increase timeout.",
        })
    except Exception as exc:
        logger.error("local_ollama_workspace: stream error: %s", exc)
        yield OpenClawEvent("error", {
            "message": f"Local Ollama error: {exc}",
            "fix_hint": "Check Ollama logs for details.",
        })
```

---

## 4. Phase 3 — Backend: Smart Routing in `_run_workspace_bg`

### File: `python_back_end/workspace/workspace_router.py`

Modify `_run_workspace_bg` to support the new `local` agent_id and auto-fallback.

### Changes to `_run_workspace_bg`:

Find the section where `agent_id` dispatches to different stream functions.
Replace/extend the routing block:

```python
from .kimi_workspace import (
    stream_kimi_workspace,
    stream_ollama_cloud_workspace,
    stream_local_ollama_workspace,   # NEW import
)

# Inside _run_workspace_bg, where the stream generator is selected:

agent_id = ws["agent_id"]
chat_history = ws["chat_history"]
task_brief = ws["task_brief"]
model_name = ws.get("model_name", "")  # NEW: specific model name from frontend

if agent_id == "kimi":
    # Try to get Kimi API key — per-user DB first, then env
    api_key = await _get_kimi_key(pool, ws["user_id"])
    if api_key:
        event_stream = stream_kimi_workspace(task_brief, chat_history, api_key)
    else:
        # AUTO-FALLBACK: no Kimi key → try local Ollama instead of erroring
        logger.warning("No Kimi API key for user %s — falling back to local Ollama", ws["user_id"])
        fallback_event = OpenClawEvent("log", {
            "message": "Kimi K2.5 API key not found. Falling back to local Ollama.",
        })
        await _push_event(workspace_id, fallback_event, pool, queue)
        event_stream = stream_local_ollama_workspace(task_brief, chat_history, model_name)

elif agent_id == "nvidia-kimi":
    api_key = os.getenv("NVIDIA_API_KEY", "")
    if api_key:
        event_stream = stream_kimi_workspace(
            task_brief, chat_history, api_key,
            api_url="https://integrate.api.nvidia.com/v1",
        )
    else:
        logger.warning("No NVIDIA API key — falling back to local Ollama")
        fallback_event = OpenClawEvent("log", {
            "message": "NVIDIA NIM key not found. Falling back to local Ollama.",
        })
        await _push_event(workspace_id, fallback_event, pool, queue)
        event_stream = stream_local_ollama_workspace(task_brief, chat_history, model_name)

elif agent_id in ("qwen3", "gpt-oss"):
    event_stream = stream_ollama_cloud_workspace(task_brief, chat_history, model=model_name or "gpt-oss:120b")

elif agent_id == "local":
    # NEW: explicit local Ollama path
    event_stream = stream_local_ollama_workspace(task_brief, chat_history, model=model_name)

else:
    # Default: try local Ollama as the universal fallback
    event_stream = stream_local_ollama_workspace(task_brief, chat_history, model=model_name)
```

### Helper: `_get_kimi_key`

```python
async def _get_kimi_key(pool, user_id: str) -> str:
    """Return decrypted Moonshot API key — DB row first, then env var."""
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT moonshot_api_key FROM user_settings WHERE user_id = $1",
                    user_id,
                )
            if row and row.get("moonshot_api_key"):
                # If encrypted, decrypt here. For now assume plaintext or already decrypted.
                return row["moonshot_api_key"]
        except Exception as exc:
            logger.debug("Failed to fetch Kimi key from DB: %s", exc)
    return os.getenv("MOONSHOT_API_KEY", "")
```

### Update `LaunchRequest` model

Add `model_name` to the launch request so the frontend can pass the specific
Ollama model the user selected:

```python
class LaunchRequest(BaseModel):
    task_brief: str = ""
    chat_history: list[dict] = []
    session_id: str = ""
    agent_id: str = "main"
    model_name: str = ""   # NEW: e.g. "qwen2.5:7b", "deepseek-r1:14b"
```

And in `launch_workspace`, pass it through:

```python
# Inside launch_workspace, add to _start_workspace or ws dict:
_workspaces[workspace_id]["model_name"] = req.model_name
```

### Update `_start_workspace`

Extend the workspace dict:

```python
_workspaces[workspace_id] = {
    "client": client,
    "status": "running",
    "task_brief": task_brief,
    "session_id": session_id,
    "chat_history": chat_history,
    "user_id": user_id,
    "started_epoch": started_epoch,
    "agent_id": agent_id,
    "model_name": model_name,  # NEW
}
```

---

## 5. Phase 4 — Backend: Actionable Error Events

### Pattern: Every `OpenClawEvent("error", ...)` MUST include `fix_hint`

This is already demonstrated in the local Ollama streamer above. Apply the same
pattern to ALL error paths across:

- `kimi_workspace.py` — add `fix_hint` to the "API key not configured" error
- `workspace_router.py` — add `fix_hint` to launch validation errors
- `openclaw_client.py` — add `fix_hint` to WebSocket connection failures

Example fixes for existing code:

```python
# kimi_workspace.py — existing error, add fix_hint:
yield OpenClawEvent("error", {
    "message": "Kimi K2.5 API key not configured.",
    "fix_hint": "Add your Moonshot API key in Settings → Workspace, or set MOONSHOT_API_KEY in your environment.",
})

# kimi_workspace.py — stream error:
yield OpenClawEvent("error", {
    "message": f"Kimi K2.5 error: {exc}",
    "fix_hint": "Check your API key is valid and Moonshot's API is reachable. See https://platform.moonshot.cn for status.",
})

# openclaw_client.py — connection failure:
yield OpenClawEvent("error", {
    "message": f"Could not connect to workspace backend: {e}",
    "fix_hint": "The OpenClaw container may not be running. Check `docker compose ps` or `kubectl get pods -n ai-agents`.",
})
```

---

## 6. Phase 5 — Frontend: Model Selector Dropdown (Header Bubble)

### File: `front_end/newjfrontend/components/workspace/WorkspacePanel.tsx`

**Replace** the static model badge in the header with an interactive dropdown.
The current code shows a static `<span>` with `Kimi K2.5` / `Local` text.
Replace it with a dropdown that:

1. Fetches available providers from `GET /api/workspace/providers` on mount
2. Shows the currently selected model with a chevron
3. Dropdown items show: model label + status indicator (green dot = online, gray = offline, amber = no key)
4. Selecting a new model updates `openclawStore.workspaceModel` and `openclawStore.workspaceModelName`
5. Disabled items show their `reason` as a tooltip

### Implementation:

```tsx
// NEW component: ModelSelectorDropdown.tsx
// Place in: front_end/newjfrontend/components/workspace/ModelSelectorDropdown.tsx

'use client'

import React, { useEffect, useState, useRef } from 'react'
import { ChevronDown, Cpu, Wifi, WifiOff, KeyRound } from 'lucide-react'
import { useOpenClawStore } from '@/stores/openclawStore'
import { cn } from '@/lib/utils'

interface ProviderInfo {
  id: string
  label: string
  description?: string
  status: 'online' | 'offline' | 'no_key' | 'online_no_models'
  models: string[]
  reason: string | null
}

export function ModelSelectorDropdown() {
  const { workspaceModel, workspaceModelName, setWorkspaceModel, setWorkspaceModelName } = useOpenClawStore()
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Fetch providers on mount
  useEffect(() => {
    const fetchProviders = async () => {
      try {
        const token = localStorage.getItem('token') || ''
        const res = await fetch('/api/workspace/providers', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const data = await res.json()
          setProviders(data.providers)
          // Auto-select first available provider if current selection is unreachable
          autoSelectBestProvider(data.providers)
        }
      } catch (err) {
        console.error('Failed to fetch providers:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchProviders()
  }, [])

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const autoSelectBestProvider = (providerList: ProviderInfo[]) => {
    const currentProvider = providerList.find(p => p.id === workspaceModel)
    if (currentProvider?.status === 'online') return // current selection is fine

    // Priority: local > kimi > cloud-ollama > nvidia-kimi
    const priority = ['local', 'kimi', 'cloud-ollama', 'nvidia-kimi']
    for (const id of priority) {
      const p = providerList.find(prov => prov.id === id)
      if (p?.status === 'online') {
        setWorkspaceModel(id as any)
        if (p.models.length > 0) setWorkspaceModelName(p.models[0])
        return
      }
    }
  }

  const statusIcon = (status: string) => {
    switch (status) {
      case 'online': return <span className="w-2 h-2 rounded-full bg-green-400 shrink-0" />
      case 'no_key': return <KeyRound className="w-3 h-3 text-amber-400 shrink-0" />
      case 'offline': return <WifiOff className="w-3 h-3 text-red-400 shrink-0" />
      default: return <span className="w-2 h-2 rounded-full bg-gray-400 shrink-0" />
    }
  }

  // Compute display label
  const currentProvider = providers.find(p => p.id === workspaceModel)
  const displayLabel = workspaceModelName
    ? workspaceModelName
    : currentProvider?.label ?? workspaceModel

  const handleSelect = (provider: ProviderInfo, modelName?: string) => {
    if (provider.status !== 'online') return
    setWorkspaceModel(provider.id as any)
    setWorkspaceModelName(modelName || provider.models[0] || '')
    setIsOpen(false)
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground',
          'bg-muted px-2 py-1 rounded-full border border-border/50',
          'hover:bg-muted/80 hover:border-border transition-colors cursor-pointer',
        )}
      >
        <Cpu className="h-2.5 w-2.5" />
        <span className="max-w-[120px] truncate">{displayLabel}</span>
        {currentProvider && statusIcon(currentProvider.status)}
        <ChevronDown className={cn('h-2.5 w-2.5 transition-transform', isOpen && 'rotate-180')} />
      </button>

      {isOpen && (
        <div className={cn(
          'absolute top-full right-0 mt-1 z-50 min-w-[240px]',
          'bg-popover border border-border rounded-lg shadow-lg overflow-hidden',
        )}>
          {loading ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">Checking providers…</div>
          ) : providers.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">No providers available</div>
          ) : (
            providers.map(provider => {
              const isAvailable = provider.status === 'online'
              const isSelected = provider.id === workspaceModel

              // For Ollama providers with multiple models, show sub-items
              if (isAvailable && provider.models.length > 1 && (provider.id === 'local' || provider.id === 'cloud-ollama')) {
                return (
                  <div key={provider.id}>
                    <div className="px-3 py-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider border-b border-border/50">
                      {provider.label}
                    </div>
                    {provider.models.map(m => (
                      <button
                        key={m}
                        onClick={() => handleSelect(provider, m)}
                        className={cn(
                          'w-full flex items-center gap-2 px-3 py-2 text-left text-xs',
                          'hover:bg-muted/50 transition-colors',
                          isSelected && workspaceModelName === m && 'bg-violet-500/10 text-violet-300',
                        )}
                      >
                        {statusIcon(provider.status)}
                        <span className="truncate">{m}</span>
                      </button>
                    ))}
                  </div>
                )
              }

              // Single-model providers (Kimi, NVIDIA, etc.)
              return (
                <button
                  key={provider.id}
                  onClick={() => handleSelect(provider)}
                  disabled={!isAvailable}
                  title={provider.reason || undefined}
                  className={cn(
                    'w-full flex items-center gap-2 px-3 py-2 text-left text-xs',
                    'hover:bg-muted/50 transition-colors',
                    !isAvailable && 'opacity-50 cursor-not-allowed',
                    isSelected && 'bg-violet-500/10 text-violet-300',
                  )}
                >
                  {statusIcon(provider.status)}
                  <div className="flex-1 min-w-0">
                    <div className="truncate font-medium">{provider.label}</div>
                    {provider.description && (
                      <div className="text-[10px] text-muted-foreground">{provider.description}</div>
                    )}
                    {!isAvailable && provider.reason && (
                      <div className="text-[10px] text-amber-400/80 mt-0.5">{provider.reason}</div>
                    )}
                  </div>
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
```

### In `WorkspacePanel.tsx` — Replace the Static Bubble

Find this block in the header:

```tsx
<span className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded-full border border-border/50">
  <Cpu className="h-2.5 w-2.5" />
  {workspaceModel === 'kimi' ? 'Kimi K2.5' : workspaceModel === 'qwen3' ? 'Qwen3 235B' : 'Local'}
</span>
```

**Replace with:**

```tsx
import { ModelSelectorDropdown } from './ModelSelectorDropdown'

// ...in the header JSX:
<ModelSelectorDropdown />
```

Remove the old static `<span>` entirely. Do NOT keep both — that would be redundant.

---

## 7. Phase 6 — Frontend: Dynamic Suggestion Banner

### File: `front_end/newjfrontend/components/workspace/WorkspaceSuggestionBanner.tsx`

Replace the hardcoded `MODEL_OPTIONS` array with dynamic provider data.

### Changes:

1. **Remove** the static `MODEL_OPTIONS` constant at the top of the file.

2. **Add** a `useEffect` that fetches `/api/workspace/providers` and builds the
   options dynamically:

```tsx
const [modelOptions, setModelOptions] = useState<Array<{
  value: string
  label: string
  description: string
  modelName: string  // specific model to pass
  available: boolean
}>>([])

useEffect(() => {
  const fetchProviders = async () => {
    try {
      const token = localStorage.getItem('token') || ''
      const res = await fetch('/api/workspace/providers', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) return
      const data = await res.json()
      const options = data.providers
        .map((p: any) => ({
          value: p.id,
          label: p.label,
          description: p.status === 'online'
            ? (p.models[0] || 'Ready')
            : (p.reason || 'Unavailable'),
          modelName: p.models[0] || '',
          available: p.status === 'online',
        }))
        .filter((o: any) => o.available)  // Only show reachable providers
      setModelOptions(options)
    } catch { /* silent */ }
  }
  fetchProviders()
}, [])
```

3. **Update** the model selector rendering in the banner to use `modelOptions`
   instead of the old `MODEL_OPTIONS`.

4. **Update** the launch payload to include `model_name`:

```tsx
// In the launch fetch body:
body: JSON.stringify({
  task_brief: suggestion.task,
  chat_history: chatHistory,
  session_id: currentSession?.id ?? undefined,
  agent_id: workspaceModel,
  model_name: openclawStore.workspaceModelName,  // NEW
}),
```

---

## 8. Phase 7 — Frontend: Agent Graph Label Sync

### File: `front_end/newjfrontend/components/workspace/graph/AgentGraphView.tsx`

The agent graph currently shows generic labels. Update it to display the actual
model name from the store.

In the `AgentGraphWorkspaceStore` component, pull the model name from the store:

```tsx
const { workspaceModel, workspaceModelName } = useOpenClawStore()

// Use workspaceModelName (e.g. "qwen2.5:7b") as the root agent label
// instead of hardcoded "Kimi K2.5" or "Local"
```

In the graph status bar at the top:

```tsx
// Replace:
// <span>{isConnected ? `Live · ${agentCount} agents` : 'Connecting...'}</span>
// With:
<span>
  {runningCount > 0
    ? `Live · ${agentCount} agents · ${workspaceModelName || workspaceModel}`
    : `${agentCount} agents · ${workspaceModelName || workspaceModel}`}
</span>
```

### File: `front_end/newjfrontend/components/workspace/graph/AgentNode.tsx`

If the root agent node displays a model name, ensure it reads from props/store
rather than using a hardcoded string. The root node label should be
`workspaceModelName || workspaceModel` — not "Kimi K2.5".

---

## 9. Phase 8 — Store & Type Updates

### File: `front_end/newjfrontend/stores/openclawStore.ts`

Add `workspaceModelName` to the store:

```typescript
interface OpenClawState {
  // ... existing fields ...
  workspaceModel: 'local' | 'kimi' | 'nvidia-kimi' | 'cloud-ollama'  // UPDATED: renamed 'qwen3' → 'cloud-ollama'
  workspaceModelName: string  // NEW: e.g. "qwen2.5:7b", "kimi-k2.5", "gpt-oss:120b"

  // ... existing actions ...
  setWorkspaceModel: (model: 'local' | 'kimi' | 'nvidia-kimi' | 'cloud-ollama') => void
  setWorkspaceModelName: (name: string) => void  // NEW
}
```

In the store implementation:

```typescript
workspaceModelName: '',

setWorkspaceModelName: (name) => set({ workspaceModelName: name }),
```

### Backward Compatibility Note

The old `qwen3` value maps to `cloud-ollama` in the new scheme. In the
`launch_workspace` handler and `_run_workspace_bg`, keep `qwen3` as an accepted
alias:

```python
# workspace_router.py — launch_workspace:
agent_id = req.agent_id
if agent_id == "qwen3":
    agent_id = "cloud-ollama"  # normalize alias
if agent_id not in ("main", "kimi", "nvidia-kimi", "local", "cloud-ollama"):
    agent_id = "local"  # safe default
```

---

## 10. Phase 9 — Validation & Testing

### Test Matrix

| Scenario | Expected Behavior |
|----------|-------------------|
| Fresh install, no env vars, Ollama running with qwen2.5:7b | `/providers` returns local=online. Workspace auto-selects it. Tasks run. |
| Fresh install, no Ollama, no keys | `/providers` returns all offline. Banner shows "No providers available" with setup instructions. |
| Kimi key in DB, Ollama running | Both shown in dropdown. User can pick either. |
| Kimi key set, Ollama offline | Kimi shown as online, Local shown as offline (grayed + reason). |
| User selects Kimi but key is revoked mid-session | Stream emits error with `fix_hint`. Frontend shows it inline. |
| User selects local, model crashes mid-stream | `ConnectError` caught, error event with fix_hint about VRAM. |
| Cloud Ollama configured, models available | Shown in dropdown with individual model sub-items. |
| Launch with `agent_id=kimi`, no key present | Auto-fallback to local Ollama. Log event warns user. |

### Manual Smoke Test Procedure

1. `docker compose up` with only Ollama and backend running (no Moonshot key).
2. Open Harvis → start a workspace task.
3. Verify the dropdown shows "Local Ollama" with the auto-detected model.
4. Verify the Agents tab shows the actual model name.
5. Kill the Ollama container mid-task → verify the error message includes a fix hint.
6. Add a Moonshot key in Settings → verify the dropdown updates to show Kimi as available.
7. Select Kimi → run a task → verify it streams from Moonshot.

---

## 11. File Change Summary

| File | Action | What Changes |
|------|--------|--------------|
| `python_back_end/workspace/workspace_router.py` | MODIFY | Add `/providers` endpoint, probe functions, `_get_kimi_key`, `model_name` in `LaunchRequest`, updated routing in `_run_workspace_bg`, `qwen3` alias handling |
| `python_back_end/workspace/kimi_workspace.py` | MODIFY | Add `stream_local_ollama_workspace()`, add `fix_hint` to all error events |
| `python_back_end/workspace/openclaw_client.py` | MODIFY | Add `fix_hint` to connection error events |
| `front_end/.../workspace/ModelSelectorDropdown.tsx` | CREATE | New dropdown component |
| `front_end/.../workspace/WorkspacePanel.tsx` | MODIFY | Replace static model bubble with `<ModelSelectorDropdown />` |
| `front_end/.../workspace/WorkspaceSuggestionBanner.tsx` | MODIFY | Remove hardcoded `MODEL_OPTIONS`, fetch from `/providers`, pass `model_name` in launch payload |
| `front_end/.../workspace/graph/AgentGraphView.tsx` | MODIFY | Show actual model name from store |
| `front_end/.../workspace/graph/AgentNode.tsx` | MODIFY | Root agent label reads from store, not hardcoded |
| `front_end/.../stores/openclawStore.ts` | MODIFY | Add `workspaceModelName`, `setWorkspaceModelName`, rename `qwen3` → `cloud-ollama` |

---

## 12. Non-Goals / Anti-Patterns

**DO NOT:**

- ❌ Add a separate settings page for model configuration — the dropdown IS the configuration.
- ❌ Create redundant provider lists — there is ONE source of truth: the `/providers` endpoint. The frontend does not maintain a second hardcoded list.
- ❌ Show provider options that are guaranteed unreachable — offline providers are visible but disabled, not hidden (so users know they exist and what to do).
- ❌ Change the SSE protocol or event format — `OpenClawEvent` stays exactly the same, just with the optional `fix_hint` field added to error data.
- ❌ Modify the K8s/OpenClaw pod configuration — this prompt is about the Harvis backend + frontend only. The OpenClaw container config is a separate concern.
- ❌ Add LiteLLM or any new dependency — this uses Ollama's built-in OpenAI-compatible API directly.
- ❌ Store model selection in the database — it's ephemeral session state in the Zustand store. Users pick on each launch.
- ❌ Duplicate the Ollama probe logic — `_probe_local_ollama` is the single function that checks Ollama. Both `/providers` and fallback logic use it.

---

## Implementation Order

Execute phases in this exact order. Each phase is independently testable.

```
Phase 1 → Backend probe functions + /providers endpoint
Phase 2 → Local Ollama stream function
Phase 3 → Smart routing + fallback in _run_workspace_bg
Phase 4 → fix_hint on all error events
Phase 5 → ModelSelectorDropdown component + WorkspacePanel swap
Phase 6 → Dynamic suggestion banner
Phase 7 → Agent graph label sync
Phase 8 → Store updates
Phase 9 → Test matrix validation
```

**Commit after each phase.** Each phase should compile and not break existing behavior.