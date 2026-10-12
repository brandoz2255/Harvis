"""Turn the model's source markers into a numbered citation list.

The prompt asks for ``[SOURCE 3]``, but models also write ``[SOURCE 3, Para 2]``,
``[SOURCE 1: Para 5]``, ``[S3]``, ``【SOURCE 3】``, ``[SOURCE 1, SOURCE 2]``, a bare
``SOURCE 3`` or a title (``[Source: My Paper]``). The old extractor only knew
``[S3]`` and ``[3]``, so a normal answer matched nothing and fell through to
"top three chunks, no quote".

``resolve_citations`` returns the answer with every marker rewritten to ``[k]``,
where k is the position in the returned citation list (order of first mention), so
the number in the text and the numbered list under the answer always agree. Each
citation carries the snippet of the chunk it points at.
"""
from __future__ import annotations

import re
from typing import Any, List, Sequence, Tuple

_GROUP = re.compile(r"\[([^\[\]]{1,120})\]|【([^【】]{1,120})】")
_NUMBERED = re.compile(r"^\s*(?:sources?|s)\s*[:#]?\s*\d", re.IGNORECASE)
_TITLED = re.compile(r"^\s*sources?\s*:\s*(.+)$", re.IGNORECASE)
_LOCATOR = re.compile(r"\b(?:paragraphs?|para|pages?|pg|p|sections?|sec)\.?\s*\d+(?:\s*[-–]\s*\d+)?", re.IGNORECASE)
_BARE = re.compile(r"\bSOURCE\s+(\d+)(?:\s*[,:]?\s*(?:para|page|section)\s*\.?\s*\d+)?", re.IGNORECASE)
_PLAIN_NUMBERS = re.compile(r"^\s*\d+(?:\s*,\s*\d+)*\s*$")
_PARA_TAIL = re.compile(r",\s*(?:para|page|section|p\.|pg)\b.*$", re.IGNORECASE)

SNIPPET_CHARS = 240


def snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """The start of a chunk as one tidy line, cut at a word boundary."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _numbers_in(inner: str) -> List[int]:
    return [int(n) for n in re.findall(r"\d+", _LOCATOR.sub("", inner))]


def _title_index(chunks: Sequence[Any]) -> dict:
    out: dict = {}
    for i, c in enumerate(chunks, 1):
        title = (getattr(c, "source_title", "") or "").strip().lower()
        if title:
            out.setdefault(title, i)
    return out


def _lookup_title(raw: str, titles: dict) -> int:
    key = _PARA_TAIL.sub("", raw.strip()).strip().lower()
    if not key:
        return 0
    if key in titles:
        return titles[key]
    for title, idx in titles.items():
        if title in key or key in title:
            return idx
    return 0


def resolve_citations(answer: str, chunks: Sequence[Any]) -> Tuple[str, List[Any], bool]:
    """``(answer with [k] markers, ordered chunk list cited, any_explicit_marker)``.

    ``chunks`` are the retrieval results in prompt order (``SOURCE n`` is
    ``chunks[n-1]``). Markers that point outside the context are removed rather
    than left as numbers that match nothing.
    """
    total = len(chunks)
    order: List[int] = []  # context index (1-based) in order of first mention
    titles = _title_index(chunks)
    explicit = False

    def slot(n: int) -> int:
        if n not in order:
            order.append(n)
        return order.index(n) + 1

    def group(match: "re.Match[str]") -> str:
        nonlocal explicit
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        numbers: List[int] = []
        if _NUMBERED.match(inner) or (_PLAIN_NUMBERS.match(inner) and match.group(1) is not None):
            numbers = _numbers_in(inner)
        else:
            titled = _TITLED.match(inner)
            if not titled:
                return match.group(0)
            idx = _lookup_title(titled.group(1), titles)
            if not idx:
                return match.group(0)
            numbers = [idx]
        explicit = True
        valid = []
        for n in numbers:
            if 1 <= n <= total and n not in valid:
                valid.append(n)
        return "".join(f"[{slot(n)}]" for n in valid)

    def bare(match: "re.Match[str]") -> str:
        nonlocal explicit
        n = int(match.group(1))
        explicit = True
        return f"[{slot(n)}]" if 1 <= n <= total else ""

    out = _GROUP.sub(group, answer or "")
    out = _BARE.sub(bare, out)
    return out, [chunks[n - 1] for n in order], explicit
