"""Per-source summaries as chat context: the Summary level and "summarize everything" questions.

A source set to Summary in the Sources tab is not searched. The model reads its stored Dense
Summary (and any other saved insight, see ``context_builder.insight_text``) as one cited passage
instead. A broad question ("summarize my sources", "key points") has no passage that is close to
it, so the similarity floor would refuse it; it is answered from every source's summary, or from
the start of its text when it has none yet.

A summary passage is a stand-in ``ChunkWithScore`` (no embedding, no row of its own) so the prompt,
the ``[SOURCE n]`` numbering and the citations work as they do for retrieved passages. Reads are
scoped to one notebook; the caller has already checked the person's role on it.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence
from uuid import UUID, uuid5

from .context_builder import INSIGHT_FALLBACK_CHARS, insight_text
from .models import ChunkWithScore, NotebookChunk

MAX_OVERVIEW_SOURCES = 30

SUMMARY_SECTION = "Summary"
OPENING_SECTION = "Start of source"

_OVERVIEW_MAX_WORDS = 30
_OVERVIEW = re.compile(
    r"""(?ix)
    \b(?:
        overview | tl;?\s?dr | in\ a\ nutshell | big\ picture | recap\b
      | key\ (?:points|takeaways|themes|ideas|findings) | main\ (?:points|ideas|themes|takeaways)
      | summari[sz]e\ (?:everything|all|it|them|these|this|(?:(?:the|my|all)\ )*(?:whole|entire|notebook|sources?|documents?|materials?|collection|key|main)\b)
      | (?:give\ me|write|need|want|show\ me)\ (?:a|an|the)\ (?:\w+\ )?summary
      | summary\ of\ (?:everything|all|(?:(?:the|my|all)\ )+(?:notebook|sources?|documents?|materials?|collection))
      | what(?:'s|\ is|\ are)\ (?:this|these|the)\ (?:notebook|sources?|documents?|materials?|collection)\b.{0,15}\b(?:about|cover|contain)
      | what\ do(?:es)?\ (?:this|these|the|my)\ (?:notebook|sources?|documents?|materials?|collection)\b.{0,15}\b(?:say|cover|contain)
    )\b
    | ^\W*summari[sz]e\W*$
    """
)


def is_overview_question(message: str) -> bool:
    """True for a broad request about the whole notebook (summarize, overview, key points, tl;dr)."""
    text = " ".join(str(message or "").split())
    return bool(text) and len(text.split()) <= _OVERVIEW_MAX_WORDS and bool(_OVERVIEW.search(text))


_SOURCES_SQL = """
    SELECT s.id, s.title, LEFT(COALESCE(s.content_text, ''), $3) AS head
    FROM notebook_sources s
    JOIN notebooks n ON n.id = s.notebook_id AND n.is_active = TRUE
    WHERE s.notebook_id = $1 AND s.status = 'ready'
      AND ($2::uuid[] IS NULL OR s.id = ANY($2::uuid[]))
    ORDER BY s.created_at, s.id
    LIMIT $4
"""
# Insights are written under the owner's id when a source finishes ingesting.
_INSIGHTS_SQL = """
    SELECT t.source_id, t.transformed_content, t.custom_prompt
    FROM notebook_transformations t
    JOIN notebooks n ON n.id = t.notebook_id AND n.user_id = t.user_id
    WHERE t.notebook_id = $1 AND t.source_id = ANY($2::uuid[])
    ORDER BY t.created_at DESC
"""


@dataclass
class SummaryPassages:
    """Passages for the sources asked about, plus which ones had no summary."""

    chunks: List[ChunkWithScore] = field(default_factory=list)
    summarized: List[Dict[str, str]] = field(default_factory=list)  # {source_id, title}: a stored summary
    opened: List[Dict[str, str]] = field(default_factory=list)  # no summary; the start of the text instead
    missing: List[Dict[str, str]] = field(default_factory=list)  # no summary and nothing to use instead


def summary_passage(
    notebook_id: UUID, source_id: UUID, title: Optional[str], text: str, section: str
) -> ChunkWithScore:
    chunk = NotebookChunk(
        id=uuid5(source_id, section),
        source_id=source_id,
        notebook_id=notebook_id,
        content=text,
        metadata={"kind": "summary", "section": section},
        created_at=datetime.now(timezone.utc),
    )
    return ChunkWithScore(chunk=chunk, score=1.0, source_title=title, vector_score=None)


def _uuids(raw: Iterable[Any]) -> List[UUID]:
    out: List[UUID] = []
    for item in raw:
        try:
            value = item if isinstance(item, UUID) else UUID(str(item))
        except (ValueError, AttributeError, TypeError):
            continue
        if value not in out:
            out.append(value)
    return out


async def load_summary_passages(
    pool: Any,
    notebook_id: UUID,
    source_ids: Optional[Sequence[Any]] = None,
    *,
    text_fallback: bool = False,
    limit: int = MAX_OVERVIEW_SOURCES,
) -> SummaryPassages:
    """One passage per ready source of this notebook (all of them when ``source_ids`` is None).

    A source with no stored summary gets the start of its text when ``text_fallback`` is set,
    otherwise it is listed in ``missing``. A list of ids of which none parses reads nothing,
    never the whole notebook.
    """
    wanted: Optional[List[UUID]] = None
    if source_ids:
        wanted = _uuids(source_ids)
        if not wanted:
            return SummaryPassages()
    async with pool.acquire() as conn:
        rows = list(await conn.fetch(
            _SOURCES_SQL, notebook_id, wanted, INSIGHT_FALLBACK_CHARS if text_fallback else 0, limit
        ))
        saved: Dict[str, List[Dict[str, Any]]] = {}
        if rows:
            for row in await conn.fetch(_INSIGHTS_SQL, notebook_id, [r["id"] for r in rows]):
                saved.setdefault(str(row["source_id"]), []).append(
                    {"transformed_content": row["transformed_content"], "custom_prompt": row["custom_prompt"]}
                )

    out = SummaryPassages()
    for row in rows:
        sid = str(row["id"])
        entry = {"source_id": sid, "title": row["title"] or "Untitled source"}
        summary = insight_text(saved.get(sid, []))
        if summary:
            out.summarized.append(entry)
            out.chunks.append(summary_passage(notebook_id, row["id"], row["title"], summary, SUMMARY_SECTION))
            continue
        head = str(row["head"] or "").strip()
        if text_fallback and head:
            out.opened.append(entry)
            out.chunks.append(summary_passage(notebook_id, row["id"], row["title"], head, OPENING_SECTION))
        else:
            out.missing.append(entry)
    return out


def context_report(
    mode: str,
    passages: SummaryPassages,
    *,
    unreadable: Iterable[str] = (),
) -> Dict[str, Any]:
    """What the answer was built from, for the chat to show. Titles and ids only, never source text."""
    excluded = [{**m, "reason": "no_summary"} for m in passages.missing]
    excluded += [{"source_id": str(s), "title": None, "reason": "unreadable"} for s in unreadable]
    return {
        "mode": mode,  # "summary" (Summary level, with or without searched passages) or "overview"
        "summarized": passages.summarized,
        "opened": passages.opened,
        "excluded": excluded,
    }
