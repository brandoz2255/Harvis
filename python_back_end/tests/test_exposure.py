"""Shared-server rules (HARVIS_EXPOSURE): the mode switch, the admin-only gate
for code-running routes, and the sign-up hooks.

A local install must behave exactly as before, so each area tests that too.
The experimental Cloudflare Tunnel has its own tests (test_tunnel.py).
"""
import asyncio
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from plugins.exposure import gate, mode, signup  # noqa: E402
from plugins.exposure.routes import create_exposure_router  # noqa: E402

STRONG = "s" * 40


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("HARVIS_EXPOSURE", "HARVIS_BUILD_SPACE_ACCESS", "HARVIS_SETUP_CODE",
                "HARVIS_CF_ACCESS_TEAM_DOMAIN", "HARVIS_CF_ACCESS_AUD", "JWT_SECRET",
                "HARVIS_CF_ACCESS_ALLOWED_EMAILS", "HARVIS_BIND_ADDR_PUBLIC", "KUBERNETES_SERVICE_HOST"):
        monkeypatch.delenv(key, raising=False)


def run(coro):
    return asyncio.run(coro)


def _client():
    app = FastAPI()

    def deny():
        raise HTTPException(401)

    app.include_router(create_exposure_router(get_current_user=deny, require_admin=deny))
    return TestClient(app)


# ─── mode ────────────────────────────────────────────────────────────────────


def test_unset_is_local_and_changes_nothing():
    assert mode.exposure() == "local"
    assert not mode.shared()
    assert mode.build_space_open_to_all()
    assert mode.startup_problems() == []


@pytest.mark.parametrize("bind", ["0.0.0.0", "192.168.1.20", "::"])
def test_local_on_a_network_bound_port_is_shared(monkeypatch, bind):
    monkeypatch.setenv("HARVIS_EXPOSURE", "local")
    monkeypatch.setenv("HARVIS_BIND_ADDR_PUBLIC", bind)
    assert mode.exposure() == "lan" and mode.shared()


@pytest.mark.parametrize("bind", ["127.0.0.1", "localhost", "::1", "127.0.0.2"])
def test_local_on_loopback_stays_local(monkeypatch, bind):
    monkeypatch.setenv("HARVIS_BIND_ADDR_PUBLIC", bind)
    assert mode.exposure() == "local"


def test_unset_on_kubernetes_is_shared(monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.43.0.1")
    assert mode.exposure() == "lan"


def test_unknown_value_fails_toward_locked_down(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "Public")
    assert mode.exposure() == "lan"
    assert mode.shared()


def test_shared_keeps_code_for_admins_unless_opened(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert not mode.build_space_open_to_all()
    monkeypatch.setenv("HARVIS_BUILD_SPACE_ACCESS", "everyone")
    assert mode.build_space_open_to_all()


@pytest.mark.parametrize("secret", [None, "key", "changeme", "short-but-random"])
def test_shared_refuses_a_guessable_signing_secret(monkeypatch, secret):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    if secret is not None:
        monkeypatch.setenv("JWT_SECRET", secret)
    assert any("JWT_SECRET" in p for p in mode.startup_problems())


def test_exposure_card_is_admin_only():
    assert _client().get("/api/exposure").status_code == 401


# ─── admin-only gate ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("path,gated", [
    ("/api/workspace/launch", True),
    ("/api/kubectl/pending", True),
    ("/hermes-api/api/terminal/open", True),
    ("/api/adaptive/spaces/abc/repo/write", True),
    ("/api/adaptive/spaces/abc/plan", False),
    ("/hermes-api/api/sandbox", True),  # bare form of a gated prefix
    ("/api/workspace", True),
    ("/api/workspaces", False),
    ("/kubectl/exec", False),  # OpenClaw pods; has its own gateway token
    ("/api/chat", False),
    ("/api/tunnel/verify", False),
    ("/api/remote/ssh/hosts/3/exec", True),
    ("/api/openclaw/tasks", True),
    ("/api/owui/openclaw/sync/apply", True),
    ("/api/artifacts/0b6c/build", True),
    ("/api/artifacts/0b6c/build/stop", True),
    ("/api/artifacts/0b6c/download", False),
    ("/api/artifacts/generate", False),
])
def test_admin_only_paths(path, gated):
    assert gate.admin_only_path(path) is gated


