"""
Harvis Execution Core — Phase 1: Conversational Execution Trace facade.

A clean `/api/harvis/*` namespace over the EXISTING workspace run/event store.
This module owns NO storage and NO streaming logic — every endpoint delegates
to workspace_router (launch, SSE stream, action gates) or terminal_container
(event emission). New event types (terminal_output / artifact / decision /
search_trace) ride the same workspace_events table; event_type has no CHECK
constraint so no migration is needed.

Auth:
  • User-facing endpoints — same JWT dependency as workspace_router
    (get_current_user_optimized), with per-user ownership enforced on every
    run read via the workspace_runs.user_id column.
  • POST /runs/{id}/events — service-internal (agent/sandbox side-channel),
    guarded by the OPENCLAW_GATEWAY_TOKEN bearer exactly like terminal_routes.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized

from .terminal_container import emit_terminal_event
from .terminal_routes import _check_gateway_token
from .workspace_router import (
    _resolve_run_action,
    launch_workspace_internal,
    stream_workspace,
)

logger = logging.getLogger(__name__)

harvis_trace_router = APIRouter(prefix="/api/harvis", tags=["harvis-trace"])

# Event types the internal push endpoint accepts. Later phases emit these from
# the sandbox shell / lane gates; anything else must go through the normal
# OpenClawClient pipeline so _db_save_event's whitelist stays authoritative.
_INTERNAL_EVENT_TYPES = frozenset(
    {"terminal_output", "artifact", "decision", "search_trace", "log"}
)


# ── Request models ───────────────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    task_brief: str = Field(..., min_length=1)
    chat_history: Optional[list[dict]] = None
    agent_id: str = "main"
    model_name: str = ""
    session_id: Optional[str] = None
    live_web: bool = True
    attachments: Optional[list[dict]] = None
    uniform_model: bool = False


class PushEventRequest(BaseModel):
    event_type: str = Field(..., min_length=1)
    payload: dict = Field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pool_of(request: Request):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return pool


async def _require_owned_run(pool, run_id: str, user_id: int):
    """Fetch the run row iff it belongs to this user; 404 otherwise (no
    existence leak — foreign runs and missing runs look identical)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, task_brief, status, started_at, completed_at,
                   duration_ms, event_count, tool_calls, final_summary,
                   error_message, parent_run_id, role, model_provider, model_name
            FROM workspace_runs
            WHERE id = $1 AND user_id = $2
            """,
            run_id, int(user_id),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


def _parse_payload(raw) -> dict:
    # asyncpg returns JSONB as str (no global codec) — tolerate both forms,
    # same as the stream_workspace replay path.
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


# ── User-facing endpoints (JWT) ──────────────────────────────────────────────

@harvis_trace_router.post("/runs")
async def create_run(
    req: CreateRunRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Launch a run through the existing internal launcher (same background
    task + broadcaster + DB row the /api/workspace/launch path creates)."""
    result = await launch_workspace_internal(
        request=request,
        user_id=int(current_user["id"]),
        task_brief=req.task_brief,
        chat_history=req.chat_history or [],
        agent_id=req.agent_id,
        model_name=req.model_name,
        session_id=req.session_id,
        live_web=req.live_web,
        attachments=req.attachments,
        uniform_model=req.uniform_model,
    )
    # Present the workspace id under the Harvis vocabulary too.
    return {"run_id": result["workspace_id"], **result}


@harvis_trace_router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    pool = _pool_of(request)
    row = await _require_owned_run(pool, run_id, current_user["id"])
    return {
        "run_id": row["id"],
        "session_id": row["session_id"],
        "task_brief": row["task_brief"],
        "status": row["status"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        "duration_ms": row["duration_ms"],
        "event_count": row["event_count"],
        "tool_calls": row["tool_calls"],
        "final_summary": row["final_summary"],
        "error_message": row["error_message"],
        "parent_run_id": row["parent_run_id"],
        "role": row["role"],
        "model_provider": row["model_provider"],
        "model_name": row["model_name"],
    }


@harvis_trace_router.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    request: Request,
    after_seq: int = -1,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Cursor-paged replay of the run's persisted trace (mirrors the SSE
    replay SELECT). `after_seq` is exclusive; pass the last seen seq to poll."""
    pool = _pool_of(request)
    await _require_owned_run(pool, run_id, current_user["id"])
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT seq, event_type, payload
            FROM workspace_events
            WHERE workspace_id = $1 AND seq > $2
            ORDER BY seq ASC
            """,
            run_id, int(after_seq),
        )
    events = [
        {"seq": r["seq"], "type": r["event_type"], **_parse_payload(r["payload"])}
        for r in rows
    ]
    return {
        "run_id": run_id,
        "after_seq": int(after_seq),
        "last_seq": events[-1]["seq"] if events else int(after_seq),
        "events": events,
    }


@harvis_trace_router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """SSE trace stream — delegates to the existing two-phase generator
    (DB replay → live broadcaster → heartbeat → terminal sentinel)."""
    pool = _pool_of(request)
    # Explicit ownership gate BEFORE delegating (stream_workspace only checks
    # the DB owner on the no-in-memory-run path).
    await _require_owned_run(pool, run_id, current_user["id"])
    return await stream_workspace(run_id, request, current_user)


@harvis_trace_router.post("/runs/{run_id}/action/{action_id}/approve")
async def approve_action(
    run_id: str, action_id: str, request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Approve a gated action → the paused agent turn resumes + dispatches it."""
    return await _resolve_run_action(request, current_user, run_id, action_id, True)


@harvis_trace_router.post("/runs/{run_id}/action/{action_id}/deny")
async def deny_action(
    run_id: str, action_id: str, request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Deny a gated action → the turn skips it and continues."""
    return await _resolve_run_action(request, current_user, run_id, action_id, False)


# ── Service-internal event push (gateway token, NOT JWT) ─────────────────────

@harvis_trace_router.post(
    "/runs/{run_id}/events",
    dependencies=[Depends(_check_gateway_token)],
)
async def push_run_event(
    run_id: str,
    body: PushEventRequest,
    request: Request,
):
    """Side-channel for trusted internal services (sandbox shell, lane gates,
    search proxy) to append trace events. Persists via emit_terminal_event
    (MAX(seq)+1 row + live broadcast) so SSE subscribers see it immediately."""
    if body.event_type not in _INTERNAL_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"event_type must be one of {sorted(_INTERNAL_EVENT_TYPES)}",
        )
    pool = _pool_of(request)
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM workspace_runs WHERE id = $1", run_id
        )
    if not exists:
        raise HTTPException(status_code=404, detail="Run not found")

    payload = dict(body.payload or {})
    # Strip envelope-reserved keys: the SSE/replay frames spread the payload over
    # {type, seq, ...}, so a payload carrying "type"/"seq" could spoof a terminal
    # event or corrupt the GET /events cursor. The event_type is set from the field.
    for reserved in ("type", "seq"):
        payload.pop(reserved, None)
    payload.setdefault("run_id", run_id)
    await emit_terminal_event(
        pool, run_id, event_type=body.event_type, payload=payload
    )
    return {"ok": True, "run_id": run_id, "event_type": body.event_type}
