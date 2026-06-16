"""User-facing CRUD for per-user cron jobs (Phase 6 storage)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized

from .store import PgCronJobStore
from .types import JobStatus, ScheduleType

router = APIRouter(prefix="/api/cron", tags=["cron"])


class CronJobView(BaseModel):
    id: str
    name: str
    schedule_type: str
    schedule_expr: str
    prompt: str
    delivery: Optional[str] = None
    status: str
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    run_count: int
    error_message: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class CreateCronJobPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    schedule_type: ScheduleType
    schedule_expr: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1, max_length=20_000)
    delivery: Optional[str] = Field(default=None, max_length=200)
    metadata: dict = Field(default_factory=dict)


def _store(request: Request) -> PgCronJobStore:
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    return PgCronJobStore(pool)


def _to_view(j) -> CronJobView:
    return CronJobView(
        id=str(j.id),
        name=j.name,
        schedule_type=j.schedule_type.value,
        schedule_expr=j.schedule_expr,
        prompt=j.prompt,
        delivery=j.delivery,
        status=j.status.value,
        next_run_at=j.next_run_at.isoformat() if j.next_run_at else None,
        last_run_at=j.last_run_at.isoformat() if j.last_run_at else None,
        run_count=j.run_count,
        error_message=j.error_message,
        metadata=dict(j.metadata or {}),
    )


@router.get("")
async def list_my_jobs(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    store = _store(request)
    user_id = current_user["id"]
    jobs = await store.list_for_user(user_id)
    return {"jobs": [_to_view(j).model_dump() for j in jobs]}


@router.post("")
async def create_my_job(
    body: CreateCronJobPayload,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    store = _store(request)
    user_id = current_user["id"]
    job = await store.create(
        user_id=user_id,
        name=body.name,
        schedule_type=body.schedule_type,
        schedule_expr=body.schedule_expr,
        prompt=body.prompt,
        delivery=body.delivery,
        metadata=body.metadata,
    )
    if job is None:
        raise HTTPException(status_code=500, detail="job creation failed (check schedule_expr / DB connectivity)")
    return {"ok": True, "job": _to_view(job).model_dump()}


@router.get("/stats")
async def my_automation_stats(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    """Real run outcomes for this user's automations — aggregated from the
    workspace_runs the cron tick launched (tagged session_id 'cron-<job>').
    Counts only parent (orchestrator) runs so one fire == one run.

    NOTE: declared BEFORE GET /{job_id} so 'stats' isn't matched as a job id.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    uid = current_user["id"]
    async with pool.acquire() as conn:
        by_status = await conn.fetch(
            """
            SELECT status, COUNT(*) AS n
            FROM workspace_runs
            WHERE user_id = $1 AND session_id LIKE 'cron-%'
              AND parent_run_id IS NULL
              AND started_at >= NOW() - INTERVAL '7 days'
            GROUP BY status
            """,
            uid,
        )
        recent = await conn.fetch(
            """
            SELECT id, task_brief, status, started_at, final_summary
            FROM workspace_runs
            WHERE user_id = $1 AND session_id LIKE 'cron-%'
              AND parent_run_id IS NULL
            ORDER BY started_at DESC
            LIMIT 20
            """,
            uid,
        )
    counts = {r["status"]: int(r["n"]) for r in by_status}
    return {
        "successful_7d": counts.get("done", 0),
        "failed_7d": counts.get("error", 0),
        "recent": [
            {
                "id": r["id"],
                "task_brief": r["task_brief"],
                "status": r["status"],
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "summary": r["final_summary"],
            }
            for r in recent
        ],
    }


@router.get("/{job_id}")
async def get_my_job(
    job_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    try:
        job_uuid = UUID(job_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid job_id")
    store = _store(request)
    job = await store.get(job_uuid)
    if job is None or job.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job": _to_view(job).model_dump()}


@router.put("/{job_id}/status")
async def set_my_job_status(
    job_id: str,
    status: JobStatus,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    try:
        job_uuid = UUID(job_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid job_id")
    store = _store(request)
    # Ownership check before mutation
    job = await store.get(job_uuid)
    if job is None or job.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="job not found")
    ok = await store.set_status(job_uuid, status)
    return {"ok": bool(ok), "status": status.value}


@router.delete("/{job_id}")
async def delete_my_job(
    job_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    try:
        job_uuid = UUID(job_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid job_id")
    store = _store(request)
    job = await store.get(job_uuid)
    if job is None or job.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="job not found")
    ok = await store.delete(job_uuid)
    return {"ok": bool(ok)}
