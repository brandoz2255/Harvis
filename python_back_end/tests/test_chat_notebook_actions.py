"""Chat notebook actions: "make a notebook about X" and "make me a quiz on X".

A fake notebook manager and a fake web search stand in for the database and the network. The properties
that matter: the fast paths only take clear requests, sources come from the user's own links or a web
search (never from a model's argument), the reply carries a pill link to the notebook, and a study
artifact is generated only after a source is ready.
"""

import asyncio
import json
import os
import sys
import types
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import chat_actions, chat_notebook_actions as nb  # noqa: E402
from owui_compat.chat_action_handlers import Ctx  # noqa: E402


def say(resp) -> str:
    async def collect():
        return [c async for c in resp.body_iterator]

    out = ""
    for chunk in asyncio.run(collect()):
        for line in (chunk.decode() if isinstance(chunk, bytes) else chunk).splitlines():
            if line.startswith("data: {"):
                out += json.loads(line[6:])["choices"][0]["delta"].get("content", "")
    return out


class FakeManager:
    def __init__(self, notebooks=()):
        self.notebooks = list(notebooks)
        self.sources: dict = {}
        self.db_pool = object()

    async def create_notebook(self, user_id, req):
        n = types.SimpleNamespace(id=uuid4(), user_id=user_id, title=req.title)
        self.notebooks.append(n)
        return n

    async def list_notebooks(self, user_id, limit, offset):
        mine = [n for n in self.notebooks if n.user_id == user_id]
        return mine, len(mine)

    async def get_notebook(self, notebook_id, user_id):
        return next(n for n in self.notebooks if n.id == notebook_id and n.user_id == user_id)

    async def list_sources(self, notebook_id, user_id):
        return list(self.sources.get(notebook_id, []))

    async def create_source(self, notebook_id, user_id, source_type, title=None, storage_path=None, metadata=None):
        s = types.SimpleNamespace(id=uuid4(), title=title, storage_path=storage_path, status="pending")
        self.sources.setdefault(notebook_id, []).append(s)
        return s


@pytest.fixture
def env(monkeypatch):
    mgr = FakeManager()
    searches, spawned = [], []
    monkeypatch.setattr(nb, "_manager", lambda ctx: mgr)

    async def fake_discover(topic):
        searches.append(topic)
        return [{"url": f"https://example.org/{i}", "title": f"Page {i}"} for i in range(3)]

    monkeypatch.setattr(nb, "_discover", fake_discover)
    monkeypatch.setattr(nb, "_spawn", lambda coro: (spawned.append(coro), coro.close()))
    return types.SimpleNamespace(mgr=mgr, searches=searches, spawned=spawned)


def ctx(text, user_id=7):
    return Ctx(request=object(), body={}, user=types.SimpleNamespace(id=user_id), pool=object(), user_id=user_id,
               text=text)


# ── fast paths ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,topic", [
    ("make a notebook about Mars with some sources", "Mars"),
    ("can you create a new notebook on black holes", "black holes"),
    ("make a notebook with sources about the Roman empire", "the Roman empire"),
    ("Harvis, make me a notebook for rust async, and add a few sources", "rust async"),
])
def test_notebook_fast_path(text, topic):
    assert chat_actions.fast_path(text) == ("make_notebook", {"topic": topic})


@pytest.mark.parametrize("text,args", [
    ("make me a quiz on Mars", {"kind": "quiz", "topic": "Mars", "notebook": ""}),
    ("make flashcards from my Biology notebook", {"kind": "flashcards", "topic": "", "notebook": "Biology"}),
    ("create a mind map of rovers from my Mars notebook", {"kind": "mind map", "topic": "rovers", "notebook": "Mars"}),
    ("give me a study guide for the notebook called Chem 101",
     {"kind": "study guide", "topic": "", "notebook": "Chem 101"}),
])
def test_study_fast_path(text, args):
    assert chat_actions.fast_path(text) == ("make_study", args)


@pytest.mark.parametrize("text", [
    "make a quiz about this", "make a quiz on the code above", "how do I make a notebook about Mars",
    "make a timeline of the release", "the notebook about Mars is great", "make a notebook about it",
])
def test_fast_path_leaves_other_turns(text):
    assert chat_actions.fast_path(text) is None


def test_cues_and_specs():
    assert "make_notebook" in chat_actions.matching_tools("set up a notebook for my thesis reading")
    assert "make_study" in chat_actions.matching_tools("turn my Mars notes into flash cards please")
    assert chat_actions.matching_tools("my notebook battery died") == []
    assert {"make_notebook", "make_study"} <= set(chat_actions.TOOL_SPECS)


