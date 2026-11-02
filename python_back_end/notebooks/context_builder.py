"""What a notebook chat is allowed to see: one level per source, one switch per note.

A person ticks sources and notes in the chat panel. Each source carries a level:

* ``full``     the source's own text
* ``insights`` only what was written about it (the Dense Summary and other saved insights),
               or the start of the text when none exists yet
* ``off``      left out

``build_context`` turns that selection into a plan. When everything chosen fits the prompt
budget it is *stuffed*: the model reads the text itself, nothing is searched. When it does
not fit, the small parts (insights and notes) are still stuffed, cut by priority, and only
the ``full`` sources are *retrieved* from. Every read is scoped to the signed-in owner and
to the notebook, so an id from another notebook is silently ignored.

Priorities follow the idea in open-notebook's context builder (source 100, insight 75,
note 50; MIT, (c) 2024 Luis Novo): when room runs out, notes go first.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from .auto_insights import QUESTIONS_MARKER, SUMMARY_MARKER
from .rag_limits import rag_context_budget

logger = logging.getLogger(__name__)

OFF, INSIGHTS, FULL = "off", "insights", "full"
PRIORITY = {"source": 100, "insight": 75, "note": 50}

INSIGHT_CAP_CHARS = 3000  # all saved insights of one source together
INSIGHT_FALLBACK_CHARS = 1500  # start of the text, for a source with no insight yet
NOTE_CAP_CHARS = 4000
MIN_SLICE_CHARS = 200  # a cut item is only worth keeping with this much text left
FIXED_SHARE = 0.5  # of the budget the stuffed parts may take when sources are retrieved too
MAX_SELECTED = 60  # per kind; the rest of a longer selection is ignored
_HEADER_FIXED = 40  # "--- SOURCE 12: ... ---" lines around each passage, minus the title

_OFF_WORDS = {"", "off", "none", "not in", "not-in", "no", "exclude", "excluded", "false"}
_ID = re.compile(r"^(?:source_insight|source|note|insight)?:?\s*([0-9a-fA-F-]{32,36})$")


def normalize_mode(raw: Any, default: str = OFF) -> str:
    """``insights``, ``full`` or ``off`` from what a client sends ("full content", "not in"...)."""
    text = " ".join(str(raw if raw is not None else "").replace("_", " ").strip().lower().split())
    if text in _OFF_WORDS:
        return OFF
    if text.startswith("insight"):
        return INSIGHTS
    if text.startswith("full") or text in ("on", "yes", "true", "all"):
        return FULL
    return default


def _uuid_str(raw: Any) -> Optional[str]:
    match = _ID.match(str(raw or "").strip())
    if not match:
        return None
    try:
        return str(UUID(match.group(1)))
    except ValueError:
        return None


@dataclass(frozen=True)
class ContextSelection:
    """Which sources (at which level) and notes the person ticked. ``off`` entries are not kept."""

    sources: Dict[str, str] = field(default_factory=dict)  # source id -> INSIGHTS | FULL
    notes: Dict[str, str] = field(default_factory=dict)  # note id -> FULL

    @property
    def is_empty(self) -> bool:
        return not self.sources and not self.notes


def _selection(sources: Iterable[Tuple[Any, Any]], notes: Iterable[Tuple[Any, Any]], default: str) -> ContextSelection:
    out_s: Dict[str, str] = {}
    out_n: Dict[str, str] = {}
    for raw_id, raw_mode in sources:
        sid, mode = _uuid_str(raw_id), normalize_mode(raw_mode, default)
        if sid and mode != OFF and len(out_s) < MAX_SELECTED:
            out_s[sid] = mode
    for raw_id, raw_mode in notes:
        nid, mode = _uuid_str(raw_id), normalize_mode(raw_mode, default)
        if nid and mode != OFF and len(out_n) < MAX_SELECTED:
            out_n[nid] = FULL
    return ContextSelection(out_s, out_n)


def selection_from_config(context_config: Any) -> ContextSelection:
    """From ``/chat/context``'s ``{"sources": {id: mode}, "notes": {id: mode}}``."""
    cfg = context_config if isinstance(context_config, dict) else {}
    srcs = cfg.get("sources") if isinstance(cfg.get("sources"), dict) else {}
    notes = cfg.get("notes") if isinstance(cfg.get("notes"), dict) else {}
    return _selection(srcs.items(), notes.items(), OFF)


