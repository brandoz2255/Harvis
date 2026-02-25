"""
OpenAI-compatible model proxy for OpenClaw → Moonshot forwarding.

OpenClaw is configured with a "harvis-proxy" provider whose baseUrl points at
http://harvis-ai-merged-backend:8000/v1  (internal cluster network only).

When the kimi agent sends a chat.send request, OpenClaw calls:
  POST http://harvis-ai-merged-backend:8000/v1/chat/completions
  Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>
  Body: {"model": "kimi-k2.5", "messages": [...], "stream": true}

This proxy:
  1. Verifies the request carries the shared OPENCLAW_GATEWAY_TOKEN (so random pods
     on the cluster can't use it to call Moonshot at our expense).
  2. Forwards the request to https://api.moonshot.cn/v1/chat/completions with the
     real MOONSHOT_API_KEY (which never leaves the backend pod).
  3. Streams the response back verbatim so OpenClaw's tool loop works normally.

Security notes:
  - Only kimi-* model names are forwarded; anything else gets a 400.
  - The Moonshot API key is read from env at startup — not embedded in config.
  - Network isolation: the NetworkPolicy on the OpenClaw pod allows egress to
    the backend on port 8000 but nowhere else, so the key can't be exfiltrated.
"""

import json
import logging
import os

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
# Use MOONSHOT_BASE_URL from env if set; default to moonshot.ai (international endpoint).
# moonshot_api.py uses the same default — keep them in sync.
MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")

# Only route these model prefixes to Moonshot — reject anything else.
_ALLOWED_MODELS = {"kimi-k2.5", "kimi-k2", "kimi-k1.5", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"}

model_proxy_router = APIRouter(prefix="/v1", tags=["model-proxy"])


def _verify_token(authorization: str | None) -> None:
    """Verify the request carries the shared internal token."""
    if not OPENCLAW_GATEWAY_TOKEN:
        # If no token configured, skip verification (dev mode only)
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer "):]
    if token != OPENCLAW_GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid proxy token")


@model_proxy_router.post("/chat/completions")
async def proxy_chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """
    Forward a chat completion request from OpenClaw to the Moonshot API.

    Supports both streaming (stream=true) and non-streaming responses.
    The response is forwarded verbatim so OpenClaw's tool loop is unaffected.
    """
    _verify_token(authorization)

    if not MOONSHOT_API_KEY:
        raise HTTPException(status_code=503, detail="MOONSHOT_API_KEY not configured on backend")

    body = await request.json()
    model_name: str = body.get("model", "")

    # Normalise: strip provider prefix that OpenClaw might include
    if "/" in model_name:
        model_name = model_name.split("/", 1)[1]
        body = {**body, "model": model_name}

    if model_name not in _ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_name}' not routable through this proxy. "
                   f"Allowed: {sorted(_ALLOWED_MODELS)}"
        )

    # Force temperature=1.0 — Moonshot's Kimi models require it
    body = {**body, "temperature": 1.0}

    is_streaming = body.get("stream", False)
    target_url = f"{MOONSHOT_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {MOONSHOT_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info(
        "model_proxy: forwarding model=%s stream=%s to Moonshot",
        model_name, is_streaming,
    )

    if is_streaming:
        return StreamingResponse(
            _stream_from_moonshot(target_url, headers, body),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-streaming: forward and return the JSON response
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            resp = await client.post(target_url, json=body, headers=headers)
            if resp.status_code != 200:
                logger.error("model_proxy: Moonshot error %s: %s", resp.status_code, resp.text[:200])
                raise HTTPException(status_code=502, detail=f"Moonshot API error: {resp.status_code}")
            return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Moonshot API request timed out")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("model_proxy: unexpected error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


async def _stream_from_moonshot(url: str, headers: dict, body: dict):
    """Async generator that forwards the SSE stream from Moonshot to OpenClaw."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    error_msg = error_body.decode(errors="replace")[:200]
                    logger.error("model_proxy: Moonshot streaming error %s: %s", resp.status_code, error_msg)
                    # Yield an SSE error so OpenClaw's parser doesn't hang
                    error_event = json.dumps({
                        "error": {"message": f"Moonshot error {resp.status_code}: {error_msg}", "type": "proxy_error"}
                    })
                    yield f"data: {error_event}\n\n"
                    return

                async for line in resp.aiter_lines():
                    if line:
                        yield f"{line}\n"
                    else:
                        yield "\n"

    except Exception as exc:
        logger.error("model_proxy: stream error: %s", exc)
        error_event = json.dumps({"error": {"message": str(exc), "type": "proxy_error"}})
        yield f"data: {error_event}\n\n"
