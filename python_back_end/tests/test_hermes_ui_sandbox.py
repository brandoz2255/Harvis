"""Each chat's sandbox: virtual paths stay inside the caller's own folder, the
files pane's /api/fs/* calls, and the terminal WebSocket's frame protocol."""

import json
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.hermes_ui import rest_sandbox, sandbox, sessions  # noqa: E402

CWD = "/sandbox/sess-1/workspace"


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path))
    monkeypatch.delenv("HARVIS_SANDBOX_ENABLED", raising=False)
    return tmp_path


# ─── paths ───────────────────────────────────────────────────────────────────

def test_virtual_path_maps_into_the_users_own_folder(root):
    sid, real, inner = sandbox.resolve(7, CWD + "/src/app.py", create=True)
    assert sid == "sess-1"
    assert real == os.path.join(os.path.realpath(root), "u7", "sess-1", "src", "app.py")
    assert inner == "/workspace/src/app.py"
    assert sandbox.resolve(7, CWD)[2] == "/workspace"


@pytest.mark.parametrize("bad", [
    "/etc/passwd", "/sandbox/sess-1", "/sandbox/sess-1/other", "/sandbox/../u8/workspace",
    CWD + "/../../u8/sess-1/workspace", CWD + "/./x", "/sandbox/bad id/workspace", "",
])
def test_paths_outside_a_sandbox_are_refused(bad):
    with pytest.raises(sandbox.SandboxError):
        sandbox.resolve(7, bad)


def test_a_symlink_pointing_out_is_refused(root):
    base = root / "u7" / "sess-1"
    base.mkdir(parents=True)
    (base / "escape").symlink_to(root)
    with pytest.raises(sandbox.SandboxError):
        sandbox.resolve(7, CWD + "/escape/u8")


def test_another_users_session_id_only_reaches_your_own_folder(root):
    (root / "u8" / "sess-1").mkdir(parents=True)
    (root / "u8" / "sess-1" / "secret.txt").write_text("theirs")
    assert sandbox.list_dir(7, CWD) == {"entries": []}


def test_off_switch(monkeypatch):
    monkeypatch.setenv("HARVIS_SANDBOX_ENABLED", "false")
    assert sandbox.virtual_cwd("sess-1") is None
    with pytest.raises(sandbox.SandboxError):
        sandbox.resolve(7, CWD)


def test_sessions_report_the_sandbox_as_their_cwd():
    s = sessions.Live(id="sess-1", user_id=7)
    assert sessions.runtime_info(s)["cwd"] == CWD


# ─── files ───────────────────────────────────────────────────────────────────

def test_list_read_write_and_git_root(root):
    base = root / "u7" / "sess-1"
    (base / "repo" / ".git").mkdir(parents=True)
    (base / "repo" / "README.md").write_text("# hi")
    (base / "b.png").write_bytes(b"\x89PNG\x00\x00")

    listing = sandbox.list_dir(7, CWD)["entries"]
    assert [e["name"] for e in listing] == ["repo", "b.png"]  # folders first
    assert listing[0] == {"name": "repo", "isDirectory": True, "path": CWD + "/repo"}

    assert sandbox.read_text(7, CWD + "/repo/README.md")["content"] == "# hi"
    assert sandbox.read_text(7, CWD + "/b.png")["binary"] is True
    assert sandbox.read_data_url(7, CWD + "/b.png")["dataUrl"].startswith("data:image/png;base64,")

    sandbox.write_text(7, CWD + "/repo/notes.txt", "saved")
    assert (base / "repo" / "notes.txt").read_text() == "saved"
    with pytest.raises(sandbox.SandboxError):
        sandbox.write_text(7, CWD + "/missing/notes.txt", "x")

    assert sandbox.git_root(7, CWD + "/repo/README.md") == {"root": CWD + "/repo"}
    assert sandbox.git_root(7, CWD) == {"root": None}


def test_fs_routes_turn_refusals_into_400s():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err:
        rest_sandbox._guard(sandbox.list_dir, 7, "/etc")
    assert err.value.status_code == 400


# ─── terminal ────────────────────────────────────────────────────────────────

class _Api:
    def __init__(self):
        self.resized = []

    def exec_resize(self, exec_id, height, width):
        self.resized.append((height, width))

    def exec_inspect(self, exec_id):
        return {"ExitCode": 0}


class _State:
    last_used_at = 0.0


def _client(monkeypatch, opened):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(rest_sandbox, "decode_token_fast", lambda tok: {"sub": "7"} if tok == "good" else None)
    app = FastAPI()
    app.include_router(rest_sandbox.router)
    monkeypatch.setattr(rest_sandbox, "_open_shell", opened)
    return TestClient(app)


