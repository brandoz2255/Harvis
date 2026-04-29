# Adapted shape from NousResearch/hermes-agent (MIT) — cron/jobs.py.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID


class ScheduleType(str, Enum):
    CRON = "cron"            # POSIX cron expression — needs `croniter`
    INTERVAL = "interval"    # e.g. "30m", "2h", "7d" — fires every N
    ONCE = "once"            # ISO datetime — fires once and completes


class JobStatus(str, Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"  # for ONCE jobs that finished, or jobs the user retired
    ERROR = "error"


@dataclass(frozen=True)
class CronJob:
    id: UUID
    user_id: int
    name: str
    schedule_type: ScheduleType
    schedule_expr: str
    prompt: str
    delivery: Optional[str] = None
    status: JobStatus = JobStatus.SCHEDULED
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    run_count: int = 0
    error_message: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
