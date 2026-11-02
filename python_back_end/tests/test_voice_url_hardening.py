"""Pentest hardening: client-named voice samples stay in the voice folder, the TTS service's
import calls need the internal token, web-fetch dials only the address it vetted, chat-link
fetches are guarded in every exposure mode, the vibe voice upload leaves no temp file."""
import asyncio
import os
import socket
import sys

import httpcore
import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice_paths  # noqa: E402
from plugins.hermes_ui import providers, sandbox  # noqa: E402
from research import safe_fetch  # noqa: E402
from tools import url_safety  # noqa: E402
from tts_system import security  # noqa: E402


# ─── F23: voice samples resolve under the voice folder only ───────────────────

@pytest.fixture
def voices(tmp_path, monkeypatch):
    root = tmp_path / "voices"
    root.mkdir()
    (root / "ada.wav").write_bytes(b"RIFF")
    outside = tmp_path / "secret.wav"
    outside.write_bytes(b"RIFF")
    monkeypatch.setenv("HARVIS_VOICE_DIR", str(root))
    return root, outside


def test_a_sample_inside_the_voice_folder_resolves(voices):
    root, _ = voices
    assert voice_paths.resolve_voice_prompt("ada.wav") == str(root.resolve() / "ada.wav")
    assert voice_paths.resolve_voice_prompt(str(root / "ada.wav")) == str(root.resolve() / "ada.wav")


@pytest.mark.parametrize("probe", ["../secret.wav", "/etc/passwd", "ada.wav\x00.txt", "", None, ".", "notes.txt", "missing.wav"])
def test_anything_else_resolves_to_nothing(voices, probe):
    assert voice_paths.resolve_voice_prompt(probe) is None


def test_an_absolute_path_outside_and_a_symlink_out_are_refused(voices):
    root, outside = voices
    assert voice_paths.resolve_voice_prompt(str(outside)) is None
    os.symlink(outside, root / "link.wav")
    assert voice_paths.resolve_voice_prompt("link.wav") is None


def test_job_queue_no_longer_treats_voice_id_as_a_path(voices):
    _, outside = voices
    assert voice_paths.resolve_voice_prompt(str(outside)) is None


# ─── F23/F24: TTS service guards ──────────────────────────────────────────────

def test_safe_child_keeps_ids_inside_the_library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    assert security.safe_child(root, "voice_ab12") == root / "voice_ab12"
    for bad in ["..", ".", "../x", "a/b", "", "..%2f", "a\x00b", "/etc"]:
        with pytest.raises(ValueError):
            security.safe_child(root, bad)
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", root / "hop")
    with pytest.raises(ValueError):
        security.safe_child(root, "hop")


def _import_client():
    app = FastAPI()

    @app.post("/rvc/voices/import", dependencies=[Depends(security.require_internal_token)])
    async def imp():
        return {"ok": True}

    return TestClient(app)


