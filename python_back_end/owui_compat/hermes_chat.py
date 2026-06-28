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


async def proxy_hermes_chat(owui_body: dict):
    """Forward an OpenAI-shaped chat body to the Hermes API server (stream or non-stream).

    Returns a FastAPI response (StreamingResponse for SSE, JSONResponse otherwise). The
    request is sent verbatim except the model is normalized to a concrete Ollama tag the
    Hermes app understands when the caller passed the sentinel id."""
    body = dict(owui_body)
    # The sidecar's configured default model handles the actual inference; if the caller
    # sent our sentinel id as the model, drop to the sidecar default by sending its tag.
    if is_hermes_chat_model(body.get("model")):
        body["model"] = os.getenv("HARVIS_HERMES_AGENT_DEFAULT_MODEL", "qwen3:4b")
    stream = bool(body.get("stream"))
    url = f"{_base_url()}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}

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
