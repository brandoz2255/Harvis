"""Skills the user switches on, edits and deletes from the Hermes UI.

Switching a skill ON is the human approval the fail-closed skill gate asks for
(owui_compat.skills.gated_skill_blocks wants ``audit.verdict == 'supported'``):
Harvis drafts skills itself (learn.draft_skill) and saves them OFF, and the
"Harvis learned a skill ▸ Enable" toast or the Skills tab switch is where a
person vouches for one. Without this an agent-written skill could never apply.

``/learning/node`` is the skill editor's read/save/delete door (the desktop app
names skills by node id; here that is the skill name, optionally ``skill:``-prefixed).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

log = logging.getLogger("hermes_ui.rest")

router = APIRouter(prefix="/hermes-api/api", tags=["hermes-ui"])

MAX_CONTENT = 20000


def _uid(user) -> int:
    return int(getattr(user, "id", None) or getattr(user, "user_id", None) or user["id"])


def _pool(request: Request):
    return request.app.state.pg_pool


def _node_name(raw: str) -> str:
    name = (raw or "").strip()
    return name[len("skill:"):] if name.startswith("skill:") else name


def approval(user_id: int, via: str) -> dict:
    """The audit record a person switching a skill on leaves behind."""
    return {"verdict": "supported", "approved_by": user_id, "via": via,
            "approved_at": datetime.now(timezone.utc).isoformat()}


# The desktop Capabilities screen sends PUT (src/api/skills.ts setSkillEnabled);
# accept POST too so any older/OWUI caller keeps working.
@router.api_route("/skills/toggle", methods=["POST", "PUT"])
async def skill_toggle(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    name, enabled = str(body.get("name") or ""), bool(body.get("enabled"))
    uid = _uid(user)
    async with _pool(request).acquire() as conn:
        # ON also approves (unless already approved), and a draft graduates out
        # of the "drafts" category; OFF leaves the audit alone.
        tag = await conn.execute(
            "UPDATE owui_skills SET enabled=$3, updated_at=NOW(), meta = CASE WHEN $3 THEN "
            "  (CASE WHEN COALESCE(meta->'audit'->>'verdict','') = 'supported' THEN meta "
            "        ELSE jsonb_set(meta, '{audit}', $4::jsonb) END)"
            "  || (CASE WHEN meta->>'category' = 'drafts' THEN '{\"category\":\"learned\"}'::jsonb "
            "           ELSE '{}'::jsonb END) "
            "ELSE meta END "
            "WHERE user_id=$1 AND name=$2",
            uid, name, enabled, json.dumps(approval(uid, "hermes-toggle")))
    return {"ok": tag.endswith("1"), "name": name, "enabled": enabled}


@router.get("/learning/node")
async def learning_node(request: Request, user=Depends(get_current_user_optimized)):
    name = _node_name(request.query_params.get("id") or "")
    async with _pool(request).acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, content FROM owui_skills WHERE user_id=$1 AND name=$2", _uid(user), name)
    if not row:
        raise HTTPException(404, f"skill not found: {name}")
    return {"ok": True, "kind": "skill", "label": row["name"], "content": row["content"]}


@router.put("/learning/node")
async def learning_node_edit(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    name = _node_name(str(body.get("id") or ""))
    content = str(body.get("content") or "")
    if not content.strip():
        raise HTTPException(400, "A skill can't be empty.")
    if len(content) > MAX_CONTENT:
        raise HTTPException(400, f"A skill can be at most {MAX_CONTENT} characters.")
    # The person editing is the person vouching for it, so the verdict stays
    # (OWUI's editor clears it because there an edit can come from anyone with access).
    async with _pool(request).acquire() as conn:
        tag = await conn.execute(
            "UPDATE owui_skills SET content=$3, updated_at=NOW() WHERE user_id=$1 AND name=$2",
            _uid(user), name, content)
    if not tag.endswith("1"):
        raise HTTPException(404, f"skill not found: {name}")
    return {"ok": True, "message": f"Saved {name}."}


@router.delete("/learning/node")
async def learning_node_delete(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    name = _node_name(str(body.get("id") or ""))
    async with _pool(request).acquire() as conn:
        tag = await conn.execute("DELETE FROM owui_skills WHERE user_id=$1 AND name=$2", _uid(user), name)
    if not tag.endswith("1"):
        raise HTTPException(404, f"skill not found: {name}")
    return {"ok": True, "message": f"Deleted {name}."}
