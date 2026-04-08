"""
Harvis Workspaces API router.

Endpoints:
  POST /api/workspace/suggest          — Analyze chat, return workspace suggestion
  POST /api/workspace/launch           — Confirm launch, start OpenClaw task
  GET  /api/workspace/stream/{ws_id}   — SSE stream of workspace activity log
  POST /api/workspace/cancel/{ws_id}   — Cancel a running workspace
  GET  /api/workspace/status/{ws_id}   — Get current workspace status
  GET  /api/workspace/history          — List last 20 workspace runs for current user
  GET  /api/workspace/run/{ws_id}/events — Get all stored events for a run
  POST /api/workspace/run/{ws_id}/rerun  — Re-run a previous workspace task

Architecture — Background Task + Queue + DB:
  1. /launch  → inserts workspace_runs row + starts _run_workspace_bg() asyncio.Task
  2. Background task drives client.stream():
       • Saves every event to workspace_events (DB is the authoritative log)
       • Pushes (seq, event) tuples to a per-workspace asyncio.Queue for live SSE
       • Puts a None sentinel when done
       • Keeps running even if the SSE client disconnects
  3. /stream  → two-phase async generator:
       Phase 1: replay all workspace_events from DB  (reconnection, history)
       Phase 2: consume live events from asyncio.Queue (near-real-time streaming)
       SSE disconnect does NOT cancel the background task — sub-agents finish.
  4. /cancel  → signals client.cancel() and cancels the asyncio.Task
"""

import asyncio
import json
import logging
import os
import re
import secrets
import time
import uuid
from typing import Optional

import httpx as _httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth_optimized import get_current_user_optimized
from .openclaw_client import OpenClawClient, OpenClawEvent
from .kimi_workspace import (
    stream_kimi_workspace,
    stream_ollama_cloud_workspace,
    stream_local_ollama_workspace,
    stream_parallel_workspace,
)
from .task_detector import detect_workspace_task

logger = logging.getLogger(__name__)

workspace_router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# ─── Provider probe URLs (read once at module load) ──────────────────────────
_LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
_EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
_EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")
_MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
_NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")


# ─── Provider probe functions ────────────────────────────────────────────────

async def _probe_local_ollama() -> dict:
    """Ping local Ollama and list available models."""
    base = _LOCAL_OLLAMA_URL.rstrip("/")
    tags_url = base.replace("/v1", "") + "/api/tags" if "/v1" in base else f"{base}/api/tags"
    try:
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(5.0)) as client:
            resp = await client.get(tags_url)
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


async def _probe_kimi(pool, user_id: int) -> dict:
    """Check Moonshot API key -- per-user DB row first, then env var."""
    has_key = bool(_MOONSHOT_API_KEY)

    if not has_key and pool:
        try:
            from main import get_user_api_key
            config = await get_user_api_key(pool, user_id, "moonshot")
            if config and config.get("api_key"):
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
        headers: dict[str, str] = {}
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

async def _get_kimi_key(pool, user_id: int) -> str:
    """Return decrypted Moonshot API key -- DB row first, then env var."""
    if pool:
        try:
            from main import get_user_api_key
            config = await get_user_api_key(pool, user_id, "moonshot")
            if config and config.get("api_key"):
                return config["api_key"]
        except Exception as exc:
            logger.debug("Failed to fetch Kimi key from DB: %s", exc)
    return _MOONSHOT_API_KEY


# ─── In-memory workspace registry ─────────────────────────────────────────────
# Maps workspace_id → {client, status, task_brief, session_id, ...}
# Safe for replicas=1 (Ollama co-location requirement keeps backend single-replica).
_workspaces: dict[str, dict] = {}

# Per-workspace asyncio.Queue for live SSE streaming.
# Items: (seq: int, event: OpenClawEvent) while running, None when done.
_workspace_queues: dict[str, asyncio.Queue] = {}

# asyncio.Task references so /cancel can cancel the background task.
_workspace_tasks: dict[str, asyncio.Task] = {}


# ─── Request / Response models ─────────────────────────────────────────────────

class SuggestRequest(BaseModel):
    chat_history: list[dict]


class LaunchRequest(BaseModel):
    task_brief: str
    chat_history: list[dict]
    session_id: Optional[str] = None
    agent_id: str = "main"
    model_name: str = ""
    enable_interactive: bool = False
    live_web: bool = True  # When True, OpenClaw gets X-Live-Web (broad web + browser navigate)
    parallel: bool = True   # When True, planner may split task into parallel sub-agents


