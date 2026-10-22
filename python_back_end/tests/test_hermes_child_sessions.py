"""Agent steps as child sessions: subagent events, follow-up chips, and the parent link on a session row."""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import runs, sessions, store  # noqa: E402
from plugins.hermes_ui.ws import Connection  # noqa: E402

DSN = os.getenv("DATABASE_URL") or "postgresql://pguser:pgpassword@pgsql:5432/database"
STEP = "run1-s1"


def translate(*events):
    tr = runs._Translator("run1", "http://h")
    return [item for ev in events for item in tr.translate(ev)]


def kinds(items):
    return [k for k, _ in items]


def test_step_started_opens_a_subagent_row_with_the_plan_size():
    out = translate({"type": "plan", "steps": [{"label": "Research"}, {"label": "Write"}]},
                    {"type": "step_started", "run_id": "run1", "n": 1, "label": "Research", "engine": "openclaw",
                     "status": "running", "step_run_id": STEP})
    start = dict(out)["subagent.start"]
    assert start == {"subagent_id": STEP, "goal": "Research", "task_index": 0, "task_count": 2,
                     "status": "running", "engine": "openclaw"}
    assert "reasoning" in kinds(out)


def test_child_tool_calls_keep_the_tool_card_and_add_a_subagent_tool():
    out = translate({"type": "step_started", "n": 1, "label": "Research", "step_run_id": STEP, "run_id": "run1"},
                    {"type": "tool_call", "run_id": STEP, "tool": "web_search", "args": {"query": "rust  async"}},
                    {"type": "tool_call", "run_id": "run1", "tool": "plan", "args": {}})
    assert kinds(out).count("tool.start") == 2
    tools = [p for k, p in out if k == "subagent.tool"]
    assert tools == [{"subagent_id": STEP, "tool_name": "web_search", "tool_preview": "rust async"}]


def test_agent_end_completes_the_step_with_counts_and_a_status():
    ok = translate({"type": "step_started", "n": 2, "label": "Write", "step_run_id": "run1-s2", "run_id": "run1"},
                   {"type": "tool_call", "run_id": "run1-s2", "tool": "write_file", "args": {"path": "a.md"}},
                   {"type": "agent_end", "run_id": "run1-s2", "label": "Write", "summary": "Wrote a.md",
                    "success": True, "parent_run_id": "run1", "model": "qwen3"})
    done = dict(ok)["subagent.complete"]
    assert done["status"] == "completed" and done["summary"] == "Wrote a.md" and done["tool_count"] == 1
    assert done["model"] == "qwen3" and done["task_index"] == 1 and done["duration_seconds"] >= 0
    bad = translate({"type": "step_started", "n": 1, "label": "x", "step_run_id": STEP, "run_id": "run1"},
                    {"type": "agent_end", "run_id": STEP, "summary": "error: boom", "success": False})
    assert dict(bad)["subagent.complete"]["status"] == "failed"


def test_an_agent_end_for_an_unknown_run_is_ignored():
    assert translate({"type": "agent_end", "run_id": "other", "summary": "s"}) == []


def test_propose_next_becomes_one_capped_followups_item():
    out = translate({"type": "propose_next", "status": "waiting", "suggestions": ["a", "b", "c", "d"]},
                    {"type": "done", "summary": "ok", "suggestions": ["again"]})
    follow = [p for k, p in out if k == "followups"]
    assert len(follow) == 1 and [i["prompt"] for i in follow[0]["items"]] == ["a", "b", "c"]
    assert follow[0]["items"][0] == {"title": "a", "prompt": "a"}


def test_followups_accept_objects_skip_empty_and_stay_quiet_when_the_run_acts_on_them():
    out = translate({"type": "final_message", "content": "hi",
                     "suggestions": [{"label": "Polish", "task": "Polish the draft"}, " ", {"x": 1}]})
    assert dict(out)["followups"]["items"] == [{"title": "Polish", "prompt": "Polish the draft"}]
    assert "followups" not in kinds(translate({"type": "propose_next", "status": "running", "suggestions": ["a"]}))
    assert "followups" not in kinds(translate({"type": "propose_next", "suggestions": []}))


