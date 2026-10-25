"""A deep-research run may go past its planned time (the round in flight and the report
still finish); whoever watches it is told how long it has taken against that plan."""
import asyncio
import time

from deep_research import handler as handler_mod
from deep_research.researcher import DeepResearcher
from plugins.hermes_ui import research_follow
from tests.test_deep_research_failures import _researcher, _stub_loop


def test_a_running_job_reports_its_time_against_the_plan():
    h = handler_mod.ResearchHandler()
    h._active_tasks["rp-1"] = {"status": "running", "progress": {}, "query": "q",
                               "started_at": time.time() - 400, "max_time": 300}
    status = h.get_status("rp-1")
    assert 399 <= status["elapsed"] <= 401 and status["time_budget"] == 300


def test_time_lines_say_when_the_plan_is_passed():
    assert research_follow.time_line(45, 300) == "45 s in, planned about 5 min"
    assert research_follow.time_line(240, 300) == "4 min in, planned about 5 min"
    over = research_follow.time_line(400, 300)
    assert over.startswith("6 min in, past the planned 5 min") and "Still working" in over
    assert research_follow.time_line(90, 0) == "1 min in"


def test_the_finished_reply_says_how_long_it_took():
    text = research_follow.report_text("rp-0123456789ab", "body", [], "", took=361)
    assert "took 6 min" in text
    assert "took" not in research_follow.report_text("rp-0123456789ab", "body", [], "")


def test_writing_past_the_planned_time_says_so(monkeypatch):
    _stub_loop(monkeypatch, findings=[{"url": "https://x", "title": "X", "summary": "s"}], synth_result="R")

    async def final(self, q, report):
        return "FINAL"

    monkeypatch.setattr(DeepResearcher, "_final_report", final)
    events = []
    r = _researcher(max_rounds=1, min_rounds=1, max_time=1000, progress_callback=events.append)
    monkeypatch.setattr(r, "_time_exceeded", lambda: bool(r.findings))  # out of time after round one
    assert asyncio.run(r.research("q")) == "FINAL"
    writing = [e for e in events if e.get("phase") == "writing"][-1]
    assert writing["over_time"] is True and "Planned time is up" in writing["message"]
    assert "Planned time is up" in research_follow.progress_line(writing)


def test_writing_in_time_has_no_overtime_note(monkeypatch):
    _stub_loop(monkeypatch, findings=[{"url": "https://x", "title": "X", "summary": "s"}], synth_result="R")

    async def final(self, q, report):
        return "FINAL"

    monkeypatch.setattr(DeepResearcher, "_final_report", final)
    events = []
    r = _researcher(max_rounds=1, min_rounds=1, max_time=1000, progress_callback=events.append)
    asyncio.run(r.research("q"))
    writing = [e for e in events if e.get("phase") == "writing"][-1]
    assert "over_time" not in writing and "message" not in writing


class _Resp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


def test_the_chat_follower_adds_a_time_line_each_minute(monkeypatch):
    polls = iter([
        {"status": "running", "progress": {"phase": "planning"}, "elapsed": 30, "time_budget": 120},
        {"status": "running", "progress": {"phase": "planning"}, "elapsed": 70, "time_budget": 120},
        {"status": "running", "progress": {"phase": "planning"}, "elapsed": 75, "time_budget": 120},
        {"status": "running", "progress": {"phase": "writing"}, "elapsed": 190, "time_budget": 120},
        {"status": "done", "progress": {}, "elapsed": 361, "time_budget": 120},
    ])

    class Client:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return _Resp(next(polls))
        async def post(self, *a, **kw): return _Resp({"result": "the report", "sources": []})

    async def no_wait(_s):
        return None

    monkeypatch.setattr(research_follow.httpx, "AsyncClient", Client)
    monkeypatch.setattr(research_follow.asyncio, "sleep", no_wait)

    async def collect():
        return [x async for x in research_follow.follow_research("tok", "rp-0123456789ab")]

    out = asyncio.run(collect())
    lines = [v for k, v in out if k == "reasoning"]
    assert "1 min in, planned about 2 min\n" in lines
    assert sum("1 min in" in v for v in lines) == 1  # once per minute, not once per poll
    assert any(v.startswith("3 min in, past the planned 2 min") for v in lines)
    assert out[-1][0] == "text" and "took 6 min" in out[-1][1]
