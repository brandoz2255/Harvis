"""Auto mode must not launch a tool-loop on a model that cannot call tools, and only an
explicit Agent/Orchestrate pick may rewrite the shared workspace model."""

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import workspace_bridge as wb  # noqa: E402


def _caps(monkeypatch, table):
    import vison_models.llm_connector as conn

    asked = []

    def fake(model, url=None):
        asked.append(model)
        return table.get(model, [])

    monkeypatch.setattr(conn, "model_capabilities", fake)
    return asked


def test_a_model_without_tools_is_flagged(monkeypatch):
    _caps(monkeypatch, {"gemma3:4b": ["completion", "vision"], "qwen3:4b": ["completion", "tools"]})
    assert asyncio.run(wb._cannot_call_tools("gemma3:4b")) is True
    assert asyncio.run(wb._cannot_call_tools("qwen3:4b")) is False


def test_unknown_capabilities_do_not_block_the_launch(monkeypatch):
    _caps(monkeypatch, {})
    assert asyncio.run(wb._cannot_call_tools("remote-node-model")) is False


@pytest.mark.parametrize("model", ["", "auto", "hermes-agent", "anthropic/claude", "moonshot/kimi-k3",
                                   "openai/gpt-6", "kimi-code/k3"])
def test_sentinels_and_cloud_ids_are_never_looked_up(monkeypatch, model):
    asked = _caps(monkeypatch, {model: ["completion"]})
    assert asyncio.run(wb._cannot_call_tools(model)) is False
    assert asked == []


def test_a_failing_lookup_does_not_block_the_launch(monkeypatch):
    import vison_models.llm_connector as conn

    def boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(conn, "model_capabilities", boom)
    assert asyncio.run(wb._cannot_call_tools("gemma3:4b")) is False


class _Harness:
    def __init__(self, monkeypatch, caps):
        import workspace.task_detector as td
        import importlib
        wr = importlib.import_module("workspace.workspace_router")  # the package attribute is a router
        import plugins.exposure as exposure

        self.synced, self.started = [], []
        _caps(monkeypatch, caps)

        async def detect(history):
            return td.WorkspaceSuggestion({"should_suggest": True, "confidence": 0.95,
                                           "task_type": "file", "task_brief": "b", "reason": "r"})

        async def sync(pool, model):
            self.synced.append(model)

        async def start(**kw):
            self.started.append(kw)

        async def create(*a, **k):
            return None

        async def enable(*a, **k):
            return "cap-token"

        monkeypatch.setattr(td, "detect_workspace_task", detect)
        monkeypatch.setattr(wr, "_start_workspace", start)
        monkeypatch.setattr(wr, "_db_create_run", create)
        monkeypatch.setattr(wr, "_db_enable_interactive", enable)
        monkeypatch.setattr(exposure, "build_space_allowed", lambda uid: True)
        monkeypatch.setattr(wb, "_sync_workspace_model", sync)
        monkeypatch.setattr(wb, "_approvals_enabled", lambda: False)
        self.request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_pool=object())))
        self.user = SimpleNamespace(id=7)

    def run(self, model, mode="auto", text="what is the code word in the attached file", **extra):
        self.body = {"model": model, "harvis_mode": mode, **extra,
                     "messages": [{"role": "user", "content": text}]}
        return asyncio.run(wb.maybe_handle_workspace(self.request, self.body, self.user))


async def _drain(resp):
    return "".join([c async for c in resp.body_iterator])


def test_auto_mode_on_a_no_tools_model_falls_back_to_plain_chat(monkeypatch):
    h = _Harness(monkeypatch, {"gemma3:4b": ["completion", "vision"]})
    assert h.run("gemma3:4b") is None
    assert h.started == [] and h.synced == []


def test_a_run_request_on_a_no_tools_model_is_told_it_cannot_run_code(monkeypatch):
    h = _Harness(monkeypatch, {"gemma3:4b": ["completion"]})
    assert h.run("gemma3:4b", text="run this python script for me") is None
    system = h.body["messages"][0]
    assert system["role"] == "system" and system["content"].endswith(wb.NO_RUN_NOTE)
    assert len(system["content"]) > len(wb.NO_RUN_NOTE)  # the house persona is kept


def test_ordinary_chat_on_a_no_tools_model_gets_no_note(monkeypatch):
    h = _Harness(monkeypatch, {"gemma3:4b": ["completion"]})
    assert h.run("gemma3:4b", text="how do I run faster in the morning") is None
    assert [m["role"] for m in h.body["messages"]] == ["user"]


def test_agent_pick_on_a_no_tools_model_gets_a_refusal_not_a_run(monkeypatch):
    h = _Harness(monkeypatch, {"gemma3:4b": ["completion", "vision"]})
    resp = h.run("gemma3:4b", mode="agent")
    text = asyncio.run(_drain(resp))
    assert "gemma3:4b cannot call tools" in text and "Chat mode" in text
    assert h.started == [] and h.synced == []


def test_auto_launch_does_not_rewrite_the_shared_workspace_model(monkeypatch):
    h = _Harness(monkeypatch, {"qwen3:4b": ["completion", "tools"]})
    assert h.run("qwen3:4b") is not None
    assert len(h.started) == 1 and h.synced == []


def test_agent_pick_still_syncs_the_workspace_model(monkeypatch):
    h = _Harness(monkeypatch, {"qwen3:4b": ["completion", "tools"]})
    assert h.run("qwen3:4b", mode="agent") is not None
    assert len(h.started) == 1 and h.synced == ["qwen3:4b"]


def test_orchestrate_on_pool_models_is_not_refused_for_the_chat_pick(monkeypatch):
    h = _Harness(monkeypatch, {"gemma3:4b": ["completion", "vision"]})
    assert h.run("gemma3:4b", mode="orchestrate") is not None
    assert len(h.started) == 1


def test_uniform_orchestrate_on_a_no_tools_model_is_refused(monkeypatch):
    h = _Harness(monkeypatch, {"gemma3:4b": ["completion", "vision"]})
    resp = h.run("gemma3:4b", mode="orchestrate", harvis_orchestrate_uniform=True)
    assert "cannot call tools" in asyncio.run(_drain(resp))
    assert h.started == []