def _item_pair(item: Any) -> Tuple[Any, Any, bool]:
    """``(id, mode, carried_a_mode)`` of one entry of the execute payload's ``sources``/``notes``."""
    if isinstance(item, dict):
        ident = item.get("id") or item.get("source_id") or (item.get("source") or {}).get("id")
        mode = item.get("mode", item.get("level"))
        return ident, mode, mode is not None
    return item, None, False


def selection_from_context(context: Any) -> Optional[ContextSelection]:
    """The selection a ``/chat/execute`` payload carries, or None for a payload without levels.

    ``/chat/context`` stamps every source and note it returns with its ``mode``, and the client
    sends that object back unchanged. A payload where no item has a mode (a hand-built one) or
    that is missing altogether keeps the old meaning: search the whole notebook. A payload with
    both lists present and empty means the person ticked nothing.
    """
    if not isinstance(context, dict):
        return None
    srcs, notes = context.get("sources"), context.get("notes")
    src_items = [_item_pair(i) for i in srcs] if isinstance(srcs, list) else []
    note_items = [_item_pair(i) for i in notes] if isinstance(notes, list) else []
    explicit_empty = isinstance(srcs, list) and isinstance(notes, list) and not srcs and not notes
    if not (explicit_empty or any(carried for *_, carried in src_items + note_items)):
        return None
    return _selection(
        [(i, m if m is not None else FULL) for i, m, _ in src_items],
        [(i, m if m is not None else FULL) for i, m, _ in note_items],
        FULL,
    )


@dataclass
class ContextItem:
    """One piece of text that goes into the prompt as it is."""

    kind: str  # 'source' | 'insight' | 'note'
    id: str
    title: str
    text: str
    truncated: bool = False

    @property
    def priority(self) -> int:
        return PRIORITY[self.kind]

    @property
    def cost(self) -> int:
        """Characters this item takes in the prompt: its text plus the header around it."""
        return len(self.text) + len(self.title) + _HEADER_FIXED


@dataclass
class BuiltContext:
    """The plan for one question."""

    items: List[ContextItem] = field(default_factory=list)  # text to stuff, in prompt order
    retrieve_source_ids: List[str] = field(default_factory=list)  # full sources to search
    stuffed: bool = False  # True: nothing is searched, the items are all the model reads
    source_modes: Dict[str, str] = field(default_factory=dict)  # modes actually honoured
    note_ids: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)  # ids that no longer fit
    budget: int = 0

    @property
    def empty(self) -> bool:
        """Nothing usable was selected (nothing owned, ready or with text)."""
        return not self.items and not self.retrieve_source_ids

    def indicators(self, retrieved_chars: int = 0) -> Dict[str, Any]:
        """What the chat shows under an answer: which sources and notes were used and how much."""
        chars = sum(len(i.text) for i in self.items) + retrieved_chars
        used = [i.id for i in self.items if i.kind in ("source", "insight")]
        used += [s for s in self.retrieve_source_ids if s not in used]
        return {
            "sources": used,
            "notes": [i.id for i in self.items if i.kind == "note"],
            "tokens": chars // 4,
            "chars": chars,
            "mode": "stuffed" if self.stuffed else "retrieved",
            "source_modes": dict(self.source_modes),
            "dropped": list(self.dropped),
            "budget_chars": self.budget,
        }


