"""taskgen on a PIN-paired node: dialect ``ollama`` with a bearer token. Titles and tags
used to come only from OpenAI-dialect nodes, so a paired computer never wrote any."""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.inference_nodes import taskgen  # noqa: E402
from plugins.inference_nodes.types import NodeSpec, NodeState  # noqa: E402

TOKEN = "tok-taskgen-SECRET"


def run(coro):
    lp = asyncio.new_event_loop()
    try:
        return lp.run_until_complete(coro)
    finally:
        lp.close()


def node(name, dialect, models, *, token="", priority=100, reachable=True):
    spec = NodeSpec(name=name, base_url=f"http://{name}.test:11437", dialect=dialect,
                    token=token, priority=priority)
    return NodeState(spec=spec, reachable=reachable, models=set(models))


@pytest.fixture
def wire(monkeypatch):
    """Install node states and a fake server; returns the list of requests it saw."""
    seen: list[httpx.Request] = []
    reply = {"status": 200, "content": "Garden Tomato Tips"}

    def install(*states):
        async def _snapshot(*a, **k):
            return {s.spec.name: s for s in states}
        monkeypatch.setattr(taskgen, "snapshot", _snapshot)

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if reply["status"] != 200:
            return httpx.Response(reply["status"], json={"error": "x"})
        return httpx.Response(200, json={"choices": [{"message": {"content": reply["content"]}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(taskgen.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return install, seen, reply


def test_a_paired_ollama_node_writes_the_title_with_its_bearer_token(wire):
    install, seen, _ = wire
    install(node("lab", "ollama", ["qwen3:8b"], token=TOKEN))
    out = run(taskgen.complete("Title this chat", system="Be brief", max_tokens=16))
    assert out == "Garden Tomato Tips"
    req = seen[0]
    assert req.url.path == "/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    body = json.loads(req.content)
    assert body["model"] == "qwen3:8b" and body["stream"] is False and body["max_tokens"] == 16
    assert body["reasoning_effort"] == "none"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_openai_nodes_still_work_and_do_not_get_the_ollama_field(wire):
    install, seen, _ = wire
    install(node("ft", "openai", ["Qwen3.6-35B"]))
    assert run(taskgen.complete("hi")) == "Garden Tomato Tips"
    body = json.loads(seen[0].content)
    assert "reasoning_effort" not in body
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "authorization" not in seen[0].headers


def test_priority_order_decides_between_dialects(wire):
    install, seen, _ = wire
    install(node("a", "ollama", ["m1"], token=TOKEN, priority=50),
            node("b", "openai", ["m2"], priority=10))
    run(taskgen.complete("hi"))
    assert seen[0].url.host == "b.test"


def test_embedding_models_are_never_asked_for_a_title(wire):
    install, seen, _ = wire
    install(node("lab", "ollama", ["bge-m3:latest", "nomic-embed-text:latest", "qwen3:8b"], token=TOKEN))
    run(taskgen.complete("hi"))
    assert json.loads(seen[0].content)["model"] == "qwen3:8b"
    seen.clear()
    install(node("lab", "ollama", ["nomic-embed-text:latest"], token=TOKEN))
    assert run(taskgen.complete("hi")) is None and not seen


def test_requested_model_is_used_when_the_node_has_it(wire):
    install, seen, _ = wire
    install(node("lab", "ollama", ["a:1b", "z:9b"], token=TOKEN))
    run(taskgen.complete("hi", model="z:9b"))
    assert json.loads(seen[0].content)["model"] == "z:9b"


def test_unreachable_node_is_skipped_and_failure_is_none(wire):
    install, seen, reply = wire
    install(node("down", "ollama", ["m"], token=TOKEN, reachable=False))
    assert run(taskgen.complete("hi")) is None and not seen
    install(node("lab", "ollama", ["m"], token=TOKEN))
    reply["status"] = 401
    assert run(taskgen.complete("hi")) is None


def test_a_think_block_is_stripped_from_the_title(wire):
    install, _, reply = wire
    reply["content"] = "<think>hmm, a title...</think>\nGarden Tomato Tips"
    install(node("lab", "ollama", ["m"], token=TOKEN))
    assert run(taskgen.complete("hi")) == "Garden Tomato Tips"
    reply["content"] = "<think>only thinking</think>"
    assert run(taskgen.complete("hi")) is None
