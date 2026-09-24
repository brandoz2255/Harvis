"""Schedule text -> Harvis cron_jobs (schedule_type, schedule_expr, display).

The Hermes UI sends one free-text schedule per job: a preset cron expression
("0 9 * * *"), a duration ("every 30m", "2h"), a documented phrase
("every monday 9am", "weekdays at 9:30", "daily at noon") or an ISO
timestamp for a one-off. Harvis stores cron | interval | once rows, so the
phrase grammar is ported from NousResearch/hermes-agent (MIT) cron/jobs.py
and mapped onto those three kinds.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from plugins.cron.types import ScheduleType

_WEEKDAY_TO_CRON_DOW = {
    "sunday": "0", "sun": "0",
    "monday": "1", "mon": "1",
    "tuesday": "2", "tue": "2", "tues": "2",
    "wednesday": "3", "wed": "3", "weds": "3",
    "thursday": "4", "thu": "4", "thur": "4", "thurs": "4",
    "friday": "5", "fri": "5",
    "saturday": "6", "sat": "6",
}
_DAYSPEC_TO_CRON_DOW = {
    "day": "*", "daily": "*", "everyday": "*",
    "weekday": "1-5", "weekdays": "1-5",
    "weekend": "0,6", "weekends": "0,6",
}
_DURATION_RE = re.compile(
    r"^(\d*)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$")
_CRON_FIELD_RE = re.compile(r"^[\d*,/\-A-Za-z?]+$")


class ScheduleError(ValueError):
    pass


def _parse_clock_time(text: str) -> Optional[tuple[int, int]]:
    t = text.strip().lower().replace(" ", "")
    if not t:
        return None
    if t in ("noon", "midday"):
        return (12, 0)
    if t == "midnight":
        return (0, 0)
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", t)
    if not m:
        return None
    hour, minute, meridiem = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = (0 if hour == 12 else hour) if meridiem == "am" else (12 if hour == 12 else hour + 12)
    if hour > 23 or minute > 59:
        return None
    return (hour, minute)


def _natural_to_cron(rest: str) -> Optional[str]:
    """'monday 9am' -> '0 9 * * 1'; 'day at 9am' -> '0 9 * * *'; None if not a phrase."""
    tokens = rest.lower().replace(",", " ").split()
    if not tokens:
        return None
    dow = _DAYSPEC_TO_CRON_DOW.get(tokens[0])
    idx = 1
    if dow is None:
        days: list[str] = []
        while idx <= len(tokens):
            tok = tokens[idx - 1]
            if tok == "and":
                idx += 1
                continue
            mapped = _WEEKDAY_TO_CRON_DOW.get(tok)
            if mapped is None:
                break
            if mapped not in days:
                days.append(mapped)
            idx += 1
        if not days:
            return None
        dow = ",".join(days)
        idx -= 1
    time_tokens = tokens[idx:]
    if time_tokens and time_tokens[0] == "at":
        time_tokens = time_tokens[1:]
    if not time_tokens:
        return None
    parsed = _parse_clock_time(" ".join(time_tokens))
    if parsed is None:
        return None
    hour, minute = parsed
    return f"{minute} {hour} * * {dow}"


def _duration_expr(text: str) -> Optional[str]:
    """'30m' / '2 hours' / 'hour' -> the store's '<n><unit>' form, else None."""
    m = _DURATION_RE.match(text.strip().lower())
    if not m:
        return None
    value = int(m.group(1)) if m.group(1) else 1
    if value <= 0:
        return None
    return f"{value}{m.group(2)[0]}"


def _validate_cron(expr: str, original: str) -> None:
    try:
        from croniter import croniter  # type: ignore
    except ImportError:  # the store logs and skips scheduling; surface it here instead
        raise ScheduleError("cron expressions need the 'croniter' package on the backend")
    try:
        croniter(expr)
    except Exception as exc:  # noqa: BLE001
        raise ScheduleError(f"Invalid schedule '{original}': {exc}") from exc


def parse_schedule(text: str) -> tuple[ScheduleType, str, str]:
    """Return (schedule_type, schedule_expr, display) or raise ScheduleError."""
    original = (text or "").strip()
    if not original:
        raise ScheduleError("Schedule is required")
    lower = original.lower()

    if lower.startswith("every "):
        rest = original[6:].strip()
        expr = _natural_to_cron(rest)
        if expr is not None:
            _validate_cron(expr, original)
            return ScheduleType.CRON, expr, original
        dur = _duration_expr(rest)
        if dur is None:
            raise ScheduleError(
                f"Invalid schedule '{original}': use 'every 30m', 'every 2h', "
                "'every monday 9am' or 'every day at 9am'")
        return ScheduleType.INTERVAL, dur, f"every {dur}"

    expr = _natural_to_cron(lower)
    if expr is not None:
        _validate_cron(expr, original)
        return ScheduleType.CRON, expr, original

    parts = original.split()
    if len(parts) in (5, 6) and all(_CRON_FIELD_RE.match(p) for p in parts):
        expr = " ".join(parts[:5])
        _validate_cron(expr, original)
        return ScheduleType.CRON, expr, expr

    dur = _duration_expr(original)
    if dur is not None:
        return ScheduleType.INTERVAL, dur, f"every {dur}"

    try:
        when = datetime.fromisoformat(original.replace("Z", "+00:00"))
    except ValueError:
        raise ScheduleError(
            f"Invalid schedule '{original}': use a cron expression, 'every 30m', "
            "'every day at 9am', or an ISO timestamp for a one-off")
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when <= datetime.now(timezone.utc):
        raise ScheduleError(f"'{original}' is in the past")
    return ScheduleType.ONCE, when.isoformat(), original
