"""The legacy temp-file audio route must not expose unowned files."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main


@pytest.fixture
def audio_file(tmp_path, monkeypatch):
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))
    (tmp_path / "response_12345678.wav").write_bytes(b"private audio")
    return "/api/audio/response_12345678.wav"


def test_anonymous_cannot_read_audio(audio_file):
    response = TestClient(main.app).get(audio_file)
    assert response.status_code == 401
    assert b"private audio" not in response.content


@pytest.mark.parametrize("user_id", [2, 3])
def test_authenticated_users_cannot_read_unowned_audio(audio_file, user_id):
    user = main.UserResponse(id=user_id, username=f"u{user_id}", email=f"u{user_id}@example.test")
    main.app.dependency_overrides[main.get_current_user] = lambda: user
    try:
        response = TestClient(main.app).get(audio_file)
        assert response.status_code == 404
        assert b"private audio" not in response.content
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)
