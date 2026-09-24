"""Bots for the Hermes UI: validation, the chat binding, and the ws turn."""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import bots, chat, learn, providers, sessions, store  # noqa: E402
from plugins.hermes_ui.ws import Connection  # noqa: E402

NB = "0f6d2a2e-4a0b-4c9b-9d2c-1c7d2c0a1234"


def _bot(**over):
    base = {"id": "b1", "name": "Paper Bot", "description": "Reads papers.", "instructions": "",
            "model": "gemma4:e2b", "avatar": {"emoji": "📄"}, "notebook_ids": [NB],
            "starter_prompts": [], "tools": {"web_research": True, "workspace_agent": True}}
    base.update(over)
    return base


# ─── validation ──────────────────────────────────────────────────────────────

def test_clean_bot_keeps_the_allowed_fields_and_caps_them():
    out = bots.clean_bot({
        "name": "  Paper Bot ", "description": "x", "instructions": "be brief", "model": "gemma4:e2b",
        "avatar": {"emoji": "📄"}, "notebook_ids": [NB.upper(), NB], "starter_prompts": ["a", " ", "b"],
        "tools": {"web_research": 0, "workspace_agent": "yes", "shell": True}, "runs_on": {"kind": "vm"},
    })
    assert out == {
        "title": "Paper Bot", "description": "x", "system_prompt": "be brief", "model": "gemma4:e2b",
        "avatar": {"emoji": "📄"}, "notebook_ids": [NB], "starter_prompts": ["a", "b"],
        "tools": {"web_research": False, "workspace_agent": True},
    }


@pytest.mark.parametrize("bad", [
    {"name": ""},
    {"name": "x" * (bots.MAX_NAME + 1)},
    {"name": "ok", "instructions": "y" * (bots.MAX_INSTRUCTIONS + 1)},
    {"name": "ok", "notebook_ids": ["not-a-uuid"]},
    {"name": "ok", "notebook_ids": [NB] * (bots.MAX_NOTEBOOKS + 1)},
    {"name": "ok", "starter_prompts": ["p"] * (bots.MAX_STARTERS + 1)},
    {"name": "ok", "avatar": {"image": "javascript:alert(1)"}},
    {"name": "ok", "avatar": {"emoji": "<img>"}},
    {"name": "ok", "avatar": "🤖"},
    {"name": "ok", "tools": ["web_research"]},
])
def test_clean_bot_rejects_bad_input(bad):
    with pytest.raises(bots.BotError):
        bots.clean_bot(bad)


def test_avatar_accepts_a_small_data_uri_or_https_url():
    assert bots.clean_avatar({"image": "data:image/png;base64,iVBORw0KGgo="}) == {
        "image": "data:image/png;base64,iVBORw0KGgo="}
    assert bots.clean_avatar({"image": "https://example.com/a.png", "emoji": "x"}) == {
        "image": "https://example.com/a.png"}
    assert bots.clean_avatar({"emoji": "", "image": ""}) == {}


def test_handle_is_a_kebab_slug_that_starts_with_a_letter():
    assert bots.handle_for("Paper Bot!") == "paper-bot"
    assert bots.handle_for("2026 planner") == "bot-2026-planner"
    assert bots.handle_for("🤖") == "bot"
    assert len(bots.handle_for("a" * 80)) <= 40


# ─── chat binding ────────────────────────────────────────────────────────────

def test_system_message_uses_instructions_or_falls_back_to_name_and_description():
    assert bots.system_message(_bot(instructions="Answer in haiku."))["content"] == "Answer in haiku."
    assert bots.system_message(_bot())["content"] == "You are Paper Bot. Reads papers."


def test_knowledge_context_numbers_passages_and_drops_weak_ones():
    ctx = bots.knowledge_context([
        {"score": 0.9, "text": "Alpha " * 300, "source": "paper.pdf", "notebook": "Thesis"},
        {"score": 0.05, "text": "noise", "source": "x", "notebook": "y"},
    ])
    assert ctx["role"] == "system"
    assert "[1] paper.pdf — Thesis" in ctx["content"]
    assert "[2]" not in ctx["content"]
    assert "Sources:" in ctx["content"]
    assert len(ctx["content"]) < bots.PASSAGE_CHARS + 600
    assert bots.knowledge_context([]) is None


@pytest.mark.asyncio
async def test_prepare_turn_leads_with_instructions_then_knowledge(monkeypatch):
    seen = {}

    async def fake_retrieve(pool, uid, ids, query, top_k):
        seen.update(uid=uid, ids=ids, query=query, top_k=top_k)
        return [{"score": 0.8, "text": "The answer is 42.", "source": "hhgttg.txt", "notebook": "Books"}]

    monkeypatch.setattr(bots, "_retrieve", fake_retrieve)
    msgs = [{"role": "user", "content": "what is the answer?"}]
    turn = await bots.prepare_turn("pool", 7, _bot(instructions="Be Deep Thought."), msgs, "what is the answer?")

    assert seen == {"uid": 7, "ids": [NB], "query": "what is the answer?", "top_k": bots.KNOWLEDGE_TOP_K}
    assert [m["role"] for m in turn] == ["system", "user"]
    assert turn[0]["content"].startswith("Be Deep Thought.\n\n## Knowledge")
    assert "[1] hhgttg.txt — Books\nThe answer is 42." in turn[0]["content"]
    assert turn[1] is msgs[0]


