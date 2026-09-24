"""Which Harvis models the Hermes UI offers.

David, 2026-09-12: Gemini ids in Harvis's catalog are retired at Google (404)
and Ollama's `:cloud` passthrough tags need paid credits, so neither is offered
or used as a default until the catalog is fixed. Embedding models cannot chat,
so they are never offered in the chat picker either.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

log = logging.getLogger("hermes_ui.models")

HIDDEN_PROVIDERS = {"gemini"}

# Ollama's OpenAI endpoint takes low / medium / high / none, and answers 400
# ("does not support thinking") when a non-thinking model gets any of them.
_OLLAMA_EFFORT = {"none": "none", "minimal": "low", "low": "low", "medium": "medium",
                  "high": "high", "xhigh": "high", "max": "high", "ultra": "high"}
DEFAULT_EFFORT = "medium"
_THINKING_TTL = 300.0
_thinking: tuple[float, frozenset[str]] = (0.0, frozenset())
_thinking_lock = asyncio.Lock()


def is_hidden_model(model_id: str, provider: str = "") -> bool:
    mid = (model_id or "").strip().lower()
    return ((provider or "").lower() in HIDDEN_PROVIDERS or mid.startswith("gemini/") or mid.endswith(":cloud")
            or "embed" in mid.split(":", 1)[0])


async def thinking_models() -> frozenset[str]:
    """Local Ollama models whose `/api/show` lists the `thinking` capability.

    Cached for five minutes; an unreachable Ollama yields an empty set, so the
    picker falls back to offering no effort rather than a broken one.
    """
    global _thinking
    async with _thinking_lock:
        stamp, names = _thinking
        if names and time.monotonic() - stamp < _THINKING_TTL:
            return names
        base = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
        found: set[str] = set()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                tags = (await client.get(f"{base}/api/tags")).json().get("models") or []
                for tag in tags:
                    name = str(tag.get("name") or "")
                    show = (await client.post(f"{base}/api/show", json={"model": name})).json()
                    if "thinking" in (show.get("capabilities") or []):
                        found.add(name)
        except Exception as exc:  # noqa: BLE001
            log.warning("hermes_ui: could not read Ollama model capabilities: %s", exc)
            return names
        _thinking = (time.monotonic(), frozenset(found))
        return _thinking[1]


def ollama_effort(effort: str) -> str:
    """The Hermes effort scale folded onto Ollama's three levels (plus off)."""
    return _OLLAMA_EFFORT.get((effort or "").strip().lower(), _OLLAMA_EFFORT[DEFAULT_EFFORT])