@pytest.mark.parametrize("exposure,user_id,status", [
    ("lan", 2, 403),     # shared server, not an admin
    ("tunnel", 2, 403),
    ("lan", 1, 400),     # the admin gets past the gate (to the unknown-node check)
    (None, 2, 400),      # local install: unchanged for everyone
])
def test_cookbook_download_is_admin_only_when_shared(monkeypatch, exposure, user_id, status):
    import importlib
    cookbook = importlib.import_module("cookbook.router")
    if exposure:
        monkeypatch.setenv("HARVIS_EXPOSURE", exposure)
    else:
        monkeypatch.delenv("HARVIS_EXPOSURE", raising=False)
    monkeypatch.delenv("HARVIS_BUILD_SPACE_ACCESS", raising=False)
    import owui_compat.authz as authz
    monkeypatch.setattr(authz, "_admin_user_ids", lambda: {1})
    monkeypatch.setattr(cookbook.config, "node_or_400",
                        lambda node: (_ for _ in ()).throw(HTTPException(400, "unknown node")))
    app = FastAPI()
    app.include_router(cookbook.router)
    app.dependency_overrides[cookbook.get_current_user_from_request] = lambda: {"id": user_id}
    r = TestClient(app).post("/api/cookbook/download", json={"node": "x", "model": "m"})
    assert r.status_code == status
    if status == 403:
        assert "downloading models" in r.json()["detail"]


def _gated_app(monkeypatch, user_ids, admins=frozenset({1})):
    import plugins.people.gate as people_gate
    monkeypatch.setattr(people_gate, "_user_ids", lambda scope: set(user_ids))
    monkeypatch.setattr(gate, "_admin_user_ids", lambda: set(admins))
    app = FastAPI()

    @app.get("/api/workspace/launch")
    def launch():
        return {"ok": True}

    @app.get("/api/chat")
    def chat():
        return {"ok": True}

    app.add_middleware(gate.BuildSpaceGate)
    return TestClient(app)


def test_gate_is_inert_on_a_local_install(monkeypatch):
    assert _gated_app(monkeypatch, {2}).get("/api/workspace/launch").status_code == 200


