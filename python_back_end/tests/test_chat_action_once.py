"""One-off chat reminders ("remind me to stretch tomorrow at 9pm") and the note that keeps the chat
model from claiming a reminder the tool pre-pass never set.

Split from test_chat_actions.py, whose fake router, fake cron store and fixtures it reuses.
"""

import asyncio
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import chat_action_handlers as handlers, chat_actions, chat_completion  # noqa: E402
from owui_compat.chat_action_schedule import one_off_when  # noqa: E402
from plugins.cron.types import ScheduleType  # noqa: E402
from tests.test_chat_actions import USER, FakeRouter, body, fresh, request, say, store  # noqa: E402,F401

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 24, 18, 30, tzinfo=LA)


@pytest.mark.parametrize("phrase,expected", [
    ("tomorrow at 9pm", "2026-10-25T21:00:00-07:00"),
    ("at 5pm", "2026-10-25T17:00:00-07:00"),  # already past today: tomorrow
    ("8:15 pm", "2026-10-24T20:15:00-07:00"),
    ("tonight at 9", "2026-10-24T21:00:00-07:00"),
    ("this evening at 7", "2026-10-24T19:00:00-07:00"),
    ("tomorrow morning at 8", "2026-10-25T08:00:00-07:00"),
    ("at 17:30", "2026-10-25T17:30:00-07:00"),
    ("at 12am tomorrow", "2026-10-25T00:00:00-07:00"),
    ("in 20 minutes", "2026-10-24T18:50:00-07:00"),
    ("in an hour", "2026-10-24T19:30:00-07:00"),
])
def test_one_off_phrases_become_a_local_time(phrase, expected):
    assert one_off_when(phrase, NOW) == expected


@pytest.mark.parametrize("phrase", [
    "at 9", "tomorrow at 9",  # morning or night is the user's to say
    "tonight at 2", "2 eggs", "at 17pm", "at 9:75pm", "in 0 minutes", "tomorrow at 9pm tomorrow", "",
])
def test_phrases_that_are_not_a_clear_one_off_time_are_left_alone(phrase):
    assert one_off_when(phrase, NOW) is None


@pytest.mark.parametrize("text,when,what", [
    ("remind me to stretch tomorrow at 9pm", "tomorrow at 9pm", "stretch"),
    ("remind me in 10 minutes to check the oven", "in 10 minutes", "check the oven"),
    ("remind me to check in at 5pm", "at 5pm", "check in"),
    ("Hey Harvis, can you remind me at 8am tomorrow to call mom?", "at 8am tomorrow", "call mom"),
])
def test_one_off_reminders_take_the_fast_path(text, when, what):
    assert chat_actions.fast_path(text) == ("remind_once", {"when": when, "what": what})


@pytest.mark.parametrize("text", [
    "remind me to buy 2 eggs", "remind me to call mom tomorrow", "what time is it in 5 hours",
])
def test_reminders_without_a_clear_time_are_not_fast(text):
    assert chat_actions.fast_path(text) is None


def test_a_recurring_reminder_still_takes_the_every_path():
    assert chat_actions.fast_path("remind me to stretch every day at 9pm")[0] == "remind"


def _zone(monkeypatch):
    async def la(pool, user_id):
        return LA
    monkeypatch.setattr(chat_actions, "user_zone", la)
    monkeypatch.setattr(handlers, "user_zone", la)


def test_a_one_off_reminder_is_saved_as_a_once_job_without_a_model(store, monkeypatch):  # noqa: F811 (pytest fixture)
    _zone(monkeypatch)
    out = asyncio.run(chat_actions.maybe_handle_action(
        request(), body("remind me to stretch tomorrow at 9pm"), USER))
    assert FakeRouter.calls == []
    job = store.created[0]
    assert job["user_id"] == 7 and job["name"] == "stretch"
    assert job["schedule_type"] == ScheduleType.ONCE
    when = datetime.fromisoformat(job["schedule_expr"]).astimezone(LA)
    assert (when.hour, when.minute) == (21, 0)
    assert 'Scheduled: "stretch", tomorrow at 9pm.' in say(out)


def test_when_the_tool_choice_times_out_chat_is_told_nothing_was_scheduled(monkeypatch):
    monkeypatch.setattr(chat_actions, "PRE_PASS_BUDGET_S", 0.05)
    FakeRouter.delay = 1.0
    b = body("remind me to call mom tomorrow")
    assert asyncio.run(chat_actions.maybe_handle_action(request(), b, USER)) is None
    chat_completion._inject_turn_notes(b)
    assert "No reminder or scheduled job was created" in b["messages"][0]["content"]
    assert b["messages"][0]["content"].startswith("be nice")  # added to the turn's own system prompt
    assert [m["role"] for m in b["messages"]] == ["system", "user"]
    assert "harvis_turn_notes" not in b


def test_a_turn_with_no_schedule_cue_gets_no_note():
    b = body("tell me a joke")
    assert asyncio.run(chat_actions.maybe_handle_action(request(), b, USER)) is None
    assert "harvis_turn_notes" not in b


def test_a_tool_that_ran_clears_the_note(store, monkeypatch):  # noqa: F811 (pytest fixture)
    _zone(monkeypatch)
    from tests.test_chat_actions import tool_call
    FakeRouter.answer = tool_call("schedule_task", when="every day at 9am", prompt="water the plants")
    b = body("can you schedule watering the plants for me daily at 9am")
    assert asyncio.run(chat_actions.maybe_handle_action(request(), b, USER)) is not None
    assert "harvis_turn_notes" not in b


def test_a_note_with_no_system_prompt_becomes_the_first_message():
    b = {"messages": [{"role": "user", "content": "hi"}], "harvis_turn_notes": ["fact"]}
    chat_completion._inject_turn_notes(b)
    assert b["messages"][0] == {"role": "system", "content": "fact"}
