"""Per-user custom orchestration MODEL POOL (Agent Studio → Customize, opt-in).

By default a multi-agent (orchestrate) run puts every sub-agent on the SESSION's
model. A user can instead define a pool of models here and flip it ACTIVE; then the
planner re-models its task-delegated agents across this pool (round-robin) on every
orchestrate run. Inactive (default) → uniform session model.

Dedicated table (NOT folded into owui_user_settings, whose whole blob is replaced by
OWUI's settings-sync — which would clobber this).
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from fastapi import APIRouter, Depends, Request

logger = logging.getLogger(__name__)

CREATE_OWUI_ORCH_POOL_SQL = """
CREATE TABLE IF NOT EXISTS owui_orchestration_pool (
    user_id     INTEGER PRIMARY KEY,
    active      BOOLEAN NOT NULL DEFAULT FALSE,
    models      JSONB   NOT NULL DEFAULT '[]'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_MAX_MODELS = 10  # cap the pool — matches the 1–10 agent scale


def _models_list(v) -> list[str]:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return []
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for m in v:
        if isinstance(m, str) and m.strip():
            out.append(m.strip())
    return out[:_MAX_MODELS]


async def get_orchestration_pool(pool, user_id: int) -> dict:
    """{active: bool, models: list[str]} for a user. Empty/inactive ⇒ the caller
    falls back to its own model policy (the uniform session model)."""
    if pool is None:
        return {"active": False, "models": []}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT active, models FROM owui_orchestration_pool WHERE user_id=$1",
                int(user_id),
            )
    except Exception:
        logger.warning("orchestration pool read failed for user %s", user_id, exc_info=True)
        return {"active": False, "models": []}
    if not row:
        return {"active": False, "models": []}
    return {"active": bool(row["active"]), "models": _models_list(row["models"])}


def register_orchestration_pool_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        return getattr(request.app.state, "pg_pool", None)

    @router.get("/api/owui/orchestration/pool")
    async def read_orchestration_pool(request: Request, user=Depends(get_current_user)):
        return await get_orchestration_pool(_pool(request), int(user.id))

    @router.put("/api/owui/orchestration/pool")
    async def write_orchestration_pool(request: Request, user=Depends(get_current_user)):
        try:
            body = await request.json()
        except Exception:
            body = {}
        active = bool(body.get("active")) if isinstance(body, dict) else False
        models = _models_list(body.get("models") if isinstance(body, dict) else [])
        pool = _pool(request)
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO owui_orchestration_pool (user_id, active, models, updated_at) "
                        "VALUES ($1, $2, $3::jsonb, NOW()) "
                        "ON CONFLICT (user_id) DO UPDATE SET "
                        "active=EXCLUDED.active, models=EXCLUDED.models, updated_at=NOW()",
                        int(user.id), active, json.dumps(models),
                    )
            except Exception:
                logger.warning("orchestration pool persist failed for user %s", user.id, exc_info=True)
        return {"active": active, "models": models}
