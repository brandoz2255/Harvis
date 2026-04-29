"""Cron scheduler runtime — background tick loop wired into FastAPI lifespan.

Activation: HARVIS_CRON_ENABLED=true (default false). Defaulting to OFF
keeps existing deployments unchanged; operators flip the env var when
they want jobs from the cron_jobs table to actually fire.

Tick body lives in plugins/cron/scheduler.py. This module owns the
runtime loop + the dispatch callback that translates a CronJob into a
workspace launch via the existing workspace_router entry point.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from .scheduler import CronScheduler
from .store import PgCronJobStore
from .types import CronJob

logger = logging.getLogger(__name__)


def _make_dispatch(app):
    """Build a CronScheduler dispatch callback bound to ``app``.

    Each fired job becomes a workspace launch with the job's prompt as
    task_brief and the job's user_id as the run owner. Failure during
    launch propagates back to the scheduler as (False, error_message),
    which leaves the job in 'error' status with the message captured.
    """
    async def dispatch(job: CronJob) -> tuple[bool, Optional[str]]:
        try:
            from fastapi import Request
            from workspace.workspace_router import launch_workspace_internal  # type: ignore

            req = Request(scope={"type": "http", "app": app})
            await launch_workspace_internal(
                request=req,
                user_id=job.user_id,
                task_brief=job.prompt,
            )
            return True, None
        except Exception as e:
            logger.exception("cron dispatch failed for job %s (%s)", job.id, job.name)
            return False, str(e)

    return dispatch


async def start_cron_tick_loop(app) -> Optional[asyncio.Task]:
    """Start the cron tick loop. Returns the task or None if disabled.

    Idempotent against repeated lifespan starts (the FastAPI lifespan
    only fires once per process, but tests may activate multiple times).
    Runs forever until cancelled by stop_cron_tick_loop.
    """
    if os.getenv("HARVIS_CRON_ENABLED", "false").lower() != "true":
        return None

    pool = getattr(app.state, "pg_pool", None)
    if pool is None:
        logger.warning("cron tick: no pg_pool on app.state — not starting")
        return None

    try:
        interval = float(os.getenv("HARVIS_CRON_TICK_INTERVAL_S", "60"))
    except ValueError:
        interval = 60.0
    interval = max(5.0, interval)  # floor — tighter polls would hammer the DB

    store = PgCronJobStore(pool)
    sched = CronScheduler(store, dispatch=_make_dispatch(app))

    async def _loop_body():
        logger.info("⏰ cron tick loop started (interval=%.1fs)", interval)
        while True:
            try:
                n = await sched.tick()
                if n > 0:
                    logger.info("cron tick dispatched %d job(s)", n)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("cron tick raised — continuing")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    task = asyncio.create_task(_loop_body(), name="harvis-cron-tick")
    return task


async def stop_cron_tick_loop(task: Optional[asyncio.Task]) -> None:
    """Cancel and await the tick loop. Safe to call with None."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("cron tick shutdown raised")
    logger.info("⏰ cron tick loop stopped")