class InteractiveEnableRequest(BaseModel):
    workspace_id: str
    ttl_seconds: int = 3600


class WorkspaceStatus(BaseModel):
    workspace_id: str
    status: str
    task_brief: str
    session_id: str


def _looks_like_browser_task(task_brief: str, chat_history: list[dict] | None = None) -> bool:
    """
    Heuristic: should this workspace default to interactive Tier 3?
    True when the user is clearly asking to open a URL in a browser / website context.
    """
    text_parts: list[str] = [task_brief or ""]
    if chat_history:
        for msg in chat_history:
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    text_parts.append(content)
    blob = " ".join(text_parts).lower()

    # Explicit URLs
    if "http://" in blob or "https://" in blob:
        return True

    # Bare domain names (e.g. "gemini.google.com", "github.com/repo")
    if re.search(r'\b[a-z0-9-]+\.[a-z]{2,}(?:\.[a-z]{2,})?(?:/\S*)?', blob):
        # Must also have a browsing-related verb or keyword to avoid false positives
        # on mentions of "file.txt" or "model.py"
        domain_hints = [
            ".com", ".org", ".net", ".io", ".dev", ".ai", ".co",
            ".edu", ".gov", ".app", ".me", ".gg",
        ]
        if any(h in blob for h in domain_hints):
            return True

    # Screenshot/browser keywords — expanded verb list
    keywords = [" browser", "website", "web site", "screenshot", "screen shot", "webpage", "web page"]
    verbs = [
        "open ", "go to ", "navigate to ", "visit ", "take ", "capture ",
        "show ", "check ", "look at ", "browse ", "see ", "view ",
        "screenshot ", "screencap ",
    ]
    if any(k in blob for k in keywords) and any(v in blob for v in verbs):
        return True

    # "screenshot" or "screen shot" alone is strong enough signal
    if "screenshot" in blob or "screen shot" in blob:
        return True

    return False


# ─── Database helpers ──────────────────────────────────────────────────────────

async def _db_create_run(pool, workspace_id: str, user_id: int, session_id: str, task_brief: str) -> None:
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_runs (id, user_id, session_id, task_brief, status, started_at)
                VALUES ($1, $2, $3, $4, 'running', NOW())
                ON CONFLICT (id) DO NOTHING
                """,
                workspace_id, user_id, session_id, task_brief,
            )
    except Exception as exc:
        logger.error("DB: failed to create workspace_run %s: %s", workspace_id, exc)


async def _db_save_event(pool, workspace_id: str, seq: int, event: OpenClawEvent) -> None:
    if pool is None:
        return
    try:
        payload: dict = {}
        for key in (
            "content", "tool", "args", "output", "success", "message",
            "summary", "fix_hint", "model", "parent_run_id",
            "run_id", "agent_label",
        ):
            val = event.data.get(key)
            if val is not None:
                payload[key] = val
        # Always persist sub-agent tracking fields when present on the event object.
        if event.run_id and "run_id" not in payload:
            payload["run_id"] = event.run_id
        if event.agent_label and "agent_label" not in payload:
            payload["agent_label"] = event.agent_label

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_events (workspace_id, seq, event_type, payload, ts)
                VALUES ($1, $2, $3, $4::jsonb, NOW())
                """,
                workspace_id, seq, event.type, json.dumps(payload),
            )
    except Exception as exc:
        logger.error("DB: failed to save event seq=%s workspace=%s: %s", seq, workspace_id, exc)


async def _db_complete_run(
    pool,
    workspace_id: str,
    status: str,
    summary: Optional[str],
    error: Optional[str],
    tool_calls: int,
    event_count: int,
    started_epoch: float,
) -> None:
    if pool is None:
        return
    try:
        duration_ms = int((time.monotonic() - started_epoch) * 1000)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workspace_runs
                SET status        = $2,
                    completed_at  = NOW(),
                    duration_ms   = $3,
                    event_count   = $4,
                    tool_calls    = $5,
                    final_summary = $6,
                    error_message = $7
                WHERE id = $1
                """,
                workspace_id, status, duration_ms, event_count, tool_calls,
                summary, error,
            )
    except Exception as exc:
        logger.error("DB: failed to complete workspace_run %s: %s", workspace_id, exc)


async def _db_enable_interactive(
    pool,
    *,
    workspace_id: str,
    user_id: int,
    ttl_seconds: int = 3600,
) -> str:
    """Enable Tier 3 for one workspace and return capability token."""
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not available")

    ttl = max(300, min(int(ttl_seconds or 3600), 7200))
    token = secrets.token_urlsafe(32)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workspace_web_caps(workspace_id, user_id, interactive_enabled, capability_token, expires_at)
            VALUES ($1, $2, TRUE, $3, NOW() + ($4 * INTERVAL '1 second'))
            ON CONFLICT (workspace_id) DO UPDATE
              SET user_id = EXCLUDED.user_id,
                  interactive_enabled = TRUE,
                  capability_token = EXCLUDED.capability_token,
                  expires_at = EXCLUDED.expires_at
            """,
            workspace_id,
            user_id,
            token,
            ttl,
        )
    return token


