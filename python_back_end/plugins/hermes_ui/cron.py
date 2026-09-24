"""Scheduled jobs for the Hermes UI, backed by Harvis's own cron_jobs table.

Route shapes follow the reference dashboard (hermes_cli/web_routers/cron.py)
so the Scheduled jobs page, the sidebar section and the Bots routines pane
all work unchanged. Jobs created here are chat-context jobs: each fire runs
the prompt through one model turn and lands the exchange in an owui chat,
which is exactly a session in this UI. That chat is the job's "run".
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized
from plugins.cron.store import PgCronJobStore, compute_next_run
from plugins.cron.types import CronJob, JobStatus, ScheduleType

from .cron_schedule import ScheduleError, parse_schedule
from .rest import _pool, _uid
from .sessions import PROFILE_NAME

log = logging.getLogger("hermes_ui.cron")

router = APIRouter(prefix="/hermes-api/api/cron", tags=["hermes-ui"])

DELIVERY_TARGETS = [{
    "id": "local", "name": "Harvis chat (saved as a session)",
    "home_target_set": True, "home_env_var": None,
}]


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


_TARGET_IDS = {t["id"] for t in DELIVERY_TARGETS}


def job_view(job: CronJob) -> dict[str, Any]:
    """Harvis row -> the desktop's CronJob shape (types/hermes.ts)."""
    meta = job.metadata or {}
    display = str(meta.get("schedule_display") or job.schedule_expr)
    return {
        "id": str(job.id),
        "name": job.name,
        "prompt": job.prompt,
        "enabled": job.status != JobStatus.PAUSED,
        "state": job.status.value,
        "schedule": {"kind": job.schedule_type.value, "expr": job.schedule_expr, "display": display},
        "schedule_display": display,
        "next_run_at": _iso(job.next_run_at),
        "last_run_at": _iso(job.last_run_at),
        "last_error": job.error_message,
        "deliver": job.delivery if job.delivery in _TARGET_IDS else "local",
        "model": meta.get("model_name") or None,
        "provider": meta.get("provider") or None,
        "run_count": job.run_count,
        "no_agent": False,
        "script": None,
        "profile": PROFILE_NAME,
    }


def _store(request: Request) -> PgCronJobStore:
    return PgCronJobStore(_pool(request))


async def _owned(request: Request, user, job_id: str) -> CronJob:
    try:
        jid = UUID(job_id)
    except (TypeError, ValueError):
        raise HTTPException(404, "job not found")
    job = await _store(request).get(jid)
    if job is None or job.user_id != _uid(user):
        raise HTTPException(404, "job not found")
    return job


def _schedule_or_400(text: str) -> tuple[ScheduleType, str, str]:
    try:
        return parse_schedule(text)
    except ScheduleError as exc:
        raise HTTPException(400, str(exc))


def _delivery(value: Any) -> Optional[str]:
    v = str(value or "").strip()
    return None if v in ("", "local") else v


@router.get("/jobs")
async def list_jobs(request: Request, user=Depends(get_current_user_optimized)):
    jobs = await _store(request).list_for_user(_uid(user))
    return [job_view(j) for j in jobs]


@router.get("/delivery-targets")
async def delivery_targets(user=Depends(get_current_user_optimized)):
    return {"targets": DELIVERY_TARGETS}


@router.get("/blueprints")
async def blueprints(user=Depends(get_current_user_optimized)):
    return {"blueprints": []}


@router.post("/blueprints/instantiate")
async def blueprints_instantiate(user=Depends(get_current_user_optimized)):
    raise HTTPException(501, "Harvis has no automation blueprints; create the job directly.")


@router.post("/jobs")
async def create_job(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")
    stype, expr, display = _schedule_or_400(str(body.get("schedule") or ""))
    name = str(body.get("name") or "").strip() or (prompt[:60] + ("…" if len(prompt) > 60 else ""))
    model = str(body.get("model") or "").strip()
    metadata = {
        "context": "chat", "source": "hermes_ui", "schedule_display": display,
        "model_name": model, "provider": str(body.get("provider") or "").strip(),
    }
    job = await _store(request).create(
        user_id=_uid(user), name=name, schedule_type=stype, schedule_expr=expr,
        prompt=prompt, delivery=_delivery(body.get("deliver")), metadata=metadata)
    if job is None:
        raise HTTPException(500, "job creation failed")
    return job_view(job)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request, user=Depends(get_current_user_optimized)):
    return job_view(await _owned(request, user, job_id))


