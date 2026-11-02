"""One-shot LLM call used to run a prompt over a source's text.

Moved out of onb_compat/router.py so the ingest-time insights and the Sources panel
share one implementation. The call goes to the local Ollama server, never a cloud model.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 8000
_PREFERRED_CHAT_MODELS = ("llama3.1:8b", "granite4.1:8b", "gemma4:e4b", "qwen3:4b")
_resolved_model: Optional[str] = None


def ollama_url() -> str:
    return os.environ.get("OLLAMA_URL", "http://ollama:11434")


def fit_content(text: str, max_chars: int = DEFAULT_MAX_CHARS, spread: bool = False) -> str:
    """``text`` cut to ``max_chars``. With ``spread`` a long text keeps its beginning, its
    middle and its end (half, a quarter, a quarter) instead of only the beginning."""
    text = text or ""
    if len(text) <= max_chars:
        return text
    if not spread:
        return text[:max_chars]
    marker = "\n\n[...]\n\n"
    budget = max_chars - 2 * len(marker)
    head, mid, tail = budget // 2, budget // 4, budget - budget // 2 - budget // 4
    centre = len(text) // 2
    return (
        text[:head] + marker + text[centre - mid // 2 : centre - mid // 2 + mid] + marker + text[len(text) - tail :]
    )


async def run_transformation_llm(
    prompt_template: str,
    content: str,
    model: str,
    *,
    spread: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    num_ctx: int = 8192,
    num_predict: int = 3000,
    timeout: float = 180.0,
) -> str:
    """Run ``prompt_template`` (``{content}`` is replaced) over ``content`` and return the model's text.

    Raises httpx.HTTPError when the model server fails, so a caller can retry.
    """
    prompt = (prompt_template or "{content}").replace("{content}", fit_content(content, max_chars, spread))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{ollama_url()}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_ctx": num_ctx, "num_predict": num_predict},
            },
        )
        resp.raise_for_status()
        return resp.json().get("response", "") or ""


async def default_chat_model() -> str:
    """The server's default local chat model: env override, else the first preferred model
    Ollama reports, else any installed non-embedding model. Empty string when there is none."""
    global _resolved_model
    override = os.getenv("ONB_DEFAULT_CHAT_MODEL", "").strip()
    if override:
        return override
    if _resolved_model:
        return _resolved_model
    installed: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ollama_url()}/api/tags")
        if resp.status_code == 200:
            from owui_compat.ollama_hosts import drop_cloud

            installed = [m.get("name") for m in drop_cloud(resp.json().get("models", [])) if m.get("name")]
    except Exception:
        logger.warning("Could not list Ollama models for insights", exc_info=True)
    for name in _PREFERRED_CHAT_MODELS:
        if name in installed:
            _resolved_model = name
            return name
    generative = [m for m in installed if "embed" not in m.lower()]
    if generative:
        _resolved_model = generative[0]
        return generative[0]
    return ""
