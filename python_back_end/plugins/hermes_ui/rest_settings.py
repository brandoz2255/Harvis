"""Settings REST routes for the Hermes UI, answered by Harvis.

Shapes mirror the reference dashboard (hermes_cli/web_server.py) so every
page loads through its normal code path. Provider keys are read from the
backend's own environment and never edited or revealed here. Settings panels
Harvis has no counterpart for get empty but correctly typed answers instead
of a 404 toast. The Messaging page lives in messaging.py.
"""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

from . import messaging, providers, settings_store, store
from .rest import _pool, _uid

router = APIRouter(prefix="/hermes-api/api", tags=["hermes-ui"])

_SCHEMA_PATH = Path(__file__).with_name("config_schema.json")
_NOT_EDITABLE = ("Harvis keeps provider keys in the backend .env; "
                 "editing them from this page lands with migration step 3.")


@lru_cache(maxsize=1)
def _config_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _redact(value: str) -> str:
    return messaging.redact(value)


# ── Settings panels ─────────────────────────────────────────────────────────

async def _main_model(request: Request, user) -> dict[str, str]:
    current = await store.get_default_model(_pool(request), _uid(user))
    return {"model": current or "harvis-default", "provider": "harvis"}


@router.get("/config/schema")
async def config_schema(user=Depends(get_current_user_optimized)):
    return _config_schema()


