"""User-facing CRUD for per-user SOUL.md content.

JWT-auth via the existing get_current_user_optimized dependency. Routes
operate against the active user's row in the user_soul table.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized

from .loader import (
    DEFAULT_SOUL_MD,
    clear_soul,
    load_soul,
    load_soul_with_default,
    save_soul,
    seed_default_if_missing,
)

router = APIRouter(prefix="/api/soul", tags=["soul"])


class SoulPayload(BaseModel):
    content: str = Field(..., min_length=0, max_length=200_000)


class SoulView(BaseModel):
    has_soul: bool
    content: str
    is_default: bool


@router.get("", response_model=SoulView)
async def get_my_soul(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> SoulView:
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    user_id = current_user["id"]
    saved = await load_soul(pool, user_id)
    if saved is None or not saved.strip():
        return SoulView(has_soul=False, content=DEFAULT_SOUL_MD, is_default=True)
    return SoulView(has_soul=True, content=saved, is_default=False)


@router.put("")
async def put_my_soul(
    body: SoulPayload,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    user_id = current_user["id"]
    ts = await save_soul(pool, user_id, body.content)
    if ts is None:
        raise HTTPException(status_code=500, detail="save failed")
    return {"ok": True, "updated_at": ts.isoformat()}


@router.delete("")
async def delete_my_soul(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    user_id = current_user["id"]
    ok = await clear_soul(pool, user_id)
    return {"ok": bool(ok)}


@router.post("/seed-default")
async def seed_default(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    """Seed DEFAULT_SOUL_MD as the user's SOUL.md if they have none.

    Convenience for first-run UX — the frontend can call this on a new
    user's first visit to give them a starting template.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    user_id = current_user["id"]
    seeded = await seed_default_if_missing(pool, user_id)
    return {"ok": True, "seeded": bool(seeded)}