# ─── Background task ────────────────────────────────────────────────────────────

async def _run_workspace_bg(workspace_id: str, pool, started_epoch: float) -> None:
    """
    Background asyncio.Task that drives the OpenClaw WebSocket stream to completion.

    This task is independent of the SSE connection.  If the browser disconnects
    (navigates away, Nginx timeout, pod event), the task keeps running so that
    sub-agents can finish, long tool calls complete, and every event gets saved
    to the DB.

    Events are also pushed to the per-workspace asyncio.Queue so the currently
    connected SSE client receives them in near-real-time without polling.
    """
    ws = _workspaces.get(workspace_id)
    if not ws:
        logger.warning("[workspace:%s] _run_workspace_bg: workspace not found", workspace_id)
        return

    client: OpenClawClient = ws["client"]
    task_brief: str = ws["task_brief"]
    chat_history: list[dict] = ws["chat_history"]
    agent_id: str = ws.get("agent_id", "main")
    model_name: str = ws.get("model_name", "")
    queue: asyncio.Queue = _workspace_queues[workspace_id]

    seq = 0
    tool_call_count = 0
    terminal_status = "done"
    final_summary: Optional[str] = None
    final_error: Optional[str] = None

    # ── Select the event stream based on agent_id ────────────────────────────
    event_stream = None
    use_parallel = ws.get("parallel", True)

    if agent_id == "local":
        if use_parallel:
            event_stream = stream_parallel_workspace(
                task_brief, chat_history, model=model_name, provider="local",
            )
        else:
            event_stream = stream_local_ollama_workspace(task_brief, chat_history, model=model_name)

    elif agent_id == "kimi":
        api_key = await _get_kimi_key(pool, ws["user_id"])
        if api_key:
            if use_parallel:
                event_stream = stream_parallel_workspace(
                    task_brief, chat_history, api_key=api_key, provider="kimi",
                )
            else:
                event_stream = stream_kimi_workspace(task_brief, chat_history, api_key)
        else:
            logger.warning("No Kimi API key for user %s — falling back to local Ollama", ws["user_id"])
            fallback_event = OpenClawEvent("log", {
                "message": "Kimi K2.5 API key not found. Falling back to local Ollama.",
            })
            await _db_save_event(pool, workspace_id, seq, fallback_event)
            await queue.put((seq, fallback_event))
            seq += 1
            if use_parallel:
                event_stream = stream_parallel_workspace(
                    task_brief, chat_history, model=model_name, provider="local",
                )
            else:
                event_stream = stream_local_ollama_workspace(task_brief, chat_history, model=model_name)

    elif agent_id == "nvidia-kimi":
        nvidia_key = os.getenv("NVIDIA_API_KEY", "")
        if nvidia_key:
            if use_parallel:
                event_stream = stream_parallel_workspace(
                    task_brief, chat_history, api_key=nvidia_key,
                    api_url="https://integrate.api.nvidia.com/v1", provider="kimi",
                )
            else:
                event_stream = stream_kimi_workspace(
                    task_brief, chat_history, nvidia_key,
                    api_url="https://integrate.api.nvidia.com/v1",
                )
        else:
            logger.warning("No NVIDIA API key — falling back to local Ollama")
            fallback_event = OpenClawEvent("log", {
                "message": "NVIDIA NIM key not found. Falling back to local Ollama.",
            })
            await _db_save_event(pool, workspace_id, seq, fallback_event)
            await queue.put((seq, fallback_event))
            seq += 1
            event_stream = stream_local_ollama_workspace(task_brief, chat_history, model=model_name)

    elif agent_id in ("cloud-ollama", "gpt-oss"):
        if use_parallel:
            event_stream = stream_parallel_workspace(
                task_brief, chat_history, model=model_name or "gpt-oss:120b", provider="cloud-ollama",
            )
        else:
            event_stream = stream_ollama_cloud_workspace(task_brief, chat_history, model=model_name or "gpt-oss:120b")

    else:
        # Default: route through OpenClaw WebSocket
        event_stream = client.stream(
            task_brief,
            chat_history,
            interactive_context=ws.get("interactive_context"),
            live_web=ws.get("live_web", True),
        )

    try:
        async for event in event_stream:
            if event.type == "tool_call":
                tool_call_count += 1

            # Persist first — DB is the authoritative source for replays
            await _db_save_event(pool, workspace_id, seq, event)

            if event.type in ("done", "cancelled", "error"):
                terminal_status = event.type
                ws["status"] = event.type
                if event.type == "done":
                    raw_summary = event.data.get("summary") or ""
                    final_summary = raw_summary
                    # Parse structured result from research/document skills
                    structured = _parse_structured_result(raw_summary)
                    if structured is not None:
                        # Inject structured data into the done event so the frontend
                        # SSE client can render source cards + artifact download cards
                        event.data.update(structured)
                elif event.type == "error":
                    final_error = event.data.get("message")

                # Push to live queue AFTER enriching event data
                await queue.put((seq, event))
                seq += 1
                break

            # Push to live queue for the active SSE connection
            await queue.put((seq, event))
            seq += 1

        logger.info(
            "[workspace:%s] Background task finished: status=%s events=%d tool_calls=%d",
            workspace_id, terminal_status, seq, tool_call_count,
        )

    except asyncio.CancelledError:
        # /cancel was called — save a terminal event so SSE sees it
        terminal_status = "cancelled"
        ws["status"] = "cancelled"
        cancelled_event = OpenClawEvent("cancelled", {"message": "Workspace cancelled."})
        await _db_save_event(pool, workspace_id, seq, cancelled_event)
        await queue.put((seq, cancelled_event))
        seq += 1

    except Exception as exc:
        logger.error("[workspace:%s] Background task error: %s", workspace_id, exc)
        terminal_status = "error"
        final_error = str(exc)
        ws["status"] = "error"
        err_event = OpenClawEvent("error", {
            "message": str(exc),
            "fix_hint": "An unexpected error occurred in the workspace background task. Check backend logs.",
        })
        await _db_save_event(pool, workspace_id, seq, err_event)
        await queue.put((seq, err_event))
        seq += 1

    finally:
        # None sentinel signals SSE generator that the stream has ended
        await queue.put(None)

        await _db_complete_run(
            pool, workspace_id, terminal_status,
            final_summary, final_error, tool_call_count, seq, started_epoch,
        )
        _workspace_tasks.pop(workspace_id, None)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _parse_structured_result(summary: str) -> Optional[dict]:
    """
    If the agent's final summary contains a JSON block with type
    "research_result" or "document_result", extract and return it so the
    frontend can render source cards + artifact download cards.

    Returns None if no structured result is found.
    """
    if not summary:
        return None
    # Look for a JSON code block or bare JSON object in the summary text
    json_pattern = re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', re.DOTALL)
    match = json_pattern.search(summary)
    raw_json = match.group(1) if match else None

    if raw_json is None:
        # Try bare JSON object (agent may not wrap in fences)
        bare = re.search(r'(\{[^{}]*"type"\s*:\s*"(?:research|document)_result"[^{}]*\})', summary, re.DOTALL)
        if bare:
            raw_json = bare.group(1)

    if raw_json is None:
        return None

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    result_type = data.get("type")
    if result_type == "research_result":
        return {
            "structured_type": "research_result",
            "structured_summary": data.get("summary", ""),
            "structured_sources": data.get("sources", []),
            "structured_artifact_id": data.get("artifact_id"),
        }
    if result_type == "document_result":
        return {
            "structured_type": "document_result",
            "structured_title": data.get("title", ""),
            "structured_artifact_id": data.get("artifact_id"),
        }
    return None


