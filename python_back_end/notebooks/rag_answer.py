"""What a notebook answer is made of: retrieval result, resolved citations, the finished answer."""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .citations import resolve_citations, snippet
from .models import ChunkWithScore, Citation

# A model that says it found nothing is declining, not making an unsupported claim.
_DECLINE = re.compile(r"\b(?:don'?t|do not|cannot|can'?t|could not|couldn'?t|unable to)\s+(?:see|find|locate)\b", re.I)


@dataclass
class Retrieval:
    """What retrieval found for one question."""
    chunks: List[ChunkWithScore]
    rewritten_query: str  # the standalone query retrieval used; equals the message when not rewritten
    embedded: bool  # False when the query could not be embedded (keyword-only retrieval, or none)
    # Summary passages are in ``chunks`` (first), so the similarity floor must not judge them.
    floor_exempt: bool = False
    report: Optional[Dict[str, Any]] = None  # summary_context.context_report; None when no summaries were used
    empty_reply: Optional[str] = None  # why there is nothing to answer from, when it is not an empty notebook


@dataclass
class AnswerResult:
    """A finished answer, with the flags a UI needs to badge it."""
    answer: str
    citations: List[Citation]
    unsupported: bool = False  # the model cited none of the passages it was given
    refused: bool = False  # nothing close enough was found, so no model was asked
    reasoning: Optional[str] = None
    model_used: str = ""
    chunks: List[ChunkWithScore] = field(default_factory=list)
    rewritten_query: str = ""


def is_unsupported(answer: str, chunks: List[ChunkWithScore]) -> bool:
    """True when the answer cites none of the passages it was given and is not itself a decline."""
    if not chunks:
        return False
    _, cited, _ = resolve_citations(answer, chunks)
    return not cited and not _DECLINE.search(answer[:200])


def resolve_answer(answer: str, chunks: List[ChunkWithScore]) -> Tuple[str, List[Citation], bool]:
    """``(answer with [1] [2]... markers, matching citations, unsupported)``.

    Every citation carries ``quote``, the snippet of the passage it points at. If the model
    cited nothing, no passage is attached: listing passages the answer never used would make
    an ungrounded answer look sourced, so ``unsupported`` is set for the UI to show it as
    not cited.
    """
    text, cited, _explicit = resolve_citations(answer, chunks)
    citations = []
    for cws in cited:
        chunk = cws.chunk
        metadata = chunk.metadata or {}
        start, end = metadata.get("start_char"), metadata.get("end_char")
        located = all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (start, end))
        citations.append(Citation(
            source_id=chunk.source_id,
            source_title=cws.source_title,
            chunk_id=chunk.id,
            page=metadata.get("page"),
            section=metadata.get("section"),
            quote=snippet(chunk.content),
            start_char=start if located else None,
            end_char=end if located else None,
            snippet=snippet(chunk.content),
        ))
    return text, citations, bool(chunks) and not citations and not _DECLINE.search(text[:200])
