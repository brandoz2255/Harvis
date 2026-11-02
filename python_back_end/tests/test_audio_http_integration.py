"""Owner-bound audio over REAL HTTP: uvicorn serving main.app on 127.0.0.1,
httpx on the other side of a genuine socket — no ASGI transport shortcuts.

Runs fully offline (the suite is executed in a `docker run --network none`
container; loopback still works there). The TTS model is mocked at
main.safe_generate_speech_optimized, so no torch, no model files, and no
database are needed — every dependency that would touch one is overridden or
fails closed fast (DATABASE_URL points at a closed loopback port).
"""
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

# Fail-closed-fast infrastructure before main.py reads its environment.
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db")
os.environ.setdefault("DISABLE_LOCAL_TTS_WORKERS", "true")
os.environ.setdefault("IMAGES_DIR", "/tmp/harvis-test-images")
os.environ.setdefault("OWUI_FILES_DIR", "/tmp/harvis-test-owui-files")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn

import main
import job_queue
import private_audio


class _Server:
    def __init__(self, app):
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 90
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("uvicorn did not start within 90s")
            time.sleep(0.05)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=15)


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        main,
        "safe_generate_speech_optimized",
        lambda **kwargs: (8000, np.zeros(80, dtype=np.float32)),
    )
    state = {"user": None}

    def current_user():
        if state["user"] is None:
            from fastapi import HTTPException

            raise HTTPException(401, "Could not validate credentials")
        return state["user"]

    main.app.dependency_overrides[main.get_current_user] = current_user
    with _Server(main.app) as server:
        with httpx.Client(base_url=server.base_url, timeout=30.0) as client:
            yield client, state
    main.app.dependency_overrides.pop(main.get_current_user, None)


def _user(user_id):
    return main.UserResponse(id=user_id, username=f"u{user_id}", email=f"u{user_id}@example.test")


def test_private_tts_roundtrip_is_owner_bound(http):
    client, state = http

    # Anonymous: refused.
    assert client.post("/api/private/synthesize-speech", json={"text": "hello"}).status_code == 401

    # Owner synthesizes and plays back over a real socket.
    state["user"] = _user(2)
    produced = client.post("/api/private/synthesize-speech", json={"text": "hello"})
    assert produced.status_code == 200, produced.text
    audio_path = produced.json()["audio_path"]
    played = client.get(audio_path)
    assert played.status_code == 200
    assert played.content.startswith(b"RIFF")
    assert played.headers["cache-control"] == "private, no-store"

    # Another authenticated user: indistinguishable from missing.
    state["user"] = _user(3)
    assert client.get(audio_path).status_code == 404

    # Anonymous again: refused.
    state["user"] = None
    assert client.get(audio_path).status_code == 401


def test_legacy_whisper_job_endpoint_is_gone(http, monkeypatch):
    client, state = http
    called = []

    async def enqueue(**kwargs):
        called.append(kwargs)
        return "job"

    monkeypatch.setattr(job_queue, "enqueue_whisper_job", enqueue)
    state["user"] = _user(2)
    response = client.post("/api/jobs/whisper", json={"audio_path": "/etc/passwd"})
    assert response.status_code in (403, 404, 410)
    assert not called


def test_job_status_is_owner_bound(http, monkeypatch):
    client, state = http

    class Queue:
        async def get_job_status(self, job_id):
            return {"id": job_id, "data": {"user_id": 2, "text": "private"}}

    async def queue():
        return Queue()

    monkeypatch.setattr(job_queue, "get_job_queue", queue)
    state["user"] = _user(3)
    response = client.get("/api/jobs/example")
    assert response.status_code == 404
    assert "private" not in response.text
    state["user"] = _user(2)
    assert client.get("/api/jobs/example").status_code == 200


def test_core_supported_tts_contract_serves_the_caller(http, monkeypatch):
    """The OWUI/browser TTS contract (/api/v1/audio/speech) is the wiring core
    clients actually use: audio bytes straight back, no temp file involved."""
    client, state = http
    seen = []

    def fake_synthesize(text, voice=None, speed=None, response_format=None, model=None):
        seen.append((text, voice, speed))
        return b"RIFF-fake-core-audio", "audio/wav"

    monkeypatch.setattr(main, "tts_synthesize", fake_synthesize)

    # Anonymous: refused.
    assert client.post("/api/v1/audio/speech", json={"input": "hello"}).status_code == 401

    state["user"] = _user(2)
    response = client.post(
        "/api/v1/audio/speech", json={"input": "hello", "voice": "af_heart", "speed": 1.0}
    )
    assert response.status_code == 200, response.text
    assert response.content == b"RIFF-fake-core-audio"
    assert response.headers["content-type"].startswith("audio/wav")
    assert seen == [("hello", "af_heart", 1.0)]


def test_expired_clip_is_reaped_and_stops_playing(http):
    client, state = http
    state["user"] = _user(2)
    produced = client.post("/api/private/synthesize-speech", json={"text": "short lived"})
    assert produced.status_code == 200, produced.text
    audio_path = produced.json()["audio_path"]
    assert client.get(audio_path).status_code == 200

    # Age the clip past the TTL; the startup sweep's policy removes it.
    clip = Path(str(private_audio.tempfile.gettempdir())) / private_audio.ROOT_NAME / "2" / audio_path.rsplit("/", 1)[-1]
    os.utime(clip, (1.0, 1.0))
    assert private_audio.cleanup_private_audio(max_age_seconds=3600) == 1

    assert client.get(audio_path).status_code == 404
