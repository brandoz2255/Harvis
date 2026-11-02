"""Mods: what a mod may declare, that approval binds to every byte, that rules only
tighten the tool gate, and that one person's mods never reach another's.

The store tests need a scratch Postgres: set MODS_TEST_DSN to one (never the live
database; the tests create and drop their own tables). Without it they skip.
"""
import asyncio
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.mods import manifest as mf  # noqa: E402
from plugins.mods import rules as mod_rules  # noqa: E402
from plugins.mods import store  # noqa: E402
from workspace.orchestration import authz  # noqa: E402

PAGE = "<!doctype html><p>hi</p>"


def ui_mod(**over):
    m = {"harvis_mod_version": "0.1", "name": "clock-face", "version": "1.0.0",
         "author": "me", "description": "a clock",
         "ui": {"resource": "index.html", "slot": "clock", "csp": {"connectDomains": []}}}
    m.update(over)
    return m


def rules_mod(*hooks, name="careful"):
    return {"harvis_mod_version": "0.1", "name": name, "version": "1.0.0", "author": "me",
            "description": "rules", "rules": {"hooks": list(hooks)}}


# ── validation ────────────────────────────────────────────────────────────

def test_a_plain_ui_mod_is_valid():
    errors, _ = mf.validate(ui_mod(), {"index.html": PAGE})
    assert errors == []


@pytest.mark.parametrize("change, needle", [
    (lambda m: m.update(kind="ui", ui=None) or m.pop("ui"), "does nothing"),
    (lambda m: m["ui"].update(resource="../x.html"), "inside the package"),
    (lambda m: m["ui"].update(slot="everywhere"), "ui.slot"),
    (lambda m: m["ui"]["csp"].update(connectDomains=["http://evil.test"]), "bad origin"),
    (lambda m: m["ui"]["csp"].update(scriptDomains=["https://x.test"]), "not a known setting"),
    (lambda m: m.update(exec="rm -rf /"), "unknown field"),
    (lambda m: m.update(looks={"bg": "url(https://evil.test/p)"}), "not a plain theme value"),
    (lambda m: m.update(looks={"bg": "red;}body{display:none"}), "not a plain theme value"),
    (lambda m: m.update(looks={"bg": {"nested": 1}}), "plain text"),
])
def test_bad_manifests_are_refused(change, needle):
    m = ui_mod()
    change(m)
    errors, _ = mf.validate(m, {"index.html": PAGE})
    assert any(needle in e for e in errors), errors


def test_a_resource_the_manifest_does_not_name_is_refused():
    errors, _ = mf.validate(ui_mod(), {"index.html": PAGE, "extra.html": PAGE})
    assert any("extra.html" in e for e in errors)


def test_rules_need_a_match_and_the_right_event():
    errors, _ = mf.validate(rules_mod({"event": "PreToolUse", "action": "block"}))
    assert any("match" in e for e in errors)
    errors, _ = mf.validate(rules_mod({"event": "PreSend", "action": "block", "match": "tool:x"}))
    assert any("runs on PreToolUse" in e for e in errors)
    errors, _ = mf.validate(rules_mod({"event": "PreSend", "action": "prepend-context", "text": "x" * 2001}))
    assert any("2000" in e for e in errors)


# ── the hash covers every byte (the harvis-mods reference did not) ──────────

def test_changing_a_nested_csp_entry_changes_the_hash():
    a = ui_mod()
    b = copy.deepcopy(a)
    b["ui"]["csp"]["connectDomains"] = ["https://evil.test"]
    res = {"index.html": PAGE}
    assert mf.content_hash(a, res) != mf.content_hash(b, res)


def test_changing_a_rule_detail_or_resource_changes_the_hash():
    a = rules_mod({"event": "PreToolUse", "action": "block", "match": "tool:shell*"})
    b = rules_mod({"event": "PreToolUse", "action": "block", "match": "tool:sh*"})
    assert mf.content_hash(a, {}) != mf.content_hash(b, {})
    assert mf.content_hash(ui_mod(), {"index.html": PAGE}) != mf.content_hash(ui_mod(), {"index.html": PAGE + " "})