@pytest.mark.asyncio
async def test_prepare_turn_folds_a_leading_recall_into_the_one_system_message(monkeypatch):
    recall = {"role": "system", "content": "The user likes llamas."}
    user = {"role": "user", "content": "hi"}
    turn = await bots.prepare_turn("pool", 7, _bot(notebook_ids=[], instructions="Be brief."), [recall, user], "hi")
    assert turn == [{"role": "system", "content": "Be brief.\n\nThe user likes llamas."}, user]


@pytest.mark.asyncio
async def test_prepare_turn_survives_a_broken_knowledge_search(monkeypatch):
    async def boom(*_a):
        raise RuntimeError("pgvector down")

    monkeypatch.setattr(bots, "_retrieve", boom)
    turn = await bots.prepare_turn("pool", 7, _bot(), [{"role": "user", "content": "hi"}], "hi")
    assert [m["role"] for m in turn] == ["system", "user"]


@pytest.mark.asyncio
async def test_prepare_turn_skips_retrieval_without_notebooks(monkeypatch):
    async def never(*_a):
        raise AssertionError("should not search")

    monkeypatch.setattr(bots, "_retrieve", never)
    turn = await bots.prepare_turn("pool", 7, _bot(notebook_ids=[]), [], "hi")
    assert len(turn) == 1


def test_tool_switches_narrow_the_turn():
    assert bots.turn_mode(_bot(), "auto") == "auto"
    assert bots.turn_mode(_bot(tools={"workspace_agent": False}), "agent") == "chat"
    assert bots.turn_mode(None, "agent") == "agent"
    assert bots.turn_extra(_bot()) == {}
    assert bots.turn_extra(_bot(tools={"web_research": False})) == {"harvis_research": False}
    assert bots.turn_extra(None) == {}


def test_research_bridge_honours_an_explicit_false():
    from owui_compat import research_bridge as rb

    body = {"harvis_research": False, "messages": [{"role": "user", "content": "deep research on llamas"}]}
    assert asyncio.run(rb.maybe_handle_research(None, body, None)) is None


def test_stream_completion_sends_extra_flags_only_to_harvis(monkeypatch):
    captured = []

    class FakeResp:
        status_code = 500
        headers = {}

        async def aread(self):
            return b"stop"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, json, headers):
            captured.append((url, json))
            return FakeResp()

    monkeypatch.setattr(chat.httpx, "AsyncClient", FakeClient)

    async def run(endpoint):
        try:
            async for _ in chat._stream_completion("t", [], "m", endpoint, "auto", "", {"harvis_research": False}):
                pass
        except chat.ChatError:
            pass

    asyncio.run(run(None))
    asyncio.run(run({"base_url": "https://api.example.com/v1", "api_key": "k", "model": "x"}))
    assert captured[0][1]["harvis_research"] is False
    assert "harvis_research" not in captured[1][1]


# ─── sessions ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bot_session_starts_on_the_bot_model_without_saving_a_default(monkeypatch):
    async def no_save(*_a):
        raise AssertionError("bot model must not become the user's default")

    async def resolve(pool, uid):
        return "fallback-model"

    monkeypatch.setattr(store, "set_default_model", no_save)
    monkeypatch.setattr(store, "resolve_model", resolve)
    s = await sessions.create("pool", 1, bot=_bot())
    assert (s.model, s.bot_id) == ("gemma4:e2b", "b1")
    s2 = await sessions.create("pool", 1, bot=_bot(model=""))
    assert (s2.model, s2.bot_id) == ("fallback-model", "b1")
    s3 = await sessions.create("pool", 1, model="picked", bot=_bot())
    assert s3.model == "picked"


@pytest.mark.asyncio
async def test_bot_id_rides_in_the_chat_blob_and_back(monkeypatch):
    inserted = {}

    async def get_blob(pool, uid, sid):
        return None

    async def insert_chat(pool, uid, sid, blob):
        inserted.update(blob)
        return "Title"

    monkeypatch.setattr(store, "get_blob", get_blob)
    monkeypatch.setattr(store, "insert_chat", insert_chat)
    s = sessions.Live(id="s9", user_id=1, model="m", bot_id="b1")
    await sessions.append("pool", s, "user", "hello")
    assert inserted["bot_id"] == "b1"

    async def get_blob2(pool, uid, sid):
        return dict(inserted, _title="Title")

    monkeypatch.setattr(store, "get_blob", get_blob2)
    sessions.forget("s9")
    opened, msgs = await sessions.open("pool", 1, "s9")
    assert opened.bot_id == "b1"
    assert [m["role"] for m in msgs] == ["user"]


