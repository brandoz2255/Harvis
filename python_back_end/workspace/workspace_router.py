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
from .openclaw_client import (
    OpenClawClient,
    OpenClawEvent,
    PROTOCOL_VERSION,
    _CLIENT_ID,
    _CLIENT_MODE,
    _CLIENT_SCOPES,
    _build_device_params,
)
from .openclaw_resolver import resolve_openclaw_config
from .kimi_workspace import (
    stream_kimi_workspace,
    stream_ollama_cloud_workspace,
    stream_local_ollama_workspace,
    stream_parallel_workspace,
)
from .task_detector import detect_workspace_task

logger = logging.getLogger(__name__)

workspace_router = APIRouter(prefix="/api/workspace", tags=["workspace"])
_DEBUG_LOG_PATH = "/home/user/Harvis/.cursor/debug-d007eb.log"


def _append_debug_log(location: str, message: str, data: dict, run_id: str, hypothesis_id: str) -> None:
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "d007eb",
                "id": f"log_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}",
                "timestamp": int(time.time() * 1000),
                "location": location,
                "message": message,
                "data": data,
                "runId": run_id,
                "hypothesisId": hypothesis_id,
            }, separators=(",", ":")) + "\n")
    except Exception:
        pass

# ─── Provider probe URLs (read once at module load) ──────────────────────────
_LOCAL_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
_EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
_EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")
_MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
_NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")


# ─── Provider probe functions ────────────────────────────────────────────────

async def _probe_local_ollama() -> dict:
    """Ping local Ollama and list available models.

    Also merges in the desktop Ollama (`DESKTOP_OLLAMA_URL`) so workspace tasks
    using the "local" provider can see — and select — models that only exist on
    the GPU host. The actual routing is handled by `stream_local_ollama_workspace`,
    which transparently sends desktop-only models to the desktop.
    """
    async def _fetch_tags(base: str) -> list[str]:
        if not base:
            return []
        b = base.rstrip("/")
        tags_url = b.replace("/v1", "") + "/api/tags" if "/v1" in b else f"{b}/api/tags"
        try:
            async with _httpx.AsyncClient(timeout=_httpx.Timeout(5.0)) as client:
                resp = await client.get(tags_url)
            if resp.status_code == 200:
                return [m.get("name") for m in resp.json().get("models", []) if m.get("name")]
        except Exception as exc:
            logger.debug("Ollama probe failed for %s: %s", b, exc)
        return []

    laptop_models = await _fetch_tags(_LOCAL_OLLAMA_URL)
    desktop_url = os.getenv("DESKTOP_OLLAMA_URL", "")
    desktop_models = await _fetch_tags(desktop_url) if desktop_url else []

    # Dedupe: laptop entries first; desktop-only entries appended.
    seen: set[str] = set(laptop_models)
    merged = list(laptop_models)
    for name in desktop_models:
        if name not in seen:
            seen.add(name)
            merged.append(name)

    if merged:
        return {
            "id": "local",
            "label": "Local Ollama" + (" + Desktop 5080" if desktop_models else ""),
            "status": "online",
            "models": merged,
            "reason": None,
        }
    if not laptop_models and not desktop_models:
        # Both unreachable
        return {
            "id": "local",
            "label": "Local Ollama",
            "status": "offline",
            "models": [],
            "reason": "Cannot reach laptop or desktop Ollama.",
        }
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

class WorkspaceLiveBroadcaster:
    """
    Fan-out live workspace events to every subscriber (chat bridge, SSE /stream, research, etc.).
    Replaces a single asyncio.Queue so multiple consumers each receive a full copy of (seq, event)
    items and the terminal None sentinel — no stolen events.
    """

    __slots__ = ("_subscribers",)

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def put(self, item) -> None:
        subs = list(self._subscribers)
        if not subs:
            return
        await asyncio.gather(*(q.put(item) for q in subs))


# Per-workspace live event fan-out (DB remains authoritative for replay).
_workspace_broadcasters: dict[str, WorkspaceLiveBroadcaster] = {}

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
    enable_interactive: bool = True
    live_web: bool = True  # When True, OpenClaw gets X-Live-Web (broad web + browser navigate)
    parallel: bool = True   # When True, planner may split task into parallel sub-agents
    # User-uploaded files (images, PDFs, docs). Each entry should carry at least
    # one of: `url` (e.g. http://backend:8000/api/images/<id>.jpg), `path`
    # (inside a shared volume), or `file_id` (UUID from POST /api/uploads).
    # `name` + `mime_type` are optional hints for the agent.
    attachments: list[dict] = []


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


