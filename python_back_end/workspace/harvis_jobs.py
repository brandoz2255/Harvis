"""
Harvis Execution Core — Phase E1: NON-BLOCKING background jobs (lane 3).

Today's `POST /api/harvis/exec` is one-shot and blocking. This router adds a
detached job runtime on the same sandbox containers:

    POST   /api/harvis/jobs             → start, returns job_id immediately
    GET    /api/harvis/jobs/{id}        → status (+exit_code when finished)
    GET    /api/harvis/jobs/{id}/stream → pointer to the existing run SSE
    DELETE /api/harvis/jobs/{id}        → kill (pidfile → SIGTERM/-KILL pgid)

Live output rides the EXISTING trace stream: exec_bg's tail loop emits
`terminal_output` events on the job's workspace_id, so clients just consume
`GET /api/harvis/runs/{workspace_id}/stream` — no second SSE implementation.

Auth + governance mirror harvis_exec.py exactly: JWT via
get_current_user_optimized, workspace scoping via _resolve_scoped_workspace
(per-user sandbox ids, foreign runs 404), and authorize_action on lane 3
before anything starts. GET/DELETE are ownership-scoped FAIL CLOSED: an
unknown job_id, a missing workspace_runs row, or a row owned by someone else
all return an identical 404.

⚠ E1 CAVEAT: the job registry lives in WorkspaceTerminalManager._jobs —
IN-MEMORY ONLY. A backend restart forgets every job (lookups 404) even though
the detached wrapper keeps running inside the container. E2 adds persistence.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized
from owui_compat.workspace_method import LANE_CONTAINER_TERMINAL

from .harvis_exec import _resolve_scoped_workspace
from .harvis_trace import _pool_of
from .orchestration.authz import authorize_action
from .terminal_container import (
    build_tool_call_payload,
    emit_terminal_event,
    get_terminal_manager,
    is_enabled,
)

logger = logging.getLogger(__name__)

harvis_jobs_router = APIRouter(prefix="/api/harvis", tags=["harvis-jobs"])


# ── Request model ────────────────────────────────────────────────────────────

class HarvisJobRequest(BaseModel):
    workspace_id: str = Field(..., min_length=1, max_length=128)
    command: str = Field(..., min_length=1)
    workdir: str = Field(default="/workspace", min_length=1, max_length=512)


# ── Ownership (fail closed) ──────────────────────────────────────────────────

async def _require_owned_job(pool, job_id: str, user_id: int):
    """Return the job iff the caller owns its workspace; else 404.

    Missing job, missing run row, and foreign owner are indistinguishable —
    same 404, no existence leak (mirrors harvis_trace._require_owned_run).
    """
    job = get_terminal_manager().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM workspace_runs WHERE id = $1", job.workspace_id
        )
    if row is None or int(row["user_id"]) != int(user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Routes ───────────────────────────────────────────────────────────────────

@harvis_jobs_router.post("/jobs")
async def create_job(
    body: HarvisJobRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Start a detached background job in the caller's sandbox (lane 3)."""
    # Hard gate — same as harvis_exec: disabled/unready terminal 503s.
    if not is_enabled():
        raise HTTPException(503, "terminal disabled (HARVIS_TERMINAL_ENABLED=false)")
    mgr = get_terminal_manager()
    report = await mgr.probe()
    if not report.ready:
        raise HTTPException(503, f"terminal not ready: {report.reason}")

    pool = _pool_of(request)
    user_id = int(current_user["id"])
    workspace_id = await _resolve_scoped_workspace(pool, body.workspace_id, user_id)

    # Phase 2 choke point — lane-3 gate, traced decision.
    async def _emit_decision(payload: dict) -> None:
        await emit_terminal_event(
            pool, workspace_id, event_type="decision", payload=payload
        )

    res = await authorize_action(
        tool_name="exec",
        args={"command": body.command},
        lane=LANE_CONTAINER_TERMINAL,
        permission_mode=None,
        run_id=workspace_id,
        emit=_emit_decision,
    )
    if not res.allowed:
        raise HTTPException(403, res.reason or "denied by execution policy")

    await emit_terminal_event(
        pool, workspace_id,
        event_type="tool_call",
        payload=build_tool_call_payload(body.command),
    )
    try:
        job_id = await mgr.exec_bg(
            workspace_id, body.command, workdir=body.workdir, pool=pool
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:  # docker APIError etc.
        logger.error("[harvis-jobs:%s] launch failed: %s", workspace_id, exc)
        raise HTTPException(503, f"job launch failed: {exc}")

    return {
        "job_id": job_id,
        "workspace_id": workspace_id,
        "status": "running",
        "stream_url": f"/api/harvis/runs/{workspace_id}/stream",
    }


@harvis_jobs_router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Job status — ownership-scoped, fail closed."""
    pool = _pool_of(request)
    await _require_owned_job(pool, job_id, int(current_user["id"]))
    status = await get_terminal_manager().job_status(job_id)
    if status is None:  # raced a registry prune
        raise HTTPException(status_code=404, detail="Job not found")
    return status


@harvis_jobs_router.get("/jobs/{job_id}/stream")
async def get_job_stream(
    job_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Where to watch this job live. exec_bg emits on the job's workspace_id,
    so the answer is the EXISTING run SSE — no new stream implementation."""
    pool = _pool_of(request)
    job = await _require_owned_job(pool, job_id, int(current_user["id"]))
    return {
        "job_id": job_id,
        "stream_url": f"/api/harvis/runs/{job.workspace_id}/stream",
    }


@harvis_jobs_router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Kill a running job (SIGTERM→SIGKILL to its process group via pidfile)."""
    pool = _pool_of(request)
    await _require_owned_job(pool, job_id, int(current_user["id"]))
    try:
        killed = await get_terminal_manager().kill_job(job_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return {"job_id": job_id, "killed": bool(killed)}
