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

Flow:
  1. After each chat response, frontend POSTs to /suggest with the chat history.
  2. If should_suggest=true, frontend shows "Launch Workspace?" banner.
  3. User confirms → frontend POSTs to /launch → gets workspace_id back.
  4. Frontend connects to /stream/{workspace_id} (SSE) and renders the activity panel.
  5. User can hit Cancel → frontend POSTs to /cancel/{workspace_id}.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth_optimized import get_current_user_optimized
from .openclaw_client import OpenClawClient
from .task_detector import detect_workspace_task

logger = logging.getLogger(__name__)

workspace_router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# ─── In-memory workspace registry ────────────────────────────────────────────
# Maps workspace_id → {client, status, task_brief, session_id, started_epoch}
# For production with multiple backend replicas, move this to Redis.
# Currently safe because the backend Deployment has replicas=1 for the
# Ollama co-location requirement.
_workspaces: dict[str, dict] = {}


# ─── Request / Response models ────────────────────────────────────────────────

class SuggestRequest(BaseModel):
    chat_history: list[dict]           # [{role, content}, ...]


class LaunchRequest(BaseModel):
    task_brief: str                    # From the /suggest response
    chat_history: list[dict]           # Full chat history for context
    session_id: Optional[str] = None  # Pass the same session_id to resume
    agent_id: str = "main"            # OpenClaw agent: "main" (local Ollama) or "kimi"


class WorkspaceStatus(BaseModel):
    workspace_id: str
    status: str                        # "running" | "done" | "cancelled" | "error"
    task_brief: str
    session_id: str


# ─── Database helpers (all wrapped in try/except so DB never breaks workspace) ─

async def _db_create_run(pool, workspace_id: str, user_id: int, session_id: str, task_brief: str) -> None:
    """Insert a new workspace_run row. Silently ignores DB errors."""
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


async def _db_save_event(pool, workspace_id: str, seq: int, event) -> None:
    """Insert a workspace_event row. Silently ignores DB errors."""
    if pool is None:
        return
    try:
        # Build a payload dict from the event attributes
        payload: dict = {}
        for attr in ("content", "tool", "args", "output", "success", "message", "summary"):
            val = getattr(event, attr, None)
            if val is not None:
                payload[attr] = val

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_events (workspace_id, seq, event_type, payload, ts)
                VALUES ($1, $2, $3, $4::jsonb, NOW())
                """,
                workspace_id, seq, event.type, json.dumps(payload),
            )
    except Exception as exc:
        logger.error("DB: failed to save event seq=%s for workspace %s: %s", seq, workspace_id, exc)


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
    """Update workspace_run on completion. Silently ignores DB errors."""
    if pool is None:
        return
    try:
        duration_ms = int((time.monotonic() - started_epoch) * 1000)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workspace_runs
                SET status       = $2,
                    completed_at = NOW(),
                    duration_ms  = $3,
                    event_count  = $4,
                    tool_calls   = $5,
                    final_summary = $6,
                    error_message = $7
                WHERE id = $1
                """,
                workspace_id, status, duration_ms, event_count, tool_calls,
                summary, error,
            )
    except Exception as exc:
        logger.error("DB: failed to complete workspace_run %s: %s", workspace_id, exc)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@workspace_router.post("/suggest")
