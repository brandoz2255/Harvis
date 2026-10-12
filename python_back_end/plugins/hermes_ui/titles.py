"""A short chat title, written by the session's own model after the first reply.

Runs off the turn's critical path: the turn has already finished and been
saved, so a slow or failing title model costs nothing but the stand-in title
(the first message, truncated) the row already has.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from plugins import people

from . import chat, providers, store, turn_models
from .models import thinking_models

log = logging.getLogger("hermes_ui.titles")

TITLE_TIMEOUT = 45.0
MAX_WORDS = 6
MAX_CHARS = 60

_PROMPT = ("Write a title for this conversation: 3 to 6 words, in the user's language, no quotes, no trailing "
           "punctuation, no markdown. Reply with the title only.")


def clean_title(text: str) -> str:
    """The first line of ``text`` that reads like a name, or ""."""
    text = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"^.*?</think(?:ing)?>", "", text, flags=re.DOTALL | re.IGNORECASE)
    for line in text.splitlines():
        s = re.sub(r"^(?:[-*+•]|\d+[.)])\s+", "", line.strip())
        s = s.lstrip("#").replace("**", "").replace("__", "").strip()
        s = re.sub(r"^(?:chat\s+)?title\s*[:\-]\s*", "", s, flags=re.IGNORECASE)
        s = s.strip().strip("\"'`“”‘’").strip().rstrip(".!,;:?…").strip()
        if not s or s.lower().startswith(("here", "sure", "certainly", "of course", "okay", "note")):
            continue
        words = s.split()
        if len(words) > 12:  # a sentence, not a name; try the next line
            continue
        words = words[:MAX_WORDS]
        while len(words) > 1 and len(" ".join(words)) > MAX_CHARS:
            words.pop()
        out = " ".join(words)[:MAX_CHARS].strip()
        if out:
            return out
    return ""


def _excerpt(msgs: list[dict]) -> list[dict]:
    first_user = next((m for m in msgs if m["role"] == "user"), None)
    first_reply = next((m for m in msgs if m["role"] == "assistant" and m.get("content") and not m.get("error")), None)
    out = []
    if first_user:
        out.append({"role": "user", "content": (first_user["content"] or "")[:800]})
    if first_reply:
        out.append({"role": "assistant", "content": first_reply["content"][:800]})
    return out


async def generate(pool, user_id: int, token: str, model: str, msgs: list[dict]) -> str:
    """Ask the session's model for a title; "" when it fails or answers nonsense."""
    excerpt = _excerpt(msgs)
    if not excerpt:
        return ""
    endpoint = await providers.resolve_active_endpoint(pool, user_id)
    if model.startswith(turn_models.MOA_PREFIX):
        model = ""
    if not endpoint:
        # Same model limits as the turn itself; the turn already spent today's message.
        admitted = await people.admit_turn(pool, user_id, model, count=False)
        if not admitted.ok:
            return ""
        model = admitted.model or model
    effort = "none" if model and not endpoint and model in await thinking_models() else ""
    turn = [{"role": "system", "content": _PROMPT}, *excerpt,
            {"role": "user", "content": "Title for the conversation above:"}]
    out: list[str] = []

    async def collect() -> None:
        async for kind, delta in chat.stream_turn(
                token, turn, model, endpoint, "chat", effort,
                extra={"harvis_research": False, "harvis_plain": True, "max_tokens": 32}):
            if kind == "text":
                out.append(delta)

    try:
        await asyncio.wait_for(collect(), TITLE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        log.info("hermes_ui: title generation failed: %s", exc)
        return ""
    return clean_title("".join(out))


async def name_session(pool, user_id: int, token: str, sid: str, model: str, msgs: list[dict]) -> Optional[str]:
    """Generate and store the title; the new title, or None when nothing changed."""
    title = await generate(pool, user_id, token, model, msgs)
    if title and await store.set_generated_title(pool, user_id, sid, title):
        return title
    return None
