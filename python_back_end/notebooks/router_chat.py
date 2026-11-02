"""Notebook chat routes that sit beside ``notebooks.router``: streaming answers, chat settings, re-index.

``notebooks.router`` builds this router at its bottom with its own auth, manager and
people-limits dependencies, so a test that overrides those on ``notebooks.router`` covers
these routes too.
"""
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .access import require_access, scoped
from .chat_config import normalize_config
from .manager import NotebookAccessError, NotebookManager, NotebookNotFoundError, NotebookValidationError, SourceNotFoundError
from .models import ChatConfigResponse, ChatConfigUpdate, NotebookChatRequest, SourceStatus, SourceType
from .rag_stream import citation_payload

logger = logging.getLogger(__name__)

# Sources whose text can be rebuilt without their original file (pasted text is also kept in the DB;
# a URL or video is fetched again).
_REBUILDS_WITHOUT_FILE = {SourceType.URL, SourceType.YOUTUBE, SourceType.TEXT, SourceType.MARKDOWN}
_BUSY = {SourceStatus.PENDING, SourceStatus.PROCESSING}

# People with a notebook-wide re-index running. In-process: one worker, one run at a time per person,
# so re-embedding a notebook cannot pile up behind itself on a shared machine.
_reindexing: Set[int] = set()