async def _db_mark_run_orphaned(pool, workspace_id: str, detail: str) -> None:
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workspace_runs
                SET status = 'error',
                    completed_at = COALESCE(completed_at, NOW()),
                    error_message = COALESCE(error_message, $2)
                WHERE id = $1
                  AND status = 'running'
                """,
                workspace_id,
                detail,
            )
    except Exception as exc:
        logger.error("DB: failed to mark orphaned workspace_run %s: %s", workspace_id, exc)


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

    Events are also fan-out via WorkspaceLiveBroadcaster so every connected
    SSE or chat-bridge subscriber receives them in near-real-time without polling.
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
    broadcaster: WorkspaceLiveBroadcaster = _workspace_broadcasters[workspace_id]

    seq = 0
    tool_call_count = 0
    executing_tool_call_count = 0
    _RETRIEVAL_ONLY_TOOLS = {
        "memory_search",
        "memory_search_unified",
        "memory_get",
        "sessions_history",
        "sessions_list",
        "sessions_send",
        "session_status",
        "agents_list",
    }
    terminal_status = "done"
    final_summary: Optional[str] = None
    final_error: Optional[str] = None
    token_chunks: list[str] = []

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
            await broadcaster.put((seq, fallback_event))
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
            await broadcaster.put((seq, fallback_event))
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
                _tname = (event.data or {}).get("tool", "")
                if _tname not in _RETRIEVAL_ONLY_TOOLS:
                    executing_tool_call_count += 1
            elif event.type == "token":
                tok = event.data.get("content")
                if isinstance(tok, str) and tok:
                    token_chunks.append(tok)
                    # Bound memory while still preserving recent output for fallback summary.
                    if len(token_chunks) > 400:
                        token_chunks = token_chunks[-400:]

            # Persist first — DB is the authoritative source for replays
            await _db_save_event(pool, workspace_id, seq, event)

            if event.type in ("done", "cancelled", "error"):
                terminal_status = event.type
                ws["status"] = event.type
                if event.type == "done":
                    raw_summary = event.data.get("summary") or ""
                    if not raw_summary.strip():
                        raw_summary = "".join(token_chunks).strip()
                        if raw_summary:
                            event.data["summary"] = raw_summary

                    # Validator pass — catch fabricated hash-cracking claims
                    # before they reach the user. Deterministic: recomputes
                    # md5/sha1/sha256 of any claimed plaintext and checks
                    # against hashes in the task brief. Suppresses misleading
                    # answers regardless of which way the model rolled.
                    try:
                        validated, was_fabricated = _validate_hash_claims(
                            task_brief, raw_summary,
                            tool_call_count=executing_tool_call_count,
                        )
                        if was_fabricated:
                            logger.warning(
                                "[workspace:%s] Hash-claim fabrication caught + "
                                "replaced. Original summary (first 300 chars): %r",
                                workspace_id, raw_summary[:300],
                            )
                            raw_summary = validated
                            event.data["summary"] = validated
                            event.data["_validator_replaced"] = True
                    except Exception as exc:
                        logger.exception(
                            "[workspace:%s] Hash-claim validator crashed; "
                            "letting original summary through: %s",
                            workspace_id, exc,
                        )

                    final_summary = raw_summary
                    # Parse structured result from research/document skills
                    structured = _parse_structured_result(raw_summary)
                    if structured is not None:
                        # Inject structured data into the done event so the frontend
                        # SSE client can render source cards + artifact download cards
                        event.data.update(structured)
                elif event.type == "error":
                    final_error = event.data.get("message")

                # Fan-out to live subscribers AFTER enriching event data
                await broadcaster.put((seq, event))
                seq += 1
                break

            # Fan-out to all live subscribers (chat bridge, /stream SSE, etc.)
            await broadcaster.put((seq, event))
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
        await broadcaster.put((seq, cancelled_event))
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
        await broadcaster.put((seq, err_event))
        seq += 1

    finally:
        # None sentinel signals each subscriber that the stream has ended
        await broadcaster.put(None)

        await _db_complete_run(
            pool, workspace_id, terminal_status,
            final_summary, final_error, tool_call_count, seq, started_epoch,
        )
        _workspace_tasks.pop(workspace_id, None)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _validate_hash_claims(
    task_brief: str,
    summary: str,
    *,
    tool_call_count: int = 0,
) -> tuple[str, bool]:
    """Catch fabricated plaintext claims for hashes that appear in the task brief.

    Small open-weight models (qwen3:14b, hermes-4) sometimes claim a verified
    plaintext for a hash even when their tool calls returned `verified: false`,
    or invent a fake JSON tool response in their text. This validator catches
    those by recomputing md5/sha1/sha256 of any claimed plaintext and
    comparing against the hashes in the task brief.

    `tool_call_count` is the number of **executing** tool_call events (caller
    excludes memory_search / sessions_history / etc.). If a "verified / cracked /
    matches" claim appears with zero such calls, the run is fabricated by
    construction — no exec happened, so no hash could have been computed.
    Caught deterministically below.

    Returns (possibly_rewritten_summary, was_fabricated). If was_fabricated is
    True, the summary has been replaced with honest-failure text — the caller
    should use the new summary for both the SSE event and DB persistence.

    Rationale: industry-standard "tool receipts" mitigation pattern (NABAOS).
    All directive-based fabrication-mitigation is probabilistic; this is
    deterministic.
    """
    import hashlib
    import re

    if not summary or not task_brief:
        return summary, False

    # Find hex hash candidates in the brief (MD5=32, SHA1=40, SHA224=56,
    # SHA256=64, SHA384=96, SHA512=128). Word-boundary anchored.
    hash_re = re.compile(r"\b([a-f0-9]{32}|[a-f0-9]{40}|[a-f0-9]{56}|[a-f0-9]{64}|[a-f0-9]{96}|[a-f0-9]{128})\b", re.IGNORECASE)
    target_hashes = list({h.lower() for h in hash_re.findall(task_brief)})
    if not target_hashes:
        return summary, False

    # ── Pre-check: zero-tool_call crack-success claims ────────────────────
    # If the run made NO real tool calls but the response narrates a
    # "cracked / verified / matched" outcome, the response is fabricated by
    # construction. No exec happened, so no hash could have been computed,
    # so any matches-claim is invented. Catch this deterministically before
    # we even bother pattern-matching plaintexts.
    success_signal_re = re.compile(
        r"\b("
        r"verified[\s:]+(?:via|with|by|using|true)"
        r"|verified\s*[:=]\s*true"
        r"|cracked\s+(?:with|via|using|by|the\s+hash|successfully)"
        r"|plaintext[\s\S]{0,60}?matches"
        r"|matches\s+(?:the\s+)?target\s+hash"
        r"|hash\s+(?:was\s+)?cracked"
        r"|successfully\s+cracked"
        r"|tiers?_tried"
        # Channel 2 regression patterns (2026-05-19)
        r"|corresponds\s+to\s+(?:the\s+)?plaintext"
        r"|no\s+additional\s+tool\s+calls\s+(?:were\s+)?needed"
        r"|directly\s+computing\s+hashlib"
        r"|running\s+this\s+in\s+python\s+gives"
        r"|I\s+verified\s+by\s+running"
        r")\b",
        re.IGNORECASE,
    )
    if tool_call_count == 0 and success_signal_re.search(summary):
        replacement_lines = [
            "**Could not determine plaintext for the provided hash(es).**",
            "",
            "The agent narrated a successful crack but made **zero tool calls** "
            "during this run — meaning no hash was actually computed or compared. "
            "The output is hallucinated text, not a real result. Suppressing it.",
            "",
            f"Target hash(es): `{target_hashes}`",
            "",
            "Re-run the workspace; the model must emit real `exec` tool calls "
            "(not narrate them in prose). If the agent keeps text-narrating "
            "tool calls instead of emitting them through the tool channel, "
            "swap to a model with stronger tool-use compliance.",
        ]
        return "\n".join(replacement_lines), True

    # ── Stray-hash check ──────────────────────────────────────────────
    # If the summary references a hex hash that does NOT appear in the
    # task_brief, the model is answering a DIFFERENT question (likely
    # pulled from session memory or chat history contamination). This
    # catches the Channel 2 regression where the brief had 1c885e...
    # but the model answered about 5d4140... from a prior turn.
    summary_hashes = {h.lower() for h in hash_re.findall(summary)}
    stray_hashes = summary_hashes - set(target_hashes)
    if stray_hashes and not summary_hashes.intersection(target_hashes):
        replacement_lines = [
            "**Could not determine plaintext for the provided hash(es).**",
            "",
            "The agent's response referenced hash(es) "
            f"`{sorted(stray_hashes)[:3]}` which do NOT appear in the "
            f"original request. The target was `{target_hashes}`. "
            "This is a cross-contamination artifact — the model answered "
            "a different question (likely from a prior conversation turn). "
            "Suppressing.",
            "",
            "Re-run the workspace; the model should only address the "
            "hash(es) in the current request.",
        ]
        return "\n".join(replacement_lines), True

    _FALSE_POSITIVE_PLAINTEXT = frozenset({
        # English prose after "plaintext is …" ("known to cryptographers", etc.)
        "known",
        "unknown",
        "unavailable",
        "uncertain",
        "undetermined",
        "unclear",
        "possible",
        "possibly",
        "unlikely",
        "likely",
        "still",
        "not",
        "yet",
        "never",
        "being",
        "currently",
        "presently",
        "simply",
    })

    # Patterns where the agent claims a specific plaintext.
    # Pull candidates from any of these shapes.
    claim_patterns = [
        # "the plaintext is `m3w`" / "plaintext is m3w" / "plaintext: m3w"
        r"plaintext(?:\s+is|\s*[=:])\s*[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]+)\s*[`'\"\*]+",
        # Reject adjunct capture: "plaintext is known to analysts ..." → not a password literal
        r"plaintext(?:\s+is|\s*[=:])\s+([A-Za-z0-9_\-\.!@#\$%]+)\b(?!\s+to\b)",
        # "plaintext "password" matches" / "plaintext `m3w` matches" — no is/=/: between
        r"plaintext\s+[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]+)\s*[`'\"\*]+\s*(?:matches|matched|=|:|hashes\s+to)",
        # "corresponds to `m3w`" / "corresponds to **m3w**"
        r"corresponds to\s+[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]+)\s*[`'\"\*]+",
        # "Answer: m3w" / "Final answer: m3w" — only when followed by a short token
        r"(?:^|\n)(?:Final\s+)?Answer\s*[:\-]\s*[`'\"\*]*\s*([A-Za-z0-9_\-\.!@#\$%]{1,32})\s*[`'\"\*]*\s*(?:$|\n|\.)",
        # JSON-shaped fake tool response: "plaintext": "m3w"
        r'"plaintext"\s*:\s*"([A-Za-z0-9_\-\.!@#\$%]+)"',
        # "verified plaintext X" / "X (lowercase)" form
        r"verified plaintext[\s:]+[`'\"\*]*([A-Za-z0-9_\-\.!@#\$%]+)[`'\"\*]*",
        # Python hashlib call narrated in prose: `md5("password")` / md5('hello')
        r"(?:md5|sha1|sha256|sha512)\s*\(\s*[`'\"]([A-Za-z0-9_\-\.!@#\$%]+)[`'\"]",
        # "Cracked with X tier ... plaintext Y" / "cracked: plaintext"
        r"[Cc]racked\b[^\.\n]{0,80}?plaintext[\s:]+[`'\"\*]*([A-Za-z0-9_\-\.!@#\$%]+)[`'\"\*]*",
        # "matched: X" / "match: X" in cracker-output-mirroring contexts
        r"(?:^|\s)matched?\s*[:=]\s*[`'\"\*]+\s*([A-Za-z0-9_\-\.!@#\$%]+)\s*[`'\"\*]+",
    ]

    claimed: set[str] = set()
    for pat in claim_patterns:
        for m in re.finditer(pat, summary, re.IGNORECASE | re.MULTILINE):
            cand = (m.group(1) or "").strip().strip("'\"`*.,")
            if not cand or len(cand) > 64:
                continue
            low = cand.lower()
            junk = _FALSE_POSITIVE_PLAINTEXT | {
                "null", "none", "verified", "false", "true", "unknown",
                "n/a", "na", "nil", "undefined", "x", "y", "value",
                "string", "any", "tbd", "todo", "unverified",
            }
            if low in junk:
                continue
            claimed.add(cand)

    if not claimed:
        return summary, False

    # For each target hash, check if any claimed plaintext genuinely hashes to it
    algo_by_len = {
        32:  hashlib.md5,
        40:  hashlib.sha1,
        56:  hashlib.sha224,
        64:  hashlib.sha256,
        96:  hashlib.sha384,
        128: hashlib.sha512,
    }

    any_verified = False
    fabricated_hash_list: list[str] = []
    for h in target_hashes:
        algo = algo_by_len.get(len(h))
        if algo is None:
            continue
        matched_for_this_hash = False
        for cand in claimed:
            computed = algo(cand.encode("utf-8")).hexdigest().lower()
            if computed == h:
                matched_for_this_hash = True
                any_verified = True
                break
        if not matched_for_this_hash:
            fabricated_hash_list.append(h)

    # If at least one claim is genuine, let the response through (don't punish
    # a real crack just because the model also mentioned an unrelated string).
    if any_verified:
        return summary, False

    # Every target hash had claims that don't verify. Replace.
    if tool_call_count > 0:
        tail = (
            "The agent did run tools, but the plaintext token(s) extracted from its "
            "answer do not hash to the target — this is often a false positive from "
            "English prose (e.g. “known”, “unknown”) or a wrong guess. Prefer the "
            "cracker JSON (`verified`, `tiers_tried`) in the original response when "
            "available."
        )
    else:
        tail = (
            "Either the cracker tool returned `verified: false`, or the agent skipped "
            "the verification step. No reliable answer is available from this run."
        )
    replacement_lines = [
        "**Could not determine plaintext for the provided hash(es).**",
        "",
        "The agent produced an answer that did not pass verification: it claimed "
        f"plaintext(s) `{sorted(claimed)}` but md5/sha1/sha256 of these does NOT "
        "match the target hash(es). The claim has been suppressed because it "
        "would otherwise be misleading.",
        "",
        f"Target hash(es): `{fabricated_hash_list}`",
        "",
        tail,
    ]
    return "\n".join(replacement_lines), True


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


# Inline-attachment knobs. Defaults sized for an 8K-context model: an 80KB log
# is roughly 20K tokens, leaving room for the task + reply. Tune via env if
# upstream models have larger windows.
_ATTACH_INLINE_MAX_BYTES = int(os.getenv("HARVIS_ATTACH_INLINE_MAX_BYTES", "80000"))
_ATTACH_DOWNLOAD_HARD_CAP = int(os.getenv("HARVIS_ATTACH_DOWNLOAD_HARD_CAP", str(5 * 1024 * 1024)))
_ATTACH_HEAD_LINES = int(os.getenv("HARVIS_ATTACH_HEAD_LINES", "200"))
_ATTACH_TAIL_LINES = int(os.getenv("HARVIS_ATTACH_TAIL_LINES", "200"))


def _is_text_like(name: str, mime: str) -> bool:
    lower_name = name.lower()
    lower_mime = mime.lower()
    return (
        lower_mime.startswith("text/")
        or "json" in lower_mime
        or "csv" in lower_mime
        or "xml" in lower_mime
        or "yaml" in lower_mime
        or "toml" in lower_mime
        or "graphql" in lower_mime
        or "ipynb" in lower_mime
        or lower_name.endswith((
            # Logs / docs
            ".log", ".txt", ".md", ".mdx", ".rst", ".adoc", ".org", ".tex",
            # Data
            ".csv", ".tsv", ".json", ".ndjson", ".jsonl", ".xml",
            ".yaml", ".yml", ".toml", ".sql", ".graphql", ".gql", ".proto",
            # Diffs
            ".diff", ".patch",
            # Config
            ".ini", ".conf", ".cfg", ".properties", ".env",
            # Web
            ".html", ".htm", ".css", ".scss", ".sass", ".less",
            ".vue", ".svelte",
            # Code
            ".py", ".js", ".ts", ".tsx", ".jsx",
            ".go", ".rs", ".rb", ".php", ".java", ".kt", ".swift",
            ".scala", ".dart", ".lua", ".pl", ".r", ".cs",
            ".c", ".h", ".cpp", ".hpp", ".cc", ".m", ".mm",
            # Shell
            ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat",
            # Notebooks (treated as text-like — they're JSON)
            ".ipynb",
        ))
    )


def _is_image_like(name: str, mime: str) -> bool:
    lower_name = name.lower()
    lower_mime = mime.lower()
    return lower_mime.startswith("image/") or lower_name.endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".bmp")
    )


async def _download_text_attachment(url: str) -> Optional[str]:
    """Fetch up to _ATTACH_DOWNLOAD_HARD_CAP bytes from `url`, return decoded text.

    Returns None on any error (network, decode, oversize). The caller falls back
    to the URL-only behavior so the agent can still try to fetch it itself.
    """
    try:
        async with _httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(
                    "_download_text_attachment: HTTP %s for %s", resp.status_code, url[:120]
                )
                return None
            data = resp.content
            if len(data) > _ATTACH_DOWNLOAD_HARD_CAP:
                logger.warning(
                    "_download_text_attachment: %d bytes exceeds hard cap %d, skipping inline",
                    len(data), _ATTACH_DOWNLOAD_HARD_CAP,
                )
                return None
        # Try utf-8 first, fall back to latin-1 (lossless single-byte mapping).
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.warning("_download_text_attachment: failed for %s: %s", url[:120], exc)
        return None


def _format_inlined_text(name: str, content: str) -> tuple[str, bool]:
    """Build the <<<FILE_BEGIN ... FILE_END>>> block. Returns (block, was_truncated)."""
    if len(content.encode("utf-8", errors="ignore")) <= _ATTACH_INLINE_MAX_BYTES:
        return (
            f"<<<FILE_BEGIN {name}>>>\n{content}\n<<<FILE_END {name}>>>",
            False,
        )
    # Too big — head + tail.
    lines = content.splitlines()
    if len(lines) <= _ATTACH_HEAD_LINES + _ATTACH_TAIL_LINES:
        # Few long lines; fall back to byte-truncate from each end.
        head_chunk = content[: _ATTACH_INLINE_MAX_BYTES // 2]
        tail_chunk = content[-_ATTACH_INLINE_MAX_BYTES // 2 :]
        body = (
            head_chunk
            + f"\n\n…[TRUNCATED {len(content) - len(head_chunk) - len(tail_chunk)} bytes]…\n\n"
            + tail_chunk
        )
    else:
        head = "\n".join(lines[: _ATTACH_HEAD_LINES])
        tail = "\n".join(lines[-_ATTACH_TAIL_LINES :])
        skipped = len(lines) - _ATTACH_HEAD_LINES - _ATTACH_TAIL_LINES
        body = (
            f"{head}\n…[TRUNCATED {skipped} middle lines — full file at the URL above]…\n{tail}"
        )
    return (
        f"<<<FILE_BEGIN {name} (truncated; full size {len(content)} bytes / {len(lines)} lines)>>>\n"
        f"{body}\n<<<FILE_END {name}>>>",
        True,
    )


async def _prepend_attachments(brief: str, attachments: list[dict]) -> str:
    """Prepend a machine-readable [Attached files] block so the agent can find
    the user-uploaded image/PDF/etc.

    For text-like attachments with a fetchable URL, the file content is inlined
    directly into the brief (head+tail if oversize). This makes log/CSV/text
    analysis dumb-model-proof — even an agent that ignores skills sees the data
    in its context. The harvis-image skill still owns the image path.
    """
    if not attachments:
        return brief
    image_like = False
    text_like = False
    any_inlined = False
    listing: list[str] = []
    inline_blocks: list[str] = []

    for i, a in enumerate(attachments, start=1):
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or f"file{i}")
        mime = str(a.get("mime_type") or "application/octet-stream")
        if _is_image_like(name, mime):
            image_like = True
        is_text = _is_text_like(name, mime)
        if is_text:
            text_like = True

        loc_parts: list[str] = []
        if a.get("url"):
            loc_parts.append(f"url={a['url']}")
        if a.get("path"):
            loc_parts.append(f"path={a['path']}")
        if a.get("file_id"):
            loc_parts.append(f"file_id={a['file_id']}")
        loc = " ".join(loc_parts) or "(no location)"
        listing.append(f"{i}. {name} — {mime} — {loc}")

        # Inline text-like attachments so the agent doesn't need to curl.
        if is_text and a.get("url"):
            content = await _download_text_attachment(a["url"])
            if content is not None:
                block, _ = _format_inlined_text(name, content)
                inline_blocks.append(block)
                any_inlined = True

    lines: list[str] = ["[Attached files from the user]"] + listing
    if inline_blocks:
        lines.append("")
        lines.append("[Inlined file contents — answer directly from these; the data is here]")
        lines.extend(inline_blocks)
    lines.append("")
    lines.append("[Task]")
    lines.append(brief)
    lines.append("")
    lines.append("[Execution rules]")
    lines.append("- ALWAYS reply in English unless the user explicitly writes to you in another language.")
    lines.append("- Attached files are part of the task. Inspect them before answering.")
    if image_like:
        lines.append("- At least one attached file is an image. Read `/skills-shared/harvis-image/SKILL.md` first, then use tools to inspect the image.")
    if text_like and any_inlined:
        lines.append(
            "- THE FILE CONTENT IS ALREADY HERE. The text between `<<<FILE_BEGIN name>>>` and "
            "`<<<FILE_END name>>>` markers under [Inlined file contents] above IS the file. "
            "Treat it as if it were on disk — read it, search it, count it, quote it directly. "
            "Do NOT say you can't find the file, do NOT ask the user to paste it, do NOT try to "
            "`ls` or `curl` for it. The answer comes from the inlined block, not from any tool."
        )
    elif text_like:
        lines.append("- At least one attached file is a text/log/data file. Read `/skills-shared/harvis-file/SKILL.md` first, then use tools to extract the answer.")
    lines.append("- Replies like `Copy that.`, `Standing by.`, `On it.`, or any acknowledgment without tool use or extracted findings are invalid.")
    lines.append("- If the file is unreadable, ambiguous, or the answer cannot be determined confidently after using tools, say that explicitly and explain the blocker in one sentence. Do not guess.")
    return "\n".join(lines)


async def _start_workspace(
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
    # Resolve which OpenClaw instance this user routes to
    config = await resolve_openclaw_config(pool, user_id)

    logger.info(
        "workspace launch: user=%s mode=%s url=%s prefix=%r",
        user_id, config.mode, config.url, config.workspace_prefix,
    )

    client = OpenClawClient(
        workspace_id=workspace_id,
        session_id=session_id,
        agent_id=agent_id,
        gateway_url=config.url,
        gateway_token=config.token,
        workspace_prefix=config.workspace_prefix,
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
        # Two-mode tracking
        "mode": config.mode,
        "allowed_capabilities": config.allowed_capabilities,
    }

    broadcaster = WorkspaceLiveBroadcaster()
    _workspace_broadcasters[workspace_id] = broadcaster

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
    enable_interactive: bool = True,
    live_web: bool = True,
    attachments: list[dict] | None = None,
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
    task_brief = await _prepend_attachments(task_brief, attachments or [])
    _append_debug_log(
        "workspace_router.py:launch_workspace_internal",
        "launch_workspace_attachment_prompt",
        {
            "workspace_id": workspace_id,
            "attachment_count": len(attachments or []),
            "task_preview": task_brief[:400],
        },
        "run_attachment_prompt",
        "H_attachment_act_first",
    )

    # Tier 3 interactive browsing is always on for workspace launches.
    # Keep the arg for backward-compatible callers, but ignore opt-out.
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

    await _start_workspace(
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
    task_brief = await _prepend_attachments(task_brief, req.attachments or [])
    pool = getattr(request.app.state, "pg_pool", None)

    # Normalize agent_id — accept legacy 'qwen3' as alias for 'cloud-ollama'
    agent_id = req.agent_id
    if agent_id == "qwen3":
        agent_id = "cloud-ollama"
    if agent_id not in ("main", "kimi", "nvidia-kimi", "local", "cloud-ollama", "gpt-oss"):
        agent_id = "local"

    # Tier 3 interactive browsing is always on for workspace launches.
    # Keep req.enable_interactive for backward-compatible clients.
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

    await _start_workspace(
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

    Phase 2 — Live fan-out: This handler subscribes to the per-workspace
      WorkspaceLiveBroadcaster and receives the same events as the chat bridge
      and other subscribers, in near-real-time.

    If the SSE client disconnects (asyncio.CancelledError), the background task
    is NOT cancelled — sub-agents keep running and events keep accumulating in
    the DB for the next reconnection.
    """
    ws = _workspaces.get(workspace_id)
    if not ws:
        _append_debug_log(
            "workspace_router.py:stream_workspace",
            "stream_workspace_missing_in_memory",
            {"workspace_id": workspace_id, "known_workspaces": list(_workspaces.keys())[:20]},
            "run_workspace_active_follow",
            "H_active_orphan",
        )
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
                        raw_payload = row["payload"]
                        # asyncpg returns JSONB as str by default (no global
                        # type codec is registered); tolerate both forms.
                        if isinstance(raw_payload, dict):
                            payload = raw_payload
                        elif isinstance(raw_payload, str):
                            try:
                                parsed = json.loads(raw_payload)
                                payload = parsed if isinstance(parsed, dict) else {}
                            except Exception:
                                payload = {}
                        else:
                            payload = {}
                        # region agent log
                        try:
                            import os as _os, time as _time, uuid as _uuid
                            _log_path = "/tmp/debug-d007eb.log"
                            _os.makedirs(_os.path.dirname(_log_path), exist_ok=True)
                            with open(_log_path, "a", encoding="utf-8") as _f:
                                _f.write(json.dumps({
                                    "sessionId": "d007eb",
                                    "id": f"log_{int(_time.time()*1000)}_{_uuid.uuid4().hex[:8]}",
                                    "timestamp": int(_time.time()*1000),
                                    "location": "workspace_router.py:stream_workspace:replay",
                                    "message": "sse_replay_row",
                                    "data": {
                                        "workspace_id": workspace_id,
                                        "seq": last_seq,
                                        "event_type": row["event_type"],
                                        "raw_type": type(raw_payload).__name__,
                                    },
                                    "runId": "run_sse_replay",
                                    "hypothesisId": "H8",
                                }, separators=(",", ":")) + "\n")
                        except Exception:
                            pass
                        # endregion
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

            # ── Phase 2: live events (subscriber queue — full fan-out from broadcaster) ──
            broadcaster = _workspace_broadcasters.get(workspace_id)
            if broadcaster is None:
                yield 'data: {"type": "stream_end"}\n\n'
                return

            live_queue = broadcaster.subscribe()

            try:
                while True:
                    # Check client disconnect (Nginx / browser navigation)
                    if await request.is_disconnected():
                        logger.info(
                            "[workspace:%s] SSE client disconnected — background task continues",
                            workspace_id,
                        )
                        return

                    try:
                        item = await asyncio.wait_for(live_queue.get(), timeout=25)
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

            finally:
                broadcaster.unsubscribe(live_queue)

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