_GENERIC_BRIEFS = {
    "execute the task in a harvis workspace",
    "execute task in harvis workspace",
    "workspace",
    "/workspace",
    "",
}


def _resolve_task_brief(brief: str, chat_history: list[dict]) -> str:
    if brief.strip().lower() in _GENERIC_BRIEFS:
        last_user = next(
            (m for m in reversed(chat_history) if m.get("role") == "user"),
            None,
        )
        if last_user and isinstance(last_user.get("content"), str):
            extracted = last_user["content"].strip()
            if extracted:
                return extracted[:500]
    return brief


def _start_workspace(
    workspace_id: str,
    session_id: str,
    task_brief: str,
    chat_history: list[dict],
    agent_id: str,
    user_id: int,
    pool,
    started_epoch: float,
    model_name: str = "",
    interactive_context: Optional[dict] = None,
    live_web: bool = True,
    parallel: bool = True,
) -> OpenClawClient:
    """
    Register a workspace in memory, create its queue, and start the background task.
    Returns the OpenClawClient for the /cancel endpoint.
    """
    client = OpenClawClient(
        workspace_id=workspace_id,
        session_id=session_id,
        agent_id=agent_id,
    )

    _workspaces[workspace_id] = {
        "client": client,
        "status": "running",
        "task_brief": task_brief,
        "session_id": session_id,
        "chat_history": chat_history,
        "user_id": user_id,
        "started_epoch": started_epoch,
        "agent_id": agent_id,
        "model_name": model_name,
        "interactive_context": interactive_context or None,
        "live_web": live_web,
        "parallel": parallel,
    }

    queue: asyncio.Queue = asyncio.Queue()
    _workspace_queues[workspace_id] = queue

    task = asyncio.create_task(
        _run_workspace_bg(workspace_id, pool, started_epoch),
        name=f"workspace-{workspace_id}",
    )
    _workspace_tasks[workspace_id] = task

    return client


