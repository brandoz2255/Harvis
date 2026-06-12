"""
Cookbook client — thin async proxy to a node's `llmfit serve` REST API and its
Ollama. No business logic: llmfit owns hardware-scan + fit-scoring + model DB;
Ollama owns the actual model pull.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import httpx

from . import config

logger = logging.getLogger(__name__)


async def health(llmfit_url: str) -> Dict[str, Any]:
    """GET {llmfit}/health → {alive, latency_ms, error?}. Never raises."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=config.HEALTH_TIMEOUT) as cli:
            r = await cli.get(f"{llmfit_url}/health")
        return {"alive": r.status_code == 200, "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001 — a health probe must never propagate
        return {"alive": False, "latency_ms": None, "error": str(e)[:200]}


async def get_json(llmfit_url: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Proxy a GET to the node's llmfit and return parsed JSON. Raises HTTP 502 on failure."""
    from fastapi import HTTPException

    clean = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        async with httpx.AsyncClient(timeout=config.PROXY_TIMEOUT) as cli:
            r = await cli.get(f"{llmfit_url}{path}", params=clean)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"llmfit unreachable at {llmfit_url}: {e}")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"llmfit {path} -> {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"llmfit {path} returned non-JSON")


async def ollama_pull_stream(ollama_url: str, model: str):
    """Stream Ollama /api/pull NDJSON progress, re-emitted as SSE 'data:' lines."""
    payload = {"name": model, "stream": True}
    timeout = httpx.Timeout(config.PULL_TIMEOUT, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as cli:
            async with cli.stream("POST", f"{ollama_url}/api/pull", json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")[:300]
                    yield f"data: {json.dumps({'error': f'ollama pull {resp.status_code}: {body}'})}\n\n"
                    return
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if line:
                        # llmfit/Ollama NDJSON object passes straight through as one SSE event
                        yield f"data: {line}\n\n"
    except httpx.RequestError as e:
        yield f"data: {json.dumps({'error': f'ollama unreachable at {ollama_url}: {e}'})}\n\n"
        return
    yield f"data: {json.dumps({'status': 'done', 'final': True})}\n\n"
