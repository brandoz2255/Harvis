"""Chat core of the Hermes UI facade: rewind/truncate, stopped and failed turns, plain errors,
titles, usage, slash commands, and the session RPCs that need no database."""

import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import errors, rewind, session_ops, sessions, store, titles, usage, ws_slash  # noqa: E402
from plugins.hermes_ui.ws import Connection  # noqa: E402


def _blob(*pairs):
    """A chat blob holding user/assistant messages in order; pairs are (role, text, kwargs)."""
    blob = store.new_chat_blob("m1")
    for role, text, *rest in pairs:
        parent = blob["history"]["currentId"]
        store.append_to_blob(blob, store.make_message(role, text, parent, "m1", **(rest[0] if rest else {})))
    return blob


def _three_turns():
    return _blob(("user", "one"), ("assistant", "r1"), ("user", "two"), ("assistant", "r2"),
                 ("user", "three"), ("assistant", "r3"))


# ---- store: row ids, truncation, error and stopped flags ----------------------------------------

def test_rows_are_numbered_from_one_and_carry_flags():
    blob = _blob(("user", "hi"), ("assistant", "partial", {"interrupted": True}),
                 ("user", "again"), ("assistant", "", {"error": "The model server is not responding."}))
    rows = store.linear_messages(blob)
    assert [r["row_id"] for r in rows] == [1, 2, 3, 4]
    assert rows[1]["interrupted"] is True and rows[1]["content"] == "partial"
    assert rows[3]["error"] == "The model server is not responding."
    assert "error" not in rows[0] and "interrupted" not in rows[0]


def test_a_legacy_interrupted_suffix_is_stripped_and_flagged():
    rows = store.linear_messages(_blob(("user", "hi"), ("assistant", "half an answ\n\n[interrupted]")))
    assert rows[1]["content"] == "half an answ" and rows[1]["interrupted"] is True


def test_truncate_blob_drops_the_tail_everywhere():
    blob = _three_turns()
    store.truncate_blob(blob, 2)
    rows = store.linear_messages(blob)
    assert [r["content"] for r in rows] == ["one", "r1"]
    assert len(blob["messages"]) == 2 and len(blob["history"]["messages"]) == 2
    tail = blob["history"]["messages"][blob["history"]["currentId"]]
    assert tail["childrenIds"] == []
    parent = blob["history"]["currentId"]
    store.append_to_blob(blob, store.make_message("user", "new", parent, "m1"))
    assert [r["content"] for r in store.linear_messages(blob)] == ["one", "r1", "new"]


def test_truncate_to_zero_empties_the_branch():
    blob = _three_turns()
    store.truncate_blob(blob, 0)
    assert store.linear_messages(blob) == [] and blob["history"]["currentId"] is None


# ---- rewind plan --------------------------------------------------------------------------------

def _rows():
    return store.linear_messages(_three_turns())


def test_edit_and_resend_cuts_at_the_row_and_maps_survivors():
    params = {"confirm_truncate": True, "truncate_before_row_id": 3, "rebind_survivor_row_ids": [1, 2, 3, 4, 5, 6]}
    plan = rewind.plan(_rows(), params, "two, edited")
    assert plan.cut == 2 and plan.user_row_id == 3
    assert plan.row_id_map == {"1": 1, "2": 2, "3": 3, "4": None, "5": None, "6": None}


def test_cut_by_user_ordinal_skips_failed_turns():
    msgs = store.linear_messages(_blob(("user", "a"), ("assistant", "", {"error": "boom."}),
                                       ("user", "b"), ("assistant", "ok")))
    plan = rewind.plan(msgs, {"confirm_truncate": True, "truncate_before_user_ordinal": 0}, "b2")
    assert plan.cut == 2


def test_a_stale_target_raises_the_message_the_ui_recognises():
    with pytest.raises(rewind.RewindError, match="not in session history"):
        rewind.plan(_rows(), {"confirm_truncate": True, "truncate_before_row_id": 40}, "x")
    with pytest.raises(rewind.RewindError):
        rewind.plan(_rows(), {"confirm_truncate": True, "truncate_before_row_id": 2}, "x")  # an assistant row


def test_emptying_the_session_needs_confirmation():
    with pytest.raises(rewind.RewindError, match="confirm_empty_truncate"):
        rewind.plan(_rows(), {"confirm_truncate": True, "truncate_before_row_id": 1}, "x")
    plan = rewind.plan(_rows(), {"confirm_truncate": True, "truncate_before_row_id": 1,
                                 "confirm_empty_truncate": True}, "x")
    assert plan.cut == 0


def test_a_plain_submit_appends():
    assert rewind.plan(_rows(), {}, "four").cut is None


