"""Per-user, per-model profiles for CLOUD chat models (Claude + OpenAI).

The Cursor-style "Edit" affordance on a cloud model saves a small profile: a default reasoning
EFFORT (the mode shown next to the name), an optional THINKING BUDGET, and a custom DISPLAY NAME.
Local (Ollama) models are intentionally excluded — they have no reasoning-effort control, so they
carry no profile (the picker never offers Edit for them).

The saved effort/budget flow into the chat request at call time (``cloud_chat.proxy_cloud_chat``);
the display name overrides the picker label (``cloud_chat.cloud_chat_model_entries``). Additive and
fail-open: any error → the model simply behaves as if unprofiled.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

_EFFORTS = {"low", "medium", "high", "max"}
_NAME_MAX = 60
_BUDGET_MAX = 200000

CREATE_MODEL_PROFILES_SQL = """
CREATE TABLE IF NOT EXISTS owui_model_profiles (
    user_id         INTEGER NOT NULL,
    model_id        TEXT NOT NULL,
    effort          TEXT,
    thinking_budget INTEGER,
    display_name    TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, model_id)
);
"""

_SCHEMA_READY = False


async def _ensure_schema(pool) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY or pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(CREATE_MODEL_PROFILES_SQL)
        _SCHEMA_READY = True
    except Exception:
        logger.warning("model_profiles: schema ensure failed", exc_info=True)


def _is_cloud_model(mid: str) -> bool:
    """Only cloud models carry a profile — local Ollama tags are excluded by design."""
    mid = (mid or "").strip()
    return mid.startswith("anthropic/") or mid.startswith("openai/")


async def get_model_profiles(pool, user_id: int) -> dict:
    """{model_id: {effort, thinking_budget, display_name}} for a user. Fail-open → {}."""
    if pool is None or not user_id:
        return {}
    await _ensure_schema(pool)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT model_id, effort, thinking_budget, display_name "
                "FROM owui_model_profiles WHERE user_id=$1",
                int(user_id),
            )
    except Exception:
        logger.debug("model_profiles: read failed", exc_info=True)
        return {}
    return {
        r["model_id"]: {
            "effort": r["effort"],
            "thinking_budget": r["thinking_budget"],
            "display_name": r["display_name"],
        }
        for r in rows
    }


def _clean_profile(body: dict) -> dict:
    """Return ONLY the fields PRESENT in the body (validated). Absent keys are omitted so the caller
    can merge them over an existing row (partial update — e.g. the draggable effort bar sends only
    ``effort`` and must not wipe a saved budget/name). A present key with an empty/null value clears
    that field. Raises 400 on bad input."""
    out: dict = {}
    if "effort" in body:
        effort = (str(body.get("effort") or "").strip().lower()) or None
        if effort is not None and effort not in _EFFORTS:
            raise HTTPException(status_code=400, detail=f"effort must be one of {sorted(_EFFORTS)}")
        out["effort"] = effort
    if "thinking_budget" in body:
        tb = body.get("thinking_budget")
        if tb in ("", None):
            tb = None
        else:
            try:
                tb = max(0, min(_BUDGET_MAX, int(tb)))
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="thinking_budget must be an integer")
        out["thinking_budget"] = tb
    if "display_name" in body:
        name = body.get("display_name")
        if name is not None:
            name = (str(name).strip()[:_NAME_MAX]) or None
        out["display_name"] = name
    return out


def register_model_profile_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        return getattr(request.app.state, "pg_pool", None)

    @router.get("/api/owui/model-profiles")
    async def list_model_profiles(request: Request, user=Depends(get_current_user)):
        return {"profiles": await get_model_profiles(_pool(request), int(user.id))}

    @router.put("/api/owui/model-profiles")
    async def upsert_model_profile(request: Request, user=Depends(get_current_user)):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be an object")
        mid = str(body.get("model_id") or "").strip()  # str() → non-string bodies 400, never 500
        if not _is_cloud_model(mid) or len(mid) > 128:
            raise HTTPException(
                status_code=400,
                detail="model_id must be a cloud model id (anthropic/… or openai/…) under 128 chars",
            )
        provided = _clean_profile(body)  # only the fields the caller sent
        pool = _pool(request)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        await _ensure_schema(pool)
        # Merge the provided fields over the existing row (partial update). Then normalize:
        # an all-empty merged profile means "reset to default" → delete the row.
        existing = (await get_model_profiles(pool, int(user.id))).get(mid, {})
        merged = {
            "effort": provided.get("effort", existing.get("effort")),
            "thinking_budget": provided.get("thinking_budget", existing.get("thinking_budget")),
            "display_name": provided.get("display_name", existing.get("display_name")),
        }
        if merged["effort"] is None and merged["thinking_budget"] is None and merged["display_name"] is None:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM owui_model_profiles WHERE user_id=$1 AND model_id=$2",
                    int(user.id), mid,
                )
            return {"model_id": mid, "profile": None}
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO owui_model_profiles "
                "(user_id, model_id, effort, thinking_budget, display_name, updated_at) "
                "VALUES ($1,$2,$3,$4,$5,NOW()) "
                "ON CONFLICT (user_id, model_id) DO UPDATE SET "
                "effort=EXCLUDED.effort, thinking_budget=EXCLUDED.thinking_budget, "
                "display_name=EXCLUDED.display_name, updated_at=NOW()",
                int(user.id), mid, merged["effort"], merged["thinking_budget"], merged["display_name"],
            )
        return {"model_id": mid, "profile": merged}

    @router.delete("/api/owui/model-profiles/{model_id:path}")
    async def delete_model_profile(model_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        await _ensure_schema(pool)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM owui_model_profiles WHERE user_id=$1 AND model_id=$2",
                int(user.id), (model_id or "").strip(),
            )
        return {"model_id": model_id, "profile": None}
