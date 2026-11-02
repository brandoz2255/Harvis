"""Who may do what to a notebook, decided in one place.

``NotebookManager.get_notebook_access`` says which role a person holds; this module turns a
role into allowed actions and hands routes an :class:`Access` to act with. The manager's
read and write methods are still keyed by the owner's id, so a route that has proved the
right role passes ``access.owner_id`` to them. Anything that is private to one person
(their chat turns) stays keyed by ``access.user_id``.

Roles and what they may do:

======== ===================================================================
owner    everything, including sharing and deleting the notebook
editor   read, chat, add/remove sources and notes; not share or delete
viewer   read sources, notes and artifacts; no chat, no changes
chat_only chat only; never sees a source's text, a note or a cited passage
======== ===================================================================

A person with no access, or whose share was revoked, gets 404 exactly like a notebook that
does not exist. A person with a lower role than the action needs gets 403.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import Depends, HTTPException, Request

from .manager import NoteNotFoundError, NotebookNotFoundError, SourceNotFoundError
from .models import Citation, MessageRole, NotebookChatMessage

logger = logging.getLogger(__name__)

# What each kind of request needs. "meta" is the notebook's title and counts.
NEEDS: Dict[str, Tuple[str, ...]] = {
    "meta": ("owner", "editor", "viewer", "chat_only"),
    "read": ("owner", "editor", "viewer"),
    "chat": ("owner", "editor", "chat_only"),
    "write": ("owner", "editor"),
    "owner": ("owner",),
}

# Keys of a citation that carry text copied out of a source.
_PASSAGE_KEYS = ("quote", "snippet", "start_char", "end_char", "text", "locator", "locator_range")


@dataclass(frozen=True)
class Access:
    notebook_id: UUID
    user_id: int
    role: str
    owner_id: int

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def can_read_sources(self) -> bool:
        return self.role in NEEDS["read"]


async def _owner_of(manager: Any, notebook_id: UUID) -> Optional[int]:
    async with manager.db_pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT user_id FROM notebooks WHERE id = $1 AND is_active = TRUE", notebook_id
        )
    return int(value) if value is not None else None


async def resolve_access(manager: Any, notebook_id: UUID, user_id: int) -> Optional[Access]:
    """The caller's access to an active notebook, or None when they have none."""
    getter = getattr(manager, "get_notebook_access", None)
    if getter is None:
        # A manager without sharing support: owner only, as before sharing existed.
        try:
            await manager.get_notebook(notebook_id, user_id)
        except NotebookNotFoundError:
            return None
        return Access(notebook_id, user_id, "owner", user_id)
    role = await getter(notebook_id, user_id)
    if role is None:
        return None
    owner_id = user_id if role == "owner" else await _owner_of(manager, notebook_id)
    if owner_id is None:
        return None
    return Access(notebook_id, user_id, role, owner_id)


async def require_access(manager: Any, notebook_id: UUID, user_id: int, need: str) -> Access:
    """Access for ``need`` ('meta', 'read', 'chat', 'write' or 'owner'), else 404 or 403."""
    if need not in NEEDS:
        raise ValueError(f"unknown need {need!r}")
    access = await resolve_access(manager, notebook_id, user_id)
    if access is None:
        raise HTTPException(status_code=404, detail="Notebook not found")
    if access.role not in NEEDS[need]:
        raise HTTPException(status_code=403, detail="Your role on this notebook does not allow that.")
    return access


def guard(get_user: Callable, get_manager: Callable) -> Callable[[str], Callable]:
    """Build ``guard(need)``, a FastAPI dependency for routes with a ``notebook_id`` path value.

    The router that owns the auth and manager dependencies passes them in, so test overrides
    on those two functions apply here as well.
    """

    def for_need(need: str) -> Callable:
        async def dependency(
            notebook_id: UUID,
            request: Request,
            current_user: Dict = Depends(get_user),
            manager: Any = Depends(get_manager),
        ) -> Access:
            return await require_access(manager, notebook_id, int(current_user["id"]), need)

        return dependency

    return for_need


def redact_citation(citation: Dict[str, Any]) -> Dict[str, Any]:
    """A citation dict without any text copied from a source (for the chat_only role)."""
    return {k: v for k, v in citation.items() if k not in _PASSAGE_KEYS}


