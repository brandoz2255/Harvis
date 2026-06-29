"""Phase E4B — Hermes Agent as a CHAT model (OpenAI-compatible passthrough).

The harvis-hermes-agent sidecar runs the real Hermes Agent app's OpenAI-compatible
API server on :8642 (``API_SERVER_ENABLED=true``). This module surfaces that server as
a single selectable chat model (``hermes-agent``) in the OWUI facade, WITHOUT touching
Harvis's native model-routing brain (``model_proxy.execute_chat_completion``):

  * ``hermes_chat_model_entry()`` returns the OWUI model dict — only when the engine flag
    is on AND the sidecar is up — so the model appears in the picker exactly when usable.
  * ``run_chat_completion`` intercepts a request whose model == ``hermes-agent`` and calls
    ``proxy_hermes_chat`` here, which forwards the OpenAI body straight to :8642/v1 (stream
    or non-stream) with the API-server key. Nothing enters the native router.

This is the "Chat" half of the E4B "Build + Chat" decision. Talking to this model = a real
conversation with the Hermes Agent runtime (its own system prompt, tools, memory), so a
turn runs the agent loop and is heavier/slower than a plain Ollama completion — that's the
genuine Hermes experience, not a thin LLM call. No cloud credentials (local Ollama under
the hood); the only secret is the sidecar's own API-server key, never logged.
"""

from __future__ import annotations

import json
import logging
import os

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

# The single model id the facade exposes for Hermes-Agent chat. Distinct from the Build
# engine id (also "hermes-agent") — different surface (chat vs the engine-adapter), but the
# same underlying app, so sharing the name is intentional and user-legible.
HERMES_CHAT_MODEL_ID = "hermes-agent"


