"""Read-only notebook tools for agents: list, search, and ask a person's notebooks.

These are not in the harvis-mcp registry on purpose. That service has one deployment-wide
bearer token and no notion of a user, so a notebook tool there could not know whose
notebooks it was reading. These run in the backend behind the same JWT every other
``/api`` route uses (see ``mcp/server/notebook_mcp.py``): the user id comes from the
request and goes into :class:`NotebookToolContext` server-side. No tool argument can
name a user, and every notebook id is checked against that user through
``notebooks.access.resolve_access`` before anything is read: the owner and people the
notebook was shared with may use it, by role (search needs a role that reads sources, ask a
role that may chat). A notebook that belongs to someone else with no share, does not exist, or is not a UUID all answer the same way.

Nothing here writes. ``notebook_ask`` uses the stateless ``answer_for_session`` path,
so it does not touch the notebook's chat history either.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional, Tuple
from uuid import UUID

from notebooks.ingestion import IngestionService
from notebooks.access import NEEDS, resolve_access
from notebooks.manager import NotebookManager
from notebooks.rag_chat import RAGChatService
from notebooks.rag_limits import HARD_MAX_CHUNKS, clamp_top_k, rag_chunk_limit

MAX_LIST = 100
MAX_PASSAGE_CHARS = 1200
MAX_QUESTION_CHARS = 4000
NOT_FOUND = "Notebook not found."

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_READ_ONLY_LLM = {**_READ_ONLY, "idempotentHint": False}

_NOTEBOOK_ID = {"type": "string", "description": "Notebook id from notebook_list."}

TOOLS: List[dict] = [
    {
        "name": "notebook_list",
        "description": "List the signed-in person's notebooks (id, title, source and note counts).",
        "inputSchema": {"type": "object", "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIST, "default": 50}}},
        "annotations": _READ_ONLY,
    },
    {
        "name": "notebook_search",
        "description": "Search one notebook's sources and return the most relevant passages with "
                       "their source titles, so the caller can read them itself.",
        "inputSchema": {"type": "object", "required": ["notebook_id", "query"], "properties": {
            "notebook_id": _NOTEBOOK_ID,
            "query": {"type": "string", "minLength": 1},
            "top_k": {"type": "integer", "minimum": 1, "maximum": HARD_MAX_CHUNKS,
                      "description": "Passages to return; default is the server's NOTEBOOK_RAG_CHUNKS."}}},
        "annotations": _READ_ONLY,
    },
    {
        "name": "notebook_ask",
        "description": "Ask one notebook a question and get an answer grounded only in its sources, "
                       "with numbered citations ([SOURCE N] in the answer matches citations[N-1]). "
                       "Does not save the exchange to the notebook's chat history.",
        "inputSchema": {"type": "object", "required": ["notebook_id", "question"], "properties": {
            "notebook_id": _NOTEBOOK_ID,
            "question": {"type": "string", "minLength": 1},
            "source_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 50,
                           "description": "Optional: answer from only these sources of the notebook."}}},
        "annotations": _READ_ONLY_LLM,
    },
]
TOOL_NAMES = tuple(t["name"] for t in TOOLS)


@dataclass
class NotebookToolContext:
    manager: NotebookManager
    user_id: int
    allowed_models: Optional[List[str]] = None
    # Resolves the model one answer may run on, and counts the turn against the person's
    # limits; raises when they are out of turns. Only notebook_ask calls it.
    pick_model: Optional[Callable[[], Awaitable[str]]] = None


class ToolError(Exception):
    """A refusal the model can read and act on."""


def mcp_tools() -> List[dict]:
    return [dict(t) for t in TOOLS]


def _text(args: dict, key: str, limit: int = MAX_QUESTION_CHARS) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{key} is required.")
    return value.strip()[:limit]


async def _notebook(ctx: NotebookToolContext, args: dict, need: str):
    """The caller's access to the notebook for ``need`` ('read' or 'chat'); a stranger sees NOT_FOUND."""
    raw = args.get("notebook_id")
    try:
        notebook_id = UUID(str(raw))
    except (ValueError, TypeError):
        raise ToolError(NOT_FOUND)
    access = await resolve_access(ctx.manager, notebook_id, ctx.user_id)
    if access is None:
        raise ToolError(NOT_FOUND)
    if access.role not in NEEDS[need]:
        raise ToolError("Your role on this notebook does not allow that.")
    return access


async def _list(ctx: NotebookToolContext, args: dict) -> dict:
    limit = args.get("limit", 50)
    limit = min(max(limit, 1), MAX_LIST) if isinstance(limit, int) and not isinstance(limit, bool) else 50
    notebooks, total = await ctx.manager.list_notebooks(ctx.user_id, limit=limit, offset=0)
    return {"total": total, "notebooks": [{
        "id": str(n.id), "title": n.title, "description": n.description,
        "source_count": n.source_count, "note_count": n.note_count,
        "updated_at": n.updated_at.isoformat(),
    } for n in notebooks]}


async def _search(ctx: NotebookToolContext, args: dict) -> dict:
    notebook_id = (await _notebook(ctx, args, "read")).notebook_id
    query = _text(args, "query")
    top_k = args.get("top_k")
    top_k = clamp_top_k(top_k) if isinstance(top_k, int) and not isinstance(top_k, bool) else rag_chunk_limit()
    embedding = await IngestionService(ctx.manager).get_query_embedding(query)
    if not embedding:
        raise ToolError("The notebook could not be searched right now: no embedding model answered.")
    found = await ctx.manager.search_chunks(notebook_id, embedding, top_k=top_k)
    return {"notebook_id": str(notebook_id), "passages": [{
        "source_id": str(c.chunk.source_id), "source_title": c.source_title,
        "page": (c.chunk.metadata or {}).get("page"), "score": round(c.score, 4),
        "text": c.chunk.content[:MAX_PASSAGE_CHARS],
    } for c in found]}


async def _ask(ctx: NotebookToolContext, args: dict) -> dict:
    access = await _notebook(ctx, args, "chat")
    notebook_id = access.notebook_id
    question = _text(args, "question")
    raw_ids = args.get("source_ids")
    source_ids = None
    if raw_ids:
        if not isinstance(raw_ids, list):
            raise ToolError("source_ids must be a list of source ids.")
        try:
            source_ids = [str(UUID(str(s))) for s in raw_ids]
        except ValueError:
            raise ToolError("source_ids must be a list of source ids.")
    model = await ctx.pick_model() if ctx.pick_model else ""
    rag = RAGChatService(ctx.manager, allowed_models=ctx.allowed_models)
    answer, citations = await rag.answer_for_session(
        notebook_id, question, model, source_ids=source_ids, user_id=ctx.user_id
    )
    return {"notebook_id": str(notebook_id), "answer": answer, "citations": [{
        "n": i, "source_id": str(c.source_id), "source_title": c.source_title,
        "page": c.page, "section": c.section, "quote": c.quote if access.can_read_sources else None,
    } for i, c in enumerate(citations, 1)]}


_HANDLERS = {"notebook_list": _list, "notebook_search": _search, "notebook_ask": _ask}


async def dispatch(name: str, args: dict, ctx: NotebookToolContext) -> Tuple[Any, bool]:
    """Run one tool as the context's user. Returns ``(payload, ok)``; never raises for a refusal."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool {name}"}, False
    try:
        return await handler(ctx, args), True
    except ToolError as exc:
        return {"error": str(exc)}, False
