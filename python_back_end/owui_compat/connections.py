"""Harvis MCP Connections — the "Customize" half that lets a user register an
MCP server/plugin connection. Authenticated CRUD over the existing `mcp_servers`
table (migration 013), which the unauthenticated plugins/mcp/routes.py left
unexposed. We deliberately do NOT mount those routes (they hardcode user_id=1);
this module is owner-scoped via get_current_user.

Credentials: secret values arrive under ``credentials`` and are sealed by
``plugins.mcp.credentials`` before they touch the database, so a server that
needs an API key (GitHub, Slack, Notion, Higgsfield) can actually be configured
here. A saved secret is never returned — reads are masked — and a save that
omits a credential keeps the stored one, so editing a command does not mean
retyping every token.

NOTE (honest scope): connections are stored + managed per-user here; wiring a
saved connection into the live OpenClaw agent runtime (so its tools become
callable mid-session) is a deferred follow-up — the registry exists, the runtime
discovery does not.
"""

from __future__ import annotations

import html
import json
import logging
import os
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from plugins.mcp.credentials import mask_env, merge_env, sealed_keys

logger = logging.getLogger(__name__)

_TRANSPORTS = {"stdio", "sse", "streamable-http", "http"}
_AUTH_METHODS = {"none", "oauth"}


def _callback_page(ok: bool, detail: str) -> HTMLResponse:
    """The one page a third party's redirect ever renders in Harvis.

    Everything interpolated here came back from an external provider, so it is
    escaped before it reaches the document. Self-closing: the user came from a
    popup and wants to be back in Connectors, not looking at a bare page.
    """
    safe = html.escape(detail or "")
    title = "Connected" if ok else "Authorization failed"
    body = (
        f"<strong>{html.escape(safe)}</strong> is authorized. You can close this window."
        if ok
        else f"Harvis could not finish the authorization.<br><span class='d'>{safe}</span>"
    )
    return HTMLResponse(
        f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.6 ui-sans-serif, system-ui, sans-serif; margin: 0;
         display: grid; place-items: center; min-height: 100vh; padding: 24px; }}
  .c {{ max-width: 30rem; text-align: center; }}
  h1 {{ font-size: 1.15rem; margin: 0 0 .5rem; }}
  .d {{ opacity: .7; font-size: .9em; word-break: break-word; }}
  .m {{ font-size: 2rem; }}
