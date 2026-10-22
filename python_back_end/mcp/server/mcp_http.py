"""Streamable-HTTP MCP endpoint (POST /mcp) in front of the same tool registry
and the same bearer token and scopes as /mcp/invoke.

Stateless and JSON-only: every POST carries one JSON-RPC message and is answered
with application/json (or 202 for notifications). No session id, no SSE stream.
"""
import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .auth import check_bearer, scope_allowed
from .registry import invoke_tool, registry
from .tool_meta import annotations, describe, failure_reason, unavailable_reason

logger = logging.getLogger("harvis-mcp")

router = APIRouter()

LATEST_PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = (LATEST_PROTOCOL, "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "harvis-mcp", "title": "Harvis MCP", "version": "1.0.0"}
MAX_BODY_BYTES = 8_000_000

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
FORBIDDEN = -32003


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _error_body(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _challenge(exc: HTTPException) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=headers)


def _input_schema(tool) -> dict:
    schema = tool.input_model.model_json_schema()
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def _tool_listing(tool) -> dict:
    return {
        "name": tool.name,
        "description": describe(tool.name, tool.scope),
        "inputSchema": _input_schema(tool),
        "annotations": annotations(tool.name),
    }


def _initialize(params: dict) -> dict:
    asked = params.get("protocolVersion")
    version = asked if asked in SUPPORTED_PROTOCOLS else LATEST_PROTOCOL
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": SERVER_INFO,
        "instructions": "Harvis workspace tools. tools/list shows only the tools this token may call.",
    }


def _tools_list() -> dict:
    return {"tools": [_tool_listing(t) for t in registry.values()
                      if scope_allowed(t.scope) and not unavailable_reason(t.name)]}


async def _tools_call(params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments", {})
    if not isinstance(name, str):
        raise RpcError(INVALID_PARAMS, "tools/call needs a tool name")
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "arguments must be an object")
    tool = registry.get(name)
    if tool is None:
        raise RpcError(INVALID_PARAMS, f"Unknown tool {name}")
    if not scope_allowed(tool.scope):
        raise RpcError(FORBIDDEN, f"Token is not granted {tool.scope} for {name}")
    why_not = unavailable_reason(name)
    if why_not:
        return _tool_result(f"{name} is unavailable: {why_not}", is_error=True)
    try:
        out = await invoke_tool(tool, args)
    except asyncio.TimeoutError:
        return _tool_result(f"{name} timed out after {tool.timeout_s}s", is_error=True)
    except Exception as exc:
        return _tool_result(str(exc) or exc.__class__.__name__, is_error=True)
    payload = out.model_dump(mode="json") if hasattr(out, "model_dump") else out
    return _tool_result(json.dumps(payload, default=str), is_error=failure_reason(payload) is not None)


def _tool_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def _dispatch(method: str, params: dict) -> Optional[dict]:
    if method == "initialize":
        return _initialize(params)
    if method == "ping":
        return {}
    if method == "tools/list":
        return _tools_list()
    if method == "tools/call":
        return await _tools_call(params)
    raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")


@router.post("/mcp")
@router.post("/mcp/", include_in_schema=False)
async def mcp_endpoint(request: Request):
    try:
        check_bearer(request.headers.get("authorization"), bad_token_status=401)
    except HTTPException as exc:
        return _challenge(exc)

    seen = request.headers.get("mcp-protocol-version")
    if seen and seen not in SUPPORTED_PROTOCOLS:
        return JSONResponse(_error_body(None, INVALID_REQUEST, f"Unsupported MCP-Protocol-Version {seen}"),
                            status_code=400)
    declared = request.headers.get("content-length") or ""
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return JSONResponse(_error_body(None, INVALID_REQUEST, "Request too large"), status_code=413)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return JSONResponse(_error_body(None, INVALID_REQUEST, "Request too large"), status_code=413)

    try:
        msg = json.loads(raw)
    except ValueError:
        return JSONResponse(_error_body(None, PARSE_ERROR, "Parse error"), status_code=400)
    if isinstance(msg, list):
        return JSONResponse(_error_body(None, INVALID_REQUEST, "Batch requests are not supported"),
                            status_code=400)
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return JSONResponse(_error_body(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message"), status_code=400)

    method = msg.get("method")
    if method is None:
        # A client's reply to a server request; this server sends none.
        return Response(status_code=202)
    if not isinstance(method, str):
        return JSONResponse(_error_body(None, INVALID_REQUEST, "method must be a string"), status_code=400)
    if "id" not in msg:
        return Response(status_code=202)

    req_id = msg["id"]
    if isinstance(req_id, bool) or not isinstance(req_id, (str, int)):
        return JSONResponse(_error_body(None, INVALID_REQUEST, "id must be a string or integer"),
                            status_code=400)
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return JSONResponse(_error_body(req_id, INVALID_PARAMS, "params must be an object"))
    try:
        result = await _dispatch(method, params)
    except RpcError as exc:
        return JSONResponse(_error_body(req_id, exc.code, exc.message))
    except Exception:
        logger.exception("mcp %s failed", method)
        return JSONResponse(_error_body(req_id, INTERNAL_ERROR, "Internal error"))
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


@router.api_route("/mcp", methods=["GET", "DELETE"], include_in_schema=False)
async def mcp_no_stream(request: Request):
    return Response(status_code=405, headers={"Allow": "POST"})
