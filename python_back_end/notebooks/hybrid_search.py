"""Hybrid retrieval over notebook_chunks: a vector leg and a keyword leg fused by rank.

Callers are NotebookManager.search_chunks_hybrid, which checks the caller's access to the
notebook first; nothing here knows about users. Both legs filter on notebook_id.
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from asyncpg import Pool
from asyncpg.exceptions import UndefinedColumnError

from .models import ChunkWithScore, NotebookChunk

logger = logging.getLogger(__name__)

RRF_K = 60
DIVERSITY_FRACTION = 0.6
MAX_TOP_K = 100

# Dropped from the keyword query only: with the 'simple' config nothing is stopped, so a
# natural-language question would otherwise match on "the" and "of" alone.
_QUERY_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i in is it its of on or "
    "that the their there this to was were what when where which who why will with".split()
)

_COLUMNS = (
    "c.id, c.source_id, c.notebook_id, c.content, c.metadata, c.chunk_index, c.created_at, "
    "s.title AS source_title"
)

_VECTOR_SQL = f"""
    SELECT {_COLUMNS}, 1 - (c.embedding <=> $1::vector) AS vector_score
    FROM notebook_chunks c
    JOIN notebook_sources s ON s.id = c.source_id
    WHERE c.notebook_id = $2
      AND c.embedding IS NOT NULL
      AND ($4::uuid[] IS NULL OR c.source_id = ANY($4::uuid[]))
      AND ($5::uuid[] IS NULL OR NOT (c.source_id = ANY($5::uuid[])))
    ORDER BY c.embedding <=> $1::vector
    LIMIT $3
"""

# websearch_to_tsquery ANDs every term; turn that into OR so a long question still finds
# chunks that hold most of its words. ts_rank_cd then prefers chunks matching more terms.
_KEYWORD_SQL = f"""
    WITH q AS (
        SELECT replace(websearch_to_tsquery('simple', $1)::text, '&', '|')::tsquery AS tsq
    )
    SELECT {_COLUMNS}, 1 - (c.embedding <=> $4::vector) AS vector_score
    FROM notebook_chunks c
    JOIN notebook_sources s ON s.id = c.source_id
    CROSS JOIN q
    WHERE c.notebook_id = $2
      AND c.content_tsv @@ q.tsq
      AND ($5::uuid[] IS NULL OR c.source_id = ANY($5::uuid[]))
      AND ($6::uuid[] IS NULL OR NOT (c.source_id = ANY($6::uuid[])))
    ORDER BY ts_rank_cd(c.content_tsv, q.tsq) DESC
    LIMIT $3