def test_terminal_relays_keys_output_and_resize(monkeypatch):
    shell, ours = socket.socketpair()
    api = _Api()
    seen = {}

    async def opened(user_id, cwd, cols, rows):
        seen.update(user_id=user_id, cwd=cwd, cols=cols, rows=rows)
        return None, _State(), api, "exec-1", ours

    client = _client(monkeypatch, opened)
    with client.websocket_connect(f"/hermes-api/api/terminal/ws?cwd={CWD}&cols=100&rows=30",
                                  cookies={"access_token": "good"}) as ws:
        assert json.loads(ws.receive_text()) == {"t": "ready"}
        assert seen == {"user_id": 7, "cwd": CWD, "cols": 100, "rows": 30}

        ws.send_text(json.dumps({"t": "i", "d": "ls\n"}))
        assert shell.recv(100) == b"ls\n"

        shell.sendall("héllo\r\n".encode())
        assert json.loads(ws.receive_text()) == {"t": "o", "d": "héllo\r\n"}

        ws.send_text(json.dumps({"t": "r", "c": 120, "r": 40}))
        shell.close()  # the shell exits
        assert json.loads(ws.receive_text()) == {"t": "x", "code": 0}
    assert (40, 120) in api.resized


def test_terminal_reports_a_sandbox_that_cannot_start(monkeypatch):
    async def opened(*a):
        raise sandbox.SandboxError("Docker isn't reachable")

    client = _client(monkeypatch, opened)
    with client.websocket_connect(f"/hermes-api/api/terminal/ws?cwd={CWD}", cookies={"access_token": "good"}) as ws:
        assert json.loads(ws.receive_text()) == {"t": "e", "message": "Docker isn't reachable"}


