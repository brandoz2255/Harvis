"""The document tools as an authenticated MCP server: ``POST /api/docs/mcp``.

Claude Code and Kimi Code sidecars speak MCP and nothing else, so this is how they reach
the same harvis-doc parsers, exporters and page renderer a chat turn uses. It is the same
tool set as every other lane: ``docs_tools.mcp_tools()`` and ``docs_tools.dispatch`` are
shared, so there is one implementation.

Identity comes from the request. The user id is read off the JWT by the dependency every
other Harvis route uses and placed in the ``DocsToolContext`` server-side; a tool argument
can never name a user, a path or a storage key.

Like :mod:`cad_mcp` this is stateless HTTP JSON-RPC: one POST carries one request and gets
one response. ``docs_preview`` answers with real MCP ``image`` content blocks so a
vision-capable model sees its own pages; the text block and ``structuredContent`` carry the
page text without the image bytes.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from . import docs_tools

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "harvis-docs", "version": "0.1"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

MAX_BODY_BYTES = 2 * docs_tools.MAX_SOURCE_BYTES + 100_000   # JSON escaping can double a source at the limit

SIDECAR_MCP_URL = os.getenv("HARVIS_DOCS_MCP_URL", "http://backend:8000/api/docs/mcp")
SIDECAR_TOKEN_MINUTES = 90

# Appended to a sidecar's system prompt when this server is offered. ``{server}`` is the
# MCP server name, which the CLI uses to prefix every tool (``mcp__harvis-docs__docs_guide``).
SIDECAR_NOTE = (
    "Documents: to make a deck, doc or sheet file, write one harvis-doc (call "
    "`mcp__{server}__docs_guide` for the format), then `docs_validate`, `docs_check` and "
    "`docs_export` from the same server. Give the user the `download_url` it returns."
)


def sidecar_mcp_config(user_id: int | None) -> dict | None:
    """The ``--mcp-config`` payload that gives a sidecar the document tools, or ``None``
    for an anonymous caller. Same signer and lifetime as the CAD door."""
    if not user_id:
        return None
    from main import create_access_token   # late: main imports this package

    token = create_access_token({"sub": str(int(user_id))}, timedelta(minutes=SIDECAR_TOKEN_MINUTES))
    return {"mcpServers": {SERVER_INFO["name"]: {
        "type": "http", "url": SIDECAR_MCP_URL, "headers": {"Authorization": f"Bearer {token}"}}}}


def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_result(payload: dict, ok: bool) -> dict:
    content = [{"type": "text", "text": docs_tools.as_text(payload, ok)}, *docs_tools.image_blocks(payload)]
    return {"content": content, "structuredContent": docs_tools.without_images(payload), "isError": not ok}


async def _handle(message: dict, ctx: docs_tools.DocsToolContext) -> dict | None:
    """One JSON-RPC message in, one response out; ``None`` for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, INVALID_REQUEST, "expected a JSON-RPC 2.0 request")
    req_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(req_id, INVALID_PARAMS, "params must be an object")
    is_notification = "id" not in message

    if method == "initialize":
        return None if is_notification else _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    if method and method.startswith("notifications/"):
        return None
    if method == "ping":
        return None if is_notification else _result(req_id, {})
    if method == "tools/list":
        return None if is_notification else _result(req_id, {"tools": docs_tools.mcp_tools()})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(name, str):
            return _error(req_id, INVALID_PARAMS, "tools/call needs a tool name")
        if not isinstance(args, dict):
            return _error(req_id, INVALID_PARAMS, "arguments must be an object")
        payload, ok = await docs_tools.dispatch(name, args, ctx)
        # A refused call is a result the model can read and fix, not a transport error.
        return None if is_notification else _result(req_id, _tool_result(payload, ok))
    if is_notification:
        return None
    return _error(req_id, METHOD_NOT_FOUND, f"unknown method: {method}")


def register_docs_mcp_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.post("/api/docs/mcp")
    async def docs_mcp(request: Request, user=Depends(get_current_user)):
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse(_error(None, INVALID_REQUEST, "the request body is too large"), status_code=413)
        try:
            message = json.loads(raw or b"{}")
        except ValueError:
            return JSONResponse(_error(None, PARSE_ERROR, "invalid JSON"), status_code=400)

        user_id = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
        ctx = docs_tools.DocsToolContext(
            pool=getattr(request.app.state, "pg_pool", None),
            user_id=int(user_id) if user_id else None,
            source="mcp",
        )
        try:
            response = await _handle(message, ctx)
        except Exception:
            logger.exception("docs mcp request failed")
            rid = message.get("id") if isinstance(message, dict) else None
            return JSONResponse(_error(rid, INTERNAL_ERROR, "the request failed"), status_code=500)
        if response is None:
            return JSONResponse(None, status_code=202)
        return JSONResponse(response)

    @router.get("/api/docs/mcp")
    async def docs_mcp_manifest(user=Depends(get_current_user)):
        """What this endpoint is, for a human wiring up a sidecar. Not part of MCP."""
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": SERVER_INFO,
            "transport": "http-jsonrpc",
            "tools": list(docs_tools.TOOL_NAMES),
            "auth": "Bearer token — the same Harvis JWT the rest of /api uses",
        }
