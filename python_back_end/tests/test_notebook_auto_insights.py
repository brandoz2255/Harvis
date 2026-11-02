"""Insights written for a source once it is ready: Dense Summary, suggested questions, retries,
and the rule that nothing here can fail or block ingestion. The model call, the people
controls and the database are all fakes."""
import asyncio
import json
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import auto_insights as ai  # noqa: E402
from notebooks import transform_llm  # noqa: E402
from notebooks.manager import SourceNotFoundError  # noqa: E402

_real_sleep = asyncio.sleep  # the llm fixture replaces asyncio.sleep for the retry tests

QUESTIONS = (
    "1. What do mitochondria produce for the cell?\n"
    "- Why are ribosomes needed to make proteins?\n"
    "How does the nucleus protect the DNA?\n"
    "What is the role of the cell membrane?\n"
    "Here is some chatter that is not a question.\n"
)


def run(coro):
    return asyncio.run(coro)


class Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class Conn:
    def __init__(self, db):
        self.db = db

    def transaction(self):
        return Tx()

    async def fetchrow(self, sql, *args):
        return self.db.row

    async def fetch(self, sql, *args):
        if self.db.defs_error:
            raise RuntimeError("relation does not exist")
        return self.db.defs

    async def fetchval(self, sql, *args):
        self.db.inserts.append(args)
        return uuid4()

    async def execute(self, sql, *args):
        if sql.startswith("DELETE"):
            self.db.deletes.append(args)
        elif "metadata" in sql and "$1::jsonb" in sql:
            self.db.metadata.append(json.loads(args[0]))
        return "UPDATE 3"


class Acquire:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return Conn(self.db)

    async def __aexit__(self, *a):
        return False


class DB:
    def __init__(self, text="The cell is the basic unit of life. " * 40, status="ready"):
        self.row = {"notebook_id": uuid4(), "content_text": text, "status": status}
        self.defs, self.defs_error = [], False
        self.inserts, self.deletes, self.metadata = [], [], []
        self.pool = SimpleNamespace(acquire=lambda: Acquire(self))


class Manager:
    def __init__(self, db, missing=False):
        self.db_pool = db.pool
        self.missing = missing

    async def get_source(self, sid, uid):
        if self.missing:
            raise SourceNotFoundError("gone")
        return SimpleNamespace(id=sid)


@pytest.fixture
def llm(monkeypatch):
    """A scripted model: returns a summary for the summary prompt and questions for the questions prompt."""
    state = SimpleNamespace(calls=[], fail_times=0, questions=QUESTIONS, summary="**Cells**\n- basic unit of life")

    async def fake(prompt, content, model, **kw):
        state.calls.append((prompt, model, kw))
        if state.fail_times > 0:
            state.fail_times -= 1
            raise RuntimeError("model server down")
        return state.questions if prompt == ai.QUESTIONS_PROMPT else (
            state.summary if prompt == ai.DENSE_SUMMARY_PROMPT else "custom output"
        )

    async def admit(pool, uid, model=None, *, count=True):
        assert count is False and model == ""  # insights never spend the person's daily messages
        return state.admission

    state.admission = SimpleNamespace(ok=True, model="gemma4:e4b", reason="")
    monkeypatch.setattr(transform_llm, "run_transformation_llm", fake)
    monkeypatch.setattr("plugins.people.controls.admit_turn", admit)
    sleeps = []

    async def no_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(ai.asyncio, "sleep", no_sleep)
    state.sleeps = sleeps
    return state


# --- parsing ----------------------------------------------------------------------------------


def test_parse_questions_keeps_real_questions_and_strips_markers():
    got = ai.parse_questions(QUESTIONS)
    assert got == [
        "What do mitochondria produce for the cell?",
        "Why are ribosomes needed to make proteins?",
        "How does the nucleus protect the DNA?",
        "What is the role of the cell membrane?",
    ]


