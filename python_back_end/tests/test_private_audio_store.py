"""Unit tests for the shared owner-bound private audio store."""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import private_audio
import job_queue
import model_manager


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(private_audio.tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path


def test_write_read_roundtrip_owner_only(store):
    name = "response_" + "a" * 32 + ".wav"
    path = private_audio.write_private_audio(2, name, b"RIFF-x")
    assert path == "/api/audio/" + name
    clip = store / "harvis-private-audio" / "2" / name
    assert clip.read_bytes() == b"RIFF-x"
    # Owner-only permissions the whole way down.
    assert (clip.stat().st_mode & 0o777) == 0o600
    assert ((store / "harvis-private-audio" / "2").stat().st_mode & 0o777) == 0o700
    assert ((store / "harvis-private-audio").stat().st_mode & 0o777) == 0o700


def test_rejects_non_wav_and_traversal_names(store):
    with pytest.raises(ValueError):
        private_audio.write_private_audio(2, "../escape.wav", b"x")
    with pytest.raises(ValueError):
        private_audio.write_private_audio(2, "clip.mp3", b"x")
    with pytest.raises(ValueError):
        private_audio.write_private_audio(2, "", b"x")


def test_unsafe_user_directory_is_refused(store):
    userdir = store / "harvis-private-audio" / "2"
    userdir.mkdir(parents=True, mode=0o755)
    userdir.chmod(0o755)
    with pytest.raises(OSError):
        private_audio.open_private_dir(2)


def test_cleanup_reaps_old_clips_and_keeps_fresh(store):
    old = private_audio.write_private_audio(2, "response_" + "b" * 32 + ".wav", b"old")
    fresh = private_audio.write_private_audio(2, "response_" + "c" * 32 + ".wav", b"fresh")
    other = private_audio.write_private_audio(3, "response_" + "d" * 32 + ".wav", b"other")
    old_file = store / "harvis-private-audio" / "2" / old.rsplit("/", 1)[-1]
    stale = 10_000_000.0
    os.utime(old_file, (stale, stale))

    removed = private_audio.cleanup_private_audio(max_age_seconds=3600)

    assert removed == 1
    assert not old_file.exists()
    assert (store / "harvis-private-audio" / "2" / fresh.rsplit("/", 1)[-1]).exists()
    assert (store / "harvis-private-audio" / "3" / other.rsplit("/", 1)[-1]).exists()


def test_cleanup_removes_empty_user_directories(store):
    path = private_audio.write_private_audio(4, "response_" + "e" * 32 + ".wav", b"x")
    clip = store / "harvis-private-audio" / "4" / path.rsplit("/", 1)[-1]
    os.utime(clip, (1.0, 1.0))

    assert private_audio.cleanup_private_audio(max_age_seconds=1) == 1
    assert not (store / "harvis-private-audio" / "4").exists()


def test_cleanup_leaves_unsafe_directories_alone(store):
    userdir = store / "harvis-private-audio" / "5"
    userdir.mkdir(parents=True, mode=0o700)
    victim = userdir / ("response_" + "f" * 32 + ".wav")
    victim.write_bytes(b"x")
    os.utime(victim, (1.0, 1.0))
    userdir.chmod(0o755)  # no longer a shape we trust — not ours to delete from

    assert private_audio.cleanup_private_audio(max_age_seconds=1) == 0
    assert victim.exists()


def test_cleanup_without_root_is_a_noop(store):
    assert private_audio.cleanup_private_audio() == 0


class _FakeJob:
    def __init__(self, data):
        self.id = "11111111-2222-3333-4444-555555555555"
        self.data = data
        self.created_at = None
        self.done_result = None
        self.fail_error = None

    async def done(self, result=None):
        self.done_result = result

    async def fail(self, error=None):
        self.fail_error = error


def test_tts_worker_writes_into_owners_namespace(store, monkeypatch):
    monkeypatch.setattr(
        model_manager,
        "generate_speech_unified",
        lambda **kwargs: (8000, np.zeros(80, dtype=np.float32)),
    )
    job = _FakeJob({"text": "hello", "tts_engine": "qwen", "user_id": 2})

    asyncio.run(job_queue.process_tts_job(job))

    assert job.fail_error is None
    audio_path = job.done_result["audio_path"]
    name = audio_path.rsplit("/", 1)[-1]
    assert name.startswith("tts_11111111-")
    clip = store / "harvis-private-audio" / "2" / name
    assert clip.read_bytes().startswith(b"RIFF")
    # Nothing leaked into the shared temp root.
    assert not (store / name).exists()


def test_tts_worker_refuses_unowned_job(store, monkeypatch):
    called = []
    monkeypatch.setattr(
        model_manager,
        "generate_speech_unified",
        lambda **kwargs: called.append(kwargs) or (8000, np.zeros(8, dtype=np.float32)),
    )
    job = _FakeJob({"text": "hello", "tts_engine": "qwen", "user_id": None})

    asyncio.run(job_queue.process_tts_job(job))

    assert job.done_result is None
    assert job.fail_error is not None
    assert not called  # never even synthesizes for an unowned job
    assert not (store / "harvis-private-audio").exists()


@pytest.mark.parametrize("name", ["a\x00.wav", "a\x00b.wav", "..\\escape.wav", "dir\\clip.wav"])
def test_valid_name_rejects_nul_and_backslash(store, name):
    assert not private_audio.valid_name(name)
    with pytest.raises(ValueError):
        private_audio.write_private_audio(2, name, b"x")