def truncate_to_fit(items: List[ContextItem], budget: int) -> Tuple[List[ContextItem], List[ContextItem]]:
    """``(kept, dropped)``: highest priority first, the item that crosses the limit is cut."""
    kept: List[ContextItem] = []
    dropped: List[ContextItem] = []
    left = max(budget, 0)
    for item in sorted(items, key=lambda i: -i.priority):
        if item.cost <= left:
            kept.append(item)
            left -= item.cost
            continue
        room = left - len(item.title) - _HEADER_FIXED
        if room >= MIN_SLICE_CHARS:
            kept.append(replace(item, text=item.text[: room - 1].rstrip() + "…", truncated=True))
            left = 0
        else:
            dropped.append(item)
    return kept, dropped


def insight_text(rows: Iterable[Dict[str, Any]]) -> str:
    """One source's saved insights as text: the Dense Summary first, then newer ones, no
    suggested-question list, cut to ``INSIGHT_CAP_CHARS``. ``rows`` come newest first."""
    summary, others = [], []
    for row in rows:
        body = str(row.get("transformed_content") or "").strip()
        marker = row.get("custom_prompt")
        if not body or marker == QUESTIONS_MARKER:
            continue
        (summary if marker == SUMMARY_MARKER else others).append(body)
    text = "\n\n".join(summary[:1] + others)
    return text[:INSIGHT_CAP_CHARS].rstrip()


_META_SQL = """
    SELECT s.id, s.title, LENGTH(COALESCE(s.content_text, '')) AS chars,
           LEFT(COALESCE(s.content_text, ''), $4) AS head
    FROM notebook_sources s
    JOIN notebooks n ON n.id = s.notebook_id AND n.user_id = $3
    WHERE s.id = ANY($1::uuid[]) AND s.notebook_id = $2 AND s.status = 'ready'
"""
_INSIGHT_SQL = """
    SELECT t.source_id, t.transformed_content, t.custom_prompt
    FROM notebook_transformations t
    WHERE t.source_id = ANY($1::uuid[]) AND t.user_id = $2 AND t.notebook_id = $3
    ORDER BY t.created_at DESC
"""
_NOTE_SQL = """
    SELECT id, title, LEFT(content, $4) AS content
    FROM notebook_notes
    WHERE id = ANY($1::uuid[]) AND notebook_id = $2 AND user_id = $3
"""
_FULL_SQL = """
    SELECT s.id, s.content_text
    FROM notebook_sources s
    JOIN notebooks n ON n.id = s.notebook_id AND n.user_id = $3
    WHERE s.id = ANY($1::uuid[]) AND s.notebook_id = $2
"""


async def _fetch(conn_or_pool: Any, sql: str, *args: Any):
    if hasattr(conn_or_pool, "acquire"):
        async with conn_or_pool.acquire() as conn:
            return await conn.fetch(sql, *args)
    return await conn_or_pool.fetch(sql, *args)


def _group_insights(rows: Iterable[Any]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["source_id"]), []).append(
            {"transformed_content": row["transformed_content"], "custom_prompt": row["custom_prompt"]}
        )
    return grouped


