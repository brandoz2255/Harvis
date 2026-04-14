"""
MemPalace HTTP+SSE MCP Server
==============================
Wraps the MemPalace stdio MCP server as an HTTP+SSE service so that
OpenCode, OpenClaw, Harvis chatbot, and Claude Code can all share one
persistent memory palace over the network.

Endpoints:
  GET  /sse           — SSE transport (opencode / claude mcp)
  POST /message       — paired with /sse
  POST /              — Streamable HTTP transport
  POST /mcp           — direct JSON-RPC (for curl testing)
  GET  /health        — liveness check
"""

import os
import sys
import json
import uuid
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mempalace-http")

# ── MemPalace bootstrap ───────────────────────────────────────────────────────
# MEMPALACE_PALACE_PATH must be set before importing so MempalaceConfig picks it
# up at module level.  We default to /data/palace (Docker volume mount).
palace_path = os.environ.get("MEMPALACE_PALACE_PATH", "/data/palace")
os.environ.setdefault("MEMPALACE_PALACE_PATH", palace_path)
os.makedirs(palace_path, exist_ok=True)
logger.info(f"Palace path: {palace_path}")

# Deferred import so the env var is set first
from mempalace.mcp_server import handle_request  # noqa: E402

logger.info("MemPalace MCP handler loaded")

# ── SSE connection registry ───────────────────────────────────────────────────
_sse_queues: Dict[str, asyncio.Queue] = {}


# ── FastAPI lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MemPalace HTTP+SSE MCP Server starting")
    yield
    logger.info("MemPalace HTTP+SSE MCP Server stopped")


app = FastAPI(
    title="MemPalace MCP Server",
    description="Shared AI memory for Harvis chatbot, OpenCode, OpenClaw, and Claude Code",
    version="1.0.0",
    lifespan=lifespan,
)


# ── helpers ───────────────────────────────────────────────────────────────────

class RpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[str | int] = None
    method: str
    params: Optional[dict] = None


async def _dispatch(req: RpcRequest) -> dict:
    """Route a JSON-RPC request to the MemPalace handler (sync, run in thread)."""
    payload = {
        "jsonrpc": req.jsonrpc,
        "id": req.id,
        "method": req.method,
        "params": req.params or {},
    }
    logger.info(f"→ {req.method} (id={req.id})")
    result = await asyncio.to_thread(handle_request, payload)
    return result


# ── Streamable HTTP transport (POST /) ────────────────────────────────────────

@app.post("/")
async def streamable_http(request: Request) -> Response:
    try:
        body = await request.json()
        req = RpcRequest(**body)
    except Exception as e:
        return Response(status_code=400, content=str(e))

    if req.id is None or (req.method or "").startswith("notifications/"):
        return Response(status_code=202)

    response = await _dispatch(req)

    if "text/event-stream" in request.headers.get("Accept", ""):
        async def _stream() -> AsyncGenerator[str, None]:
            yield f"event: message\ndata: {json.dumps(response)}\n\n"
        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    return JSONResponse(content=response)


# ── SSE transport (GET /sse + POST /message) ──────────────────────────────────

@app.get("/sse")
async def sse_endpoint(request: Request) -> StreamingResponse:
    connection_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues[connection_id] = queue
    logger.info(f"SSE connection opened: {connection_id}")

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            yield f"event: endpoint\ndata: /message?connectionId={connection_id}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: message\ndata: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as e:
            logger.error(f"SSE error [{connection_id}]: {e}")
            raise
        finally:
            _sse_queues.pop(connection_id, None)
            logger.info(f"SSE connection closed: {connection_id}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/message")
@app.post("/sse/message")
async def message_handler(request: Request) -> Response:
    connection_id = request.query_params.get("connectionId")
    try:
        body = await request.json()
        req = RpcRequest(**body)
    except Exception as e:
        return Response(status_code=400, content=str(e))

    is_notification = req.id is None or (req.method or "").startswith("notifications/")
    if is_notification:
        return Response(status_code=202)

    response = await _dispatch(req)

    queue = _sse_queues.get(connection_id) if connection_id else None
    if queue is not None:
        await queue.put(response)
        return Response(status_code=202)

    logger.warning(f"No SSE queue for connectionId={connection_id}, returning inline")
    return JSONResponse(content=response)


# ── Direct MCP endpoint (POST /mcp) ───────────────────────────────────────────

@app.post("/mcp")
async def mcp_direct(req: RpcRequest) -> Dict[str, Any]:
    """Direct JSON-RPC — response in HTTP body (useful for curl testing)."""
    return await _dispatch(req)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "palace_path": palace_path,
        "service": "mempalace-mcp",
        "version": "1.0.0",
    }
