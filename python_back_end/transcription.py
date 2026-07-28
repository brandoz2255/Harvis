"""Speech-to-text that doesn't care who does the transcribing.

Every transcription route in Harvis used to call
`model_manager.transcribe_with_whisper_optimized` directly. That function
loads openai-whisper in-process, which is one of the things keeping torch and
the CUDA stack inside the backend image — and it is the only option, so a
deploy without a GPU has no speech input at all.

This module puts a provider in front of it. The provider is chosen by env var
and defaults to `local`, so nothing about the current deployment changes; but
`sidecar` lets the same routes talk to any OpenAI-compatible
`/audio/transcriptions` endpoint (a faster-whisper container, a vLLM box, a
hosted API), and `browser` lets the client do it with the Web Speech API while
the server stays out of the audio path entirely.

    HARVIS_STT_PROVIDER   local (default) | sidecar | browser | disabled
    HARVIS_STT_URL        base URL for `sidecar`, e.g. http://stt:8001/v1
    HARVIS_STT_MODEL      model id sent to the sidecar (default "whisper-1")
    HARVIS_STT_API_KEY    optional bearer token for the sidecar
    HARVIS_STT_LANGUAGE   optional ISO code; omitted means auto-detect

Every provider returns the same dict the in-process path always returned —
`{"text": ..., "segments": [...], "language": ...}` — so callers don't branch.
"""

import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

LOCAL = "local"
SIDECAR = "sidecar"
BROWSER = "browser"
DISABLED = "disabled"

_VALID = (LOCAL, SIDECAR, BROWSER, DISABLED)

DEFAULT_SIDECAR_MODEL = "whisper-1"


class TranscriptionUnavailable(RuntimeError):
    """The configured provider cannot transcribe, and says why.

    Distinct from a transcription that was attempted and failed: this means
    the server was never going to do it, so routes should answer 503 with the
    message rather than surfacing a stack trace as a 500.
    """


def get_provider() -> str:
    """Configured provider, falling back to `local` on an unknown value."""
    raw = (os.getenv("HARVIS_STT_PROVIDER") or LOCAL).strip().lower()
    if raw not in _VALID:
        logger.warning(
            "HARVIS_STT_PROVIDER=%r is not one of %s — using %s", raw, _VALID, LOCAL
        )
        return LOCAL
    return raw


def _sidecar_base() -> Optional[str]:
    url = (os.getenv("HARVIS_STT_URL") or "").strip()
    return url.rstrip("/") or None


def status() -> Dict[str, Any]:
    """What the server will do with audio, without touching a model."""
    provider = get_provider()
    info: Dict[str, Any] = {
        "provider": provider,
        # `browser` is available in the sense that speech input works — it just
        # happens client-side. Routes still refuse the upload; the UI is meant
        # to read `server_transcribes` and not send one.
        "available": provider in (LOCAL, SIDECAR, BROWSER),
        "server_transcribes": provider in (LOCAL, SIDECAR),
        "language": os.getenv("HARVIS_STT_LANGUAGE") or "auto",
    }
    if provider == SIDECAR:
        info["url"] = _sidecar_base()
        info["model"] = os.getenv("HARVIS_STT_MODEL") or DEFAULT_SIDECAR_MODEL
        info["configured"] = bool(info["url"])
        if not info["url"]:
            info["available"] = False
            info["server_transcribes"] = False
    elif provider == LOCAL:
        info["model"] = os.getenv("WHISPER_MODEL", "base")
        info["in_process"] = True
    return info


def _language(override: Optional[str] = None) -> str:
    """Per-request language wins over the server default; blank means detect.

    The UI's "preferred STT language" is a per-user setting, so it has to be
    able to override HARVIS_STT_LANGUAGE rather than only fill in for it.
    """
    return (override or os.getenv("HARVIS_STT_LANGUAGE") or "").strip()


