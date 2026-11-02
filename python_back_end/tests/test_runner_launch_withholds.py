"""An auto launch may run commands only where dispatch_tool sends them to the
chat's isolated container; everywhere else exec and run_tests stay withheld."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspace.orchestration import runner  # noqa: E402
from workspace.orchestration.runner import _default_system, _launch_withholds  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_on(monkeypatch):
    monkeypatch.delenv("HARVIS_BUILD_ISOLATED_RUNNER", raising=False)


def test_user_launches_withhold_nothing():
    assert _launch_withholds("user", None) == set()


def test_auto_launch_without_a_sandbox_cannot_run_commands():
    assert _launch_withholds("auto", None) == {"exec", "run_tests"}
    assert _launch_withholds("auto", "") == {"exec", "run_tests"}


def test_auto_launch_in_a_sandbox_can_run_commands():
    assert _launch_withholds("auto", "sess-1") == set()


@pytest.mark.parametrize("off", ["0", "false", "no", "off"])
def test_isolated_runner_off_withholds_again(monkeypatch, off):
    monkeypatch.setenv("HARVIS_BUILD_ISOLATED_RUNNER", off)
    assert _launch_withholds("auto", "sess-1") == {"exec", "run_tests"}


def test_offer_matches_dispatch_routing(monkeypatch):
    # Whatever the flag says, exec is offered only when dispatch_tool would isolate it.
    for env in ("", "1", "0", "off", "garbage"):
        monkeypatch.setenv("HARVIS_BUILD_ISOLATED_RUNNER", env)
        for sid in (None, "sess-1"):
            isolated = bool(sid) and runner._isolated_runner_enabled()
            assert ("exec" not in _launch_withholds("auto", sid)) == isolated


def test_prompt_follows_the_offer():
    assert "run exec / run_tests" in _default_system("coder", _launch_withholds("auto", "sess-1"))
    assert "cannot run commands" in _default_system("coder", _launch_withholds("auto", None))


# ─── skill tool results name their tool, so Hermes can close the card ────────

import asyncio  # noqa: E402
import json  # noqa: E402


class _Router:
    def __init__(self, name, args):
        self.turn = {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
        self.sent = False

    async def complete(self, *, tools, **_):
        if self.sent or not tools:
            return {"role": "assistant", "content": "done"}
        self.sent = True
        return self.turn


def _tool_results(tmp_path, name, args, **kw):
    async def go():
        return [e async for e in runner.SubAgentRunner(_Router(name, args)).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="use a skill",
            model_name="m", workspace_path=str(tmp_path), **kw)]
    return [e.data for e in asyncio.run(go()) if e.type == "tool_result"]


def _no_mod_rules(monkeypatch):
    # The fake pool cannot be read, and unreadable mod rules make every tool ask first.
    import plugins.mods as mods
    from plugins.mods.rules import ModRules

    async def empty(pool, uid):
        return ModRules()

    monkeypatch.setattr(mods, "rules_for_user", empty)


@pytest.mark.parametrize("name", ["list_skills", "read_skill"])
def test_skill_reads_name_their_tool(tmp_path, monkeypatch, name):
    from plugins.hermes_ui import skill_select
    from workspace.orchestration import toolsets

    async def fake(*_a, **_k):
        return "skill body"

    async def none(*_a, **_k):
        return set()

    monkeypatch.setattr(skill_select, "run_list_skills", fake)
    monkeypatch.setattr(skill_select, "run_read_skill", fake)
    monkeypatch.setattr(toolsets, "disabled_tool_names", none)
    _no_mod_rules(monkeypatch)
    out = _tool_results(tmp_path, name, {"name": "x"}, pool=object(), user_id=1, launch_mode="user")
    assert out and out[0]["tool"] == name and out[0]["output"] == "skill body"


def test_withheld_skill_tool_denial_names_its_tool(tmp_path):
    out = _tool_results(tmp_path, "propose_skill", {"name": "x"}, launch_mode="auto")
    assert out and out[0]["tool"] == "propose_skill" and out[0]["output"].startswith("DENIED")


# ─── a mod's ask-first rule reaches the tools the runner handles itself ──────

def test_a_mod_ask_rule_gates_a_runner_handled_tool(tmp_path, monkeypatch):
    import plugins.mods as mods
    from plugins.hermes_ui import skill_select
    from plugins.mods.rules import ModRules
    from workspace.orchestration import toolsets

    ran = []

    async def fake(*_a, **_k):
        ran.append(1)
        return "skill body"

    async def none(*_a, **_k):
        return set()

    async def rules(pool, uid):
        return ModRules([("careful", {"event": "PreToolUse", "action": "require-approval",
                                      "match": "tool:list_skills"})])

    async def quiet(*_a, **_k):
        return None

    async def deny(_action_id):
        return False, False

    monkeypatch.setattr(skill_select, "run_list_skills", fake)
    monkeypatch.setattr(toolsets, "disabled_tool_names", none)
    monkeypatch.setattr(mods, "rules_for_user", rules)
    monkeypatch.setattr(runner, "register_pending", lambda *_a, **_k: None)
    for helper in ("persist_pending", "announce_approval", "mark_pending_resolved", "withdraw_approval"):
        monkeypatch.setattr(runner, helper, quiet)
    monkeypatch.setattr(runner, "await_action_outcome", deny)

    async def go():
        return [e async for e in runner.SubAgentRunner(_Router("list_skills", {})).run(
            run_id="r1", parent_run_id="p1", label="Harvis Agent", task="use a skill",
            model_name="m", workspace_path=str(tmp_path), pool=object(), user_id=1, launch_mode="user")]

    events = asyncio.run(go())
    asks = [e.data for e in events if e.type == "approval_request"]
    results = [e.data for e in events if e.type == "tool_result"]
    assert asks and "careful" in asks[0]["reason"]
    assert ran == [] and results[0]["output"] == "Denied by the user."
