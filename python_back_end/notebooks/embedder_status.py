"""Is Notebooks ready to read sources?

Notebooks runs on this backend and needs exactly one thing a fresh install lacks:
an embedding model on the model server. Without one, ingestion falls back to
whatever chat model is installed, which is slow and makes poor search vectors.
So "install Notebooks" means pulling that one model, and this module is how the
setup wizard and the Notebooks page find out whether that has happened.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

EMBEDDER_TAG = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
# Measured, not quoted: nomic-embed-text:latest reports 274,302,450 bytes in
# Ollama's /api/tags. Only meaningful when EMBEDDER_TAG is left at its default.
EMBEDDER_DOWNLOAD_MB = 274
# Name fragments that mark a dedicated embedder, so a server that already has
# mxbai-embed-large or all-minilm is not told to download another one.
_EMBEDDER_MARKS = ("embed", "minilm", "bge-")
_TIMEOUT = httpx.Timeout(5.0)


def is_embedder(name: str) -> bool:
    n = (name or "").lower()
    return n.split(":")[0] == EMBEDDER_TAG.lower().split(":")[0] or any(m in n for m in _EMBEDDER_MARKS)


async def embedder_status() -> dict[str, Any]:
    """``state`` is one of ready, not_installed, unsupported, unreachable.

    unsupported: the server answers but is not Ollama (no /api/tags), so Harvis
    cannot pull for it and the operator has to load an embedder there themselves.
    """
    url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
    probe = f"GET {url}/api/tags"
    base = {
        "id": "notebooks",
        "model": None,
        "install_tag": EMBEDDER_TAG,
        "download_mb": EMBEDDER_DOWNLOAD_MB,
        "probe": probe,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as hc:
            r = await hc.get(f"{url}/api/tags")
    except Exception as exc:
        return {**base, "state": "unreachable", "reason": f"model server unreachable: {str(exc)[:160]}"}
    if r.status_code == 404:
        return {
            **base,
            "state": "unsupported",
            "reason": f"this model server is not Ollama, so Harvis cannot download for it — load an "
            f"embedding model there yourself (for example {EMBEDDER_TAG})",
        }
    if r.status_code != 200:
        return {**base, "state": "unreachable", "reason": f"model server answered HTTP {r.status_code}"}
    names = [str(m.get("name") or m.get("model") or "") for m in (r.json() or {}).get("models") or []]
    found = next((n for n in names if is_embedder(n)), None)
    if found:
        return {**base, "state": "ready", "model": found, "reason": f"{found} is installed"}
    return {
        **base,
        "state": "not_installed",
        "reason": f"needs the {EMBEDDER_TAG} embedding model ({EMBEDDER_DOWNLOAD_MB} MB) to read your sources",
    }
