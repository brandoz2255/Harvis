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

import asyncio
import json
import logging
import os

import asyncpg
import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

EXTERNAL_OLLAMA_URL = os.getenv("EXTERNAL_OLLAMA_URL", "")
EXTERNAL_OLLAMA_API_KEY = os.getenv("EXTERNAL_OLLAMA_API_KEY", "")

OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Pricing constants (USD per million tokens)
_KIMI_COST_IN_PER_M   = 0.14
_KIMI_COST_OUT_PER_M  = 0.14
_NVIDIA_COST_IN_PER_M = 0.14
_NVIDIA_COST_OUT_PER_M = 0.14
_OLLAMA_COST_PER_M    = 0.0   # self-hosted, no marginal cost


async def _log_usage(model: str, tokens_in: int, tokens_out: int, cost: float) -> None:
    """Write a usage record to proxy_usage_log. Failures are logged but never propagated."""
    if not DATABASE_URL:
        return
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "INSERT INTO proxy_usage_log(model, tokens_in, tokens_out, cost_usd) VALUES($1,$2,$3,$4)",
            model, tokens_in, tokens_out, cost,
        )
        await conn.close()
        logger.info("usage: model=%s in=%d out=%d cost=$%.6f", model, tokens_in, tokens_out, cost)
    except Exception as e:
        logger.warning("usage log failed: %s", e)