@lru_cache(maxsize=1)
def _env_catalog() -> dict[str, dict[str, Any]]:
    with _SCHEMA_PATH.with_name("env_catalog.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _channel_keys() -> frozenset[str]:
    return messaging.channel_keys()


@router.get("/env")
async def env_vars(user=Depends(get_current_user_optimized)):
    """Which provider/tool keys the backend container has set, values redacted.

    The values themselves never leave the container: editing and reveal are
    refused below, and the Messaging page owns the per-platform credentials."""
    out: dict[str, dict[str, Any]] = {}
    for key, meta in _env_catalog().items():
        value = os.getenv(key) or ""
        out[key] = {
            "advanced": bool(meta.get("advanced")),
            "category": meta.get("category") or "setting",
            "channel_managed": key in _channel_keys(),
            "description": meta.get("description") or "",
            "is_password": bool(meta.get("password")),
            "is_set": bool(value),
            "redacted_value": _redact(value) if value else None,
            "tools": list(meta.get("tools") or []),
            "url": meta.get("url"),
        }
    return out


@router.put("/env")
@router.delete("/env")
async def env_var_edit(user=Depends(get_current_user_optimized)):
    raise HTTPException(501, _NOT_EDITABLE)


@router.post("/env/reveal")
async def env_var_reveal(user=Depends(get_current_user_optimized)):
    raise HTTPException(501, "Harvis never reveals backend secrets to the browser.")


@router.get("/providers/custom-endpoints")
async def custom_endpoints(request: Request, user=Depends(get_current_user_optimized)):
    return await providers.custom_endpoints_payload(
        _pool(request), _uid(user), await _main_model(request, user))


def _endpoint_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _models_url(base_url: str) -> str:
    """Accept the usual OpenAI ``.../v1`` URL and the provider root too."""
    return f"{base_url}/models" if base_url.rstrip("/").endswith("/v1") else f"{base_url}/v1/models"


async def _probe_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        endpoint = providers.normalize_endpoint(payload, require_model=False)
    except providers.EndpointValidationError as exc:
        raise _endpoint_error(exc) from exc
    api_key = payload.get("api_key")
    api_key = api_key.strip() if isinstance(api_key, str) else ""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(_models_url(endpoint["base_url"]), headers=headers)
    except httpx.RequestError:
        return {"ok": False, "reachable": False, "models": [], "message": "Could not reach this endpoint."}
    if response.status_code in (401, 403):
        return {"ok": False, "reachable": True, "models": [], "message": "Authentication failed — check the API key."}
    if response.status_code >= 400:
        return {"ok": False, "reachable": True, "models": [],
                "message": f"Endpoint returned HTTP {response.status_code}."}
    try:
        data = response.json().get("data", [])
        models = [str(row.get("id")) for row in data if isinstance(row, dict) and row.get("id")][:100]
    except (ValueError, AttributeError):
        models = []
    return {"ok": True, "reachable": True, "models": models, "message": "Endpoint is reachable."}


@router.post("/providers/custom-endpoints/validate")
async def validate_custom_endpoint(request: Request, user=Depends(get_current_user_optimized)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload = body if isinstance(body, dict) else {}
    # Editing an endpoint deliberately leaves the password field blank.  Reuse
    # its encrypted saved key for the probe without ever returning it to JS.
    if not payload.get("api_key") and isinstance(payload.get("id"), str):
        saved = await providers.resolve_endpoint(_pool(request), _uid(user), payload["id"])
        if saved and saved.get("api_key"):
            payload = {**payload, "api_key": saved["api_key"]}
    return await _probe_endpoint(payload)


@router.post("/providers/custom-endpoints")
async def save_custom_endpoint(request: Request, user=Depends(get_current_user_optimized)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        endpoint = await providers.save_endpoint(_pool(request), _uid(user), body if isinstance(body, dict) else {})
    except providers.EndpointValidationError as exc:
        raise _endpoint_error(exc) from exc
    payload = await providers.custom_endpoints_payload(_pool(request), _uid(user), await _main_model(request, user))
    return {"ok": True, "id": endpoint["id"], **payload}


@router.post("/providers/custom-endpoints/{endpoint_id}/activate")
async def activate_custom_endpoint(endpoint_id: str, request: Request, user=Depends(get_current_user_optimized)):
    try:
        endpoint = await providers.activate_endpoint(_pool(request), _uid(user), endpoint_id)
    except providers.EndpointValidationError as exc:
        raise _endpoint_error(exc) from exc
    return {"ok": True, "provider": endpoint["id"], "model": endpoint["model"]}


@router.delete("/providers/custom-endpoints/{endpoint_id}")
async def delete_custom_endpoint(endpoint_id: str, request: Request, user=Depends(get_current_user_optimized)):
    try:
        await providers.delete_endpoint(_pool(request), _uid(user), endpoint_id)
    except providers.EndpointValidationError as exc:
        raise _endpoint_error(exc) from exc
    return await providers.custom_endpoints_payload(_pool(request), _uid(user), await _main_model(request, user))


@router.get("/providers/oauth")
async def oauth_providers(user=Depends(get_current_user_optimized)):
    return {"providers": []}


@router.get("/model/recommended-default")
async def recommended_default(request: Request, user=Depends(get_current_user_optimized)):
    return {**await _main_model(request, user), "free_tier": None}


AUX_KEY = "auxiliary_models"
MOA_KEY = "moa"
AUX_TASKS = ("vision", "compression", "skills_hub", "approval", "mcp", "title_generation", "review", "curator")


async def aux_tasks(pool, uid: int) -> list[dict[str, str]]:
    """AuxiliaryTaskAssignment rows: only tasks the user pinned to a model."""
    saved = await settings_store.get_key(pool, uid, AUX_KEY, {})
    saved = saved if isinstance(saved, dict) else {}
    return [{"task": task, "provider": str(row.get("provider") or "harvis"), "model": str(row.get("model") or ""),
             "base_url": str(row.get("base_url") or "")}
            for task, row in saved.items() if isinstance(row, dict) and row.get("model")]


async def set_aux_task(pool, uid: int, task: str, provider: str, model: str, base_url: str = "") -> list[str]:
    """Pin (or with ``__reset__`` / an empty model, unpin) an auxiliary task."""
    saved = await settings_store.get_key(pool, uid, AUX_KEY, {})
    saved = saved if isinstance(saved, dict) else {}
    if task == "__reset__":
        saved = {}
    elif task not in AUX_TASKS:
        raise HTTPException(400, f"unknown auxiliary task: {task}")
    elif not model or model == "harvis-default":
        saved.pop(task, None)
    else:
        saved[task] = {"provider": provider or "harvis", "model": model, "base_url": base_url}
    await settings_store.set_key(pool, uid, AUX_KEY, saved)
    return sorted(saved)


@router.get("/model/auxiliary")
async def auxiliary_models(request: Request, user=Depends(get_current_user_optimized)):
    return {"main": await _main_model(request, user), "tasks": await aux_tasks(_pool(request), _uid(user))}


def _moa_defaults() -> dict[str, Any]:
    slot = {"provider": "harvis", "model": "", "enabled": False}
    preset = {"aggregator": slot, "aggregator_temperature": 0.7,
              "degraded_reference_policy": "loud", "enabled": False,
              "max_tokens": 4096, "reference_models": [],
              "reference_temperature": 0.7, "reference_timeout": None}
    return {"default_preset": "default", "active_preset": "default",
            "presets": {"default": preset}, **preset}


@router.get("/model/moa")
async def moa_models(request: Request, user=Depends(get_current_user_optimized)):
    saved = await settings_store.get_key(_pool(request), _uid(user), MOA_KEY)
    return saved if isinstance(saved, dict) and saved.get("presets") else _moa_defaults()


@router.put("/model/moa")
async def moa_models_save(request: Request, user=Depends(get_current_user_optimized)):
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("presets"), dict):
        raise HTTPException(400, "expected a MoA config with presets")
    saved = {**_moa_defaults(), **body}
    await settings_store.set_key(_pool(request), _uid(user), MOA_KEY, saved)
    return {**saved, "ok": True}


@router.get("/memory")
async def memory_status(user=Depends(get_current_user_optimized)):
    return {"active": "harvis",
            "providers": [{"name": "harvis", "configured": True,
                           "description": "Harvis memory: postgres + vector store"}],
            "builtin_files": {"memory": 0, "user": 0}}


@router.get("/curator")
async def curator_status(user=Depends(get_current_user_optimized)):
    return {"enabled": False, "paused": False, "interval_hours": None,
            "last_run_at": None, "min_idle_hours": None,
            "stale_after_days": None, "archive_after_days": None}


@router.get("/tools/terminal/backends")
async def terminal_backends(user=Depends(get_current_user_optimized)):
    return {"active": "harvis",
            "backends": [{"name": "harvis", "label": "Harvis workspace",
                          "description": "Commands run inside the Harvis workspace sandbox.",
                          "active": True, "status": "ready", "detail": ""}]}


@router.get("/tools/computer-use/status")
async def computer_use_status(user=Depends(get_current_user_optimized)):
    return {"platform": sys.platform, "platform_supported": False, "installed": False,
            "version": None, "ready": False, "can_grant": False, "checks": [],
            "accessibility": None, "screen_recording": None,
            "screen_recording_capturable": None, "source": None}


@router.get("/git/gh-auth")
async def gh_auth(user=Depends(get_current_user_optimized)):
    return {"available": False, "authenticated": False}


@router.get("/sessions/search")
async def sessions_search(user=Depends(get_current_user_optimized)):
    return {"results": []}


@router.get("/learning/graph")
async def learning_graph(user=Depends(get_current_user_optimized)):
    return {"nodes": [], "edges": [], "clusters": [], "memory": [], "stats": {}}
