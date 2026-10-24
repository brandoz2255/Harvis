"""Deep research and chat web search fail loudly instead of finishing 'done' with nothing."""
import asyncio

import pytest

from deep_research import handler as handler_mod
from deep_research import researcher as researcher_mod
from deep_research.researcher import DeepResearcher
from deep_research.visual_report import _extract_report_title
from plugins.hermes_ui import research_follow


def _run(coro):
    return asyncio.run(coro)


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_client(resp):
    class _Client:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return resp
    return _Client


# ── _probe_model: an embedding model cannot write a report ────────────────────

def test_probe_rejects_embedding_model(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(_Resp(200, {"capabilities": ["embedding"]})))
    with pytest.raises(RuntimeError, match="embedding model"):
        _run(handler_mod.ResearchHandler._probe_model("nomic-embed-text"))


def test_probe_accepts_chat_model_and_old_ollama_without_capabilities(monkeypatch):
    import httpx
    for payload in ({"capabilities": ["completion", "tools"]}, {}):
        monkeypatch.setattr(httpx, "AsyncClient", _fake_client(_Resp(200, payload)))
        _run(handler_mod.ResearchHandler._probe_model("qwen3:4b"))


# ── _llm: a thinking model that ran out of tokens is an error, not an answer ──

def _researcher(**kw):
    return DeepResearcher(llm_endpoint="", llm_model="m", llm_headers=None, **kw)


def test_llm_raises_when_content_empty_but_thinking_present(monkeypatch):
    import httpx
    resp = _Resp(200, {"message": {"content": "", "thinking": "Okay, the user wants"}})
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(resp))
    with pytest.raises(RuntimeError, match="thinking"):
        _run(_researcher()._llm([{"role": "user", "content": "hi"}]))


def test_llm_turns_thinking_off_and_returns_content(monkeypatch):
    import httpx
    seen = {}

    class _Client(_fake_client(_Resp(200, {"message": {"content": "answer"}}))):
        async def post(self, url, json=None, **kw):
            seen.update(json)
            return _Resp(200, {"message": {"content": "answer"}})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    assert _run(_researcher()._llm([{"role": "user", "content": "hi"}])) == "answer"
    # Top-level think=False lets hybrid thinkers (qwen3) answer instead of spending the budget reasoning.
    assert seen["think"] is False and "think" not in seen["options"]


def test_llm_empty_content_without_thinking_stays_empty(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(_Resp(200, {"message": {"content": ""}})))
    assert _run(_researcher()._llm([{"role": "user", "content": "hi"}])) == ""


# ── synthesis timeout, final-report fallbacks ─────────────────────────────────

def test_synthesis_timeout_defaults_to_300_and_reads_env(monkeypatch):
    seen = []

    async def fake_llm(self, messages, **kw):
        seen.append(kw["timeout"])
        return "report"

    monkeypatch.setattr(DeepResearcher, "_llm", fake_llm)
    r = _researcher()
    monkeypatch.delenv("DEEP_RESEARCH_SYNTH_TIMEOUT", raising=False)
    _run(r._synthesize("q", [{"url": "u", "summary": "s"}], ""))
    monkeypatch.setenv("DEEP_RESEARCH_SYNTH_TIMEOUT", "450")
    _run(r._synthesize("q", [{"url": "u", "summary": "s"}], ""))
    monkeypatch.setenv("DEEP_RESEARCH_SYNTH_TIMEOUT", "garbage")
    _run(r._synthesize("q", [{"url": "u", "summary": "s"}], ""))
    assert seen == [300, 450, 300]


def test_empty_final_reply_keeps_the_input_report(monkeypatch):
    async def fake_llm(self, messages, **kw):
        return ""

    monkeypatch.setattr(DeepResearcher, "_llm", fake_llm)
    assert _run(_researcher()._final_report("q", "the evolving report")) == "the evolving report"


