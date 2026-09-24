"""The Hermes UI's voice endpoints, answered by Harvis's own STT/TTS.

Hermes asks /api/audio/voice-config first: "direct" there would mean the
browser calls a cloud provider itself with a key we hand it. Harvis never
hands out keys, so both sides answer "relay" and every clip comes through
here to `transcription.py` / `synthesis.py` — the same engines the OWUI
/api/v1/audio/* routes use (Whisper and the voice sidecar, or whatever
HARVIS_STT_PROVIDER / HARVIS_TTS_PROVIDER name).
"""
from __future__ import annotations

import base64
import binascii
import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

import synthesis
import transcription
from auth_optimized import get_current_user_optimized

log = logging.getLogger("hermes_ui.audio")

router = APIRouter(prefix="/hermes-api/api/audio")

# A minute of 48 kHz webm/opus is well under 1 MB; this only stops a runaway upload.
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_SPEAK_CHARS = 4000

_EXT = {"webm": ".webm", "ogg": ".ogg", "wav": ".wav", "mpeg": ".mp3", "mp3": ".mp3", "mp4": ".m4a", "m4a": ".m4a"}


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    """`data:audio/webm;codecs=opus;base64,....` → (bytes, 'audio/webm')."""
    head, sep, payload = (data_url or "").partition(",")
    if not sep or not head.startswith("data:") or ";base64" not in head:
        raise HTTPException(400, "Expected a base64 data URL")
    mime = head[5:].split(";", 1)[0].strip().lower() or "audio/webm"
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Audio is not valid base64")
    if not raw:
        raise HTTPException(400, "Empty audio")
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio clip is too large")
    return raw, mime


@router.get("/voice-config")
async def voice_config(user=Depends(get_current_user_optimized)):
    reason = "Harvis runs speech on the server"
    return {"ok": True, "stt": {"mode": "relay", "reason": reason}, "tts": {"mode": "relay", "reason": reason}}


@router.post("/transcribe")
async def transcribe(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    raw, mime = _decode_data_url(body.get("data_url") or "")
    ext = _EXT.get((body.get("mime_type") or mime).split("/")[-1].split(";")[0], ".webm")
    path = os.path.join(tempfile.gettempdir(), f"hermes_stt_{uuid.uuid4().hex}{ext}")
    try:
        with open(path, "wb") as f:
            f.write(raw)
        result = await run_in_threadpool(transcription.transcribe, path, True, None)
    except transcription.TranscriptionUnavailable as e:
        raise HTTPException(503, str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error("Hermes STT failed: %s", e)
        raise HTTPException(500, f"Transcription failed: {e}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    text = result.get("text", "") if isinstance(result, dict) else str(result or "")
    return {"ok": True, "provider": transcription.get_provider(), "transcript": text.strip()}


@router.post("/speak")
async def speak(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Nothing to say")
    try:
        audio, mime = await run_in_threadpool(synthesis.synthesize, text[:MAX_SPEAK_CHARS])
    except synthesis.SynthesisUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        log.error("Hermes TTS failed: %s", e)
        raise HTTPException(500, f"Speech synthesis failed: {e}")
    encoded = base64.b64encode(audio).decode("ascii")
    return {"ok": True, "provider": synthesis.get_provider(), "mime_type": mime, "data_url": f"data:{mime};base64,{encoded}"}


@router.get("/elevenlabs/voices")
async def elevenlabs_voices(user=Depends(get_current_user_optimized)):
    # Harvis has no ElevenLabs account; say so instead of 404ing the settings page.
    return {"available": False, "voices": []}
