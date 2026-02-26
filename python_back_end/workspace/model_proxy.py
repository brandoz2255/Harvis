"""
OpenAI-compatible model proxy for OpenClaw → cloud LLM forwarding.

OpenClaw is configured with a "harvis-proxy" provider whose baseUrl points at
http://harvis-ai-merged-backend:8000/v1  (internal cluster network only).

This proxy handles TWO routing paths based on the requested model:

  kimi-k2.5  →  https://api.moonshot.ai/v1  (Moonshot API, MOONSHOT_API_KEY)
  gpt-oss:*  →  EXTERNAL_OLLAMA_URL/v1       (Cloud Ollama, EXTERNAL_OLLAMA_API_KEY)

Security:
  1. Verifies the shared OPENCLAW_GATEWAY_TOKEN on every request so only the
     OpenClaw pod can use this proxy.
  2. API keys / upstream URLs never leave the backend pod.
  3. NetworkPolicy on the OpenClaw pod allows egress only to this backend on
     port 8000, so there is no way for OpenClaw to call cloud APIs directly.
"""

import json
import logging
import os

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")

EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")

OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

# Model prefixes routed to Moonshot
_KIMI_MODELS = {"kimi-k2.5", "kimi-k2", "kimi-k1.5", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"}

# Model prefixes routed to the external/cloud Ollama instance
_OLLAMA_CLOUD_PREFIX = "gpt-oss"

model_proxy_router = APIRouter(prefix="/v1", tags=["model-proxy"])


def _verify_token(authorization: str | None) -> None:
    """Verify the request carries the shared internal token."""
    if not OPENCLAW_GATEWAY_TOKEN:
        return  # dev mode — no token configured
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer "):]
    if token != OPENCLAW_GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid proxy token")


def _resolve_route(model_name: str) -> tuple[str, dict, bool]:
    """
    Determine the upstream URL and headers for a given model name.

    Returns (target_url, headers, is_kimi).
    Raises HTTP 400 if the model is not routable.
    """
    # Kimi / Moonshot models
    if model_name in _KIMI_MODELS:
        if not MOONSHOT_API_KEY:
            raise HTTPException(status_code=503, detail="MOONSHOT_API_KEY not configured on backend")
        return (
            f"{MOONSHOT_BASE_URL}/chat/completions",
            {"Authorization": f"Bearer {MOONSHOT_API_KEY}", "Content-Type": "application/json"},
            True,
        )

    # GPT-OSS cloud Ollama models
    if model_name.startswith(_OLLAMA_CLOUD_PREFIX):
        if not EXTERNAL_OLLAMA_URL:
            raise HTTPException(
                status_code=503,
                detail="EXTERNAL_OLLAMA_URL not configured on backend. "
                       "Add it to the harvis-backend-env K8s secret.",
            )
        headers = {"Content-Type": "application/json"}
        if EXTERNAL_OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {EXTERNAL_OLLAMA_API_KEY}"
        return (
            f"{EXTERNAL_OLLAMA_URL.rstrip('/')}/v1/chat/completions",
            headers,
            False,
        )

    raise HTTPException(
        status_code=400,
        detail=f"Model '{model_name}' not routable through this proxy. "
               f"Supported: kimi-k2.5, gpt-oss:*",
    )


@model_proxy_router.post("/chat/completions")
async def proxy_chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """
    Forward a chat completion request from OpenClaw to the appropriate upstream.

    - kimi-k2.5  → Moonshot API
    - gpt-oss:*  → External/cloud Ollama instance (EXTERNAL_OLLAMA_URL)

    Supports both streaming (stream=true) and non-streaming responses.
    """
    _verify_token(authorization)

    body = await request.json()
    model_name: str = body.get("model", "")

    # Strip provider prefix that OpenClaw may include (e.g. "harvis-proxy/gpt-oss:120b")
    if "/" in model_name:
        model_name = model_name.split("/", 1)[1]
        body = {**body, "model": model_name}

    target_url, headers, is_kimi = _resolve_route(model_name)

    # Moonshot requires temperature=1.0; Ollama does not — only apply for Kimi
    if is_kimi:
        body = {**body, "temperature": 1.0}

    is_streaming = body.get("stream", False)

    logger.info(
        "model_proxy: model=%s stream=%s → %s",
        model_name, is_streaming, target_url.split("/v1")[0],
    )

    if is_streaming:
        return StreamingResponse(
            _stream_from_upstream(target_url, headers, body),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-streaming
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            resp = await client.post(target_url, json=body, headers=headers)
            if resp.status_code != 200:
                logger.error("model_proxy: upstream error %s: %s", resp.status_code, resp.text[:200])
                raise HTTPException(status_code=502, detail=f"Upstream API error: {resp.status_code}")
            return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream API request timed out")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("model_proxy: unexpected error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


async def _stream_from_upstream(url: str, headers: dict, body: dict):
    """Async generator that forwards the SSE stream from any upstream to OpenClaw."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    error_msg = error_body.decode(errors="replace")[:200]
                    logger.error("model_proxy: upstream streaming error %s: %s", resp.status_code, error_msg)
                    error_event = json.dumps({
                        "error": {"message": f"Upstream error {resp.status_code}: {error_msg}", "type": "proxy_error"}
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
