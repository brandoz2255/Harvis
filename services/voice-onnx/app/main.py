"""voice-onnx — Harvis's default speech service.

Local speech recognition, voice activity detection and Kokoro synthesis, all on
ONNX Runtime through sherpa-onnx. No PyTorch, no CUDA, no cloud calls: if a
model isn't on disk it is fetched once from the pinned GitHub release into the
persistent model volume, and after that the service works with the network off.

The HTTP surface is OpenAI-shaped on purpose — the Harvis backend's existing
`sidecar` STT provider talks to it unchanged.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import engines, models

logging.basicConfig(
    level=os.getenv("VOICE_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("voice-onnx")

API_KEY = os.getenv("VOICE_API_KEY", "").strip()
MAX_UPLOAD_MB = int(os.getenv("VOICE_MAX_UPLOAD_MB", "50"))

app = FastAPI(
    title="Harvis voice-onnx",
    version="1.0.0",
    description="Local ONNX speech: recognition, VAD and Kokoro synthesis.",
)


def require_key(authorization: str = Header(default="")) -> None:
    """Off unless VOICE_API_KEY is set. The service is meant to live on an
    internal network; the key is for deployments that expose it anyway."""
    if not API_KEY:
        return
    token = authorization.removeprefix("Bearer ").strip()
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")


@app.exception_handler(engines.VoiceError)
async def _voice_error(_request, exc: engines.VoiceError):
    return JSONResponse(status_code=400, content={"error": {"message": str(exc)}})


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #

@app.get("/health", tags=["ops"])
def health() -> dict:
    """Healthy means the process is up and can serve. Model state is reported
    separately so a first-run download in progress doesn't read as an outage."""
    return {
        "status": "ok",
        "service": "voice-onnx",
        "engine": "sherpa-onnx",
        "torch": False,
        "models_dir": str(models.MODELS_DIR),
        "models": engines.loaded_state(),
    }


# --------------------------------------------------------------------------- #
# voices
# --------------------------------------------------------------------------- #

@app.get("/v1/audio/voices", tags=["audio"])
def list_voices(model: str | None = None, _: None = Depends(require_key)) -> dict:
    """Voices available for server-side synthesis. Loads the TTS model on first
    call, which is also what downloads it."""
    tts = engines.get_synthesizer(model)
    lang_of = {"a": "en-US", "b": "en-GB", "e": "es", "f": "fr", "h": "hi",
               "i": "it", "j": "ja", "p": "pt-BR", "z": "zh"}
    voices = []
    for sid, name in enumerate(tts.voices):
        prefix = name[:2] if len(name) > 2 and name[1] in ("f", "m") else ""
        voices.append({
            "id": name,
            "name": name.split("_", 1)[-1].replace("-", " ").title() or name,
            "sid": sid,
            "gender": {"f": "female", "m": "male"}.get(prefix[1:2], "unknown"),
            "language": lang_of.get(prefix[:1], "en-US"),
            "model": tts.bundle.name,
        })
    return {"voices": voices, "model": tts.bundle.name,
            "sample_rate": tts.sample_rate, "source": tts.voice_source}


# --------------------------------------------------------------------------- #
# transcription
# --------------------------------------------------------------------------- #

@app.post("/v1/audio/transcriptions", tags=["audio"])
async def transcriptions(
    file: UploadFile = File(...),
    model: str | None = Form(default=None),
    language: str | None = Form(default=None),
    response_format: str = Form(default="json"),
    _: None = Depends(require_key),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413,
                            detail=f"upload exceeds {MAX_UPLOAD_MB} MB")

    started = time.perf_counter()
    result = await run_in_threadpool(_transcribe, raw, model, language)
    result["processing_ms"] = round((time.perf_counter() - started) * 1000, 1)
    log.info("transcribed %.2fs of audio in %.0f ms -> %d chars",
             result["duration"], result["processing_ms"], len(result["text"]))

    if response_format == "text":
        return Response(result["text"], media_type="text/plain")
    if response_format in ("json", ""):
        return {"text": result["text"]}
    return result  # verbose_json and anything else gets the full record


def _transcribe(raw: bytes, model: str | None, language: str | None) -> dict:
    samples = engines.decode_audio(raw)
    duration = len(samples) / engines.SAMPLE_RATE
    recognizer = engines.get_recognizer(model, language)

    # VAD first: it drops silence and long pauses, which is both faster and
    # more accurate than feeding a whole noisy clip to the recognizer.
    speech = engines.split_speech(samples)
    segments, texts = [], []
    for idx, seg in enumerate(speech):
        # Decode from the original waveform with a margin rather than from the
        # VAD's trimmed copy: silero clips the onset of the first word, and a
        # fifth of a second of real audio in front of it is what brings it back.
        margin = int(0.2 * engines.SAMPLE_RATE)
        lo = max(0, int(seg.start * engines.SAMPLE_RATE) - margin)
        hi = min(len(samples), int(seg.end * engines.SAMPLE_RATE) + margin)
        text = recognizer.transcribe(samples[lo:hi])
        if not text:
            continue
        texts.append(text)
        segments.append({"id": idx, "start": round(seg.start, 3),
                         "end": round(seg.end, 3), "text": text})

    if not speech and duration > 0:
        # No speech at all — say so, instead of returning an empty string that
        # looks identical to a broken model.
        return {"task": "transcribe", "language": recognizer.language,
                "duration": round(duration, 3), "text": "", "segments": [],
                "speech_detected": False, "model": recognizer.bundle.name}

    return {
        "task": "transcribe",
        "language": recognizer.language,
        "duration": round(duration, 3),
        "text": " ".join(texts).strip(),
        "segments": segments,
        "speech_detected": True,
        "model": recognizer.bundle.name,
    }


# --------------------------------------------------------------------------- #
# synthesis
# --------------------------------------------------------------------------- #

class SpeechRequest(BaseModel):
    input: str = Field(..., description="Text to speak")
    voice: str | None = Field(default=None, description="Voice id or numeric sid")
    model: str | None = Field(default=None, description="TTS bundle key")
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    response_format: str = Field(default="wav")


@app.post("/v1/audio/speech", tags=["audio"])
async def speech(req: SpeechRequest, _: None = Depends(require_key)):
    text = req.input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="input is empty")
    if len(text) > 8000:
        raise HTTPException(status_code=413, detail="input exceeds 8000 characters")

    started = time.perf_counter()
    payload, mime, seconds = await run_in_threadpool(_synthesize, req)
    elapsed = time.perf_counter() - started
    log.info("synthesized %.2fs of audio in %.0f ms (rtf %.2f)",
             seconds, elapsed * 1000, elapsed / seconds if seconds else 0)
    return Response(
        payload,
        media_type=mime,
        headers={
            "X-Audio-Duration": f"{seconds:.3f}",
            "X-Synthesis-Ms": f"{elapsed * 1000:.0f}",
        },
    )


def _synthesize(req: SpeechRequest) -> tuple[bytes, str, float]:
    tts = engines.get_synthesizer(req.model)
    samples = tts.synthesize(req.input, req.voice, req.speed)
    payload, mime = engines.encode_audio(samples, tts.sample_rate,
                                         req.response_format)
    return payload, mime, len(samples) / tts.sample_rate