async def launch_workspace_internal(
    *,
    request: Request,
    user_id: int,
    task_brief: str,
    chat_history: list[dict] | None = None,
    agent_id: str = "main",
    model_name: str = "",
    session_id: str | None = None,
    enable_interactive: bool = False,
    live_web: bool = True,
) -> dict:
    """
    Launch a workspace run without JWT (internal integrations).

    Intended for trusted server-side integrations (e.g., Discord bot) that already
    run inside the backend process and can supply an owning user_id.
    """
    workspace_id = str(uuid.uuid4())[:8]
    session_id = session_id or f"ws-{workspace_id}"
    chat_history = chat_history or []
    task_brief = _resolve_task_brief(task_brief, chat_history)

    # Auto-enable Tier 3 when the task clearly needs a browser,
    # unless the caller explicitly disabled it.
    if not enable_interactive and _looks_like_browser_task(task_brief, chat_history):
        enable_interactive = True

    pool = getattr(request.app.state, "pg_pool", None)
    started_epoch = time.monotonic()

    interactive_context: Optional[dict] = None
    interactive_enabled = False
    if enable_interactive:
        try:
            cap_token = await _db_enable_interactive(
                pool,
                workspace_id=workspace_id,
                user_id=user_id,
                ttl_seconds=3600,
            )
            interactive_context = {
                "workspace_id": workspace_id,
                "capability_token": cap_token,
            }
            interactive_enabled = True
        except Exception as exc:
            logger.warning(
                "Failed to enable interactive for internal workspace %s: %s",
                workspace_id,
                exc,
            )

    _start_workspace(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=task_brief,
        chat_history=chat_history,
        agent_id=agent_id,
        user_id=user_id,
        pool=pool,
        started_epoch=started_epoch,
        model_name=model_name,
        live_web=live_web,
        interactive_context=interactive_context,
    )

    try:
        await _db_create_run(pool, workspace_id, user_id, session_id, task_brief)
    except Exception as exc:
        logger.error("DB: _db_create_run (internal) raised unexpectedly: %s", exc)

    logger.info(
        "Workspace launched (internal): id=%s user=%s session=%s agent=%s brief=%r",
        workspace_id, user_id, session_id, agent_id, task_brief,
    )

    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "task_brief": task_brief,
        "interactive_enabled": interactive_enabled,
    }


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@workspace_router.post("/suggest")
async def suggest_workspace(
    req: SuggestRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    suggestion = await detect_workspace_task(req.chat_history)
    return suggestion.to_dict()


@workspace_router.get("/providers")
async def list_providers(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Probe all configured LLM providers and return their availability.
    Called by the frontend on mount to populate the workspace model selector.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    providers = []
    providers.append(await _probe_local_ollama())
    providers.append(await _probe_kimi(pool, current_user["id"]))
    providers.append(_probe_nvidia())
    providers.append(await _probe_cloud_ollama())
    return {"providers": providers}


@workspace_router.post("/launch")
async def launch_workspace(
    request: Request,
    req: LaunchRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Launch a new workspace.  Returns workspace_id immediately.

    The OpenClaw task starts as a background asyncio.Task — decoupled from the
    SSE connection.  The frontend connects to /stream/{workspace_id} and receives
    events regardless of when it connects (DB replay + live queue).
    """
    workspace_id = str(uuid.uuid4())[:8]
    session_id = req.session_id or f"ws-{workspace_id}"
    task_brief = _resolve_task_brief(req.task_brief, req.chat_history)
    pool = getattr(request.app.state, "pg_pool", None)

    # Normalize agent_id — accept legacy 'qwen3' as alias for 'cloud-ollama'
    agent_id = req.agent_id
    if agent_id == "qwen3":
        agent_id = "cloud-ollama"
    if agent_id not in ("main", "kimi", "nvidia-kimi", "local", "cloud-ollama", "gpt-oss"):
        agent_id = "local"

    # Auto-enable Tier 3 when the task clearly needs a browser,
    # unless the caller explicitly disabled it.
    enable_interactive = bool(req.enable_interactive)
    if not enable_interactive and _looks_like_browser_task(task_brief, req.chat_history):
        enable_interactive = True

    started_epoch = time.monotonic()

    interactive_context: Optional[dict] = None
    interactive_enabled = False
    if enable_interactive:
        try:
            cap_token = await _db_enable_interactive(
                pool,
                workspace_id=workspace_id,
                user_id=current_user["id"],
                ttl_seconds=3600,
            )
            interactive_context = {
                "workspace_id": workspace_id,
                "capability_token": cap_token,
            }
            interactive_enabled = True
        except Exception as exc:
            logger.warning("Failed to enable interactive for workspace %s: %s", workspace_id, exc)

    _start_workspace(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=task_brief,
        chat_history=req.chat_history,
        agent_id=agent_id,
        user_id=current_user["id"],
        pool=pool,
        started_epoch=started_epoch,
        model_name=req.model_name,
        live_web=req.live_web,
        interactive_context=interactive_context,
        parallel=req.parallel,
    )

    try:
        await _db_create_run(pool, workspace_id, current_user["id"], session_id, task_brief)
    except Exception as exc:
        logger.error("DB: _db_create_run raised unexpectedly: %s", exc)

    logger.info(
        "Workspace launched: id=%s user=%s session=%s agent=%s parallel=%s brief=%r",
        workspace_id, current_user["id"], session_id, agent_id, req.parallel, task_brief,
    )

    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "task_brief": task_brief,
        "interactive_enabled": interactive_enabled,
    }


@workspace_router.post("/interactive/enable")
async def enable_workspace_interactive(
    request: Request,
    req: InteractiveEnableRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Explicitly enable Tier 3 interactive browsing for a workspace."""
    pool = getattr(request.app.state, "pg_pool", None)
    workspace_id = (req.workspace_id or "").strip()
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")

    ws = _workspaces.get(workspace_id)
    if ws is not None and int(ws.get("user_id", -1)) != int(current_user["id"]):
        raise HTTPException(status_code=403, detail="Workspace does not belong to current user")
    if ws is None and pool is not None:
        async with pool.acquire() as conn:
            owner = await conn.fetchval("SELECT user_id FROM workspace_runs WHERE id = $1", workspace_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        if int(owner) != int(current_user["id"]):
            raise HTTPException(status_code=403, detail="Workspace does not belong to current user")

    cap_token = await _db_enable_interactive(
        pool,
        workspace_id=workspace_id,
        user_id=current_user["id"],
        ttl_seconds=req.ttl_seconds,
    )
    if ws is not None:
        ws["interactive_context"] = {
            "workspace_id": workspace_id,
            "capability_token": cap_token,
        }

    return {"workspace_id": workspace_id, "interactive_enabled": True}


@workspace_router.get("/stream/{workspace_id}")
async def stream_workspace(
    workspace_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    SSE stream of workspace activity.  Two-phase generator:

    Phase 1 — DB replay: All events stored in workspace_events are replayed in
      order.  This handles reconnection (tab reload, Nginx timeout, etc.) — the
      frontend always gets a complete picture regardless of when it connects.

    Phase 2 — Live queue: New events are consumed from the per-workspace
      asyncio.Queue as the background task pushes them.  The SSE client
      receives them in near-real-time.

    If the SSE client disconnects (asyncio.CancelledError), the background task
    is NOT cancelled — sub-agents keep running and events keep accumulating in
    the DB for the next reconnection.
    """
    ws = _workspaces.get(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

    pool = getattr(request.app.state, "pg_pool", None)

    async def event_generator():
        last_seq = -1  # highest seq replayed from DB

        try:
            # ── Phase 1: replay stored events from DB ─────────────────────────
            if pool:
                try:
                    async with pool.acquire() as conn:
                        rows = await conn.fetch(
                            """
                            SELECT seq, event_type, payload
                            FROM workspace_events
                            WHERE workspace_id = $1
                            ORDER BY seq ASC
                            """,
                            workspace_id,
                        )
                    for row in rows:
                        last_seq = row["seq"]
                        payload = dict(row["payload"])
                        event_data = {"type": row["event_type"], **payload}
                        yield f"data: {json.dumps(event_data)}\n\n"
                        if row["event_type"] in ("done", "cancelled", "error"):
                            # Terminal event already in DB — we're fully replayed
                            yield 'data: {"type": "stream_end"}\n\n'
                            return
                except Exception as exc:
                    logger.error("DB: replay workspace_events %s: %s", workspace_id, exc)

            # If the workspace is already terminal (DB write may have raced ahead
            # of the status update), close the stream now
            current_status = ws.get("status", "running")
            if current_status in ("done", "cancelled", "error"):
                yield 'data: {"type": "stream_end"}\n\n'
                return

            # ── Phase 2: live events from background task queue ───────────────
            queue = _workspace_queues.get(workspace_id)
            if queue is None:
                yield 'data: {"type": "stream_end"}\n\n'
                return

            while True:
                # Check client disconnect (Nginx / browser navigation)
                if await request.is_disconnected():
                    logger.info(
                        "[workspace:%s] SSE client disconnected — background task continues",
                        workspace_id,
                    )
                    return

                try:
                    item = await asyncio.wait_for(queue.get(), timeout=25)
                except asyncio.TimeoutError:
                    # Heartbeat SSE comment — keeps Nginx from closing a quiet stream
                    yield ": ping\n\n"
                    # Safety: if task ended without a sentinel, break
                    task = _workspace_tasks.get(workspace_id)
                    if task and task.done():
                        break
                    continue

                if item is None:
                    # Sentinel: background task has ended
                    break

                seq_num, event = item

                # Skip events we already replayed from DB (reconnection case)
                if seq_num <= last_seq:
                    continue

                yield event.to_sse()

                if event.type in ("done", "cancelled", "error"):
                    break

        except asyncio.CancelledError:
            # SSE stream cancelled by client — intentionally do NOT cancel the
            # background task so sub-agents and long tool calls keep running.
            logger.info("[workspace:%s] SSE stream cancelled by client", workspace_id)
            return

        yield 'data: {"type": "stream_end"}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@workspace_router.post("/cancel/{workspace_id}")
async def cancel_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Cancel a running workspace. Cancels both the OpenClaw client and the background task."""
    ws = _workspaces.get(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

    # Signal OpenClaw client to stop on its next event
    ws["client"].cancel()

    # Cancel the background asyncio.Task (raises CancelledError inside _run_workspace_bg)
    task = _workspace_tasks.get(workspace_id)
    if task and not task.done():
        task.cancel()

    _workspaces[workspace_id]["status"] = "cancelled"

    logger.info("Workspace cancelled: id=%s user=%s", workspace_id, current_user["id"])
    return {"workspace_id": workspace_id, "status": "cancelled"}


@workspace_router.get("/status/{workspace_id}", response_model=WorkspaceStatus)
async def get_workspace_status(
    workspace_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    ws = _workspaces.get(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")
    return WorkspaceStatus(
        workspace_id=workspace_id,
        status=ws["status"],
        task_brief=ws["task_brief"],
        session_id=ws["session_id"],
    )


@workspace_router.get("/history")
async def list_workspace_history(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"runs": []}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, session_id, task_brief, status,
                       started_at, completed_at, duration_ms,
                       event_count, tool_calls, final_summary, error_message
                FROM workspace_runs
                WHERE user_id = $1
                ORDER BY started_at DESC
                LIMIT 20
                """,
                current_user["id"],
            )
        runs = [dict(r) for r in rows]
        for run in runs:
            for key in ("started_at", "completed_at"):
                if run.get(key) is not None:
                    run[key] = run[key].isoformat()
        return {"runs": runs}
    except Exception as exc:
        logger.error("DB: failed to fetch workspace history for user %s: %s", current_user["id"], exc)
        return {"runs": []}


@workspace_router.post("/run/{source_id}/rerun")
async def rerun_workspace(
    source_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Re-launch a previous workspace run using its stored task_brief.
    Creates a fresh workspace_id + session_id and starts a new background task.
    """
    pool = getattr(request.app.state, "pg_pool", None)

    task_brief: Optional[str] = None
    agent_id = "main"

    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT task_brief FROM workspace_runs WHERE id = $1 AND user_id = $2",
                    source_id, current_user["id"],
                )
            if row:
                task_brief = row["task_brief"]
        except Exception as exc:
            logger.error("DB: failed to fetch task_brief for rerun %s: %s", source_id, exc)

    if not task_brief:
        ws = _workspaces.get(source_id)
        if ws and ws.get("user_id") == current_user["id"]:
            task_brief = ws["task_brief"]
            agent_id = ws.get("agent_id", "main")

    if not task_brief:
        raise HTTPException(status_code=404, detail="Workspace run not found")

    workspace_id = str(uuid.uuid4())[:8]
    session_id = f"ws-{workspace_id}"
    started_epoch = time.monotonic()

    _start_workspace(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=task_brief,
        chat_history=[],
        agent_id=agent_id,
        user_id=current_user["id"],
        pool=pool,
        started_epoch=started_epoch,
    )

    try:
        await _db_create_run(pool, workspace_id, current_user["id"], session_id, task_brief)
    except Exception as exc:
        logger.error("DB: _db_create_run (rerun) raised unexpectedly: %s", exc)

    logger.info(
        "Workspace rerun: source=%s new=%s user=%s brief=%r",
        source_id, workspace_id, current_user["id"], task_brief,
    )
    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "task_brief": task_brief,
    }


@workspace_router.get("/usage/summary")
async def usage_summary(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Return token usage and cost aggregates from proxy_usage_log.

    Response:
      today    — totals for the current calendar day (UTC)
      by_model — per-model totals for the last 30 days, ordered by cost desc
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {
            "today": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0},
            "by_model": [],
        }
    try:
        async with pool.acquire() as conn:
            by_model = await conn.fetch("""
                SELECT model,
                       SUM(tokens_in)::int  AS tokens_in,
                       SUM(tokens_out)::int AS tokens_out,
                       SUM(cost_usd)        AS cost_usd
                FROM proxy_usage_log
                WHERE ts >= NOW() - INTERVAL '30 days'
                GROUP BY model ORDER BY cost_usd DESC
            """)
            today = await conn.fetchrow("""
                SELECT COALESCE(SUM(tokens_in),0)::int  AS tokens_in,
                       COALESCE(SUM(tokens_out),0)::int AS tokens_out,
                       COALESCE(SUM(cost_usd),0)        AS cost_usd
                FROM proxy_usage_log WHERE ts >= CURRENT_DATE
            """)
        return {
            "today": dict(today),
            "by_model": [dict(r) for r in by_model],
        }
    except Exception as exc:
        logger.error("DB: failed to fetch usage summary: %s", exc)
        return {
            "today": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0},
            "by_model": [],
        }


@workspace_router.get("/run/{workspace_id}/events")
async def get_workspace_events(
    workspace_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"events": []}
    try:
        async with pool.acquire() as conn:
            run = await conn.fetchrow(
                "SELECT user_id FROM workspace_runs WHERE id = $1",
                workspace_id,
            )
            if run is None or run["user_id"] != current_user["id"]:
                raise HTTPException(status_code=404, detail="Run not found")
            rows = await conn.fetch(
                """
                SELECT id, workspace_id, seq, event_type, payload, ts
                FROM workspace_events
                WHERE workspace_id = $1
                ORDER BY seq ASC
                """,
                workspace_id,
            )
        events = []
        for r in rows:
            row_dict = dict(r)
            row_dict["ts"] = row_dict["ts"].isoformat() if row_dict.get("ts") else None
            events.append(row_dict)
        return {"events": events}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("DB: failed to fetch events for workspace %s: %s", workspace_id, exc)
        return {"events": []}


@workspace_router.get("/active")
async def get_active_workspace(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Return the latest running workspace for the current user (if any).

    Used for external triggers (e.g., Discord) so the UI can attach to a run that
    started outside the browser.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"active": None}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, session_id, task_brief, status, started_at
                FROM workspace_runs
                WHERE user_id = $1
                  AND status = 'running'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                current_user["id"],
            )
        if not row:
            return {"active": None}
        d = dict(row)
        d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
        # Identify external source from session_id convention (discord-*)
        session_id = d.get("session_id") or ""
        d["source"] = "discord" if session_id.startswith("discord-") else "web"
        return {"active": d}
    except Exception as exc:
        logger.error("DB: failed to fetch active workspace: %s", exc)
        return {"active": None}
