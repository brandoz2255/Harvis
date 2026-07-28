"""A local mirror of the Kokoro model the *browser* loads.

Harvis's preferred playback path is Kokoro running in the user's tab (kokoro-js
+ transformers.js), not server synthesis — it costs the server nothing and
starts speaking immediately. But that path fetches its weights and voice
embeddings straight from huggingface.co on first use, so a machine that is
offline (or on a network that can't reach HF) has no voice at all, and every
fresh browser profile re-downloads ~90 MB from the internet.

This mirrors those exact files into the persistent model volume and serves them
back over HTTP, so after one sync the browser path works with the network off.
Nothing is baked into the image; the mirror lives beside the server-side models
in the same volume.

    VOICE_BROWSER_ASSETS   1 (default) to sync on startup, 0 to skip entirely
    VOICE_BROWSER_DTYPES   which ONNX variants to mirror (default "q8")
    VOICE_BROWSER_REPO     source repo (default onnx-community/Kokoro-82M-v1.0-ONNX)

The file list comes from the repo's own manifest rather than a hardcoded list,
for the same reason the server-side voice names are read out of the model: a
list written here drifts from the thing it describes, and the drift is silent.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

from .models import MODELS_DIR, _download

log = logging.getLogger("voice-onnx.browser")

HF = "https://huggingface.co"
REPO = os.getenv("VOICE_BROWSER_REPO", "onnx-community/Kokoro-82M-v1.0-ONNX")
ROOT = MODELS_DIR / "browser"

# transformers.js maps a dtype to a filename suffix; these are the four the
# Harvis UI offers, plus the two half-precision quantisations it may pick on its
# own. Anything not mirrored still works online — the client falls back to HF.
DTYPE_FILES = {
    "fp32": "onnx/model.onnx",
    "fp16": "onnx/model_fp16.onnx",
    "q8": "onnx/model_quantized.onnx",
    "q4": "onnx/model_q4.onnx",
    "q4f16": "onnx/model_q4f16.onnx",
    "q8f16": "onnx/model_q8f16.onnx",
}

# Small, always needed: transformers.js reads the config and tokenizer before it
# touches any weights.
BASE_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json")

_sync_lock = threading.Lock()
_state: dict = {"status": "idle", "files": 0, "bytes": 0, "dtypes": [], "error": ""}


def enabled() -> bool:
    return os.getenv("VOICE_BROWSER_ASSETS", "1").strip().lower() not in (
        "0", "false", "no", ""
    )


def wanted_dtypes() -> list[str]:
    raw = os.getenv("VOICE_BROWSER_DTYPES", "q8")
    picked = [d.strip() for d in raw.split(",") if d.strip()]
    unknown = [d for d in picked if d not in DTYPE_FILES]
    if unknown:
        log.warning("ignoring unknown VOICE_BROWSER_DTYPES entries: %s", unknown)
    return [d for d in picked if d in DTYPE_FILES]


def repo_dir() -> Path:
    return ROOT / REPO


def _repo_files() -> dict[str, int]:
    """{path: size} straight from the repo manifest."""
    url = f"{HF}/api/models/{REPO}?blobs=true"
    with urllib.request.urlopen(url, timeout=60) as r:
        payload = json.load(r)
    return {
        s["rfilename"]: s.get("size") or 0
        for s in payload.get("siblings", [])
        if "rfilename" in s
    }


def _wanted(available: dict[str, int]) -> list[str]:
    want = [f for f in BASE_FILES if f in available]
    # Every voice embedding: 54 files at ~510 KB, and a voice the mirror is
    # missing is a voice that silently reaches for the internet mid-sentence.
    want += sorted(f for f in available if f.startswith("voices/") and f.endswith(".bin"))
    for dtype in wanted_dtypes():
        f = DTYPE_FILES[dtype]
        if f in available:
            want.append(f)
        else:
            log.warning("%s has no file for dtype %s (%s)", REPO, dtype, f)
    return want


def manifest() -> dict:
    """What is actually on disk right now. The client reads this to decide
    whether the local mirror is worth pointing at."""
    root = repo_dir()
    files: dict[str, int] = {}
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file() and not p.name.endswith(".part"):
                files[str(p.relative_to(root))] = p.stat().st_size
    dtypes = [d for d, f in DTYPE_FILES.items() if f in files]
    voices = sorted(
        Path(f).stem for f in files if f.startswith("voices/") and f.endswith(".bin")
    )
    return {
        "repo": REPO,
        "enabled": enabled(),
        "complete": bool(dtypes) and bool(voices) and "config.json" in files,
        "dtypes": dtypes,
        "voices": voices,
        "files": len(files),
        "bytes": sum(files.values()),
        "sync": dict(_state),
    }


def sync(force: bool = False) -> dict:
    """Download anything missing. Safe to call repeatedly: a file that is
    already on disk at the right size is left alone."""
    if not enabled() and not force:
        _state.update(status="disabled")
        return manifest()

    with _sync_lock:
        _state.update(status="syncing", error="")
        root = repo_dir()
        try:
            available = _repo_files()
        except (urllib.error.URLError, OSError, ValueError) as e:
            # No network is the normal case on a machine that already synced —
            # report it and keep serving whatever is on disk.
            _state.update(status="offline", error=str(e))
            log.warning("browser asset sync skipped: %s", e)
            return manifest()

        want = _wanted(available)
        fetched = downloaded_bytes = 0
        for rel in want:
            dest = root / rel
            size = available.get(rel) or 0
            if dest.exists() and (size == 0 or dest.stat().st_size == size):
                continue
            url = f"{HF}/{REPO}/resolve/main/{rel}"
            try:
                _download(url, dest)
            except (urllib.error.URLError, OSError) as e:
                _state.update(status="error", error=f"{rel}: {e}")
                log.warning("browser asset %s failed: %s", rel, e)
                return manifest()
            fetched += 1
            downloaded_bytes += dest.stat().st_size

        _state.update(status="ready", files=fetched, bytes=downloaded_bytes,
                      dtypes=wanted_dtypes(), error="")
        if fetched:
            log.info("mirrored %d browser asset(s), %.1f MB", fetched,
                     downloaded_bytes / 1e6)
        return manifest()


def sync_in_background() -> None:
    """Startup hook: never block health on a 90 MB download."""
    if not enabled():
        _state.update(status="disabled")
        return
    root = repo_dir()
    root.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=sync, name="browser-assets", daemon=True).start()
