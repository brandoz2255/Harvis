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


class _Handshake:
    def __init__(self, **headers):
        self.headers = headers


def test_socket_refuses_a_cross_origin_handshake():
    from plugins.hermes_ui.ws import _origin_allowed

    # A sandbox preview on another port of the same machine must not ride the cookie.
    assert not _origin_allowed(_Handshake(origin="http://localhost:5173", host="localhost:9000"))
    assert not _origin_allowed(_Handshake(origin="https://evil.example", host="harvis.lan:9000"))


def test_socket_accepts_its_own_origin_and_non_browser_clients():
    from plugins.hermes_ui.ws import _origin_allowed

    assert _origin_allowed(_Handshake(origin="http://192.168.4.201:9000", host="192.168.4.201:9000"))
    assert _origin_allowed(_Handshake(origin="http://localhost:9000", host="backend:8000"))
    assert _origin_allowed(_Handshake(host="localhost:9000"))


def test_user_body_never_carries_the_jwt():
    from owui_compat.translate import harvis_user_to_owui

    body = harvis_user_to_owui({"id": 5, "username": "ada", "email": "a@x.test"}, expires_at=123)

    assert "token" not in body and "token_type" not in body
    assert body["expires_at"] == 123


@pytest.mark.asyncio
async def test_socket_ends_quietly_when_the_browser_vanished_mid_send(monkeypatch):
    import types

    from plugins.hermes_ui import ws as ws_mod

    monkeypatch.setattr(ws_mod, "decode_token_fast", lambda tok: {"sub": "3"})

    class GoneSocket:
        headers = {"host": "localhost:9000"}
        cookies = {"access_token": "t"}
        app = types.SimpleNamespace(state=types.SimpleNamespace(pg_pool=None))

        async def accept(self):
            pass

        async def send_text(self, text):
            raise RuntimeError("Unexpected ASGI message 'websocket.send'")

        async def receive_text(self):
            raise RuntimeError('WebSocket is not connected. Need to call "accept" first.')

    await ws_mod.hermes_ws(GoneSocket())  # must return, not raise
