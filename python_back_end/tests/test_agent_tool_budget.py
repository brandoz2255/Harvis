"""Connector schema is budgeted so a teammate run reaches its first tool call."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.agents import tool_budget  # noqa: E402


def _spec(name: str, description: str, pad: int = 0) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": description + ("x" * pad), "parameters": {}},
    }


def test_a_small_catalogue_is_left_alone():
    specs = [_spec("a", "one"), _spec("b", "two")]
    assert tool_budget.trim(specs, "anything") == (specs, 0)


def test_goal_relevant_tools_survive_the_cut():
    specs = [_spec(f"filler_{i}", "unrelated bookkeeping", pad=400) for i in range(10)]
    specs.append(_spec("browser_navigate", "open a web page in the browser"))
    kept, dropped = tool_budget.trim(specs, "browse the web for cats", limit=900)
    names = [s["function"]["name"] for s in kept]
    assert "browser_navigate" in names
    assert dropped == len(specs) - len(kept) > 0


def test_kept_tools_stay_in_catalogue_order():
    specs = [_spec(f"t{i}", "web page browser", pad=200) for i in range(8)]
    kept, _ = tool_budget.trim(specs, "browse", limit=700)
    names = [s["function"]["name"] for s in kept]
    assert names == sorted(names, key=lambda n: int(n[1:]))


def test_zero_budget_drops_every_connector(monkeypatch):
    monkeypatch.setenv("HARVIS_AGENT_MCP_BUDGET_CHARS", "0")
    specs = [_spec("a", "one"), _spec("b", "two")]
    assert tool_budget.trim(specs, "goal") == ([], 2)


def test_empty_catalogue_is_not_an_error():
    assert tool_budget.trim([], "goal") == ([], 0)
