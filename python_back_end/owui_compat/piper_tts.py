"""Piper TTS — real-time CPU speech synthesis (no GPU/VRAM).

The neural qwen TTS needs ~3-5GB VRAM to generate, which the 8GB laptop GPU
can't spare alongside the desktop + STT, so it OOM-falls-back to CPU (~15-40s/
sentence — unusable for voice). Piper is an ONNX engine built for CPU: it
synthesizes faster than real-time (~0.1-0.3s/sentence) with zero GPU contention.

The voice model lives in the persisted cache (`/models-cache/piper/…onnx`); the
OWUI `/api/v1/audio/speech` endpoint routes here when `HARVIS_TTS_ENGINE=piper`.
Robust to both the older (`synthesize_stream_raw`) and newer (`synthesize` →
AudioChunk) piper-tts APIs.
"""

from __future__ import annotations

import io
import os
import wave
import logging
import threading

logger = logging.getLogger(__name__)

PIPER_MODEL = os.getenv("PIPER_MODEL", "/models-cache/piper/en_US-lessac-medium.onnx")

_voice = None
_lock = threading.Lock()


def piper_available() -> bool:
    try:
        import piper  # noqa: F401
    except Exception:
        return False
    return os.path.exists(PIPER_MODEL)


def _load():
    global _voice
    if _voice is None:
        from piper import PiperVoice

        _voice = PiperVoice.load(PIPER_MODEL)
        logger.info("🔊 Piper voice loaded (CPU): %s", PIPER_MODEL)
    return _voice


def piper_synthesize_wav(text: str) -> bytes:
    """Synthesize `text` → WAV bytes via Piper (CPU). Returns b'' on failure."""
    text = (text or "").strip()
    if not text:
        return b""
    with _lock:
        try:
            voice = _load()
        except Exception as e:
            logger.error("Piper load failed: %s", e)
            return b""

        # default sample rate; medium voices are 22050 — read the real one if exposed
        sr = 22050
        cfg = getattr(voice, "config", None)
        if cfg is not None:
            sr = getattr(cfg, "sample_rate", None) or getattr(cfg, "sampling_rate", sr) or sr

        pcm = bytearray()
        try:
            # newer piper-tts (>=1.3): synthesize() yields AudioChunk objects
            produced = False
            for chunk in voice.synthesize(text):
                produced = True
                b = getattr(chunk, "audio_int16_bytes", None)
                if b is None and isinstance(chunk, (bytes, bytearray)):
                    b = bytes(chunk)
                if b:
                    pcm.extend(b)
                sr = getattr(chunk, "sample_rate", sr)
            if not produced:
                raise AttributeError("synthesize produced nothing")
        except (AttributeError, TypeError):
            # older piper-tts: synthesize_stream_raw() yields raw int16 PCM bytes
            pcm = bytearray()
            for b in voice.synthesize_stream_raw(text):
                pcm.extend(b)

        if not pcm:
            logger.warning("Piper produced no audio for %d chars", len(text))
            return b""

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16
            wf.setframerate(int(sr))
            wf.writeframes(bytes(pcm))
        return buf.getvalue()