def test_the_hash_ignores_key_order():
    a = ui_mod()
    b = dict(reversed(list(a.items())))
    assert mf.content_hash(a, {"index.html": PAGE}) == mf.content_hash(b, {"index.html": PAGE})


# ── rules only tighten ─────────────────────────────────────────────────────

def test_the_strictest_rule_wins():
    r = mod_rules.ModRules([
        ("a", {"event": "PreToolUse", "action": "require-approval", "match": "tool:shell*"}),
        ("b", {"event": "PreToolUse", "action": "block", "match": "tool:SHELL"}),
    ])
    assert r.tool_rule("shell")[0] == "block"
    assert r.tool_rule("shell_exec")[0] == "require-approval"
    assert r.tool_rule("read_file") is None


def test_context_text_is_labelled_and_session_start_only_once():
    r = mod_rules.ModRules([
        ("tone", {"event": "PreSend", "action": "prepend-context", "text": "Be brief."}),
        ("hello", {"event": "SessionStart", "action": "prepend-context", "text": "Say hi."}),
    ])
    first, later = r.context_text(first_turn=True), r.context_text(first_turn=False)
    assert "[From the user's mod 'tone']" in first and "Say hi." in first
    assert "Be brief." in later and "Say hi." not in later


def _authorize(**kw):
    events = []
    res = asyncio.run(authz.authorize_action(
        tool_name=kw.pop("tool", "read_file"), args={}, lane=2, permission_mode=kw.pop("mode", None),
        run_id="r", emit=events.append, **kw))
    return res, events


def test_a_block_rule_denies_a_tool_the_gate_would_allow():
    res, events = _authorize(mod_rule=("block", "your mod 'careful' blocks read_file"))
    assert not res.allowed and res.tier is None
    assert events[-1]["source"] == "mod_rule"


def test_an_ask_rule_turns_an_allow_into_a_gate():
    res, events = _authorize(mod_rule=("require-approval", "asks"))
    assert res.allowed and res.needs_approval and res.tier
    assert len(events) == 1 and events[0]["policy"] == "gate"
    res, _ = _authorize(mode="full-auto", mod_rule=("require-approval", "asks"))
    assert res.needs_approval


def test_an_ask_rule_outranks_approve_for_session(monkeypatch):
    async def approved(*_a, **_k):
        return True

    monkeypatch.setattr(authz, "is_session_approved", approved)
    res, events = _authorize(tool="exec", mode="ask", session_id="s", mod_rule=("require-approval", "asks"))
    assert res.needs_approval and events[-1]["source"] == "mod_rule"
    res, events = _authorize(tool="exec", mode="ask", session_id="s")
    assert not res.needs_approval and events[-1]["source"] == "session_approval"


@pytest.mark.parametrize("manifest_patch,resources", [
    ({"description": float("nan")}, {}),
    ({"description": "a\u0000b"}, {}),
    ({"description": "\ud800"}, {}),
    ({}, {"index.html": "x\u0000"}),
])
def test_values_postgres_cannot_store_are_a_422_not_a_500(manifest_patch, resources):
    errors, _ = mf.validate({**ui_mod(), **manifest_patch}, {"index.html": PAGE, **resources})
    assert errors and len(errors) == 1


def test_without_a_rule_the_gate_is_unchanged():
    res, _ = _authorize()
    assert res.allowed and not res.needs_approval


def test_a_rule_cannot_loosen_a_plan_mode_block():
    res, _ = _authorize(tool="exec", mode="plan", mod_rule=("require-approval", "asks"))
    assert not res.allowed


# ── store (scratch Postgres only) ──────────────────────────────────────────

DSN = os.getenv("MODS_TEST_DSN")
needs_db = pytest.mark.skipif(not DSN, reason="MODS_TEST_DSN not set (scratch Postgres only)")
MIG = os.path.join(os.path.dirname(__file__), "..", "migrations", "025_user_mods.sql")


