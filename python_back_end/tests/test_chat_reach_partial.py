"""Chat web search returns partial results instead of timing out empty."""
import asyncio
import time

import pytest

from owui_compat import chat_reach, reach_budget


def _hit(n):
    return {"title": f"T{n}", "url": f"https://example.org/{n}", "snippet": "postgresql release notes"}


# ── clip_query ─────────────────────────────────────────────────────────────

def test_clip_query_short_is_untouched():
    assert reach_budget.clip_query("latest postgresql release") == "latest postgresql release"


def test_clip_query_cuts_at_word_boundary():
    text = " ".join(["alphabet"] * 60)
    out = reach_budget.clip_query(text, 50)
    assert len(out) <= 50
    assert out.split() == ["alphabet"] * len(out.split())  # no half word


def test_clip_query_keeps_whole_word_when_cut_lands_on_space():
    out = reach_budget.clip_query("aaaa bbbb cccc", 9)
    assert out == "aaaa bbbb"


def test_clip_query_unbroken_token_is_hard_cut():
    assert len(reach_budget.clip_query("x" * 500, 100)) == 100


# ── read_many ──────────────────────────────────────────────────────────────

async def _fake_reader(url):
    if "slow" in url:
        await asyncio.sleep(30)
    return {"url": url, "text": "body " + url, "ok": True}


def test_read_many_keeps_finished_pages_and_drops_the_slow_one():
    async def go():
        sink = []
        t0 = time.monotonic()
        abandoned = await reach_budget.read_many(
            ["https://a/1", "https://a/slow", "https://a/2"], _fake_reader, 0.3, sink)
        return sink, abandoned, time.monotonic() - t0

    sink, abandoned, took = asyncio.run(go())
    assert sorted(p["url"] for p in sink) == ["https://a/1", "https://a/2"]
    assert abandoned == 1
    assert took < 2


def test_read_many_survives_outer_cancel_with_pages_kept():
    async def go():
        sink = []
        task = asyncio.ensure_future(reach_budget.read_many(
            ["https://a/1", "https://a/slow"], _fake_reader, 30, sink))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return sink

    assert [p["url"] for p in asyncio.run(go())] == ["https://a/1"]


# ── search timeout ─────────────────────────────────────────────────────────

def test_slow_search_returns_empty_not_hang(monkeypatch):
    import sys
    import types

    class Agent:
        def __init__(self, **kw): pass
        def search_web(self, q, n):
            time.sleep(3)
            return [_hit(1)]

    mod = types.ModuleType("research.web_search")
    mod.WebSearchAgent = Agent
    monkeypatch.setitem(sys.modules, "research", types.ModuleType("research"))
    monkeypatch.setitem(sys.modules, "research.web_search", mod)

    async def go():
        # Timed inside the loop: asyncio.run() itself joins the worker thread on
        # exit, which is a test-harness artifact, not request latency.
        t0 = time.monotonic()
        out = await chat_reach._search("postgres", timeout=0.3)
        return out, time.monotonic() - t0

    out, took = asyncio.run(go())
    assert out == []
    assert took < 2.0


def test_search_receives_clipped_query(monkeypatch):
    import sys
    import types

    seen = []

    class Agent:
        def __init__(self, **kw): pass
        def search_web(self, q, n):
            seen.append(q)
            return []

    mod = types.ModuleType("research.web_search")
    mod.WebSearchAgent = Agent
    monkeypatch.setitem(sys.modules, "research", types.ModuleType("research"))
    monkeypatch.setitem(sys.modules, "research.web_search", mod)
    asyncio.run(chat_reach._search("word " * 200))
    assert seen and len(seen[0]) <= 200 and seen[0].endswith("word")


# ── gather ────────────────────────────────────────────────────────────────

def _stub(monkeypatch, search, read):
    monkeypatch.setattr(chat_reach, "_search", search)
    monkeypatch.setattr(chat_reach, "_read", read)
    monkeypatch.setattr(chat_reach, "_grade", lambda q, r, p: ("ok", []) if p else ("thin", []))


def test_gather_keeps_fast_pages_when_one_fetch_hangs(monkeypatch):
    async def search(q, timeout=12.0):
        return [_hit(1), _hit(2), _hit(3)]

    async def read(url):
        if url.endswith("/3"):
            await asyncio.sleep(30)
        return {"url": url, "text": "page " + url, "ok": True}

    _stub(monkeypatch, search, read)
    monkeypatch.setattr(chat_reach, "_FETCH_BUDGET_S", 0.4)
    out = asyncio.run(chat_reach.gather("q", "m", query="postgres release"))
    assert "page https://example.org/1" in out["context"]
    assert "page https://example.org/2" in out["context"]
    assert "https://example.org/3" in out["sources"]  # still listed from the search