def test_no_expansion_pass_once_time_is_up(monkeypatch):
    calls = []

    async def fake_llm(self, messages, **kw):
        calls.append(1)
        return "short report"

    monkeypatch.setattr(DeepResearcher, "_llm", fake_llm)
    r = _researcher(max_time=1)
    r._start_time = 0  # long past
    assert _run(r._final_report("q", "x")) == "short report"
    assert len(calls) == 1

    r2 = _researcher(max_time=10_000)
    r2._start_time = researcher_mod.time.time()
    calls.clear()
    _run(r2._final_report("q", "x"))
    assert len(calls) == 2  # short report, time left: expansion is asked for


def test_failed_expansion_keeps_the_first_pass_final_report(monkeypatch):
    replies = iter(["short final report", RuntimeError("model used its whole token budget thinking")])

    async def fake_llm(self, messages, **kw):
        nxt = next(replies)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr(DeepResearcher, "_llm", fake_llm)
    r = _researcher(max_time=10_000)
    r._start_time = researcher_mod.time.time()
    assert _run(r._final_report("q", "the evolving report")) == "short final report"


def test_empty_synthesis_reply_keeps_the_previous_report(monkeypatch):
    async def fake_llm(self, messages, **kw):
        return "  "

    monkeypatch.setattr(DeepResearcher, "_llm", fake_llm)
    out = _run(_researcher()._synthesize("q", [{"url": "u", "summary": "s"}], "round one report"))
    assert out == "round one report"


def test_progress_events_list_queries_in_the_order_they_were_asked(monkeypatch):
    replies = iter(['["first a", "first b"]', '["second a", "first a"]'])

    async def fake_llm(self, messages, **kw):
        return next(replies)

    monkeypatch.setattr(DeepResearcher, "_llm", fake_llm)
    events = []
    r = _researcher(progress_callback=events.append)
    _run(r._generate_queries("q", "", 1))
    assert _run(r._generate_queries("q", "", 2)) == ["second a"]
    r._emit(phase="searching")
    assert events[-1]["queries"] == ["first a", "first b", "second a"]
    assert "second a" in research_follow.progress_line(events[-1])


def _stub_loop(monkeypatch, *, findings, synth_result=""):
    async def plan(self, q): return ""
    async def classify(self, q): return "product"
    async def queries(self, q, report, n): return ["a query"]
    async def search_extract(self, qs, q): return list(findings)
    async def synth(self, q, f, report): return synth_result
    async def stop(self, q, report, n): return True
    for name, fn in (("_create_plan", plan), ("_classify_category", classify),
                     ("_generate_queries", queries), ("_search_and_extract", search_extract),
                     ("_synthesize", synth), ("_should_stop", stop)):
        monkeypatch.setattr(DeepResearcher, name, fn)


def test_findings_become_the_report_when_synthesis_produced_nothing(monkeypatch):
    _stub_loop(monkeypatch, findings=[{"url": "https://x", "title": "X", "summary": "solar is cheap"}])
    got = {}

    async def final(self, q, report):
        got["report"] = report
        return "FINAL"

    monkeypatch.setattr(DeepResearcher, "_final_report", final)
    r = _researcher(max_rounds=1, min_rounds=1, max_time=1000)
    assert _run(r.research("q")) == "FINAL"
    assert "solar is cheap" in got["report"] and "https://x" in got["report"]
    assert r.category == "product"


def test_nothing_found_still_says_so(monkeypatch):
    _stub_loop(monkeypatch, findings=[])
    r = _researcher(max_rounds=1, min_rounds=1, max_time=1000, max_empty_rounds=5)
    assert _run(r.research("q")).startswith("No information could be gathered")


def test_search_unavailable_names_the_cause(monkeypatch):
    _stub_loop(monkeypatch, findings=[])
    r = _researcher(max_rounds=2, min_rounds=1, max_time=1000, max_empty_rounds=1)
    r._last_search_error = "ConnectionError: boom"
    out = _run(r.research("q"))
    assert out.startswith("**Search unavailable**")
    assert "ConnectionError: boom" in out
    assert "search provider settings" not in out