def test_session_info_carries_the_bot_id():
    row = {"id": "s1", "title": "t", "preview": "", "created": 0, "updated": 0, "message_count": 0,
           "model": "m", "pinned": False, "archived": False, "bot_id": "b1"}
    assert sessions.to_session_info(row)["bot_id"] == "b1"
    assert sessions.to_session_info(dict(row, bot_id=""))["bot_id"] is None


# ─── the ws turn ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_turn_binds_the_bot_every_turn(monkeypatch):
    calls = {}

    async def get_bot(pool, uid, bot_id):
        calls["bot_id"] = bot_id
        return _bot(instructions="You are Paper Bot.", tools={"web_research": False, "workspace_agent": False})

    async def fake_retrieve(pool, uid, ids, query, top_k):
        return [{"score": 0.9, "text": "Passage.", "source": "p.pdf", "notebook": "N"}]

    async def endpoint(pool, uid):
        return None

    async def section(pool, uid):
        return {"chat_mode": "agent"}

    async def recall(pool, uid, q):
        return None

    async def thinking():
        return frozenset()

    async def append(pool, s, role, content, reasoning=""):
        calls["assistant"] = content
        return []

    async def stream_turn(token, turn, model, ep, mode, effort, origin, extra=None):
        calls.update(turn=turn, model=model, mode=mode, origin=origin, extra=extra)
        yield "text", "42"

    monkeypatch.setattr(bots, "get_bot", get_bot)
    monkeypatch.setattr(bots, "_retrieve", fake_retrieve)
    monkeypatch.setattr(providers, "resolve_active_endpoint", endpoint)
    monkeypatch.setattr(store, "get_section", section)
    monkeypatch.setattr(learn, "recall_message", recall)
    monkeypatch.setattr(learn, "after_turn", lambda *a, **k: None)
    monkeypatch.setattr(sessions, "append", append)
    monkeypatch.setattr("plugins.hermes_ui.ws.thinking_models", thinking)
    monkeypatch.setattr(chat, "stream_turn", stream_turn)

    emitted = []

    class Conn:
        pool, user_id, token, origin = "pool", 1, "tok", "http://o"
        turns, runs = {}, {}

        async def emit(self, kind, sid, payload):
            emitted.append(kind)

        _relay = Connection._relay

    live = sessions.Live(id="s1", user_id=1, model="gemma4:e2b", bot_id="b1", running=True)
    msgs = [{"role": "user", "content": "what does the paper say?"}]
    await Connection._run_turn(Conn(), live, msgs)

    assert calls["bot_id"] == "b1"
    assert [m["role"] for m in calls["turn"]] == ["system", "user"]
    assert calls["turn"][0]["content"].startswith("You are Paper Bot.")
    assert "[1] p.pdf — N" in calls["turn"][0]["content"]
    assert calls["mode"] == "chat"
    assert calls["extra"] == {"harvis_research": False}
    assert calls["origin"] == "http://o"
    assert calls["assistant"] == "42"
    assert "message.complete" in emitted and live.running is False


@pytest.mark.asyncio
async def test_run_turn_without_a_bot_is_unchanged(monkeypatch):
    calls = {}

    async def get_bot(*_a):
        raise AssertionError("no bot lookup for a plain chat")

    async def endpoint(pool, uid):
        return None

    async def section(pool, uid):
        return {"chat_mode": "auto"}

    async def recall(pool, uid, q):
        return None

    async def thinking():
        return frozenset()

    async def append(pool, s, role, content, reasoning=""):
        return []

    async def stream_turn(token, turn, model, ep, mode, effort, origin, extra=None):
        calls.update(turn=turn, mode=mode, extra=extra)
        yield "text", "ok"

    monkeypatch.setattr(bots, "get_bot", get_bot)
    monkeypatch.setattr(providers, "resolve_active_endpoint", endpoint)
    monkeypatch.setattr(store, "get_section", section)
    monkeypatch.setattr(learn, "recall_message", recall)
    monkeypatch.setattr(learn, "after_turn", lambda *a, **k: None)
    monkeypatch.setattr(sessions, "append", append)
    monkeypatch.setattr("plugins.hermes_ui.ws.thinking_models", thinking)
    monkeypatch.setattr(chat, "stream_turn", stream_turn)

    class Conn:
        pool, user_id, token, origin = "pool", 1, "tok", ""
        turns, runs = {}, {}

        async def emit(self, kind, sid, payload):
            pass

        _relay = Connection._relay

    msgs = [{"role": "user", "content": "hi"}]
    await Connection._run_turn(Conn(), sessions.Live(id="s2", user_id=1, model="m"), msgs)
    assert calls == {"turn": msgs, "mode": "auto", "extra": {}}
