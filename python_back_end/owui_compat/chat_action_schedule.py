"""Reading schedule phrases for chat reminders: "every weekday morning at 9" into the text
``cron_schedule.parse_schedule`` understands, a second folded-in request split off, and the
user's own timezone. A cron time is stored as written (local) with ``metadata.timezone``; the
cron store reads it in that zone, so it holds across daylight-saving changes."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

_DAYPART_MERIDIEM = {"morning": "am", "afternoon": "pm", "evening": "pm", "night": "pm"}
_WHEN_RE = re.compile(r"^(?:every|each)\s+(?P<spec>.+?)(?:\s+at\s+(?P<time>.+?))?$")
_DURATION_SPEC = re.compile(r"^(?:\d+\s*)?(?:minutes?|mins?|hours?|hrs?)$")
_BARE_TIME = re.compile(r"^(\d{1,2})(?::(\d{2}))?$")
_WEEKDAY_NAMES = (r"sun|mon|tue|tues|wed|weds|thu|thur|thurs|fri|sat|"
                  r"(?:sun|mon|tues|wednes|thurs|fri|satur)day")
# What may follow "every"/"each" for the phrase to be a schedule at all. "every time you write
# code" and "every so often" are standing instructions for the chat, not something to put in cron.
_SCHEDULE_WORD = re.compile(
    r"^(?:every|each)\s+(?:day|daily|everyday|morning|afternoon|evening|night|weekdays?|weekends?|weeks?|weekly|hours?|"
    r"minutes?|mins?|hrs?|" + _WEEKDAY_NAMES + r"|\d+\s*(?:m|min|mins|minutes?|h|hr|hrs|hours?|d|days?|w|weeks?))\b(?!['\u2019])",
    re.I)  # not "each day's sales": a possessive is part of a sentence, not a schedule
_EVERY_PHRASE = re.compile(r"^\s*(?:every|each)\s+\S", re.I)
# Specs that name a day but no clock time: those get a question instead of a guess.
_DAY_SPECS = frozenset({
    "day", "daily", "everyday", "weekday", "weekdays", "weekend", "weekends", "week", "weekly",
    "morning", "afternoon", "evening", "night",
    "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sun", "mon", "tue", "tues", "wed", "weds", "thu", "thur", "thurs", "fri", "sat",
})


def is_schedule_when(text: str) -> bool:
    """True when ``text`` starts "every"/"each" followed by a real schedule word."""
    return bool(_SCHEDULE_WORD.match(" ".join((text or "").split())))


def normalize_when(text: str, today: str = "") -> tuple[Optional[str], bool]:
    """``(schedule_text, needs_time)`` for "every morning at 8" style phrases.

    "every weekday morning at 9" drops the daypart after a day word, and "every week at 9" runs on
    ``today`` (a lowercase weekday name, the user's own today; UTC's when empty).

    ``schedule_text`` is what ``cron_schedule.parse_schedule`` understands, or None when the
    phrase is not one this can read. ``needs_time`` is True only for a day, daypart or weekday
    phrase with no usable clock time ("every morning", "every morning at 12"), which gets a
    question instead of a guess.
    """
    clean = " ".join((text or "").strip().lower().rstrip(".!").split())
    m = _WHEN_RE.match(clean)
    if not m:
        return None, False
    spec, at = m.group("spec"), m.group("time")
    if _DURATION_SPEC.match(spec):
        return (None, False) if at else (f"every {spec}", False)
    words = spec.split()
    if len(words) == 2 and words[0] in _DAY_SPECS and words[0] not in _DAYPART_MERIDIEM and words[1] in _DAYPART_MERIDIEM:
        spec, daypart = words[0], words[1]  # "weekday morning", "saturday evening"
    else:
        daypart = spec if spec in _DAYPART_MERIDIEM else None
        if daypart:
            spec = "day"
    if spec in ("week", "weekly"):
        spec = today or datetime.now(timezone.utc).strftime("%A").lower()
    elif spec.startswith("week on "):
        spec = spec[8:]
    if not at:
        return None, spec.split()[0] in _DAY_SPECS
    at = at.strip()
    bare = _BARE_TIME.match(at)
    if bare and daypart:
        hour = int(bare.group(1))
        if hour == 12 and daypart == "morning":
            return None, True  # 12 in the morning could mean midnight or noon: ask
        if 1 <= hour <= 12:
            # A bare 12 is noon only in the afternoon; "every night at 12" is midnight, and so is the
            # small-hours "every night at 1" (nobody means 1 PM by night).
            if hour == 12:
                at += "pm" if daypart == "afternoon" else "am"
            elif daypart == "night" and hour <= 4:
                at += "am"
            else:
                at += _DAYPART_MERIDIEM[daypart]
    return f"every {spec} at {at}", False


def split_second_schedule(when: str, what: str) -> tuple[str, str, str]:
    """``(when, what, extra)``: a second "every ... to ..." request folded into one message is cut off.

    "every day at 8 to check email and every friday at 5 to submit timesheet" is two reminders; only
    the first becomes a job, and ``extra`` is the rest so the reply can say plainly it was not set.
    """
    cut = re.search(r"\s+and\s+(?:to|that)\s+", when or "")
    if cut:
        return when[:cut.start()], what, when[cut.start():].strip()[4:]
    for m in re.finditer(r"\b(?:every|each)\s+\S", what or "", re.I):
        tail = what[m.start():]
        head = re.sub(r"(?:[\s,;]+(?:and|then))*[\s,;]*$", "", what[:m.start()], flags=re.I)
        # A second request is joined to the first ("..., and every friday at 5 to ...") and has the
        # whole shape of one: a schedule with a clock time or duration, then "to"/"that" and its text.
        # "take my pills every day so that I do not forget" is one reminder.
        joined = re.search(r"(?:[,;]|\b(?:and|then))\s*$", what[:m.start()], re.I)
        second = re.match(r"(?P<when>(?:every|each)\s+.+?)\s+(?:to|that)\s+\S", tail, re.I | re.S)
        if (head and joined and second and is_schedule_when(tail)
                and normalize_when(second.group("when"))[0]):
            return when, head, tail.strip()
    return when, what, ""


# A one-off: "in 20 minutes", "at 5pm", "tomorrow at 9am", "tonight at 9". A clock time needs "at" or
# am/pm (so "remind me to buy 2 eggs" is not a time), and a bare 1-12 needs am/pm or a daypart to say which.
_ONE_OFF_IN = re.compile(r"^in\s+(?P<n>\d{1,3}|an?|one)\s+(?P<unit>minutes?|mins?|hours?|hrs?)$")
_ONE_OFF_AT = re.compile(
    r"^(?:(?P<day>today|tonight|tomorrow(?:\s+(?:morning|afternoon|evening|night))?|"
    r"this\s+(?:morning|afternoon|evening))\s+)?(?P<at>at\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*"
    r"(?P<ap>[ap])?(?:\.?m\.?)?(?:\s+(?P<day2>today|tonight|tomorrow(?:\s+(?:morning|afternoon|evening|night))?))?$")


def one_off_when(phrase: str, now: datetime) -> Optional[str]:
    """ISO time (with ``now``'s offset) for a one-off reminder phrase, or None when it is not one.

    ``now`` is the user's own current time; a clock time with no day word that has already
    passed today means tomorrow.
    """
    clean = " ".join((phrase or "").strip().lower().rstrip(".!").split())
    m = _ONE_OFF_IN.match(clean)
    if m:
        n = 1 if m.group("n") in ("a", "an", "one") else int(m.group("n"))
        delta = timedelta(hours=n) if m.group("unit").startswith("h") else timedelta(minutes=n)
        return (now + delta).replace(second=0, microsecond=0).isoformat() if n else None
    m = _ONE_OFF_AT.match(clean)
    if not m or (m.group("day") and m.group("day2")):
        return None
    day = m.group("day") or m.group("day2") or ""
    hour, minute, ap = int(m.group("h")), int(m.group("m") or 0), m.group("ap")
    if not (m.group("at") or ap) or minute > 59 or hour > 23:
        return None
    part = day.split()[-1] if day else ""
    part = "night" if part == "tonight" else part
    if 1 <= hour <= 12:
        if ap:
            hour = hour % 12 + (12 if ap == "p" else 0)
        elif part in ("afternoon", "evening") or (part == "night" and hour >= 6):
            hour = hour % 12 + 12
        elif part != "morning":
            return None  # "tomorrow at 9": morning or night is the user's to say
    elif ap:
        return None  # "at 17pm"
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day.startswith("tomorrow"):
        when += timedelta(days=1)
    elif not day and when <= now:
        when += timedelta(days=1)
    return when.isoformat()


async def user_zone(pool, user_id: int) -> Optional[ZoneInfo]:
    """The user's own timezone from the Hermes ``timezone`` setting (as turn_models.time_text reads it)."""
    try:
        from plugins.hermes_ui import settings_store
        from plugins.hermes_ui.rest import CONFIG

        name = str(settings_store.get_path(await settings_store.config_for(pool, user_id, CONFIG), "timezone") or "")
        return ZoneInfo(name.strip()) if name.strip() else None
    except Exception:
        return None
