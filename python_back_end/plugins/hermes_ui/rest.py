"""REST half of the Hermes UI facade (shapes from front_end/hermes-desktop-ui/src/types/hermes.ts)."""
from __future__ import annotations

import json
import logging
import os
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from . import providers, sessions, settings_store, store
from .models import is_hidden_model, thinking_models

log = logging.getLogger("hermes_ui.rest")

router = APIRouter(prefix="/hermes-api/api", tags=["hermes-ui"])

FACADE_VERSION = "0.21.0-harvis-facade"
PROFILE_NAME = sessions.PROFILE_NAME

_HERE = os.path.dirname(__file__)


def _load_json(name: str) -> dict:
    with open(os.path.join(_HERE, name), encoding="utf-8") as fh:
        return json.load(fh)


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


# The reference config (every key the settings panels know about) with the
# handful of values Harvis pins: the model always resolves through the
# Harvis backend, and there is no desktop repo scanning or local terminal.
CONFIG = _merge(_load_json("config_defaults.json"), {
    "agent": {"reasoning_effort": "medium", "service_tier": "default", "personalities": {}},
    "display": {"personality": "", "skin": "default", "timestamps": True,
                "interim_assistant_messages": False},
    "desktop": {"repo_scan_enabled": False, "repo_scan_roots": [], "repo_scan_exclude_paths": []},
    "terminal": {"cwd": "", "font_family": ""},
    "stt": {"enabled": False},
    "voice": {"max_recording_seconds": 60, "auto_tts": False},
    "model": {"default": "harvis-default", "provider": "harvis"},
})


MODELS_URL = os.getenv("HARVIS_HERMES_UI_MODELS_URL", "http://127.0.0.1:8000/api/models")


def _uid(user) -> int:
    return int(getattr(user, "id", None) or getattr(user, "user_id", None) or user["id"])


def _pool(request: Request):
    return request.app.state.pg_pool


def _token(request: Request) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get("access_token") or ""


