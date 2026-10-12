"""A toolset switched off on the Capabilities screen keeps its tools from the model."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from plugins.hermes_ui import store  # noqa: E402
from workspace.orchestration import toolsets  # noqa: E402

TOOLS = [("read_file", 1), ("edit_file", 2), ("exec", 3), ("computer_click", 4), ("computer_snapshot", 4),
         ("agent_reach_search", 1), ("agent_reach_read", 1), ("finish", 0), ("brand_new_tool", 1)]


def test_cards_cover_every_tool_exactly_once():
    cards = toolsets.build_toolsets(set(), TOOLS)
    seen = [t for c in cards for t in c["tools"]]
    assert sorted(seen) == sorted(t for t, _ in TOOLS)
    by_name = {c["name"]: c for c in cards}
    assert by_name["harvis-browser"]["tools"] == ["computer_click", "computer_snapshot"]
    assert by_name["harvis-reach"]["tools"] == ["agent_reach_search", "agent_reach_read"]
    assert by_name[toolsets.OTHER]["tools"] == ["brand_new_tool"]


def test_enabled_flag_follows_the_disabled_set():
    cards = {c["name"]: c for c in toolsets.build_toolsets({"harvis-terminal"}, TOOLS)}
    assert cards["harvis-terminal"]["enabled"] is False and cards["harvis-files"]["enabled"] is True


def test_withheld_tools_are_the_members_of_the_disabled_sets():
    assert toolsets.withheld_tools(["harvis-terminal", "harvis-browser"], TOOLS) == {
        "exec", "computer_click", "computer_snapshot"}
    assert toolsets.withheld_tools([], TOOLS) == set()
    assert toolsets.withheld_tools(["no-such-set"], TOOLS) == set()


def test_finish_is_never_withheld_even_when_its_set_is_off():
    assert "finish" not in toolsets.withheld_tools(["harvis-agent"], TOOLS)


def test_unclaimed_tools_can_be_switched_off_too():
    assert toolsets.withheld_tools([toolsets.OTHER], TOOLS) == {"brand_new_tool"}


def test_the_real_registry_is_covered_and_exec_can_be_withheld():
    names = {t for t, _ in toolsets.registry_tools()}
    assert "exec" in names and "finish" in names
    withheld = toolsets.withheld_tools(["harvis-terminal", "harvis-agent"])
    assert "exec" in withheld and "finish" not in withheld


def _patch_store(monkeypatch, section):
    async def get_section(pool, uid):
        return section
    monkeypatch.setattr(store, "get_section", get_section)


def test_runner_reads_the_users_choice(monkeypatch):
    _patch_store(monkeypatch, {"disabled_toolsets": ["harvis-terminal"]})
    assert asyncio.run(toolsets.disabled_tool_names(object(), 7)) == {"exec"}


def test_no_pool_or_no_user_withholds_nothing():
    assert asyncio.run(toolsets.disabled_tool_names(None, 7)) == set()
    assert asyncio.run(toolsets.disabled_tool_names(object(), None)) == set()


def test_a_broken_settings_read_fails_open(monkeypatch):
    async def boom(pool, uid):
        raise RuntimeError("db down")
    monkeypatch.setattr(store, "get_section", boom)
    assert asyncio.run(toolsets.disabled_tool_names(object(), 7)) == set()


def test_garbage_in_the_setting_withholds_nothing(monkeypatch):
    _patch_store(monkeypatch, {"disabled_toolsets": "harvis-terminal"})
    assert asyncio.run(toolsets.disabled_tool_names(object(), 7)) == set()


def test_toolset_enabled():
    assert toolsets.toolset_enabled(None, "harvis-reach") is True
    assert toolsets.toolset_enabled(["harvis-reach"], "harvis-reach") is False
