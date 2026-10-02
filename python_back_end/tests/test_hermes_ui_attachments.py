"""Browser uploads attached to a Hermes prompt: ownership, storage, and the
completion body (plugins/hermes_ui/attachments.py + ws.m_prompt_submit)."""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import attachments, bots, chat, learn, providers, sessions, store  # noqa: E402
from plugins.hermes_ui.ws import ERR_PARAMS, Connection  # noqa: E402

ROWS = {
    "f1": {"id": "f1", "filename": "sales.csv", "content_type": "text/csv", "size": 120},
    "f2": {"id": "f2", "filename": "cat.png", "content_type": "image/png", "size": 2048},
}


class _Conn:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    async def fetch(self, sql, user_id, ids):
        self.queries.append((sql, user_id, list(ids)))
        return [r for fid, r in self.rows.items() if fid in ids and r.get("user_id", 1) == user_id]


class _Pool:
    def __init__(self, rows=ROWS):
        self.conn = _Conn(rows)

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


# ─── requested_ids / owned ───────────────────────────────────────────────────

def test_requested_ids_accepts_objects_and_bare_strings_once_each():
    assert attachments.requested_ids(None) == []
    assert attachments.requested_ids([{"id": "a"}, "b", {"id": " a "}]) == ["a", "b"]


@pytest.mark.parametrize("raw", ["f1", [{"name": "x"}], [""], [{"id": 3}]])
def test_requested_ids_rejects_malformed_input(raw):
    with pytest.raises(attachments.AttachmentError):
        attachments.requested_ids(raw)


def test_requested_ids_caps_the_count():
    with pytest.raises(attachments.AttachmentError, match="at most 20"):
        attachments.requested_ids([f"f{i}" for i in range(attachments.MAX_FILES_PER_MESSAGE + 1)])


@pytest.mark.asyncio
async def test_owned_returns_references_in_request_order():
    pool = _Pool()
    refs = await attachments.owned(pool, 1, ["f2", "f1"])
    assert refs == [
        {"type": "file", "id": "f2", "name": "cat.png", "content_type": "image/png", "size": 2048},
        {"type": "file", "id": "f1", "name": "sales.csv", "content_type": "text/csv", "size": 120},
    ]
    assert pool.conn.queries[0][1] == 1 and "user_id = $1" in pool.conn.queries[0][0]


@pytest.mark.asyncio
async def test_owned_refuses_an_id_that_is_not_this_users():
    with pytest.raises(attachments.AttachmentError, match="not yours"):
        await attachments.owned(_Pool(), 2, ["f1"])
    with pytest.raises(attachments.AttachmentError):
        await attachments.owned(_Pool(), 1, ["f1", "ghost"])
    assert await attachments.owned(_Pool(), 1, []) == []


# ─── prompt.submit ───────────────────────────────────────────────────────────

class _Ws:
    """A Connection with the session already open and the turn stubbed out."""

    def __init__(self, live):
        self.pool, self.user_id, self.live, self.turns, self.ran = _Pool(), 1, live, {}, []

    async def _open(self, rid, params):
        return self.live, [], None

    async def _run_turn(self, s, msgs, voice=False):
        self.ran.append(msgs)
        s.running = False


def _live():
    return sessions.Live(id="s1", user_id=1, model="m")


@pytest.fixture
def appended(monkeypatch):
    calls = []

    async def append(pool, s, role, content, reasoning="", files=None):
        calls.append({"role": role, "content": content, "files": files})
        return [{"role": role, "content": content, "attachments": files or []}]

    monkeypatch.setattr(sessions, "append", append)
    return calls


@pytest.mark.asyncio
async def test_submit_stores_the_owned_references_on_the_user_message(appended):
    ws = _Ws(_live())
    res = await Connection.m_prompt_submit(ws, 1, {"session_id": "s1", "text": "summarise", "files": [{"id": "f1"}]})
    await asyncio.gather(*ws.turns.values())

    assert res["result"]["ok"] is True and res["result"]["user_turn_count"] == 1
    assert appended == [{"role": "user", "content": "summarise", "files": [
        {"type": "file", "id": "f1", "name": "sales.csv", "content_type": "text/csv", "size": 120}]}]
    assert ws.ran and ws.ran[0][0]["attachments"][0]["id"] == "f1"