def open_steps(*ids):
    return [{"type": "step_started", "n": i + 1, "label": f"Step {i + 1}", "step_run_id": sid, "run_id": "run1"}
            for i, sid in enumerate(ids)]


def completes(items):
    return {p["subagent_id"]: p for k, p in items if k == "subagent.complete"}


def test_done_closes_steps_that_never_got_an_agent_end():
    out = translate(*open_steps("s1", "s2"),
                    {"type": "agent_end", "run_id": "s1", "summary": "ok", "success": True},
                    {"type": "done", "summary": "all done"})
    done = completes(out)
    assert done["s1"]["status"] == "completed" and done["s2"]["status"] == "interrupted"
    assert kinds(out).count("subagent.complete") == 2  # s1 is not closed a second time
    assert kinds(out).index("subagent.complete", kinds(out).index("subagent.complete") + 1) < kinds(out).index("text")


def test_cancelled_interrupts_open_steps_once():
    tr = runs._Translator("run1", "http://h")
    for ev in open_steps("s1", "s2"):
        tr.translate(ev)
    out = tr.translate({"type": "cancelled"})
    assert {sid: p["status"] for sid, p in completes(out).items()} == {"s1": "interrupted", "s2": "interrupted"}
    assert out[-1] == ("text", "\n\n[cancelled]") and tr.steps == {}
    assert tr.finish() == []


def test_error_flushes_open_steps_as_failed_and_leaves_the_raise_to_follow_run():
    tr = runs._Translator("run1", "http://h")
    for ev in open_steps("s1"):
        tr.translate(ev)
    out = tr.translate({"type": "error", "message": "boom"})
    assert completes(out)["s1"]["status"] == "failed"
    assert isinstance(tr.error, runs.ChatError) and str(tr.error) == "boom"


class _FakeStream:
    def __init__(self, lines, status=200):
        self.lines, self.status_code = lines, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class _FakeClient:
    lines: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, *a, **k):
        return _FakeStream(self.lines)


def follow(monkeypatch, *events):
    _FakeClient.lines = [f"data: {json.dumps(ev)}" for ev in events]
    monkeypatch.setattr(runs.httpx, "AsyncClient", _FakeClient)
    got, err = [], None

    async def go():
        nonlocal err
        try:
            async for item in runs.follow_run("tok", "run1", "http://h"):
                got.append(item)
        except runs.ChatError as exc:
            err = exc
    asyncio.run(go())
    return got, err


def test_follow_run_yields_the_failed_step_before_raising_the_run_error(monkeypatch):
    got, err = follow(monkeypatch, *open_steps("s1"), {"type": "error", "message": "boom"})
    assert str(err) == "boom" and completes(got)["s1"]["status"] == "failed"


def test_follow_run_interrupts_open_steps_when_the_stream_ends_without_a_terminal_event(monkeypatch):
    got, err = follow(monkeypatch, *open_steps("s1"), {"type": "stream_end"})
    assert err is None and completes(got)["s1"]["status"] == "interrupted"
    got, _ = follow(monkeypatch, *open_steps("s1"))  # stream just closes
    assert completes(got)["s1"]["status"] == "interrupted"


NEXT = "\n\nWorth doing next:\n- Polish the draft\n- Add tests"


