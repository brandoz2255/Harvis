"""Hermes UI voice endpoints: the data-URL boundary and the relay answer."""
import asyncio
import base64

import pytest
from fastapi import HTTPException

from plugins.hermes_ui import audio


def test_data_url_decodes_to_bytes_and_mime():
    raw, mime = audio._decode_data_url("data:audio/webm;codecs=opus;base64," + base64.b64encode(b"abc").decode())
    assert raw == b"abc"
    assert mime == "audio/webm"


@pytest.mark.parametrize("bad", ["", "nope", "data:audio/webm,abc", "data:audio/webm;base64,***", "data:audio/webm;base64,"])
def test_bad_data_urls_are_400(bad):
    with pytest.raises(HTTPException) as err:
        audio._decode_data_url(bad)
    assert err.value.status_code == 400


def test_voice_config_never_hands_out_a_provider_key():
    config = asyncio.run(audio.voice_config(user={"id": 1}))
    assert config["stt"]["mode"] == "relay" and config["tts"]["mode"] == "relay"
    assert "api_key" not in config["stt"] and "api_key" not in config["tts"]


def test_speech_to_text_is_on_by_default():
    # The UI refuses to send any mic audio while stt.enabled is false.
    from plugins.hermes_ui import rest
    assert rest.CONFIG["stt"]["enabled"] is True


def _transcribe(monkeypatch, result=None, error=None):
    class Req:
        async def json(self):
            return {"data_url": "data:audio/webm;base64," + base64.b64encode(b"abc").decode()}

    def fake(path, auto_unload, language):
        if error:
            raise error
        return result

    monkeypatch.setattr(audio.transcription, "transcribe", fake)
    return asyncio.run(audio.transcribe(Req(), user={"id": 1}))


@pytest.mark.parametrize(
    "heard,said",
    [
        ("Hey Harvest Open Settings.", "Hey Harvis Open Settings."),
        ("hey, harvest, start a research", "hey, Harvis, start a research"),
        ("Harvest, start a deep research", "Harvis, start a deep research"),
        ("  Okay harvest", "Okay Harvis"),
    ],
)
def test_the_product_name_is_restored_when_it_is_addressed(monkeypatch, heard, said):
    out = _transcribe(monkeypatch, {"text": heard})
    assert out["transcript"] == said


@pytest.mark.parametrize("text", ["The harvest was good this year", "Harvest festival is on Friday", "we harvest in autumn"])
def test_the_ordinary_word_harvest_is_left_alone(monkeypatch, text):
    assert _transcribe(monkeypatch, {"text": text})["transcript"] == text


def test_an_undecodable_recording_is_422_and_a_missing_engine_stays_503(monkeypatch):
    with pytest.raises(HTTPException) as err:
        _transcribe(monkeypatch, error=audio.transcription.InvalidAudio("raw ffmpeg text"))
    assert err.value.status_code == 422
    assert "ffmpeg" not in err.value.detail and "http" not in err.value.detail

    with pytest.raises(HTTPException) as err:
        _transcribe(monkeypatch, error=audio.transcription.TranscriptionUnavailable("sidecar down"))
    assert err.value.status_code == 503


def test_the_sidecar_reports_a_clip_it_cannot_decode_as_invalid_audio(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import transcription

    clip = tmp_path / "a.webm"
    clip.write_bytes(b"abc")
    monkeypatch.setenv("HARVIS_STT_URL", "http://stt.test/v1")

    def answer(status, text):
        monkeypatch.setattr(transcription.requests, "post", lambda *a, **k: SimpleNamespace(status_code=status, text=text))

    answer(400, '{"error":{"message":"could not decode audio: [in#0] Error opening input"}}')
    with pytest.raises(transcription.InvalidAudio):
        transcription._transcribe_sidecar(str(clip))

    for status, text in ((400, '{"error":{"message":"unknown model"}}'), (500, "boom")):
        answer(status, text)
        with pytest.raises(transcription.TranscriptionUnavailable) as err:
            transcription._transcribe_sidecar(str(clip))
        assert not isinstance(err.value, transcription.InvalidAudio)
