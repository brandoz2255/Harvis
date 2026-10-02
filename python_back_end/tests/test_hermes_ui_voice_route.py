"""The Laya voice router: reading its answer, what each route does, and the ws turn."""

import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import chat, learn, providers, sessions, store, voice_route  # noqa: E402
from plugins.hermes_ui.ws import Connection  # noqa: E402


def _reply(choice, conf):
    return {"model": "laya-rl-agent", "answers": {"route": {
        "type": "choice", "choice": choice, "answer_confidence": conf, "confidence": 0.1}}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("HARVIS_LAYA_URL", "http://laya:8000")
    monkeypatch.setenv("HARVIS_VOICE_FAST_MODEL", "gemma4:e2b")
    monkeypatch.setenv("HARVIS_VOICE_BIG_MODEL", "qwen3.5-9b")
    monkeypatch.setenv("HARVIS_LAYA_MIN_CONFIDENCE", "0.5")
    monkeypatch.setattr(voice_route, "_paused_until", 0.0)


def test_parse_takes_a_confident_known_route_only():
    assert voice_route.parse(_reply("answer_fast", 0.8)) == voice_route.Route("answer_fast", 0.8)
    assert voice_route.parse(_reply("answer_fast", 0.3)) is None  # unsure
    assert voice_route.parse(_reply("dance", 0.9)) is None  # not a route
    assert voice_route.parse({}) is None


def test_plan_maps_each_route_to_a_model_and_mode():
    fast = voice_route.plan(voice_route.Route("answer_fast", 0.9), "llama3.1:8b", "auto")
    assert (fast.model, fast.mode, fast.note) == ("gemma4:e2b", "chat", "")
    big = voice_route.plan(voice_route.Route("escalate", 0.9), "llama3.1:8b", "auto")
    assert (big.model, big.mode) == ("qwen3.5-9b", "chat")
    tool = voice_route.plan(voice_route.Route("tool", 0.9), "llama3.1:8b", "auto")
    assert (tool.model, tool.mode) == ("llama3.1:8b", "auto")  # the workspace detectors decide
    ask = voice_route.plan(voice_route.Route("clarify", 0.9), "", "auto")
    assert ask.model == "gemma4:e2b" and ask.note == voice_route.CLARIFY_NOTE
    # A mode the user asked for outright ("use a team") is never overridden.
    assert voice_route.plan(voice_route.Route("answer_fast", 0.9), "", "orchestrate").mode == "orchestrate"


@pytest.mark.asyncio
async def test_decide_asks_laya_one_choice_question():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(200, json=_reply("escalate", 0.7))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        route = await voice_route.decide("explain how a transformer works", client)
    assert route == voice_route.Route("escalate", 0.7)
    assert seen["url"] == "http://laya:8000/v1/systemone"
    assert '"route"' in seen["body"] and '"choice"' in seen["body"]


@pytest.mark.asyncio
async def test_a_down_router_is_skipped_and_paused(monkeypatch):
    hits = []

    def handler(request):
        hits.append(1)
        raise httpx.ConnectError("no such host")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await voice_route.decide("hi", client) is None
        assert await voice_route.decide("hi again", client) is None
    assert len(hits) == 1  # the second turn did not wait on a dead sidecar


@pytest.mark.asyncio
async def test_router_off_when_url_is_empty(monkeypatch):
    monkeypatch.setenv("HARVIS_LAYA_URL", "")
    assert await voice_route.decide("hi") is None


def _stub_turn(monkeypatch, calls, route):
    async def endpoint(pool, uid):
        return None

    async def recall(pool, uid, q):
        return None

    async def thinking():
        return frozenset()

    async def append(pool, s, role, content, reasoning=""):
        return []

    async def stream_turn(token, turn, model, ep, mode, effort, origin, extra=None):
        calls.update(model=model, mode=mode, turn=turn)
        yield "text", "Hey!"

    async def section(pool, uid):
        return {}

    async def decide(text, client=None):
        calls["asked"] = text
        return route

    monkeypatch.setattr(providers, "resolve_active_endpoint", endpoint)
    monkeypatch.setattr(store, "get_section", section)
    monkeypatch.setattr(learn, "recall_message", recall)
    monkeypatch.setattr(learn, "after_turn", lambda *a, **k: None)
    monkeypatch.setattr(sessions, "append", append)
    monkeypatch.setattr("plugins.hermes_ui.ws.thinking_models", thinking)
    monkeypatch.setattr(chat, "stream_turn", stream_turn)
    monkeypatch.setattr(voice_route, "decide", decide)


class _Conn:
    pool, user_id, token, origin = "pool", 1, "tok", ""

    def __init__(self):
        self.turns, self.runs, self.events = {}, {}, []

    async def emit(self, kind, sid, payload):
        self.events.append((kind, payload))

    _relay = Connection._relay


@pytest.mark.asyncio
async def test_a_spoken_hi_runs_on_the_small_model(monkeypatch):
    calls = {}
    _stub_turn(monkeypatch, calls, voice_route.Route("answer_fast", 0.8))
    conn = _Conn()
    live = sessions.Live(id="v1", user_id=1, model="llama3.1:8b")
    await Connection._run_turn(conn, live, [{"role": "user", "content": "hi"}], voice=True)
    assert calls["asked"] == "hi"
    assert (calls["model"], calls["mode"]) == ("gemma4:e2b", "chat")
    assert any("Voice route: answer fast" in str(p) for _, p in conn.events)


@pytest.mark.asyncio
async def test_clarify_puts_its_note_before_the_spoken_message(monkeypatch):
    calls = {}
    _stub_turn(monkeypatch, calls, voice_route.Route("clarify", 0.7))
    live = sessions.Live(id="v2", user_id=1, model="")
    await Connection._run_turn(_Conn(), live, [{"role": "user", "content": "uh the thing"}], voice=True)
    roles = [m["role"] for m in calls["turn"]]
    assert roles[-2:] == ["system", "user"] and calls["turn"][-1]["content"] == "uh the thing"


@pytest.mark.asyncio
async def test_a_typed_turn_never_asks_the_router(monkeypatch):
    calls = {}
    _stub_turn(monkeypatch, calls, voice_route.Route("answer_fast", 0.9))
    live = sessions.Live(id="v3", user_id=1, model="llama3.1:8b")
    await Connection._run_turn(_Conn(), live, [{"role": "user", "content": "hi"}])
    assert "asked" not in calls
    assert (calls["model"], calls["mode"]) == ("llama3.1:8b", "auto")


PAGES = {"settings": "Settings", "notebooks": "Notebooks"}


def _page_reply(choice, conf):
    return {"answers": {"page": {"type": "choice", "choice": choice, "answer_confidence": conf}}}


@pytest.mark.asyncio
async def test_pick_page_offers_every_page_plus_stay():
    seen = {}

    def handler(request):
        seen["body"] = request.read().decode()
        return httpx.Response(200, json=_page_reply("notebooks", 0.9))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        route = await voice_route.pick_page("open my notebooks", PAGES, client)
    assert route == voice_route.Route("notebooks", 0.9)
    assert '"notebooks"' in seen["body"] and '"settings"' in seen["body"] and '"stay"' in seen["body"]


@pytest.mark.asyncio
async def test_pick_page_ignores_stay_unsure_and_unknown():
    for reply in (_page_reply("stay", 0.9), _page_reply("settings", 0.7), _page_reply("admin", 0.9)):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r, j=reply: httpx.Response(200, json=j))) as c:
            assert await voice_route.pick_page("open settings", PAGES, c) is None


