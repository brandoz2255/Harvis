"""Private TTS producer and playback through the real HTTP routes."""
import numpy as np
from fastapi.testclient import TestClient
import main


def test_synthesized_audio_is_only_accessible_to_its_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(main, "safe_generate_speech_optimized", lambda **kwargs: (8000, np.zeros(80, dtype=np.float32)))
    client = TestClient(main.app)
    user_a = main.UserResponse(id=2, username="a", email="a@example.test")
    user_b = main.UserResponse(id=3, username="b", email="b@example.test")
    try:
        assert client.post('/api/private/synthesize-speech', json={'text': 'hello'}).status_code == 401
        main.app.dependency_overrides[main.get_current_user] = lambda: user_a
        produced = client.post('/api/private/synthesize-speech', json={'text': 'hello'})
        assert produced.status_code == 200, produced.text
        path = produced.json()['audio_path']
        owner = client.get(path)
        assert owner.status_code == 200
        assert owner.content.startswith(b'RIFF')
        assert owner.headers['cache-control'] == 'private, no-store'
        assert client.post('/api/private/synthesize-speech', json={'text': 'hello', 'audio_prompt': '/etc/passwd'}).status_code == 400
        main.app.dependency_overrides[main.get_current_user] = lambda: user_b
        assert client.get(path).status_code == 404
        other = client.post('/api/private/synthesize-speech', json={'text': 'second user'})
        assert other.status_code == 200
        assert client.get(other.json()['audio_path']).status_code == 200
        main.app.dependency_overrides[main.get_current_user] = lambda: user_a
        assert client.get(other.json()['audio_path']).status_code == 404
        # Even a legacy file with the new filename format is not adopted.
        legacy = 'response_' + 'a' * 32 + '.wav'
        (tmp_path / legacy).write_bytes(b'unowned')
        assert client.get('/api/audio/' + legacy).status_code == 404
        # Symlinks in a private directory cannot redirect the playback route.
        (tmp_path / 'harvis-private-audio' / '2' / legacy).symlink_to(tmp_path / legacy)
        assert client.get('/api/audio/' + legacy).status_code == 404
        main.app.dependency_overrides.pop(main.get_current_user)
        assert client.get(path).status_code == 401
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)


def test_directory_swap_cannot_redirect_read(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(main.tempfile, 'gettempdir', lambda: str(tmp_path))
    root = tmp_path / 'harvis-private-audio'
    userdir = root / '2'
    userdir.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    name = 'response_' + 'b' * 32 + '.wav'
    (userdir / name).write_bytes(b'owner')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / name).write_bytes(b'secret')
    original_open = os.open
    def racing_open(path, flags, *args, **kwargs):
        if str(path) in (str(userdir / name), name):
            userdir.rename(root / 'saved')
            userdir.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', racing_open)
    main.app.dependency_overrides[main.get_current_user] = lambda: main.UserResponse(id=2, username='a', email='a@example.test')
    try:
        result = TestClient(main.app).get('/api/audio/' + name)
        assert result.content != b'secret'
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)
