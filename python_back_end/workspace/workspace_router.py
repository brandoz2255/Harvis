"""
Harvis Workspaces API router.

Endpoints:
  POST /api/workspace/suggest          — Analyze chat, return workspace suggestion
  POST /api/workspace/launch           — Confirm launch, start OpenClaw task
  GET  /api/workspace/stream/{ws_id}   — SSE stream of workspace activity log
  POST /api/workspace/cancel/{ws_id}   — Cancel a running workspace
  GET  /api/workspace/status/{ws_id}   — Get current workspace status

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
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth_optimized import get_current_user_optimized
from .openclaw_client import OpenClawClient
from .task_detector import detect_workspace_task

logger = logging.getLogger(__name__)

workspace_router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# ─── In-memory workspace registry ────────────────────────────────────────────
# Maps workspace_id → {client, status, task_brief, session_id}
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


class WorkspaceStatus(BaseModel):
    workspace_id: str
    status: str                        # "running" | "done" | "cancelled" | "error"
    task_brief: str
    session_id: str


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
    req: LaunchRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """
    Launch a new workspace. Returns workspace_id immediately.
    The frontend uses workspace_id to connect to /stream/{workspace_id}.
    """
    workspace_id = str(uuid.uuid4())[:8]

    # If a session_id is provided, OpenClaw will continue that conversation's
    # history — making the workspace "resumable" across launches.
    session_id = req.session_id or f"harvis-user-{current_user['id']}"

    client = OpenClawClient(workspace_id=workspace_id, session_id=session_id)

    _workspaces[workspace_id] = {
        "client": client,
        "status": "running",
        "task_brief": req.task_brief,
        "session_id": session_id,
        "chat_history": req.chat_history,
    }

    logger.info(f"Workspace launched: id={workspace_id} user={current_user['id']} brief={req.task_brief!r}")

    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "status": "running",
        "task_brief": req.task_brief,
    }


@workspace_router.get("/stream/{workspace_id}")
async def stream_workspace(
    workspace_id: str,
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

    async def event_generator():
        try:
            async for event in client.stream(task_brief, chat_history):
                yield event.to_sse()

                # Update status when terminal events arrive
                if event.type in ("done", "cancelled", "error"):
                    _workspaces[workspace_id]["status"] = event.type
                    break

            # Send a final keep-alive close signal
            yield "data: {\"type\": \"stream_end\"}\n\n"

        except asyncio.CancelledError:
            # Client disconnected (navigated away, etc.)
            client.cancel()
            _workspaces[workspace_id]["status"] = "cancelled"

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

    client: OpenClawClient = ws["client"]
    client.cancel()
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
