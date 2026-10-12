"""Near-duplicate check for saved memories.

"Remember that my exam is Friday" is saved twice: once as typed (the regex
path, "Asked Harvis to remember: …") and once reworded by the model extractor
("User's exam is on Friday"). The wording differs, so an exact or substring
check misses it. Two memories count as the same when, after dropping filler
words, one's content words are almost all contained in the other's.
"""
from __future__ import annotations

import re

_LEAD_RE = re.compile(r"^\s*(?:asked harvis to remember|remember(?: that)?|note(?: that)?)\s*[:,-]?\s*", re.I)
# Words that carry no fact: articles, auxiliaries, and the "user" framing an extractor adds.
_FILLER = frozenset(
    "a an the is are was were be been am to of on in at for and that this it its "
    "user users person my their his her your our me i has have had do does".split())
MIN_CONTAINMENT = 0.8


def _stem(word: str) -> str:
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    return word


def content_words(text: str) -> frozenset[str]:
    text = _LEAD_RE.sub("", (text or "").replace("'s", ""))
    words = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(_stem(w) for w in words if w not in _FILLER)


def same_memory(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` say the same thing in different words."""
    wa, wb = content_words(a), content_words(b)
    if not wa or not wb:
        return False
    overlap = len(wa & wb)
    if overlap < 2 and min(len(wa), len(wb)) > 1:
        return False
    return overlap / min(len(wa), len(wb)) >= MIN_CONTAINMENT and overlap / max(len(wa), len(wb)) >= 0.5


def find_duplicate(candidate: str, existing: list[tuple[int, str]]) -> int | None:
    """The id of the first of ``existing`` ((id, content) pairs) that duplicates ``candidate``."""
    for memory_id, content in existing:
        if same_memory(candidate, content):
            return memory_id
    return None