def test_search_failure_reason_comes_from_the_search_agent(monkeypatch):
    import sys
    import types

    class Agent:
        def __init__(self, **kw): self.last_error = ""
        def search_web(self, q):
            self.last_error = "DDGSException: No results found"
            return []

    mod = types.ModuleType("research.web_search")
    mod.WebSearchAgent = Agent
    monkeypatch.setitem(sys.modules, "research.web_search", mod)
    r = _researcher()
    assert _run(r._search("q")) == []
    assert r._last_search_error == "DDGSException: No results found"


# ── handler turns an outage or an empty run into an error ─────────────────────

def _handler_with_report(monkeypatch, report, findings=()):
    async def noprobe(model): return None

    async def fake_research(self, query, **kw):
        self.findings = list(findings)
        return report

    h = handler_mod.ResearchHandler()
    monkeypatch.setattr(handler_mod.ResearchHandler, "_probe_model", staticmethod(noprobe))
    monkeypatch.setattr(DeepResearcher, "research", fake_research)
    return h


def test_handler_raises_on_search_unavailable(monkeypatch):
    h = _handler_with_report(monkeypatch, "**Search unavailable** — Harvis could not get results: X.")
    with pytest.raises(RuntimeError) as e:
        _run(h.call_research_service("q", "m"))
    assert "Search unavailable" in str(e.value) and "**" not in str(e.value)


def test_handler_raises_when_nothing_was_gathered(monkeypatch):
    h = _handler_with_report(monkeypatch, "No information could be gathered for this question.")
    with pytest.raises(RuntimeError, match="found nothing"):
        _run(h.call_research_service("q", "m"))


def test_handler_keeps_a_real_report(monkeypatch):
    h = _handler_with_report(monkeypatch, "## Findings\n\nreal text", findings=[{"url": "u"}])
    out = _run(h.call_research_service("q", "m"))
    assert "real text" in out


def test_detected_category_is_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(handler_mod, "RESEARCH_DATA_DIR", tmp_path)

    class R:
        findings = []
        category = "product"

    entry = {"query": "q", "status": "done", "result": "r", "started_at": 1.0,
             "researcher": R(), "category": None}
    handler_mod.ResearchHandler()._save_result("rp-1", entry)
    import json
    assert json.loads((tmp_path / "rp-1.json").read_text())["category"] == "product"

    entry2 = dict(entry, category="academic")
    handler_mod.ResearchHandler()._save_result("rp-2", entry2)
    assert json.loads((tmp_path / "rp-2.json").read_text())["category"] == "academic"


# ── small fixes ───────────────────────────────────────────────────────────────

def test_title_strips_only_an_h1():
    title, body = _extract_report_title("# Real Title\n\nintro\n\n## Part\n\ntext", "the question")
    assert title == "Real Title" and "Real Title" not in body and "## Part" in body

    title, body = _extract_report_title("intro\n\n## Quick Guide\n\ntext", "the question")
    assert title == "the question"
    assert "## Quick Guide" in body

    title, body = _extract_report_title("# Executive Summary\n\n## Part\n\n# Solar in 2026\n\ntext", "q")
    assert title == "Solar in 2026" and "# Executive Summary" in body and "## Part" in body


def test_progress_line_prefers_the_rounds_own_query():
    line = research_follow.progress_line(
        {"phase": "searching", "round": 2, "queries": ["old", "random"], "query_preview": "this round"})
    assert "this round" in line and "random" not in line
    # Without a preview the last query still names the search.
    assert "b" in research_follow.progress_line({"phase": "searching", "round": 2, "queries": ["a", "b"]})


# ── web search: remember why it came back empty, retry once ───────────────────