def test_the_worth_doing_next_block_is_dropped_from_the_text_when_cards_were_sent():
    sugg = ["Polish the draft", "Add tests"]
    final = translate({"type": "propose_next", "status": "waiting", "suggestions": sugg},
                      {"type": "final_message", "content": "Wrote a.md." + NEXT},
                      {"type": "done", "summary": "Wrote a.md." + NEXT})
    assert [p for k, p in final if k == "text"] == ["Wrote a.md."]
    only_done = translate({"type": "propose_next", "status": "waiting", "suggestions": sugg},
                          {"type": "done", "summary": "Wrote a.md.\n\nFiles: a.md." + NEXT})
    assert [p for k, p in only_done if k == "text"] == ["Wrote a.md.\n\nFiles: a.md."]
    # the cards ride on the final_message itself
    inline = translate({"type": "final_message", "content": "Wrote a.md." + NEXT, "suggestions": sugg})
    assert dict(inline)["text"] == "Wrote a.md." and "followups" in kinds(inline)


def test_the_worth_doing_next_block_stays_when_no_cards_were_sent():
    out = translate({"type": "final_message", "content": "Wrote a.md." + NEXT})
    assert dict(out)["text"] == "Wrote a.md." + NEXT
    running = translate({"type": "propose_next", "status": "running", "suggestions": ["x"]},
                        {"type": "done", "summary": "ok" + NEXT})
    assert [p for k, p in running if k == "text"] == ["ok" + NEXT]


def test_text_that_merely_mentions_worth_doing_next_mid_reply_is_kept():
    body = "Worth doing next: nothing, it is finished.\n\nThanks."
    out = translate({"type": "final_message", "content": body, "suggestions": ["a"]})
    assert dict(out)["text"] == body


def test_complete_lists_the_files_the_step_wrote_deduped_in_order():
    ok = {"type": "tool_result", "run_id": STEP, "output": "ok", "success": True}
    out = translate(*open_steps(STEP),
                    {"type": "tool_call", "run_id": STEP, "tool": "edit_file", "args": {"path": "b.md", "content": "x"}}, ok,
                    {"type": "tool_call", "run_id": STEP, "tool": "str_replace", "args": {"path": "a.py"}}, ok,
                    {"type": "tool_call", "run_id": STEP, "tool": "apply_patch", "args": {"path": "b.md"}}, ok,
                    {"type": "tool_call", "run_id": STEP, "tool": "apply_patch", "args": {"path": "gone.txt", "delete": True}}, ok,
                    {"type": "tool_call", "run_id": STEP, "tool": "read_file", "args": {"path": "r.txt"}}, ok,
                    {"type": "tool_call", "run_id": STEP, "tool": "exec", "args": {"command": "ls"}}, ok,
                    {"type": "tool_call", "run_id": "run1", "tool": "edit_file", "args": {"path": "parent.md"}},
                    {"type": "agent_end", "run_id": STEP, "summary": "ok", "success": True,
                     "files": ["/ws/everything/else.txt", "/ws/b.md"]})
    done = completes(out)[STEP]
    assert done["files_written"] == ["b.md", "a.py"] and done["tool_count"] == 6


def test_a_denied_or_failed_edit_is_not_listed_as_written():
    out = translate(*open_steps(STEP),
                    {"type": "tool_call", "run_id": STEP, "tool": "edit_file", "args": {"path": "denied.md"}},
                    {"type": "tool_result", "run_id": STEP, "output": "DENIED: policy", "success": False},
                    {"type": "tool_call", "run_id": STEP, "tool": "edit_file", "args": {"path": "never-answered.md"}},
                    {"type": "agent_end", "run_id": STEP, "summary": "ok", "success": True})
    assert "files_written" not in completes(out)[STEP]


def test_input_tokens_are_the_billed_total_not_the_last_context_size():
    out = translate(*open_steps(STEP),
                    {"type": "agent_end", "run_id": STEP, "summary": "ok", "success": True, "prompt_tokens": 900,
                     "completion_tokens": 120, "usage_detail": {"input": 4200, "output": 120}})
    done = completes(out)[STEP]
    assert done["input_tokens"] == 4200 and done["output_tokens"] == 120


