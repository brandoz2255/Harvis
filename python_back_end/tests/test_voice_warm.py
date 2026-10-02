"""The voice call keeps its model loaded: which model, which Ollama, how often."""

import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins import people  # noqa: E402
from plugins.hermes_ui import providers, voice_warm  # noqa: E402
from plugins.people.controls import Admission  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://local-ollama:11434")
    monkeypatch.delenv("DESKTOP_OLLAMA_URL", raising=False)
    monkeypatch.delenv("HARVIS_VOICE_KEEP_ALIVE", raising=False)
    monkeypatch.setattr(voice_warm, "_last", {})

    async def no_endpoint(pool, uid):
        return None

    async def admit(pool, uid, model, count=True):
        assert count is False  # a warm-up never spends one of the person's messages
        return Admission(True, model=model or "")

    monkeypatch.setattr(providers, "resolve_active_endpoint", no_endpoint)
    monkeypatch.setattr(people, "admit_turn", admit)


def _integrations(monkeypatch, default):
    from owui_compat import capabilities

    async def read(pool, uid):
        return {}, default

    monkeypatch.setattr(capabilities, "_read_integrations", read)


@pytest.mark.asyncio
async def test_the_session_model_is_warmed():
    assert await voice_warm.voice_model(None, 1, "gemma4:e2b") == "gemma4:e2b"


@pytest.mark.asyncio
async def test_no_session_model_falls_back_to_the_saved_default(monkeypatch):
    _integrations(monkeypatch, "llama3.2:3b")
    assert await voice_warm.voice_model(None, 1, "") == "llama3.2:3b"
    assert await voice_warm.voice_model(None, 1, "moa:team") == "llama3.2:3b"


def _auto(monkeypatch, model):
    from workspace import model_proxy

    async def resolve():
        return model

    monkeypatch.setattr(model_proxy, "resolve_auto_model", resolve)


@pytest.mark.asyncio
async def test_no_pick_anywhere_warms_what_auto_resolves_to(monkeypatch):
    _integrations(monkeypatch, None)
    _auto(monkeypatch, "hermes3:3b")
    assert await voice_warm.voice_model(None, 1, "") == "hermes3:3b"


@pytest.mark.asyncio
async def test_nothing_to_warm_for_an_own_endpoint_a_cloud_model_or_no_model(monkeypatch):
    _integrations(monkeypatch, None)
    _auto(monkeypatch, "")
    assert await voice_warm.voice_model(None, 1, "") == ""

    from owui_compat import cloud_chat
    monkeypatch.setattr(cloud_chat, "is_cloud_chat_model", lambda m: m == "claude-x")
    assert await voice_warm.voice_model(None, 1, "claude-x") == ""

    async def endpoint(pool, uid):
        return {"base_url": "https://api.example.test/v1", "model": "m"}

    monkeypatch.setattr(providers, "resolve_active_endpoint", endpoint)
    assert await voice_warm.voice_model(None, 1, "gemma4:e2b") == ""


@pytest.mark.asyncio
async def test_a_blocked_person_gets_no_warm_up(monkeypatch):
    async def blocked(pool, uid, model, count=True):
        return Admission(False, "blocked")

    monkeypatch.setattr(people, "admit_turn", blocked)
    assert await voice_warm.voice_model(None, 1, "gemma4:e2b") == ""


def _client(monkeypatch, answers, seen):
    real = httpx.AsyncClient

    def handler(request):
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        seen.append((str(request.url), request.content))
        return httpx.Response(answers.get(request.url.host, 200), json={})

    monkeypatch.setattr(voice_warm.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
async def test_warm_loads_on_the_native_api_with_the_keep_alive(monkeypatch):
    seen = []
    _client(monkeypatch, {}, seen)
    assert await voice_warm.warm("gemma4:e2b") is True
    url, body = seen[0]
    assert url == "http://local-ollama:11434/api/generate"
    assert b'"keep_alive":"30m"' in body.replace(b" ", b"")
    assert b'"model":"gemma4:e2b"' in body.replace(b" ", b"")


@pytest.mark.asyncio
async def test_a_model_missing_locally_is_tried_on_the_desktop_ollama(monkeypatch):
    monkeypatch.setenv("DESKTOP_OLLAMA_URL", "http://desktop-ollama:11434/")
    seen = []
    _client(monkeypatch, {"local-ollama": 404}, seen)
    assert await voice_warm.warm("big:70b") is True
    assert [u for u, _ in seen] == ["http://local-ollama:11434/api/generate",
                                    "http://desktop-ollama:11434/api/generate"]


@pytest.mark.asyncio
async def test_schedule_warms_once_a_minute_unless_a_turn_just_ran(monkeypatch):
    calls = []

    async def warm(model):
        calls.append(model)
        return True

    monkeypatch.setattr(voice_warm, "warm", warm)

    async def drain():
        while voice_warm._tasks:
            await asyncio.gather(*list(voice_warm._tasks))

    voice_warm.schedule(None, 1, "gemma4:e2b")
    await drain()
    voice_warm.schedule(None, 1, "gemma4:e2b")  # the call reopened within the minute
    await drain()
    assert calls == ["gemma4:e2b"]
    voice_warm.rewarm_after_turn(None, 1, "gemma4:e2b")
    await drain()
    assert calls == ["gemma4:e2b", "gemma4:e2b"]


@pytest.mark.asyncio
async def test_a_failed_warm_up_is_swallowed(monkeypatch):
    async def warm(model):
        raise RuntimeError("ollama exploded")

    monkeypatch.setattr(voice_warm, "warm", warm)
    voice_warm.schedule(None, 1, "gemma4:e2b")
    while voice_warm._tasks:
        await asyncio.gather(*list(voice_warm._tasks))


@pytest.mark.asyncio
async def test_a_model_held_longer_already_is_not_cut_back(monkeypatch):
    seen = []
    real = httpx.AsyncClient

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [
                {"name": "gemma4:e2b", "expires_at": "2319-01-12T18:33:44.004731374Z"}]})
        return httpx.Response(200, json={})

    monkeypatch.setattr(voice_warm.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert await voice_warm.warm("gemma4:e2b") is True
    assert seen == ["/api/ps"]  # no load request: Ollama keeps it forever already
    seen.clear()
    assert await voice_warm.warm("llama3.2:3b") is True  # not loaded: load it
    assert seen == ["/api/ps", "/api/generate"]


def test_expiry_parsing_takes_a_local_offset_and_a_short_window():
    from datetime import datetime, timedelta, timezone
    soon = (datetime.now(timezone(timedelta(hours=-7))) + timedelta(minutes=2)).isoformat()
    ps = {"models": [{"name": "m", "expires_at": soon}]}
    assert voice_warm._held_long_enough(ps, "m", 60) is True
    assert voice_warm._held_long_enough(ps, "m", 1800) is False
    assert voice_warm._window_seconds("30m") == 1800
    assert voice_warm._window_seconds("-1") < 0
