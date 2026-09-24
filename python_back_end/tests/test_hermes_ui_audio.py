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
