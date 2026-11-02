"""Every producer's clip name must be servable to its owner and nobody else."""
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main
import private_audio


def _user(user_id):
    return main.UserResponse(id=user_id, username=f"u{user_id}", email=f"u{user_id}@example.test")


def _fetch(user, path):
    main.app.dependency_overrides[main.get_current_user] = lambda: user
    try:
        return TestClient(main.app).get(path)
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)


PRODUCER_NAMES = [
    lambda: f"response_{uuid.uuid4()}.wav",
    lambda: f"response_{uuid.uuid4().hex}.wav",
    lambda: f"vision_{uuid.uuid4()}.wav",
    lambda: f"screen_analysis_{uuid.uuid4()}.wav",
    lambda: f"tts_{uuid.uuid4()}_{uuid.uuid4().hex[:8]}.wav",
]


@pytest.mark.parametrize("make_name", PRODUCER_NAMES)
def test_producer_clip_is_served_to_owner_only(tmp_path, monkeypatch, make_name):
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))
    name = make_name()
    path = private_audio.write_private_audio(2, name, b"RIFFclip")

    owner = _fetch(_user(2), path)
    assert owner.status_code == 200
    assert owner.content == b"RIFFclip"
    assert _fetch(_user(3), path).status_code == 404


@pytest.mark.parametrize(
    "bad",
    ["..%2Fsecret.wav", "%2e%2e%2fsecret.wav", "a%00.wav", "response_x.mp3", "..", "%2Fetc%2Fpasswd"],
)
def test_traversal_and_non_wav_names_are_refused(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))
    (tmp_path / "secret.wav").write_bytes(b"outside")
    private_audio.write_private_audio(2, "response_" + "a" * 32 + ".wav", b"RIFFclip")
    assert _fetch(_user(2), "/api/audio/" + bad).status_code == 404