async def suggest_workspace(
    req: SuggestRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Analyze the current chat history and return a workspace suggestion.
    Called by the frontend after every AI response in chat.
    If should_suggest=true, the frontend shows the "Launch Workspace?" banner.
    """
    suggestion = await detect_workspace_task(req.chat_history)
    return suggestion.to_dict()


@workspace_router.post("/launch")
async def launch_workspace(
    request: Request,
    req: LaunchRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Launch a new workspace. Returns workspace_id immediately.
    The frontend uses workspace_id to connect to /stream/{workspace_id}.

    Session isolation: each launch gets a unique session by default.
    Pass session_id explicitly only when the user intentionally resumes
    a previous workspace run. This prevents contamination from failed/
    confused previous sessions in OpenClaw's conversation history.
    """
    workspace_id = str(uuid.uuid4())[:8]

    # Each workspace gets its own isolated OpenClaw session unless the caller
    # explicitly requests a resume. Sharing session_id across launches would
    # cause OpenClaw to inherit conversation history from previous (possibly
    # failed or confused) runs.
    session_id = req.session_id or f"ws-{workspace_id}"

    # Resolve the actual task from the brief. If the brief is the generic
    # default, fall back to the last user message in the chat history.
    task_brief = _resolve_task_brief(req.task_brief, req.chat_history)

    pool = getattr(request.app.state, "pg_pool", None)

    # Workspace always runs via OpenClaw — it's an execution environment with
    # real tools (shell, code, file ops). Not a chat interface.
    # agent_id selects which OpenClaw agent handles this session:
    #   "main" → local Ollama (gpt-oss:latest)
    #   "kimi" → Kimi K2.5 via Harvis proxy
    #   "gpt-oss" → GPT-OSS 120B via external/cloud Ollama (routed through OpenClaw)
    agent_id = req.agent_id if req.agent_id in ("main", "kimi", "gpt-oss") else "main"
    client = OpenClawClient(workspace_id=workspace_id, session_id=session_id, agent_id=agent_id)

    started_epoch = time.monotonic()

    _workspaces[workspace_id] = {
        "client": client,
        "status": "running",
        "task_brief": task_brief,
        "session_id": session_id,
        "chat_history": req.chat_history,
        "user_id": current_user["id"],
        "started_epoch": started_epoch,
        "agent_id": agent_id,
    }

    logger.info(
        "Workspace launched: id=%s user=%s session=%s brief=%r",
        workspace_id, current_user["id"], session_id, task_brief,
    )

    # Persist to DB (non-blocking, failure safe)
    try:
        await _db_create_run(pool, workspace_id, current_user["id"], session_id, task_brief)
    except Exception as exc:
        logger.error("DB: _db_create_run raised unexpectedly: %s", exc)

    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "task_brief": task_brief,
    }


_GENERIC_BRIEFS = {
    "execute the task in a harvis workspace",
    "execute task in harvis workspace",
    "workspace",
    "/workspace",
    "",
}


def _resolve_task_brief(brief: str, chat_history: list[dict]) -> str:
    """
    If the brief is a generic placeholder, extract the actual user intent
    from the last user message in the chat history.
    """
    if brief.strip().lower() in _GENERIC_BRIEFS:
        last_user = next(
            (m for m in reversed(chat_history) if m.get("role") == "user"),
            None,
        )
        if last_user and isinstance(last_user.get("content"), str):
            extracted = last_user["content"].strip()
            if extracted:
                return extracted[:500]  # keep it reasonable length
    return brief


