"""The notebook tools as an authenticated MCP server: ``POST /api/notebook-tools/mcp``.

Same shape as ``owui_compat/docs_mcp.py``: stateless HTTP JSON-RPC, one POST in and one
response out, identity from the Harvis JWT the dependency passed in. The tools are in
``tools/notebooks.py``; this file only speaks the protocol and builds the per-request
:class:`NotebookToolContext`.

Mount it with ``register_notebook_mcp_routes(router, get_current_user)`` next to
``register_docs_mcp_routes``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from notebooks.manager import NotebookManager

from .tools import notebooks as nb_tools

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "harvis-notebooks", "version": "0.1"}
ROUTE = "/api/notebook-tools/mcp"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

MAX_BODY_BYTES = 64 * 1024


def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_result(payload: Any, ok: bool) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}],
            "structuredContent": payload if isinstance(payload, dict) else {"result": payload},
            "isError": not ok}


async def handle(message: Any, ctx: nb_tools.NotebookToolContext) -> Optional[dict]:
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
    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    if method == "ping":
        return None if is_notification else _result(req_id, {})
    if method == "tools/list":
        return None if is_notification else _result(req_id, {"tools": nb_tools.mcp_tools()})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(name, str):
            return _error(req_id, INVALID_PARAMS, "tools/call needs a tool name")
        if not isinstance(args, dict):
            return _error(req_id, INVALID_PARAMS, "arguments must be an object")
        payload, ok = await nb_tools.dispatch(name, args, ctx)
        # A refused call is a result the model can read and fix, not a transport error.
        return None if is_notification else _result(req_id, _tool_result(payload, ok))
    if is_notification:
        return None
    return _error(req_id, METHOD_NOT_FOUND, f"unknown method: {method}")


def _manager_of(request: Request) -> Optional[NotebookManager]:
    manager = getattr(request.app.state, "notebook_manager", None)
    if manager is None:
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is not None:
            manager = NotebookManager(pool)
            request.app.state.notebook_manager = manager
    return manager


def register_notebook_mcp_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.post(ROUTE)
    async def notebook_mcp(request: Request, user=Depends(get_current_user)):
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse(_error(None, INVALID_REQUEST, "the request body is too large"), status_code=413)
        try:
            message = json.loads(raw or b"{}")
        except ValueError:
            return JSONResponse(_error(None, PARSE_ERROR, "invalid JSON"), status_code=400)

        user_id = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
        manager = _manager_of(request)
        if not user_id or manager is None:
            raise HTTPException(status_code=503 if user_id else 401, detail="Notebooks are not available.")
        user_id = int(user_id)
        pool = manager.db_pool

        from plugins.people.controls import allowed_for, require_turn

        async def pick_model() -> str:
            try:
                return await require_turn(pool, user_id, "")
            except HTTPException as exc:
                raise nb_tools.ToolError(str(exc.detail))

        ctx = nb_tools.NotebookToolContext(
            manager=manager, user_id=user_id,
            allowed_models=await allowed_for(pool, user_id), pick_model=pick_model)
        try:
            response = await handle(message, ctx)
        except Exception:
            logger.exception("notebook mcp request failed")
            rid = message.get("id") if isinstance(message, dict) else None
            return JSONResponse(_error(rid, INTERNAL_ERROR, "the request failed"), status_code=500)
        if response is None:
            return JSONResponse(None, status_code=202)
        return JSONResponse(response)

    @router.get(ROUTE)
    async def notebook_mcp_manifest(user=Depends(get_current_user)):
        """What this endpoint is, for a human wiring up an agent. Not part of MCP."""
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": SERVER_INFO,
            "transport": "http-jsonrpc",
            "tools": list(nb_tools.TOOL_NAMES),
            "auth": "Bearer token, the same Harvis JWT the rest of /api uses",
        }