def redact_citations(access: Access, citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return citations if access.can_read_sources else [redact_citation(c) for c in citations]


# ─── Lookups that must stay inside the notebook in the URL ─────────────────────

async def get_source_in(manager: Any, access: Access, source_id: UUID):
    """The source, only if it belongs to this access's notebook."""
    source = await manager.get_source(source_id, access.owner_id)
    if str(source.notebook_id) != str(access.notebook_id):
        raise SourceNotFoundError(f"Source {source_id} not found")
    return source


async def note_author_in(manager: Any, access: Access, note_id: UUID) -> int:
    """The id of the person who wrote the note, if it is in this access's notebook.

    ``NotebookManager`` keys a note's get/update/delete by its author, so an owner or editor
    acting on someone else's note passes that author's id.
    """
    async with manager.db_pool.acquire() as conn:
        author = await conn.fetchval(
            "SELECT user_id FROM notebook_notes WHERE id = $1 AND notebook_id = $2",
            note_id, access.notebook_id,
        )
    if author is None:
        raise NoteNotFoundError(f"Note {note_id} not found")
    return int(author)


# ─── Private chat: rows are keyed by (notebook_id, user_id) ────────────────────

def _message(row: Any, *, redact: bool) -> NotebookChatMessage:
    data = dict(row)
    raw = data.get("citations")
    if isinstance(raw, str):
        raw = json.loads(raw)
    cites = [Citation(**c) for c in (raw or [])]
    if redact:
        cites = [c.model_copy(update={"quote": None, "snippet": None, "start_char": None, "end_char": None}) for c in cites]
    data["citations"] = cites
    return NotebookChatMessage(**data)


async def get_own_chat_history(
    manager: Any, access: Access, limit: int = 50, offset: int = 0
) -> Tuple[List[NotebookChatMessage], int]:
    """This person's turns in this notebook; nobody else's, the owner's included."""
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, notebook_id, user_id, role, content, reasoning, citations, model_used, created_at
            FROM notebook_chat_messages
            WHERE notebook_id = $1 AND user_id = $2
            ORDER BY created_at ASC
            LIMIT $3 OFFSET $4
            """,
            access.notebook_id, access.user_id, limit, offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM notebook_chat_messages WHERE notebook_id = $1 AND user_id = $2",
            access.notebook_id, access.user_id,
        )
    return [_message(r, redact=not access.can_read_sources) for r in rows], int(total or 0)


async def clear_own_chat_history(manager: Any, access: Access) -> None:
    """Delete this person's turns only."""
    async with manager.db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM notebook_chat_messages WHERE notebook_id = $1 AND user_id = $2",
            access.notebook_id, access.user_id,
        )


class ScopedManager:
    """A NotebookManager that acts for one person on one notebook they were already admitted to.

    ``RAGChatService`` checks ownership with ``get_notebook`` and saves turns with
    ``add_chat_message``, both owner-only on the real manager. This stand-in answers those two
    for the admitted person and passes everything else through. It is built only after
    :func:`require_access`, and refuses any other notebook or person.
    """

    def __init__(self, manager: Any, access: Access):
        self._manager = manager
        self._access = access

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)

    def _check(self, notebook_id: UUID, user_id: int) -> None:
        if str(notebook_id) != str(self._access.notebook_id) or int(user_id) != self._access.user_id:
            raise NotebookNotFoundError(f"Notebook {notebook_id} not found")

    async def get_notebook(self, notebook_id: UUID, user_id: int):
        self._check(notebook_id, user_id)
        return await self._manager.get_notebook(notebook_id, self._access.owner_id)

    async def add_chat_message(
        self,
        notebook_id: UUID,
        user_id: int,
        role: MessageRole,
        content: str,
        reasoning: Optional[str] = None,
        citations: Optional[List[Citation]] = None,
        model_used: Optional[str] = None,
    ) -> NotebookChatMessage:
        self._check(notebook_id, user_id)
        payload = json.dumps([c.model_dump() for c in (citations or [])], default=str)
        async with self._manager.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO notebook_chat_messages
                    (notebook_id, user_id, role, content, reasoning, citations, model_used)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, notebook_id, user_id, role, content, reasoning, citations, model_used, created_at
                """,
                notebook_id, user_id, role.value, content, reasoning, payload, model_used,
            )
        return _message(row, redact=False)


def scoped(manager: Any, access: Access) -> Any:
    """The manager to give a service that does its own owner check; the real one for the owner."""
    return manager if access.is_owner else ScopedManager(manager, access)