@pytest.mark.asyncio
async def test_submit_rejects_a_foreign_file_id_and_stores_nothing(appended):
    ws = _Ws(_live())
    ws.user_id = 2
    res = await Connection.m_prompt_submit(ws, 2, {"session_id": "s1", "text": "hi", "files": [{"id": "f1"}]})

    assert res["error"]["code"] == ERR_PARAMS and "not yours" in res["error"]["message"]
    assert appended == [] and ws.turns == {} and ws.live.running is False


@pytest.mark.asyncio
async def test_submit_rejects_a_malformed_files_param(appended):
    res = await Connection.m_prompt_submit(_Ws(_live()), 3, {"session_id": "s1", "text": "hi", "files": "f1"})
    assert res["error"]["code"] == ERR_PARAMS and appended == []


@pytest.mark.asyncio
async def test_submit_allows_empty_text_when_a_file_is_attached(appended):
    ws = _Ws(_live())
    res = await Connection.m_prompt_submit(ws, 4, {"session_id": "s1", "text": "", "files": ["f2"]})
    await asyncio.gather(*ws.turns.values())

    assert "result" in res and appended[0]["content"] == "" and appended[0]["files"][0]["id"] == "f2"


@pytest.mark.asyncio
async def test_submit_still_rejects_an_empty_prompt_without_files(appended):
    res = await Connection.m_prompt_submit(_Ws(_live()), 5, {"session_id": "s1", "text": "  "})
    assert res["error"] == {"code": ERR_PARAMS, "message": "empty prompt"} and appended == []


@pytest.mark.asyncio
async def test_submit_without_files_appends_an_empty_reference_list(appended):
    ws = _Ws(_live())
    await Connection.m_prompt_submit(ws, 6, {"session_id": "s1", "text": "plain"})
    await asyncio.gather(*ws.turns.values())
    assert appended[0]["files"] == []


# ─── history ─────────────────────────────────────────────────────────────────

def test_history_rows_carry_the_references_and_old_rows_do_not():
    ref = attachments.reference(ROWS["f1"])
    blob = store.new_chat_blob("m")
    store.append_to_blob(blob, store.make_message("user", "first", None, "m"))
    first = blob["history"]["currentId"]
    store.append_to_blob(blob, store.make_message("assistant", "ok", first, "m"))
    second = blob["history"]["currentId"]
    store.append_to_blob(blob, store.make_message("user", "", second, "m", files=[ref]))

    rows = store.linear_messages(blob)
    assert "attachments" not in rows[0] and "attachments" not in rows[1]
    assert rows[2]["attachments"] == [ref]
    assert attachments.turn_files(rows) == [{"type": "file", "id": "f1", "name": "sales.csv"}]
    assert attachments.latest_turn_has_files(rows) is True


def test_turn_files_keeps_every_upload_once_oldest_first():
    msgs = [
        {"role": "user", "content": "a", "attachments": [{"id": "f1", "name": "sales.csv"}]},
        {"role": "assistant", "content": "b", "attachments": [{"id": "nope"}]},
        {"role": "user", "content": "c", "attachments": [{"id": "f2", "name": "cat.png"}, {"id": "f1"}]},
        {"role": "user", "content": "d"},
    ]
    assert attachments.turn_files(msgs) == [{"type": "file", "id": "f1", "name": "sales.csv"},
                                            {"type": "file", "id": "f2", "name": "cat.png"}]
    assert attachments.latest_turn_has_files(msgs) is False
    assert attachments.turn_files([]) == []


# ─── the completion body ─────────────────────────────────────────────────────

def _stub_turn(monkeypatch, calls):
    async def endpoint(pool, uid):
        return None

    async def section(pool, uid):
        return {"chat_mode": "auto"}

    async def recall(pool, uid, q):
        return None

    async def thinking():
        return frozenset()

    async def append(pool, s, role, content, reasoning="", files=None):
        return []

    async def stream_turn(token, turn, model, ep, mode, effort, origin, extra=None):
        calls.update(turn=turn, extra=extra)
        yield "text", "ok"

    monkeypatch.setattr(providers, "resolve_active_endpoint", endpoint)
    monkeypatch.setattr(store, "get_section", section)
    monkeypatch.setattr(learn, "recall_message", recall)
    monkeypatch.setattr(learn, "after_turn", lambda *a, **k: None)
    monkeypatch.setattr(sessions, "append", append)
    monkeypatch.setattr("plugins.hermes_ui.ws.thinking_models", thinking)
    monkeypatch.setattr(chat, "stream_turn", stream_turn)


