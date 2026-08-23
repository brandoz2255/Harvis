"""One MCP server that re-exposes a user's own connectors to a sidecar engine.

A Harvis run reaches its tools two different ways, and until now only one of
them could see what the user had connected. The native agent loop asks
:mod:`tool_bridge` for OpenAI-shaped tool entries. A sidecar engine — the
Claude Code CLI, Kimi Code — never enters that loop at all: it only sees the
MCP servers named in the single ``--mcp-config`` Harvis hands it at launch, and
that config listed exactly two Harvis-authored servers. So a model on the
subscription lane would say it had no Higgsfield tool, and it was right.

This module closes that by speaking MCP *outward* over the same JSON-RPC-over-
HTTP shape :mod:`owui_compat.cad_mcp` established, while speaking MCP *inward*
through the existing runtime. The sidecar sees one server, ``harvis``; behind
it sit every connector that user has enabled, whatever transport each uses.

**Why a bridge rather than handing the sidecar the vendor URL directly.** The
alternative was to write each remote server's endpoint and bearer token into
the CLI's ``--mcp-config`` argument. That puts a vendor OAuth token in the
container's argv where any process can read it off ``ps``, it cannot express a
stdio connector at all (those run as sandbox siblings, not URLs), and it would
need the launch path to become async so tokens could be refreshed. Here the
only credential that leaves the backend is a short-lived Harvis JWT for the
user who launched the run — exactly what the CAD door already ships — and
every vendor token stays where it was sealed.

**Naming.** Tool names are built here rather than borrowed from
``tool_bridge.wire_name`` because the budget is different: a client prefixes
what it receives with ``mcp__<server>__``, so a name that already carried
``mcp__`` would arrive doubled and blow the 64-character limit the Anthropic
API enforces. Ours are ``<server>__<tool>``, and the map back to the real tool
is built in the same request that listed it, so a truncated or sanitised name
is never guessed at.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import timedelta
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .runtime import any_transport_enabled, mcp_runtime
from .protocol import McpError
from .server_registry import McpServerRegistry
from .types import McpServerConfig

logger = logging.getLogger(__name__)

SERVER_NAME = "harvis"
SERVER_INFO = {"name": SERVER_NAME, "version": "0.1"}
PROTOCOL_VERSION = "2024-11-05"

SIDECAR_MCP_URL = os.getenv(
    "HARVIS_CONNECTOR_MCP_URL", "http://backend:8000/api/connectors/mcp")
# Long enough to outlive a slow run, short enough that a leaked argv is not a
# standing key. Matches the CAD door rather than inventing a second lifetime.
SIDECAR_TOKEN_MINUTES = 90

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

MAX_BODY_BYTES = 256 * 1024

# `mcp__harvis__` costs 13 of the 64 characters a tool name may use, so the
# name we publish may be at most 51. Splitting that as 12/2/34 leaves room for
# a two-digit disambiguating suffix on the rare collision.
_NAME_SAFE = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_SERVER = 12
_MAX_TOOL = 34


# Names the run a sidecar's connector calls belong to, so media a connector
# produces can be attached to it. Absent → the bridge still works, the image
# just keeps the connector's own (browser-unreachable) URL.
RUN_HEADER = "X-Harvis-Run"


def bridge_tool_name(server_name: str, tool_name: str) -> str:
    server = _NAME_SAFE.sub("_", server_name or "")[:_MAX_SERVER]
    tool = _NAME_SAFE.sub("_", tool_name or "")[:_MAX_TOOL]
    return f"{server}__{tool}"


async def _tool_map(pool, user_id: int) -> dict[str, tuple[McpServerConfig, str, dict]]:
    """``published name -> (server config, real tool name, tool definition)``.

    Built fresh per request from live sessions, which is what makes dispatch
    exact: the name we answer a call on is the same string this function
    published, never a re-derivation that has to guess where truncation fell.

    Never raises. A connector that is down contributes nothing and logs, on the
    same reasoning as :func:`tool_bridge.mcp_tool_specs` — one broken connector
    must not take away the ones that work.
    """
    out: dict[str, tuple[McpServerConfig, str, dict]] = {}
    if not any_transport_enabled() or not user_id:
        return out

    registry = McpServerRegistry(pool)
    mcp_runtime.bind_pool(pool)
    try:
        configs = await registry.list_for_user(int(user_id), include_disabled=False)
    except Exception:
        logger.exception("mcp bridge: could not list servers for user %s", user_id)
        return out

    for cfg in configs:
        try:
            tools = await mcp_runtime.list_tools(cfg)
        except McpError as exc:
            logger.warning("mcp bridge: %s unavailable — %s", cfg.server_name, exc)
            continue
        except Exception:
            logger.exception("mcp bridge: %s failed to connect", cfg.server_name)
            continue

        for tool in tools:
            real = str(tool.get("name") or "")
            if not real:
                continue
            name = bridge_tool_name(cfg.server_name, real)
            if name in out:
                # Two tools that truncate to the same string. Suffix rather than
                # drop: a shadowed tool the model can see but not call is worse
                # than an ugly name.
                for n in range(2, 100):
                    candidate = f"{name[:len(name) - 2]}{n:02d}"
                    if candidate not in out:
                        name = candidate
                        break
                else:
                    continue
            out[name] = (cfg, real, tool)
    return out


def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def error_response(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text_result(text: str, ok: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": not ok}


async def _mirror_content(content: list, pool, workspace_id: str) -> list:
    """Rewrite unreachable image URLs inside MCP content blocks. Never raises."""
    try:
        from .media_capture import mirror_media_urls
    except Exception:
        return content
    out = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                text, _saved = await mirror_media_urls(
                    str(block.get("text") or ""), pool=pool, workspace_id=workspace_id,
                )
                out.append({**block, "text": text})
                continue
            except Exception:
                logger.exception("mcp bridge: media mirroring failed")
        out.append(block)
    return out


async def handle_jsonrpc(
    message: dict, *, pool, user_id: Optional[int], workspace_id: str = "",
) -> dict | None:
    """One JSON-RPC message in, one response out — ``None`` for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return error_response(None, INVALID_REQUEST, "expected a JSON-RPC 2.0 request")

    req_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return error_response(req_id, INVALID_PARAMS, "params must be an object")

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
        if is_notification:
            return None
        mapping = await _tool_map(pool, int(user_id or 0))
        tools = []
        for name, (cfg, real, definition) in sorted(mapping.items()):
            description = str(definition.get("description") or "").strip() or real
            tools.append({
                "name": name,
                # The owning connector is named in the description because the
                # prefix is truncated and a model reading `higgsfiel__…` should
                # still know whose tool it is calling.
                "description": f"[{cfg.server_name}] {description}"[:1024],
                "inputSchema": definition.get("inputSchema")
                or {"type": "object", "properties": {}},
            })
        return _result(req_id, {"tools": tools})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(name, str):
            return error_response(req_id, INVALID_PARAMS, "tools/call needs a tool name")
        if not isinstance(args, dict):
            return error_response(req_id, INVALID_PARAMS, "arguments must be an object")

        mapping = await _tool_map(pool, int(user_id or 0))
        entry = mapping.get(name)
        if entry is None:
            # A result, not a JSON-RPC error: the model can read this and pick a
            # real tool, whereas a transport error is not something it can act on.
            return None if is_notification else _result(req_id, _text_result(
                f"no connected connector provides '{name}'", False))

        cfg, real, _definition = entry
        try:
            result = await mcp_runtime.call_tool(cfg, real, args)
        except McpError as exc:
            return None if is_notification else _result(
                req_id, _text_result(f"{cfg.server_name}: {exc}", False))
        except Exception as exc:
            logger.exception("mcp bridge: call failed for %s", name)
            return None if is_notification else _result(req_id, _text_result(
                f"{cfg.server_name}: tool call failed ({exc.__class__.__name__})", False))

        if is_notification:
            return None
        # Pass the upstream blocks through rather than flattening to text. The
        # sidecar is an MCP client like any other, so an image stays an image
        # here — only the native loop, which consumes plain text, needs
        # `protocol.flatten_content`.
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            content = result["content"]
            # A connector's image URL points at its own service, which the
            # sidecar can reach and the user's browser cannot. Mirror the bytes
            # into this run's artifacts so the link the model repeats is one
            # that actually opens — and so the picture shows up in the rail.
            if workspace_id and not result.get("isError"):
                content = await _mirror_content(content, pool, workspace_id)
            return _result(req_id, {
                "content": content,
                "isError": bool(result.get("isError")),
            })
        return _result(req_id, _text_result(json.dumps(result, default=str)[:8000], True))

    if is_notification:
        return None
    return error_response(req_id, METHOD_NOT_FOUND, f"unknown method: {method}")


