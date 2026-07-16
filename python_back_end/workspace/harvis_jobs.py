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

E2 PERSISTENCE: every job is mirrored into the workspace_jobs table
(insert on launch, update on every terminal state), so a backend restart no
longer forgets jobs — GET falls back to the row, and a startup task
(reattach_running_jobs) resumes tailing wrappers that are still alive inside
their sandbox containers or finalizes ones that finished while we were down.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized
from owui_compat.workspace_method import LANE_CONTAINER_TERMINAL

from .harvis_exec import _resolve_permission_mode, _resolve_scoped_workspace
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
    # Phase 5: per-job max lifetime. None → the server default
    # (HARVIS_JOB_MAX_LIFETIME_S); values above the ceiling are clamped.
    timeout_secs: Optional[int] = Field(default=None, ge=1, le=86400)


# Phase 5: log tails read back from persisted terminal_output events.
_LOG_TAIL_LINES = 40


async def _job_log_tail(pool, workspace_id: str, job_id: str) -> str:
    """Last ~40 lines of a job's streamed output, rebuilt from the persisted
    terminal_output events (survives the in-container janitor AND backend
    restarts — the events table is the job's durable log store).

    FAIL-SOFT: any error (missing table, bad payload, pool down) returns ''.
    """
    if pool is None:
        return ""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload->>'content' AS content
                FROM workspace_events
                WHERE workspace_id = $1
                  AND event_type = 'terminal_output'
                  AND payload->>'job_id' = $2
                ORDER BY seq DESC
                LIMIT 80
                """,
                workspace_id, job_id,
            )
        text = "".join((r["content"] or "") for r in reversed(rows))
        return "\n".join(text.splitlines()[-_LOG_TAIL_LINES:])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[job:%s] log-tail read failed: %s", job_id, exc)
        return ""


async def _require_terminal_ready():
    """Hard gate — same as harvis_exec: disabled/unready terminal 503s.
    Called BEFORE _resolve_scoped_workspace so a disabled terminal never
    upserts a sandbox run row (preserves create_job's original ordering)."""
    if not is_enabled():
        raise HTTPException(503, "terminal disabled (HARVIS_TERMINAL_ENABLED=false)")
    mgr = get_terminal_manager()
    report = await mgr.probe()
    if not report.ready:
        raise HTTPException(503, f"terminal not ready: {report.reason}")
    return mgr


async def _gate_and_launch(
    pool,
    mgr,
    workspace_id: str,
    command: str,
    workdir: str,
    user_id: int,
    timeout_secs: Optional[int],
) -> str:
    """Shared launch path for POST /jobs and POST /jobs/{id}/retry.

    Runs the SAME lane-3 authorize_action gate as the original start (a retry
    is a fresh action — it never inherits a stale approval), emits the
    tool_call trace event, and starts the detached job. Raises HTTPException
    with the exact status codes create_job always used.
    """
    async def _emit_decision(payload: dict) -> None:
        await emit_terminal_event(
            pool, workspace_id, event_type="decision", payload=payload
        )

    permission_mode, vc_session_id = await _resolve_permission_mode(pool, workspace_id)
    res = await authorize_action(
        tool_name="exec",
        args={"command": command},
        lane=LANE_CONTAINER_TERMINAL,
        permission_mode=permission_mode,
        run_id=workspace_id,
        emit=_emit_decision,
        session_id=vc_session_id,
        pool=pool,
    )
    if not res.allowed:
        raise HTTPException(403, res.reason or "denied by execution policy")
    if res.needs_approval:
        # One-shot launch endpoint — no interactive approval loop, so a gated
        # action is REFUSED (fail closed). Approve-for-session or a higher
        # ladder rung lets it through.
        raise HTTPException(
            403,
            f"requires approval under permission mode '{permission_mode}' "
            f"(risk: {res.tier}): {res.reason or 'gated action'} — approve it for "
            "the session in the Build UI or raise the session's permission mode.",
        )

    await emit_terminal_event(
        pool, workspace_id,
        event_type="tool_call",
        payload=build_tool_call_payload(command),
    )
    try:
        return await mgr.exec_bg(
            workspace_id, command, workdir=workdir, pool=pool,
            user_id=user_id, timeout_secs=timeout_secs,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:  # docker APIError etc.
        logger.error("[harvis-jobs:%s] launch failed: %s", workspace_id, exc)
        raise HTTPException(503, f"job launch failed: {exc}")


# ── Ownership (fail closed) ──────────────────────────────────────────────────

async def _require_owned_job(pool, job_id: str, user_id: int):
    """Return the job iff the caller owns its workspace; else 404.

    Missing job, missing run row, and foreign owner are indistinguishable —
    same 404, no existence leak (mirrors harvis_trace._require_owned_run).

    E2: when the in-memory registry lost the job (backend restart, retention
    prune) we fall back to the persisted workspace_jobs row and check BOTH
    the owning run's user_id AND the user_id stamped on the job row —
    fail closed on any mismatch or missing piece.
    """
    job = get_terminal_manager().get_job(job_id)
    if job is not None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM workspace_runs WHERE id = $1", job.workspace_id
            )
        if row is None or int(row["user_id"]) != int(user_id):
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT j.id, j.workspace_id, j.user_id AS job_user,
                   r.user_id AS ws_user
            FROM workspace_jobs j
            LEFT JOIN workspace_runs r ON r.id = j.workspace_id
            WHERE j.id = $1
            """,
            job_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["ws_user"] is None or int(row["ws_user"]) != int(user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if row["job_user"] is not None and int(row["job_user"]) != int(user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return SimpleNamespace(job_id=row["id"], workspace_id=row["workspace_id"])


# ── Routes ───────────────────────────────────────────────────────────────────

@harvis_jobs_router.post("/jobs")
async def create_job(
    body: HarvisJobRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Start a detached background job in the caller's sandbox (lane 3).

    Hard gate + Phase 2 choke point (lane-3 authorize_action with the session's
    REAL permission mode, traced decision) live in _gate_and_launch — shared
    verbatim with POST /jobs/{id}/retry.
    """
    mgr = await _require_terminal_ready()
    pool = _pool_of(request)
    user_id = int(current_user["id"])
    workspace_id = await _resolve_scoped_workspace(pool, body.workspace_id, user_id)
    job_id = await _gate_and_launch(
        pool, mgr, workspace_id, body.command, body.workdir, user_id, body.timeout_secs,
    )
    return {
        "job_id": job_id,
        "workspace_id": workspace_id,
        "status": "running",
        "stream_url": f"/api/harvis/runs/{workspace_id}/stream",
    }


@harvis_jobs_router.get("/jobs")
async def list_jobs(
    request: Request,
    limit: int = 50,
    current_user: dict = Depends(get_current_user_optimized),
):
    """The caller's background jobs, newest first — the Dev Console's job list.
    Owner-scoped two ways (fail closed): the job's own user_id OR the owning run's
    user_id must match. Persisted rows survive a backend restart, so this reflects
    history, not just the in-memory registry."""
    pool = _pool_of(request)
    if pool is None:
        return {"jobs": []}
    uid = int(current_user["id"])
    lim = max(1, min(int(limit or 50), 200))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT j.id, j.workspace_id, j.command, j.status, j.exit_code,
                   j.timeout_secs, j.started_at, j.finished_at
            FROM workspace_jobs j
            LEFT JOIN workspace_runs r ON r.id = j.workspace_id
            WHERE j.user_id = $1 OR r.user_id = $1
            ORDER BY j.started_at DESC NULLS LAST
            LIMIT $2
            """,
            uid, lim,
        )
    jobs = []
    for r in rows:
        jobs.append({
            "id": r["id"],
            "workspace_id": r["workspace_id"],
            "command": r["command"],
            "status": r["status"],
            "exit_code": r["exit_code"],
            "timeout_secs": r["timeout_secs"],
            "started_at": int(r["started_at"].timestamp()) if r["started_at"] else None,
            "finished_at": int(r["finished_at"].timestamp()) if r["finished_at"] else None,
            # Phase 5: last ~40 lines for the task card — fail-soft to ''.
            "log_tail": await _job_log_tail(pool, r["workspace_id"], r["id"]),
            "stream_url": f"/api/harvis/runs/{r['workspace_id']}/stream",
        })
    return {"jobs": jobs}


@harvis_jobs_router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Job status — ownership-scoped, fail closed."""
    pool = _pool_of(request)
    await _require_owned_job(pool, job_id, int(current_user["id"]))
    # E2: pool lets job_status answer from the workspace_jobs row when the
    # in-memory registry was lost (backend restart / retention prune).
    status = await get_terminal_manager().job_status(job_id, pool=pool)
    if status is None:  # raced a registry prune
        raise HTTPException(status_code=404, detail="Job not found")
    # Phase 5: attach the persisted log tail (fail-soft to '').
    ws = status.get("workspace_id")
    status["log_tail"] = await _job_log_tail(pool, ws, job_id) if ws else ""
    return status


@harvis_jobs_router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Re-run a finished/failed job with the SAME command, workdir, workspace
    and timeout — as a NEW job. HUMAN-triggered only (a button, never an
    auto-retry loop). Ownership fail-closed like every other job route, and
    the launch passes through the SAME lane-3 authorize_action gate the
    original start used — a retry never inherits a stale approval."""
    mgr = await _require_terminal_ready()
    pool = _pool_of(request)
    user_id = int(current_user["id"])
    await _require_owned_job(pool, job_id, user_id)

    # Source of truth for what to re-run: the persisted row (survives
    # restarts); fall back to the in-memory registry if the insert was lost.
    row = None
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT workspace_id, command, workdir, status, timeout_secs
                    FROM workspace_jobs WHERE id = $1
                    """,
                    job_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[job:%s] retry lookup failed: %s", job_id, exc)
    if row is not None:
        workspace_id = row["workspace_id"]
        command = row["command"]
        workdir = row["workdir"] or "/workspace"
        status = row["status"]
        timeout_secs = row["timeout_secs"]
    else:
        mem = get_terminal_manager().get_job(job_id)
        if mem is None:
            raise HTTPException(status_code=404, detail="Job not found")
        workspace_id, command = mem.workspace_id, mem.command
        workdir, status, timeout_secs = mem.workdir, mem.status, mem.timeout_secs

    if status == "running":
        raise HTTPException(409, "Job is still running — stop it before retrying.")
    if not (command or "").strip():
        raise HTTPException(409, "Original command was not recorded — cannot retry.")

    new_job_id = await _gate_and_launch(
        pool, mgr, workspace_id, command, workdir, user_id, timeout_secs,
    )
    return {
        "job_id": new_job_id,
        "workspace_id": workspace_id,
        "retried_from": job_id,
        "status": "running",
        "stream_url": f"/api/harvis/runs/{workspace_id}/stream",
    }


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