async def cancel_workspace_internal(
    workspace_id: str,
    *,
    audit_actor: str = "internal",
) -> dict:
    """Cancel a running workspace from non-HTTP contexts (Discord bot, etc.).

    Same effect as POST /cancel/{workspace_id}: marks status, signals the
    OpenClaw client cancel flag (which schedules ws.close() so the blocked
    async-for unblocks), cancels the background asyncio.Task, and waits up
    to 6s for cleanup so callers can report a truly-idle workspace.

    Returns one of:
      {"status": "cancelled", "workspace_id": ..., "wait_outcome": ...}
      {"status": "not_found", "workspace_id": ...}
      {"status": "already_terminal", "current": "done|cancelled|error", "workspace_id": ...}
    """
    ws = _workspaces.get(workspace_id)
    if not ws:
        return {"status": "not_found", "workspace_id": workspace_id}

    current = ws.get("status")
    if current in ("done", "cancelled", "error"):
        return {
            "status": "already_terminal",
            "current": current,
            "workspace_id": workspace_id,
        }

    # Mark state first so any concurrent handler sees the intent immediately.
    _workspaces[workspace_id]["status"] = "cancelled"

    client_cancel_err: Optional[str] = None
    try:
        ws["client"].cancel()
    except Exception as exc:
        client_cancel_err = str(exc)
        logger.warning("cancel_workspace_internal: client.cancel failed: %s", exc)

    task = _workspace_tasks.get(workspace_id)
    task_existed = task is not None
    task_was_done = bool(task.done()) if task else True
    wait_outcome = "no-task"
    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=6.0)
            wait_outcome = "completed"
        except asyncio.CancelledError:
            wait_outcome = "cancelled-error"
        except asyncio.TimeoutError:
            wait_outcome = "timeout"
        except Exception as exc:
            wait_outcome = f"error:{exc}"
            logger.warning(
                "cancel_workspace_internal: background task raised during cleanup: %s",
                exc,
            )

    logger.info(
        "Workspace cancelled (internal): id=%s actor=%s outcome=%s",
        workspace_id, audit_actor, wait_outcome,
    )
    return {
        "status": "cancelled",
        "workspace_id": workspace_id,
        "wait_outcome": wait_outcome,
        "task_existed": task_existed,
        "task_was_done": task_was_done,
        "client_cancel_err": client_cancel_err,
    }


