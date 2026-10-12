"""MCP half of the Capabilities screen that rest_capabilities.py does not hold:
the config-record projection the MCP tab lists from, the real connect-and-list
probe behind each server's status dot, and the OAuth routes the UI calls
(logic in mcp_oauth_flows.py).

The desktop MCP tab does not read GET /mcp/servers. It draws its list from the
``mcp_servers`` map inside the config record (GET /api/config), the same way
the Hermes CLI reads config.yaml, and saves the whole map back with PUT
/mcp/servers. ``config_servers`` is that projection of the ``mcp_servers``
table; rest.py splices it into the record so load and save round-trip.
Registered BEFORE rest.py, which ends in a catch-all.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from auth_optimized import get_current_user_optimized

log = logging.getLogger("hermes_ui.rest")

router = APIRouter(prefix="/hermes-api/api", tags=["hermes-ui"])

def _uid(user) -> int:
    return int(getattr(user, "id", None) or getattr(user, "user_id", None) or user["id"])


def _pool(request: Request):
    return request.app.state.pg_pool


def _args(raw) -> list:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return list(raw) if isinstance(raw, list) else []


async def config_servers(pool, user_id: int) -> dict:
    """The user's ``mcp_servers`` rows as the config.yaml-shaped map the MCP tab
    reads: ``{name: {transport, url | command, args, enabled?, auth?}}``.

    Only the keys the editor would write are present (``enabled`` appears only
    when false, exactly as the editor stores it), so what the tab shows is what
    its Save sends back. ``env`` is sealed in the table and never leaves it.
    """
    if pool is None:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT server_name, transport, url, command, args, auth_method, enabled "
            "FROM mcp_servers WHERE user_id=$1 ORDER BY server_name", int(user_id))
    out: dict = {}
    for r in rows:
        entry: dict = {"transport": r["transport"]}
        if r["url"]:
            entry["url"] = r["url"]
        if r["command"]:
            entry["command"] = r["command"]
            entry["args"] = _args(r["args"])
        if str(r["auth_method"] or "none") == "oauth":
            entry["auth"] = "oauth"
        if not r["enabled"]:
            entry["enabled"] = False
        out[r["server_name"]] = entry
    return out


@router.post("/mcp/servers/{name}/test")
async def mcp_server_test(name: str, request: Request,
                          user=Depends(get_current_user_optimized)):
    """Connect for real and list tools — the only honest 'does this work?'.

    Shape is the desktop's McpTestResult: ``{ok, error?, tools:[{name,
    description, schema_chars}]}``. A failure is a 200 with ``ok: false`` so the
    status dot can show WHY, and the wording of an auth failure is chosen so
    the tab's needs-auth classifier (which looks for 'authentication') fires.
    """
    from plugins.mcp import runtime as mcp_rt
    from plugins.mcp.protocol import McpAuthRequired, McpError
    from plugins.mcp.server_registry import McpServerRegistry
    from plugins.mcp.types import Transport

    pool, uid = _pool(request), _uid(user)
    cfg = await McpServerRegistry(pool).get(uid, name)
    if cfg is None:
        raise HTTPException(404, f"unknown MCP server: {name}")
    if not mcp_rt.transport_enabled(cfg.transport):
        flag = ("HARVIS_MCP_RUNTIME_ENABLED" if cfg.transport == Transport.STDIO
                else "HARVIS_MCP_REMOTE_ENABLED")
        return {"ok": False, "tools": [],
                "error": f"{cfg.transport.value} MCP servers are disabled on this "
                         f"deployment — set {flag}=1 and restart the backend."}
    runtime = mcp_rt.mcp_runtime
    runtime.bind_pool(pool)
    # Drop any cached session so the probe reflects the config as saved now.
    await runtime.disconnect(uid, cfg.server_name)
    try:
        tools = await runtime.list_tools(cfg)
    except McpAuthRequired as exc:
        return {"ok": False, "tools": [],
                "error": f"authentication required — the server answered 401 ({exc})"}
    except McpError as exc:
        return {"ok": False, "tools": [], "error": str(exc)}
    except Exception as exc:
        log.exception("hermes_ui: MCP probe failed for %s", cfg.server_name)
        return {"ok": False, "tools": [], "error": f"{exc.__class__.__name__}: {exc}"}
    return {"ok": True, "tools": [
        {"name": str(t.get("name") or ""),
         "description": str(t.get("description") or ""),
         "schema_chars": len(json.dumps(t.get("inputSchema") or {}))}
        for t in tools if t.get("name")]}


# The tab's Connect button: start a flow, open the vendor's page, poll the flow.
# The logic lives in mcp_oauth_flows.py; these are the routes the UI calls
# (api/mcp.ts McpOAuthFlow) plus the vendor's redirect target.

@router.post("/mcp/servers/{name}/auth")
async def mcp_server_auth(name: str, request: Request, user=Depends(get_current_user_optimized)):
    """Begin signing in. Body (optional): ``{client_id, client_secret}`` for a server
    that offers no dynamic registration."""
    from . import mcp_oauth_flows as flows

    try:
        body = await request.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    return await flows.start(
        _pool(request), _uid(user), name, request,
        client_id=str(body.get("client_id") or ""), client_secret=str(body.get("client_secret") or ""))


@router.get("/mcp/oauth/flows/{flow_id}")
async def mcp_oauth_flow(flow_id: str, user=Depends(get_current_user_optimized)):
    from . import mcp_oauth_flows as flows

    flow = flows.get(_uid(user), flow_id)
    if flow is None:
        raise HTTPException(404, "That sign-in is no longer in progress. Click Connect to start again.")
    return flow


@router.delete("/mcp/oauth/flows/{flow_id}")
async def mcp_oauth_flow_cancel(flow_id: str, user=Depends(get_current_user_optimized)):
    from . import mcp_oauth_flows as flows

    result = flows.cancel(_uid(user), flow_id)
    if result is None:
        raise HTTPException(404, "That sign-in is no longer in progress.")
    return result


@router.get("/mcp/oauth/callback")
async def mcp_oauth_callback(request: Request):
    """Where the vendor returns the person. Deliberately not signed in: see mcp_oauth_flows."""
    from . import mcp_oauth_flows as flows

    params = request.query_params
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return flows.callback_page(False, "the database is not ready")
    ok, detail = await flows.complete(
        pool, params.get("state") or "", params.get("code") or "",
        (params.get("error_description") or params.get("error") or "")[:300])
    return flows.callback_page(ok, detail)