def _flag_on() -> bool:
    return (os.getenv("HARVIS_OWUI_HERMES_AGENT_ENGINE") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _base_url() -> str:
    # The sidecar's OpenAI-compatible API server (internal network, no host port).
    return os.getenv("HARVIS_HERMES_AGENT_CHAT_URL", "http://harvis-hermes-agent:8642").rstrip("/")


def _api_key() -> str:
    # Must match the sidecar's API_SERVER_KEY (compose default harvis-hermes-local-dev).
    return os.getenv("HARVIS_HERMES_API_SERVER_KEY", "harvis-hermes-local-dev")


def is_hermes_chat_model(model_id: str | None) -> bool:
    return (model_id or "").strip() == HERMES_CHAT_MODEL_ID


# ── Hermes Agent model resolution (the LLM the agent runtime runs on) ──────────────────────
# This is the model INSIDE the Hermes Agent runtime — NOT the user's normal chat model. qwen3:4b
# is only the tested default for the 8GB dev GPU; it is NOT "the Hermes model". Priority:
#   1. per-user preference  2. HARVIS_HERMES_AGENT_DEFAULT_MODEL  3. a tool-capable recommended
#   model that's installed  4. first installed model.
_HERMES_RECOMMENDED = ["qwen3:8b", "qwen3:4b", "qwen2.5-coder:7b", "llama3.1:8b", "qwen3:14b"]


async def _installed_ollama_models() -> list[str]:
    url = (os.getenv("OLLAMA_URL", "http://ollama:11434")).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{url}/api/tags")
            return [m.get("name") for m in ((r.json() or {}).get("models") or []) if m.get("name")]
    except Exception:
        return []


async def _hermes_model_pref(pool, user_id) -> str | None:
    """Read settings.integrations.preferences.hermes_agent_model (per-user). Fail-soft None."""
    if not pool or not user_id:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT settings FROM owui_user_settings WHERE user_id=$1", int(user_id))
        if not row or not row["settings"]:
            return None
        s = row["settings"]
        if isinstance(s, str):
            s = json.loads(s)
        val = ((s.get("integrations") or {}).get("preferences") or {}).get("hermes_agent_model")
        return (val or "").strip() or None
    except Exception:
        return None


async def resolve_hermes_model(pool=None, user_id=None) -> str:
    """The Ollama model the Hermes Agent runtime runs on, per the priority above."""
    env = (os.getenv("HARVIS_HERMES_AGENT_DEFAULT_MODEL") or "qwen3:4b").strip()
    pref = await _hermes_model_pref(pool, user_id)
    installed = await _installed_ollama_models()
    # 1. per-user pref (use it if installed, or if we can't enumerate)
    if pref and (not installed or pref in installed):
        return pref
    # 2. env default
    if env and (not installed or env in installed):
        return env
    # 3. a recommended tool-capable model that's installed
    for rec in _HERMES_RECOMMENDED:
        if rec in installed:
            return rec
    # 4. first installed, else the env tag
    return installed[0] if installed else env


async def _sidecar_up() -> bool:
    """Cheap liveness probe so the model only lists when actually reachable (fail-closed)."""
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r = await client.get(f"{_base_url()}/health")
            return r.status_code < 500
    except Exception:
        return False


async def hermes_chat_model_entry() -> dict | None:
    """OWUI model dict for the picker — only when flag on AND sidecar reachable, else None."""
    if not _flag_on():
        return None
    if not await _sidecar_up():
        return None
    return {
        "id": HERMES_CHAT_MODEL_ID,
        "name": "Hermes Agent",
        "object": "model",
        "owned_by": "hermes-agent",
        "info": {
            "meta": {
                "description": (
                    "The real NousResearch Hermes Agent app (its own tools + memory), "
                    "served via its OpenAI-compatible API. Heavier than a plain model — "
                    "each turn runs the agent loop on local models."
                ),
                "capabilities": {},
            }
        },
    }


async def proxy_hermes_chat(owui_body: dict, pool=None, user_id=None):
    """Forward an OpenAI-shaped chat body to the Hermes API server (stream or non-stream).

    Returns a FastAPI response (StreamingResponse for SSE, JSONResponse otherwise). A clean
    OpenAI body is sent; the model is the RESOLVED Hermes Agent model (per-user pref → env →
    recommended → first-installed), regardless of the model id the caller picked — the user's
    normal chat model never drives the Hermes runtime.

    Connection mode (Bring your Hermes into Harvis): a VERIFIED external Hermes Agent → route
    there with the user's token; otherwise the LOCAL sidecar (managed or imported profile)."""
    resolved = await resolve_hermes_model(pool, user_id)
    body = {
        "model": resolved,  # external servers may override with their own configured model
        "messages": owui_body.get("messages") or [],
        "stream": bool(owui_body.get("stream")),
    }
    if owui_body.get("temperature") is not None:
        body["temperature"] = owui_body["temperature"]
    stream = bool(body.get("stream"))
    # Resolve the target: external Hermes (user-owned) wins over the local sidecar.
    base_url, api_key = _base_url(), _api_key()
    try:
        from .hermes_connect import resolve_external_target
        ext = await resolve_external_target(pool, user_id)
        if ext:
            base_url, api_key = ext["base_url"], (ext.get("token") or "")
    except Exception:
        pass
    url = f"{base_url}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if not stream:
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(url, headers=headers, json=body)
            return JSONResponse(status_code=r.status_code, content=r.json())
        except Exception as exc:
            logger.warning("hermes_chat: non-stream proxy failed: %s", exc)
            return JSONResponse(
                status_code=502,
                content={"error": {"message": "Hermes Agent chat is unavailable right now."}},
            )

    async def _gen():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", url, headers=headers, json=body) as r:
                    if r.status_code >= 400:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        err = {"error": {"message": f"Hermes Agent chat error: {detail}"}}
                        yield f"data: {json.dumps(err)}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                        return
                    async for chunk in r.aiter_raw():
                        if chunk:
                            yield chunk
        except Exception as exc:
            logger.warning("hermes_chat: stream proxy failed: %s", exc)
            err = {"error": {"message": "Hermes Agent chat stream dropped."}}
            yield f"data: {json.dumps(err)}\n\n".encode()
            yield b"data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")
