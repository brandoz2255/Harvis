"""How much source text one notebook answer may carry.

Both numbers are read from the environment on every call, so an operator can change
them with a restart and a test can change them with ``monkeypatch.setenv``. A bad
value (not a number, zero, negative) falls back to the default; a value past the cap
is clamped to it. The context size is the exception below: a number under its floor is
raised to the floor instead of being ignored.
"""
import os
from typing import List

CHUNKS_ENV = "NOTEBOOK_RAG_CHUNKS"
CONTEXT_CHARS_ENV = "NOTEBOOK_RAG_CONTEXT_CHARS"

DEFAULT_CHUNKS = 8
HARD_MAX_CHUNKS = 20

# Answers run with num_ctx 8192 and reserve up to 1024 tokens for the reply. Sources at the
# default 9000 characters (about 2.5k tokens), 6000 characters of conversation history and
# the instructions fit with room to spare.
NUM_CTX = 8192
DEFAULT_CONTEXT_CHARS = 9000
MIN_CONTEXT_CHARS = 2000
HARD_MAX_CONTEXT_CHARS = 40000


def _env_int(name: str, default: int, hard_max: int, hard_min: int = 1, raise_to_min: bool = False) -> int:
    try:
        value = int(os.getenv(name, "").strip())
    except ValueError:
        return default
    if value < hard_min:
        return hard_min if raise_to_min else default
    return min(value, hard_max)


def rag_chunk_limit() -> int:
    """Passages retrieved for one answer when the caller did not ask for a number."""
    return _env_int(CHUNKS_ENV, DEFAULT_CHUNKS, HARD_MAX_CHUNKS)


def rag_context_budget() -> int:
    """Characters of source text (headers included) one prompt may carry."""
    return _env_int(
        CONTEXT_CHARS_ENV, DEFAULT_CONTEXT_CHARS, HARD_MAX_CONTEXT_CHARS, MIN_CONTEXT_CHARS, raise_to_min=True
    )


def clamp_top_k(asked: int) -> int:
    """A caller's explicit passage count, held to the hard cap and never below one."""
    return max(1, min(int(asked), HARD_MAX_CHUNKS))


def fit_to_budget(texts: List[str], budget: int) -> List[str]:
    """Shorten passages so their total is at most ``budget`` characters.

    Every passage keeps a place (the citation numbers must still line up with the
    prompt). Short passages keep all their text and hand the room they do not need to
    the longer ones; the longer ones are cut at the same length and end in an ellipsis.
    """
    if sum(len(t) for t in texts) <= budget:
        return list(texts)
    allowance = [0] * len(texts)
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    left = max(budget, 0)
    for rank, i in enumerate(order):
        share = left // (len(texts) - rank)
        allowance[i] = min(len(texts[i]), share)
        left -= allowance[i]
    return [t if len(t) <= allowance[i] else t[:max(allowance[i] - 1, 0)].rstrip() + "…"
            for i, t in enumerate(texts)]
