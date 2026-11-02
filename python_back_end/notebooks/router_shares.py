"""Notebook sharing routes: who else may open a notebook, and as what.

``notebooks.router`` builds this router at its bottom with its own auth and manager
dependencies, so a test that overrides those covers these routes too.

Only the owner manages shares. Everyone else needs a signed-in account: a link is a code
that a signed-in person redeems (``POST /shares/accept``), which turns it into a share for
that person. There is no anonymous access. Revoking a link stops new people joining with it;
people who already joined hold their own share, which is revoked on its own.
"""
import logging
import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, List, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .access import Access, guard
from .manager import NotebookManager, NotebookValidationError

logger = logging.getLogger(__name__)

Role = Literal["viewer", "chat_only", "editor"]

# Failed link redemptions allowed per person in a window. Tokens carry 192 bits, so this only
# stops a script from hammering the endpoint.
MAX_BAD_TOKENS = 10
BAD_TOKEN_WINDOW_SECONDS = 300
_bad_tokens: Dict[int, Deque[float]] = defaultdict(deque)


class AddShareRequest(BaseModel):
    user: str = Field(min_length=1, max_length=254, description="Username or email of an existing account")
    role: Role


class LinkShareRequest(BaseModel):
    role: Role


class AcceptLinkRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)


def _too_many_bad_tokens(user_id: int) -> bool:
    attempts = _bad_tokens[user_id]
    cutoff = time.monotonic() - BAD_TOKEN_WINDOW_SECONDS
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    if not attempts:
        _bad_tokens.pop(user_id, None)
    return len(attempts) >= MAX_BAD_TOKENS


def _note_bad_token(user_id: int) -> None:
    _bad_tokens[user_id].append(time.monotonic())


def _public(share: Dict[str, Any], names: Dict[int, str]) -> Dict[str, Any]:
    """A share as the API shows it: never the stored link hash, and the username for a person."""
    out = {
        "id": str(share["id"]),
        "notebook_id": str(share["notebook_id"]),
        "kind": share["kind"],
        "role": share["role"],
        "user_id": share.get("user_id"),
        "username": names.get(share["user_id"]) if share.get("user_id") is not None else None,
        "created_at": share["created_at"],
        "revoked_at": share.get("revoked_at"),
    }
    if "token" in share:
        out["token"] = share["token"]
    return out


async def _usernames(manager: Any, user_ids: List[int]) -> Dict[int, str]:
    if not user_ids:
        return {}
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, username FROM users WHERE id = ANY($1::int[])", user_ids)
    return {int(r["id"]): r["username"] for r in rows}


async def _find_user(manager: Any, handle: str) -> Dict[str, Any]:
    """The account whose email, else username, matches ``handle`` (case-insensitive)."""
    handle = handle.strip()
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, username FROM users
            WHERE lower(email) = lower($1) OR lower(username) = lower($1)
            ORDER BY (lower(email) = lower($1)) DESC
            LIMIT 1
            """,
            handle,
        )
    if not row:
        raise HTTPException(status_code=404, detail="No account matches that username or email.")
    return {"id": int(row["id"]), "username": row["username"]}


def make_router(*, get_user: Callable[..., Any], get_manager: Callable[..., Any]) -> APIRouter:
    router = APIRouter(tags=["notebook-shares"])
    need = guard(get_user, get_manager)

    # Fixed paths first: they must not be read as a notebook id.

    @router.post("/shares/accept")
    async def accept_link(
        body: AcceptLinkRequest,
        current_user: Dict = Depends(get_user),
        manager: NotebookManager = Depends(get_manager),
    ):
        """Redeem a link code as the signed-in person; returns the notebook and the role they now hold."""
        user_id = int(current_user["id"])
        if _too_many_bad_tokens(user_id):
            raise HTTPException(status_code=429, detail="Too many invalid link codes. Try again in a few minutes.")
        joined = await manager.accept_link_share(body.token.strip(), user_id)
        if not joined:
            _note_bad_token(user_id)
            raise HTTPException(status_code=404, detail="That link is not valid or was revoked.")
        return {"notebook_id": str(joined["notebook_id"]), "role": joined["role"]}

    @router.get("/shares/received")
    async def notebooks_shared_with_me(
        current_user: Dict = Depends(get_user),
        manager: NotebookManager = Depends(get_manager),
    ):
        """Notebooks other people shared with the signed-in person, with the role held."""
        async with manager.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT n.id, n.title, n.emoji, n.description, n.updated_at, s.role,
                       u.username AS owner_username
                FROM notebook_shares s
                JOIN notebooks n ON n.id = s.notebook_id AND n.is_active = TRUE
                JOIN users u ON u.id = n.user_id
                WHERE s.user_id = $1 AND s.revoked_at IS NULL AND n.user_id <> $1
                ORDER BY n.updated_at DESC
                """,
                int(current_user["id"]),
            )
        return [
            {
                "notebook_id": str(r["id"]),
                "title": r["title"],
                "emoji": r["emoji"],
                "description": r["description"],
                "role": r["role"],
                "owner_username": r["owner_username"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    @router.get("/{notebook_id}/my-access")
    async def my_access(access: Access = Depends(need("meta"))):
        """The signed-in person's role on this notebook, so the UI can hide what they cannot do."""
        return {
            "notebook_id": str(access.notebook_id),
            "role": access.role,
            "is_owner": access.is_owner,
            "can_read_sources": access.can_read_sources,
            "can_chat": access.role in ("owner", "editor", "chat_only"),
            "can_edit": access.role in ("owner", "editor"),
        }

    @router.get("/{notebook_id}/shares")
    async def list_shares(
        access: Access = Depends(need("owner")),
        manager: NotebookManager = Depends(get_manager),
    ):
        shares = await manager.list_shares(access.notebook_id, access.owner_id)
        names = await _usernames(manager, [s["user_id"] for s in shares if s.get("user_id") is not None])
        return {"shares": [_public(s, names) for s in shares]}

    @router.post("/{notebook_id}/shares")
    async def share_with_user(
        body: AddShareRequest,
        access: Access = Depends(need("owner")),
        manager: NotebookManager = Depends(get_manager),
    ):
        """Give an existing account a role; sharing again with the same account changes their role."""
        target = await _find_user(manager, body.user)
        if target["id"] == access.owner_id:
            raise HTTPException(status_code=400, detail="You already own this notebook.")
        try:
            share = await manager.create_user_share(access.notebook_id, access.owner_id, target["id"], body.role)
        except NotebookValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _public(share, {target["id"]: target["username"]})

    @router.post("/{notebook_id}/shares/link")
    async def create_link(
        body: LinkShareRequest,
        access: Access = Depends(need("owner")),
        manager: NotebookManager = Depends(get_manager),
    ):
        """Make a link code. The code is in this response only; the server keeps a hash."""
        try:
            share = await manager.create_link_share(access.notebook_id, access.owner_id, body.role)
        except NotebookValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _public(share, {})

    @router.delete("/{notebook_id}/shares/{share_id}")
    async def revoke(
        share_id: UUID,
        access: Access = Depends(need("owner")),
        manager: NotebookManager = Depends(get_manager),
    ):
        """Revoke a person's share or a link. Access ends on the person's next request."""
        if not await manager.revoke_share(access.notebook_id, access.owner_id, share_id):
            raise HTTPException(status_code=404, detail="Share not found")
        return {"message": "Share revoked"}

    return router