def _transcribe_local(
    audio_path: str, auto_unload: bool = True, language: Optional[str] = None
) -> Dict[str, Any]:
    # Imported here rather than at module scope so a build without torch can
    # still import this module and serve the sidecar/browser providers. The
    # failure is named and only reachable when `local` is actually selected.
    try:
        from model_manager import TORCH_AVAILABLE, transcribe_with_whisper_optimized
    except ImportError as e:
        raise TranscriptionUnavailable(
            "In-process Whisper is unavailable in this build "
            f"({e}). Set HARVIS_STT_PROVIDER=sidecar and HARVIS_STT_URL, or "
            "install the voice pack."
        ) from e

    # Ask before calling. Without this the no-torch build reaches Whisper's own
    # loader and raises a bare RuntimeError, which routes would surface as a 500
    # — a configuration answer dressed up as a server fault.
    if not TORCH_AVAILABLE:
        raise TranscriptionUnavailable(
            "HARVIS_STT_PROVIDER=local needs in-process Whisper, and torch is not "
            "installed in this backend. Set HARVIS_STT_PROVIDER=sidecar with "
            "HARVIS_STT_URL, use browser speech recognition, or install the voice pack."
        )

    lang = _language(language)
    kwargs: Dict[str, Any] = {"auto_unload": auto_unload}
    if lang:
        # Asked rather than assumed: the in-process helper's signature has grown
        # before, and passing a keyword it doesn't take would turn a language
        # preference into a TypeError on every local transcription.
        import inspect

        if "language" in inspect.signature(transcribe_with_whisper_optimized).parameters:
            kwargs["language"] = lang
        else:
            logger.info(
                "STT language %r ignored: in-process Whisper here auto-detects", lang
            )

    result = transcribe_with_whisper_optimized(audio_path, **kwargs)
    # The system-whisper fallback path returns a bare {"text": ...}; normalise
    # so callers can always read segments/language without a .get() dance.
    return {
        "text": (result or {}).get("text", ""),
        "segments": (result or {}).get("segments", []),
        "language": (result or {}).get("language"),
    }


def _transcribe_sidecar(
    audio_path: str, timeout: int = 300, language: Optional[str] = None
) -> Dict[str, Any]:
    base = _sidecar_base()
    if not base:
        raise TranscriptionUnavailable(
            "HARVIS_STT_PROVIDER=sidecar but HARVIS_STT_URL is not set. Point it "
            "at an OpenAI-compatible base URL, e.g. http://stt:8001/v1"
        )

    model = os.getenv("HARVIS_STT_MODEL") or DEFAULT_SIDECAR_MODEL
    lang = _language(language)
    api_key = (os.getenv("HARVIS_STT_API_KEY") or "").strip()

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    data = {"model": model, "response_format": "verbose_json"}
    if lang:
        data["language"] = lang

    url = f"{base}/audio/transcriptions"
    logger.info("🎤 Transcribing via STT sidecar %s (model=%s)", url, model)

    # Read the file separately from the POST. requests.ConnectionError subclasses
    # OSError, so a single try around both reported "could not reach the sidecar"
    # outages as "could not read the audio file" — the wrong thing to go fix.
    try:
        with open(audio_path, "rb") as fh:
            payload_bytes = fh.read()
    except OSError as e:
        raise TranscriptionUnavailable(f"Could not read audio {audio_path}: {e}") from e

    try:
        res = requests.post(
            url,
            headers=headers,
            data=data,
            files={"file": (os.path.basename(audio_path), payload_bytes)},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise TranscriptionUnavailable(
            f"Could not reach the STT sidecar at {url}: {e}"
        ) from e

    if res.status_code >= 400:
        # A 4xx here is the sidecar rejecting our request (bad model id, no
        # such route), not a transient outage — surface its own words.
        raise TranscriptionUnavailable(
            f"STT sidecar {url} returned HTTP {res.status_code}: {res.text[:300]}"
        )

    payload = res.json()
    text = payload.get("text", "")
    logger.info("✅ Sidecar transcription: %d chars", len(text))
    return {
        "text": text,
        "segments": payload.get("segments", []),
        "language": payload.get("language"),
    }


def transcribe(
    audio_path: str, auto_unload: bool = True, language: Optional[str] = None
) -> Dict[str, Any]:
    """Transcribe a file with whichever provider is configured.

    `language` is an ISO-639-1 code from the caller (the user's own preference);
    blank or None falls back to HARVIS_STT_LANGUAGE, and then to auto-detect.

    Raises TranscriptionUnavailable when the server is not the one doing the
    transcribing (browser/disabled) or the provider is misconfigured. Real
    transcription failures propagate from the provider unchanged.
    """
    provider = get_provider()

    if provider == DISABLED:
        raise TranscriptionUnavailable(
            "Speech-to-text is disabled on this server (HARVIS_STT_PROVIDER=disabled)."
        )
    if provider == BROWSER:
        raise TranscriptionUnavailable(
            "This server is configured for browser speech recognition "
            "(HARVIS_STT_PROVIDER=browser); send the transcript, not the audio."
        )
    if provider == SIDECAR:
        return _transcribe_sidecar(audio_path, language=language)
    return _transcribe_local(audio_path, auto_unload=auto_unload, language=language)
