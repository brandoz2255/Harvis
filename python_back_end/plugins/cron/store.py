"""Cron job persistence layer.

CronJobStore is the ABC the scheduler talks to. PgCronJobStore is the
Postgres implementation against the cron_jobs table (migration 014).
Other stores (in-memory for tests, file-based for legacy import) can
implement the same shape.
"""

from __future__ import annotations

import abc
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import asyncpg

from .types import CronJob, JobStatus, ScheduleType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# next_run_at computation — pluggable so tests can mock "now"
# ---------------------------------------------------------------------------


_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)


def _parse_interval(expr: str) -> Optional[timedelta]:
    m = _INTERVAL_RE.match(expr or "")
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "s":
        return timedelta(seconds=n)
    if unit == "m":
        return timedelta(minutes=n)
    if unit == "h":
        return timedelta(hours=n)
    if unit == "d":
        return timedelta(days=n)
    return None


def compute_next_run(
    schedule_type: ScheduleType,
    schedule_expr: str,
    *,
    now: Optional[datetime] = None,
    last_run_at: Optional[datetime] = None,
) -> Optional[datetime]:
    """Compute the next firing time, or None if the schedule is exhausted."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if schedule_type == ScheduleType.ONCE:
        try:
            target = datetime.fromisoformat(schedule_expr)
        except ValueError:
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return target if target > now else None

    if schedule_type == ScheduleType.INTERVAL:
        delta = _parse_interval(schedule_expr)
        if delta is None or delta.total_seconds() <= 0:
            return None
        anchor = last_run_at or now
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        nxt = anchor + delta
        return nxt if nxt > now else now + delta

    if schedule_type == ScheduleType.CRON:
        try:
            from croniter import croniter  # type: ignore
        except ImportError:
            logger.error(
                "cron: schedule_type=cron requires the 'croniter' package — "
                "skipping next-run computation for %r",
                schedule_expr,
            )
            return None
        try:
            it = croniter(schedule_expr, now)
            return it.get_next(datetime).astimezone(timezone.utc)
        except Exception:
            logger.exception("cron: invalid cron expression %r", schedule_expr)
            return None

    return None


# ---------------------------------------------------------------------------
# Store ABC
# ---------------------------------------------------------------------------


class CronJobStore(abc.ABC):
    @abc.abstractmethod
    async def create(
        self,
        *,
        user_id: int,
        name: str,
        schedule_type: ScheduleType,
        schedule_expr: str,
        prompt: str,
        delivery: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[CronJob]: ...

    @abc.abstractmethod
    async def get(self, job_id: UUID) -> Optional[CronJob]: ...

    @abc.abstractmethod
    async def list_for_user(self, user_id: int) -> list[CronJob]: ...

    @abc.abstractmethod
    async def find_due(self, *, now: Optional[datetime] = None, limit: int = 50) -> list[CronJob]: ...

    @abc.abstractmethod
    async def mark_running(self, job_id: UUID) -> bool: ...

    @abc.abstractmethod
    async def record_run(
        self,
        job_id: UUID,
        *,
        success: bool,
        error_message: Optional[str] = None,
        next_run_at: Optional[datetime] = None,
    ) -> bool: ...

    @abc.abstractmethod
    async def set_status(self, job_id: UUID, status: JobStatus) -> bool: ...

    @abc.abstractmethod
    async def delete(self, job_id: UUID) -> bool: ...


# ---------------------------------------------------------------------------
# Postgres implementation
# ---------------------------------------------------------------------------


_SELECT_COLS = (
    "id, user_id, name, schedule_type, schedule_expr, prompt, delivery, "
    "status, next_run_at, last_run_at, run_count, error_message, metadata, "
    "created_at, updated_at"
)


def _row_to_job(row) -> CronJob:
    return CronJob(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        schedule_type=ScheduleType(row["schedule_type"]),
        schedule_expr=row["schedule_expr"],
        prompt=row["prompt"],
        delivery=row["delivery"],
        status=JobStatus(row["status"]),
        next_run_at=row["next_run_at"],
        last_run_at=row["last_run_at"],
        run_count=row["run_count"],
        error_message=row["error_message"],
        metadata=_load_jsonb(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _load_jsonb(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            return json.loads(value) or {}
        except (TypeError, ValueError):
            return {}
    return {}


class PgCronJobStore(CronJobStore):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self,
        *,
        user_id: int,
        name: str,
        schedule_type: ScheduleType,
        schedule_expr: str,
        prompt: str,
        delivery: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[CronJob]:
        next_run = compute_next_run(schedule_type, schedule_expr)
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO cron_jobs
                        (user_id, name, schedule_type, schedule_expr, prompt,
                         delivery, status, next_run_at, metadata, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, 'scheduled', $7, $8::jsonb, NOW(), NOW())
                    RETURNING {_SELECT_COLS}
                    """,
                    int(user_id),
                    name,
                    schedule_type.value,
                    schedule_expr,
                    prompt,
                    delivery,
                    next_run,
                    json.dumps(metadata or {}, default=str),
                )
        except Exception:
            logger.exception("cron.create failed for user=%s name=%s", user_id, name)
            return None
        return _row_to_job(row)

    async def get(self, job_id: UUID) -> Optional[CronJob]:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_SELECT_COLS} FROM cron_jobs WHERE id = $1",
                    job_id,
                )
        except Exception:
            logger.exception("cron.get failed for %s", job_id)
            return None
        return _row_to_job(row) if row else None

    async def list_for_user(self, user_id: int) -> list[CronJob]:
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT {_SELECT_COLS} FROM cron_jobs WHERE user_id = $1 ORDER BY created_at DESC",
                    int(user_id),
                )
        except Exception:
            logger.exception("cron.list_for_user failed for %s", user_id)
            return []
        return [_row_to_job(r) for r in rows]

    async def find_due(self, *, now: Optional[datetime] = None, limit: int = 50) -> list[CronJob]:
        ts = now or datetime.now(timezone.utc)
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT {_SELECT_COLS}
                    FROM cron_jobs
                    WHERE status = 'scheduled'
                      AND next_run_at IS NOT NULL
                      AND next_run_at <= $1
                    ORDER BY next_run_at ASC
                    LIMIT $2
                    """,
                    ts,
                    int(limit),
                )
        except Exception:
            logger.exception("cron.find_due failed")
            return []
        return [_row_to_job(r) for r in rows]

    async def mark_running(self, job_id: UUID) -> bool:
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE cron_jobs
                    SET status = 'running', updated_at = NOW()
                    WHERE id = $1 AND status = 'scheduled'
                    """,
                    job_id,
                )
        except Exception:
            logger.exception("cron.mark_running failed for %s", job_id)
            return False
        return _changed(result) > 0

    async def record_run(
        self,
        job_id: UUID,
        *,
        success: bool,
        error_message: Optional[str] = None,
        next_run_at: Optional[datetime] = None,
    ) -> bool:
        if next_run_at is not None:
            new_status = JobStatus.SCHEDULED
        else:
            new_status = JobStatus.COMPLETED if success else JobStatus.ERROR
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE cron_jobs
                    SET last_run_at = NOW(),
                        next_run_at = $2,
                        status = $3,
                        run_count = run_count + 1,
                        error_message = $4,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    job_id,
                    next_run_at,
                    new_status.value,
                    error_message,
                )
        except Exception:
            logger.exception("cron.record_run failed for %s", job_id)
            return False
        return _changed(result) > 0

    async def set_status(self, job_id: UUID, status: JobStatus) -> bool:
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE cron_jobs SET status = $2, updated_at = NOW() WHERE id = $1",
                    job_id,
                    status.value,
                )
        except Exception:
            logger.exception("cron.set_status failed for %s", job_id)
            return False
        return _changed(result) > 0

    async def delete(self, job_id: UUID) -> bool:
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute("DELETE FROM cron_jobs WHERE id = $1", job_id)
        except Exception:
            logger.exception("cron.delete failed for %s", job_id)
            return False
        return _changed(result) > 0


def _changed(result: str) -> int:
    try:
        return int((result or "X 0").split()[-1])
    except (ValueError, IndexError):
        return 0
