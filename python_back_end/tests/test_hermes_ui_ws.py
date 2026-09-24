"""Contract tests for the lightweight Hermes gateway compatibility methods."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui.ws import Connection  # noqa: E402


@pytest.mark.asyncio
async def test_projects_tree_returns_an_empty_harvis_tree_until_projects_exist():
    result = await Connection.m_projects_tree(None, 17, {"preview_limit": 3})

    assert result == {
        "jsonrpc": "2.0",
        "id": 17,
        "result": {"projects": [], "active_id": None, "scoped_session_ids": []},
    }


@pytest.mark.asyncio
async def test_wake_status_explicitly_reports_the_feature_unavailable():
    result = await Connection.m_wake_status(None, 18, {"client_capture": True, "surface": "gui"})

    assert result == {
        "jsonrpc": "2.0",
        "id": 18,
        "result": {"available": False, "enabled": False, "listening": False, "reason": "unavailable"},
    }


def test_effort_scale_folds_onto_ollamas_three_levels():
    from plugins.hermes_ui.models import ollama_effort

    assert ollama_effort("minimal") == "low"
    assert ollama_effort("medium") == "medium"
    assert ollama_effort("ultra") == "high"
    assert ollama_effort("none") == "none"
    assert ollama_effort("") == "medium"


@pytest.mark.asyncio
async def test_config_set_reasoning_sets_the_session_effort(monkeypatch):
    from plugins.hermes_ui import sessions

    live = sessions.Live(id="s1", user_id=1)
    emitted = []

    class Conn:
        async def _open(self, rid, params):
            return live, [], None

        async def emit(self, kind, sid, payload):
            emitted.append((kind, payload["reasoning_effort"]))

    result = await Connection.m_config_set(Conn(), 5, {"key": "reasoning", "session_id": "s1", "value": "High"})

    assert result["result"] == {"ok": True}
    assert live.effort == "high"
    assert emitted == [("session.info", "high")]