# ── make_notebook ────────────────────────────────────────────────────────────
def test_make_notebook_searches_and_links(env):
    text = say(asyncio.run(nb.make_notebook(ctx("make a notebook about mars"), {"topic": "mars"})))
    made = env.mgr.notebooks[0]
    assert made.title == "Mars" and env.searches == ["mars"]
    assert len(env.mgr.sources[made.id]) == 3 and len(env.spawned) == 3  # one ingestion task per source
    assert f"(#/notebooks?nb={made.id})" in text and "added 3 sources" in text


def test_make_notebook_uses_only_the_users_links(env):
    c = ctx("make a notebook about mars with https://nasa.gov/mars and http://example.com/a.")
    asyncio.run(nb.make_notebook(c, {"topic": "mars https://evil.example/model-made"}))
    made = env.mgr.notebooks[0]
    assert [s.storage_path for s in env.mgr.sources[made.id]] == ["https://nasa.gov/mars", "http://example.com/a"]
    assert env.searches == [] and "evil" not in made.title


def test_make_notebook_without_sources_says_so(env, monkeypatch):
    async def nothing(topic):
        return []

    monkeypatch.setattr(nb, "_discover", nothing)
    text = say(asyncio.run(nb.make_notebook(ctx("x"), {"topic": "obscure thing"})))
    assert "could not find sources" in text and "#/notebooks?nb=" in text


def test_pill_escapes_brackets():
    n = types.SimpleNamespace(id="abc", title="A [weird] title")
    assert nb.pill(n, "&make=quiz") == "[📓 A (weird) title](#/notebooks?nb=abc&make=quiz)"


# ── make_study ───────────────────────────────────────────────────────────────
def test_make_study_uses_an_existing_notebook(env):
    mine = types.SimpleNamespace(id=uuid4(), user_id=7, title="Mars Research")
    theirs = types.SimpleNamespace(id=uuid4(), user_id=8, title="Mars")
    env.mgr.notebooks += [theirs, mine]
    text = say(asyncio.run(nb.make_study(ctx("q"), {"kind": "quiz", "notebook": "mars"})))
    assert f"#/notebooks?nb={mine.id}&make=quiz" in text and env.searches == []
    assert len(env.spawned) == 1


def test_make_study_creates_a_notebook_for_a_topic(env):
    text = say(asyncio.run(nb.make_study(ctx("make me a quiz on mars"), {"kind": "flash cards", "topic": "mars"})))
    made = env.mgr.notebooks[0]
    assert "I made the notebook **Mars** with 3 sources" in text and "set of flashcards" in text
    assert f"&make=flashcards" in text and len(env.spawned) == 4  # three ingestions and the generation


def test_make_study_missing_notebook_asks(env):
    text = say(asyncio.run(nb.make_study(ctx("q"), {"kind": "quiz", "notebook": "Physics"})))
    assert "could not find a notebook called \"Physics\"" in text and env.mgr.notebooks == []


def test_make_study_unknown_kind_falls_through(env):
    assert asyncio.run(nb.make_study(ctx("q"), {"kind": "podcast", "topic": "mars"})) is None


def test_generate_waits_for_a_ready_source(monkeypatch):
    mgr = FakeManager()
    nid = uuid4()
    src = types.SimpleNamespace(status="processing")
    mgr.sources[nid] = [src]
    calls = []

    async def fake_sleep(_):
        src.status = "ready"

    async def fake_generate(notebook_id, body, request, user, manager):
        calls.append((notebook_id, body, user))

    monkeypatch.setattr(nb.asyncio, "sleep", fake_sleep)
    import onb_compat.router as onb_router

    monkeypatch.setattr(onb_router, "onb_notebook_generate", fake_generate)
    asyncio.run(nb.generate_when_ready(object(), mgr, nid, 7, "quiz", "Focus on rovers."))
    assert calls == [(str(nid), {"kind": "quiz", "prompt": "Focus on rovers."}, {"id": 7})]


def test_generate_skips_when_nothing_is_ready(monkeypatch):
    mgr = FakeManager()
    nid = uuid4()
    mgr.sources[nid] = [types.SimpleNamespace(status="error")]
    called = []
    import onb_compat.router as onb_router

    monkeypatch.setattr(onb_router, "onb_notebook_generate", lambda *a: called.append(a))
    asyncio.run(nb.generate_when_ready(object(), mgr, nid, 7, "quiz", ""))
    assert called == []
