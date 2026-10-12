"""Ollama cloud models (``kimi-k2.6:cloud``, ``gpt-oss:120b-cloud``) forward prompts to
ollama.com, so Harvis leaves them out of every model list and refuses them as chat
targets unless HARVIS_ALLOW_CLOUD_MODELS=1. No network: HTTP is a MockTransport."""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owui_compat import ollama_hosts as oh  # noqa: E402
from plugins.inference_nodes import probe  # noqa: E402
from plugins.inference_nodes.types import NodeSpec  # noqa: E402

TAGS = {"models": [
    {"name": "qwen3:8b", "model": "qwen3:8b", "size": 5},
    {"name": "kimi-k2.6:cloud", "model": "kimi-k2.6:cloud"},
    {"name": "gpt-oss:120b-cloud", "model": "gpt-oss:120b-cloud"},
    {"name": "newmodel:latest", "model": "newmodel:latest", "remote_host": "https://ollama.com:443"},
    {"name": "cloudy:latest", "model": "cloudy:latest"},
    {"name": "hf.co/acme/cloud-thing:Q4", "model": "hf.co/acme/cloud-thing:Q4"},
]}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv(oh.CLOUD_MODELS_ENV, raising=False)
    oh._cache.clear()
    oh._cache_at = 0.0
    probe._cache.clear()
    probe._cache_at = 0.0
    yield
    oh._cache.clear()
    probe._cache.clear()


def run(coro):
    lp = asyncio.new_event_loop()
    try:
        return lp.run_until_complete(coro)
    finally:
        lp.close()