def test_gather_hard_deadline_returns_partial_state(monkeypatch):
    calls = {"n": 0}

    async def search(q, timeout=12.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_hit(1)]
        await asyncio.sleep(30)  # round two hangs entirely
        return []

    async def read(url):
        return {"url": url, "text": "kept page", "ok": True}

    monkeypatch.setattr(chat_reach, "_search", search)
    monkeypatch.setattr(chat_reach, "_read", read)
    monkeypatch.setattr(chat_reach, "_grade", lambda q, r, p: ("thin", []))

    async def nxt(*a, **k):
        return "another query"
    monkeypatch.setattr(chat_reach, "_next_query", nxt)
    monkeypatch.setattr(chat_reach, "_GRACE_S", 0.2)

    t0 = time.monotonic()
    out = asyncio.run(chat_reach.gather(
        "q", "m", query="postgres", deadline=time.monotonic() + 0.5))
    assert time.monotonic() - t0 < 3
    assert "kept page" in out["context"]
    assert "ran out of time" in out["context"]


def test_gather_without_deadline_gets_a_default_budget(monkeypatch):
    """The hedge path passes no deadline; it must not run unbounded."""
    async def search(q, timeout=12.0):
        await asyncio.sleep(30)
        return []

    monkeypatch.setattr(chat_reach, "_search", search)
    monkeypatch.setattr(chat_reach, "_TOTAL_BUDGET_S", 0.3)
    monkeypatch.setattr(chat_reach, "_GRACE_S", 0.2)
    t0 = time.monotonic()
    out = asyncio.run(chat_reach.gather("q", "m", query="postgres"))
    assert out == {"context": "", "sources": []}
    assert time.monotonic() - t0 < 3


def test_gather_nothing_found_is_empty_context(monkeypatch):
    async def search(q, timeout=12.0):
        return []
    monkeypatch.setattr(chat_reach, "_search", search)
    out = asyncio.run(chat_reach.gather("q", "m", query="postgres"))
    assert out["context"] == ""


# ── Agent Reach toolset gate ──────────────────────────────────────────────

class _Req:
    class app:
        class state:
            pg_pool = object()
    class state:
        pass


def _body():
    return {"model": "m", "messages": [{"role": "user", "content": "What is the latest PostgreSQL version?"}]}


@pytest.fixture
def reach_on(monkeypatch):
    import sys
    import types

    mod = types.ModuleType("agent_reach.tools")
    mod.agent_reach_enabled = lambda: True
    monkeypatch.setitem(sys.modules, "agent_reach", types.ModuleType("agent_reach"))
    monkeypatch.setitem(sys.modules, "agent_reach.tools", mod)
    monkeypatch.setattr(chat_reach, "chat_reach_enabled", lambda: True)
    monkeypatch.setattr(chat_reach.reach_gate, "verdict", lambda m: "yes")
    ran = []

    async def fake_gather(*a, **k):
        ran.append(1)
        return {"context": "ctx", "sources": ["https://x/1"]}

    monkeypatch.setattr(chat_reach, "gather", fake_gather)
    return ran


def _section(monkeypatch, section):
    from plugins.hermes_ui import store

    async def get_section(pool, uid):
        return section
    monkeypatch.setattr(store, "get_section", get_section)


def test_reach_off_skips_automatic_lookup(monkeypatch, reach_on):
    _section(monkeypatch, {"disabled_toolsets": ["harvis-reach"]})
    body = _body()
    asyncio.run(chat_reach.maybe_inject_reach(_Req(), body, user_id=5))
    assert reach_on == []
    assert "web_results" not in str(body)


def test_reach_on_grounds_the_turn(monkeypatch, reach_on):
    _section(monkeypatch, {"disabled_toolsets": ["harvis-files"]})
    body = _body()
    asyncio.run(chat_reach.maybe_inject_reach(_Req(), body, user_id=5))
    assert reach_on == [1]
    assert "web_results" in str(body)


def test_forced_search_ignores_the_toggle(monkeypatch, reach_on):
    _section(monkeypatch, {"disabled_toolsets": ["harvis-reach"]})
    body = _body()
    body["features"] = {"web_search": True}
    asyncio.run(chat_reach.maybe_inject_reach(_Req(), body, user_id=5))
    assert reach_on == [1]


def test_toggle_read_failure_fails_open(monkeypatch, reach_on):
    from plugins.hermes_ui import store

    async def boom(pool, uid):
        raise RuntimeError("db down")
    monkeypatch.setattr(store, "get_section", boom)
    body = _body()
    asyncio.run(chat_reach.maybe_inject_reach(_Req(), body, user_id=5))
    assert reach_on == [1]