def test_terminal_needs_a_signed_in_user(monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    async def opened(*a):
        raise AssertionError("must not open a shell")

    client = _client(monkeypatch, opened)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/hermes-api/api/terminal/ws?cwd={CWD}") as ws:
            ws.receive_text()


# ─── the chat's agent works in the same sandbox ──────────────────────────────

def test_bridge_resolves_the_chat_sandbox_inside_the_users_folder(root):
    from owui_compat.workspace_bridge import _chat_sandbox

    box = _chat_sandbox({"harvis_sandbox_session": "sess-1"}, 7)
    assert box["workspace_path"] == os.path.join(str(root), "u7", "sess-1")
    assert box["session_id"] == sandbox.runner_key(7, "sess-1")
    assert sandbox.app_prefix(7, "sess-1") in box["note"]
    assert box["session_id"].startswith("hs-u7-")
    assert os.path.isdir(box["workspace_path"])
    assert _chat_sandbox({}, 7) is None                                      # OWUI chats: unchanged
    assert _chat_sandbox({"harvis_sandbox_session": "../u8"}, 7) is None     # refused, not escaped


def test_orchestrated_run_uses_the_sandbox_folder_and_runner(monkeypatch, root):
    import asyncio as aio
    import importlib

    from workspace.orchestration import orchestrator
    # The module, not the APIRouter that workspace/__init__.py re-exports under the same name.
    wr = importlib.import_module("workspace.workspace_router")

    async def noop(*a, **k):
        return None
    for name in ("_db_create_run", "_db_save_artifact", "_db_complete_run", "_db_set_run_repo"):
        monkeypatch.setattr(wr, name, noop)

    seen = {}

    class Runner:
        async def run(self, **kw):
            seen.update(kw)
            return
            yield  # pragma: no cover — an async generator that yields nothing

    class Iso:
        def __init__(self, **kw):
            pass

        async def create_workspace_for_agent(self, *a, **k):
            raise AssertionError("a sandboxed run must not get a scratch dir")

        async def cleanup(self, path):
            raise AssertionError("a sandboxed run must never wipe the chat's folder")

    monkeypatch.setattr(orchestrator, "SubAgentRunner", Runner)
    monkeypatch.setattr(orchestrator, "WorkspaceIsolationManager", Iso)
    box = {"workspace_path": str(root / "u7" / "sess-1"), "session_id": sandbox.runner_key(7, "sess-1"),
           "note": "SANDBOX NOTE"}

    async def go():
        return [ev async for ev in orchestrator.run_orchestrated(
            "clone the repo", [], model_name="m", pool=None, parent_workspace_id="w1",
            user_id=7, single_agent=True, uniform_model=True, sandbox=box)]
    aio.run(go())
    assert seen["workspace_path"] == box["workspace_path"]
    assert seen["session_id"] == box["session_id"]   # → exec_isolated in the chat's hardened runner
    assert seen["task"].startswith("SANDBOX NOTE")


@pytest.mark.parametrize("text, mode", [
    ("install ComfyUI", "agent"),
    ("Please install pinokio in my sandbox", "agent"),
    ("hey harvis, can you set up https://github.com/x/y and run it", "agent"),
    ("clone the repo and start it", "agent"),
    ("how do I install python on windows?", None),
    ("what does setup.py do", None),
    ("just answer: can you install things?", "chat"),
])
def test_an_install_instruction_asks_for_an_agent_run(text, mode):
    from plugins.hermes_ui import chat
    assert chat.requested_mode(text) == mode


# ─── app links, GPU switch, size, delete ─────────────────────────────────────

def test_runner_names_are_per_user_and_never_collide():
    long_a, long_b = "x" * 60 + "a", "x" * 60 + "b"
    assert sandbox.container_name(7, long_a) != sandbox.container_name(7, long_b)
    assert sandbox.container_name(7, "s") != sandbox.container_name(8, "s")
    assert len(sandbox.container_name(123456, long_a)) <= len("harvis-vc-run-") + 40


def test_app_links_verify_and_die_with_the_sandbox(root):
    sandbox.ensure_dir(7, "sess-1")
    prefix = sandbox.app_prefix(7, "sess-1")
    cap = prefix.rsplit("/", 1)[1]
    assert sandbox.verify_cap(cap) == (7, "sess-1")
    assert (root / "u7" / "sess-1" / ".harvis" / "app-url-prefix").read_text().strip() == prefix

    assert sandbox.verify_cap(cap.replace("7.", "8.", 1)) is None          # another user
    assert sandbox.verify_cap(cap[:-1] + ("0" if cap[-1] != "0" else "1")) is None  # forged sig
    assert sandbox.verify_cap("junk") is None

    sandbox.delete_dir(7, "sess-1")
    assert sandbox.verify_cap(cap) is None
    sandbox.ensure_dir(7, "sess-1")                                          # a fresh sandbox
    assert sandbox.verify_cap(cap) is None                                   # gets a new secret


def test_gpu_switch_and_usage(root):
    assert not sandbox.gpu_wanted(7, "sess-1")
    sandbox.set_gpu(7, "sess-1", True)
    assert sandbox.gpu_wanted(7, "sess-1")
    sandbox.set_gpu(7, "sess-1", False)
    assert not sandbox.gpu_wanted(7, "sess-1")
    (root / "u7" / "sess-1" / "big.bin").write_bytes(b"x" * 100_000)
    assert sandbox.usage_bytes(7, "sess-1") >= 100_000


def test_listening_ports_are_parsed_from_proc_net():
    from plugins.hermes_ui.rest_sandbox import parse_listening
    proc = """  sl  local_address rem_address   st
   0: 00000000:1EAA 00000000:0000 0A 00000000:00000000
   1: 0100007F:1F90 00000000:0000 0A 00000000:00000000
   2: 0100007F:1F91 0100007F:C350 01 00000000:00000000
   0: 00000000000000000000000000000000:1F40 00000000000000000000000000000000:0000 0A 0"""
    assert parse_listening(proc) == [
        {"port": 7850, "public": True}, {"port": 8000, "public": True}, {"port": 8080, "public": False}]


def test_app_proxy_strips_credentials_and_sandboxes_the_page(monkeypatch, root):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from plugins.hermes_ui import rest_sandbox_apps as apps

    sandbox.ensure_dir(7, "sess-1")
    cap = sandbox.app_prefix(7, "sess-1").rsplit("/", 1)[1]
    seen = {}

    def upstream(request: httpx.Request):
        seen.update(url=str(request.url), headers=dict(request.headers))
        return httpx.Response(200, headers={"set-cookie": "a=b", "x-frame-options": "DENY",
                                            "content-type": "text/html"},
                              stream=httpx.ByteStream(b"<h1>app</h1>"))  # streamed, like a real upstream
    monkeypatch.setattr(apps, "_client", httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    app = FastAPI()
    app.include_router(apps.router)
    client = TestClient(app)

    r = client.get(f"{sandbox.APP_PREFIX}/{cap}/7860/assets/x.js?v=1",
                   headers={"cookie": "access_token=SECRET", "authorization": "Bearer SECRET"})
    assert r.status_code == 200 and r.text == "<h1>app</h1>"
    assert seen["url"] == f"http://{sandbox.container_name(7, 'sess-1')}:7860/assets/x.js?v=1"
    assert "cookie" not in seen["headers"] and "authorization" not in seen["headers"]
    assert r.headers["content-security-policy"].startswith("sandbox ")
    assert "allow-same-origin" not in r.headers["content-security-policy"]
    assert "set-cookie" not in r.headers and "x-frame-options" not in r.headers

    assert client.get(f"{sandbox.APP_PREFIX}/{cap}/7860", follow_redirects=False).status_code == 307
    assert client.get(f"{sandbox.APP_PREFIX}/{cap}/22/").status_code == 404        # blocked port
    assert client.get(f"{sandbox.APP_PREFIX}/{cap[:-2]}xx/7860/").status_code == 404  # bad link
