"""Persist OWUI user settings (UI prefs, default model, etc.).

Replaces the old stub that merged + returned the body but never stored it — so
prefs (incl. the chat's default model) reset on reload. Now upserted to
owui_user_settings(user_id, settings JSONB).
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from fastapi import APIRouter, Depends, Request

logger = logging.getLogger(__name__)

DEFAULT_USER_SETTINGS: dict = {"ui": {}, "version": 0}

CREATE_OWUI_USER_SETTINGS_SQL = """
CREATE TABLE IF NOT EXISTS owui_user_settings (
    user_id     INTEGER PRIMARY KEY,
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _as_dict(v) -> dict:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def register_user_settings_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        return getattr(request.app.state, "pg_pool", None)

    @router.get("/api/v1/users/user/settings")
    async def owui_user_settings(request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        if pool is None:
            return DEFAULT_USER_SETTINGS
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT settings FROM owui_user_settings WHERE user_id=$1", int(user.id)
                )
        except Exception:
            logger.warning("owui_compat: user-settings read failed", exc_info=True)
            return DEFAULT_USER_SETTINGS
        if not row:
            return DEFAULT_USER_SETTINGS
        s = _as_dict(row["settings"])
        s.setdefault("ui", {})
        return s or DEFAULT_USER_SETTINGS

    @router.post("/api/v1/users/user/settings/update")
    async def owui_user_settings_update(request: Request, user=Depends(get_current_user)):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        merged = {**DEFAULT_USER_SETTINGS, **body}
        merged.setdefault("ui", {})
        pool = _pool(request)
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO owui_user_settings (user_id, settings, updated_at) "
                        "VALUES ($1, $2::jsonb, NOW()) "
                        "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                        int(user.id), json.dumps(merged),
                    )
            except Exception:
                logger.warning("owui_compat: user-settings persist failed", exc_info=True)
        return merged