async def build_context(
    conn_or_pool: Any,
    *,
    notebook_id: UUID,
    user_id: int,
    selection: ContextSelection,
    budget: Optional[int] = None,
) -> BuiltContext:
    """Decide what the model reads for this selection (see the module docstring).

    ``conn_or_pool`` is an asyncpg pool or connection. Sources that are not ready, have no
    text, or belong to someone else's notebook are skipped, not reported.
    """
    budget = budget or rag_context_budget()
    plan = BuiltContext(budget=budget)
    if selection.is_empty:
        return plan

    src_ids = [UUID(s) for s in selection.sources]
    meta: Dict[str, Any] = {}
    if src_ids:
        rows = await _fetch(conn_or_pool, _META_SQL, src_ids, notebook_id, user_id, INSIGHT_FALLBACK_CHARS)
        meta = {str(r["id"]): r for r in rows}
    insights_ids = [UUID(s) for s, m in selection.sources.items() if m == INSIGHTS and s in meta]
    saved: Dict[str, List[Dict[str, Any]]] = {}
    if insights_ids:
        saved = _group_insights(await _fetch(conn_or_pool, _INSIGHT_SQL, insights_ids, user_id, notebook_id))

    insight_items: List[ContextItem] = []
    full_ids: List[str] = []
    for sid, mode in selection.sources.items():
        row = meta.get(sid)
        if row is None or not row["chars"]:
            continue
        plan.source_modes[sid] = mode
        title = row["title"] or "Untitled source"
        if mode == FULL:
            full_ids.append(sid)
            continue
        text = insight_text(saved.get(sid, [])) or str(row["head"] or "").strip()
        if text:
            insight_items.append(ContextItem("insight", sid, title, text))

    note_items: List[ContextItem] = []
    if selection.notes:
        rows = await _fetch(
            conn_or_pool, _NOTE_SQL, [UUID(n) for n in selection.notes], notebook_id, user_id, NOTE_CAP_CHARS
        )
        for row in rows:
            text = str(row["content"] or "").strip()
            if text:
                plan.note_ids.append(str(row["id"]))
                note_items.append(ContextItem("note", str(row["id"]), row["title"] or "Untitled note", text))

    fixed = insight_items + note_items
    full_cost = sum(int(meta[s]["chars"]) + len(meta[s]["title"] or "") + _HEADER_FIXED for s in full_ids)
    if full_cost + sum(i.cost for i in fixed) <= budget:
        plan.stuffed = True
        plan.items = await _with_full_text(conn_or_pool, notebook_id, user_id, full_ids, meta) + fixed
        return plan

    # Too much to read in one go: keep the small parts, search the big ones.
    limit = budget if not full_ids else int(budget * FIXED_SHARE)
    kept, dropped = truncate_to_fit(fixed, limit)
    plan.items = sorted(kept, key=lambda i: -i.priority)
    plan.dropped = [i.id for i in dropped]
    plan.retrieve_source_ids = full_ids
    return plan


async def _with_full_text(
    conn_or_pool: Any, notebook_id: UUID, user_id: int, full_ids: List[str], meta: Dict[str, Any]
) -> List[ContextItem]:
    if not full_ids:
        return []
    rows = await _fetch(conn_or_pool, _FULL_SQL, [UUID(s) for s in full_ids], notebook_id, user_id)
    text = {str(r["id"]): str(r["content_text"] or "").strip() for r in rows}
    return [ContextItem("source", s, meta[s]["title"] or "Untitled source", text[s]) for s in full_ids if text.get(s)]


# ─── preview (the chat panel's token counter) ────────────────────────────────────

def estimate_chars(
    selection: ContextSelection,
    *,
    chunk_chars: Dict[str, int],
    note_chars: Dict[str, int],
    insight_chars: Dict[str, int],
) -> int:
    """Characters the selection would put in front of the model, level by level.

    ``chunk_chars`` is the stored size of each source's text, ``insight_chars`` the size of
    its saved insights (0 when it has none, which falls back to the start of the text).
    """
    total = 0
    for sid, mode in selection.sources.items():
        full = int(chunk_chars.get(sid, 0))
        if mode == FULL:
            total += full
        else:
            total += min(int(insight_chars.get(sid, 0)) or min(full, INSIGHT_FALLBACK_CHARS), INSIGHT_CAP_CHARS)
    total += sum(min(int(c), NOTE_CAP_CHARS) for c in note_chars.values())
    return total


async def saved_insight_chars(conn_or_pool: Any, source_ids: List[str], user_id: int) -> Dict[str, int]:
    """Size of each source's saved insights; a failure is a missing estimate, never an error."""
    if not source_ids:
        return {}
    try:
        rows = await _fetch(
            conn_or_pool,
            """SELECT t.source_id, t.transformed_content, t.custom_prompt FROM notebook_transformations t
               WHERE t.source_id = ANY($1::uuid[]) AND t.user_id = $2 ORDER BY t.created_at DESC""",
            [UUID(s) for s in source_ids], user_id,
        )
    except Exception:
        logger.info("Could not size saved insights; estimating from the text instead", exc_info=True)
        return {}
    return {sid: len(insight_text(group)) for sid, group in _group_insights(rows).items()}
