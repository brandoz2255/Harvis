"""GET /harvis/providers — every model source the Settings page shows, each with a way to
connect it (or an honest reason it is read-only).

Kinds:
  local        — the Ollama this server was configured with (OLLAMA_URL). No key. The
                 per-user editable copy is a custom endpoint with id ``ollama``.
  user-api-key — a key in ``user_api_keys`` (Kimi/Moonshot). Saved through
                 POST /api/user/api-keys, which verifies it with Moonshot first.

The free hosted tiers (Groq … OmniRoute) come from /harvis/free-providers. The env-only rows
that ``/api/workspace/providers`` reports (nvidia-kimi, cloud-ollama) are deliberately NOT
listed: nothing on this page can change them, and NVIDIA / Ollama Cloud have per-user key
rows of their own.

Nothing here decrypts or returns a key.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Request

from auth_optimized import get_current_user_optimized

from . import providers as endpoints
from .rest import _uid

log = logging.getLogger("hermes_ui.providers")

router = APIRouter(prefix="/hermes-api/api")

LOCAL_ENDPOINT_ID = "local-ollama"
MOONSHOT_CONSOLE = "https://platform.moonshot.ai/console/api-keys"


async def local_ollama() -> dict:
    """Server-side Ollama status. Patched in tests."""
    from workspace.workspace_router import _probe_local_ollama

    return await _probe_local_ollama()


async def user_key_status(pool, uid: int, provider: str) -> dict:
    """Whether a ``user_api_keys`` row exists — read without decrypting the key."""
    if pool is None:
        return {"saved": False, "verified": False, "auth_mode": "api_key", "last_error": None}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT api_url, updated_at FROM user_api_keys "
            "WHERE user_id = $1 AND provider_name = $2 AND is_active = TRUE",
            uid, provider)
    # POST /api/user/api-keys refuses to store a Moonshot key that fails verification,
    # so a saved row is a verified one.
    return {"saved": bool(row), "verified": bool(row), "auth_mode": "api_key", "last_error": None,
            "api_url": (row["api_url"] if row else None)}


def _local_row(probe: dict, endpoint: dict | None) -> dict:
    server_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
    return {
        "id": "local",
        "kind": "local",
        "label": "Local Ollama",
        "status": probe.get("status", "offline"),
        "models": [m for m in probe.get("models", []) if isinstance(m, str)],
        "reason": probe.get("reason"),
        "note": "The Ollama this Harvis server talks to. Change the address below to use a different "
                "one for your chats; the server's own address comes from OLLAMA_URL.",
        "base_url": server_url,
        "console_url": None,
        "auth": None,
        "endpoint": endpoints.public_endpoint(endpoint) if endpoint else None,
        "endpoint_id": LOCAL_ENDPOINT_ID,
    }


def _kimi_row(auth: dict) -> dict:
    saved = bool(auth.get("saved"))
    return {
        "id": "kimi",
        "kind": "user-api-key",
        "provider_name": "moonshot",
        "label": "Kimi (Moonshot cloud)",
        "status": "online" if saved else "no_key",
        "models": ["kimi-k3", "kimi-k2.6", "kimi-k2.5"] if saved else [],
        "reason": None if saved else "No Moonshot API key saved for your account.",
        "note": "Moonshot's hosted Kimi models. Harvis checks the key with Moonshot before saving it.",
        "base_url": os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
        "console_url": MOONSHOT_CONSOLE,
        "auth": {k: auth.get(k) for k in ("saved", "verified", "auth_mode", "last_error")},
        "endpoint": None,
        "endpoint_id": None,
    }


@router.get("/harvis/providers")
async def harvis_providers(request: Request, user=Depends(get_current_user_optimized)):
    pool, uid = request.app.state.pg_pool, _uid(user)
    try:
        probe = await local_ollama()
    except Exception as exc:  # noqa: BLE001
        log.warning("hermes_ui: local Ollama probe failed: %s", type(exc).__name__)
        probe = {"status": "offline", "models": [], "reason": "The Ollama probe failed."}
    endpoint = None
    if pool is not None:
        rows, active_id = await endpoints.list_endpoints(pool, uid)
        endpoint = next((r for r in rows if r.get("id") == LOCAL_ENDPOINT_ID), None)
        if endpoint is not None:
            endpoint = {**endpoint, "_active": active_id == LOCAL_ENDPOINT_ID}
    local = _local_row(probe, endpoint)
    if endpoint is not None:
        local["endpoint"]["is_current"] = bool(endpoint.get("_active"))
    kimi = _kimi_row(await user_key_status(pool, uid, "moonshot"))
    return {"providers": [local, kimi]}