def mock_httpx(monkeypatch, module, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize("name,cloud", [
    ("kimi-k2.6:cloud", True), ("gpt-oss:120b-cloud", True), ("Qwen3-Coder:480B-Cloud", True),
    ("qwen3:8b", False), ("qwen3", False), ("cloudy:latest", False),
    ("hf.co/acme/cloud-thing:Q4", False), ("llama3:cloud-ish", False), ("", False), (None, False),
])
def test_is_cloud_model_by_tag(name, cloud):
    assert oh.is_cloud_model(name) is cloud


def test_remote_host_on_a_tags_entry_marks_it_cloud():
    assert oh.is_cloud_model("newmodel:latest", {"remote_host": "https://ollama.com:443"})
    assert not oh.is_cloud_model("newmodel:latest", {"remote_host": ""})


def test_env_opt_in_unhides(monkeypatch):
    assert oh.is_hidden_cloud_model("kimi-k2.6:cloud")
    for v in ("1", "true", "YES"):
        monkeypatch.setenv(oh.CLOUD_MODELS_ENV, v)
        assert oh.cloud_models_allowed() and not oh.is_hidden_cloud_model("kimi-k2.6:cloud")
    monkeypatch.setenv(oh.CLOUD_MODELS_ENV, "0")
    assert oh.is_hidden_cloud_model("kimi-k2.6:cloud")


def test_drop_cloud_handles_strings_and_tag_dicts():
    assert oh.drop_cloud(["a:1b", "x:cloud"]) == ["a:1b"]
    kept = oh.drop_cloud(TAGS["models"])
    assert [m["name"] for m in kept] == ["qwen3:8b", "cloudy:latest", "hf.co/acme/cloud-thing:Q4"]
    assert oh.drop_cloud(None) == [] and oh.drop_cloud([5]) == [5]


def test_cloud_refusal_sentence_names_the_model_and_the_switch(monkeypatch):
    msg = oh.cloud_refusal("kimi-k2.6:cloud")
    assert "kimi-k2.6:cloud" in msg and oh.CLOUD_MODELS_ENV in msg and "ollama.com" in msg
    assert oh.cloud_refusal("qwen3:8b") is None
    monkeypatch.setenv(oh.CLOUD_MODELS_ENV, "1")
    assert oh.cloud_refusal("kimi-k2.6:cloud") is None


def _handler(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/api/tags":
        return httpx.Response(200, json=TAGS)
    return httpx.Response(404)


def test_ollama_host_probe_leaves_cloud_tags_out(monkeypatch):
    mock_httpx(monkeypatch, oh, _handler)
    spec = oh.HostSpec(oh.LOCAL, "http://ollama.test:11434", "Ollama")
    st = run(oh._probe(spec, 2.0))
    assert st.reachable
    assert st.tags == {"qwen3:8b", "cloudy:latest", "hf.co/acme/cloud-thing:Q4"}
    assert "kimi-k2.6:cloud" not in st.order and "kimi-k2.6:cloud" not in st.last_good_tags
    # and nothing about a hidden model can be routed to
    assert not st.has("kimi-k2.6:cloud")


def test_ollama_host_probe_keeps_cloud_tags_when_opted_in(monkeypatch):
    monkeypatch.setenv(oh.CLOUD_MODELS_ENV, "1")
    mock_httpx(monkeypatch, oh, _handler)
    st = run(oh._probe(oh.HostSpec(oh.LOCAL, "http://ollama.test:11434", "Ollama"), 2.0))
    assert "kimi-k2.6:cloud" in st.tags and "gpt-oss:120b-cloud" in st.tags


def test_node_probe_ollama_dialect_leaves_cloud_tags_out(monkeypatch):
    mock_httpx(monkeypatch, probe, _handler)
    spec = NodeSpec(name="lab", base_url="http://lab.test:11437", dialect="ollama", token="t")
    st = run(probe._probe(spec, 2.0))
    assert st.models == {"qwen3:8b", "cloudy:latest", "hf.co/acme/cloud-thing:Q4"}
    assert "kimi-k2.6:cloud" not in st.last_good_models


def test_node_probe_openai_dialect_leaves_cloud_ids_out(monkeypatch):
    def handler(req):
        if req.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen3:8b"}, {"id": "kimi-k2.6:cloud"}]})
        return httpx.Response(404)
    mock_httpx(monkeypatch, probe, handler)
    spec = NodeSpec(name="n", base_url="http://n.test:8000", dialect="openai")
    assert run(probe._probe(spec, 2.0)).models == {"qwen3:8b"}


def test_a_cloud_model_is_not_routable_through_the_hosts(monkeypatch):
    mock_httpx(monkeypatch, oh, _handler)
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.test:11434")
    monkeypatch.delenv(oh.HOSTS_ENV, raising=False)
    monkeypatch.delenv("DESKTOP_OLLAMA_URL", raising=False)
    assert run(oh.resolve("kimi-k2.6:cloud", force=True)) == (None, "absent")
    base, _ = run(oh.resolve("qwen3:8b"))
    assert base == "http://ollama.test:11434"
    avail = run(oh.available())
    assert "kimi-k2.6:cloud" not in avail


# ── the chat path ───────────────────────────────────────────────────────────

def test_proxy_chat_refuses_a_cloud_model_with_400(monkeypatch):
    from workspace import model_proxy

    class Req:      # never reached: the refusal comes before any routing
        pass

    body = {"model": "kimi-k2.6:cloud", "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(HTTPException) as ei:
        run(model_proxy.execute_chat_completion(Req(), body))
    assert ei.value.status_code == 400
    assert "kimi-k2.6:cloud" in ei.value.detail and oh.CLOUD_MODELS_ENV in ei.value.detail


def test_proxy_chat_does_not_refuse_with_the_opt_in(monkeypatch):
    from workspace import model_proxy

    monkeypatch.setenv(oh.CLOUD_MODELS_ENV, "1")
    reached = []

    async def _route(model_name):
        reached.append(model_name)
        raise RuntimeError("routing reached")

    monkeypatch.setattr(model_proxy, "_resolve_route", _route)
    body = {"model": "kimi-k2.6:cloud", "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(Exception) as ei:
        run(model_proxy.execute_chat_completion(object(), body))
    assert not (isinstance(ei.value, HTTPException) and ei.value.status_code == 400
                and oh.CLOUD_MODELS_ENV in str(ei.value.detail))
