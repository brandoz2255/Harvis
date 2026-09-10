"""The teammate's computer: who may see a screen, and how the page finds it.

Pure-function coverage. The runner calls are exercised live (the pane against
a real headed session); what is checked here is the part that decides whose
screen is whose, because a wrong answer there shows one user another's
logged-in browser.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from plugins.agents import computer as c  # noqa: E402

TOKEN = "81b297c14bb508a3ad8b83df2ac52956"


def _rec(sid="s1", uid=7, agent_id="a1b2c3d4-0000", token=TOKEN):
    return {
        "session_id": sid, "user_id": uid, "agent_id": agent_id,
        "profile": c.profile_key_for(uid, agent_id), "token": token,
        "display": ":100", "width": 1280, "height": 800,
        "taken_over": False, "created_at": 1,
    }


@pytest.fixture(autouse=True)
def _clean_registry():
    c._sessions.clear()
    yield
    c._sessions.clear()


# ── profile keys ─────────────────────────────────────────────────────────────

def test_profile_key_is_per_user_and_per_teammate():
    assert c.profile_key_for(7, "a1b2c3d4-0000") == "u7-a1b2c3d4"
    assert c.profile_key_for(8, "a1b2c3d4-0000") != c.profile_key_for(7, "a1b2c3d4-0000")
    assert c.profile_key_for(7, "ffffffff-1") != c.profile_key_for(7, "a1b2c3d4-0000")


def test_profile_key_without_a_teammate_is_the_users_default():
    assert c.profile_key_for(7, None) == "u7-default"
    assert c.profile_key_for(7, "") == "u7-default"


def test_profile_key_only_ever_contains_runner_safe_characters():
    # The runner refuses anything outside [a-z0-9-_]; nothing a caller sends
    # may reach it as a path.
    key = c.profile_key_for(7, "../../etc/PASSWD")
    assert key == "u7-etcpassw"
    assert set(key) <= set("abcdefghijklmnopqrstuvwxyz0123456789-_")


# ── the path the page uses ───────────────────────────────────────────────────

def test_vnc_path_carries_the_token_and_nothing_about_the_runner():
    path = c.vnc_path(TOKEN)
    assert path == f"agents/vnc/websockify?token={TOKEN}"
    assert "6080" not in path and "browser-runner" not in path


def test_vnc_path_refuses_anything_that_is_not_a_runner_token():
    for bad in ("", "abc", "x" * 32, TOKEN + "&path=..", TOKEN.upper(), None):
        with pytest.raises(ValueError):
            c.vnc_path(bad)


# ── ownership ────────────────────────────────────────────────────────────────

def test_a_session_is_only_visible_to_the_user_who_started_it():
    c._remember(_rec(sid="mine", uid=7))
    assert c.owned(7, "mine") is not None
    assert c.owned(8, "mine") is None       # someone else: as if it did not exist
    assert c.owned(7, "nope") is None


def test_listing_is_scoped_to_the_caller():
    c._remember(_rec(sid="a", uid=7))
    c._remember(_rec(sid="b", uid=8, agent_id="other"))
    assert [r["session_id"] for r in c._mine(7)] == ["a"]
    assert [r["session_id"] for r in c._mine(8)] == ["b"]


def test_public_view_hides_the_user_id_and_raw_runner_fields():
    view = c.public_view(_rec())
    assert "user_id" not in view and "token" not in view
    assert view["vncPath"].endswith(TOKEN)
    assert view["sessionId"] == "s1" and view["takenOver"] is False


# ── route order ──────────────────────────────────────────────────────────────

def test_computer_paths_are_not_swallowed_by_the_agent_id_routes():
    # FastAPI flattens included routers lazily, so the only honest check is a
    # request: "/computer/sessions" must reach the computer handler (an empty
    # list for this user), not agents_get with agent_id="computer" (which
    # would 503 here for want of a pool).
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_optimized import get_current_user_optimized
    from plugins.agents import routes

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user_optimized] = lambda: {"id": 7}
    client = TestClient(app)

    r = client.get("/api/agents/computer/sessions")
    assert r.status_code == 200, r.text
    assert r.json() == {"items": []}
    assert "/api/agents/computer/sessions/{session_id}/takeover" in app.openapi()["paths"]


def test_a_strangers_session_id_is_a_404_not_a_403():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_optimized import get_current_user_optimized
    from plugins.agents import routes

    c._remember(_rec(sid="theirs", uid=8))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user_optimized] = lambda: {"id": 7}
    client = TestClient(app)
    for method, path in (
        ("GET", "/api/agents/computer/sessions/theirs"),
        ("DELETE", "/api/agents/computer/sessions/theirs"),
        ("POST", "/api/agents/computer/sessions/theirs/takeover"),
    ):
        r = client.request(method, path, json={"taken": True})
        assert r.status_code == 404, (method, r.status_code, r.text)


# ── the agent's side: verbs, snapshots, hard limits ──────────────────────────

import asyncio  # noqa: E402


def test_every_computer_tool_maps_to_a_runner_verb_and_nothing_else_does():
    from workspace.orchestration.tools import COMPUTER_TOOLS
    for name in COMPUTER_TOOLS:
        assert c.verb_of(name), name
    assert c.verb_of("read_file") is None
    assert c.verb_of("") is None


def test_computer_tools_are_on_the_wire_in_lane_5():
    from workspace.orchestration.tools import COMPUTER_TOOLS, lane_for_tool, wire_tool_names
    from owui_compat.workspace_method import LANE_EXTERNAL_SERVICES
    assert COMPUTER_TOOLS <= wire_tool_names()
    for name in COMPUTER_TOOLS:
        assert lane_for_tool(name) == LANE_EXTERNAL_SERVICES, name


def test_snapshot_text_lists_controls_in_ref_order_then_trims_the_text():
    snap = {
        "title": "Cats", "url": "https://duckduckgo.com/?q=cats",
        "refs": {
            "ref_10": {"role": "link", "name": "Cat pictures", "href": "https://x/cats"},
            "ref_2": {"role": "textbox", "name": "q", "type": "search"},
        },
        "text": "x" * 20000,
    }
    out = c.snapshot_text(snap)
    assert out.startswith("Page: Cats\nURL: https://duckduckgo.com/?q=cats\nControls:\n")
    assert out.index("ref_2 [textbox]") < out.index("ref_10 [link]")
    assert '"Cat pictures" → https://x/cats' in out
    assert "(search)" in out
    assert len(out) <= c.SNAPSHOT_MAX_CHARS + 1
    assert out.endswith("…")


def test_hard_limit_is_judged_by_what_the_cached_ref_actually_is():
    rec = _rec(uid=7, agent_id="a1b2c3d4-0000")
    rec["refs"] = {"ref_3": {"role": "button", "name": "Pay now"},
                   "ref_4": {"role": "link", "name": "Cat pictures"}}
    c._remember(rec)
    ctx = {"user_id": 7, "agent_id": "a1b2c3d4-0000", "cleared_limits": []}
    assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_3"}) == "pay"
    assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_4"}) is None
    assert c.hard_limit_for(ctx, "computer_snapshot", {}) is None
    assert c.hard_limit_for(ctx, "computer_open", {"url": "https://shop.example/checkout"}) is None


def test_a_cleared_limit_is_not_a_limit_for_that_teammate():
    rec = _rec(uid=7, agent_id="a1b2c3d4-0000")
    rec["refs"] = {"ref_3": {"role": "button", "name": "Pay now"}}
    c._remember(rec)
    ctx = {"user_id": 7, "agent_id": "a1b2c3d4-0000", "cleared_limits": ["pay"]}
    assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_3"}) is None


def test_no_session_yet_means_no_refs_means_no_limit():
    ctx = {"user_id": 7, "agent_id": "nobody", "cleared_limits": []}
    assert c.hard_limit_for(ctx, "computer_click", {"ref": "ref_3"}) is None


def test_act_refuses_a_bad_ref_or_a_missing_url_before_touching_the_runner():
    ctx = {"user_id": 7, "agent_id": "a1", "run_id": "r", "cleared_limits": [], "pool": None}
    text, ok = asyncio.run(c.act(ctx, "computer_click", {"ref": "button 3"}))
    assert not ok and "ref_12" in text
    text, ok = asyncio.run(c.act(ctx, "computer_open", {"url": ""}))
    assert not ok and "duckduckgo" in text
    text, ok = asyncio.run(c.act(ctx, "not_a_tool", {}))
    assert not ok


def test_dispatch_without_a_computer_denies_rather_than_starting_a_browser():
    from workspace.orchestration.tools import dispatch_tool
    text, ok = asyncio.run(dispatch_tool("/tmp", "computer_snapshot", {}))
    assert not ok and "no computer" in text


def test_the_computer_flag_is_on_by_default_and_honours_an_off_switch(monkeypatch):
    from workspace.orchestration import authz
    from owui_compat.workspace_method import LANE_EXTERNAL_SERVICES
    monkeypatch.delenv("HARVIS_AGENT_COMPUTER_ENABLED", raising=False)
    assert authz._lane_flag_enabled(LANE_EXTERNAL_SERVICES, "computer_click")
    monkeypatch.setenv("HARVIS_AGENT_COMPUTER_ENABLED", "0")
    assert not authz._lane_flag_enabled(LANE_EXTERNAL_SERVICES, "computer_click")


def test_a_named_hard_limit_asks_even_on_the_agent_rung():
    from workspace.orchestration.authz import authorize_action
    from owui_compat.workspace_method import LANE_EXTERNAL_SERVICES
    seen = []
    res = asyncio.run(authorize_action(
        tool_name="computer_click", args={"ref": "ref_3"}, lane=LANE_EXTERNAL_SERVICES,
        permission_mode="agent", run_id="r", emit=seen.append, hard_limit="pay",
    ))
    assert res.needs_approval and res.tier == "hard"
    assert "spends money" in res.reason
    plain = asyncio.run(authorize_action(
        tool_name="computer_open", args={"url": "https://duckduckgo.com/?q=cats"},
        lane=LANE_EXTERNAL_SERVICES, permission_mode="agent", run_id="r", emit=seen.append,
    ))
    assert plain.allowed and not plain.needs_approval


def test_only_a_goal_written_as_several_things_goes_to_the_planner():
    from workspace.orchestration.coordinator import multi_part
    assert not multi_part("browse for cats")
    assert not multi_part("find three laptops under $800 on newegg and put them in a sheet")
    assert multi_part("find three laptops, then put them in a sheet")
    assert multi_part("1. find laptops\n2. compare them\n3. write it up")


def test_computer_context_carries_what_the_gate_and_audit_need():
    from workspace.orchestration.coordinator import computer_context
    agent = {"id": "a1", "autonomy": {"cleared_limits": ["send", None]}}
    ctx = computer_context(agent, user_id="7", run_id="r1", pool=None)
    assert ctx == {"user_id": 7, "agent_id": "a1", "run_id": "r1",
                   "cleared_limits": ["send"], "pool": None}
