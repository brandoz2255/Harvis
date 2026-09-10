"""A teammate on "auto" runs on a real model, never on an empty name."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugins.agents.models as models  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def test_sentinels_and_non_models_are_not_usable():
    for bad in ("", "auto", "Auto", "default", "agent:abc", "hermes-agent", None):
        assert not models.usable_pick(bad), bad
    assert models.usable_pick("gemma4:e4b")
    assert models.usable_pick("anthropic/claude-sonnet-5")


def test_teammate_setting_wins():
    got = _run(models.resolve_run_model(None, 2, {"model": "gemma4:e4b"}, last_pick="qwen3:4b"))
    assert got == ("gemma4:e4b", "teammate setting")


def test_task_classification():
    assert models.classify_task("browse for cats") == "computer"
    assert models.classify_task("refactor the auth module and run tests") == "code"
    assert models.classify_task("draft an email to the landlord") == "write"
    assert models.classify_task("think about it") == "general"


def test_task_pick_prefers_a_tool_caller_and_skips_embeddings(monkeypatch):
    async def installed():
        return [
            ("nomic-embed-text:latest", "ollama"),
            ("gemma4:e2b", "ollama"),
            ("llama3.1:8b", "ollama"),
            ("batiai/qwen3.5-9b:latest", "ollama"),
        ]

    monkeypatch.setattr(models, "_installed", installed)
    got, why = _run(models.pick_for_task("browse for cats"))
    assert got == "batiai/qwen3.5-9b:latest"
    assert "computer" in why


def test_a_node_model_beats_the_same_family_on_ollama(monkeypatch):
    async def installed():
        return [
            ("Qwen3.6-35B-A3B-NVFP4", "node"),
            ("fredrezones55/Qwen3.6-35B-Uncensored:latest", "ollama"),
        ]

    monkeypatch.setattr(models, "_installed", installed)
    got, why = _run(models.pick_for_task("browse for cats"))
    assert got == "Qwen3.6-35B-A3B-NVFP4"
    assert "inference node" in why


def test_base_tag_beats_a_long_community_reupload(monkeypatch):
    async def installed():
        return [
            ("fredrezones55/Qwen3.5-9B-Uncensored-Aggressive:latest", "ollama"),
            ("qwen3.5:9b", "ollama"),
        ]

    monkeypatch.setattr(models, "_installed", installed)
    assert _run(models.pick_for_task("browse for cats"))[0] == "qwen3.5:9b"


def test_task_pick_keeps_a_deliberate_last_pick_when_it_fits(monkeypatch):
    async def installed():
        return [("batiai/qwen3.5-9b:latest", "ollama"), ("qwen3.5-coder:7b", "ollama")]

    monkeypatch.setattr(models, "_installed", installed)
    got, why = _run(models.pick_for_task("browse for cats", prefer="qwen3.5-coder:7b"))
    assert got == "qwen3.5-coder:7b"
    assert "last pick" in why


def test_task_pick_is_empty_when_nothing_matches(monkeypatch):
    async def installed():
        return [("someones/weird-model:latest", "ollama")]

    monkeypatch.setattr(models, "_installed", installed)
    assert _run(models.pick_for_task("browse for cats")) == ("", "")


def test_task_routing_beats_the_last_pick(monkeypatch):
    async def installed():
        return [("gemma4:e2b", "ollama"), ("llama3.1:8b", "ollama")]

    monkeypatch.setattr(models, "_installed", installed)
    got = _run(models.resolve_run_model(None, 2, {}, goal="browse for cats", last_pick="gemma4:e2b"))
    assert got[0] == "llama3.1:8b"


def test_task_routing_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("HARVIS_AGENT_TASK_MODELS", "0")

    async def installed():
        raise AssertionError("task routing ran while disabled")

    monkeypatch.setattr(models, "_installed", installed)
    got = _run(models.resolve_run_model(None, 2, {}, goal="browse for cats", last_pick="gemma4:e2b"))
    assert got == ("gemma4:e2b", "last picked in chat")


def test_auto_uses_last_pick(monkeypatch):
    async def boom(**_):  # the resolver must not even be asked
        raise AssertionError("resolver called")

    monkeypatch.setattr("plugins.models.resolver.resolve_or_describe", boom)
    monkeypatch.setenv("HARVIS_AGENT_TASK_MODELS", "0")
    got = _run(models.resolve_run_model(None, 2, {"model": None}, last_pick=" qwen3:4b "))
    assert got == ("qwen3:4b", "last picked in chat")


def test_auto_ignores_teammate_pick_and_falls_to_resolver(monkeypatch):
    monkeypatch.setenv("HARVIS_AGENT_TASK_MODELS", "0")
    async def fake(**kw):
        assert kw["user_id"] == 2
        return "llama3.1:8b", "user preference (openclaw_llm_config)"

    monkeypatch.setattr("plugins.models.resolver.resolve_or_describe", fake)
    got = _run(models.resolve_run_model(None, 2, {"model": "auto"}, last_pick="agent:other"))
    assert got == ("llama3.1:8b", "user preference (openclaw_llm_config)")


def test_nothing_installed_is_empty_not_an_exception(monkeypatch):
    monkeypatch.setenv("HARVIS_AGENT_TASK_MODELS", "0")
    async def fake(**_):
        return None, "no models available"

    monkeypatch.setattr("plugins.models.resolver.resolve_or_describe", fake)
    assert _run(models.resolve_run_model(None, 2, {})) == ("", "no model available")


def test_resolver_error_is_swallowed(monkeypatch):
    monkeypatch.setenv("HARVIS_AGENT_TASK_MODELS", "0")
    async def fake(**_):
        raise RuntimeError("db down")

    monkeypatch.setattr("plugins.models.resolver.resolve_or_describe", fake)
    assert _run(models.resolve_run_model(None, 2, {}))[0] == ""


def test_model_budget_is_bounded_and_positive():
    """The picker must never name a model this box cannot afford to load."""
    from plugins.agents.models import _model_budget_bytes

    budget = _model_budget_bytes()
    assert budget >= 1024 ** 3
    # 45% of RAM, capped by the env default (14 GB) — never the whole machine.
    assert budget <= 14 * 1024 ** 3


def test_oversized_ollama_tags_are_not_candidates(monkeypatch):
    """A 22 GB tag on a 32 GB box took the machine down; it must not be picked."""
    import plugins.agents.models as M

    async def _sizes():
        return {"huge:latest": 22 * 1024 ** 3, "small:latest": 5 * 1024 ** 3}

    async def _tags():
        return ["huge:latest", "small:latest"]

    monkeypatch.setattr(M, "_ollama_sizes", _sizes)
    monkeypatch.setattr(
        "plugins.models.resolver.list_ollama_models", _tags, raising=False
    )

    async def _no_nodes():
        return {}

    monkeypatch.setattr("plugins.inference_nodes.snapshot", _no_nodes, raising=False)
    names = [n for n, _ in _run(M._installed())]
    assert "small:latest" in names
    assert "huge:latest" not in names


def test_unknown_sizes_are_kept(monkeypatch):
    """No size data must not silently hide every model."""
    import plugins.agents.models as M

    async def _sizes():
        return {}

    async def _tags():
        return ["mystery:latest"]

    async def _no_nodes():
        return {}

    monkeypatch.setattr(M, "_ollama_sizes", _sizes)
    monkeypatch.setattr(
        "plugins.models.resolver.list_ollama_models", _tags, raising=False
    )
    monkeypatch.setattr("plugins.inference_nodes.snapshot", _no_nodes, raising=False)
    assert ("mystery:latest", "ollama") in _run(M._installed())
