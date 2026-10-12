"""One-shot text generation on an inference node for the small background jobs.

Chat titles, tags and follow-ups are normally a tiny Ollama model's job. While a node
holds the GPU (FreeToken keeps ~6 GB of an 8 GB card) that model cannot load and
Ollama answers 500, so those lanes fall back to a heuristic ("first six words").
This asks the node that *is* awake instead: thinking off, a short budget, no stream.
Every failure returns ``None`` — the callers keep their heuristic as the last resort.

Both dialects work. An Ollama node (one paired by PIN, dialect ``ollama``) also serves
``/v1/chat/completions``, which the node helper lets through, and ``NodeSpec.headers()``
carries the node's bearer token exactly as the probe and ``model_proxy`` send it.
"""

from __future__ import annotations

import logging
import re

import httpx

from .probe import snapshot
from .types import NodeSpec

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 45.0

# A node can serve embedding and rerank models next to chat models; a title must never
# be asked of one of those (Ollama lists them in the same tag list).
_NOT_CHAT = ("embed", "bge-", "minilm", "rerank", "nomic")
_THINK_BLOCK = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _chat_models(models) -> list[str]:
    return sorted(m for m in models if not any(k in m.lower() for k in _NOT_CHAT))


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
        if not st.reachable:
            continue
        chat = _chat_models(st.models)
        if not chat:
            continue
        mid = model if model in chat else chat[0]
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
        if st.spec.dialect == "ollama":
            # Ollama ignores chat_template_kwargs; its OpenAI shim switches thinking off
            # with reasoning_effort, and a thinking model would otherwise spend the whole
            # short budget before writing a word.
            body["reasoning_effort"] = "none"
        try:
            text = await _post(st.spec, body, timeout)
        except Exception as e:
            logger.warning("inference_nodes: task-gen on %s raised %s", st.spec.name, type(e).__name__)
            continue
        if text:
            text = _THINK_BLOCK.sub("", text)
        if text and text.strip():
            logger.info("inference_nodes: task-gen served by %s (%s)", st.spec.name, mid)
            return text.strip()
    return None
