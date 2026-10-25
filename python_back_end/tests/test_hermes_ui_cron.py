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


# ── cron expressions in the job's own timezone (daylight saving) ──────────────
LA = "America/Los_Angeles"


def _local_runs(expr, tz, start, count):
    from zoneinfo import ZoneInfo
    from plugins.cron.store import compute_next_run
    now, out = start, []
    for _ in range(count):
        now = compute_next_run(ScheduleType.CRON, expr, now=now, tz=tz)
        out.append(now.astimezone(ZoneInfo(LA)).strftime("%m-%d %H:%M %Z"))
    return out


def test_a_cron_in_a_timezone_keeps_its_local_hour_across_the_2026_11_01_change():
    runs = _local_runs("0 9 * * *", LA, datetime(2026, 10, 30, 12, tzinfo=timezone.utc), 4)
    assert runs == ["10-30 09:00 PDT", "10-31 09:00 PDT", "11-01 09:00 PST", "11-02 09:00 PST"]
    assert _local_runs("30 17 * * 5", LA, datetime(2026, 10, 20, tzinfo=timezone.utc), 3) == [
        "10-23 17:30 PDT", "10-30 17:30 PDT", "11-06 17:30 PST"]


def test_the_result_is_utc_and_a_zone_name_works_as_well_as_a_zone():
    from zoneinfo import ZoneInfo
    from plugins.cron.store import compute_next_run
    now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    a = compute_next_run(ScheduleType.CRON, "0 9 * * *", now=now, tz=LA)
    b = compute_next_run(ScheduleType.CRON, "0 9 * * *", now=now, tz=ZoneInfo(LA))
    assert a == b == datetime(2026, 11, 5, 17, tzinfo=timezone.utc) and a.utcoffset() == timedelta(0)


def test_no_timezone_reads_the_cron_in_utc_exactly_as_before():
    from plugins.cron.store import compute_next_run
    now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    assert compute_next_run(ScheduleType.CRON, "0 9 * * *", now=now) == datetime(2026, 11, 6, 9, tzinfo=timezone.utc)
    assert compute_next_run(ScheduleType.CRON, "0 9 * * *", now=now, tz=None) == datetime(2026, 11, 6, 9, tzinfo=timezone.utc)


def test_the_repeated_hour_when_clocks_fall_back_fires_once():
    runs = _local_runs("30 1 * * *", LA, datetime(2026, 10, 31, 12, tzinfo=timezone.utc), 3)
    assert runs == ["11-01 01:30 PDT", "11-02 01:30 PST", "11-03 01:30 PST"]


def test_interval_and_once_schedules_ignore_the_zone():
    from plugins.cron.store import compute_next_run
    now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    assert compute_next_run(ScheduleType.INTERVAL, "2h", now=now, last_run_at=now, tz=LA) == now + timedelta(hours=2)
    assert compute_next_run(ScheduleType.ONCE, "2026-11-06T09:00:00+00:00", now=now, tz=LA) == datetime(
        2026, 11, 6, 9, tzinfo=timezone.utc)


def test_zone_of_reads_the_job_metadata_and_ignores_junk():
    from plugins.cron.store import zone_of
    assert zone_of({"timezone": LA}).key == LA and zone_of({"timezone": "UTC"}).key == "UTC"
    assert zone_of({}) is None and zone_of(None) is None
    assert zone_of({"timezone": ""}) is None and zone_of({"timezone": "Not/AZone"}) is None
    assert zone_of({"timezone": 5}) is None


def test_the_scheduler_reschedules_a_zoned_job_in_its_zone():
    import asyncio
    from plugins.cron.scheduler import CronScheduler
    job = _job(metadata={"timezone": LA}, next_run_at=datetime(2026, 10, 31, 16, tzinfo=timezone.utc))
    recorded = {}

    class Store:
        async def find_due(self, **kw):
            return [job]

        async def mark_running(self, job_id):
            return True

        async def record_run(self, job_id, **kw):
            recorded.update(kw)
            return True

    async def dispatch(j):
        return True, None

    ran = asyncio.run(CronScheduler(Store(), dispatch=dispatch).tick(now=datetime(2026, 10, 31, 16, 1, tzinfo=timezone.utc)))
    assert ran == 1
    assert recorded["next_run_at"] == datetime(2026, 11, 1, 17, tzinfo=timezone.utc)  # 09:00 PST, not 08:00


def test_job_view_names_the_zone_a_cron_is_written_in():
    v = job_view(_job(metadata={"schedule_display": "every day at 9am", "timezone": LA}))
    assert v["schedule"]["timezone"] == LA and v["schedule"]["expr"] == "0 9 * * *"
    assert "timezone" not in job_view(_job())["schedule"]
    assert "timezone" not in job_view(_job(schedule_type=ScheduleType.INTERVAL, schedule_expr="2h",
                                           metadata={"timezone": LA}))["schedule"]