def test_rvc_import_refuses_everyone_when_no_token_is_configured(monkeypatch):
    for name in ("TTS_INTERNAL_TOKEN", "HARVIS_GATEWAY_TOKEN", "OPENCLAW_GATEWAY_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    client = _import_client()
    assert client.post("/rvc/voices/import").status_code == 403
    assert client.post("/rvc/voices/import", headers={"X-Internal-Token": ""}).status_code == 403


def test_rvc_import_needs_the_matching_token(monkeypatch):
    monkeypatch.setenv("TTS_INTERNAL_TOKEN", "s3cret-token")
    client = _import_client()
    assert client.post("/rvc/voices/import").status_code == 403
    assert client.post("/rvc/voices/import", headers={"X-Internal-Token": "nope"}).status_code == 403
    assert client.post("/rvc/voices/import", headers={"X-Internal-Token": "s3cret-token"}).status_code == 200
    assert client.post("/rvc/voices/import", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_the_server_gates_both_import_routes_and_loads_weights_only():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server = open(os.path.join(here, "tts_system", "server.py")).read()
    assert '@app.post("/rvc/voices/import", dependencies=[Depends(require_internal_token)])' in server
    assert '@app.post("/rvc/voices/import-url", dependencies=[Depends(require_internal_token)])' in server
    for rel in ("engines/rvc_engine.py", "engines/vibevoice_engine.py"):
        text = open(os.path.join(here, "tts_system", rel)).read()
        assert "weights_only=True" in text, rel


# ─── F21: web-fetch pins the vetted address ───────────────────────────────────

class _NoDial(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.dialled = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.dialled.append(host)
        raise httpcore.ConnectError("no network in tests")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("no network in tests")

    async def sleep(self, seconds):
        pass


def test_web_fetch_transport_dials_through_the_connect_time_guard():
    transport = url_safety._PublicOnlyTransport()
    assert isinstance(transport._inner._pool._network_backend, providers._GuardedBackend)


def test_a_name_that_turns_private_between_check_and_connect_is_not_dialled(monkeypatch):
    answers = iter([["93.184.216.34"], ["10.0.0.9"]])
    calls = []

    def getaddrinfo(host, port, *args, **kwargs):
        calls.append(host)
        ip = next(answers)[0]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    transport = url_safety._PublicOnlyTransport()
    dialler = _NoDial()
    transport._inner._pool._network_backend._inner = dialler

    async def go():
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("http://rebind.example/")

    with pytest.raises(HTTPException) as err:
        asyncio.run(go())
    assert err.value.status_code == 400
    assert len(calls) == 2          # the check, then the connect: the second answer was vetted too
    assert dialler.dialled == []    # and the private answer was never dialled


# ─── F21: a chat link is fetched through the guard in every mode ──────────────

def test_forced_guard_applies_on_a_local_install(monkeypatch):
    import plugins.exposure as exposure

    monkeypatch.setattr(exposure, "shared", lambda: False)
    assert safe_fetch.enabled() is False
    with safe_fetch.forced():
        assert safe_fetch.enabled() is True
    assert safe_fetch.enabled() is False


def test_chat_link_extraction_uses_the_guarded_fetcher_locally(monkeypatch):
    import plugins.exposure as exposure
    from research.extract import html_trafilatura

    monkeypatch.setattr(exposure, "shared", lambda: False)
    used = []

    def fake_fetch(url, **kw):
        used.append(url)
        return httpx.Response(200, text="<html>x</html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(safe_fetch, "fetch", fake_fetch)
    monkeypatch.setattr(html_trafilatura.requests, "get", lambda *a, **k: pytest.fail("unguarded requests.get"))
    with safe_fetch.forced():
        assert html_trafilatura.fetch_html("http://example.test/", "ua", 5) == "<html>x</html>"
    assert used == ["http://example.test/"]


# ─── /api/voice-transcribe leaves nothing behind ──────────────────────────────

def _vibe_client(monkeypatch, tmp_path, transcribe):
    from vibecoding import commands

    monkeypatch.setattr(commands.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(commands, "transcribe_audio", transcribe)
    app = FastAPI()
    app.include_router(commands.router)
    app.dependency_overrides[commands.get_current_user] = lambda: {"id": 7, "username": "u7"}
    return TestClient(app, raise_server_exceptions=False)


def test_voice_upload_is_removed_after_success(monkeypatch, tmp_path):
    seen = []

    def transcribe(path):
        seen.append(path)
        assert os.path.isfile(path) and os.path.dirname(path) != str(tmp_path)  # not loose in the shared root
        return {"text": " hello "}

    res = _vibe_client(monkeypatch, tmp_path, transcribe).post(
        "/api/voice-transcribe", files={"file": ("a.wav", b"RIFFxxxx", "audio/wav")})
    assert res.status_code == 200 and res.json()["transcription"] == "hello"
    assert not os.path.exists(seen[0]) and os.listdir(tmp_path) == []


def test_voice_upload_is_removed_when_transcription_fails(monkeypatch, tmp_path):
    def transcribe(path):
        raise RuntimeError("boom")

    res = _vibe_client(monkeypatch, tmp_path, transcribe).post(
        "/api/voice-transcribe", files={"file": ("a.wav", b"RIFFxxxx", "audio/wav")})
    assert res.status_code == 500
    assert os.listdir(tmp_path) == []


# ─── F25: a named pipe where the file should be cannot hang or be written ──────

def test_write_text_refuses_a_named_pipe(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "ROOT", str(tmp_path / "root"))
    base = sandbox.ensure_dir(7, "sess-1")
    os.mkfifo(os.path.join(base, "pipe"))
    with pytest.raises(sandbox.SandboxError):
        sandbox.write_text(7, "/sandbox/sess-1/workspace/pipe", "x")
