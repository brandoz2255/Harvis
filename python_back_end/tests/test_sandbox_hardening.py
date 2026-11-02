"""Pentest hardening for the chat sandbox: terminal Origin check, the GPU grant and link
secret living outside the runner's mount, no writes through planted links, hardened
workspace-terminal containers."""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import rest_sandbox, sandbox  # noqa: E402

CWD = "/sandbox/sess-1/workspace"


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path / "root"))
    monkeypatch.delenv("HARVIS_SANDBOX_ENABLED", raising=False)
    return tmp_path / "root"


# ─── F17 / F30: Origin check on the terminal socket ──────────────────────────

def _client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(rest_sandbox, "decode_token_fast", lambda tok: {"sub": "7"} if tok == "good" else None)

    async def opened(*a):
        raise sandbox.SandboxError("stop here")

    monkeypatch.setattr(rest_sandbox, "_open_shell", opened)
    app = FastAPI()
    app.include_router(rest_sandbox.router)
    return TestClient(app)


def test_terminal_socket_refuses_a_foreign_origin(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    client = _client(monkeypatch)
    client.cookies.set("access_token", "good")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/hermes-api/api/terminal/ws?cwd={CWD}",
                                      headers={"origin": "http://localhost:5173", "host": "localhost:9000"}):
            pass
    assert exc.value.code == 4403


def test_terminal_socket_accepts_the_harvis_origin(monkeypatch):
    client = _client(monkeypatch)
    client.cookies.set("access_token", "good")
    with client.websocket_connect(f"/hermes-api/api/terminal/ws?cwd={CWD}",
                                  headers={"origin": "http://localhost:9000", "host": "localhost:9000"}) as ws:
        assert json.loads(ws.receive_text()) == {"t": "e", "message": "stop here"}


# ─── F25: nothing the runner plants makes the backend write elsewhere ────────

def test_link_secret_and_gpu_grant_are_outside_the_runner_mount(root):
    sandbox.ensure_dir(7, "sess-1")
    sandbox.set_gpu(7, "sess-1", True)
    session = root / "u7" / "sess-1"
    assert not any(p.name in ("proxy-salt", "gpu", "user-md-mirror.json") for p in session.rglob("*"))
    assert (root / ".meta" / "u7" / "sess-1" / "proxy-salt").is_file()
    assert (root / ".meta" / "u7" / "sess-1" / "gpu").is_file()


def test_a_symlink_planted_as_the_prefix_note_is_not_followed(root, tmp_path):
    base = sandbox.ensure_dir(7, "sess-1")
    victim = tmp_path / "victim"
    victim.write_text("keep me")
    note = os.path.join(base, ".harvis", "app-url-prefix")
    os.remove(note)
    os.symlink(victim, note)
    sandbox.ensure_dir(7, "sess-1")
    assert victim.read_text() == "keep me"


def test_a_symlinked_notes_folder_is_replaced_not_followed(root, tmp_path):
    base = sandbox.ensure_dir(7, "sess-1")
    victim_dir = tmp_path / "inbox"
    victim_dir.mkdir()
    os.rename(os.path.join(base, ".harvis"), os.path.join(base, "old"))
    os.symlink(victim_dir, os.path.join(base, ".harvis"))
    sandbox.ensure_dir(7, "sess-1")
    sandbox.set_gpu(7, "sess-1", True)
    assert list(victim_dir.iterdir()) == []
    assert not os.path.islink(os.path.join(base, ".harvis"))
    assert os.path.isfile(os.path.join(base, ".harvis", "app-url-prefix"))


def test_a_hard_link_planted_as_the_prefix_note_is_not_truncated(root, tmp_path):
    base = sandbox.ensure_dir(7, "sess-1")
    victim = tmp_path / "victim"
    victim.write_text("keep me")
    note = os.path.join(base, ".harvis", "app-url-prefix")
    os.remove(note)
    os.link(victim, note)
    sandbox.ensure_dir(7, "sess-1")
    assert victim.read_text() == "keep me"


def test_a_gpu_marker_written_by_the_runner_grants_nothing(root):
    base = sandbox.ensure_dir(7, "sess-1")
    open(os.path.join(base, ".harvis", "gpu"), "w").close()
    assert not sandbox.gpu_wanted(7, "sess-1")
    assert not sandbox.gpu_granted(base)
    sandbox.set_gpu(7, "sess-1", True)
    assert sandbox.gpu_granted(base)
    assert not sandbox.gpu_granted(str(root / "elsewhere"))


def test_file_writers_refuse_the_harvis_folder(root, tmp_path):
    base = sandbox.ensure_dir(7, "sess-1")
    with pytest.raises(sandbox.SandboxError):
        sandbox.write_text(7, CWD + "/.harvis/gpu", "")
    with pytest.raises(sandbox.SandboxError):
        sandbox.write_text(7, CWD + "/.harvis/app-url-prefix", "x")
    os.symlink(os.path.join(base, ".harvis"), os.path.join(base, "alias"))
    with pytest.raises(sandbox.SandboxError):
        sandbox.write_text(7, CWD + "/alias/gpu", "")
    assert not os.path.exists(os.path.join(base, ".harvis", "gpu"))
    assert sandbox.write_text(7, CWD + "/ok.txt", "fine")["ok"]


