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
import re
import uuid
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


_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")


def skill_name(content: str, given: str = "") -> str:
    """The skill's name: what the user typed, else frontmatter ``name:``, else the first heading."""
    name = (given or "").strip()
    if not name and content.startswith("---"):
        end = content.find("\n---", 3)
        for line in content[3:end if end != -1 else 0].splitlines():
            if line.strip().startswith("name:"):
                name = line.split(":", 1)[1].strip().strip("'\"")
                break
    if not name:
        m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        name = m.group(1).strip() if m else ""
    return name


@router.post("/skills")
async def skill_create(request: Request, user=Depends(get_current_user_optimized)):
    """Add a skill the user wrote or uploaded (a SKILL.md). The person adding it
    is the person vouching for it, so it is saved on and approved."""
    from owui_compat.skills import _parse_skill_md

    body = await request.json()
    content = str(body.get("content") or "")
    if not content.strip():
        raise HTTPException(400, "A skill can't be empty.")
    if len(content) > MAX_CONTENT:
        raise HTTPException(400, f"A skill can be at most {MAX_CONTENT} characters.")
    name = skill_name(content, str(body.get("name") or ""))
    if not name:
        raise HTTPException(400, "Give the skill a name, or start it with a '# Heading'.")
    if not _NAME_OK.match(name):
        raise HTTPException(400, "Use letters, numbers, spaces, dots, dashes or underscores (up to 64).")
    description, _body, emoji = _parse_skill_md(content)
    uid = _uid(user)
    meta = {"category": "custom", "audit": approval(uid, "hermes-add")}
    async with _pool(request).acquire() as conn:
        if await conn.fetchval("SELECT 1 FROM owui_skills WHERE user_id=$1 AND name=$2", uid, name):
            raise HTTPException(409, f"You already have a skill called {name}.")
        await conn.execute(
            "INSERT INTO owui_skills (id, user_id, name, description, content, emoji, meta, enabled) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, TRUE)",
            str(uuid.uuid4()), uid, name, description, content, emoji or None, json.dumps(meta))
    return {"ok": True, "name": name, "message": f"Added {name}. Harvis will use it when a chat matches."}


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