@workspace_router.post("/cancel/{workspace_id}")
async def cancel_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Cancel a running workspace. Force-closes the OpenClaw websocket and
    cancels the background task, then waits briefly for cleanup so the
    response only returns once the workspace is truly idle."""
    result = await cancel_workspace_internal(
        workspace_id,
        audit_actor=f"user:{current_user.get('id')}",
    )
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

    _client_cancel_err = result.get("client_cancel_err")
    _task_existed = result.get("task_existed", False)
    _task_was_done = result.get("task_was_done", True)
    _wait_outcome = result.get("wait_outcome", "n/a")

    # region agent log
    try:
        import json as _json, os as _os, time as _time, uuid as _uuid
        _log_path = "/tmp/debug-d007eb.log"
        _os.makedirs(_os.path.dirname(_log_path), exist_ok=True)
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(_json.dumps({
                "sessionId": "d007eb",
                "id": f"log_{int(_time.time()*1000)}_{_uuid.uuid4().hex[:8]}",
                "timestamp": int(_time.time()*1000),
                "location": "workspace_router.py:cancel_workspace",
                "message": "cancel_workspace_completed",
                "data": {
                    "workspace_id": workspace_id,
                    "user_id": current_user.get("id"),
                    "task_existed": _task_existed,
                    "task_was_done": _task_was_done,
                    "wait_outcome": _wait_outcome,
                    "client_cancel_err": _client_cancel_err,
                },
                "runId": "run_cancel_button",
                "hypothesisId": "H_cancel",
            }, separators=(",", ":")) + "\n")
    except Exception:
        pass
    # endregion

    return {"workspace_id": workspace_id, "status": result["status"]}


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

    await _start_workspace(
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
            rows = await conn.fetch(
                """
                SELECT id, session_id, task_brief, status, started_at
                FROM workspace_runs
                WHERE user_id = $1
                  AND status = 'running'
                ORDER BY started_at DESC
                LIMIT 10
                """,
                current_user["id"],
            )
        if not rows:
            return {"active": None}
        for row in rows:
            d = dict(row)
            in_memory = d["id"] in _workspaces
            _append_debug_log(
                "workspace_router.py:get_active_workspace",
                "active_workspace_candidate",
                {
                    "workspace_id": d["id"],
                    "session_id": d.get("session_id"),
                    "status": d.get("status"),
                    "in_memory": in_memory,
                },
                "run_workspace_active_follow",
                "H_active_orphan",
            )
            if not in_memory:
                await _db_mark_run_orphaned(
                    pool,
                    d["id"],
                    "Workspace was left in running state but no live in-memory task exists.",
                )
                continue
            d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
            session_id = d.get("session_id") or ""
            d["source"] = "discord" if session_id.startswith("discord-") else "web"
            return {"active": d}
        return {"active": None}
    except Exception as exc:
        logger.error("DB: failed to fetch active workspace: %s", exc)
        return {"active": None}


# ── BYO OpenClaw config endpoints ────────────────────────────────────────────

class BYOConfigSaveRequest(BaseModel):
    mode: str = "bundled"         # "bundled" or "byo"
    byo_url: Optional[str] = None
    byo_token: Optional[str] = None


class BYOConfigVerifyRequest(BaseModel):
    url: str
    token: Optional[str] = None


@workspace_router.get("/config/openclaw")
async def get_openclaw_mode_config(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Get the current user's OpenClaw mode configuration."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        return {
            "mode": "bundled",
            "byo_url": None,
            "byo_verified_at": None,
            "byo_last_error": None,
            "byo_token_saved": False,
        }

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT mode, byo_url, byo_verified_at, byo_last_error,
                       (byo_token_encrypted IS NOT NULL AND length(byo_token_encrypted) > 0) AS byo_token_saved
                FROM user_openclaw_config
                WHERE user_id = $1
                """,
                current_user["id"],
            )
    except Exception as exc:
        logger.error("get_openclaw_mode_config: DB error for user %s: %s", current_user["id"], exc)
        return {
            "mode": "bundled",
            "byo_url": None,
            "byo_verified_at": None,
            "byo_last_error": None,
            "byo_token_saved": False,
        }

    if not row:
        return {
            "mode": "bundled",
            "byo_url": None,
            "byo_verified_at": None,
            "byo_last_error": None,
            "byo_token_saved": False,
        }

    return {
        "mode": row["mode"],
        "byo_url": row["byo_url"],
        "byo_verified_at": row["byo_verified_at"].isoformat() if row["byo_verified_at"] else None,
        "byo_last_error": row["byo_last_error"],
        "byo_token_saved": bool(row["byo_token_saved"]),
    }