class _TurnConn:
    pool, user_id, token, origin = "pool", 1, "tok", "http://o"
    turns, runs = {}, {}

    async def emit(self, kind, sid, payload):
        pass

    _relay = Connection._relay


@pytest.mark.asyncio
async def test_run_turn_puts_the_chats_files_in_the_body(monkeypatch):
    calls = {}
    _stub_turn(monkeypatch, calls)
    live = sessions.Live(id="s1", user_id=1, model="gemma4:e2b", running=True)
    msgs = [{"role": "user", "content": "what is in the sheet?",
             "attachments": [attachments.reference(ROWS["f1"])]}]
    await Connection._run_turn(_TurnConn(), live, msgs)

    assert calls["extra"]["files"] == [{"type": "file", "id": "f1", "name": "sales.csv"}]
    assert calls["extra"]["harvis_sandbox_session"] == "s1"
    # The transcript the model sees is text only; the ids travel in `files`.
    assert calls["turn"][-1]["content"] == "what is in the sheet?"


@pytest.mark.asyncio
async def test_run_turn_without_files_adds_no_files_key(monkeypatch):
    calls = {}
    _stub_turn(monkeypatch, calls)
    live = sessions.Live(id="s1", user_id=1, model="gemma4:e2b", running=True)
    await Connection._run_turn(_TurnConn(), live, [{"role": "user", "content": "hello"}])
    assert "files" not in calls["extra"]


# ─── review fixes: limits, custom endpoints, upload names ───────────────────

def test_requested_ids_stops_early_on_a_huge_list():
    import time
    t0 = time.monotonic()
    with pytest.raises(attachments.AttachmentError):
        attachments.requested_ids([f"f{i}" for i in range(60000)])
    assert time.monotonic() - t0 < 0.5
    # Repeats of one id are not counted against the cap.
    assert attachments.requested_ids(["a"] * 500) == ["a"]


def test_turn_files_keeps_only_the_newest_uploads():
    msgs = [{"role": "user", "content": str(i), "attachments": [{"id": f"f{i}", "name": f"{i}.csv"}]}
            for i in range(attachments.MAX_FILES_PER_TURN + 5)]
    # Re-attaching an old file makes it new again.
    msgs.append({"role": "user", "content": "again", "attachments": [{"id": "f0"}]})
    ids = [f["id"] for f in attachments.turn_files(msgs)]
    assert len(ids) == attachments.MAX_FILES_PER_TURN
    assert ids[0] == "f0" and ids[-1] == f"f{attachments.MAX_FILES_PER_TURN + 4}"
    assert attachments.turn_files(msgs)[0]["name"] == "0.csv"


@pytest.mark.asyncio
async def test_custom_endpoint_turn_says_the_files_are_not_sent(monkeypatch):
    calls, relayed = {}, []
    _stub_turn(monkeypatch, calls)

    async def endpoint(pool, uid):
        return {"base_url": "https://example.test/v1", "model": "m", "id": "ep"}

    monkeypatch.setattr(providers, "resolve_active_endpoint", endpoint)

    class _C(_TurnConn):
        async def _relay(self, s, kind, delta, parts, thoughts):
            relayed.append((kind, delta))
            parts.append(delta) if kind == "text" else None

    live = sessions.Live(id="s1", user_id=1, model="gemma4:e2b", running=True)
    msgs = [{"role": "user", "content": "sum it", "attachments": [attachments.reference(ROWS["f1"])]}]
    await Connection._run_turn(_C(), live, msgs)
    assert ("text", attachments.CUSTOM_ENDPOINT_NOTE) in relayed


def test_upload_names_are_safe_on_disk_and_in_the_db():
    from owui_compat import upload_store as u
    assert u.disk_suffix("report.CSV") == ".csv"
    assert u.disk_suffix("x." + "a" * 300) == ""
    assert u.disk_suffix("x.c\x00sv") == ""
    assert u.disk_suffix("../../etc/passwd") == ""
    assert u.disk_suffix(None) == ""
    assert u.display_name("a\x00b.csv", "fid") == "ab.csv"
    assert u.display_name("\x00", "fid") == "fid"
    assert len(u.display_name("n" * 1000, "fid")) == 255
