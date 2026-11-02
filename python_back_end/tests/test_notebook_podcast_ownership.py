"""NotebookLM podcast audio: generation rows bind an owner, playback enforces it."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notebooks import podcast_audio
from notebooks.router import router, get_current_user_from_request, get_notebook_manager
from onb_compat.podcasts import router as onb_router


class _FakeConn:
    def __init__(self, owned):
        self._owned = owned
        self.queries = []

    async def fetchval(self, query, user_id, tail):
        self.queries.append((user_id, tail))
        return 1 if (user_id, tail) in self._owned else None


class _FakePool:
    """Just enough asyncpg.Pool for user_owns_audio."""

    def __init__(self, owned=frozenset()):
        self.conn = _FakeConn(owned)

    def acquire(self):
        return self

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


def test_user_owns_audio_matches_the_generating_user():
    owned = frozenset({(2, "/0123abcd-0000-4000-8000-00000000abcd.wav")})
    pool = _FakePool(owned)
    name = "0123abcd-0000-4000-8000-00000000abcd.wav"
    assert asyncio.run(podcast_audio.user_owns_audio(pool, 2, name)) is True
    assert asyncio.run(podcast_audio.user_owns_audio(pool, 3, name)) is False
    assert asyncio.run(podcast_audio.user_owns_audio(pool, 2, "ffffffff-0000-4000-8000-00000000abcd.wav")) is False


def test_user_owns_audio_fails_closed_without_a_pool():
    assert asyncio.run(podcast_audio.user_owns_audio(None, 2, "x.wav")) is False
    assert asyncio.run(podcast_audio.user_owns_audio(_FakePool(), 2, "")) is False


@pytest.fixture
def podcast_app(tmp_path, monkeypatch):
    monkeypatch.setattr(podcast_audio, "AUDIO_DIR", tmp_path)
    name = "0123abcd-0000-4000-8000-00000000abcd.wav"
    (tmp_path / name).write_bytes(b"RIFF-podcast")
    app = FastAPI()
    app.include_router(router)
    app.include_router(onb_router)
    pool = _FakePool(frozenset({(2, "/" + name)}))
    app.state.pg_pool = pool
    app.state.current_test_user = None

    async def fake_user(request: Request):
        if app.state.current_test_user is None:
            from fastapi import HTTPException

            raise HTTPException(401, "Could not validate credentials")
        return app.state.current_test_user

    async def fake_manager():
        return SimpleNamespace(db_pool=pool)

    app.dependency_overrides[get_current_user_from_request] = fake_user
    app.dependency_overrides[get_notebook_manager] = fake_manager
    return app, name


def test_owner_plays_back_their_episode(podcast_app):
    app, name = podcast_app
    app.state.current_test_user = {"id": 2, "username": "owner"}
    response = TestClient(app).get(f"/api/notebooks/podcasts/tts-audio/{name}")
    assert response.status_code == 200
    assert response.content == b"RIFF-podcast"


def test_other_user_cannot_play_the_episode(podcast_app):
    app, name = podcast_app
    app.state.current_test_user = {"id": 3, "username": "other"}
    response = TestClient(app).get(f"/api/notebooks/podcasts/tts-audio/{name}")
    assert response.status_code == 404
    assert b"RIFF-podcast" not in response.content


def test_anonymous_cannot_play_the_episode(podcast_app):
    app, name = podcast_app
    response = TestClient(app).get(f"/api/notebooks/podcasts/tts-audio/{name}")
    assert response.status_code == 401


def test_traversal_and_foreign_names_never_served(podcast_app):
    app, name = podcast_app
    app.state.current_test_user = {"id": 2, "username": "owner"}
    client = TestClient(app)
    assert client.get("/api/notebooks/podcasts/tts-audio/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/api/notebooks/podcasts/tts-audio/not-a-real-file.wav").status_code == 404


# ── The vendored NotebookLM UI's own facade (/onb-api) enforces the same rule ──

def test_facade_owner_plays_back_their_episode(podcast_app):
    app, name = podcast_app
    app.state.current_test_user = {"id": 2, "username": "owner"}
    response = TestClient(app).get(f"/onb-api/podcasts/tts-audio/{name}")
    assert response.status_code == 200
    assert response.content == b"RIFF-podcast"


def test_facade_other_user_cannot_play_the_episode(podcast_app):
    app, name = podcast_app
    app.state.current_test_user = {"id": 3, "username": "other"}
    response = TestClient(app).get(f"/onb-api/podcasts/tts-audio/{name}")
    assert response.status_code == 404
    assert b"RIFF-podcast" not in response.content


def test_facade_anonymous_cannot_play_the_episode(podcast_app):
    app, name = podcast_app
    response = TestClient(app).get(f"/onb-api/podcasts/tts-audio/{name}")
    assert response.status_code == 401
