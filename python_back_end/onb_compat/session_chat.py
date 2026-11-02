"""One chat turn of an onb_compat notebook session.

``chat_execute`` in the router used to call ``answer_for_session`` with a bare question: no
earlier turns, no notebook chat settings, no output language, and every ticked source meant
"search the whole notebook". This module is that turn done properly:

* the session's earlier turns go to the model (and to the follow-up query rewrite), with the
  ``[cite:N]`` markers the router stored in old answers taken back out;
* the notebook's chat settings (persona, style, length, output language) apply;
* when the client sends a level per source (``insights`` / ``full``) and per note, the
  selection is turned into a plan by ``notebooks.context_builder``: stuffed when it fits,
  otherwise retrieved from;
* each citation carries where its passage sits: ``start_char``, ``end_char``, ``page``.

A client that sends no levels (an older or hand-built payload) keeps the old meaning: search the
whole notebook, or only the listed sources.

Nothing here touches the database except through ``notebooks.context_builder``, whose reads are
scoped to the owner, and the rag object it is given.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from notebooks.citations import snippet
from notebooks.context_builder import (
    BuiltContext,
    ContextItem,
    build_context,
    selection_from_context,
)
from notebooks.grounding import REFUSAL_TEXT, is_grounded
from notebooks.models import Citation
from notebooks.rag_answer import _DECLINE
from notebooks.rag_prompt import build_context as build_chunk_context
from notebooks.rag_prompt import num_predict_for, system_prompt_for

logger = logging.getLogger(__name__)

NO_SOURCES_TEXT = (
    "I don't have any sources in context to answer from. Add a source "
    "(or include one in the context) and ask again."
)
FLAGS_KEY = "_flags"  # marks the one non-citation element kept at the end of a stored citations list

_CITE_MARK = re.compile(r"\s*\[cite:\d+\]")
_CITED = re.compile(r"\[cite:\d+\]")
_SOURCE_NUM = re.compile(r"\[\s*S(?:OURCE)?\s*(\d+)\s*(?::[^\]]*)?\]", re.IGNORECASE)


# ─── citations ────────────────────────────────────────────────────────────────

def pick_locator(quote: str) -> str:
    """A clean, findable single-line locator from a cited chunk. Overlap chunks can start
    mid-word (e.g. "e's Notebook LM!" from a "Google's Notebook LM!" cut), so pick the first
    sentence-like line and drop a leading partial-word fragment."""
    for line in (quote or "").splitlines():
        line = line.strip()
        if len(line) < 12:
            continue
        words = line.split()
        if words and words[0][:1].islower():  # a leading mid-word fragment
            words = words[1:]
        cand = " ".join(words).strip()
        if len(cand) >= 16:
            return cand[:120]
    return (quote or "").strip()[:120]


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value >= 0 else None


def _located(chunk_with_score: Any, citation: Any) -> Dict[str, Optional[int]]:
    """``start_char``, ``end_char`` and ``page`` of one cited passage; None where unknown."""
    meta = getattr(getattr(chunk_with_score, "chunk", None), "metadata", None) or {}
    page = _int_or_none(getattr(citation, "page", None))
    if page is None:
        page = _int_or_none(meta.get("page"))
    return {
        "start_char": _int_or_none(meta.get("start_char")),
        "end_char": _int_or_none(meta.get("end_char")),
        "page": page or None,
    }


def build_citations_payload(
    cits: Any, chunks: Optional[List[Any]] = None, kinds: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """One entry PER cited passage, in prompt order: ``index`` i is the model's ``[cite:i]``.

    Each carries its own snippet and a findable ``locator`` string (what the vendored UI
    shows), plus ``start_char``/``end_char``/``page`` (also grouped as ``locator_range``) so a
    chip can jump to the exact characters. ``chunks`` is the ``ChunkWithScore`` list parallel to
    ``cits``; without it the offsets are None. ``kinds`` marks non-source entries (``note``).
    """
    out: List[Dict[str, Any]] = []
    parallel = chunks if chunks is not None and len(chunks) == len(cits or []) else None
    for i, c in enumerate(cits or [], 1):
        quote = (getattr(c, "quote", "") or "").strip()
        where = _located(parallel[i - 1] if parallel else None, c)
        chunk_id = getattr(c, "chunk_id", None)
        out.append({
            "index": i,
            "source_id": str(getattr(c, "source_id", "") or ""),
            "title": getattr(c, "source_title", None) or "",
            "snippet": quote[:280],
            "locator": pick_locator(quote),
            "kind": (kinds[i - 1] if kinds and i <= len(kinds) else "source"),
            "chunk_id": str(chunk_id) if chunk_id else None,
            "start_char": where["start_char"],
            "end_char": where["end_char"],
            "page": where["page"],
            "locator_range": dict(where),
        })
    return out


def pack_citations(
    payload: List[Dict[str, Any]], *, unsupported: bool = False, refused: bool = False,
    indicators: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """The ``citations`` JSONB value to store: the payload, plus one flags element when any
    flag is set. (The column is the only place a message can keep them without a migration.)"""
    flags: Dict[str, Any] = {}
    if unsupported:
        flags["unsupported"] = True
    if refused:
        flags["refused"] = True
    if indicators:
        flags["context"] = indicators
    return list(payload) + ([{FLAGS_KEY: flags}] if flags else [])


def unpack_citations(raw: Any) -> "tuple[List[Dict[str, Any]], Dict[str, Any]]":
    """``(citations, flags)`` from a stored value, a list or its JSON text; never raises."""
    if isinstance(raw, (str, bytes)):
        try:
            import json

            raw = json.loads(raw)
        except Exception:
            return [], {}
    if not isinstance(raw, list):
        return [], {}
    cits = [c for c in raw if isinstance(c, dict) and FLAGS_KEY not in c]
    flags: Dict[str, Any] = {}
    for c in raw:
        if isinstance(c, dict) and isinstance(c.get(FLAGS_KEY), dict):
            flags.update(c[FLAGS_KEY])
    return cits, flags


def strip_cite_markers(text: str) -> str:
    """An earlier answer as plain prose: ``[cite:N]`` markers the router added are removed."""
    return _CITE_MARK.sub("", text or "").strip()


def clean_history(history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for turn in history or []:
        content = turn.get("content") if isinstance(turn, dict) else None
        if isinstance(content, str):
            content = strip_cite_markers(content) if turn.get("role") == "assistant" else content
            if content.strip():
                out.append({"role": turn.get("role"), "content": content})
    return out


def rewrite_source_markers(answer: str, n_cits: int) -> str:
    """Only numbered markers; the router's title-aware rewrite runs on top of this when needed."""
    if not answer or not n_cits:
        return answer
    return _SOURCE_NUM.sub(
        lambda m: f"[cite:{int(m.group(1))}]" if 1 <= int(m.group(1)) <= n_cits else m.group(0), answer
    )