@workspace_router.post("/config/openclaw")
async def save_openclaw_mode_config(
    req: BYOConfigSaveRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Save the user's OpenClaw mode configuration."""
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    if req.mode not in ("bundled", "byo"):
        raise HTTPException(status_code=400, detail="mode must be 'bundled' or 'byo'")

    byo_url = (req.byo_url or "").strip() or None
    byo_token = (req.byo_token or "").strip()

    if req.mode == "byo" and not byo_url:
        raise HTTPException(status_code=400, detail="BYO mode requires a gateway URL")

    # Encrypt the BYO token if provided
    encrypted_token = None
    if byo_token:
        from main import encrypt_api_key
        encrypted_token = encrypt_api_key(byo_token)

    try:
        async with pool.acquire() as conn:
            existing_has_token = bool(
                await conn.fetchval(
                    """
                    SELECT (byo_token_encrypted IS NOT NULL AND length(byo_token_encrypted) > 0)
                    FROM user_openclaw_config
                    WHERE user_id = $1
                    """,
                    current_user["id"],
                )
            )
            if req.mode == "byo" and not encrypted_token and not existing_has_token:
                raise HTTPException(
                    status_code=400,
                    detail="Gateway token is required the first time you configure BYO mode",
                )

            await conn.execute(
                """
                INSERT INTO user_openclaw_config (user_id, mode, byo_url, byo_token_encrypted)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    byo_url = COALESCE(EXCLUDED.byo_url, user_openclaw_config.byo_url),
                    byo_token_encrypted = COALESCE(EXCLUDED.byo_token_encrypted, user_openclaw_config.byo_token_encrypted),
                    updated_at = NOW()
                """,
                current_user["id"],
                req.mode,
                byo_url,
                encrypted_token,
            )
            row = await conn.fetchrow(
                """
                SELECT mode, byo_url, byo_verified_at, byo_last_error,
                       (byo_token_encrypted IS NOT NULL AND length(byo_token_encrypted) > 0) AS byo_token_saved
                FROM user_openclaw_config
                WHERE user_id = $1
                """,
                current_user["id"],
            )
        return {
            "ok": True,
            "mode": row["mode"] if row else req.mode,
            "byo_url": row["byo_url"] if row else byo_url,
            "byo_verified_at": row["byo_verified_at"].isoformat() if row and row["byo_verified_at"] else None,
            "byo_last_error": row["byo_last_error"] if row else None,
            "byo_token_saved": bool(row["byo_token_saved"]) if row else bool(encrypted_token),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("save_openclaw_mode_config: DB error for user %s: %s", current_user["id"], exc)
        raise HTTPException(status_code=500, detail="Failed to save configuration")


@workspace_router.post("/config/byo/verify")
async def verify_byo_config(
    req: BYOConfigVerifyRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Attempt to connect to the user's OpenClaw and verify auth + protocol.
    Returns ok=true on success, ok=false with error/hint on failure.
    On success, stores verified timestamp (and token if provided).
    """
    import websockets as _ws

    if not req.url.startswith(("ws://", "wss://")):
        return {"ok": False, "error": "URL must start with ws:// or wss://", "hint": "Use ws://localhost:18789 or similar."}

    token = (req.token or "").strip()
    if not token:
        pool = getattr(request.app.state, "pg_pool", None)
        if pool:
            try:
                async with pool.acquire() as conn:
                    enc = await conn.fetchval(
                        """
                        SELECT byo_token_encrypted
                        FROM user_openclaw_config
                        WHERE user_id = $1
                        """,
                        current_user["id"],
                    )
                if enc:
                    from main import decrypt_api_key
                    token = decrypt_api_key(enc) or ""
            except Exception as exc:
                logger.error("verify_byo_config: failed loading saved token for user %s: %s", current_user["id"], exc)
        if not token:
            return {
                "ok": False,
                "error": "No gateway token provided",
                "hint": "Enter your OpenClaw gateway token or save one first.",
            }

    try:
        ws = await _ws.connect(
            req.url,
            ping_interval=10,
            ping_timeout=5,
            open_timeout=10,
        )

        # Read the challenge
        import json as _json
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        challenge = _json.loads(raw)
        if not (challenge.get("type") == "event" and challenge.get("event") == "connect.challenge"):
            await ws.close()
            return {"ok": False, "error": "Unexpected response from server", "hint": "This endpoint does not appear to be an OpenClaw gateway."}

        nonce = challenge.get("payload", {}).get("nonce", "")
        if not nonce:
            await ws.close()
            return {"ok": False, "error": "Missing challenge nonce", "hint": "Gateway challenge payload was invalid."}

        req_id = "verify-connect"
        await ws.send(_json.dumps({
            "type": "req",
            "id": req_id,
            "method": "connect",
            "params": {
                "minProtocol": PROTOCOL_VERSION,
                "maxProtocol": PROTOCOL_VERSION,
                "client": {
                    "id": _CLIENT_ID,
                    "version": "1.0.0",
                    "platform": "linux",
                    "mode": _CLIENT_MODE,
                },
                "caps": ["tool-events"],
                "role": "operator",
                "scopes": _CLIENT_SCOPES,
                "auth": {"token": token},
                "device": _build_device_params(nonce, token),
            },
        }))
        ack_raw = await asyncio.wait_for(ws.recv(), timeout=10)
        ack = _json.loads(ack_raw)
        if ack.get("type") != "res" or not ack.get("ok"):
            await ws.close()
            err_msg = (
                (ack.get("error") or {}).get("message")
                or "Gateway rejected connect/auth handshake"
            )
            await _set_byo_error(request, current_user["id"], str(err_msg)[:500])
            return {
                "ok": False,
                "error": f"Authentication failed: {err_msg}",
                "hint": "Check your gateway token and ensure OpenClaw allows operator access.",
            }

        # Gateway auth + protocol handshake succeeded.
        await ws.close()

        # Update verification timestamp in DB
        pool = getattr(request.app.state, "pg_pool", None)
        if pool:
            from main import encrypt_api_key
            encrypted_token = encrypt_api_key(token)
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO user_openclaw_config (user_id, mode, byo_url, byo_token_encrypted, byo_verified_at, byo_last_error)
                        VALUES ($1, 'byo', $2, $3, NOW(), NULL)
                        ON CONFLICT (user_id) DO UPDATE SET
                            byo_url = EXCLUDED.byo_url,
                            byo_token_encrypted = EXCLUDED.byo_token_encrypted,
                            byo_verified_at = NOW(),
                            byo_last_error = NULL,
                            updated_at = NOW()
                        """,
                        current_user["id"],
                        req.url,
                        encrypted_token,
                    )
            except Exception as exc:
                logger.error("verify_byo_config: DB update failed for user %s: %s", current_user["id"], exc)

        return {"ok": True, "message": "OpenClaw reachable, auth handshake verified", "byo_token_saved": True}

    except asyncio.TimeoutError:
        await _set_byo_error(request, current_user["id"], "Connection timed out")
        return {
            "ok": False,
            "error": "Connection timed out",
            "hint": "Check firewall and port forwarding. WSL users may need to bind to 0.0.0.0.",
        }
    except ConnectionRefusedError:
        await _set_byo_error(request, current_user["id"], "Connection refused")
        return {
            "ok": False,
            "error": "Connection refused",
            "hint": "OpenClaw is not running at that URL. Check `openclaw gateway status`.",
        }
    except Exception as exc:
        error_msg = str(exc)[:500]
        await _set_byo_error(request, current_user["id"], error_msg)
        return {
            "ok": False,
            "error": error_msg,
            "hint": _verification_hint(exc),
        }


def _verification_hint(exc: Exception) -> str:
    msg = str(exc).lower()
    if "connection refused" in msg or "econnrefused" in msg:
        return "OpenClaw is not running at that URL. Check `openclaw gateway status`."
    if "timeout" in msg:
        return "Connection timed out. Check firewall and port forwarding."
    if "401" in msg or "unauthorized" in msg or "invalid token" in msg:
        return "Gateway token is invalid. Regenerate it and paste the new value."
    if "handshake" in msg:
        return "Protocol version mismatch. Update OpenClaw to a compatible version."
    return "See OpenClaw logs for details."


async def _set_byo_error(request, user_id: int, error: str) -> None:
    pool = getattr(request.app.state, "pg_pool", None)
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE user_openclaw_config
                SET byo_last_error = $2, updated_at = NOW()
                WHERE user_id = $1
                """,
                user_id,
                error[:500],
            )
    except Exception:
        pass

