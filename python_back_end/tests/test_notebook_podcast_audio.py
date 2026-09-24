"""Notebook podcasts voice through the default speech sidecar."""
import io
import wave

import pytest

from notebooks import podcast_audio as pa


def _wav(frames: int, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * frames)
    return buf.getvalue()


def test_clips_join_with_a_pause_between_turns():
    audio, seconds = pa.join_wavs([_wav(24000), _wav(12000)], pause=0.5)
    with wave.open(io.BytesIO(audio), "rb") as w:
        assert w.getnframes() == 24000 + 12000 + 12000
    assert seconds == pytest.approx(2.0)


def test_mismatched_clips_are_refused():
    with pytest.raises(ValueError):
        pa.join_wavs([_wav(100, 24000), _wav(100, 16000)])


def test_each_speaker_keeps_one_voice():
    order: dict = {}
    assert pa.voice_for("Ana", order) == pa.VOICES[0]
    assert pa.voice_for("Ben", order) == pa.VOICES[1]
    assert pa.voice_for("Ana", order) == pa.VOICES[0]


def test_only_our_own_files_are_served(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "AUDIO_DIR", tmp_path)
    name = "0123abcd-0000-4000-8000-00000000abcd.wav"
    (tmp_path / name).write_bytes(b"x")
    assert pa.local_file(name) == tmp_path / name
    assert pa.local_file("../etc/passwd") is None
    assert pa.local_file("missing-0000.wav") is None
    assert pa.local_file("abc.mp3") is None