def test_parse_questions_caps_at_five_dedupes_and_needs_three():
    many = "\n".join(f"Question number {i} about cells?" for i in range(9))
    assert len(ai.parse_questions(many)) == 5
    assert len(ai.parse_questions("Same question here?\nSame question here?\nAnother one is here?\nA third one here?")) == 3
    for bad in ("", "no questions here", "Only one question?\nAnd a statement.", "Why?\nHow?\nWhat?"):
        with pytest.raises(ValueError):
            ai.parse_questions(bad)


def test_switches(monkeypatch):
    monkeypatch.delenv("NOTEBOOK_AUTO_INSIGHTS", raising=False)
    assert ai.enabled() and ai.should_run(1000)
    monkeypatch.setenv("NOTEBOOK_AUTO_INSIGHTS_MAX_CHARS", "5000")
    assert ai.should_run(5000) and not ai.should_run(5001)
    for off in ("0", "false", "No", "off"):
        monkeypatch.setenv("NOTEBOOK_AUTO_INSIGHTS", off)
        assert not ai.enabled() and not ai.should_run(10)
    monkeypatch.setenv("NOTEBOOK_AUTO_INSIGHTS_MAX_CHARS", "junk")
    monkeypatch.setenv("NOTEBOOK_AUTO_INSIGHTS", "1")
    assert ai.max_chars() == ai.DEFAULT_MAX_CHARS


# --- the run ------------------------------------------------------------------------------------


def test_a_ready_source_gets_a_summary_questions_and_a_done_status(llm):
    db, sid = DB(), uuid4()
    run(ai.run_default_insights(Manager(db), sid, 7))
    markers = [args[7] for args in db.inserts]
    assert markers == [ai.SUMMARY_MARKER, ai.QUESTIONS_MARKER]
    kinds = [args[3] for args in db.inserts]
    assert kinds == ["summarize", "custom"]  # the types notebook_transformations allows
    assert [args[5] for args in db.inserts][0].startswith("**Cells**")
    final = db.metadata[-1]
    assert final["insights_status"] == "done" and final["insights_model"] == "gemma4:e4b"
    assert len(final["suggested_questions"]) == 4 and final["summary_insight_id"]
    assert llm.sleeps == []


def test_results_replace_the_previous_run_for_the_same_source_and_person(llm):
    db, sid = DB(), uuid4()
    run(ai.run_default_insights(Manager(db), sid, 7))
    assert sorted(a[2] for a in db.deletes) == sorted([ai.SUMMARY_MARKER, ai.QUESTIONS_MARKER])
    assert all(a[0] == sid and a[1] == 7 for a in db.deletes)


def test_the_model_sees_a_spread_of_a_long_source(llm):
    db = DB(text="word " * 30000)
    run(ai.run_default_insights(Manager(db), uuid4(), 1))
    assert all(kw["spread"] is True and kw["max_chars"] == 12000 for _p, _m, kw in llm.calls)
    assert llm.calls[1][2]["num_predict"] == 400


def test_a_flaky_model_is_retried_twice_with_backoff(llm):
    llm.fail_times = 2
    db = DB()
    run(ai.run_default_insights(Manager(db), uuid4(), 1))
    assert llm.sleeps == [2.0, 8.0]
    assert db.metadata[-1]["insights_status"] == "done"


def test_giving_up_records_an_error_and_never_raises(llm):
    llm.fail_times = 99
    db = DB()
    run(ai.run_default_insights(Manager(db), uuid4(), 1))  # must not raise
    assert llm.sleeps == [2.0, 8.0] and len(llm.calls) == 3
    status = db.metadata[-1]
    assert status["insights_status"] == "error" and "RuntimeError" in status["insights_error"]
    assert db.inserts == []  # nothing half-written


def test_unusable_questions_count_as_a_failed_attempt(llm):
    llm.questions = "I cannot think of anything."
    db = DB()
    run(ai.run_default_insights(Manager(db), uuid4(), 1))
    assert db.metadata[-1]["insights_status"] == "error" and db.inserts == []