def test_retry_after_a_failed_turn_replaces_the_pair_instead_of_duplicating():
    msgs = store.linear_messages(_blob(("user", "q1"), ("assistant", "a1"),
                                       ("user", "q2"), ("assistant", "", {"error": "Retry."})))
    assert rewind.plan(msgs, {}, "q2").cut == 2
    assert rewind.plan(msgs, {}, "something else").cut is None
    lone = store.linear_messages(_blob(("user", "q1")))
    assert rewind.plan(lone, {}, "q1").cut == 0


def test_regenerate_inherits_the_attachments_of_the_replaced_message():
    ref = {"type": "file", "id": "f1", "name": "a.txt", "content_type": "text/plain", "size": 3}
    msgs = store.linear_messages(_blob(("user", "q", {"files": [ref]}), ("assistant", "a")))
    plan = rewind.plan(msgs, {"confirm_truncate": True, "truncate_before_row_id": 1,
                              "confirm_empty_truncate": True}, "q")
    assert plan.inherit_files and plan.inherit_files[0]["id"] == "f1"


# ---- plain errors -------------------------------------------------------------------------------

def test_http_failures_become_sentences_and_keep_the_raw_body_for_the_log():
    failure = errors.from_http(503, "{'detail': 'upstream connect error'}")
    assert "not responding" in str(failure) and "upstream" not in str(failure)
    assert "upstream" in failure.raw
    assert "{" not in str(errors.from_http(404, {"detail": "model 'x' not found"}))
    assert "model 'x' not found" in str(errors.from_http(404, {"detail": "model 'x' not found"}))


@pytest.mark.parametrize("exc", [
    httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), RuntimeError("{'error': {'code': 500}}"),
    Exception("Traceback (most recent call last): boom"), ValueError(),
])
def test_friendly_never_shows_a_payload(exc):
    text = errors.friendly(exc)
    assert text.endswith((".", ")", "!", "?")) and "{" not in text and "Traceback" not in text


def test_a_short_plain_message_we_raised_ourselves_survives():
    assert errors.friendly(RuntimeError("You have used your 20 daily messages")) == \
        "You have used your 20 daily messages."


# ---- titles -------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ('"Planning a Trip to Japan"', "Planning a Trip to Japan"),
    ("Title: Fixing the **login** bug.", "Fixing the login bug"),
    ("<think>hmm</think>\nDebugging Python Imports", "Debugging Python Imports"),
    ("Sure! Here is a title:\nBaking Sourdough Bread", "Baking Sourdough Bread"),
    ("one two three four five six seven eight", "one two three four five six"),
    ("", ""),
])
def test_clean_title(raw, expected):
    assert titles.clean_title(raw) == expected


# ---- usage and compress -------------------------------------------------------------------------

def test_usage_counts_and_percentages_are_bounded():
    msgs = [{"role": "user", "content": "x" * 400}, {"role": "assistant", "content": "y" * 800}]
    stats = usage.usage_of(msgs, 1000)
    assert stats["input"] >= 100 and stats["output"] >= 200
    assert 0 <= stats["context_percent"] <= 100
    breakdown = usage.breakdown_of(msgs, "m1", 1000)
    assert breakdown["model"] == "m1"


def test_compress_keeps_the_last_two_user_turns_verbatim():
    msgs = store.linear_messages(_three_turns())
    older, kept = session_ops.split_for_compress(msgs)
    assert [m["content"] for m in kept] == ["two", "r2", "three", "r3"]
    assert [m["content"] for m in older] == ["one", "r1"]
    older, kept = session_ops.split_for_compress(msgs[:2])
    assert older == []


# ---- slash commands -----------------------------------------------------------------------------

def test_catalog_lists_every_required_command_with_a_description():
    cat = ws_slash.catalog()
    names = {pair[0].split()[0] for pair in cat["pairs"]}
    assert {"/new", "/title", "/model", "/compress", "/branch", "/usage", "/help", "/research", "/web"} <= names
    assert all(pair[1] for pair in cat["pairs"])
    assert cat["canon"]["/clear"] == "/new"
    assert set(cat["commands"]) == {c for c, *_ in ws_slash.COMMANDS}


def test_complete_slash_prefix_options_and_models():
    assert [i["text"] for i in ws_slash.complete("/mo", [])["items"]] == ["/model"]
    assert {i["text"] for i in ws_slash.complete("/c", [])["items"]} >= {"/compress", "/new"}  # /clear is /new
    assert [i["text"] for i in ws_slash.complete("/web o", [])["items"]] == ["on", "off"]
    models = ws_slash.complete("/model qw", ["qwen3:8b", "llama3"])
    assert [i["text"] for i in models["items"]] == ["qwen3:8b"] and models["replace_from"] == len("/model") + 1
    assert ws_slash.complete("hello", [])["items"] == []