@pytest.fixture
def pool():
    import asyncpg

    async def setup():
        p = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
        async with p.acquire() as c:
            await c.execute("DROP TABLE IF EXISTS user_mods; DROP TABLE IF EXISTS users;"
                            "CREATE TABLE users (id SERIAL PRIMARY KEY, username TEXT);"
                            "INSERT INTO users (username) VALUES ('a'), ('b');")
            with open(MIG) as f:
                sql = f.read()
            await c.execute(sql)
            await c.execute(sql)  # boot applies it every time: must be idempotent
        return p

    loop = asyncio.new_event_loop()
    p = loop.run_until_complete(setup())
    yield loop, p
    loop.run_until_complete(p.close())
    loop.close()


@needs_db
def test_install_approve_rollback_and_isolation(pool):
    loop, p = pool
    run = loop.run_until_complete
    v1 = run(store.install(p, 1, ui_mod(), {"index.html": PAGE}, "agent"))
    assert v1["mod"]["status"] == "draft" and v1["approval"]["slot"] == "clock"
    h1 = v1["approval"]["hash"]

    # B cannot approve, read or remove A's mod.
    with pytest.raises(store.ModError):
        run(store.approve(p, 2, "clock-face", h1))
    with pytest.raises(store.ModError):
        run(store.resources(p, 2, "clock-face", h1))
    assert run(store.remove(p, 2, "clock-face")) == 0
    assert run(store.list_mods(p, 2)) == []

    # Approval binds to the exact hash.
    with pytest.raises(store.ModError):
        run(store.approve(p, 1, "clock-face", "0" * 64))
    assert run(store.approve(p, 1, "clock-face", h1))["status"] == "on"

    v2 = run(store.install(p, 1, ui_mod(version="1.1.0"), {"index.html": PAGE + "<b>2</b>"}, "user"))
    h2 = v2["approval"]["hash"]
    assert v2["mod"]["status"] == "draft"
    run(store.approve(p, 1, "clock-face", h2))
    on = [m for m in run(store.list_mods(p, 1)) if m["status"] == "on"]
    assert [m["hash"] for m in on] == [h2]

    assert run(store.rollback(p, 1, "clock-face"))["hash"] == h1
    assert run(store.set_off(p, 1, "clock-face", "crashed", broken=True))["status"] == "broken"
    assert run(store.resources(p, 1, "clock-face", h1)) == {"index.html": PAGE}
    # Nothing earlier than h1, and rollback never turns the crashed version back on.
    with pytest.raises(store.ModError):
        run(store.rollback(p, 1, "clock-face"))
    assert not [m for m in run(store.list_mods(p, 1)) if m["status"] == "on"]

    # The person re-approves h1 by hand. With v2 then switched off (not crashed),
    # rollback steps back to h1, not v2.
    run(store.approve(p, 1, "clock-face", h1))
    run(store.approve(p, 1, "clock-face", h2))
    run(store.set_off(p, 1, "clock-face"))
    assert run(store.rollback(p, 1, "clock-face"))["hash"] == h1

    # The card for a stored version comes from the server's bytes, with the stored hash.
    c = run(store.card(p, 1, "clock-face", h2))
    assert c["approval"]["hash"] == h2 and c["mod"]["hash"] == h2
    with pytest.raises(store.ModError):
        run(store.card(p, 2, "clock-face", h2))


@needs_db
def test_agent_drafts_never_prune_approved_versions(pool, monkeypatch):
    loop, p = pool
    run = loop.run_until_complete
    monkeypatch.setattr(store, "MAX_VERSIONS_PER_MOD", 2)
    v1 = run(store.install(p, 1, ui_mod(), {"index.html": PAGE}, "user"))
    run(store.approve(p, 1, "clock-face", v1["approval"]["hash"]))
    run(store.set_off(p, 1, "clock-face"))
    for i in range(4):
        run(store.install(p, 1, ui_mod(version=f"1.0.{i + 1}"), {"index.html": PAGE + str(i)}, "agent"))
    hashes = {m["hash"] for m in run(store.list_mods(p, 1))}
    assert v1["approval"]["hash"] in hashes and len(hashes) == 3


