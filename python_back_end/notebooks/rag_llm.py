"""One round trip to Ollama's /api/chat, shared by the notebook answer and the query rewrite."""
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def separate_thinking(text: str) -> Tuple[str, str]:
    """Split inline <think>...</think> blocks from the answer: ``(reasoning, answer)``."""
    reasoning = ""
    remaining = text

    while "<think>" in remaining and "</think>" in remaining:
        start = remaining.find("<think>")
        end = remaining.find("</think>")

        if start != -1 and end != -1 and end > start:
            thought = remaining[start + len("<think>"):end].strip()
            if thought:
                reasoning += thought + "\n\n"
            remaining = remaining[:start] + remaining[end + len("</think>"):]
        else:
            break

    return reasoning.strip(), remaining.strip()


async def post_chat(
    base_url: str, model: str, messages: List[Dict[str, str]], options: Dict[str, Any], timeout: float
) -> Optional[Tuple[str, Optional[str]]]:
    """POST to ``/api/chat``; ``(answer, reasoning)``, or None if this model gave nothing.

    A requests ConnectionError propagates so the caller can stop trying a dead host.
    """
    # Offload the blocking HTTP call to a thread so the async event loop
    # (and the rest of the backend) isn't frozen for the whole generation.
    response = await asyncio.to_thread(
        requests.post,
        f"{base_url}/api/chat",
        json={"model": model, "messages": messages, "stream": False, "think": False, "options": options},
        timeout=timeout,
    )
    if response.status_code == 404:
        logger.debug(f"Model {model} not found at {base_url}, trying next...")
        return None
    if response.status_code != 200:
        logger.warning(f"LLM request with {model} failed: {response.status_code}")
        return None

    data = response.json()
    reply = data.get("message") or {}
    answer = reply.get("content") or ""
    # Reasoning models (gpt-oss, etc.) may put chain-of-thought in a separate Ollama
    # `thinking` field and/or inline <think>...</think>.
    reasoning = reply.get("thinking") or data.get("thinking") or None
    if "<think>" in answer and "</think>" in answer:
        inline_reasoning, answer = separate_thinking(answer)
        reasoning = reasoning or inline_reasoning

    answer = answer.strip()
    if not answer:
        # Reasoning-only response (all tokens went to the thinking channel, `content`
        # is blank). Don't persist an empty bubble; the caller tries the next model.
        logger.warning(f"Model {model} returned empty content (reasoning-only); trying next model")
        return None
    return answer, reasoning
