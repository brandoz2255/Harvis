"""Notebooks' install check (embedder_status) and the Messaging page's first-run
steps. The model server is faked with httpx.MockTransport; nothing opens a socket."""
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from notebooks import embedder_status as es  # noqa: E402
from plugins.hermes_ui.messaging_gateway import GATEWAY_START_COMMAND  # noqa: E402
from plugins.hermes_ui.messaging_steps import setup_steps  # noqa: E402


def status_with(monkeypatch, handler):
    real = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(es.httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("OLLAMA_URL", "http://model-server:11434")
    return asyncio.run(es.embedder_status())


def tags(*names):
    return lambda request: httpx.Response(200, json={"models": [{"name": n} for n in names]})


def test_is_embedder_matches_dedicated_embedders_only():
    assert es.is_embedder("nomic-embed-text:latest")
    assert es.is_embedder("mxbai-embed-large")
    assert es.is_embedder("all-minilm:22m")
    assert not es.is_embedder("gemma4:e2b")
    assert not es.is_embedder("llama3.1:8b")


def test_chat_models_only_is_not_installed_with_size(monkeypatch):
    st = status_with(monkeypatch, tags("gemma4:e2b"))
    assert st["state"] == "not_installed"
    assert st["download_mb"] == 274
    assert st["install_tag"] == es.EMBEDDER_TAG
    assert "274 MB" in st["reason"]


def test_any_embedder_counts_as_ready(monkeypatch):
    st = status_with(monkeypatch, tags("gemma4:e2b", "mxbai-embed-large:latest"))
    assert st["state"] == "ready"
    assert st["model"] == "mxbai-embed-large:latest"


def test_non_ollama_server_is_unsupported_not_broken(monkeypatch):
    st = status_with(monkeypatch, lambda request: httpx.Response(404))
    assert st["state"] == "unsupported"


def test_down_server_is_unreachable(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused")

    st = status_with(monkeypatch, refuse)
    assert st["state"] == "unreachable"


def test_legacy_discord_steps_point_at_env_and_name_the_user():
    steps = setup_steps("discord", supported=True, legacy_discord=True, gateway_up=False, owner=3)
    text = " ".join(steps)
    assert "DISCORD_BOT_TOKEN=" in text and "DISCORD_DEFAULT_USER_ID=3" in text
    assert "docker compose up -d backend" in text
    assert "Message Content Intent" in text


def test_gateway_platform_steps_include_start_command_only_when_down():
    down = setup_steps("telegram", supported=True, legacy_discord=False, gateway_up=False, owner=3)
    up = setup_steps("telegram", supported=True, legacy_discord=False, gateway_up=True, owner=3)
    assert any(GATEWAY_START_COMMAND in s for s in down)
    assert not any(GATEWAY_START_COMMAND in s for s in up)


def test_unsupported_platform_has_no_steps():
    assert setup_steps("qq", supported=False, legacy_discord=False, gateway_up=True, owner=3) == []