</style>
<div class="c"><div class="m">{'&#10003;' if ok else '&#10005;'}</div>
<h1>{title}</h1><p>{body}</p></div>
<script>setTimeout(function () {{ try {{ window.close(); }} catch (e) {{}} }}, {2500 if ok else 8000});</script>"""
    )


def _conn_to_dict(row, authorized: Optional[set] = None) -> dict:
    def _j(v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v

    created = row["created_at"]
    updated = row["updated_at"]
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "name": row["server_name"],
        "transport": row["transport"],
        "url": row["url"],
        "command": row["command"],
        "args": _j(row["args"]) or [],
        # Sealed values come back as a fixed mask — never the ciphertext, never
        # a length. `credential_keys` is what the UI needs to show "saved".
        "env": mask_env(_j(row["env"]) or {}),
        "credential_keys": sealed_keys(_j(row["env"]) or {}),
        "auth_method": row["auth_method"],
        # Whether an OAuth grant is on file. Only meaningful for remote servers
        # with auth_method='oauth'; the UI uses it to pick Authorize vs Connected.
        "authorized": bool(authorized and row["server_name"] in authorized),
        "enabled": row["enabled"],
        "created_at": int(created.timestamp()) if created else None,
        "updated_at": int(updated.timestamp()) if updated else None,
    }


class ConnForm(BaseModel):
    name: Optional[str] = None
    server_name: Optional[str] = None
    transport: str = "stdio"
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list] = None
    env: Optional[dict] = None
    # Secret env values, sealed before storage. Kept separate from `env` so a
    # client can post non-secret config without ever handling ciphertext.
    credentials: Optional[dict] = None
    # Credential names to forget outright.
    drop_credentials: Optional[list] = None
    auth_method: str = "none"


def register_connection_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        return pool

    @router.get("/api/owui/mcp/connections")
    async def conn_list(request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM mcp_servers WHERE user_id=$1 ORDER BY updated_at DESC",
                int(user.id),
            )
            granted = await conn.fetch(
                "SELECT server_name FROM mcp_oauth_tokens "
                "WHERE user_id=$1 AND tokens_json IS NOT NULL",
                int(user.id),
            )
        authorized = {g["server_name"] for g in granted}
        return {"items": [_conn_to_dict(r, authorized) for r in rows]}

    @router.post("/api/owui/mcp/connections")
    async def conn_upsert(form: ConnForm, request: Request, user=Depends(get_current_user)):
        name = (form.name or form.server_name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Connection name is required.")
        transport = (form.transport or "stdio").strip().lower()
        if transport not in _TRANSPORTS:
            raise HTTPException(status_code=400, detail=f"Unsupported transport: {transport}")
        if transport == "stdio" and not (form.command or "").strip():
            raise HTTPException(status_code=400, detail="stdio connections need a command.")
        if transport != "stdio" and not (form.url or "").strip():
            raise HTTPException(status_code=400, detail="Remote connections need a URL.")
        auth_method = (form.auth_method or "none").strip().lower()
        if auth_method not in _AUTH_METHODS:
            raise HTTPException(
                status_code=400, detail=f"Unsupported auth method: {auth_method}"
            )
        if transport != "stdio":
            # Refuse an unreachable or internal URL at save time rather than
            # letting it fail later as a mystery inside the agent loop.
            from plugins.mcp.http_transport import guard_url_async
            from plugins.mcp.protocol import McpError as _McpError

            try:
                await guard_url_async(form.url or "")
            except _McpError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        pool = _pool(request)
        async with pool.acquire() as conn:
            # Read the stored env first: a re-save that omits a credential must
            # keep it, otherwise editing the command silently wipes the token.
            prior = await conn.fetchval(
                "SELECT env FROM mcp_servers WHERE user_id=$1 AND server_name=$2",
                int(user.id), name,
            )
            if isinstance(prior, str):
                try:
                    prior = json.loads(prior)
                except (TypeError, ValueError):
                    prior = {}
            env = merge_env(
                prior or {},
                env=form.env or {},
                credentials=form.credentials or {},
                drop=form.drop_credentials or [],
            )
            row = await conn.fetchrow(
                "INSERT INTO mcp_servers (user_id, server_name, transport, url, command, args, env, auth_method) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8) "
                "ON CONFLICT (user_id, server_name) DO UPDATE SET "
                "transport=EXCLUDED.transport, url=EXCLUDED.url, command=EXCLUDED.command, "
                "args=EXCLUDED.args, env=EXCLUDED.env, auth_method=EXCLUDED.auth_method, updated_at=NOW() "
                "RETURNING *",
                int(user.id), name, transport, form.url or None, form.command or None,
                json.dumps(form.args or []), json.dumps(env), auth_method,
            )
        return _conn_to_dict(row)

    @router.post("/api/owui/mcp/connections/{conn_id}/toggle")
    async def conn_toggle(conn_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE mcp_servers SET enabled = NOT enabled, updated_at = NOW() "
                "WHERE id=$1 AND user_id=$2 RETURNING *",
                int(conn_id), int(user.id),
            )
        if not row:
            raise HTTPException(status_code=404, detail="Connection not found")
        return _conn_to_dict(row)

    @router.delete("/api/owui/mcp/connections/{conn_id}")
    async def conn_delete(conn_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM mcp_servers WHERE id=$1 AND user_id=$2", int(conn_id), int(user.id)
            )
        return True

    # -- remote servers: authorization + a real reachability check -----------

    async def _config_for(pool, user_id: int, conn_id: str):
        """The registry's view of one connection, owner-scoped."""
        from plugins.mcp.server_registry import McpServerRegistry

        async with pool.acquire() as conn:
            name = await conn.fetchval(
                "SELECT server_name FROM mcp_servers WHERE id=$1 AND user_id=$2",
                int(conn_id), int(user_id),
            )
        if not name:
            raise HTTPException(status_code=404, detail="Connection not found")
        cfg = await McpServerRegistry(pool).get(int(user_id), name)
        if cfg is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        return cfg

    def _redirect_uri(request: Request) -> str:
        """Where the vendor sends the user back.

        Behind Nginx the app's own origin is in the forwarded headers, not in
        the socket, so a naive base_url produces ``http://backend:8000`` — a
        host the user's browser cannot reach and the vendor will reject.
        """
        override = (os.getenv("HARVIS_PUBLIC_URL") or "").strip().rstrip("/")
        if override:
            return f"{override}/api/owui/mcp/oauth/callback"
        headers = request.headers
        host = headers.get("x-forwarded-host") or headers.get("host") or ""
        proto = headers.get("x-forwarded-proto") or request.url.scheme or "http"
        if not host:
            return str(request.url_for("mcp_oauth_callback"))
        return f"{proto}://{host}/api/owui/mcp/oauth/callback"

    @router.post("/api/owui/mcp/connections/{conn_id}/probe")
    async def conn_probe(conn_id: str, request: Request, user=Depends(get_current_user)):
        """Actually connect and list tools. The only honest 'does this work?'."""
        from plugins.mcp.protocol import McpAuthRequired, McpError
        from plugins.mcp.runtime import mcp_runtime, transport_enabled
        from plugins.mcp.types import Transport

        pool = _pool(request)
        cfg = await _config_for(pool, int(user.id), conn_id)
        if not transport_enabled(cfg.transport):
            flag = (
                "HARVIS_MCP_RUNTIME_ENABLED"
                if cfg.transport == Transport.STDIO
                else "HARVIS_MCP_REMOTE_ENABLED"
            )
            return {
                "ok": False,
                "needs_authorization": False,
                "error": f"{cfg.transport.value} MCP servers are disabled here "
                         f"— set {flag}=1 and restart the backend.",
            }
        mcp_runtime.bind_pool(pool)
        # Drop any cached session so a probe reflects the config as saved now.
        await mcp_runtime.disconnect(int(user.id), cfg.server_name)
        try:
            tools = await mcp_runtime.list_tools(cfg)
        except McpAuthRequired as exc:
            return {
                "ok": False,
                "needs_authorization": True,
                "error": str(exc),
                "detail": exc.www_authenticate,
            }
        except McpError as exc:
            return {"ok": False, "needs_authorization": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("mcp probe failed for %s", cfg.server_name)
            return {"ok": False, "needs_authorization": False, "error": str(exc)}
        return {
            "ok": True,
            "needs_authorization": False,
            "tool_count": len(tools),
            "tools": [t.get("name") for t in tools if t.get("name")][:60],
        }

    @router.post("/api/owui/mcp/connections/{conn_id}/authorize")
    async def conn_authorize(conn_id: str, request: Request, user=Depends(get_current_user)):
        """Begin an OAuth authorization. Returns a URL for the user to open."""
        from plugins.mcp.oauth import begin_authorization
        from plugins.mcp.protocol import McpError

        pool = _pool(request)
        cfg = await _config_for(pool, int(user.id), conn_id)
        if not cfg.url:
            raise HTTPException(status_code=400, detail="Only remote servers use OAuth.")
        try:
            return await begin_authorization(cfg, pool, _redirect_uri(request))
        except McpError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/owui/mcp/connections/{conn_id}/authorize")
    async def conn_deauthorize(conn_id: str, request: Request, user=Depends(get_current_user)):
        """Forget a stored grant, so the next Authorize starts clean."""
        from plugins.mcp.oauth import forget
        from plugins.mcp.runtime import mcp_runtime

        pool = _pool(request)
        cfg = await _config_for(pool, int(user.id), conn_id)
        await forget(cfg, pool)
        await mcp_runtime.disconnect(int(user.id), cfg.server_name)
        return {"ok": True}

    @router.get("/api/owui/mcp/oauth/callback", name="mcp_oauth_callback")
    async def mcp_oauth_callback(request: Request):
        """Where the vendor returns the user. Deliberately unauthenticated.

        The browser arriving here carries no Harvis token — the JWT lives in
        localStorage, and a redirect from a third party cannot present it. The
        ``state`` value is what authenticates this call: it is a 192-bit secret
        minted by the authorize route above and bound server-side to exactly one
        (user, server) pair, which is precisely the job OAuth gives it.
        """
        from plugins.mcp.oauth import complete_authorization
        from plugins.mcp.protocol import McpError
        from plugins.mcp.runtime import mcp_runtime

        params = request.query_params
        state = params.get("state") or ""
        code = params.get("code") or ""
        if params.get("error"):
            return _callback_page(
                False, params.get("error_description") or params.get("error") or "denied"
            )
        if not state or not code:
            return _callback_page(False, "the provider returned no authorization code")
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            return _callback_page(False, "the database is not ready")
        try:
            done = await complete_authorization(state, code, pool)
        except McpError as exc:
            return _callback_page(False, str(exc))
        except Exception as exc:
            logger.exception("mcp oauth callback failed")
            return _callback_page(False, str(exc))
        # A session cached from before the grant is holding a 401.
        await mcp_runtime.disconnect(int(done["user_id"]), done["server_name"])
        return _callback_page(True, done["server_name"])
