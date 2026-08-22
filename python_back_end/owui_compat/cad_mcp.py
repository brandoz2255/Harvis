"""The CAD tool surface as an authenticated MCP server: ``POST /api/cad/mcp``.

Claude Code and Kimi Code are sidecars. They do not run inside a Harvis chat turn,
so they cannot be handed native tool definitions the way the chat lanes are — they
speak MCP, and MCP is the only door they have. This module is that door, and it is
the *same tool set* as the native lanes: ``cad_tools.mcp_tools()`` and
``cad_tools.dispatch`` are shared, so there is exactly one implementation and one
place where the ownership rules live.

**Identity comes from the request, never from the payload.** The user id is read
off the JWT by the same dependency every other Harvis route uses and placed in the
``CadToolContext`` server-side. A sidecar can name a project id; it cannot name a
user, a storage key, or a path — ``dispatch`` refuses those arguments outright, and
every store read is scoped to the authenticated caller. That is what makes an MCP
surface safe to expose to a process running with a developer's shell.

This is a **stateless HTTP JSON-RPC** endpoint, not the stdio transport: one POST
carries one request and gets one response. There is no session to hijack and
nothing is kept between calls, so a dropped connection loses a call rather than a
conversation. ``initialize`` is answered for conformance — clients send it first —
but the server holds no state as a result.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from datetime import timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import cad_tools, fab_cad

logger = logging.getLogger(__name__)

# Matches the version the Harvis MCP *client* speaks (plugins/mcp/protocol.py).
# One version across both directions keeps a client and server in the same
# deployment from disagreeing about the wire.
PROTOCOL_VERSION = "2024-11-05"

SERVER_INFO = {"name": "harvis-cad", "version": "0.1"}

# JSON-RPC 2.0 error codes. `-32000` is the reserved implementation-defined range,
# which is where a tool that ran and refused belongs — a CAD tool answering
# "not_found" is not a malformed request.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

MAX_BODY_BYTES = 256 * 1024

# How a sidecar reaches this endpoint. Sidecars are sibling containers on the
# backend's own Docker network, so the URL is the internal service name — the
# host-facing one resolves to nothing from inside them.
SIDECAR_MCP_URL = os.getenv("HARVIS_CAD_MCP_URL", "http://backend:8000/api/cad/mcp")

# Long enough for a build with repair attempts, short enough that a token left
# behind in a process listing is dead before anyone could go looking for it.
SIDECAR_TOKEN_MINUTES = 90

# Server-injected context, carried beside the bearer token rather than inside the
# tool arguments. See `sidecar_mcp_config`.
CONTEXT_HEADER = "x-harvis-cad-context"

# The user's own message is the answer key a part is graded against, and a long one
# would otherwise bloat the process command line. Well past any real CAD request.
MAX_CONTEXT_USER_TEXT = 4000


def sidecar_mcp_config(user_id: int | None, *, conversation_id: str | None = None,
                       user_text: str | None = None,
                       model_provider: str | None = None,
                       model_name: str | None = None) -> dict | None:
    """The ``--mcp-config`` payload that lets a Claude Code sidecar author CAD.

    ``None`` when the lane is off or the caller is anonymous. That matters: handing
    the CLI a server whose every call 404s costs the model a round trip and reads to
    it as its own mistake, so a deployment without CAD should register nothing at all.

    The token is minted per run and scoped to one user by the same signer the rest of
    ``/api`` verifies against. It travels in the command line, like the model
    credential three lines above it in every launch site — the alternative, a config
    file in the shared artifact volume, would leave the token on disk after the run
    instead of dying with the process.

    **The context header is why a sidecar-authored part can be graded honestly.** A
    sidecar has no way to know the conversation it belongs to or what the person
    actually typed, so without this those arrive — if at all — as ``_meta`` the model
    itself wrote, and the DesignSpec would be extracted from the model's retelling of
    the request. Putting them here makes them exactly as trustworthy as the bearer
    token they sit next to: both are written by Harvis into one launch, and a process
    that could forge one could equally have stolen the other. The model is never asked
    for them and there is no tool that accepts them.
    """
    if not fab_cad.cad_enabled() or not user_id:
        return None
    # Late import: `main` imports this package, so a module-level import would cycle.
    # One signer for every Harvis token, rather than a second copy of the secret's
    # env-var name and fallback living out here.
    from main import create_access_token

    token = create_access_token({"sub": str(int(user_id))},
                                timedelta(minutes=SIDECAR_TOKEN_MINUTES))
    headers = {"Authorization": f"Bearer {token}"}
    ctx = {k: v for k, v in (
        ("conversation_id", str(conversation_id) if conversation_id else None),
        ("user_text", (user_text or "").strip()[:MAX_CONTEXT_USER_TEXT] or None),
        ("model_provider", model_provider or None),
        ("model_name", model_name or None),
    ) if v}
    if ctx:
        # Base64 because a header may not carry the newlines a real request has, and
        # a mangled answer key is worse than none.
        headers[CONTEXT_HEADER] = base64.b64encode(
            json.dumps(ctx, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return {"mcpServers": {SERVER_INFO["name"]: {
        "type": "http",
        "url": SIDECAR_MCP_URL,
        "headers": headers,
    }}}


def _injected_context(request: Request) -> dict:
    """Read the server-injected context header. Never raises — a malformed header
    means the launch site did not set one, which is the pre-existing behaviour."""
    raw = request.headers.get(CONTEXT_HEADER)
    if not raw:
        return {}
    try:
        data = json.loads(base64.b64decode(raw))
    except Exception:
        logger.debug("cad mcp: unreadable context header", exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_result(payload: dict, ok: bool) -> dict:
    """One tool answer in both shapes MCP clients read.

    ``content`` is what a model actually sees; ``structuredContent`` is the same
    object for a client that would rather parse than re-parse. A refusal is
    ``isError: true`` *and* readable text — a client that only checks the flag and
    one that only reads the text both learn the same thing.
    """
    return {
        "content": [{"type": "text", "text": cad_tools.as_text(payload, ok)}],
        "structuredContent": payload,
        "isError": not ok,
    }


async def _handle(message: dict, ctx_for: Callable[[dict], cad_tools.CadToolContext]) -> dict | None:
    """One JSON-RPC message in, one response out — or ``None`` for a notification.

    A notification (no ``id``) gets no reply, per JSON-RPC. ``notifications/
    initialized`` is the one clients always send, and answering it would be a
    protocol error rather than a courtesy.
    """
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
            # Tools and nothing else. Declaring resources or prompts we do not serve
            # sends clients calling into a hole.
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })

    if method and method.startswith("notifications/"):
        return None

    if method == "ping":
        return None if is_notification else _result(req_id, {})

    if method == "tools/list":
        return None if is_notification else _result(req_id, {"tools": cad_tools.mcp_tools()})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(name, str):
            return _error(req_id, INVALID_PARAMS, "tools/call needs a tool name")
        if not isinstance(args, dict):
            return _error(req_id, INVALID_PARAMS, "arguments must be an object")
        payload, ok = await cad_tools.dispatch(name, args, ctx_for(params))
        # A refused tool is a *result*, not a JSON-RPC error: the call itself was
        # well-formed and the model needs to read why it was refused so it can fix
        # the next one. A transport error would arrive as an exception it cannot act on.
        return None if is_notification else _result(req_id, _tool_result(payload, ok))

    if is_notification:
        return None
    return _error(req_id, METHOD_NOT_FOUND, f"unknown method: {method}")


def register_cad_mcp_routes(router: APIRouter, get_current_user: Callable) -> None:
    def require_cad_enabled() -> None:
        """404, not 403 — the same answer the rest of the CAD lane gives, so a
        disabled deployment is indistinguishable from one that never had the lane."""
        if not fab_cad.cad_enabled():
            raise HTTPException(status_code=404, detail="Not Found")

    @router.post("/api/cad/mcp", dependencies=[Depends(require_cad_enabled)])
    async def cad_mcp(request: Request, user=Depends(get_current_user)):
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse(
                _error(None, INVALID_REQUEST, "the request body is too large"),
                status_code=413)
        try:
            message = json.loads(raw or b"{}")
        except ValueError:
            return JSONResponse(_error(None, PARSE_ERROR, "invalid JSON"), status_code=400)

        pool = getattr(request.app.state, "pg_pool", None)
        user_id = getattr(user, "id", None) or (
            user.get("id") if isinstance(user, dict) else None)

        injected = _injected_context(request)

        def ctx_for(params: dict) -> cad_tools.CadToolContext:
            # Harvis's own header wins over `_meta` in every field. `_meta` is written
            # by the client — for a sidecar that means the model — so it is a hint
            # about what the person asked for and is labelled as such: `_design_spec`
            # records `source`, and a spec extracted from a model's paraphrase is
            # never indistinguishable from one extracted from the user's own words.
            # When the launch site injected the real message, the paraphrase loses.
            meta = params.get("_meta") or {}
            return cad_tools.CadToolContext(
                pool=pool,
                user_id=int(user_id),
                conversation_id=(injected.get("conversation_id")
                                 or meta.get("conversation_id") or None),
                user_text=(injected.get("user_text") or meta.get("user_text") or None),
                source="mcp",
                # Only ever from the header: which model is really driving is
                # something the surface knows and the caller may not claim.
                model_provider=(injected.get("model_provider") or None),
                model_name=(injected.get("model_name") or None),
            )

        try:
            response = await _handle(message, ctx_for)
        except Exception:
            logger.exception("cad mcp request failed")
            rid = message.get("id") if isinstance(message, dict) else None
            return JSONResponse(_error(rid, INTERNAL_ERROR, "the request failed"),
                                status_code=500)

        if response is None:
            # A notification is answered with 202 and no body, which is what an MCP
            # client over HTTP expects for a message it is not waiting on.
            return JSONResponse(None, status_code=202)
        return JSONResponse(response)

    @router.get("/api/cad/mcp", dependencies=[Depends(require_cad_enabled)])
    async def cad_mcp_manifest(user=Depends(get_current_user)):
        """What this endpoint is, for a human wiring up a sidecar.

        Not part of MCP — a GET on the same path is what someone does first when a
        config is not working, and an empty 405 teaches them nothing.
        """
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": SERVER_INFO,
            "transport": "http-jsonrpc",
            "tools": [t["name"] for t in cad_tools.mcp_tools()],
            "auth": "Bearer token — the same Harvis JWT the rest of /api uses",
        }
