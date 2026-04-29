"""User-facing CRUD for per-user memories (Phase 4 storage)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized

from .manager import get_manager

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryEntryView(BaseModel):
    content: str
    source: str
    metadata: dict = Field(default_factory=dict)
    created_at: Optional[str] = None


class CreateMemoryPayload(BaseModel):
    content: str = Field(..., min_length=1, max_length=20_000)
    source: str = Field(default="manual", max_length=100)
    metadata: dict = Field(default_factory=dict)


async def _provider(request: Request):
    """Lazy-activate the global MemoryManager against the app pool."""
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    mgr = get_manager()
    if mgr.provider is None:
        try:
            await mgr.activate(config={"pool": pool})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"memory provider activate failed: {e}")
    if mgr.provider is None:
        raise HTTPException(status_code=503, detail="no memory provider active")
    return mgr.provider


@router.get("", response_model=dict)
async def list_my_memories(
    request: Request,
    query: Optional[str] = Query(default=None, max_length=500),
    limit: int = Query(default=50, ge=1, le=500),
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    provider = await _provider(request)
    user_id = current_user["id"]
    entries = await provider.recall(user_id, query=query, limit=limit)
    return {
        "entries": [
            MemoryEntryView(
                content=e.content,
                source=e.source,
                metadata=dict(e.metadata or {}),
                created_at=e.created_at.isoformat() if e.created_at else None,
            ).model_dump()
            for e in entries
        ]
    }


@router.post("")
async def create_my_memory(
    body: CreateMemoryPayload,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    provider = await _provider(request)
    user_id = current_user["id"]
    saved = await provider.remember(
        user_id, body.content, source=body.source, metadata=body.metadata,
    )
    if saved is None:
        raise HTTPException(status_code=500, detail="memory save failed")
    return {
        "ok": True,
        "entry": MemoryEntryView(
            content=saved.content,
            source=saved.source,
            metadata=dict(saved.metadata or {}),
            created_at=saved.created_at.isoformat() if saved.created_at else None,
        ).model_dump(),
    }


@router.delete("")
async def clear_my_memories(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    provider = await _provider(request)
    user_id = current_user["id"]
    deleted = await provider.forget(user_id)
    return {"ok": True, "deleted": int(deleted or 0)}


@router.get("/provider")
async def memory_provider_info(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),  # noqa: ARG001
) -> dict:
    """Diagnostic — which memory provider is active for this backend."""
    provider = await _provider(request)
    return {
        "active": True,
        "name": getattr(provider, "name", "unknown"),
        "class": type(provider).__name__,
    }