def test_deleting_a_sandbox_removes_its_meta_folder(root):
    sandbox.ensure_dir(7, "sess-1")
    sandbox.delete_dir(7, "sess-1")
    assert not (root / ".meta" / "u7" / "sess-1").exists()


# ─── F20: the GPU toggle is the admin's ──────────────────────────────────────

def _gpu_app(monkeypatch, user_id, shared_host):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth_optimized import get_current_user_optimized

    monkeypatch.setenv("HARVIS_EXPOSURE", "lan" if shared_host else "local")
    monkeypatch.setenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")

    async def available():
        return True

    class _Mgr:
        async def drop_isolated(self, key):
            return True

    async def mgr():
        return _Mgr()

    monkeypatch.setattr(rest_sandbox, "gpu_available", available)
    monkeypatch.setattr(rest_sandbox, "_manager", mgr)
    app = FastAPI()
    app.include_router(rest_sandbox.router)
    app.dependency_overrides[get_current_user_optimized] = lambda: {"id": user_id}
    return TestClient(app)


def test_a_non_admin_cannot_grant_the_gpu_on_a_shared_host(monkeypatch):
    client = _gpu_app(monkeypatch, 2, shared_host=True)
    r = client.post("/hermes-api/api/sandbox/gpu", json={"session": "sess-1", "on": True})
    assert r.status_code == 403
    assert not sandbox.gpu_wanted(2, "sess-1")


def test_a_non_admin_cannot_grant_the_gpu_even_when_build_space_is_open(monkeypatch):
    monkeypatch.setenv("HARVIS_BUILD_SPACE_ACCESS", "everyone")
    client = _gpu_app(monkeypatch, 2, shared_host=True)
    assert client.post("/hermes-api/api/sandbox/gpu", json={"session": "sess-1", "on": True}).status_code == 403


def test_the_admin_and_a_local_owner_can_grant_the_gpu(monkeypatch):
    assert _gpu_app(monkeypatch, 1, True).post(
        "/hermes-api/api/sandbox/gpu", json={"session": "sess-1", "on": True}).json() == {"ok": True, "gpu": True}
    assert _gpu_app(monkeypatch, 2, False).post(
        "/hermes-api/api/sandbox/gpu", json={"session": "sess-2", "on": True}).json() == {"ok": True, "gpu": True}


# ─── F19 / F20 on the container: what actually gets spawned ──────────────────

class _Containers:
    def __init__(self):
        self.runs = []

    def get(self, name):
        from docker.errors import NotFound
        raise NotFound("none")

    def run(self, image, command=None, **kw):
        self.runs.append((image, command, kw))
        return object()


class _Client:
    def __init__(self):
        self.containers = _Containers()

    class networks:
        @staticmethod
        def get(_n):
            return object()


def _manager():
    from workspace.terminal_container import WorkspaceTerminalManager

    m = WorkspaceTerminalManager.__new__(WorkspaceTerminalManager)
    m._client = _Client()
    m._terminals = {}
    m._own_mounts = [{"Destination": "/", "Source": "/host"}]
    return m


def test_workspace_terminal_container_is_unprivileged():
    m = _manager()
    asyncio.run(m._spawn("ws-1"))
    runs = m._client.containers.runs
    main = [r for r in runs if r[1] == ["sh", "-c", "tail -f /dev/null"]][0][2]
    assert main["user"] == "1001:1001"
    assert main["cap_drop"] == ["ALL"] and "cap_add" not in main
    assert main["security_opt"] == ["no-new-privileges:true"]
    assert main["pids_limit"] > 0
    chown = [r for r in runs if r[1] and r[1][0] == "chown"][0][2]
    assert chown["user"] == "0" and chown["network_mode"] == "none" and chown["cap_add"] == ["CHOWN"]


def test_an_old_root_terminal_container_is_replaced():
    m = _manager()
    removed = []

    class _Old:
        status = "running"
        attrs = {"Config": {"User": ""}, "HostConfig": {}}

        def remove(self, force=False):
            removed.append(force)

    m._client.containers.get = lambda name: _Old()
    asyncio.run(m._spawn("ws-1"))
    assert removed == [True]
    assert m._client.containers.runs


def test_terminal_network_comes_from_the_environment(monkeypatch):
    import importlib

    import workspace.terminal_container as tc

    monkeypatch.setenv("HARVIS_TERMINAL_NETWORK", "ws-term-net")
    try:
        assert importlib.reload(tc)._NETWORK == "ws-term-net"
    finally:
        monkeypatch.delenv("HARVIS_TERMINAL_NETWORK")
        importlib.reload(tc)


def _spawn_isolated(root, grant, plant):
    m = _manager()
    base = sandbox.ensure_dir(7, "sess-1")
    if plant:
        open(os.path.join(base, ".harvis", "gpu"), "w").close()
    if grant:
        sandbox.set_gpu(7, "sess-1", True)

    async def host_path_of(p):
        return p

    m.host_path_of = host_path_of
    asyncio.run(m._spawn_isolated("vc:x", sandbox.runner_key(7, "sess-1"), base))
    return m._client.containers.runs[-1][2]


def test_a_runner_planted_gpu_marker_does_not_get_it_the_gpu(root):
    assert "device_requests" not in _spawn_isolated(root, grant=False, plant=True)


def test_an_admin_granted_gpu_is_one_device_not_all(root):
    kw = _spawn_isolated(root, grant=True, plant=False)
    (req,) = kw["device_requests"]
    assert req.count == 1
