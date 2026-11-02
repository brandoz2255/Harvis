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

from plugins.hermes_ui.providers import EndpointValidationError, guarded_client

logger = logging.getLogger(__name__)

# The single model id the facade exposes for Hermes-Agent chat. Distinct from the Build
# engine id (also "hermes-agent") — different surface (chat vs the engine-adapter), but the
# same underlying app, so sharing the name is intentional and user-legible.
HERMES_CHAT_MODEL_ID = "hermes-agent"
# The user's OPTIONAL linked OpenClaw (owui_compat/openclaw_connect.py). Only offered while
# that link is verified; it shares this module's passthrough and is never anyone's default.
OPENCLAW_CHAT_MODEL_ID = "openclaw-external"


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
    """True for the agent-passthrough models: Hermes, and the user's linked OpenClaw. Both skip
    the native router and the tool-gathering rounds; `proxy_hermes_chat` picks the target."""
    return (model_id or "").strip() in (HERMES_CHAT_MODEL_ID, OPENCLAW_CHAT_MODEL_ID)


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
            from .ollama_hosts import drop_cloud

            return [m.get("name") for m in drop_cloud((r.json() or {}).get("models") or []) if m.get("name")]
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


async def hermes_chat_model_entry(pool=None, user_id=None) -> dict | None:
    """OWUI model dict for the picker. Shown when the flag is on AND a Hermes is actually
    reachable — either this user's VERIFIED external Hermes (BYO "Connect an external Hermes")
    or the bundled local sidecar. Fail-closed: if neither is reachable, the model is hidden so
    the picker never lists a dead engine. A connected external satisfies the gate on its own,
    so the local sidecar can be removed without hiding Hermes from BYO users."""
    if not _flag_on():
        return None
    reachable = False
    try:
        from .hermes_connect import is_external_active
        if pool is not None and user_id is not None and await is_external_active(pool, user_id):
            reachable = True
    except Exception:
        pass
    if not reachable and not await _sidecar_up():
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


async def openclaw_chat_model_entry(pool=None, user_id=None) -> dict | None:
    """OWUI model dict for this user's linked OpenClaw, or None. Appears only while the link is
    VERIFIED, so a user who never linked one never sees it and it can never be a default."""
    try:
        from .openclaw_connect import is_openclaw_linked

        if pool is None or user_id is None or not await is_openclaw_linked(pool, user_id):
            return None
    except Exception:
        return None
    return {
        "id": OPENCLAW_CHAT_MODEL_ID,
        "name": "OpenClaw (your gateway)",
        "object": "model",
        "owned_by": "openclaw",
        "info": {
            "meta": {
                "description": (
                    "The OpenClaw gateway you linked in Settings, via its OpenAI-compatible API. "
                    "Optional and legacy; Hermes Agent is the recommended agent."
                ),
                "capabilities": {},
            }
        },
    }


def _failure(message: str, stream: bool, status: int):
    if not stream:
        return JSONResponse(status_code=status, content={"error": {"message": message}})

    async def _one():
        yield f"data: {json.dumps({'error': {'message': message}})}\n\n".encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(_one(), media_type="text/event-stream")


async def proxy_hermes_chat(owui_body: dict, pool=None, user_id=None):
    """Forward an OpenAI-shaped chat body to the Hermes API server (stream or non-stream).

    Returns a FastAPI response (StreamingResponse for SSE, JSONResponse otherwise). A clean
    OpenAI body is sent; the model is the RESOLVED Hermes Agent model (per-user pref → env →
    recommended → first-installed), regardless of the model id the caller picked — the user's
    normal chat model never drives the Hermes runtime.

    Connection mode (Bring your Hermes into Harvis): a VERIFIED external Hermes Agent → route
    there with the user's token; otherwise the LOCAL sidecar (managed or imported profile).

    The `openclaw-external` model goes to the user's linked OpenClaw instead (see
    `_proxy_openclaw_chat`); it never falls back to Hermes or anything local."""
    if (owui_body.get("model") or "").strip() == OPENCLAW_CHAT_MODEL_ID:
        return await _proxy_openclaw_chat(owui_body, pool, user_id)
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
    base_url, api_key, guarded = _base_url(), _api_key(), False
    try:
        from .hermes_connect import resolve_external_target
        ext = await resolve_external_target(pool, user_id)
        if ext:
            base_url, api_key, guarded = ext["base_url"], (ext.get("token") or ""), bool(ext.get("guarded"))
    except EndpointValidationError as exc:
        return _failure(str(exc), stream, 400)
    except Exception:
        pass
    return await _forward(base_url, api_key, guarded, body, "Hermes Agent")


async def _proxy_openclaw_chat(owui_body: dict, pool, user_id):
    """Chat through the user's linked OpenClaw gateway (OpenAI-compatible /v1/chat/completions)."""
    stream = bool(owui_body.get("stream"))
    try:
        from .openclaw_connect import resolve_openclaw_target

        target = await resolve_openclaw_target(pool, user_id)
    except EndpointValidationError as exc:
        return _failure(str(exc), stream, 400)
    except Exception:
        target = None
    if not target:
        return _failure("No OpenClaw is linked. Link and verify yours in Settings, or use Hermes.", stream, 400)
    body = {"model": "openclaw", "messages": owui_body.get("messages") or [], "stream": stream}
    if owui_body.get("temperature") is not None:
        body["temperature"] = owui_body["temperature"]
    return await _forward(target["base_url"], target.get("token") or "", bool(target.get("guarded")), body, "OpenClaw")


async def _forward(base_url: str, api_key: str, guarded: bool, body: dict, label: str):
    """POST `body` to `{base_url}/v1/chat/completions` and relay it (SSE passthrough when streaming).
    `guarded` dials through the connect-time SSRF guard. `label` names the agent in user-facing errors."""
    stream = bool(body.get("stream"))
    url = f"{base_url}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def _client(timeout):
        if guarded:
            return guarded_client(timeout=timeout)
        return httpx.AsyncClient(timeout=timeout)

    if not stream:
        try:
            async with _client(180.0) as client:
                r = await client.post(url, headers=headers, json=body)
            return JSONResponse(status_code=r.status_code, content=r.json())
        except EndpointValidationError as exc:
            return _failure(str(exc), stream, 400)
        except Exception as exc:
            logger.warning("hermes_chat: non-stream proxy to %s failed: %s", label, exc)
            return JSONResponse(
                status_code=502,
                content={"error": {"message": f"{label} chat is unavailable right now."}},
            )

    async def _gen():
        try:
            async with _client(None) as client:
                async with client.stream("POST", url, headers=headers, json=body) as r:
                    if r.status_code >= 400:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        err = {"error": {"message": f"{label} chat error: {detail}"}}
                        yield f"data: {json.dumps(err)}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                        return
                    async for chunk in r.aiter_raw():
                        if chunk:
                            yield chunk
        except EndpointValidationError as exc:
            err = {"error": {"message": str(exc)}}
            yield f"data: {json.dumps(err)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        except Exception as exc:
            logger.warning("hermes_chat: stream proxy to %s failed: %s", label, exc)
            err = {"error": {"message": f"{label} chat stream dropped."}}
            yield f"data: {json.dumps(err)}\n\n".encode()
            yield b"data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")
