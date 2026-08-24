"""Startup prefetch for the server-side speech models.

The image deliberately ships no model weights — they are fetched once from the
pinned GitHub release into the persistent volume. That keeps the image ~1 GB
instead of ~2.5 GB, and it is the right trade. What was wrong was *when* the
fetch happened: lazily, on the user's first request.

On a fresh install that meant the first click of the speaker icon sat in silence
for a measured 36 s on a fast connection while 384 MB of Kokoro came down — and
the backend gives the sidecar 120 s, so a slower link turned "read this out
loud" into a timeout. Meanwhile /health had been answering 200 the whole time,
because process health and model readiness are deliberately separate signals, so
nothing anywhere reported that the service could not yet speak.

So: pull the bundles in the background as soon as the process is up, on the same
non-blocking pattern `browser_assets.sync_in_background()` already uses for the
in-browser mirror. By the time anyone has signed up and typed a first message,
the models are on disk and the first speak is instant. Nothing here blocks
startup, nothing here fails a health check, and a box with no internet degrades
exactly as it does today — the request path is unchanged and still fetches on
demand if this never finished.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from . import engines, models

log = logging.getLogger("voice-onnx.warmup")

# Order matters: TTS is the biggest bundle and the one a user hits first, since
# every assistant reply offers a speaker button while ASR waits on a mic click.
_KINDS = ("tts", "asr", "vad")

_state: dict = {"status": "pending", "done": [], "failed": {}, "seconds": None}
_lock = threading.Lock()


def _wanted() -> tuple[str, ...]:
    """VOICE_PREFETCH: 1/true/all (default), 0/false/off, or a subset list."""
    raw = os.getenv("VOICE_PREFETCH", "1").strip().lower()
    if raw in {"0", "false", "no", "off", "none"}:
        return ()
    if raw in {"1", "true", "yes", "on", "all", ""}:
        return _KINDS
    picked = tuple(k for k in _KINDS if k in {p.strip() for p in raw.split(",")})
    return picked or _KINDS


def _bundle(kind: str):
    if kind == "tts":
        return models.pick_tts()
    if kind == "asr":
        return models.pick_asr()
    return models.VAD_BUNDLE


def _load(kind: str) -> None:
    """Construct the engine so the first real request pays no load either.

    Downloading is what takes 36 s; engine construction takes well under a
    second. They are split so the download — which holds only its own per-bundle
    lock — never sits inside `engines._load_lock` and stall an unrelated
    request that wanted a different model.
    """
    if kind == "tts":
        engines.get_synthesizer()
    elif kind == "asr":
        engines.get_recognizer()
    else:
        engines.get_vad()


def _run(kinds: tuple[str, ...]) -> None:
    started = time.monotonic()
    with _lock:
        _state.update(status="running", done=[], failed={})
    for kind in kinds:
        try:
            bundle = _bundle(kind)
        except Exception as exc:  # a bad VOICE_*_MODEL env value
            with _lock:
                _state["failed"][kind] = str(exc)
            log.warning("prefetch %s: cannot resolve bundle: %s", kind, exc)
            continue

        if models.is_present(bundle):
            _load(kind)
            with _lock:
                _state["done"].append(kind)
            continue

        # Two tries. A transient DNS blip on a just-booted host is worth one
        # retry; a firewalled box is not worth hammering, and the request path
        # still fetches on demand if this gives up.
        last = ""
        for attempt in (1, 2):
            try:
                log.info("prefetch %s: downloading %s", kind, bundle.name)
                models.ensure(bundle)
                _load(kind)
                with _lock:
                    _state["done"].append(kind)
                log.info("prefetch %s: ready (%s)", kind, bundle.name)
                last = ""
                break
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                log.warning("prefetch %s attempt %d failed: %s", kind, attempt, last)
                if attempt == 1:
                    time.sleep(5)
        if last:
            with _lock:
                _state["failed"][kind] = last

    with _lock:
        _state["seconds"] = round(time.monotonic() - started, 1)
        _state["status"] = "ready" if not _state["failed"] else "partial"
    log.info(
        "prefetch finished in %ss: ready=%s failed=%s",
        _state["seconds"], _state["done"], sorted(_state["failed"]),
    )


def prefetch_in_background() -> None:
    """Startup hook. Never blocks health, never blocks a request."""
    kinds = _wanted()
    if not kinds:
        with _lock:
            _state.update(status="disabled")
        log.info("prefetch disabled by VOICE_PREFETCH")
        return
    threading.Thread(target=_run, args=(kinds,), name="voice-warmup", daemon=True).start()


def state() -> dict:
    with _lock:
        return {
            "status": _state["status"],
            "ready": list(_state["done"]),
            "failed": dict(_state["failed"]),
            "seconds": _state["seconds"],
        }