async def _harvis_models(token: str) -> list[dict]:
    """Harvis's own model list (same one the main chat picker shows)."""
    headers = {"Authorization": f"Bearer {token}", "Cookie": f"access_token={token}"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(MODELS_URL, headers=headers)
    r.raise_for_status()
    body = r.json()
    rows = body.get("data") if isinstance(body, dict) else body
    return [m for m in (rows or []) if isinstance(m, dict) and m.get("id")
            and not is_hidden_model(str(m["id"]), _provider_of(m))]


def _provider_of(m: dict) -> str:
    return str(m.get("owned_by") or m.get("provider") or "harvis")


@router.get("/status")
async def status(user=Depends(get_current_user_optimized)):
    return {
        "status": "ok",
        "version": FACADE_VERSION,
        "config_version": 1,
        "latest_config_version": 1,
        "profile": PROFILE_NAME,
        "gateway_running": True,
        "backend": "harvis",
        "ts": time.time(),
    }


@router.get("/hermes/update/check")
async def update_check(force: str | None = None, user=Depends(get_current_user_optimized)):
    return {"install_method": "docker", "current_version": FACADE_VERSION,
            "latest_version": FACADE_VERSION, "behind": 0, "update_available": False}


@router.get("/config")
async def config(request: Request, user=Depends(get_current_user_optimized)):
    """The reference config with this user's saved overrides merged on top."""
    return await settings_store.config_for(_pool(request), _uid(user), CONFIG)


@router.get("/config/defaults")
async def config_defaults(user=Depends(get_current_user_optimized)):
    return CONFIG


@router.put("/config")
async def config_put(request: Request, user=Depends(get_current_user_optimized)):
    """Autosave / reset / import all PUT ``{config: <partial or full record>}``;
    the patch deep-merges onto the user's overrides (a full default record
    therefore clears them, which is what Reset expects)."""
    body = await request.json()
    patch = body.get("config") if isinstance(body, dict) else None
    if not isinstance(patch, dict):
        raise HTTPException(400, "expected {config: {...}}")
    await settings_store.apply_config_patch(_pool(request), _uid(user), patch, CONFIG)
    return {"ok": True}


def _archived_filter(request: Request) -> str:
    value = str(request.query_params.get("archived") or "exclude")
    return value if value in ("exclude", "include", "only") else "exclude"


@router.get("/profiles/sessions")
async def profiles_sessions(request: Request, user=Depends(get_current_user_optimized)):
    """Paginated all-profile list; identical to /sessions since sessions are per user."""
    return await list_sessions(request, user)


@router.get("/profiles/sessions/sidebar")
async def sidebar(request: Request, user=Depends(get_current_user_optimized)):
    limit = int(request.query_params.get("recents_limit") or 50)
    rows, total = await sessions.list_for(_pool(request), _uid(user), limit, 0)
    return {
        "recents": {"profile": PROFILE_NAME, "sessions": rows, "total": total, "has_more": total > limit},
        "cron": {"sessions": [], "total": 0},
        "messaging": {"sessions": [], "total": 0},
    }


@router.get("/sessions")
async def list_sessions(request: Request, user=Depends(get_current_user_optimized)):
    limit = int(request.query_params.get("limit") or 50)
    offset = int(request.query_params.get("offset") or 0)
    rows, total = await sessions.list_for(_pool(request), _uid(user), limit, offset, _archived_filter(request))
    return {"sessions": rows, "total": total, "limit": limit, "offset": offset,
            "has_more": offset + limit < total}


@router.patch("/sessions/{sid}")
async def patch_session(sid: str, request: Request, user=Depends(get_current_user_optimized)):
    """Sidebar mutations: {archived} | {pinned} | {title} | {unread} (see api/sessions.ts)."""
    body = await request.json()
    body = body if isinstance(body, dict) else {}
    title = body.get("title")
    if title is not None and not isinstance(title, str):
        raise HTTPException(400, "title must be a string")
    ok = await store.set_flags(
        _pool(request), _uid(user), sid,
        archived=None if body.get("archived") is None else bool(body["archived"]),
        pinned=None if body.get("pinned") is None else bool(body["pinned"]),
        title=title.strip()[:200] if isinstance(title, str) and title.strip() else None)
    if not ok:
        raise HTTPException(404, "session not found")
    out: dict = {"ok": True}
    if isinstance(title, str):
        out["title"] = title.strip()[:200]
    return out  # unread is a desktop-local watermark; accepted, nothing to store


@router.delete("/sessions/{sid}")
async def delete_session(sid: str, request: Request, user=Depends(get_current_user_optimized)):
    deleted = await store.delete_chat(_pool(request), _uid(user), sid)
    live = sessions.live(_uid(user), sid)
    if live is not None and not live.persisted:
        sessions.forget(sid)
        deleted = True
    return {"ok": True, "already_absent": not deleted}


@router.get("/sessions/{sid}")
async def get_session(sid: str, request: Request, user=Depends(get_current_user_optimized)):
    info = await sessions.info_for(_pool(request), _uid(user), sid)
    if not info:
        raise HTTPException(404, "session not found")
    return info


@router.get("/sessions/{sid}/messages")
async def get_session_messages(sid: str, request: Request, user=Depends(get_current_user_optimized)):
    s, msgs = await sessions.open(_pool(request), _uid(user), sid)
    if not s:
        raise HTTPException(404, "session not found")
    return {"messages": msgs, "message_count": len(msgs)}


async def build_model_options(pool, uid: int, token: str) -> dict:
    """Model picker payload (REST /model/options and WS model.options share it)."""
    current = await store.resolve_model(pool, uid)
    if is_hidden_model(current):
        current = ""
    try:
        rows = await _harvis_models(token)
    except Exception as exc:  # noqa: BLE001
        log.warning("hermes_ui: model list unavailable: %s", exc)
        rows = []
    groups: dict[str, list[str]] = {}
    for m in rows:
        groups.setdefault(_provider_of(m), []).append(str(m["id"]))
    custom_endpoints, active_endpoint_id = await providers.list_endpoints(pool, uid)
    custom_names: dict[str, str] = {}
    for endpoint in custom_endpoints:
        endpoint_id = str(endpoint.get("id") or "")
        if not endpoint_id:
            continue
        endpoint_models = [str(model) for model in endpoint.get("models", []) if isinstance(model, str)]
        if endpoint.get("model") and str(endpoint["model"]) not in endpoint_models:
            endpoint_models.insert(0, str(endpoint["model"]))
        if endpoint_models:
            groups[endpoint_id] = endpoint_models
            custom_names[endpoint_id] = str(endpoint.get("name") or endpoint_id)
    # Saved Mixture-of-agents presets are picked like any other model (upstream Hermes does the same).
    from .turn_models import MOA_KEY, MOA_PREFIX, moa_ready
    moa = await settings_store.get_key(pool, uid, MOA_KEY, {})
    presets = moa.get("presets") if isinstance(moa, dict) else None
    moa_ids = [f"{MOA_PREFIX}{name}" for name, preset in (presets or {}).items()
               if isinstance(preset, dict) and moa_ready(preset)]
    if moa_ids:
        groups["moa"] = moa_ids
        custom_names["moa"] = "Mixture of agents"
    cur_provider = (active_endpoint_id if active_endpoint_id in groups else
                    next((p for p, ids in groups.items() if current in ids), "harvis"))
    # Effort is offered only where it does something: local Ollama models that
    # report the `thinking` capability (gpt-oss, qwen3, gemma4). Everything else
    # says reasoning False, or the UI assumes every model takes a level.
    thinking = await thinking_models()
    provider_rows = [{
        "name": slug, "slug": slug, "models": ids, "total_models": len(ids),
        "is_current": slug == cur_provider, "authenticated": True, "auth_type": "harvis",
        "capabilities": {mid: {"reasoning": slug not in custom_names and mid in thinking, "fast": False}
                         for mid in ids},
    } for slug, ids in sorted(groups.items())]
    for row in provider_rows:
        if row["slug"] in custom_names:
            row["name"] = custom_names[row["slug"]]
            row["auth_type"] = "moa" if row["slug"] == "moa" else "custom-endpoint"
    if not current:
        provider_rows.insert(0, {"name": "Harvis default", "slug": "harvis", "models": ["harvis-default"],
                                 "total_models": 1, "is_current": True, "authenticated": True,
                                 "capabilities": {"harvis-default": {"reasoning": False, "fast": False}}})
    return {"model": current or "harvis-default", "provider": cur_provider, "providers": provider_rows}


@router.get("/model/options")
async def model_options(request: Request, user=Depends(get_current_user_optimized)):
    return await build_model_options(_pool(request), _uid(user), _token(request))


@router.get("/model/info")
async def model_info(request: Request, user=Depends(get_current_user_optimized)):
    current = await store.resolve_model(_pool(request), _uid(user))
    return {"model": current or "harvis-default", "provider": "harvis", "capabilities": {}}


async def apply_model_choice(pool, uid: int, provider: str, model: str) -> dict:
    """Make ``model`` (on ``provider``) the user's default; shared by REST
    /model/set and the WS ``config.set model --global`` path."""
    model = model.strip()
    if model == "harvis-default":
        model = ""
    provider = provider or "harvis"
    if provider != "harvis":
        try:
            endpoint = await providers.activate_endpoint(pool, uid, provider, model)
        except providers.EndpointValidationError:
            # A normal Harvis provider name (Ollama, cloud, etc.) is not a
            # custom endpoint, so it must retain the standard backend route.
            await providers.deactivate_endpoint(pool, uid)
        else:
            model = str(endpoint.get("model") or model)
    else:
        await providers.deactivate_endpoint(pool, uid)
    await store.set_default_model(pool, uid, model)
    return {"ok": True, "provider": provider, "model": model or "harvis-default", "scope": "main"}


@router.post("/model/set")
async def model_set(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    model = str(body.get("model") or "").strip()
    provider = str(body.get("provider") or "harvis")
    pool, uid = _pool(request), _uid(user)
    if str(body.get("scope") or "main") == "auxiliary":
        # A helper-task pin must never touch the main model.
        from .rest_settings import set_aux_task
        task = str(body.get("task") or "")
        tasks = await set_aux_task(pool, uid, task, provider, model, str(body.get("base_url") or ""))
        return {"ok": True, "scope": "auxiliary", "task": task, "provider": provider,
                "model": model or "harvis-default", "reset": task == "__reset__", "tasks": tasks}
    return await apply_model_choice(pool, uid, provider, model)


@router.get("/fs/default-cwd")
async def default_cwd(user=Depends(get_current_user_optimized)):
    return {"cwd": "", "path": ""}


# ── Side pages (Capabilities / Messaging / Scheduled jobs) ─────────────────
# Shapes copied from the desktop's api/*.ts return types. Empty lists keep the
# pages rendering their "nothing here yet" state instead of a spinner or a
# shell crash; skills are the one surface already backed by Harvis data.

@router.post("/sessions/owner-backfill")
async def owner_backfill(user=Depends(get_current_user_optimized)):
    return {"ok": True, "updated": 0}


@router.get("/analytics/usage")
async def analytics_usage(request: Request, user=Depends(get_current_user_optimized)):
    days = int(request.query_params.get("days") or 30)
    totals = {"total_actual_cost": 0, "total_api_calls": None, "total_cache_read": None,
              "total_estimated_cost": 0, "total_input": None, "total_output": None,
              "total_reasoning": None, "total_sessions": 0}
    summary = {"distinct_skills_used": 0, "total_skill_actions": 0,
               "total_skill_edits": 0, "total_skill_loads": 0}
    return {"by_model": [], "daily": [], "period_days": days, "tools": [],
            "skills": {"summary": summary, "top_skills": []}, "totals": totals}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def not_implemented(path: str, request: Request):
    # Anything the UI asks for that the facade does not model yet. Logged so the
    # next iteration can stub it properly instead of patching the UI.
    log.warning("hermes_ui: unhandled REST %s /hermes-api/api/%s", request.method, path)
    raise HTTPException(404, f"not available in Harvis yet: /api/{path}")