def test_clean_pages_drops_bad_ids_and_caps_the_list():
    raw = [{"id": "settings", "label": "  Settings  "}, {"id": "../etc", "label": "x"}, {"id": "stay", "label": "x"},
           {"id": "ok", "label": ""}, "junk"] + [{"id": f"p{i}", "label": "P"} for i in range(60)]
    pages = voice_route.clean_pages(raw)
    assert pages["settings"] == "Settings"
    assert "../etc" not in pages and "stay" not in pages and "ok" not in pages
    assert len(pages) == voice_route.MAX_PAGES


@pytest.mark.asyncio
async def test_a_thought_with_no_answer_is_asked_again_without_thinking(monkeypatch):
    calls = {}
    _stub_turn(monkeypatch, calls, None)
    efforts = []

    async def thinking():
        return frozenset({"gemma4:e2b"})

    async def stream_turn(token, turn, model, ep, mode, effort, origin, extra=None):
        efforts.append((effort, mode))
        if effort != "none":
            yield "reasoning", "Thinking Process: respond simply."
            return
        yield "text", "What's up?"

    monkeypatch.setattr("plugins.hermes_ui.ws.thinking_models", thinking)
    monkeypatch.setattr(chat, "stream_turn", stream_turn)
    conn = _Conn()
    await Connection._run_turn(conn, sessions.Live(id="t1", user_id=1, model="gemma4:e2b"),
                               [{"role": "user", "content": "Damn."}])
    assert efforts == [("medium", "auto"), ("none", "chat")]
    assert ("message.complete", {"text": "What's up?"}) in conn.events


