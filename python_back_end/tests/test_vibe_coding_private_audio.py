"""/api/vibe-coding must put its TTS clip where the owner (and only the owner) can play it."""
import os
import sys

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main
import private_audio
from vibecoding import commands


@pytest.fixture
def vibe_client(tmp_path, monkeypatch):
    monkeypatch.setattr(private_audio.tempfile, "gettempdir", lambda: str(tmp_path))

    async def fake_vibe(**_kwargs):
        return "done", []

    monkeypatch.setattr(commands, "execute_vibe_coding_with_model_management", fake_vibe)
    monkeypatch.setattr(
        commands, "generate_speech_optimized",
        lambda **_kwargs: (16000, np.zeros(1600, dtype="float32")),
    )
    app = FastAPI()
    app.include_router(commands.router)
    app.dependency_overrides[commands.get_current_user] = lambda: {"id": 7, "username": "u7"}
    return TestClient(app)


def _fetch(user_id, path):
    user = main.UserResponse(id=user_id, username=f"u{user_id}", email=f"u{user_id}@example.test")
    main.app.dependency_overrides[main.get_current_user] = lambda: user
    try:
        return TestClient(main.app).get(path)
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)


def test_vibe_coding_clip_is_private_to_the_caller(vibe_client, tmp_path):
    response = vibe_client.post("/api/vibe-coding", json={"message": "hi"})
    assert response.status_code == 200, response.text
    audio_path = response.json()["audio_path"]
    name = audio_path.rsplit("/", 1)[1]

    assert (tmp_path / "harvis-private-audio" / "7" / name).is_file()
    assert not (tmp_path / name).exists()
    assert _fetch(7, audio_path).status_code == 200
    assert _fetch(8, audio_path).status_code == 404