@needs_db
def test_racing_approves_answer_409(pool):
    loop, p = pool
    run = loop.run_until_complete
    a = run(store.install(p, 1, ui_mod(), {"index.html": PAGE}, "user"))["approval"]["hash"]
    b = run(store.install(p, 1, ui_mod(version="2.0.0"), {"index.html": PAGE + "2"}, "user"))["approval"]["hash"]

    async def both():
        return await asyncio.gather(store.approve(p, 1, "clock-face", a),
                                    store.approve(p, 1, "clock-face", b), return_exceptions=True)

    out = run(both())
    errs = [e for e in out if isinstance(e, Exception)]
    assert all(isinstance(e, store.ModError) and e.status == 409 for e in errs)
    assert len([m for m in run(store.list_mods(p, 1)) if m["status"] == "on"]) == 1


@needs_db
def test_only_approved_on_rules_are_enforced(pool):
    loop, p = pool
    run = loop.run_until_complete
    m = rules_mod({"event": "PreToolUse", "action": "block", "match": "tool:shell*"})
    v = run(store.install(p, 1, m, {}, "agent"))
    assert run(mod_rules.for_user(p, 1)).tool_rule("shell") is None  # draft: not enforced
    run(store.approve(p, 1, "careful", v["approval"]["hash"]))
    assert run(mod_rules.for_user(p, 1)).tool_rule("shell")[0] == "block"
    assert run(mod_rules.for_user(p, 2)).tool_rule("shell") is None  # never another person's
    run(store.set_off(p, 1, "careful"))
    assert run(mod_rules.for_user(p, 1)).tool_rule("shell") is None


@needs_db
def test_reinstalling_the_same_bytes_keeps_the_approval(pool):
    loop, p = pool
    run = loop.run_until_complete
    v = run(store.install(p, 1, ui_mod(), {"index.html": PAGE}, "user"))
    run(store.approve(p, 1, "clock-face", v["approval"]["hash"]))
    again = run(store.install(p, 1, ui_mod(), {"index.html": PAGE}, "agent"))
    assert again["mod"]["status"] == "on"


# ── routes: the plugin door, in the real facade order ──────────────────────

@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_optimized import get_current_user_optimized
    from plugins.hermes_ui.router import router

    calls = []

    async def fake_list(pool, uid):
        calls.append(("list", uid))
        return []

    async def fake_approve(pool, uid, name, h):
        calls.append(("approve", uid, name, h))
        return {"name": name, "hash": h, "status": "on"}

    monkeypatch.setattr(store, "list_mods", fake_list)
    monkeypatch.setattr(store, "approve", fake_approve)
    app = FastAPI()
    app.state.pg_pool = object()
    app.include_router(router)
    app.dependency_overrides[get_current_user_optimized] = lambda: {"id": 7}
    return TestClient(app), calls


def test_the_mods_backend_is_reached_before_the_plugin_catch_all(client):
    c, calls = client
    r = c.get("/hermes-api/api/plugins/mods")
    assert r.status_code == 200 and r.json() == {"mods": []}
    assert calls == [("list", 7)]
    assert c.get("/hermes-api/api/plugins").json() == {"backends": ["mods"]}


def test_the_desktop_list_url_with_a_trailing_slash_reaches_the_mods_backend(client):
    # pluginRest('mods', '') builds /api/plugins/mods/ (pluginPathSuffix always adds the slash)
    c, calls = client
    r = c.get("/hermes-api/api/plugins/mods/")
    assert r.status_code == 200 and r.json() == {"mods": []}
    assert calls == [("list", 7)]


def test_a_plugin_without_a_backend_says_so(client):
    c, _ = client
    r = c.get("/hermes-api/api/plugins/kanban/board")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "plugin_backend_missing"


def test_approve_needs_the_card_hash(client):
    c, calls = client
    assert c.post("/hermes-api/api/plugins/mods/clock-face/approve", json={"hash": "abc"}).status_code == 400
    assert c.post("/hermes-api/api/plugins/mods/clock-face/approve", json={}).status_code == 400
    h = "a" * 64
    r = c.post("/hermes-api/api/plugins/mods/clock-face/approve", json={"hash": h.upper()})
    assert r.status_code == 200 and calls[-1] == ("approve", 7, "clock-face", h)