def test_a_blocked_person_is_skipped_without_retrying(llm):
    llm.admission = SimpleNamespace(ok=False, model="", reason="Your account is paused.")
    db = DB()
    run(ai.run_default_insights(Manager(db), uuid4(), 1))
    assert llm.calls == [] and llm.sleeps == []
    assert db.metadata[-1] == {"insights_status": "error", "insights_error": "Your account is paused."}


def test_no_installed_chat_model_is_skipped(llm, monkeypatch):
    llm.admission = SimpleNamespace(ok=True, model="", reason="")

    async def none():
        return ""

    monkeypatch.setattr(transform_llm, "default_chat_model", none)
    db = DB()
    run(ai.run_default_insights(Manager(db), uuid4(), 1))
    assert llm.calls == [] and "No chat model" in db.metadata[-1]["insights_error"]


def test_the_server_default_model_is_used_when_the_admin_has_no_list(llm, monkeypatch):
    llm.admission = SimpleNamespace(ok=True, model="", reason="")

    async def default():
        return "llama3.1:8b"

    monkeypatch.setattr(transform_llm, "default_chat_model", default)
    db = DB()
    run(ai.run_default_insights(Manager(db), uuid4(), 1))
    assert db.metadata[-1]["insights_model"] == "llama3.1:8b"


def test_a_source_that_is_gone_or_being_reprocessed_is_left_alone(llm):
    db = DB()
    run(ai.run_default_insights(Manager(db, missing=True), uuid4(), 1))
    assert llm.calls == [] and "no longer exists" in db.metadata[-1]["insights_error"]
    db = DB(status="processing")
    run(ai.run_default_insights(Manager(db), uuid4(), 1))
    assert llm.calls == [] and "processed again" in db.metadata[-1]["insights_error"]


def test_custom_default_transformations_are_run_and_stored_by_definition(llm):
    db = DB()
    first, second = uuid4(), uuid4()
    db.defs = [
        {"id": first, "title": "Glossary", "prompt": "List key terms.\n{content}"},
        {"id": second, "title": "Quiz", "prompt": "Write a quiz.\n{content}"},
    ]
    run(ai.run_default_insights(Manager(db), uuid4(), 1))
    markers = [a[7] for a in db.inserts]
    assert markers == [ai.SUMMARY_MARKER, ai.QUESTIONS_MARKER, f"auto:def:{first}", f"auto:def:{second}"]


def test_missing_definitions_table_does_not_stop_the_built_ins(llm):
    db = DB()
    db.defs_error = True
    run(ai.run_default_insights(Manager(db), uuid4(), 1))
    assert db.metadata[-1]["insights_status"] == "done" and len(db.inserts) == 2


def test_cancellation_is_not_swallowed(llm, monkeypatch):
    async def slow(*a, **k):
        raise asyncio.CancelledError()

    monkeypatch.setattr(ai, "_generate", slow)
    with pytest.raises(asyncio.CancelledError):
        run(ai.run_default_insights(Manager(DB()), uuid4(), 1))


# --- scheduling ---------------------------------------------------------------------------------


def test_scheduling_returns_at_once_and_a_reschedule_cancels_the_old_task(monkeypatch):
    async def fake_run(manager, source_id, user_id):
        await _real_sleep(3600)  # the stand-in never finishes on its own

    async def main():
        monkeypatch.setattr(ai, "run_default_insights", fake_run)
        sid = uuid4()
        assert ai.schedule_default_insights(None, sid, 1) is True
        first = ai._tasks[str(sid)]
        await _real_sleep(0)
        assert not first.done()
        assert ai.schedule_default_insights(None, sid, 1) is True
        await _real_sleep(0)
        assert first.cancelled() and ai._tasks[str(sid)] is not first
        ai._tasks[str(sid)].cancel()
        await _real_sleep(0)
        await _real_sleep(0)
        assert str(sid) not in ai._tasks  # finished tasks are forgotten

    run(main())


def test_fail_stuck_insights_counts_rows():
    db = DB()
    assert run(ai.fail_stuck_insights(db.pool)) == 3
    sent = db.metadata[-1]
    assert sent["insights_status"] == "error" and "restart" in sent["insights_error"]
