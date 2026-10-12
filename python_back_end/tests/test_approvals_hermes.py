"""Approvals in the Hermes chat: a gated tool call reaches the person's window,
their answer resumes the waiting run, and silence for the whole wait is a clear deny."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import ws_approvals  # noqa: E402
from workspace.orchestration import approval_notify, risk  # noqa: E402


class FakeConn(ws_approvals.ApprovalMethods):
    def __init__(self, user_id=7, runs=None):
        self.user_id, self.pool, self.open = user_id, None, True
        self.runs = runs if runs is not None else {"sess-1": "run-1"}
        self.events = []

    async def emit(self, etype, sid=None, payload=None):
        self.events.append((etype, sid, payload))


@pytest.fixture(autouse=True)
def clean():
    ws_approvals._CONNECTIONS.clear()
    ws_approvals._PENDING.clear()
    risk._PENDING_ACTIONS.clear()
    yield
    ws_approvals._CONNECTIONS.clear()
    ws_approvals._PENDING.clear()
    risk._PENDING_ACTIONS.clear()


@pytest.fixture
def session_log(monkeypatch):
    added = []

    async def add(pool, session_id, tool, args):
        added.append((session_id, tool, args))
    monkeypatch.setattr(risk, "add_session_approval", add)
    return added


def run(coro):
    return asyncio.run(coro)


def _gate(conn, action_id="run-1-1-1", tool="exec", args=None):
    """What the runner does: register, announce, then wait for the outcome."""
    args = args if args is not None else {"command": "rm -rf build"}
    risk.register_pending(action_id, {"tool": tool, "args": args, "session_id": "sess-1"})
    return action_id, args


def test_request_reaches_the_chat_following_the_run():
    conn = FakeConn()
    ws_approvals.register(conn)

    async def go():
        aid, args = _gate(conn)
        return await approval_notify.announce(7, ("run-1", None), aid, "exec", args, "high",
                                              "deletes files", session_scoped=True)
    assert run(go()) is True
    etype, sid, payload = conn.events[0]
    assert (etype, sid) == ("approval.request", "sess-1")
    assert payload["request_id"] == "run-1-1-1"
    assert payload["command"] == "rm -rf build"
    assert payload["choices"] == ["once", "session", "deny"] and payload["allow_permanent"] is False
    assert "deletes files" in payload["description"]


def test_no_session_choice_when_the_run_has_no_session():
    conn = FakeConn()
    ws_approvals.register(conn)
    run(approval_notify.announce(7, ("run-1", None), "a1", "exec", {"command": "ls"}, "high", "", session_scoped=False))
    assert conn.events[0][2]["choices"] == ["once", "deny"]


def test_request_goes_only_to_the_owner_and_the_right_run():
    other_user, other_run = FakeConn(user_id=8), FakeConn(runs={"s": "run-9"})  # other_user follows run-1 too
    ws_approvals.register(other_user)
    ws_approvals.register(other_run)
    assert run(ws_approvals.push_request(7, ["run-1"], "a1", "exec", {}, "high", "", session_scoped=False)) is False
    assert other_user.events == [] and other_run.events == []


def test_a_subagent_run_reaches_the_parents_chat():
    conn = FakeConn()
    ws_approvals.register(conn)
    assert run(approval_notify.announce(7, ("child-1", "run-1"), "a1", "exec", {"command": "x"}, "high", "",
                                        session_scoped=False)) is True


def test_closed_connection_is_not_a_target():
    conn = FakeConn()
    ws_approvals.register(conn)
    conn.open = False
    assert run(ws_approvals.push_request(7, ["run-1"], "a1", "exec", {}, "high", "", session_scoped=False)) is False
    ws_approvals.unregister(conn)
    assert ws_approvals._CONNECTIONS == {}


def test_pending_lists_only_this_users_requests():
    conn, other = FakeConn(), FakeConn(user_id=8, runs={"s8": "run-8"})
    ws_approvals.register(conn)
    ws_approvals.register(other)
    run(ws_approvals.push_request(7, ["run-1"], "a1", "exec", {"command": "ls"}, "high", "", session_scoped=False))
    run(ws_approvals.push_request(8, ["run-8"], "a8", "exec", {"command": "pwd"}, "high", "", session_scoped=False))
    got = run(conn.m_approval_pending(1, {}))["result"]["approvals"]
    assert [a["request_id"] for a in got] == ["a1"]
    assert run(conn.m_approval_pending(1, {"session_id": "nope"}))["result"]["approvals"] == []


def test_approve_once_resumes_the_waiting_run(session_log):
    conn = FakeConn()
    ws_approvals.register(conn)

    async def go():
        aid, args = _gate(conn)
        await approval_notify.announce(7, ("run-1", None), aid, "exec", args, "high", "", session_scoped=True)
        waiter = asyncio.ensure_future(risk.await_action_outcome(aid, timeout=5))
        await asyncio.sleep(0)
        reply = await conn.m_approval_respond(3, {"choice": "once", "request_id": aid, "session_id": "sess-1"})
        return reply, await waiter
    reply, outcome = run(go())
    assert reply["result"] == {"resolved": True, "approved": True, "scope": "once"}
    assert outcome == (True, False)
    assert session_log == []


def test_approve_for_session_records_the_pattern(session_log):
    conn = FakeConn()
    ws_approvals.register(conn)

    async def go():
        aid, args = _gate(conn)
        await approval_notify.announce(7, ("run-1", None), aid, "exec", args, "high", "", session_scoped=True)
        waiter = asyncio.ensure_future(risk.await_action_outcome(aid, timeout=5))
        await asyncio.sleep(0)
        await conn.m_approval_respond(3, {"choice": "session", "request_id": aid})
        return await waiter
    assert run(go()) == (True, False)
    assert session_log == [("sess-1", "exec", {"command": "rm -rf build"})]


def test_deny_stops_the_run_and_is_not_a_timeout():
    conn = FakeConn()
    ws_approvals.register(conn)

    async def go():
        aid, args = _gate(conn)
        await approval_notify.announce(7, ("run-1", None), aid, "exec", args, "high", "", session_scoped=False)
        waiter = asyncio.ensure_future(risk.await_action_outcome(aid, timeout=5))
        await asyncio.sleep(0)
        await conn.m_approval_respond(3, {"choice": "deny", "request_id": aid})
        return await waiter
    assert run(go()) == (False, False)


def test_response_without_an_id_answers_the_oldest_request_in_the_session(session_log):
    conn = FakeConn()
    ws_approvals.register(conn)

    async def go():
        for aid in ("a1", "a2"):
            risk.register_pending(aid, {"tool": "exec", "args": {}, "session_id": "sess-1"})
            await ws_approvals.push_request(7, ["run-1"], aid, "exec", {}, "high", "", session_scoped=False)
            await asyncio.sleep(0.001)
        reply = await conn.m_approval_respond(3, {"choice": "once", "session_id": "sess-1"})
        return reply, risk._PENDING_ACTIONS["a1"]["event"].is_set(), risk._PENDING_ACTIONS["a2"]["event"].is_set()
    reply, first, second = run(go())
    assert reply["result"]["resolved"] is True and first and not second


def test_another_user_cannot_answer_my_request():
    mine, theirs = FakeConn(), FakeConn(user_id=8, runs={})
    ws_approvals.register(mine)

    async def go():
        aid, args = _gate(mine)
        await approval_notify.announce(7, ("run-1", None), aid, "exec", args, "high", "", session_scoped=False)
        reply = await theirs.m_approval_respond(3, {"choice": "once", "request_id": aid})
        return reply, risk._PENDING_ACTIONS[aid]["event"].is_set()
    reply, resolved = run(go())
    assert reply["result"] == {"resolved": False} and resolved is False


def test_stale_response_is_a_quiet_no_op():
    conn = FakeConn()
    assert run(conn.m_approval_respond(1, {"choice": "once", "request_id": "gone"}))["result"] == {"resolved": False}


def test_bad_choice_is_rejected():
    conn = FakeConn()
    assert run(conn.m_approval_respond(1, {"choice": "maybe"}))["error"]["code"] == ws_approvals.ERR_PARAMS


def test_silence_is_a_timed_out_deny_and_the_window_is_told(monkeypatch):
    monkeypatch.setenv("HARVIS_APPROVAL_TIMEOUT_S", "0.05")
    conn = FakeConn()
    ws_approvals.register(conn)

    async def go():
        aid, args = _gate(conn)
        await approval_notify.announce(7, ("run-1", None), aid, "exec", args, "high", "", session_scoped=False)
        approved, timed_out = await risk.await_action_outcome(aid)
        await approval_notify.withdraw(7, aid, approved, timed_out=timed_out)
        return approved, timed_out, aid
    approved, timed_out, aid = run(go())
    assert (approved, timed_out) == (False, True)
    assert conn.events[-1] == ("approval.resolved", "sess-1",
                               {"request_id": aid, "approved": False, "timed_out": True})
    assert ws_approvals.is_pending(aid) is False
    # a click that arrives after the timeout finds nothing to resolve
    assert run(conn.m_approval_respond(1, {"choice": "once", "request_id": aid}))["result"] == {"resolved": False}


def test_default_wait_is_five_minutes_and_the_notice_says_so(monkeypatch):
    monkeypatch.delenv("HARVIS_APPROVAL_TIMEOUT_S", raising=False)
    assert risk.approval_timeout_s() == 300.0
    text = approval_notify.TIMEOUT_NOTICE.format(minutes=5, tool="exec")
    assert "nobody answered" in text and "5 minutes" in text and "'exec' was not run" in text


def test_notify_failure_never_breaks_the_run(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("socket gone")
    monkeypatch.setattr(ws_approvals, "push_request", boom)
    monkeypatch.setattr(ws_approvals, "push_resolved", boom)
    assert run(approval_notify.announce(7, ("run-1", None), "a1", "exec", {}, "high", "", session_scoped=False)) is False
    run(approval_notify.withdraw(7, "a1", False))


def test_delivers_for_run():
    conn = FakeConn()
    ws_approvals.register(conn)
    assert ws_approvals.delivers_for_run("run-1") is True
    assert ws_approvals.delivers_for_run("run-2") is False
    assert ws_approvals.delivers_for_run("run-1", user_id=8) is False