# ── prepend-context reaches the chat prompt ────────────────────────────────

def _chat_turn(monkeypatch, hooks, messages):
    from types import SimpleNamespace
    from owui_compat import chat_completion as cc

    async def fake_active(pool, uid):
        return hooks if uid == 7 else []

    monkeypatch.setattr(store, "active_rules", fake_active)
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))
    body = {"messages": messages}
    asyncio.run(cc._inject_mod_context(req, body, user_id=7))
    return body["messages"]


TONE = ("tone", {"event": "PreSend", "action": "prepend-context", "text": "Be brief."})
HELLO = ("hello", {"event": "SessionStart", "action": "prepend-context", "text": "Say hi."})


def test_mod_context_joins_the_leading_system_message(monkeypatch):
    msgs = _chat_turn(monkeypatch, [TONE, HELLO],
                      [{"role": "system", "content": "persona"}, {"role": "user", "content": "yo"}])
    assert len(msgs) == 2 and msgs[0]["content"].startswith("persona")
    assert "Be brief." in msgs[0]["content"] and "Say hi." in msgs[0]["content"]


def test_session_start_text_only_on_the_first_turn(monkeypatch):
    msgs = _chat_turn(monkeypatch, [TONE, HELLO], [
        {"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"}])
    assert msgs[0]["role"] == "system" and "Be brief." in msgs[0]["content"]
    assert "Say hi." not in msgs[0]["content"]


def test_no_rules_leaves_the_turn_alone(monkeypatch):
    msgs = _chat_turn(monkeypatch, [], [{"role": "user", "content": "a"}])
    assert msgs == [{"role": "user", "content": "a"}]


# ── rules that cannot be read, log rules, chat web lookups ─────────────────

def test_unreadable_rules_make_every_tool_ask_and_add_no_text():
    class Broken:
        async def fetch(self, *a, **k):
            raise RuntimeError("db down")

    r = run_rules(mod_rules.for_user(Broken(), 1))
    assert r and r.tool_rule("read_file")[0] == "require-approval"
    assert r.context_text(first_turn=True) == ""


def run_rules(coro):
    return asyncio.run(coro)


def test_log_rules_write_a_line_and_never_gate(caplog):
    r = mod_rules.ModRules([
        ("audit", {"event": "PostToolUse", "action": "log", "match": "tool:exec"}),
        ("audit", {"event": "PreToolUse", "action": "log", "match": "tool:exec"}),
    ])
    assert r.tool_rule("exec") is None
    with caplog.at_level("INFO", logger="mods.rules"):
        r.log_tool("PreToolUse", "exec")
        r.log_tool("PostToolUse", "exec", ok=False)
        r.log_tool("PostToolUse", "read_file", ok=True)
    lines = [rec.getMessage() for rec in caplog.records]
    assert lines == ["mod audit: PreToolUse exec", "mod audit: PostToolUse exec failed"]


def test_a_mod_rule_stops_a_chat_web_lookup(monkeypatch):
    import plugins.mods as mods
    from owui_compat import chat_reach

    async def rules(pool, uid):
        return mod_rules.ModRules([("offline", {"event": "PreToolUse", "action": "block",
                                                "match": "tool:agent_reach_*"})])

    monkeypatch.setattr(mods, "rules_for_user", rules)
    assert "offline" in asyncio.run(chat_reach._mod_stop(None, 7))

    async def none(pool, uid):
        return mod_rules.ModRules()

    monkeypatch.setattr(mods, "rules_for_user", none)
    assert asyncio.run(chat_reach._mod_stop(None, 7)) == ""


def test_runner_handled_tools_are_listed_for_the_ask_gate():
    from workspace.orchestration import runner

    assert {"generate_image", "propose_mod", "screenshot_preview"} <= runner._IN_RUNNER_TOOLS