def _search_agent(monkeypatch, behaviour):
    from research import web_search

    calls = []

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, q, **kw):
            calls.append((q, kw.get("backend")))
            return behaviour(len(calls))

    monkeypatch.setattr(web_search, "DDGS", FakeDDGS)
    monkeypatch.setattr(web_search.time, "sleep", lambda s: None)
    return web_search.WebSearchAgent(max_results=3), calls


def _row(n):
    return {"title": f"Solar panel efficiency {n}", "href": f"https://example.org/{n}",
            "body": "solar panel efficiency report"}


def test_search_records_the_error_when_every_engine_fails(monkeypatch):
    def boom(n):
        raise ConnectionError("network blocked")

    agent, calls = _search_agent(monkeypatch, boom)
    assert agent.search_web("solar panel efficiency") == []
    assert "ConnectionError" in agent.last_error and "network blocked" in agent.last_error
    assert len(calls) == 3  # original, improved, and one retry of the original
    assert {backend for _, backend in calls} == {"auto"}


def test_search_retry_recovers_when_the_first_engines_answer_nothing(monkeypatch):
    def flaky(n):
        if n < 3:
            raise RuntimeError("No results found")
        return [_row(i) for i in range(5)]

    agent, calls = _search_agent(monkeypatch, flaky)
    out = agent.search_web("solar panel efficiency")
    assert out and agent.last_error == ""
    assert len(calls) == 3


def test_search_without_failure_does_not_retry(monkeypatch):
    agent, calls = _search_agent(monkeypatch, lambda n: [_row(i) for i in range(8)])
    assert agent.search_web("solar panel efficiency")
    assert len(calls) == 1 and agent.last_error == ""


# ── chat: a forced search that found nothing tells the model so ───────────────

def test_note_search_failed_appends_to_text_and_list_content():
    from owui_compat import chat_reach

    msgs = [{"role": "user", "content": "latest rust version"}]
    chat_reach._note_search_failed(msgs, 0)
    assert msgs[0]["content"].startswith("latest rust version")
    assert "did not answer" in msgs[0]["content"] and "Do not write tool calls" in msgs[0]["content"]

    msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    chat_reach._note_search_failed(msgs, 0)
    assert msgs[0]["content"][-1]["type"] == "text" and "web search" in msgs[0]["content"][-1]["text"]


def _inject(monkeypatch, *, forced, context):
    import types
    import agent_reach.tools as art
    from owui_compat import chat_reach

    monkeypatch.setattr(chat_reach, "chat_reach_enabled", lambda: True)
    monkeypatch.setattr(art, "agent_reach_enabled", lambda: True)

    async def fake_gather(*a, **kw):
        return {"context": context, "sources": []}

    monkeypatch.setattr(chat_reach, "gather", fake_gather)
    monkeypatch.setattr(chat_reach, "_remember_turn", lambda *a, **kw: None)
    body = {"model": "m", "messages": [{"role": "user", "content": "What is the latest Rust version?"}]}
    if forced:
        body["features"] = {"web_search": True}
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(pg_pool=None)),
                                    state=types.SimpleNamespace())
    asyncio.run(chat_reach.maybe_inject_reach(request, body, 1))
    return body["messages"][0]["content"]


def test_forced_search_with_no_results_adds_the_notice(monkeypatch):
    assert "did not answer" in _inject(monkeypatch, forced=True, context="")


def test_unforced_search_with_no_results_leaves_the_turn_alone(monkeypatch):
    from owui_compat import reach_gate

    monkeypatch.setattr(reach_gate, "verdict", lambda message: "yes")

    async def toolset_on(pool, user_id):
        return True

    from owui_compat import chat_reach
    monkeypatch.setattr(chat_reach, "_reach_toolset_on", toolset_on)
    assert _inject(monkeypatch, forced=False, context="") == "What is the latest Rust version?"


def test_forced_search_with_results_adds_the_results_not_the_notice(monkeypatch):
    out = _inject(monkeypatch, forced=True, context="[1] Rust 1.99")
    assert "Rust 1.99" in out and "did not answer" not in out