def sidecar_bridge_config(user_id: int | None, *, run_id: str = "") -> dict | None:
    """The ``mcpServers`` entry that lets a sidecar reach this user's connectors.

    Deliberately sync and deliberately incurious about whether the user has any
    connectors: resolving that needs the database, and every launch site that
    builds a CLI command is synchronous. An entry for a user with nothing
    connected answers ``tools/list`` with an empty list, which costs one round
    trip and is the same thing the CAD door does when a lane has no CAD work.
    """
    if not any_transport_enabled() or not user_id:
        return None
    # Late import: `main` imports this package indirectly, so importing it at
    # module level would cycle. One signer for every Harvis token.
    from main import create_access_token

    token = create_access_token({"sub": str(int(user_id))},
                                timedelta(minutes=SIDECAR_TOKEN_MINUTES))
    headers = {"Authorization": f"Bearer {token}"}
    if run_id:
        # Which run a connector's output belongs to. A header rather than a
        # query parameter so it never lands in a log line or a proxy's access
        # record alongside the token.
        headers[RUN_HEADER] = str(run_id)
    return {SERVER_NAME: {
        "type": "http",
        "url": SIDECAR_MCP_URL,
        "headers": headers,
    }}


def register_connector_mcp_routes(router: APIRouter, get_current_user: Callable) -> None:
    @router.post("/api/connectors/mcp")
    async def connector_mcp(request: Request, user=Depends(get_current_user)):
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse(
                error_response(None, INVALID_REQUEST, "the request body is too large"),
                status_code=413)
        try:
            message = json.loads(raw or b"{}")
        except ValueError:
            return JSONResponse(error_response(None, PARSE_ERROR, "invalid JSON"),
                                status_code=400)

        pool = getattr(request.app.state, "pg_pool", None)
        user_id = getattr(user, "id", None) or (
            user.get("id") if isinstance(user, dict) else None)

        try:
            response = await handle_jsonrpc(
            message, pool=pool, user_id=user_id,
            workspace_id=(request.headers.get(RUN_HEADER) or "").strip(),
        )
        except Exception:
            logger.exception("connector mcp request failed")
            rid = message.get("id") if isinstance(message, dict) else None
            return JSONResponse(error_response(rid, INTERNAL_ERROR, "the request failed"),
                                status_code=500)

        if response is None:
            return JSONResponse(None, status_code=202)
        return JSONResponse(response)

    @router.get("/api/connectors/mcp")
    async def connector_mcp_manifest(request: Request, user=Depends(get_current_user)):
        """What this endpoint is, for a human whose sidecar config is not working."""
        pool = getattr(request.app.state, "pg_pool", None)
        user_id = getattr(user, "id", None) or (
            user.get("id") if isinstance(user, dict) else None)
        mapping = await _tool_map(pool, int(user_id or 0))
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": SERVER_INFO,
            "transport": "http-jsonrpc",
            "tools": sorted(mapping.keys()),
            "auth": "Bearer token — the same Harvis JWT the rest of /api uses",
        }
