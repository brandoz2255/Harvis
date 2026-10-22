"""/btw side questions and /branch nesting: the child session, its parent link, and an untouched main chat."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import sessions, ws_slash  # noqa: E402
from plugins.hermes_ui.ws import Connection  # noqa: E402

MSGS = [{"role": "user", "content": "what is k3s?"}, {"role": "assistant", "content": "A light Kubernetes."},
        {"role": "assistant", "content": "boom", "error": True}]


class _Conn(ws_slash.SlashMethods):
    _branch = Connection._branch
    _btw = Connection._btw
    _link_parent = Connection._link_parent

    def __init__(self, msgs=None):
        self.pool, self.user_id, self.token = None, 1, "t"
        self.live, self.msgs = sessions.Live(id="main", user_id=1, model="m1", title="Cluster talk"), list(msgs or [])
        self.seeded, self.parents = {}, {}

    async def _open(self, rid, params):
        return self.live, self.msgs, None

    async def emit(self, etype, sid=None, payload=None):
        pass


@pytest.fixture
def conn(monkeypatch):
    c = _Conn(MSGS)

    async def seed(pool, s, rows):
        c.seeded[s.id] = list(rows)
        return list(rows)

    async def set_parent(pool, s, parent_id):
        c.parents[s.id] = parent_id

    monkeypatch.setattr(sessions, "seed", seed)
    monkeypatch.setattr(sessions, "set_parent", set_parent, raising=False)
    return c


def test_btw_is_registered_aliased_and_in_help():
    names = {c for c, *_ in ws_slash.COMMANDS}
    assert "/btw" in names and ws_slash.canonical("aside") == "/btw"
    assert "/btw" in ws_slash.SECTIONS[0][1]
    cat = ws_slash.catalog()
    assert ["/btw <question>", "Ask a side question in its own tab"] in cat["pairs"]
    assert cat["canon"]["/aside"] == "/btw" and cat["commands"]["/btw"]["argument_mode"] == "text"
    assert "/btw - Ask a side question in its own tab" in ws_slash.help_text()
    assert "/btw" in [i["text"] for i in ws_slash.complete("/as", [])["items"]]


@pytest.mark.asyncio
async def test_btw_without_a_question_shows_usage_and_creates_nothing(conn):
    out = await conn.m_slash_exec(1, {"session_id": "main", "command": "btw"})
    assert out["result"] == {"output": "Usage: /btw <question>"}
    assert conn.seeded == {} and conn.parents == {}


@pytest.mark.asyncio
async def test_btw_opens_a_linked_child_and_leaves_the_main_chat_alone(conn):
    out = await conn.m_slash_exec(1, {"session_id": "main", "command": "aside why does it use sqlite?"})
    res = out["result"]
    child_id = res["session_id"]
    assert res == {"type": "btw", "session_id": child_id, "stored_session_id": child_id,
                   "parent_session_id": "main", "title": "btw: why does it use sqlite?",
                   "message": "why does it use sqlite?", "output": "Side question opened in its own tab."}
    assert child_id != "main" and conn.parents == {child_id: "main"}
    assert [m["content"] for m in conn.seeded[child_id]] == ["what is k3s?", "A light Kubernetes."]  # no error row
    assert conn.msgs == MSGS and conn.live.title == "Cluster talk"


@pytest.mark.asyncio
async def test_btw_title_is_trimmed_and_an_empty_chat_is_allowed(conn):
    conn.msgs = []
    res = (await conn.m_slash_exec(1, {"session_id": "main", "command": "btw " + "word " * 30}))["result"]
    assert res["title"].startswith("btw: word word") and len(res["title"]) <= len("btw: ") + 40
    assert conn.seeded[res["session_id"]] == []


@pytest.mark.asyncio
async def test_btw_still_works_when_set_parent_is_missing(conn, monkeypatch):
    monkeypatch.delattr(sessions, "set_parent")
    res = (await conn.m_slash_exec(1, {"session_id": "main", "command": "btw hello"}))["result"]
    assert res["type"] == "btw" and conn.parents == {}


@pytest.mark.asyncio
async def test_branch_links_the_child_to_its_parent(conn):
    out = await conn.m_slash_exec(1, {"session_id": "main", "command": "branch"})
    (child_id,) = conn.seeded
    assert conn.parents == {child_id: "main"} and "Cluster talk (branch)" in out["result"]["output"]
    child, rows = await conn._branch(conn.live, conn.msgs, 1)
    assert [r["content"] for r in rows] == ["what is k3s?"] and conn.parents[child.id] == "main"


async def _create(conn, monkeypatch, params, refuse=False):
    from plugins.hermes_ui import bots, session_ops

    async def get_bot(pool, user_id, bot_id):
        return None

    async def model_error(pool, user_id, token, model):
        return None

    async def create(pool, user_id, model="", bot=None):
        return sessions.Live(id="child", user_id=user_id, model=model)

    async def set_parent(pool, s, parent_id):
        if refuse:
            raise ValueError("parent session not found")
        conn.parents[s.id] = parent_id

    monkeypatch.setattr(bots, "get_bot", get_bot)
    monkeypatch.setattr(session_ops, "model_error", model_error)
    monkeypatch.setattr(sessions, "create", create)
    monkeypatch.setattr(sessions, "set_parent", set_parent, raising=False)
    conn._announce = lambda s: {}
    return await Connection.m_session_create(conn, 1, params)


@pytest.mark.asyncio
async def test_session_create_links_a_right_click_branch_to_its_source(conn, monkeypatch):
    out = await _create(conn, monkeypatch, {"parent_session_id": "main", "messages": MSGS[:2]})
    assert out["result"]["session_id"] == "child" and conn.parents == {"child": "main"} and conn.seeded["child"]


@pytest.mark.asyncio
async def test_session_create_with_a_foreign_parent_still_creates_a_top_level_chat(conn, monkeypatch):
    out = await _create(conn, monkeypatch, {"parent_session_id": "not-mine"}, refuse=True)
    assert out["result"]["session_id"] == "child" and conn.parents == {}
