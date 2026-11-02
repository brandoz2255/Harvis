"""Turn a follow-up question into a standalone search query.

"What about the second one?" retrieves nothing useful on its own. When there is
conversation history, one short model call rewrites it ("What is the second
experiment's sample size?") for retrieval only; the user's own words are still what is
shown, saved and answered. Any failure or timeout falls back to the raw message.
"""
import asyncio
import logging
import re
from typing import Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

Complete = Callable[[str], Awaitable[Optional[str]]]

REWRITE_TIMEOUT = 20.0
SELF_CONTAINED_WORDS = 12
MAX_QUERY_CHARS = 300
_TURN_CHARS = 400
_TURNS_SHOWN = 4

_REFERENCES = re.compile(
    r"\b(it|its|they|them|their|theirs|this|that|these|those|he|him|his|she|her|hers|there|"
    r"also|too|more|another|other|same|above|previous|earlier|former|latter|again|else|one|ones)\b",
    re.IGNORECASE,
)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_LABEL = re.compile(r"^\s*(?:standalone\s+)?(?:search\s+)?(?:query|question|rewrite[d]?)\s*:\s*", re.IGNORECASE)


def needs_rewrite(message: str) -> bool:
    """A short message or one with a pronoun/reference word may depend on earlier turns."""
    text = message.strip()
    return len(text.split()) <= SELF_CONTAINED_WORDS or bool(_REFERENCES.search(text))


def build_prompt(message: str, history: List[Dict[str, str]]) -> str:
    shown = []
    for turn in history[-_TURNS_SHOWN:]:
        who = "User" if turn["role"] == "user" else "Assistant"
        text = " ".join(turn["content"].split())
        shown.append(f"{who}: {text[:_TURN_CHARS]}{'…' if len(text) > _TURN_CHARS else ''}")
    return (
        "Rewrite the user's last message as one standalone search query that makes sense with no "
        "conversation around it. Replace pronouns and references with the names they stand for. "
        "Keep the meaning and the language. If it is already standalone, repeat it. "
        "Output only the query, on one line.\n\n"
        "Conversation:\n" + "\n".join(shown) + f"\n\nLast message: {message.strip()}\n\nStandalone query:"
    )


def clean_rewrite(raw: Optional[str], fallback: str) -> str:
    """The first line of the model's reply without labels or quotes, or ``fallback`` if unusable."""
    text = _THINK.sub("", raw or "").strip()
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = _LABEL.sub("", line).strip().strip("\"'`“”").strip()
    if not line or len(line) > MAX_QUERY_CHARS:
        return fallback
    return line


async def rewrite_followup(
    message: str,
    history: Optional[List[Dict[str, str]]],
    complete: Complete,
    *,
    timeout: float = REWRITE_TIMEOUT,
) -> str:
    """A standalone version of ``message`` for retrieval, or ``message`` itself.

    ``complete`` takes a prompt and returns the model's text (or None). It is not called
    when there is no history or the message already stands alone.
    """
    if not history or not needs_rewrite(message):
        return message
    try:
        raw = await asyncio.wait_for(complete(build_prompt(message, history)), timeout)
    except Exception:  # includes asyncio.TimeoutError; retrieval must never fail because of this
        logger.info("Query rewrite failed or timed out; using the raw message", exc_info=True)
        return message
    return clean_rewrite(raw, message)
