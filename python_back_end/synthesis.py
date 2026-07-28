"""Text-to-speech that doesn't care who does the speaking.

The mirror image of `transcription.py`, and for the same reason. Every TTS
route called into `safe_generate_speech_optimized` (or Piper) directly, which
means speech only works in a build that carries the voice pack — and on a
torch-free backend there is no voice at all.

A provider sits in front now:

    HARVIS_TTS_PROVIDER   local (default) | sidecar | browser | disabled
    HARVIS_TTS_URL        base URL for `sidecar`, e.g. http://voice-onnx:8000/v1
    HARVIS_TTS_MODEL      model/engine id sent to the sidecar
    HARVIS_TTS_VOICE      default voice id
    HARVIS_TTS_SPEED      default speaking rate (1.0 = normal)
    HARVIS_TTS_API_KEY    optional bearer token for the sidecar
    HARVIS_TTS_FORMAT     default response format (wav)

`local` is unchanged behaviour: Piper first (fast CPU, no VRAM), falling back
to the neural engine named by HARVIS_TTS_FALLBACK. `sidecar` posts the OpenAI
`/audio/speech` contract to voice-onnx or anything that speaks it. `browser`
means the client synthesizes — the server refuses and says so, rather than
returning a 500 from a model that was never going to load.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

LOCAL = "local"
SIDECAR = "sidecar"
BROWSER = "browser"
DISABLED = "disabled"

_VALID = (LOCAL, SIDECAR, BROWSER, DISABLED)

DEFAULT_VOICE = "af_heart"
DEFAULT_FORMAT = "wav"

_MIME = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "pcm": "audio/L16",
}


class SynthesisUnavailable(RuntimeError):
    """The configured provider cannot speak, and says why.

    Distinct from a synthesis that was attempted and failed: this means the
    server was never going to do it, so routes answer 503 with the message
    instead of surfacing a stack trace as a 500.
    """


def get_provider() -> str:
    """Configured provider, falling back to `local` on an unknown value."""
    raw = (os.getenv("HARVIS_TTS_PROVIDER") or LOCAL).strip().lower()
    if raw not in _VALID:
        logger.warning(
            "HARVIS_TTS_PROVIDER=%r is not one of %s — using %s", raw, _VALID, LOCAL
        )
        return LOCAL
    return raw


def _sidecar_base() -> Optional[str]:
    url = (os.getenv("HARVIS_TTS_URL") or "").strip()
    return url.rstrip("/") or None


def default_voice() -> str:
    return (os.getenv("HARVIS_TTS_VOICE") or DEFAULT_VOICE).strip()


def default_speed() -> float:
    try:
        return float(os.getenv("HARVIS_TTS_SPEED") or 1.0)
    except ValueError:
        return 1.0


def status() -> Dict[str, Any]:
    """What the server will do with text, without loading a model."""
    provider = get_provider()
    info: Dict[str, Any] = {
        "provider": provider,
        # `browser` is available in the sense that the user hears speech — it
        # just happens client-side. The UI reads `server_synthesizes` and keeps
        # its own Kokoro/WebSpeech path instead of calling us.
        "available": provider in (LOCAL, SIDECAR, BROWSER),
        "server_synthesizes": provider in (LOCAL, SIDECAR),
        "voice": default_voice(),
        "speed": default_speed(),
    }
    if provider == SIDECAR:
        info["url"] = _sidecar_base()
        info["model"] = os.getenv("HARVIS_TTS_MODEL") or ""
        info["configured"] = bool(info["url"])
        if not info["url"]:
            info["available"] = False
            info["server_synthesizes"] = False
    elif provider == LOCAL:
        info["engine"] = os.getenv("HARVIS_TTS_ENGINE", "piper")
        info["fallback"] = os.getenv("HARVIS_TTS_FALLBACK", "qwen")
        info["in_process"] = True
    return info


# --------------------------------------------------------------------------- #
# local
# --------------------------------------------------------------------------- #

def _synthesize_local(
    text: str, engine: Optional[str] = None, speed: Optional[float] = None
) -> Tuple[bytes, str]:
    """Speak `text` in-process.

    `speed` is the per-user setting. Piper renders it (so the voice speeds up
    without shifting pitch); the neural fallback has no such knob, and says so
    in the log rather than accepting the value and ignoring it.
    """
    # This endpoint speaks the OpenAI contract, where the field is a *model* id,
    # so stock clients send "tts-1". Treating those as "whichever engine this
    # server runs" is what makes it compatible — taking them literally sent
    # every such request down the neural fallback with a nonsense engine name.
    if (engine or "").strip().lower() in {"", "default", "auto", "tts-1", "tts-1-hd"}:
        engine = os.getenv("HARVIS_TTS_ENGINE", "piper")

    # Piper: real-time CPU TTS, zero VRAM. The default on VRAM-constrained
    # boxes — the neural engine needs 3-5 GB of GPU and OOM-falls-back to CPU at
    # 15-40 s a sentence.
    if engine == "piper":
        try:
            from owui_compat.piper_tts import piper_available, piper_synthesize_wav
        except ImportError as e:
            logger.warning("Piper unavailable (%s); falling back", e)
        else:
            if piper_available():
                audio = piper_synthesize_wav(text, speed=speed)
                if audio:
                    return audio, _MIME["wav"]
                logger.warning("Piper returned no audio; falling back")
            else:
                logger.warning("Piper unavailable; falling back")
        engine = os.getenv("HARVIS_TTS_FALLBACK", "qwen")

    # Imported here rather than at module scope so a build without torch can
    # still import this module and serve the sidecar/browser providers.
    try:
        import io

        import soundfile as sf

        from model_manager import safe_generate_speech_optimized
    except ImportError as e:
        raise SynthesisUnavailable(
            f"In-process TTS is unavailable in this build ({e}). Set "
            "HARVIS_TTS_PROVIDER=sidecar with HARVIS_TTS_URL, or install the "
            "voice pack."
        ) from e

    if speed is not None and abs(float(speed) - 1.0) > 1e-6:
        logger.info(
            "TTS speed %.2f ignored: in-process engine %r renders at 1.0x only",
            float(speed), engine,
        )

    # auto_unload=False keeps the model warm: a spoken reply is split into many
    # sentences, each its own call, and reloading per sentence makes playback
    # crawl.
    sr, wav = safe_generate_speech_optimized(
        text=text, tts_engine=engine, auto_unload=False
    )
    if sr is None or wav is None:
        raise SynthesisUnavailable(
            f"In-process TTS engine {engine!r} produced no audio. Set "
            "HARVIS_TTS_PROVIDER=sidecar with HARVIS_TTS_URL to use the ONNX "
            "voice service instead."
        )
    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV")
    return buf.getvalue(), _MIME["wav"]


def _voices_local() -> List[Dict[str, Any]]:
    engine = os.getenv("HARVIS_TTS_ENGINE", "piper")
    if engine == "piper":
        try:
            from owui_compat.piper_tts import piper_available
        except ImportError:
            pass
        else:
            if piper_available():
                model = os.path.basename(
                    os.getenv("PIPER_MODEL", "en_US-lessac-medium.onnx")
                )
                name = model.replace(".onnx", "")
                return [{"id": name, "name": name.replace("-", " "),
                         "engine": "piper"}]
    return [{"id": "default", "name": "Default", "engine": engine}]


# --------------------------------------------------------------------------- #
# sidecar
# --------------------------------------------------------------------------- #

def _synthesize_sidecar(
    text: str,
    voice: Optional[str] = None,
    speed: Optional[float] = None,
    fmt: Optional[str] = None,
    timeout: int = 120,
) -> Tuple[bytes, str]:
    base = _sidecar_base()
    if not base:
        raise SynthesisUnavailable(
            "HARVIS_TTS_PROVIDER=sidecar but HARVIS_TTS_URL is not set. Point it "
            "at an OpenAI-compatible base URL, e.g. http://voice-onnx:8000/v1"
        )

    fmt = (fmt or os.getenv("HARVIS_TTS_FORMAT") or DEFAULT_FORMAT).lower()
    payload: Dict[str, Any] = {
        "input": text,
        "voice": voice or default_voice(),
        "speed": speed if speed is not None else default_speed(),
        "response_format": fmt,
    }
    model = (os.getenv("HARVIS_TTS_MODEL") or "").strip()
    if model:
        payload["model"] = model

    api_key = (os.getenv("HARVIS_TTS_API_KEY") or "").strip()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    url = f"{base}/audio/speech"
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise SynthesisUnavailable(
            f"Could not reach the TTS sidecar at {url}: {e}"
        ) from e

    if res.status_code >= 400:
        raise SynthesisUnavailable(
            f"TTS sidecar {url} returned HTTP {res.status_code}: {res.text[:300]}"
        )
    if not res.content:
        raise SynthesisUnavailable(f"TTS sidecar {url} returned no audio")

    mime = res.headers.get("content-type") or _MIME.get(fmt, "audio/wav")
    logger.info("🔊 Sidecar synthesis: %d bytes (%s)", len(res.content), mime)
    return res.content, mime


def _voices_sidecar(timeout: int = 30) -> List[Dict[str, Any]]:
    base = _sidecar_base()
    if not base:
        raise SynthesisUnavailable(
            "HARVIS_TTS_PROVIDER=sidecar but HARVIS_TTS_URL is not set."
        )
    api_key = (os.getenv("HARVIS_TTS_API_KEY") or "").strip()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{base}/audio/voices"
    try:
        res = requests.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
    except requests.RequestException as e:
        raise SynthesisUnavailable(f"Could not list voices at {url}: {e}") from e
    payload = res.json()
    voices = payload.get("voices") if isinstance(payload, dict) else payload
    return voices or []


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #

def synthesize(
    text: str,
    voice: Optional[str] = None,
    speed: Optional[float] = None,
    fmt: Optional[str] = None,
    engine: Optional[str] = None,
) -> Tuple[bytes, str]:
    """Speak `text` with whichever provider is configured.

    Returns (audio_bytes, mime_type). Raises SynthesisUnavailable when the
    server is not the one speaking (browser/disabled) or the provider is
    misconfigured.
    """
    provider = get_provider()

    if provider == DISABLED:
        raise SynthesisUnavailable(
            "Text-to-speech is disabled on this server (HARVIS_TTS_PROVIDER=disabled)."
        )
    if provider == BROWSER:
        raise SynthesisUnavailable(
            "This server is configured for browser speech synthesis "
            "(HARVIS_TTS_PROVIDER=browser); play the text client-side."
        )
    if provider == SIDECAR:
        return _synthesize_sidecar(text, voice=voice, speed=speed, fmt=fmt)
    return _synthesize_local(text, engine=engine, speed=speed)


def voices() -> List[Dict[str, Any]]:
    """Voices the configured provider offers. Empty when nobody is speaking."""
    provider = get_provider()
    if provider == SIDECAR:
        return _voices_sidecar()
    if provider == LOCAL:
        return _voices_local()
    return []
