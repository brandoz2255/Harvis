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
    from .embedding_provider import configured_provider_name

    if configured_provider_name() == "openai":
        return await _remote_status()
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


async def _remote_status() -> dict[str, Any]:
    """Status when NOTEBOOK_EMBED_PROVIDER=openai. Documents are sent to that server, so the
    answer says so; nothing is installed from here and no document text is sent by the probe."""
    from .embedding_provider import ProviderConfigError, remote_headers, remote_settings

    base: dict[str, Any] = {
        "id": "notebooks",
        "provider": "openai",
        "leaves_machine": True,
        "model": None,
        "install_tag": None,
        "download_mb": None,
    }
    try:
        settings = remote_settings()
    except ProviderConfigError as exc:
        return {**base, "state": "unsupported", "probe": None, "reason": str(exc)}
    base["probe"] = f"GET {settings.base_url}/models"
    try:
        if settings.guarded:
            from plugins.hermes_ui.providers import guarded_client

            hc = guarded_client(timeout=_TIMEOUT)
        else:
            hc = httpx.AsyncClient(timeout=_TIMEOUT)
        async with hc:
            r = await hc.get(f"{settings.base_url}/models", headers=remote_headers(settings))
    except Exception as exc:
        return {**base, "state": "unreachable", "reason": f"embedding service unreachable ({type(exc).__name__})"}
    if r.status_code in (401, 403):
        return {**base, "state": "unreachable", "reason": "the embedding service rejected the key (check NOTEBOOK_EMBED_API_KEY)"}
    if r.status_code != 200:
        return {**base, "state": "unreachable", "reason": f"embedding service answered HTTP {r.status_code}"}
    return {
        **base,
        "state": "ready",
        "model": settings.model,
        "reason": f"{settings.model} at the configured embedding service; the text of your sources is sent there",
    }