class _Conn(ws_slash.SlashMethods):
    def __init__(self, live=None, msgs=None):
        self.pool, self.user_id, self.token = None, 1, "t"
        self.live, self.msgs, self.events = live or sessions.Live(id="s1", user_id=1, model="m1"), msgs or [], []

    async def _open(self, rid, params):
        return self.live, self.msgs, None

    async def emit(self, etype, sid=None, payload=None):
        self.events.append((etype, payload))

    async def _stats(self, s, msgs):
        return usage.usage_of(msgs, 1000)


@pytest.mark.asyncio
async def test_web_command_toggles_the_session_and_announces_it():
    conn = _Conn()
    out = await Connection.m_slash_exec(conn, 1, {"session_id": "s1", "command": "web on"})
    assert conn.live.web_search is True and "on" in out["result"]["output"]
    assert conn.events[-1][1]["web_search"] is True
    await Connection.m_slash_exec(conn, 2, {"session_id": "s1", "command": "web off"})
    assert conn.live.web_search is False


@pytest.mark.asyncio
async def test_help_and_unknown_commands():
    conn = _Conn()
    helped = await ws_slash.SlashMethods.m_slash_exec(conn, 1, {"session_id": "s1", "command": "help"})
    assert "/compress" in helped["result"]["output"]
    unknown = await ws_slash.SlashMethods.m_slash_exec(conn, 2, {"session_id": "s1", "command": "nope"})
    assert "error" in unknown
    dispatched = await ws_slash.SlashMethods.m_command_dispatch(conn, 3, {"session_id": "s1", "name": "usage"})
    assert dispatched["result"]["type"] == "exec"


# ---- the turn: stopped, failed, titled ----------------------------------------------------------

class _TurnConn:
    """Just enough of Connection to run _run_turn against a scripted model stream."""
    _run_turn = Connection._run_turn
    _relay = Connection._relay
    _background = Connection._background
    _generate_title = Connection._generate_title

    def __init__(self):
        self.pool, self.user_id, self.token, self.origin = None, 1, "t", ""
        self.turns, self.runs, self.tasks, self.events = {}, {}, set(), []

    async def emit(self, etype, sid=None, payload=None):
        self.events.append((etype, payload or {}))


@pytest.fixture
def turn_env(monkeypatch):
    from plugins.hermes_ui import bots, learn, providers, skill_select, turn_models

    saved = []

    async def append(pool, s, role, content, reasoning="", **kw):
        saved.append({"role": role, "content": content, **kw})
        return []

    async def none(*a, **k):
        return None

    monkeypatch.setattr(sessions, "append", append)
    monkeypatch.setattr(providers, "resolve_active_endpoint", none)
    monkeypatch.setattr(learn, "recall_message", none)
    monkeypatch.setattr(learn, "after_turn", lambda *a, **k: None)
    monkeypatch.setattr(skill_select, "skill_message", none)
    monkeypatch.setattr(bots, "get_bot", none)
    return saved, turn_models, monkeypatch


async def _run(conn, msgs):
    s = sessions.Live(id="s1", user_id=1, model="m1", running=True)
    await conn._run_turn(s, msgs)
    await asyncio.gather(*conn.tasks)
    return s


@pytest.mark.asyncio
async def test_a_failed_turn_keeps_the_user_message_and_stores_a_plain_error(turn_env):
    saved, turn_models, monkeypatch = turn_env

    async def boom(*a, **k):
        raise RuntimeError("{'error': {'message': 'ollama exploded', 'code': 500}}")
        yield  # pragma: no cover

    monkeypatch.setattr(turn_models, "stream", boom)
    conn = _TurnConn()
    s = await _run(conn, [{"role": "user", "content": "hello"}])
    assert saved[0]["role"] == "assistant" and saved[0]["error"] and "{" not in saved[0]["error"]
    done = next(p for t, p in conn.events if t == "message.complete")
    assert done["status"] == "error" and done["text"] == saved[0]["error"] and "{" not in done["text"]
    assert not s.running
    assert not any(t == "session.title" for t, _ in conn.events)


@pytest.mark.asyncio
async def test_a_stopped_reply_is_stored_clean_and_flagged(turn_env):
    saved, turn_models, monkeypatch = turn_env

    async def slow(*a, **k):
        yield "text", "half an answer"
        await asyncio.sleep(30)

    monkeypatch.setattr(turn_models, "stream", slow)
    conn = _TurnConn()
    s = sessions.Live(id="s1", user_id=1, model="m1", running=True)
    task = asyncio.create_task(conn._run_turn(s, [{"role": "user", "content": "hello"}]))
    await asyncio.sleep(0.05)
    task.cancel()
    await task
    assert saved[0]["content"] == "half an answer" and saved[0]["interrupted"] is True
    assert "[interrupted]" not in saved[0]["content"]
    done = next(p for t, p in conn.events if t == "message.complete")
    assert done["status"] == "interrupted"


