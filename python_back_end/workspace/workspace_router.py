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
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth_optimized import get_current_user_optimized
from .openclaw_client import OpenClawClient, OpenClawEvent
from .task_detector import detect_workspace_task

logger = logging.getLogger(__name__)

workspace_router = APIRouter(prefix="/api/workspace", tags=["workspace"])

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


class WorkspaceStatus(BaseModel):
    workspace_id: str
    status: str
    task_brief: str
    session_id: str


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
    queue: asyncio.Queue = _workspace_queues[workspace_id]

    seq = 0
    tool_call_count = 0
    terminal_status = "done"
    final_summary: Optional[str] = None
    final_error: Optional[str] = None

    try:
        async for event in client.stream(task_brief, chat_history):
            if event.type == "tool_call":
                tool_call_count += 1

            # Persist first — DB is the authoritative source for replays
            await _db_save_event(pool, workspace_id, seq, event)

            # Push to live queue for the active SSE connection
            await queue.put((seq, event))
            seq += 1

            if event.type in ("done", "cancelled", "error"):
                terminal_status = event.type
                ws["status"] = event.type
                if event.type == "done":
                    final_summary = getattr(event, "summary", None)
                elif event.type == "error":
                    final_error = getattr(event, "message", None)
                break

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
        err_event = OpenClawEvent("error", {"message": str(exc)})
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
    }

    queue: asyncio.Queue = asyncio.Queue()
    _workspace_queues[workspace_id] = queue

    task = asyncio.create_task(
        _run_workspace_bg(workspace_id, pool, started_epoch),
        name=f"workspace-{workspace_id}",
    )
    _workspace_tasks[workspace_id] = task

    return client


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@workspace_router.post("/suggest")
async def suggest_workspace(
    req: SuggestRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    suggestion = await detect_workspace_task(req.chat_history)
    return suggestion.to_dict()


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
    agent_id = req.agent_id if req.agent_id in ("main", "kimi", "gpt-oss", "qwen3") else "main"
    started_epoch = time.monotonic()

    _start_workspace(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=task_brief,
        chat_history=req.chat_history,
        agent_id=agent_id,
        user_id=current_user["id"],
        pool=pool,
        started_epoch=started_epoch,
    )

    try:
        await _db_create_run(pool, workspace_id, current_user["id"], session_id, task_brief)
    except Exception as exc:
        logger.error("DB: _db_create_run raised unexpectedly: %s", exc)

    logger.info(
        "Workspace launched: id=%s user=%s session=%s agent=%s brief=%r",
        workspace_id, current_user["id"], session_id, agent_id, task_brief,
    )

    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "task_brief": task_brief,
    }


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