# Model prefixes routed to Moonshot
_KIMI_MODELS = {"kimi-k2.5", "kimi-k2", "kimi-k1.5", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"}

# Models routed to NVIDIA NIM (moonshotai/kimi-k2.5 hosted on NVIDIA infrastructure)
_NVIDIA_MODELS = {"nvidia-kimi"}

# Model prefixes routed to the external/cloud Ollama instance
_OLLAMA_CLOUD_PREFIXES = ("gpt-oss", "qwen3")

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


def _resolve_route(model_name: str) -> tuple[str, dict, bool, bool, str | None]:
    """
    Determine the upstream URL and headers for a given model name.

    Returns (target_url, headers, is_kimi, is_nvidia, upstream_model_override).
    - is_kimi: True for Moonshot-hosted Kimi (forces temperature=1.0)
    - is_nvidia: True for NVIDIA NIM Kimi (injects chat_template_kwargs thinking=true)
    - upstream_model_override: if set, replace model name in the forwarded body
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
            False,
            None,
        )

    # NVIDIA NIM — Kimi K2.5 hosted on NVIDIA infrastructure
    if model_name in _NVIDIA_MODELS:
        if not NVIDIA_API_KEY:
            raise HTTPException(status_code=503, detail="NVIDIA_API_KEY not configured on backend")
        return (
            f"{NVIDIA_BASE_URL}/chat/completions",
            {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            False,
            True,
            "moonshotai/kimi-k2.5",  # NVIDIA NIM expects the full model path
        )

    # Cloud Ollama models (gpt-oss, qwen3, etc.)
    if model_name.startswith(_OLLAMA_CLOUD_PREFIXES):
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
            False,
            None,
        )

    raise HTTPException(
        status_code=400,
        detail=f"Model '{model_name}' not routable through this proxy. "
               f"Supported: kimi-k2.5, nvidia-kimi, gpt-oss:*, qwen3:*",
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

    target_url, headers, is_kimi, is_nvidia, upstream_model = _resolve_route(model_name)

    # Apply upstream model name override (e.g. nvidia-kimi → moonshotai/kimi-k2.5)
    if upstream_model:
        body = {**body, "model": upstream_model}

    # Moonshot + NVIDIA Kimi both require temperature=1.0
    if is_kimi or is_nvidia:
        body = {**body, "temperature": 1.0}

    # NVIDIA NIM Kimi: only inject thinking param if caller requested it.
    # Sending {"thinking": False} (or True without care) can cause NVIDIA NIM to error.
    # OpenClaw requests don't send thinking_mode, so default = off (omit entirely).
    if is_nvidia:
        caller_thinking = body.pop("thinking_mode", False)
        if caller_thinking:
            body = {**body, "chat_template_kwargs": {"thinking": True}}

    is_streaming = body.get("stream", False)

    # NVIDIA NIM requires Accept: text/event-stream for streaming requests
    if is_nvidia and is_streaming:
        headers = {**headers, "Accept": "text/event-stream"}

    logger.info(
        "model_proxy: model=%s stream=%s → %s",
        model_name, is_streaming, target_url.split("/v1")[0],
    )

    if is_streaming:
        # Ask Kimi/NVIDIA to include usage in the final SSE chunk
        if is_kimi or is_nvidia:
            body = {**body, "stream_options": {"include_usage": True}}
        return StreamingResponse(
            _stream_from_upstream(target_url, headers, body, model_name=model_name, is_kimi=is_kimi or is_nvidia, is_nvidia=is_nvidia),
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
            data = resp.json()
            usage = data.get("usage", {})
            if usage:
                ti = usage.get("prompt_tokens", 0)
                to_ = usage.get("completion_tokens", 0)
                if is_nvidia:
                    rate_in, rate_out = _NVIDIA_COST_IN_PER_M, _NVIDIA_COST_OUT_PER_M
                elif is_kimi:
                    rate_in, rate_out = _KIMI_COST_IN_PER_M, _KIMI_COST_OUT_PER_M
                else:
                    rate_in, rate_out = _OLLAMA_COST_PER_M, _OLLAMA_COST_PER_M
                cost = (ti * rate_in + to_ * rate_out) / 1_000_000
                asyncio.create_task(_log_usage(model_name, ti, to_, cost))
            return data
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream API request timed out")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("model_proxy: unexpected error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


async def _stream_from_upstream(
    url: str,
    headers: dict,
    body: dict,
    model_name: str = "",
    is_kimi: bool = False,
    is_nvidia: bool = False,
):
    """Async generator that forwards the SSE stream from any upstream to OpenClaw.

    For NVIDIA NIM with thinking enabled, the model emits two delta fields:
      - reasoning_content: chain-of-thought (empty content during this phase)
      - content: final answer

    OpenClaw's OpenAI SDK only reads delta.content, so we remap reasoning_content
    → content in forwarded chunks so the Discord bot sees thinking output too.
    """
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
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])

                            # Log usage when available
                            usage = chunk.get("usage") or {}
                            if usage.get("prompt_tokens"):
                                ti = usage["prompt_tokens"]
                                to_ = usage.get("completion_tokens", 0)
                                rate_in  = _KIMI_COST_IN_PER_M  if is_kimi else _OLLAMA_COST_PER_M
                                rate_out = _KIMI_COST_OUT_PER_M if is_kimi else _OLLAMA_COST_PER_M
                                cost = (ti * rate_in + to_ * rate_out) / 1_000_000
                                asyncio.create_task(_log_usage(model_name, ti, to_, cost))

                            # NVIDIA NIM: remap reasoning_content → content so OpenClaw
                            # (OpenAI SDK) sees text during the thinking phase instead of
                            # empty deltas that look like a stalled stream.
                            if is_nvidia:
                                choices = chunk.get("choices", [])
                                modified = False
                                for choice in choices:
                                    delta = choice.get("delta", {})
                                    reasoning = delta.get("reasoning_content") or ""
                                    content = delta.get("content") or ""
                                    if reasoning and not content:
                                        delta["content"] = reasoning
                                        delta.pop("reasoning_content", None)
                                        modified = True
                                if modified:
                                    line = f"data: {json.dumps(chunk)}"

                        except Exception:
                            pass

                    if line:
                        yield f"{line}\n"
                    else:
                        yield "\n"

    except Exception as exc:
        logger.error("model_proxy: stream error: %s", exc)
        error_event = json.dumps({"error": {"message": str(exc), "type": "proxy_error"}})
        yield f"data: {error_event}\n\n"