@workspace_router.get("/stream/{workspace_id}")
async def stream_workspace(
    workspace_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    SSE stream of workspace activity.
    The frontend connects here immediately after /launch and renders the
    right-hand activity panel. Each event is a JSON object with a 'type' field:

      {type: "token",       content: "..."}          — model output token
      {type: "tool_call",  tool: "run_code", args: {}} — tool being called
      {type: "tool_result", tool: "run_code", output: "...", success: true}
      {type: "log",         message: "..."}           — info log line
      {type: "done",        summary: "..."}           — workspace complete
      {type: "cancelled",   message: "..."}           — user cancelled
      {type: "error",       message: "..."}           — error occurred
    """
    ws = _workspaces.get(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

    client: OpenClawClient = ws["client"]
    chat_history: list[dict] = ws["chat_history"]
    task_brief: str = ws["task_brief"]
    started_epoch: float = ws.get("started_epoch", time.monotonic())

    pool = getattr(request.app.state, "pg_pool", None)

    async def event_generator():
        seq = 0
        tool_call_count = 0
        final_summary: Optional[str] = None
        final_error: Optional[str] = None
        terminal_status = "done"

        try:
            # All agents (main, kimi, gpt-oss) route through OpenClaw
            # for full tool access (exec, read, write)
            event_source = client.stream(task_brief, chat_history)

            async for event in event_source:
                # Track tool calls
                if event.type == "tool_call":
                    tool_call_count += 1

                # Persist event (non-blocking, failure safe)
                try:
                    await _db_save_event(pool, workspace_id, seq, event)
                except Exception as exc:
                    logger.error("DB: _db_save_event raised unexpectedly seq=%s: %s", seq, exc)

                seq += 1
                yield event.to_sse()

                # Update status and capture final details when terminal events arrive
                if event.type in ("done", "cancelled", "error"):
                    terminal_status = event.type
                    _workspaces[workspace_id]["status"] = event.type
                    if event.type == "done":
                        final_summary = getattr(event, "summary", None)
                    elif event.type == "error":
                        final_error = getattr(event, "message", None)
                    break

            # Persist completion (non-blocking, failure safe)
            try:
                await _db_complete_run(
                    pool, workspace_id, terminal_status,
                    final_summary, final_error, tool_call_count, seq, started_epoch,
                )
            except Exception as exc:
                logger.error("DB: _db_complete_run raised unexpectedly: %s", exc)

            # Send a final keep-alive close signal
            yield "data: {\"type\": \"stream_end\"}\n\n"

        except asyncio.CancelledError:
            # Client disconnected (navigated away, etc.)
            client.cancel()
            _workspaces[workspace_id]["status"] = "cancelled"
            try:
                await _db_complete_run(
                    pool, workspace_id, "cancelled",
                    None, "client disconnected", tool_call_count, seq, started_epoch,
                )
            except Exception as exc:
                logger.error("DB: _db_complete_run (cancelled) raised unexpectedly: %s", exc)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Tell Nginx not to buffer SSE
            "Connection": "keep-alive",
        },
    )


@workspace_router.post("/cancel/{workspace_id}")
async def cancel_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Cancel a running workspace. The SSE stream will emit a 'cancelled' event."""
    ws = _workspaces.get(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")

    ws["client"].cancel()
    _workspaces[workspace_id]["status"] = "cancelled"

    logger.info(f"Workspace cancelled: id={workspace_id} user={current_user['id']}")
    return {"workspace_id": workspace_id, "status": "cancelled"}


@workspace_router.get("/status/{workspace_id}", response_model=WorkspaceStatus)
async def get_workspace_status(
    workspace_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Get the current status of a workspace (polling fallback if SSE drops)."""
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
    """
    Return the last 20 workspace runs for the current user, newest first.
    Used by the WorkspacePanel History tab.
    """
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
        # Convert timestamps to ISO strings for JSON serialisation
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
    Returns a new workspace_id + session_id. The caller connects to
    /stream/{workspace_id} exactly as it would for a fresh launch.
    """
    pool = getattr(request.app.state, "pg_pool", None)

    # Fetch task_brief from DB first (survives pod restarts)
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

    # Fall back to in-memory registry (works when pod hasn't restarted)
    if not task_brief:
        ws = _workspaces.get(source_id)
        if ws and ws.get("user_id") == current_user["id"]:
            task_brief = ws["task_brief"]
            agent_id = ws.get("agent_id", "main")

    if not task_brief:
        raise HTTPException(status_code=404, detail="Workspace run not found")

    workspace_id = str(uuid.uuid4())[:8]
    session_id = f"ws-{workspace_id}"

    client = OpenClawClient(workspace_id=workspace_id, session_id=session_id, agent_id=agent_id)
    started_epoch = time.monotonic()

    _workspaces[workspace_id] = {
        "client": client,
        "status": "running",
        "task_brief": task_brief,
        "session_id": session_id,
        "chat_history": [],  # rerun uses task_brief directly; no prior context needed
        "user_id": current_user["id"],
        "started_epoch": started_epoch,
        "agent_id": agent_id,
    }

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


@workspace_router.get("/run/{workspace_id}/events")
async def get_workspace_events(
    workspace_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Return all stored events for a given workspace_id, ordered by seq.
    Used by the WorkspacePanel History tab for run replay/review.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"events": []}

    try:
        async with pool.acquire() as conn:
            # Verify the run belongs to this user first
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
            # payload is already a dict from asyncpg JSONB decoding
            events.append(row_dict)

        return {"events": events}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("DB: failed to fetch events for workspace %s: %s", workspace_id, exc)
        return {"events": []}
