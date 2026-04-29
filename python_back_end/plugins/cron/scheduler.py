"""Cron scheduler — single-tick loop body.

This module ships the LOGIC for one tick (find due jobs, dispatch each,
record the run, compute the next next_run_at). The TICK LOOP RUNTIME
(60s background task on the gateway thread, à la Hermes
``cron/scheduler.py:tick``) is intentionally not wired here — it
needs an integration point with the FastAPI lifespan that we'll add
when a downstream phase actually needs scheduled jobs to fire in
production. Until then, the scheduler can be tick()'d manually from
tests or a future runtime task.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from .store import CronJobStore, compute_next_run
from .types import CronJob, JobStatus

logger = logging.getLogger(__name__)


# Callback the runtime owner provides — given a job, do whatever dispatch
# means (post to messaging gateway, queue a workspace, etc.) and return
# (success, error_message_or_None).
JobDispatchFn = Callable[[CronJob], Awaitable[tuple[bool, Optional[str]]]]


class CronScheduler:
    def __init__(self, store: CronJobStore, *, dispatch: JobDispatchFn) -> None:
        self._store = store
        self._dispatch = dispatch

    async def tick(self, *, now: Optional[datetime] = None, limit: int = 50) -> int:
        """Process one tick. Returns the number of jobs dispatched.

        The dispatch callback owns the actual side-effect (send message,
        run workspace, etc.). The scheduler only persists state
        transitions. A failing dispatch leaves the job in 'error' status
        and clears next_run_at — the operator decides whether to retry.
        """
        ts = now or datetime.now(timezone.utc)
        due = await self._store.find_due(now=ts, limit=limit)
        if not due:
            return 0

        dispatched = 0
        for job in due:
            # Claim the job (race-safe via WHERE status='scheduled')
            claimed = await self._store.mark_running(job.id)
            if not claimed:
                continue

            try:
                success, error_message = await self._dispatch(job)
            except Exception as exc:
                logger.exception("cron.tick: dispatch raised for job %s", job.id)
                success = False
                error_message = str(exc)

            next_at = (
                compute_next_run(
                    job.schedule_type,
                    job.schedule_expr,
                    now=ts,
                    last_run_at=ts,
                )
                if success
                else None
            )

            await self._store.record_run(
                job.id,
                success=success,
                error_message=error_message,
                next_run_at=next_at,
            )
            dispatched += 1

        return dispatched