"""


class HybridChunk(ChunkWithScore):
    """A ChunkWithScore whose `score` is the fused RRF score.

    `vector_score` is the cosine similarity to the query (None when the query had no
    embedding or the chunk has none), which is what a grounding floor should read.
    """

    vector_score: Optional[float] = None


def keyword_query(text: str) -> str:
    """Drop stopwords from a question; keep quoted, negated and operator tokens as typed."""
    tokens = (text or "").split()
    kept = [
        t for t in tokens
        if t[:1] in "\"-" or t.lower().strip(".,;:!?()[]{}'\"") not in _QUERY_STOPWORDS
    ]
    return " ".join(kept or tokens)


def rrf_fuse(*rankings: Sequence[str], k: int = RRF_K) -> Dict[str, float]:
    """Reciprocal rank fusion: each ranking (best first) adds 1/(k+rank) to its ids."""
    fused: Dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank)
    return fused


def diversify(rows: List[Dict[str, Any]], top_k: int, backfill: bool = True) -> List[Dict[str, Any]]:
    """Take rows in order, at most ceil(top_k * 0.6) per source.

    With backfill, slots left empty because other sources ran out are refilled from the
    rows the cap skipped, so a one-source notebook still returns top_k chunks. Without it
    the cap is strict.
    """
    cap = max(1, math.ceil(top_k * DIVERSITY_FRACTION))
    taken: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    per_source: Dict[str, int] = {}
    for row in rows:
        if len(taken) >= top_k:
            break
        sid = str(row["source_id"])
        if per_source.get(sid, 0) >= cap:
            skipped.append(row)
            continue
        per_source[sid] = per_source.get(sid, 0) + 1
        taken.append(row)
    if backfill:
        taken.extend(skipped[: top_k - len(taken)])
    return taken


def _vector_literal(embedding: Sequence[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


def _source_filter(source_ids: Optional[Sequence[Any]]) -> Optional[List[UUID]]:
    """None = whole notebook. A non-empty list of which nothing parses must match nothing,
    never widen to the whole notebook, so that case returns an empty list."""
    if not source_ids:
        return None
    parsed: List[UUID] = []
    for sid in source_ids:
        try:
            parsed.append(sid if isinstance(sid, UUID) else UUID(str(sid)))
        except (ValueError, AttributeError, TypeError):
            continue
    return parsed


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else 0.0


def _to_chunk(row: Dict[str, Any]) -> HybridChunk:
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    chunk = NotebookChunk(
        id=row["id"],
        source_id=row["source_id"],
        notebook_id=row["notebook_id"],
        content=row["content"],
        metadata=metadata or {},
        chunk_index=row["chunk_index"],
        created_at=row["created_at"],
    )
    return HybridChunk(
        chunk=chunk,
        score=row["score"],
        source_title=row["source_title"],
        vector_score=row["vector_score"],
    )


async def hybrid_search(
    pool: Pool,
    notebook_id: UUID,
    query_text: str,
    query_embedding: Optional[Sequence[float]],
    top_k: int = 5,
    source_ids: Optional[Sequence[Any]] = None,
    exclude_source_ids: Optional[Sequence[Any]] = None,
) -> List[HybridChunk]:
    """Fuse the vector and keyword rankings of one notebook, best first.

    ``exclude_source_ids`` leaves those sources out (the chat's Summary level reads them as
    summaries instead).

    Keyword-only when there is no query embedding; vector-only when content_tsv is
    missing. Empty when neither leg can run.
    """
    top_k = max(1, min(int(top_k), MAX_TOP_K))
    sources = _source_filter(source_ids)
    if sources is not None and not sources:
        return []
    excluded = _source_filter(exclude_source_ids)
    text = keyword_query((query_text or "").strip())
    if not text and not query_embedding:
        return []

    fetch_k = max(top_k * 4, 20)
    embedding_str = _vector_literal(query_embedding) if query_embedding else None

    vector_rows: List[Any] = []
    keyword_rows: List[Any] = []
    async with pool.acquire() as conn:
        if embedding_str is not None:
            vector_rows = await conn.fetch(_VECTOR_SQL, embedding_str, notebook_id, fetch_k, sources, excluded)
        if text:
            try:
                keyword_rows = await conn.fetch(_KEYWORD_SQL, text, notebook_id, fetch_k, embedding_str, sources, excluded)
            except UndefinedColumnError:
                logger.warning("notebook_chunks.content_tsv is missing; hybrid search is vector-only")

    by_id: Dict[str, Dict[str, Any]] = {}
    for row in list(vector_rows) + list(keyword_rows):
        data = dict(row)
        key = str(data["id"])
        data["vector_score"] = _finite(data.get("vector_score"))
        by_id.setdefault(key, data)

    fused = rrf_fuse(
        [str(r["id"]) for r in vector_rows],
        [str(r["id"]) for r in keyword_rows],
    )
    ranked = sorted(
        by_id.values(),
        key=lambda r: (-fused[str(r["id"])], -(r["vector_score"] if r["vector_score"] is not None else -1.0), str(r["id"])),
    )
    for row in ranked:
        row["score"] = fused[str(row["id"])]
    return [_to_chunk(r) for r in diversify(ranked, top_k)]