@router.get("/jobs/{job_id}/runs")
async def job_runs(job_id: str, request: Request, limit: int = 20,
                   user=Depends(get_current_user_optimized)):
    job = await _owned(request, user, job_id)
    async with _pool(request).acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, created_at, updated_at, chat->'models'->>0 AS model,
                   CASE WHEN jsonb_typeof(chat->'messages') = 'array'
                        THEN jsonb_array_length(chat->'messages') ELSE 0 END AS n
            FROM owui_chats
            WHERE user_id = $1 AND chat->>'harvis_cron_job_id' = $2
            ORDER BY updated_at DESC LIMIT $3
            """, _uid(user), str(job.id), max(1, min(int(limit), 100)))
    runs = [{
        "id": str(r["id"]), "title": r["title"] or job.name, "preview": job.prompt[:120],
        "model": r["model"], "message_count": int(r["n"] or 0),
        "started_at": r["created_at"].timestamp(), "last_active": r["updated_at"].timestamp(),
        "ended_at": r["updated_at"].timestamp(), "is_active": False, "archived": False,
        "input_tokens": 0, "output_tokens": 0, "tool_call_count": 0, "source": "cron",
        "profile": PROFILE_NAME, "is_default_profile": True,
    } for r in rows]
    return {"runs": runs, "limit": limit}


async def _apply_update(pool, job: CronJob, updates: dict[str, Any]) -> None:
    sets: list[str] = ["updated_at = NOW()"]
    args: list[Any] = [job.id]
    meta = dict(job.metadata or {})

    def add(col: str, value: Any) -> None:
        args.append(value)
        sets.append(f"{col} = ${len(args)}")

    if "name" in updates and str(updates["name"]).strip():
        add("name", str(updates["name"]).strip())
    if "prompt" in updates and str(updates["prompt"]).strip():
        add("prompt", str(updates["prompt"]).strip())
    if "deliver" in updates:
        add("delivery", _delivery(updates["deliver"]))
    if "model" in updates:
        meta["model_name"] = str(updates.get("model") or "").strip()
    if "provider" in updates:
        meta["provider"] = str(updates.get("provider") or "").strip()

    stype, expr = job.schedule_type, job.schedule_expr
    if "schedule" in updates and str(updates["schedule"]).strip():
        stype, expr, display = _schedule_or_400(str(updates["schedule"]))
        meta["schedule_display"] = display
        add("schedule_type", stype.value)
        add("schedule_expr", expr)

    enabled = updates.get("enabled")
    reschedule = "schedule" in updates or enabled is True
    if enabled is False:
        add("status", JobStatus.PAUSED.value)
    elif reschedule and job.status != JobStatus.RUNNING:
        add("status", JobStatus.SCHEDULED.value)
    if reschedule:
        add("next_run_at", compute_next_run(stype, expr, last_run_at=job.last_run_at))

    args.append(json.dumps(meta, default=str))
    sets.append(f"metadata = ${len(args)}::jsonb")
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE cron_jobs SET {', '.join(sets)} WHERE id = $1", *args)


@router.put("/jobs/{job_id}")
async def update_job(job_id: str, request: Request, user=Depends(get_current_user_optimized)):
    job = await _owned(request, user, job_id)
    body = await request.json()
    updates = body.get("updates") if isinstance(body.get("updates"), dict) else body
    await _apply_update(_pool(request), job, updates or {})
    return job_view(await _owned(request, user, job_id))


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, request: Request, user=Depends(get_current_user_optimized)):
    job = await _owned(request, user, job_id)
    await _apply_update(_pool(request), job, {"enabled": False})
    return job_view(await _owned(request, user, job_id))


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, request: Request, user=Depends(get_current_user_optimized)):
    job = await _owned(request, user, job_id)
    if compute_next_run(job.schedule_type, job.schedule_expr, last_run_at=job.last_run_at) is None:
        raise HTTPException(400, "This schedule has no future run left; give it a new schedule.")
    await _apply_update(_pool(request), job, {"enabled": True})
    return job_view(await _owned(request, user, job_id))


@router.post("/jobs/{job_id}/trigger")
async def trigger_job(job_id: str, request: Request, user=Depends(get_current_user_optimized)):
    """Fire now, same dispatch the scheduler tick uses; the schedule itself is untouched."""
    from plugins.cron.runtime import _make_dispatch  # lazy: runtime imports workspace code

    job = await _owned(request, user, job_id)
    try:
        ok, err = await _make_dispatch(request.app)(job)
    except Exception as exc:  # noqa: BLE001
        log.exception("hermes_ui: manual fire of cron job %s failed", job.id)
        ok, err = False, str(exc)
    async with _pool(request).acquire() as conn:
        await conn.execute(
            "UPDATE cron_jobs SET last_run_at = NOW(), run_count = run_count + 1, "
            "error_message = $2, updated_at = NOW() WHERE id = $1",
            job.id, None if ok else (err or "run failed"))
    if not ok:
        raise HTTPException(502, err or "run failed")
    return job_view(await _owned(request, user, job_id))


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, request: Request, user=Depends(get_current_user_optimized)):
    job = await _owned(request, user, job_id)
    return {"ok": bool(await _store(request).delete(job.id))}
