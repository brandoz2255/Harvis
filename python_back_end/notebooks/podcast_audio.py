"""Podcast audio through the speech sidecar that ships by default.

The notebook podcast code was written against ``tts-service`` (the RVC stack
behind the ``advanced-voice`` profile). A default install doesn't run it, so
every podcast ended as ``script_only``. This speaks each line through the
OpenAI-compatible ``/audio/speech`` endpoint synthesis.py already uses
(``HARVIS_TTS_URL``, voice-onnx by default), gives each speaker their own
voice, and joins the WAV clips with a short pause between turns.
"""
from __future__ import annotations

import io
import os
import uuid
import wave
from pathlib import Path
from typing import Optional

import httpx

AUDIO_DIR = Path(os.getenv("NOTEBOOK_PODCAST_AUDIO_DIR", "/data/artifacts/notebook_podcasts"))
VOICES = ("af_heart", "am_michael", "bf_emma", "bm_george")
PAUSE_SECONDS = 0.3
_FILENAME_OK = frozenset("abcdef0123456789-")


def speech_url() -> str:
    base = (os.getenv("HARVIS_TTS_URL") or "http://voice-onnx:8000/v1").rstrip("/")
    return f"{base}/audio/speech"


def voice_for(speaker: str, order: dict[str, str]) -> str:
    """Each new speaker takes the next voice; a fifth reuses the first."""
    if speaker not in order:
        order[speaker] = VOICES[len(order) % len(VOICES)]
    return order[speaker]


def join_wavs(clips: list[bytes], pause: float = PAUSE_SECONDS) -> tuple[bytes, float]:
    """Concatenate WAV clips that share one format, with silence between them."""
    out = io.BytesIO()
    params = None
    frames = 0
    with wave.open(out, "wb") as dst:
        for i, clip in enumerate(clips):
            with wave.open(io.BytesIO(clip), "rb") as src:
                p = src.getparams()
                if params is None:
                    params = p
                    dst.setnchannels(p.nchannels)
                    dst.setsampwidth(p.sampwidth)
                    dst.setframerate(p.framerate)
                elif (p.nchannels, p.sampwidth, p.framerate) != (params.nchannels, params.sampwidth, params.framerate):
                    raise ValueError("speech clips came back in different formats")
                if i:
                    gap = int(params.framerate * pause)
                    dst.writeframes(b"\x00" * gap * params.sampwidth * params.nchannels)
                    frames += gap
                dst.writeframes(src.readframes(p.nframes))
                frames += p.nframes
    if params is None:
        raise ValueError("no speech to join")
    return out.getvalue(), frames / params.framerate


async def synthesize(segments: list[dict], model: Optional[str] = None) -> tuple[str, float]:
    """Speak every ``{speaker, text}`` segment; return (filename, seconds)."""
    order: dict[str, str] = {}
    clips: list[bytes] = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            resp = await client.post(speech_url(), json={
                "model": model or os.getenv("HARVIS_TTS_MODEL") or "kokoro",
                "input": text,
                "voice": voice_for(seg.get("speaker") or "Speaker", order),
                "response_format": "wav",
            })
            resp.raise_for_status()
            clips.append(resp.content)
    audio, seconds = join_wavs(clips)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4()}.wav"
    (AUDIO_DIR / name).write_bytes(audio)
    return name, seconds


def local_file(filename: str) -> Optional[Path]:
    """The saved podcast for ``filename``, or None. Only our own uuid names resolve."""
    stem, _, ext = filename.partition(".")
    if ext != "wav" or not stem or set(stem) - _FILENAME_OK:
        return None
    path = AUDIO_DIR / filename
    return path if path.is_file() else None