@pytest.mark.asyncio
async def test_an_answered_thought_is_not_asked_again(monkeypatch):
    calls = {}
    _stub_turn(monkeypatch, calls, None)
    efforts = []

    async def thinking():
        return frozenset({"gemma4:e2b"})

    async def stream_turn(token, turn, model, ep, mode, effort, origin, extra=None):
        efforts.append(effort)
        yield "reasoning", "hmm"
        yield "text", "Hi!"

    monkeypatch.setattr("plugins.hermes_ui.ws.thinking_models", thinking)
    monkeypatch.setattr(chat, "stream_turn", stream_turn)
    await Connection._run_turn(_Conn(), sessions.Live(id="t2", user_id=1, model="gemma4:e2b"),
                               [{"role": "user", "content": "hi"}])
    assert efforts == ["medium"]


@pytest.mark.asyncio
async def test_a_plain_voice_turn_is_the_model_and_nothing_else(monkeypatch):
    calls = {}
    _stub_turn(monkeypatch, calls, voice_route.Route("answer_fast", 0.9))
    seen = {}

    async def thinking():
        return frozenset({"gemma4:e2b"})

    async def recall(pool, uid, q):
        seen["recall"] = True

    async def skill(pool, uid, q):
        seen["skill"] = True

    async def stream_turn(token, turn, model, ep, mode, effort, origin, extra=None):
        seen.update(model=model, mode=mode, effort=effort, extra=extra)
        yield "text", "Sure."

    monkeypatch.setattr("plugins.hermes_ui.ws.thinking_models", thinking)
    monkeypatch.setattr(learn, "recall_message", recall)
    monkeypatch.setattr("plugins.hermes_ui.ws.skill_select.skill_message", skill)
    monkeypatch.setattr(learn, "after_turn", lambda *a, **k: seen.setdefault("learned", True))
    monkeypatch.setattr(chat, "stream_turn", stream_turn)

    await Connection._run_turn(_Conn(), sessions.Live(id="p1", user_id=1, model="gemma4:e2b"),
                               [{"role": "user", "content": "build me a website"}], voice=True, plain=True)

    assert (seen["model"], seen["mode"], seen["effort"]) == ("gemma4:e2b", "chat", "none")
    assert seen["extra"] == {"harvis_research": False, "harvis_plain": True, "max_tokens": 80}
    assert "asked" not in calls  # Laya never picks a heavier lane
    assert not {"recall", "skill", "learned"} & seen.keys()