def test_gate_stops_non_admins_on_a_shared_server(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    c = _gated_app(monkeypatch, {2})
    r = c.get("/api/workspace/launch")
    assert r.status_code == 403 and "admins" in r.json()["detail"]
    assert c.get("/api/chat").status_code == 200


def test_gate_lets_admins_through_and_asks_strangers_to_sign_in(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    assert _gated_app(monkeypatch, {1}).get("/api/workspace/launch").status_code == 200
    assert _gated_app(monkeypatch, set()).get("/api/workspace/launch").status_code == 401


def test_gate_opens_when_the_operator_says_everyone(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    monkeypatch.setenv("HARVIS_BUILD_SPACE_ACCESS", "everyone")
    assert _gated_app(monkeypatch, {2}).get("/api/workspace/launch").status_code == 200


@pytest.mark.parametrize("method,path,open_", [
    ("GET", "/api/workspace/providers", True),
    ("GET", "/api/workspace/history", True),
    ("GET", "/api/workspace/stream/ws-1", True),
    ("GET", "/api/workspace/run/ws-1/events", True),
    ("GET", "/api/workspace/artifact/a1/raw", True),
    ("POST", "/api/workspace/cancel/ws-1", True),
    ("POST", "/api/workspace/launch", False),
    ("POST", "/api/workspace/run/ws-1/rerun", False),
    ("POST", "/api/workspace/run/ws-1/action/x/approve", False),
    ("GET", "/api/workspace/run/ws-1/repo", False),
    ("GET", "/api/workspace/fs/browse", False),
    ("GET", "/api/workspace/vibecode/sessions", False),
    ("GET", "/api/workspace/stream/ws-1/launch", False),
    ("POST", "/api/workspace/stream/ws-1", False),
    (None, "/api/workspace/stream/ws-1", False),  # a WebSocket has no method
    ("GET", "/api/workspace/providers\n", False),
    ("GET", "/api/artifacts/0b6c/build", True),  # build status of one's own artifact
    ("POST", "/api/artifacts/0b6c/build", False),
])
def test_users_keep_their_own_runs_on_a_shared_server(method, path, open_):
    assert gate.open_to_users(method, path) is open_


def test_gate_serves_a_non_admins_image_run_but_not_a_launch(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "tunnel")
    import plugins.people.gate as people_gate
    monkeypatch.setattr(people_gate, "_user_ids", lambda scope: {2})
    monkeypatch.setattr(gate, "_admin_user_ids", lambda: {1})
    app = FastAPI()

    @app.get("/api/workspace/stream/{ws_id}")
    def stream(ws_id: str):
        return {"ok": ws_id}

    @app.post("/api/workspace/launch")
    def launch():
        return {"ok": True}

    app.add_middleware(gate.BuildSpaceGate)
    c = TestClient(app)
    assert c.get("/api/workspace/stream/ws-1").status_code == 200
    assert c.post("/api/workspace/launch").status_code == 403


def test_build_space_allowed_for_launches_without_a_request(monkeypatch):
    monkeypatch.setattr(gate, "_admin_user_ids", lambda: {1})
    assert gate.build_space_allowed(2)
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert gate.build_space_allowed("1") and not gate.build_space_allowed(2)
    assert not gate.build_space_allowed(None)


# ─── sign-up ─────────────────────────────────────────────────────────────────


def test_signup_rules_skip_a_local_install():
    run(signup.before_signup("anyone@x.org", {}))


def test_shared_first_admin_needs_no_setup_code(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    assert not hasattr(signup, "first_signup_allowed")
    assert mode.describe()["setup_code_required"] is False
    monkeypatch.setenv("HARVIS_SETUP_CODE", "abc123")
    assert mode.describe()["setup_code_required"] is True


# ── the old unauthenticated vibe shell ──────────────────────────────────────

def test_legacy_vibe_shell_is_disabled():
    commands = pytest.importorskip("vibecoding.commands")
    app = FastAPI()
    app.include_router(commands.router)
    client = TestClient(app)
    assert client.post("/api/vibe/command", json={"command": "id"}).status_code == 410
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws/vibe") as sock:
            sock.send_json({"command": "id"})
            sock.receive_json()
    assert client.post("/api/vibe-coding", json={"message": "hi"}).status_code in (401, 403)


def test_voice_transcribe_needs_a_sign_in():
    commands = pytest.importorskip("vibecoding.commands")
    app = FastAPI()
    app.include_router(commands.router)
    files = {"file": ("a.wav", b"RIFF", "audio/wav")}
    assert TestClient(app).post("/api/voice-transcribe", files=files).status_code in (401, 403)


# ─── the tunnel stays out ────────────────────────────────────────────────────

@pytest.mark.parametrize("exposure", ["", "local", "lan"])
def test_without_a_tunnel_no_tunnel_code_loads(exposure):
    """The exposure card, the startup check and the sign-in hooks never import
    plugins.tunnel unless a tunnel mode is set."""
    script = (
        "import asyncio, sys\n"
        "from plugins.exposure import describe, signup, startup_problems\n"
        "card = describe(); startup_problems()\n"
        "asyncio.run(signup.before_signup('a@x.org', {'cf-access-jwt-assertion': 'x'}))\n"
        "asyncio.run(signup.before_login('a@x.org', {'cf-access-jwt-assertion': 'x'}))\n"
        "assert 'plugins.tunnel' not in sys.modules, sorted(m for m in sys.modules if 'tunnel' in m)\n"
        "assert card['tunnel'] is False and 'cloudflare_access' not in card\n"
    )
    env = {**os.environ, "HARVIS_EXPOSURE": exposure, "JWT_SECRET": STRONG}
    r = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]


def test_lan_card_has_no_tunnel_fields(monkeypatch):
    monkeypatch.setenv("HARVIS_EXPOSURE", "lan")
    monkeypatch.setenv("HARVIS_SETUP_CODE", "code-value-123")
    monkeypatch.setenv("JWT_SECRET", STRONG)
    card = mode.describe()
    assert card["tunnel"] is False and "cloudflare_access" not in card
    assert "code-value-123" not in repr(card) and STRONG not in repr(card)