async def legacy_citation_dicts(
    manager: Any, notebook_id: UUID, user_id: int, citations: List[Any]
) -> List[Dict[str, Any]]:
    """The JSON citations of ``POST /chat``: the old keys plus ``start_char``, ``end_char`` and ``snippet``.

    Offsets the citation does not carry are read from the chunk metadata, for this person's
    notebook only; if that lookup fails the citation is returned without them.
    """
    missing = [c.chunk_id for c in citations
               if getattr(c, "chunk_id", None) and getattr(c, "start_char", None) is None]
    metadata: Dict[str, Dict[str, Any]] = {}
    pool = getattr(manager, "db_pool", None)
    if missing and pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT c.id, c.metadata FROM notebook_chunks c
                    JOIN notebooks n ON n.id = c.notebook_id
                    WHERE c.notebook_id = $1 AND n.user_id = $2 AND n.is_active = TRUE AND c.id = ANY($3::uuid[])
                    """,
                    notebook_id, user_id, missing,
                )
            for row in rows:
                meta = row["metadata"]
                if isinstance(meta, str):
                    meta = json.loads(meta)
                metadata[str(row["id"])] = meta if isinstance(meta, dict) else {}
        except Exception:
            logger.warning("Could not read citation offsets", exc_info=True)
    return [citation_payload(c, metadata.get(str(c.chunk_id))) for c in citations]


def reindex_blocker(source: Any) -> Optional[str]:
    """Why this source cannot be re-indexed right now, or None."""
    if source.status in _BUSY:
        return "This source is already being processed."
    if source.type not in _REBUILDS_WITHOUT_FILE and not (source.storage_path and os.path.exists(source.storage_path)):
        # Re-indexing clears the old passages first, so never start one that cannot read its file.
        return "The original file is no longer stored, so this source cannot be re-indexed. Upload it again."
    return None


async def _reindex_in_turn(manager: NotebookManager, user_id: int, source_ids: List[UUID]) -> None:
    from .ingestion import run_ingestion_task

    try:
        for source_id in source_ids:
            await run_ingestion_task(manager, source_id, user_id)
    finally:
        _reindexing.discard(user_id)


def make_router(
    *,
    get_user: Callable[..., Any],
    get_manager: Callable[..., Any],
    person_model: Callable[..., Any],
    pool_of: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(tags=["notebooks-chat"])

    # ─── Streaming chat ────────────────────────────────────────────────────────

    @router.post("/{notebook_id}/chat/stream")
    async def chat_with_notebook_stream(
        notebook_id: UUID,
        chat_request: NotebookChatRequest,
        request: Request,
        current_user: Dict = Depends(get_user),
        manager: NotebookManager = Depends(get_manager),
    ):
        """Chat with a notebook and receive the answer token by token (Server-Sent Events)."""
        from plugins.people.controls import allowed_for
        from .rag_chat import RAGChatService
        from .rag_stream import stream_notebook_answer

        user_id = int(current_user["id"])
        # Access first (404 for a stranger, 403 for a role that cannot chat), so asking about
        # someone else's notebook cannot use up a turn.
        access = await require_access(manager, notebook_id, user_id, "chat")
        try:
            notebook = await manager.get_notebook(notebook_id, access.owner_id)
        except NotebookNotFoundError:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # The admin's limits (Settings > People), identical to POST /chat: refused, or counted.
        picked = chat_request.model if "model" in chat_request.model_fields_set else ""
        chat_request.model = await person_model(request, current_user, picked) or chat_request.model
        allowed = await allowed_for(pool_of(request), user_id)
        service = RAGChatService(scoped(manager, access), allowed_models=allowed)

        return StreamingResponse(
            stream_notebook_answer(
                service, notebook, user_id, chat_request, is_disconnected=request.is_disconnected,
                redact=not access.can_read_sources,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ─── Chat settings ─────────────────────────────────────────────────────────

    @router.get("/{notebook_id}/chat-config", response_model=ChatConfigResponse)
    async def get_chat_config(
        notebook_id: UUID,
        request: Request,
        current_user: Dict = Depends(get_user),
        manager: NotebookManager = Depends(get_manager),
    ):
        """The notebook's persona, answer style, answer length and output language."""
        await require_access(manager, notebook_id, int(current_user["id"]), "meta")
        try:
            return ChatConfigResponse(**normalize_config(await manager.get_chat_config(notebook_id, int(current_user["id"]))))
        except NotebookNotFoundError:
            raise HTTPException(status_code=404, detail="Notebook not found")

    @router.put("/{notebook_id}/chat-config", response_model=ChatConfigResponse)
    async def put_chat_config(
        notebook_id: UUID,
        body: ChatConfigUpdate,
        request: Request,
        current_user: Dict = Depends(get_user),
        manager: NotebookManager = Depends(get_manager),
    ):
        """Change chat settings. Fields left out stay as they are; an empty persona or language clears it.

        Owner only: the persona is prompt text, and a shared person must not steer what the owner's
        notebook says to everyone else.
        """
        await require_access(manager, notebook_id, int(current_user["id"]), "owner")
        try:
            saved = await manager.set_chat_config(
                notebook_id, int(current_user["id"]), **body.model_dump(exclude_unset=True)
            )
        except NotebookNotFoundError:
            raise HTTPException(status_code=404, detail="Notebook not found")
        except NotebookAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except NotebookValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return ChatConfigResponse(**normalize_config(saved))

    # ─── Re-index (re-chunk and re-embed) ──────────────────────────────────────

    @router.post("/{notebook_id}/sources/{source_id}/reindex")
    async def reindex_source(
        notebook_id: UUID,
        source_id: UUID,
        background_tasks: BackgroundTasks,
        request: Request,
        current_user: Dict = Depends(get_user),
        manager: NotebookManager = Depends(get_manager),
    ):
        """Re-read one source and embed it again, e.g. after the embedding model changed."""
        from .ingestion import run_ingestion_task

        user_id = int(current_user["id"])
        try:
            source = await manager.get_source(source_id, user_id)
        except SourceNotFoundError:
            raise HTTPException(status_code=404, detail="Source not found")
        if str(source.notebook_id) != str(notebook_id):
            raise HTTPException(status_code=404, detail="Source not found")
        blocker = reindex_blocker(source)
        if blocker:
            raise HTTPException(status_code=409, detail=blocker)

        await manager.update_source_status(source_id, SourceStatus.PENDING)
        background_tasks.add_task(run_ingestion_task, manager, source_id, user_id)
        return {"message": "Re-indexing started", "source_id": str(source_id), "queued": 1}

    @router.post("/{notebook_id}/reindex")
    async def reindex_notebook(
        notebook_id: UUID,
        background_tasks: BackgroundTasks,
        request: Request,
        current_user: Dict = Depends(get_user),
        manager: NotebookManager = Depends(get_manager),
    ):
        """Re-index every source of the notebook, one after another."""
        user_id = int(current_user["id"])
        try:
            sources = await manager.list_sources(notebook_id, user_id)
        except NotebookNotFoundError:
            raise HTTPException(status_code=404, detail="Notebook not found")
        if user_id in _reindexing:
            raise HTTPException(status_code=409, detail="A re-index is already running. Wait for it to finish.")

        queued, skipped = [], []
        for source in sources:
            reason = reindex_blocker(source)
            if reason:
                skipped.append({"source_id": str(source.id), "title": source.title, "reason": reason})
            else:
                queued.append(source.id)
        if queued:
            _reindexing.add(user_id)
            try:
                for source_id in queued:
                    await manager.update_source_status(source_id, SourceStatus.PENDING)
            except Exception:
                _reindexing.discard(user_id)
                raise
            background_tasks.add_task(_reindex_in_turn, manager, user_id, queued)
        return {
            "message": "Re-indexing started" if queued else "Nothing to re-index",
            "queued": len(queued),
            "source_ids": [str(s) for s in queued],
            "skipped": skipped,
        }

    return router
