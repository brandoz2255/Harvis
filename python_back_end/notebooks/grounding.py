"""Decide whether retrieval found anything worth answering from.

The prompt alone cannot be trusted to refuse: a small model will answer an unrelated
question from whatever passages it was handed. This gate runs before generation.
"""
import os
from typing import Optional, Sequence

MIN_SIMILARITY_ENV = "NOTEBOOK_MIN_SIMILARITY"
DEFAULT_MIN_SIMILARITY = 0.30
MAX_MIN_SIMILARITY = 0.9

REFUSAL_TEXT = "I could not find that in your sources."


def min_similarity() -> float:
    """Cosine floor from NOTEBOOK_MIN_SIMILARITY: default 0.30, clamped to 0..0.9, bad value = default."""
    try:
        value = float(os.getenv(MIN_SIMILARITY_ENV, "").strip())
    except ValueError:
        return DEFAULT_MIN_SIMILARITY
    if value != value:  # NaN
        return DEFAULT_MIN_SIMILARITY
    return max(0.0, min(value, MAX_MIN_SIMILARITY))


def best_similarity(chunks: Sequence) -> Optional[float]:
    """Highest vector similarity among the chunks; None if none carries one (keyword-only hits)."""
    scores = [c.vector_score for c in chunks if getattr(c, "vector_score", None) is not None]
    return max(scores) if scores else None


def is_grounded(chunks: Sequence) -> bool:
    """True when at least one retrieved chunk is close enough to the question to answer from.

    A chunk with no vector similarity came from the keyword leg alone, which only returns
    passages that literally contain the query terms, so it counts as grounded evidence.
    """
    if not chunks:
        return False
    if any(getattr(c, "vector_score", None) is None for c in chunks):
        return True
    return best_similarity(chunks) >= min_similarity()  # type: ignore[operator]
