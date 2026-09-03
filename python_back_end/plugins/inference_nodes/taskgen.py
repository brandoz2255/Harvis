"""One-shot text generation on an inference node for the small background jobs.

Chat titles, tags and follow-ups are normally a tiny Ollama model's job. While a node
holds the GPU (FreeToken keeps ~6 GB of an 8 GB card) that model cannot load and
Ollama answers 500, so those lanes fall back to a heuristic ("first six words").
This asks the node that *is* awake instead: thinking off, a short budget, no stream.
Every failure returns ``None`` — the callers keep their heuristic as the last resort.
"""

from __future__ import annotations

import logging

import httpx

from .probe import snapshot
from .types import NodeSpec

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 45.0


async def _post(spec: NodeSpec, body: dict, timeout: float) -> str | None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), headers=spec.headers()) as hc:
        r = await hc.post(spec.chat_url, json=body)
    if r.status_code != 200:
        logger.warning("inference_nodes: task-gen on %s → HTTP %s", spec.name, r.status_code)
        return None
    try:
        choice = (r.json().get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
    except Exception:
        logger.warning("inference_nodes: task-gen on %s → unparseable body", spec.name)
        return None
    return content if isinstance(content, str) else None


async def complete(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 32,
    temperature: float = 0.0,
    timeout: float = DEFAULT_TIMEOUT_S,
    model: str | None = None,
) -> str | None:
    """Text from the first reachable OpenAI-dialect node, by priority; ``None`` if none.

    ``model`` is used when that node serves it, otherwise the node's first model —
    a title does not care which 35B model writes it.
    """
    if not (prompt or "").strip():
        return None
    states = await snapshot()
    for st in sorted(states.values(), key=lambda s: (s.spec.priority, s.spec.name)):
        if not st.reachable or st.spec.dialect != "openai" or not st.models:
            continue
        mid = model if model in st.models else sorted(st.models)[0]
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": mid,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            text = await _post(st.spec, body, timeout)
        except Exception as e:
            logger.warning("inference_nodes: task-gen on %s raised %s", st.spec.name, type(e).__name__)
            continue
        if text and text.strip():
            logger.info("inference_nodes: task-gen served by %s (%s)", st.spec.name, mid)
            return text.strip()
    return None
