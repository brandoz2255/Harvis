"""Harvis Custom Sub-Agents — a user-defined specialist the P5 orchestrator can
delegate to (Claude-Code-subagent style): name + description (used for
auto-delegation) + dedicated system prompt + allowed tools + allowed skills +
allowed connectors (MCPs) + a model. Mirrors the skills.py house pattern:
DDL created at startup (main.py), owner-scoped CRUD registered in router.py.

Runtime consumption lives in workspace/orchestration/subagent_defs.py. NOTE
(honest scope): mcp_ids are stored + surfaced as attached config only — live
MCP tool-calling in runs is deferred (Phase G) unless HARVIS_MCP_LIVE.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

CREATE_OWUI_SUBAGENTS_SQL = """
CREATE TABLE IF NOT EXISTS owui_subagents (
    id            TEXT PRIMARY KEY,
    user_id       INTEGER NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    allowed_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    skill_ids     JSONB NOT NULL DEFAULT '[]'::jsonb,
    mcp_ids       JSONB NOT NULL DEFAULT '[]'::jsonb,
    model         TEXT,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_owui_subagents_user ON owui_subagents(user_id, updated_at DESC);
"""

# Claude-Code-style handle: lowercase kebab, starts with a letter, <= 40 chars.
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

# v1: a sub-agent may only pin a LOCAL model — cloud models need per-user creds
# the sub-agent runner can't assume (see subagent_defs._local_model_or_empty).
_CLOUD_MODEL_PREFIXES = ("anthropic/", "openai/")


def _clean_name(raw: Optional[str]) -> str:
    name = (raw or "").strip().lower()
    if not name or len(name) > 40 or not _NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Sub-agent name must be kebab-case (e.g. 'code-reviewer'), max 40 chars.",
        )
    return name


def _clean_str_list(v) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for x in v:
        s = str(x).strip()
        if s and s not in out:
            out.append(s[:200])
    return out[:64]


def _clean_model(raw: Optional[str]) -> Optional[str]:
    m = (raw or "").strip()
    if not m:
        return None
    if m.startswith(_CLOUD_MODEL_PREFIXES):
        raise HTTPException(
            status_code=400,
            detail="v1 sub-agents run local models only — leave the model empty to inherit the run's model.",
        )
    return m[:200]


def _j(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v


def _subagent_to_dict(row) -> dict:
    created = row["created_at"]
    updated = row["updated_at"]
    return {
        "id": row["id"],
        "user_id": str(row["user_id"]),
        "name": row["name"],
        "description": row["description"] or "",
        "system_prompt": row["system_prompt"] or "",
        "allowed_tools": _j(row["allowed_tools"]) or [],
        "skill_ids": _j(row["skill_ids"]) or [],
        "mcp_ids": _j(row["mcp_ids"]) or [],
        "model": row["model"],
        "enabled": row["enabled"],
        "created_at": int(created.timestamp()) if created else None,
        "updated_at": int(updated.timestamp()) if updated else None,
    }


class SubAgentForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    allowed_tools: Optional[list] = None
    skill_ids: Optional[list] = None
    mcp_ids: Optional[list] = None
    model: Optional[str] = None


def register_subagent_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        return pool

    @router.get("/api/owui/subagents")
    async def subagents_list(request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM owui_subagents WHERE user_id=$1 ORDER BY name",
                int(user.id),
            )
        return {"items": [_subagent_to_dict(r) for r in rows]}

    @router.post("/api/owui/subagents")
    async def subagents_create(form: SubAgentForm, request: Request, user=Depends(get_current_user)):
        name = _clean_name(form.name)
        model = _clean_model(form.model)
        pool = _pool(request)
        sid = str(uuid.uuid4())
        async with pool.acquire() as conn:
            dup = await conn.fetchval(
                "SELECT 1 FROM owui_subagents WHERE user_id=$1 AND name=$2", int(user.id), name
            )
            if dup:
                raise HTTPException(status_code=409, detail=f"A sub-agent named '{name}' already exists.")
            row = await conn.fetchrow(
                "INSERT INTO owui_subagents "
                "(id, user_id, name, description, system_prompt, allowed_tools, skill_ids, mcp_ids, model) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9) RETURNING *",
                sid, int(user.id), name, (form.description or "").strip(),
                form.system_prompt or "",
                json.dumps(_clean_str_list(form.allowed_tools)),
                json.dumps(_clean_str_list(form.skill_ids)),
                json.dumps(_clean_str_list(form.mcp_ids)),
                model,
            )
        return _subagent_to_dict(row)

    @router.get("/api/owui/subagents/{subagent_id}")
    async def subagents_get(subagent_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM owui_subagents WHERE id=$1 AND user_id=$2", subagent_id, int(user.id)
            )
        if not row:
            raise HTTPException(status_code=404, detail="Sub-agent not found")
        return _subagent_to_dict(row)

    @router.post("/api/owui/subagents/{subagent_id}/update")
    async def subagents_update(subagent_id: str, form: SubAgentForm, request: Request,
                               user=Depends(get_current_user)):
        pool = _pool(request)
        name = _clean_name(form.name) if form.name is not None else None
        # form.model semantics: absent → keep; "" → clear; value → validate.
        model_set = form.model is not None
        model = _clean_model(form.model) if model_set else None
        async with pool.acquire() as conn:
            if name is not None:
                dup = await conn.fetchval(
                    "SELECT 1 FROM owui_subagents WHERE user_id=$1 AND name=$2 AND id<>$3",
                    int(user.id), name, subagent_id,
                )
                if dup:
                    raise HTTPException(status_code=409, detail=f"A sub-agent named '{name}' already exists.")
            row = await conn.fetchrow(
                "UPDATE owui_subagents SET "
                "name = COALESCE($3, name), "
                "description = COALESCE($4, description), "
                "system_prompt = COALESCE($5, system_prompt), "
                "allowed_tools = COALESCE($6::jsonb, allowed_tools), "
                "skill_ids = COALESCE($7::jsonb, skill_ids), "
                "mcp_ids = COALESCE($8::jsonb, mcp_ids), "
                "model = CASE WHEN $9 THEN $10 ELSE model END, "
                "updated_at = NOW() "
                "WHERE id=$1 AND user_id=$2 RETURNING *",
                subagent_id, int(user.id), name,
                form.description.strip() if form.description is not None else None,
                form.system_prompt,
                json.dumps(_clean_str_list(form.allowed_tools)) if form.allowed_tools is not None else None,
                json.dumps(_clean_str_list(form.skill_ids)) if form.skill_ids is not None else None,
                json.dumps(_clean_str_list(form.mcp_ids)) if form.mcp_ids is not None else None,
                model_set, model,
            )
        if not row:
            raise HTTPException(status_code=404, detail="Sub-agent not found")
        return _subagent_to_dict(row)

    @router.post("/api/owui/subagents/{subagent_id}/toggle")
    async def subagents_toggle(subagent_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE owui_subagents SET enabled = NOT enabled, updated_at = NOW() "
                "WHERE id=$1 AND user_id=$2 RETURNING *",
                subagent_id, int(user.id),
            )
        if not row:
            raise HTTPException(status_code=404, detail="Sub-agent not found")
        return _subagent_to_dict(row)

    @router.delete("/api/owui/subagents/{subagent_id}")
    async def subagents_delete(subagent_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM owui_subagents WHERE id=$1 AND user_id=$2", subagent_id, int(user.id)
            )
        return True