# ─── the turn ────────────────────────────────────────────────────────────────

@dataclass
class TurnResult:
    answer: str
    citations: List[Dict[str, Any]] = field(default_factory=list)
    unsupported: bool = False
    refused: bool = False
    indicators: Optional[Dict[str, Any]] = None
    model_used: str = ""

    def stored_citations(self) -> List[Dict[str, Any]]:
        return pack_citations(
            [] if (self.unsupported or self.refused) else self.citations,
            unsupported=self.unsupported, refused=self.refused, indicators=self.indicators,
        )


async def _history(rag: Any, notebook_id: UUID, user_id: int, session_id: Any) -> List[Dict[str, str]]:
    loader = getattr(rag, "load_history", None)
    if loader is None:
        return []
    try:
        return clean_history(await loader(notebook_id, user_id, session_id=session_id))
    except Exception:
        logger.warning("Could not load session history; answering without it", exc_info=True)
        return []


def _item_citations(items: List[ContextItem]) -> "tuple[List[Citation], List[str]]":
    cits: List[Citation] = []
    kinds: List[str] = []
    for item in items:
        try:
            sid = UUID(item.id)
        except ValueError:
            continue
        label = "note" if item.kind == "note" else "source"
        cits.append(Citation(source_id=sid, source_title=item.title, quote=snippet(item.text)))
        kinds.append(label)
    return cits, kinds


def _render_items(items: List[ContextItem], start: int) -> str:
    parts = []
    for n, item in enumerate(items, start):
        label = item.title
        if item.kind == "insight":
            label = f"{item.title} (insights)"
        elif item.kind == "note":
            label = f"Note: {item.title}"
        parts.append(f"\n--- SOURCE {n}: {label} ---\n{item.text}\n---\n")
    return "\n".join(parts)


def _decline(text: str) -> bool:
    return bool(_DECLINE.search(text[:200]))


