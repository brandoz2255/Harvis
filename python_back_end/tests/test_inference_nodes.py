"""plugins.inference_nodes — registry parsing, the thinking policy, and resolution.

No network: ``probe`` is exercised by seeding its cache the way the Ollama-hosts
tests do, so what is under test is the contract (absent vs unknown, priority order,
URL ownership) and not a socket.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.inference_nodes import policy, probe, registry  # noqa: E402
from plugins.inference_nodes.types import NodeSpec, NodeState  # noqa: E402


@pytest.fixture(scope="module")
def loop():
    lp = asyncio.new_event_loop()
    yield lp
    lp.close()


@pytest.fixture(autouse=True)
def _clean_probe(monkeypatch):
    probe._cache.clear()
    probe._cache_at = 0.0
    probe._lock = asyncio.Lock()
    monkeypatch.delenv(registry.ENV_VAR, raising=False)
    monkeypatch.delenv("HARVIS_NODE_THINKING", raising=False)
    yield
    probe._cache.clear()
    probe._cache_at = 0.0


def _seed(*states: NodeState) -> None:
    for st in states:
        probe._cache[st.spec.name] = st
    probe._cache_at = time.time()


# ── registry ────────────────────────────────────────────────────────────────

def test_parse_env_shorthand(monkeypatch):
    monkeypatch.setenv("FT_TOKEN", "s3cret")
    raw = (
        "freetoken=http://host.docker.internal:1919/v1|dialect=openai|label=FreeToken (laptop)"
        "|hw=RTX 5070 8GB|token_env=FT_TOKEN, rig=http://10.0.0.5:8000|priority=10"
    )
    specs = registry.parse_env(raw)
    assert [s.name for s in specs] == ["freetoken", "rig"]
    ft, rig = specs
    assert ft.base_url == "http://host.docker.internal:1919"      # /v1 stripped
    assert ft.chat_url == "http://host.docker.internal:1919/v1/chat/completions"
    assert ft.label == "FreeToken (laptop)"
    assert ft.hardware == "RTX 5070 8GB"
    assert ft.token == "s3cret"
    assert ft.headers()["Authorization"] == "Bearer s3cret"
    assert ft.public()["has_token"] is True and "token" not in ft.public()
    assert rig.priority == 10 and rig.label == "rig" and rig.token == ""


def test_parse_env_json_and_bad_entries():
    raw = '[{"name":"a","base_url":"http://a:1","hardware":"x"},{"name":"bad","base_url":"ftp://no"}]'
    specs = registry.parse_env(raw)
    assert [s.name for s in specs] == ["a"]
    assert registry.parse_env("") == [] and registry.parse_env(None) == []
    assert registry.parse_env("nonsense") == []
    assert registry.parse_env("x=http://ok:1,junk,y=not-a-url") and len(registry.parse_env("x=http://ok:1,junk,y=not-a-url")) == 1


def test_spec_validation():
    with pytest.raises(ValueError):
        NodeSpec(name="n", base_url="http://x", dialect="grpc")
    with pytest.raises(ValueError):
        NodeSpec(name="", base_url="http://x")


def test_configured_nodes_env_only_sorted(loop, monkeypatch):
    monkeypatch.setenv(registry.ENV_VAR, "b=http://b:1|priority=5, a=http://a:1|priority=5, off=http://c:1|enabled=false")
    specs = loop.run_until_complete(registry.configured_nodes(None))
    assert [s.name for s in specs] == ["a", "b"]


# ── policy ──────────────────────────────────────────────────────────────────

def test_policy_auto_turns_thinking_off_for_tools_and_small_budgets():
    assert policy.shape_body({"messages": [], "tools": [{}]})["chat_template_kwargs"] == {"enable_thinking": False}
    assert policy.shape_body({"messages": [], "max_tokens": 64})["chat_template_kwargs"] == {"enable_thinking": False}
    assert policy.shape_body({"messages": [], "metadata": {"task": "title_generation"}})["chat_template_kwargs"] == {"enable_thinking": False}


def test_policy_auto_leaves_plain_chat_to_the_model():
    out = policy.shape_body({"messages": [], "stream": True})
    assert "chat_template_kwargs" not in out


def test_policy_respects_explicit_caller_choice(monkeypatch):
    body = {"messages": [], "tools": [{}], "chat_template_kwargs": {"enable_thinking": True}}
    assert policy.shape_body(body)["chat_template_kwargs"] == {"enable_thinking": True}
    assert "chat_template_kwargs" not in policy.shape_body({"messages": [], "reasoning_effort": "none"})
    monkeypatch.setenv("HARVIS_NODE_THINKING", "off")
    assert policy.shape_body({"messages": []})["chat_template_kwargs"] == {"enable_thinking": False}
    monkeypatch.setenv("HARVIS_NODE_THINKING", "on")
    assert policy.shape_body({"messages": [], "tools": [{}]})["chat_template_kwargs"] == {"enable_thinking": True}


def test_policy_drops_ollama_only_keys_and_maps_max_completion_tokens():
    body = {"messages": [], "options": {"num_ctx": 1}, "keep_alive": "5m", "format": "json",
            "max_completion_tokens": 2000, "stream_options": {"include_usage": True}}
    out = policy.shape_body(body)
    assert "options" not in out and "keep_alive" not in out and "format" not in out
    assert out["max_tokens"] == 2000 and "max_completion_tokens" not in out
    assert out["stream_options"] == {"include_usage": True}      # OpenAI key, kept
    assert body["options"] == {"num_ctx": 1}                      # input untouched


# ── probe / resolve ─────────────────────────────────────────────────────────

def test_resolve_present_absent_unknown(loop):
    ft = NodeSpec(name="ft", base_url="http://ft:1919", label="FreeToken")
    rig = NodeSpec(name="rig", base_url="http://rig:8000", priority=10)
    _seed(
        NodeState(spec=ft, reachable=True, models={"Qwen3.6-35B"}, ctx={"Qwen3.6-35B": 262144}),
        NodeState(spec=rig, reachable=False, error="ConnectError", last_good_models={"gemma4:26b"}),
    )
    st, why = loop.run_until_complete(probe.resolve("Qwen3.6-35B"))
    assert st is not None and st.spec.name == "ft" and why == "ft"
    st, why = loop.run_until_complete(probe.resolve("gemma4:26b"))
    assert st is None and why == "unknown:rig"
    st, why = loop.run_until_complete(probe.resolve("nope"))
    assert st is None and why == "absent"
    assert loop.run_until_complete(probe.resolve("")) == (None, "absent")


def test_resolve_prefers_lower_priority(loop):
    a = NodeSpec(name="a", base_url="http://a:1", priority=100)
    b = NodeSpec(name="b", base_url="http://b:1", priority=1)
    _seed(NodeState(spec=a, reachable=True, models={"m"}), NodeState(spec=b, reachable=True, models={"m"}))
    st, why = loop.run_until_complete(probe.resolve("m"))
    assert why == "b"


def test_resolve_with_no_nodes(loop):
    _seed()   # sets the timestamp with an empty cache → no probe, no nodes
    assert loop.run_until_complete(probe.resolve("m")) == (None, "no-nodes")


def test_unreachable_models_and_node_for_url(loop):
    ft = NodeSpec(name="ft", base_url="http://ft:1919/")
    down = NodeSpec(name="down", base_url="http://down:1")
    _seed(
        NodeState(spec=ft, reachable=True, models={"x"}),
        NodeState(spec=down, reachable=False, last_good_models={"x", "y"}),
    )
    assert loop.run_until_complete(probe.unreachable_models()) == [("y", probe._cache["down"])]
    assert probe.node_for_url("http://ft:1919/v1/chat/completions") is ft
    assert probe.node_for_url("http://ft:1919") is ft
    assert probe.node_for_url("http://ft:19190/v1/chat/completions") is None
    assert probe.node_for_url("http://host.docker.internal:11434/v1/chat/completions") is None
    assert probe.node_for_url("") is None


def test_node_for_url_falls_back_to_env_before_any_probe(monkeypatch):
    monkeypatch.setenv(registry.ENV_VAR, "ft=http://ft:1919")
    assert probe.node_for_url("http://ft:1919/v1/chat/completions").name == "ft"


# ── task-gen on a node (title / tags fallback while Ollama cannot load) ─────────


def _reachable(name, models, priority=100):
    spec = NodeSpec(name=name, base_url=f"http://{name}:1919", priority=priority)
    st = NodeState(spec=spec, reachable=True, models=set(models))
    st.last_good_models = set(models)
    return st


def test_node_complete_uses_first_reachable_node_thinking_off(loop, monkeypatch):
    from plugins.inference_nodes import taskgen

    probe._cache.update({
        "down": NodeState(spec=NodeSpec(name="down", base_url="http://down:1", priority=1)),
        "ft": _reachable("ft", {"Qwen3.6-35B-A3B-NVFP4"}, priority=50),
    })
    probe._cache_at = time.time()
    seen = {}

    async def fake_post(spec, body, timeout):
        seen["spec"] = spec
        seen["body"] = body
        return "  Docker Layer Caching\n"

    monkeypatch.setattr(taskgen, "_post", fake_post)
    out = loop.run_until_complete(taskgen.complete("Message: docker caching\nTitle:", max_tokens=24))
    assert out == "Docker Layer Caching"
    assert seen["spec"].name == "ft"
    assert seen["body"]["model"] == "Qwen3.6-35B-A3B-NVFP4"
    assert seen["body"]["stream"] is False
    assert seen["body"]["max_tokens"] == 24
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_node_complete_none_when_no_node_answers(loop, monkeypatch):
    from plugins.inference_nodes import taskgen

    probe._cache.update({"ft": _reachable("ft", {"m"})})
    probe._cache_at = time.time()

    async def boom(spec, body, timeout):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(taskgen, "_post", boom)
    assert loop.run_until_complete(taskgen.complete("x")) is None
    assert loop.run_until_complete(taskgen.complete("   ")) is None


def test_node_complete_none_with_no_nodes(loop):
    from plugins.inference_nodes import taskgen

    probe._cache_at = time.time()  # empty cache, fresh TTL → no probe, no nodes
    assert loop.run_until_complete(taskgen.complete("x")) is None


def test_kv_capacity_caps_the_paper_context():
    assert probe.kv_capacity({"kv": {"total_pages": 4098, "page_size": 1}}) == 4098
    assert probe.kv_capacity({"kv": {"total_pages": 256, "page_size": 16}}) == 4096
    assert probe.kv_capacity({"kv": {}}) is None
    assert probe.kv_capacity(None) is None
    assert probe.kv_capacity({"kv": {"total_pages": 0}}) is None


def test_policy_turns_thinking_off_when_the_cache_leaves_no_room(monkeypatch):
    monkeypatch.setenv("HARVIS_NODE_CHARS_PER_TOKEN", "1")
    big = {"model": "m", "messages": [{"role": "user", "content": "x" * 3300}]}
    small = {"model": "m", "messages": [{"role": "user", "content": "x" * 300}]}
    assert policy.decide_thinking(big, "auto", ctx_cap=4098) is False
    assert policy.decide_thinking(small, "auto", ctx_cap=4098) is None
    assert policy.decide_thinking(big, "auto", ctx_cap=None) is None
    # An explicit caller choice still wins.
    big["chat_template_kwargs"] = {"enable_thinking": True}
    assert policy.decide_thinking(big, "auto", ctx_cap=4098) is None


def test_shape_body_reads_the_probed_cache_size(monkeypatch):
    monkeypatch.setenv("HARVIS_NODE_CHARS_PER_TOKEN", "1")
    spec = NodeSpec(name="ft", base_url="http://ft:1919")
    st = NodeState(spec=spec, reachable=True, models={"m"}, ctx={"m": 4098})
    probe._cache["ft"] = st
    body = {"model": "m", "messages": [{"role": "user", "content": "x" * 3300}]}
    out = policy.shape_body(body, spec)
    assert out["chat_template_kwargs"] == {"enable_thinking": False}
    st.ctx["m"] = 262144
    out = policy.shape_body(body, spec)
    assert "chat_template_kwargs" not in out
