"""Contracts for Hermes UI custom-provider records."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui.providers import EndpointValidationError, normalize_endpoint, public_endpoint


class _Response:
    status_code = 200
    headers = {"content-type": "text/event-stream"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
        yield "data: [DONE]"


class _Client:
    sent: dict = {}

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def stream(self, _method, url, **kwargs):
        self.sent = {"url": url, **kwargs}
        type(self).sent = self.sent
        return _Response()


def test_normalize_endpoint_generates_a_safe_id_and_never_exposes_the_key():
    endpoint = normalize_endpoint({
        "name": "My local Ollama",
        "base_url": "http://host.docker.internal:11434/v1/",
        "model": "qwen3:4b",
        "models": ["qwen3:4b", "qwen3:4b", ""],
        "api_key": "super-secret",
    })

    assert endpoint["id"] == "my-local-ollama"
    assert endpoint["base_url"] == "http://host.docker.internal:11434/v1"
    assert endpoint["models"] == ["qwen3:4b"]

    visible = public_endpoint({**endpoint, "api_key_enc": "ciphertext"}, active_id=endpoint["id"])
    assert visible["is_current"] is True
    assert visible["has_api_key"] is True
    assert "api_key_enc" not in visible
    assert "super-secret" not in repr(visible)


@pytest.mark.asyncio
async def test_custom_endpoint_chat_never_forwards_the_harvis_token(monkeypatch):
    from plugins.hermes_ui import chat

    monkeypatch.setattr(chat.httpx, "AsyncClient", _Client)
    received = [item async for item in chat.stream_turn(
        "harvis-session-token", [{"role": "user", "content": "hello"}], "harvis-default",
        {"base_url": "http://ollama:11434/v1", "model": "qwen3:4b", "api_key": "endpoint-key"},
    )]

    assert received == [("text", "ok")]
    assert _Client.sent["url"] == "http://ollama:11434/v1/chat/completions"
    assert _Client.sent["headers"] == {"Authorization": "Bearer endpoint-key"}
    assert "harvis_mode" not in _Client.sent["json"]


def test_custom_endpoint_routes_exist_before_the_facade_catch_all():
    from plugins.hermes_ui.rest_settings import router

    paths = {route.path for route in router.routes}
    assert "/hermes-api/api/providers/custom-endpoints" in paths
    assert "/hermes-api/api/providers/custom-endpoints/validate" in paths
    assert "/hermes-api/api/providers/custom-endpoints/{endpoint_id}/activate" in paths


@pytest.mark.parametrize("url", ["", "ftp://localhost:11434", "http:///missing-host", "https://api.example.test/#fragment"])
def test_normalize_endpoint_rejects_unsafe_or_ambiguous_urls(url):
    with pytest.raises(EndpointValidationError):
        normalize_endpoint({"name": "Test", "base_url": url, "model": "model"})
