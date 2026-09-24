"""Hermes UI cron facade: schedule grammar and the Harvis row -> desktop job shape."""

import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.cron.types import CronJob, JobStatus, ScheduleType  # noqa: E402
from plugins.hermes_ui.cron import job_view  # noqa: E402
from plugins.hermes_ui.cron_schedule import ScheduleError, parse_schedule  # noqa: E402


@pytest.mark.parametrize("text, kind, expr", [
    ("0 9 * * *", ScheduleType.CRON, "0 9 * * *"),
    ("0 9 * * 1-5", ScheduleType.CRON, "0 9 * * 1-5"),
    ("*/15 * * * *", ScheduleType.CRON, "*/15 * * * *"),
    ("every monday 9am", ScheduleType.CRON, "0 9 * * 1"),
    ("every day at 9:30pm", ScheduleType.CRON, "30 21 * * *"),
    ("weekdays at noon", ScheduleType.CRON, "0 12 * * 1-5"),
    ("every mon, wed at 7", ScheduleType.CRON, "0 7 * * 1,3"),
    ("every 30m", ScheduleType.INTERVAL, "30m"),
    ("every 2 hours", ScheduleType.INTERVAL, "2h"),
    ("45m", ScheduleType.INTERVAL, "45m"),
    ("hour", ScheduleType.INTERVAL, "1h"),
])
def test_parse_schedule_kinds(text, kind, expr):
    got_kind, got_expr, display = parse_schedule(text)
    assert (got_kind, got_expr) == (kind, expr)
    assert display


def test_parse_once_future_iso():
    when = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    kind, expr, _ = parse_schedule(when.isoformat())
    assert kind == ScheduleType.ONCE
    assert datetime.fromisoformat(expr) == when


@pytest.mark.parametrize("text", ["", "   ", "every", "every banana", "0 9 * *", "61 9 * * *",
                                  "2020-01-01T00:00:00+00:00", "tomorrow"])
def test_parse_rejects_garbage(text):
    with pytest.raises(ScheduleError):
        parse_schedule(text)


def _job(**over):
    base = dict(id=uuid4(), user_id=2, name="Morning brief", schedule_type=ScheduleType.CRON,
                schedule_expr="0 9 * * *", prompt="Summarise my day", delivery=None,
                status=JobStatus.SCHEDULED, next_run_at=datetime(2026, 9, 13, 16, tzinfo=timezone.utc),
                metadata={"schedule_display": "every day at 9am", "model_name": "gemma4:e2b"})
    base.update(over)
    return CronJob(**base)


def test_job_view_shape():
    v = job_view(_job())
    assert v["enabled"] is True and v["state"] == "scheduled"
    assert v["schedule"] == {"kind": "cron", "expr": "0 9 * * *", "display": "every day at 9am"}
    assert v["schedule_display"] == "every day at 9am"
    assert v["next_run_at"] == "2026-09-13T16:00:00+00:00"
    assert v["deliver"] == "local" and v["model"] == "gemma4:e2b"
    assert v["last_error"] is None and v["no_agent"] is False


def test_job_view_paused_is_disabled():
    v = job_view(_job(status=JobStatus.PAUSED, error_message="boom", delivery="discord:123"))
    assert v["enabled"] is False and v["state"] == "paused"
    assert v["last_error"] == "boom" and v["deliver"] == "discord:123"