@pytest.mark.asyncio
async def test_the_first_reply_triggers_an_ai_title_without_blocking_the_turn(turn_env):
    saved, turn_models, monkeypatch = turn_env
    gate = asyncio.Event()

    async def answer(*a, **k):
        yield "text", "Paris is the capital."

    async def name_session(pool, uid, token, sid, model, msgs):
        await gate.wait()
        return "Capital of France"

    monkeypatch.setattr(turn_models, "stream", answer)
    monkeypatch.setattr(titles, "name_session", name_session)
    conn = _TurnConn()
    s = sessions.Live(id="s1", user_id=1, model="m1", running=True)
    await conn._run_turn(s, [{"role": "user", "content": "capital of france?"}])
    assert any(t == "message.complete" for t, _ in conn.events)  # the turn is done before the title is
    assert not any(t == "session.title" for t, _ in conn.events)
    gate.set()
    await asyncio.gather(*conn.tasks)
    assert ("session.title", {"title": "Capital of France"}) in conn.events and s.title == "Capital of France"


@pytest.mark.asyncio
async def test_error_rows_are_not_sent_back_to_the_model(turn_env):
    saved, turn_models, monkeypatch = turn_env
    seen = []

    async def answer(pool, uid, token, turn, *a, **k):
        seen.append([m["content"] for m in turn])
        yield "text", "ok"

    monkeypatch.setattr(turn_models, "stream", answer)
    monkeypatch.setattr(titles, "name_session", lambda *a: asyncio.sleep(0))
    conn = _TurnConn()
    await _run(conn, [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "", "error": "Retry."},
                      {"role": "user", "content": "q2"}])
    assert seen == [["q1", "q2"]]


# ---- prompt.submit ------------------------------------------------------------------------------

class _SubmitConn:
    m_prompt_submit = Connection.m_prompt_submit

    def __init__(self, msgs):
        self.pool, self.user_id, self.turns, self.started = None, 1, {}, []
        self.live, self.msgs = sessions.Live(id="s1", user_id=1, model="m1", persisted=True), msgs

    async def _open(self, rid, params):
        return self.live, self.msgs, None

    async def _run_turn(self, s, msgs, voice=False):
        self.started.append(msgs)


@pytest.fixture
def submit_env(monkeypatch):
    from plugins.hermes_ui import attachments

    calls = []

    async def owned(pool, uid, ids):
        return []

    async def append(pool, s, role, content, reasoning="", files=None, truncate_at=None, **kw):
        calls.append(truncate_at)
        base = _rows() if truncate_at is None else _rows()[:truncate_at]
        return base + [{"role": role, "content": content, "row_id": len(base) + 1}]

    monkeypatch.setattr(attachments, "owned", owned)
    monkeypatch.setattr(sessions, "append", append)
    return calls


@pytest.mark.asyncio
async def test_prompt_submit_truncates_and_returns_the_survivor_map(submit_env):
    conn = _SubmitConn(_rows())
    res = await Connection.m_prompt_submit(conn, 9, {
        "session_id": "s1", "text": "two, better", "confirm_truncate": True, "truncate_before_row_id": 3,
        "rebind_survivor_row_ids": [1, 2, 3, 4]})
    result = res["result"]
    assert submit_env == [2]
    assert result["survivor_row_id_map"] == {"1": 1, "2": 2, "3": 3, "4": None}
    assert result["user_row_id"] == 3 and result["truncated"] is True
    await asyncio.sleep(0)
    assert conn.started and conn.started[0][-1]["content"] == "two, better"


@pytest.mark.asyncio
async def test_prompt_submit_stale_target_is_a_params_error_and_stores_nothing(submit_env):
    conn = _SubmitConn(_rows())
    res = await Connection.m_prompt_submit(conn, 9, {
        "session_id": "s1", "text": "x", "confirm_truncate": True, "truncate_before_row_id": 99})
    assert res["error"]["code"] == -32602 and "not in session history" in res["error"]["message"]
    assert submit_env == []


@pytest.mark.asyncio
async def test_prompt_submit_web_search_flag_sets_the_session_and_the_turn_extra(submit_env):
    from plugins.hermes_ui.ws import _turn_extra

    conn = _SubmitConn([])
    await Connection.m_prompt_submit(conn, 1, {"session_id": "s1", "text": "news today", "web_search": True})
    assert conn.live.web_search is True
    assert _turn_extra(conn.live, None)["features"] == {"web_search": True}
    conn.live.running = False
    await Connection.m_prompt_submit(conn, 2, {"session_id": "s1", "text": "again", "web_search": False})
    assert conn.live.web_search is False and "features" not in _turn_extra(conn.live, None)
    for t in list(conn.turns.values()):
        t.cancel()