async def _answer_from_plan(
    rag: Any, plan: BuiltContext, *, notebook_id: UUID, user_id: int, message: str, model: str,
    history: List[Dict[str, str]], rewrite: Callable[[str, Any], str],
) -> TurnResult:
    """Answer from a context plan: its stuffed items, plus passages retrieved from the big sources."""
    config = await rag.load_config(notebook_id, user_id) if hasattr(rag, "load_config") else None
    chunks: List[Any] = []
    retrieved_chars = 0
    if plan.retrieve_source_ids:
        found = await rag.retrieve(
            notebook_id, user_id, message, history=history, source_ids=plan.retrieve_source_ids, model=model
        )
        chunks = list(found.chunks)
        if chunks and not is_grounded(chunks):
            chunks = []
            if not plan.items:
                return TurnResult(REFUSAL_TEXT, refused=True, model_used=model,
                                  indicators=plan.indicators())
        retrieved_chars = sum(len(c.chunk.content) for c in chunks)
    if not chunks and not plan.items:
        return TurnResult(NO_SOURCES_TEXT, model_used=model, indicators=plan.indicators())

    chunk_text, chunk_cits = build_chunk_context(chunks) if chunks else ("", [])
    item_cits, item_kinds = _item_citations(plan.items)
    context_text = "\n".join(t for t in (chunk_text, _render_items(plan.items, len(chunk_cits) + 1)) if t)
    cits = list(chunk_cits) + item_cits
    kinds = ["source"] * len(chunk_cits) + item_kinds
    parallel = list(chunks) + [None] * len(item_cits)

    extras: Dict[str, Any] = {}
    if history:
        extras["history"] = history
    num_predict = num_predict_for(config)
    if num_predict:
        extras["num_predict"] = num_predict
    answer, _reasoning, answered_by = await rag._generate_response(
        message, system_prompt_for(None, config), context_text, model, **extras
    )
    answer = rewrite(answer.strip(), cits)
    unsupported = not _CITED.search(answer) and not _decline(answer)
    return TurnResult(
        answer, build_citations_payload(cits, parallel, kinds), unsupported=unsupported,
        model_used=answered_by, indicators=plan.indicators(retrieved_chars),
    )


async def answer_turn(
    *,
    manager: Any,
    rag: Any,
    notebook_id: UUID,
    user_id: int,
    session_id: Any,
    message: str,
    model: str,
    context: Optional[Dict[str, Any]],
    legacy_source_ids: Optional[List[str]] = None,
    rewrite: Optional[Callable[[str, Any], str]] = None,
) -> TurnResult:
    """Answer ``message`` for this session. The caller has already checked that ``user_id``
    owns the session and notebook, and saves the exchange.

    ``legacy_source_ids`` is the source filter of a payload without levels (None: search all).
    ``rewrite(answer, citations)`` turns the model's source markers into ``[cite:i]``; the
    router passes its title-aware version.
    """
    rewrite = rewrite or (lambda text, cits: rewrite_source_markers(text, len(cits or [])))
    history = await _history(rag, notebook_id, user_id, session_id)
    selection = selection_from_context(context)

    if selection is not None:
        if selection.is_empty:
            return TurnResult(NO_SOURCES_TEXT, model_used=model,
                              indicators={"sources": [], "notes": [], "tokens": 0, "chars": 0,
                                          "mode": "empty", "source_modes": {}, "dropped": []})
        plan = await build_context(manager.db_pool, notebook_id=notebook_id, user_id=user_id, selection=selection)
        if plan.empty:
            return TurnResult(NO_SOURCES_TEXT, model_used=model, indicators=plan.indicators())
        return await _answer_from_plan(
            rag, plan, notebook_id=notebook_id, user_id=user_id, message=message, model=model,
            history=history, rewrite=rewrite,
        )

    detailed = getattr(rag, "answer_for_session_detailed", None)
    if detailed is None:  # a rag object that predates the detailed answer
        answer, cits = await rag.answer_for_session(notebook_id, message, model, source_ids=legacy_source_ids)
        return TurnResult(rewrite(answer, cits), build_citations_payload(cits), model_used=model)

    result = await detailed(
        notebook_id, message, model, legacy_source_ids, user_id=user_id, history=history or None,
    )
    return TurnResult(
        rewrite(result.answer, result.citations),
        build_citations_payload(result.citations, result.chunks),
        unsupported=bool(result.unsupported), refused=bool(result.refused),
        model_used=result.model_used or model,
    )
