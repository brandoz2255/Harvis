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
# A failed read is retried sooner, but not on every picker open: an Ollama that is
# down would otherwise cost its timeout each time.
_THINKING_FAIL_TTL = 30.0
_thinking: tuple[float, frozenset[str]] = (0.0, frozenset())
_thinking_ttl = _THINKING_TTL
# Read alongside _thinking: models that can only think (Qwen3-4B-Thinking-2507 starts every
# reply inside <think>), and each chat-capable tag's size, smallest first, for picking a
# quick stand-in.
_thinking_only: frozenset[str] = frozenset()
_by_size: tuple[str, ...] = ()
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
    global _thinking, _thinking_ttl, _thinking_only, _by_size
    async with _thinking_lock:
        stamp, names = _thinking
        if stamp and time.monotonic() - stamp < _thinking_ttl:
            return names
        base = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
        found: set[str] = set()
        only: set[str] = set()
        sized: list[tuple[int, str]] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=1.5)) as client:
                tags = (await client.get(f"{base}/api/tags")).json().get("models") or []
                from owui_compat.ollama_hosts import drop_cloud

                tags = drop_cloud(tags)
                tag_names = [str(tag.get("name") or "") for tag in tags]
                shows = await asyncio.gather(
                    *(client.post(f"{base}/api/show", json={"model": name}) for name in tag_names),
                    return_exceptions=True)
                for tag, name, show in zip(tags, tag_names, shows):
                    if isinstance(show, BaseException):
                        continue
                    info = show.json()
                    caps = info.get("capabilities") or []
                    if "thinking" in caps:
                        found.add(name)
                        finetune = str((info.get("model_info") or {}).get("general.finetune") or "")
                        if "thinking" in finetune.lower():
                            only.add(name)
                    if "completion" in caps and not is_hidden_model(name):
                        sized.append((int(tag.get("size") or 0), name))
        except Exception as exc:  # noqa: BLE001
            log.warning("hermes_ui: could not read Ollama model capabilities: %s", exc)
            _thinking, _thinking_ttl = (time.monotonic(), names), _THINKING_FAIL_TTL
            return names
        _thinking, _thinking_ttl = (time.monotonic(), frozenset(found)), _THINKING_TTL
        _thinking_only, _by_size = frozenset(only), tuple(n for _, n in sorted(sized))
        return _thinking[1]


async def voice_model(model: str) -> str:
    """The model a spoken turn runs on.

    A model that can only think spends a voice turn's small token budget reasoning, and
    with thinking off Ollama hands that reasoning back as the answer, so the call reads
    "Okay, the user asked me to..." aloud. Such a model is swapped for HARVIS_VOICE_MODEL,
    else the smallest local chat model that answers directly. Any other model is kept.
    """
    await thinking_models()
    if model not in _thinking_only:
        return model
    pinned = os.getenv("HARVIS_VOICE_MODEL", "").strip()
    if pinned:
        return pinned
    from notebooks.embedder_status import is_embedder

    for name in _by_size:
        if name not in _thinking_only and not is_embedder(name):
            return name
    return model


def ollama_effort(effort: str) -> str:
    """The Hermes effort scale folded onto Ollama's three levels (plus off)."""
    return _OLLAMA_EFFORT.get((effort or "").strip().lower(), _OLLAMA_EFFORT[DEFAULT_EFFORT])