@pytest.mark.asyncio
async def test_a_dropped_stream_settles_open_steps_before_the_error(monkeypatch):
    import httpx

    class _Resp:
        status_code = 200

        async def aiter_lines(self):
            yield "data: " + json.dumps({"type": "step_started", "n": 1, "label": "x", "step_run_id": STEP, "run_id": "run1"})
            raise httpx.ReadTimeout("gone")

    class _Stream:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *exc):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, *a, **k):
            return _Stream()

    monkeypatch.setattr(runs.httpx, "AsyncClient", _Client)
    seen = []
    with pytest.raises(httpx.ReadTimeout):
        async for item in runs.follow_run("t", "run1", "http://x"):
            seen.append(item)
    assert [p["status"] for k, p in seen if k == "subagent.complete"] == ["failed"]


def test_complete_has_no_files_written_for_a_step_that_wrote_nothing_even_when_the_event_lists_files():
    out = translate(*open_steps(STEP),
                    {"type": "agent_end", "run_id": STEP, "summary": "error: x", "success": False, "files": ["/ws/a"]})
    assert "files_written" not in completes(out)[STEP]


def test_complete_takes_duration_and_token_counts_from_the_event():
    out = translate(*open_steps(STEP),
                    {"type": "agent_end", "run_id": STEP, "summary": "ok", "success": True, "duration_ms": 12345,
                     "prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020})
    done = completes(out)[STEP]
    assert done["duration_seconds"] == 12.3 and done["input_tokens"] == 900 and done["output_tokens"] == 120
    bare = completes(translate(*open_steps(STEP), {"type": "agent_end", "run_id": STEP, "summary": "ok"}))[STEP]
    assert "input_tokens" not in bare and "output_tokens" not in bare and bare["duration_seconds"] < 5


# ---- relaying to the UI --------------------------------------------------------------------------

class _RelayConn:
    _relay = Connection._relay

    def __init__(self):
        self.pool, self.events = object(), []

    async def emit(self, etype, sid=None, payload=None):
        self.events.append((etype, payload))


def test_relay_passes_subagent_events_through_and_names_the_followups_event(monkeypatch):
    conn, s = _RelayConn(), sessions.Live(id="p1", user_id=1)
    run = asyncio.run
    run(conn._relay(s, "subagent.start", {"subagent_id": "x"}, [], []))
    run(conn._relay(s, "subagent.tool", {"subagent_id": "x", "tool_name": "t"}, [], []))
    run(conn._relay(s, "followups", {"items": [{"title": "a", "prompt": "a"}]}, [], []))
    assert [e for e, _ in conn.events] == ["subagent.start", "subagent.tool", "harvis.followups"]


def test_relay_adds_the_child_session_id_on_complete_and_survives_a_failure(monkeypatch):
    conn, s = _RelayConn(), sessions.Live(id="p1", user_id=1, model="m")
    made = []

    async def spawn(pool, parent, title, goal, summary):
        made.append((parent.id, title, goal, summary))
        return sessions.Live(id="child-1", user_id=1)

    monkeypatch.setattr(sessions, "spawn_child", spawn)
    payload = {"subagent_id": "x", "goal": "Research", "summary": "found it", "status": "completed"}
    asyncio.run(conn._relay(s, "subagent.complete", payload, [], []))
    assert conn.events[-1][1]["child_session_id"] == "child-1"
    assert made == [("p1", "Research", "Research", "found it")]

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(sessions, "spawn_child", boom)
    asyncio.run(conn._relay(s, "subagent.complete", payload, [], []))
    assert conn.events[-1][0] == "subagent.complete" and "child_session_id" not in conn.events[-1][1]


# ---- the parent link -----------------------------------------------------------------------------

def test_session_info_carries_the_parent_and_none_without_one():
    row = {"id": "c1", "title": "T", "preview": "", "created": 1.0, "updated": 2.0, "message_count": 2,
           "model": "m", "pinned": False, "parent_id": "p1"}
    assert sessions.to_session_info(row)["parent_session_id"] == "p1"
    assert sessions.to_session_info({**row, "parent_id": ""})["parent_session_id"] is None
    assert sessions.to_session_info({k: v for k, v in row.items() if k != "parent_id"})["parent_session_id"] is None


def with_db(fn):
    async def main():
        import asyncpg
        try:
            pool = await asyncpg.create_pool(DSN, min_size=1, max_size=1, timeout=5)
        except Exception as exc:  # no database in this environment
            pytest.skip(f"no database: {type(exc).__name__}")
        try:
            async with pool.acquire() as conn:
                await conn.execute("CREATE TEMP TABLE owui_chats (LIKE owui_chats INCLUDING DEFAULTS)")
            return await fn(pool)
        finally:
            await pool.close()
    return asyncio.run(main())


async def stored(pool, uid, sid):
    blob = store.new_chat_blob("m")
    await store.insert_chat(pool, uid, sid, blob)


def test_set_parent_stores_the_link_and_the_summary_reads_it_back():
    async def go(pool):
        parent = sessions.Live(id="11111111-1111-4111-8111-111111111111", user_id=1, model="m")
        child = sessions.Live(id="22222222-2222-4222-8222-222222222222", user_id=1, model="m")
        await stored(pool, 1, parent.id)
        await stored(pool, 1, child.id)
        child.persisted = True
        await sessions.set_parent(pool, child, parent.id)
        info = await sessions.info_for(pool, 1, child.id)
        top = await sessions.info_for(pool, 1, parent.id)
        return child.parent_id, info["parent_session_id"], top["parent_session_id"]
    assert with_db(go) == ("11111111-1111-4111-8111-111111111111", "11111111-1111-4111-8111-111111111111", None)


def test_set_parent_refuses_another_users_chat_and_unknown_ids():
    async def go(pool):
        theirs = "33333333-3333-4333-8333-333333333333"
        await stored(pool, 2, theirs)
        child = sessions.Live(id="44444444-4444-4444-8444-444444444444", user_id=1)
        for bad in (theirs, "55555555-5555-4555-8555-555555555555", "not-a-uuid", "", child.id):
            with pytest.raises(ValueError):
                await sessions.set_parent(pool, child, bad)
        return child.parent_id
    assert with_db(go) == ""


def test_spawn_child_creates_a_seeded_session_nested_under_the_parent():
    async def go(pool):
        parent = sessions.Live(id="66666666-6666-4666-8666-666666666666", user_id=1, model="m")
        await stored(pool, 1, parent.id)
        parent.persisted = True
        child = await sessions.spawn_child(pool, parent, "Research", "Look into X", "X is Y")
        s, msgs = await sessions.open(pool, 1, child.id)
        info = await sessions.info_for(pool, 1, child.id)
        listed, _ = await sessions.list_for(pool, 1)
        return info, [(m["role"], m["content"]) for m in msgs], {r["id"]: r["parent_session_id"] for r in listed}
    info, msgs, listed = with_db(go)
    assert info["title"] == "Research" and info["parent_session_id"] == "66666666-6666-4666-8666-666666666666"
    assert msgs == [("user", "Look into X"), ("assistant", "X is Y")]
    assert listed[info["id"]] == info["parent_session_id"]


def test_a_draft_child_carries_the_link_into_its_first_row():
    async def go(pool):
        parent = sessions.Live(id="77777777-7777-4777-8777-777777777777", user_id=1, model="m")
        await stored(pool, 1, parent.id)
        draft = sessions.fork(parent, "btw")
        await sessions.set_parent(pool, draft, parent.id)
        await sessions.append(pool, draft, "user", "hi")
        return (await sessions.info_for(pool, 1, draft.id))["parent_session_id"]
    assert with_db(go) == "77777777-7777-4777-8777-777777777777"
