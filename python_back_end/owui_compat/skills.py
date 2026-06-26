"""Harvis user-created Skills — the "Customize" half that lets a user author a
skill (a SKILL.md-style capability: name + description + markdown body) and have
it stored, listed, toggled, and edited. Mirrors the knowledge.py house pattern.

These replace the old GET /api/v1/skills/ stub (which returned []). The existing
OWUI skills frontend client (lib/apis/skills/index.ts) + the Agent Studio Brain
panel consume these. NOTE (honest scope): created skills are stored + surfaced in
the UI; auto-loading them into the live OpenClaw agent runtime (which reads
SKILL.md from a /skills mount) is a deferred follow-up — see the design note.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

CREATE_OWUI_SKILLS_SQL = """
CREATE TABLE IF NOT EXISTS owui_skills (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    emoji       TEXT,
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_owui_skills_user ON owui_skills(user_id, updated_at DESC);
"""


def _skill_to_owui(row) -> dict:
    meta = row["meta"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    created = row["created_at"]
    updated = row["updated_at"]
    return {
        "id": row["id"],
        "user_id": str(row["user_id"]),
        "name": row["name"],
        "description": row["description"] or "",
        "content": row["content"] or "",
        "emoji": row["emoji"],
        "meta": meta or {},
        "enabled": row["enabled"],
        "created_at": int(created.timestamp()) if created else None,
        "updated_at": int(updated.timestamp()) if updated else None,
    }


class SkillForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    emoji: Optional[str] = None
    meta: Optional[dict] = None
    # OWUI clients sometimes send these; accepted + ignored.
    access_control: Optional[dict] = None
    access_grants: Optional[list] = None


def register_skill_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        return pool

    async def _list(request: Request, user) -> list:
        pool = _pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM owui_skills WHERE user_id=$1 ORDER BY updated_at DESC",
                int(user.id),
            )
        return [_skill_to_owui(r) for r in rows]

    # ── list (literals before /id/{id}) ──
    @router.get("/api/v1/skills/")
    async def skills_list(request: Request, user=Depends(get_current_user)):
        return await _list(request, user)

    @router.get("/api/v1/skills/list")
    async def skills_list_paginated(request: Request, user=Depends(get_current_user),
                                    query: str = None, page: int = None):  # noqa: ARG001
        items = await _list(request, user)
        if query:
            q = query.lower()
            items = [s for s in items if q in (s["name"] or "").lower() or q in (s["description"] or "").lower()]
        return {"items": items, "total": len(items)}

    @router.get("/api/v1/skills/export")
    async def skills_export(request: Request, user=Depends(get_current_user)):
        return await _list(request, user)

    @router.post("/api/v1/skills/create")
    async def skills_create(form: SkillForm, request: Request, user=Depends(get_current_user)):
        name = (form.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Skill name is required.")
        pool = _pool(request)
        sid = str(uuid.uuid4())
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO owui_skills (id, user_id, name, description, content, emoji, meta) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *",
                sid, int(user.id), name, form.description or "", form.content or "",
                form.emoji, json.dumps(form.meta or {}),
            )
        return _skill_to_owui(row)

    @router.get("/api/v1/skills/id/{skill_id}")
    async def skills_get(skill_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM owui_skills WHERE id=$1 AND user_id=$2", skill_id, int(user.id)
            )
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        return _skill_to_owui(row)

    @router.post("/api/v1/skills/id/{skill_id}/update")
    async def skills_update(skill_id: str, form: SkillForm, request: Request,
                            user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE owui_skills SET "
                "name = COALESCE($3, name), "
                "description = COALESCE($4, description), "
                "content = COALESCE($5, content), "
                "emoji = COALESCE($6, emoji), "
                "meta = CASE WHEN $7::jsonb IS NULL THEN meta ELSE $7::jsonb END, "
                "updated_at = NOW() "
                "WHERE id=$1 AND user_id=$2 RETURNING *",
                skill_id, int(user.id), form.name, form.description, form.content,
                form.emoji, json.dumps(form.meta) if form.meta is not None else None,
            )
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        return _skill_to_owui(row)

    @router.post("/api/v1/skills/id/{skill_id}/toggle")
    async def skills_toggle(skill_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE owui_skills SET enabled = NOT enabled, updated_at = NOW() "
                "WHERE id=$1 AND user_id=$2 RETURNING *",
                skill_id, int(user.id),
            )
        if not row:
            raise HTTPException(status_code=404, detail="Skill not found")
        return _skill_to_owui(row)

    @router.delete("/api/v1/skills/id/{skill_id}/delete")
    async def skills_delete(skill_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM owui_skills WHERE id=$1 AND user_id=$2", skill_id, int(user.id)
            )
        return True
