"""Persist OWUI user settings (UI prefs, default model, etc.).

Replaces the old stub that merged + returned the body but never stored it — so
prefs (incl. the chat's default model) reset on reload. Now upserted to
owui_user_settings(user_id, settings JSONB).

Phase 4 additions — the ``settings.harvis`` subtree (Customize surface):
- ``harvis.modelRouting`` — EXPLICIT task-type → model map (chat / build /
  research / notebook / orchestrated). Empty string = session default. This is
  pure user configuration: there is deliberately NO keyword/content-based
  automatic routing anywhere (locked project decision).
- ``harvis.presets`` — named agent presets {id, name, model, engine, runMode,
  persona}; ``harvis.activePresetId`` marks the applied one.
Served via dedicated RMW endpoints (``/api/owui/harvis/settings``) that mutate
ONLY the harvis subtree (FOR UPDATE, sibling keys preserved — same pattern as
capabilities.py). The full-blob OWUI settings-sync endpoint below now also
PRESERVES server-managed subtrees (harvis, integrations) when the client body
omits them, so a frontend settings save can't clobber them.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)

DEFAULT_USER_SETTINGS: dict = {"ui": {}, "version": 0}

# Subtrees written by dedicated server endpoints; the full-blob settings-sync
# must not drop them when the OWUI client posts a body without them.
_SERVER_MANAGED_KEYS = ("harvis", "integrations")

# ── settings.harvis subtree ────────────────────────────────────────────────
HARVIS_TASK_KEYS = ("chat", "build", "research", "notebook", "orchestrated")
_ENGINES = {"", "native", "opencode", "codex", "claude-code", "hermes-agent", "hermes-native"}
_RUN_MODES = {"auto", "plan"}
_MAX_PRESETS = 24
_MAX_PERSONA_CHARS = 8000


def _default_harvis() -> dict:
    return {
        "modelRouting": {k: "" for k in HARVIS_TASK_KEYS},
        "presets": [],
        "activePresetId": None,
    }


def _sanitize_routing(v) -> dict:
    routing = {k: "" for k in HARVIS_TASK_KEYS}
    if isinstance(v, dict):
        for k in HARVIS_TASK_KEYS:
            val = v.get(k)
            if isinstance(val, str):
                routing[k] = val.strip()[:256]
    return routing


def _sanitize_presets(v) -> list:
    out: list[dict] = []
    if not isinstance(v, list):
        return out
    for p in v[:_MAX_PRESETS]:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()[:80]
        if not name:
            continue
        engine = str(p.get("engine") or "").strip()
        run_mode = str(p.get("runMode") or "auto").strip().lower()
        out.append(
            {
                "id": str(p.get("id") or uuid.uuid4())[:64],
                "name": name,
                "model": str(p.get("model") or "").strip()[:256],
                "engine": engine if engine in _ENGINES else "",
                "runMode": run_mode if run_mode in _RUN_MODES else "auto",
                "persona": str(p.get("persona") or "")[:_MAX_PERSONA_CHARS],
            }
        )
    return out


def _harvis_view(settings: dict) -> dict:
    harvis = settings.get("harvis") if isinstance(settings, dict) else None
    if not isinstance(harvis, dict):
        harvis = {}
    view = _default_harvis()
    view["modelRouting"] = _sanitize_routing(harvis.get("modelRouting"))
    view["presets"] = _sanitize_presets(harvis.get("presets"))
    active = harvis.get("activePresetId")
    if isinstance(active, str) and any(p["id"] == active for p in view["presets"]):
        view["activePresetId"] = active
    return view

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
                    async with conn.transaction():
                        row = await conn.fetchrow(
                            "SELECT settings FROM owui_user_settings WHERE user_id=$1 FOR UPDATE",
                            int(user.id),
                        )
                        existing = _as_dict(row["settings"]) if row else {}
                        # Full-blob sync must not drop server-managed subtrees the
                        # OWUI client doesn't know about (harvis, integrations).
                        for k in _SERVER_MANAGED_KEYS:
                            if k not in body and k in existing:
                                merged[k] = existing[k]
                        await conn.execute(
                            "INSERT INTO owui_user_settings (user_id, settings, updated_at) "
                            "VALUES ($1, $2::jsonb, NOW()) "
                            "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                            int(user.id), json.dumps(merged),
                        )
            except Exception:
                logger.warning("owui_compat: user-settings persist failed", exc_info=True)
        return merged

    # ── settings.harvis subtree (Customize: model routing + agent presets) ──
    @router.get("/api/owui/harvis/settings")
    async def harvis_settings_get(request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        if pool is None:
            return _default_harvis()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT settings FROM owui_user_settings WHERE user_id=$1", int(user.id)
                )
        except Exception:
            logger.warning("owui_compat: harvis-settings read failed", exc_info=True)
            return _default_harvis()
        return _harvis_view(_as_dict(row["settings"]) if row else {})

    @router.put("/api/owui/harvis/settings")
    async def harvis_settings_put(request: Request, user=Depends(get_current_user)):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        pool = _pool(request)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        # RMW that mutates ONLY the keys the client sent, ONLY inside
        # settings.harvis — every sibling settings key is preserved.
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT settings FROM owui_user_settings WHERE user_id=$1 FOR UPDATE",
                    int(user.id),
                )
                settings = _as_dict(row["settings"]) if row else {}
                harvis = settings.get("harvis")
                if not isinstance(harvis, dict):
                    harvis = _default_harvis()
                if "modelRouting" in body:
                    harvis["modelRouting"] = _sanitize_routing(body.get("modelRouting"))
                if "presets" in body:
                    harvis["presets"] = _sanitize_presets(body.get("presets"))
                if "activePresetId" in body:
                    active = body.get("activePresetId")
                    harvis["activePresetId"] = (
                        str(active)[:64] if isinstance(active, str) and active else None
                    )
                settings["harvis"] = harvis
                settings.setdefault("ui", {})
                await conn.execute(
                    "INSERT INTO owui_user_settings (user_id, settings, updated_at) "
                    "VALUES ($1, $2::jsonb, NOW()) "
                    "ON CONFLICT (user_id) DO UPDATE SET settings=EXCLUDED.settings, updated_at=NOW()",
                    int(user.id), json.dumps(settings),
                )
        return _harvis_view(settings)
