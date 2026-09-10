"""/api/agents — CRUD for agent teammates.

JWT-auth via the same get_current_user_optimized dependency the rest of the
plugin routers use. Every query is owner-scoped in SQL (``user_id=$n``), so a
guessed agent id from another account returns 404 rather than someone else's
teammate.

POST /{id}/run is the roster's "give it a goal" button. It goes through the
same intake door as chat and cron so a run behaves identically wherever it was
started from.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth_optimized import get_current_user_optimized

from . import computer, intake, store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])
# Mounted first: "/computer/sessions" must never be matched as "/{agent_id}/...".
router.include_router(computer.router)


def _pool(request: Request):
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not ready")
    return pool


def _uid(current_user) -> int:
    # The dependency hands back a dict here; objects elsewhere in the codebase.
    raw = current_user["id"] if isinstance(current_user, dict) else getattr(current_user, "id")
    return int(raw)


@router.post("/ensure-default")
async def agents_ensure_default(request: Request, current_user=Depends(get_current_user_optimized)):
    """The teammate Work mode talks to, made on first use. Declared before the
    ``/{agent_id}`` routes so "ensure-default" is never read as an agent id."""
    return await store.ensure_default_assistant(_pool(request), _uid(current_user))


class RunForm(BaseModel):
    goal: str
    # None → read it out of the goal wording ("just do all of it"); an explicit
    # bool is the roster's toggle and wins over the wording.
    override: Optional[bool] = None
    session_id: Optional[str] = None


class AgentForm(BaseModel):
    """All fields optional so the same model serves create and partial update.

    ``name`` is the only one create insists on, checked in the handler.
    """

    name: Optional[str] = None
    title: Optional[str] = None
    job: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    avatar: Optional[dict] = None
    engine: Optional[str] = None
    autonomy: Optional[dict] = None
    budget: Optional[dict] = None
    check_ins: Optional[list] = None
    allowed_tools: Optional[list] = None
    skill_ids: Optional[list] = None
    mcp_ids: Optional[list] = None
    model: Optional[str] = None
    enabled: Optional[bool] = None
    pinned_chat_id: Optional[str] = None


def _fields(form: AgentForm) -> dict[str, Any]:
    """Only the keys the caller actually sent, so absent means "leave alone"."""
    return form.model_dump(exclude_unset=True)


@router.get("")
async def agents_list(request: Request, current_user=Depends(get_current_user_optimized)):
    items = await store.list_teammates(_pool(request), _uid(current_user))
    return {"items": items}


@router.post("")
async def agents_create(
    form: AgentForm, request: Request, current_user=Depends(get_current_user_optimized)
):
    try:
        return await store.create_agent(_pool(request), _uid(current_user), _fields(form))
    except store.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/{agent_id}")
async def agents_get(
    agent_id: str, request: Request, current_user=Depends(get_current_user_optimized)
):
    agent = await store.get_agent(_pool(request), _uid(current_user), agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/{agent_id}")
async def agents_update(
    agent_id: str,
    form: AgentForm,
    request: Request,
    current_user=Depends(get_current_user_optimized),
):
    try:
        agent = await store.update_agent(
            _pool(request), _uid(current_user), agent_id, _fields(form)
        )
    except store.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/{agent_id}")
async def agents_delete(
    agent_id: str, request: Request, current_user=Depends(get_current_user_optimized)
):
    ok = await store.delete_agent(_pool(request), _uid(current_user), agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"deleted": True}


@router.post("/{agent_id}/default")
async def agents_set_default(
    agent_id: str, request: Request, current_user=Depends(get_current_user_optimized)
):
    agent = await store.set_default_assistant(_pool(request), _uid(current_user), agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/{agent_id}/runs")
async def agents_runs(
    agent_id: str,
    request: Request,
    limit: int = 25,
    current_user=Depends(get_current_user_optimized),
):
    pool = _pool(request)
    uid = _uid(current_user)
    if not await store.get_agent(pool, uid, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"items": await store.list_runs(pool, uid, agent_id, limit)}


@router.get("/{agent_id}/audit")
async def agents_audit(
    agent_id: str,
    request: Request,
    limit: int = 100,
    current_user=Depends(get_current_user_optimized),
):
    """What the teammate's computer actually did, allowed actions included."""
    pool = _pool(request)
    uid = _uid(current_user)
    if not await store.get_agent(pool, uid, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT run_id, ts, tool, target, tier, decision, reason, approval_id "
            "FROM agent_action_audit WHERE agent_id=$1 AND user_id=$2 "
            "ORDER BY ts DESC LIMIT $3",
            agent_id, uid, max(1, min(int(limit), 500)),
        )
    return {
        "items": [
            {
                "run_id": r["run_id"],
                "ts": int(r["ts"].timestamp()) if r["ts"] else None,
                "tool": r["tool"],
                "target": r["target"],
                "tier": r["tier"],
                "decision": r["decision"],
                "reason": r["reason"],
                "approval_id": r["approval_id"],
            }
            for r in rows
        ]
    }


@router.post("/{agent_id}/run")
async def agents_run(
    agent_id: str,
    form: RunForm,
    request: Request,
    current_user=Depends(get_current_user_optimized),
):
    """Hand the teammate a goal. Returns as soon as the run is launched."""
    goal = (form.goal or "").strip()
    if not goal:
        raise HTTPException(status_code=400, detail="Give the teammate something to do.")
    uid = _uid(current_user)
    agent = await store.get_agent(_pool(request), uid, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.get("enabled"):
        raise HTTPException(status_code=409, detail="That teammate is turned off.")
    return await intake.create_agent_run(
        request=request,
        user_id=uid,
        agent=agent,
        goal=goal,
        override=form.override,
        session_id=form.session_id,
    )
