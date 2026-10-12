"""Signing in to a hosted MCP server from the Hermes MCP tab ("Connect").

The tab asks for a flow (``POST /mcp/servers/{name}/auth``), opens the vendor's
sign-in page in a window, and polls the flow until it reads ``approved``. In
between, the vendor sends the person's browser to Harvis's callback with a code.

Who is allowed to do what:

* Starting, polling and cancelling are signed-in calls, and a flow is only ever
  visible to the user who started it.
* The callback is not signed in — the browser the vendor redirects has no Harvis
  token to present. ``state`` stands in for it: a 192-bit secret minted at start,
  bound to one (user, server) inside ``plugins.mcp.oauth``, usable once, and
  refused after ten minutes.

The tokens themselves never pass through here; ``plugins.mcp.oauth`` exchanges the
code and stores them sealed. This module only tracks progress for the poll.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import secrets
import time
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from plugins.mcp import oauth

log = logging.getLogger("hermes_ui.mcp_oauth")

CALLBACK_PATH = "/hermes-api/api/mcp/oauth/callback"
FLOW_TTL_S = oauth.PENDING_TTL_S
_KEEP_FINISHED_S = 3600
_PROBE_TIMEOUT_S = 20.0

# flow_id -> flow record. One backend process, like the pending store it fronts.
_FLOWS: dict[str, dict] = {}


def redirect_uri(request: Request) -> str:
    """Where the vendor sends the person back.

    Behind Nginx the app's own origin is in the forwarded headers, not in the
    socket; ``HARVIS_PUBLIC_URL`` wins when set (tunnels, custom domains).
    """
    override = (os.getenv("HARVIS_PUBLIC_URL") or "").strip().rstrip("/")
    if override:
        return f"{override}{CALLBACK_PATH}"
    headers = request.headers
    host = headers.get("x-forwarded-host") or headers.get("host") or ""
    proto = headers.get("x-forwarded-proto") or getattr(request.url, "scheme", "") or "http"
    return f"{proto}://{host}{CALLBACK_PATH}" if host else CALLBACK_PATH


def _view(flow: dict) -> dict:
    out = {"flow_id": flow["flow_id"], "server_name": flow["server_name"], "status": flow["status"],
           "authorization_url": flow.get("authorization_url"), "error": flow.get("error")}
    if flow.get("tools") is not None:
        out["tools"] = flow["tools"]
    if flow.get("needs_client_id"):
        out["needs_client_id"] = True
    return out


def _sweep() -> None:
    cutoff = time.time() - _KEEP_FINISHED_S
    for fid in [f for f, v in _FLOWS.items() if v["created"] < cutoff]:
        _FLOWS.pop(fid, None)


def _drop_live_flow(user_id: int, server_name: str) -> None:
    """A second Connect for the same server replaces the first, rather than 409ing."""
    for fid, flow in list(_FLOWS.items()):
        if flow["user_id"] == user_id and flow["server_name"] == server_name:
            if flow.get("state"):
                oauth.discard(flow["state"])
            _FLOWS.pop(fid, None)


async def start(pool, user_id: int, name: str, request: Request, *,
                client_id: str = "", client_secret: str = "") -> dict:
    from plugins.mcp.server_registry import McpServerRegistry

    cfg = await McpServerRegistry(pool).get(user_id, name)
    if cfg is None:
        raise HTTPException(404, f"unknown MCP server: {name}")
    if not cfg.url:
        raise HTTPException(400, "Only remote servers (with a URL) can sign in with OAuth.")
    _sweep()
    _drop_live_flow(user_id, cfg.server_name)
    flow = {"flow_id": secrets.token_urlsafe(16), "user_id": user_id, "server_name": cfg.server_name,
            "status": "starting", "authorization_url": None, "error": None, "state": None,
            "created": time.time()}
    _FLOWS[flow["flow_id"]] = flow
    try:
        begun = await oauth.begin_authorization(
            cfg, pool, redirect_uri(request), client_id=client_id, client_secret=client_secret)
    except oauth.OAuthError as exc:
        _fail(flow, str(exc), needs_client_id=exc.code == oauth.disc.CODE_NO_REGISTRATION)
    except Exception as exc:
        # McpError from the SSRF guard lands here too: its text is safe to show.
        from plugins.mcp.protocol import McpError
        if isinstance(exc, McpError):
            _fail(flow, str(exc))
        else:
            log.exception("hermes_ui: MCP OAuth start failed for %s", cfg.server_name)
            _fail(flow, "Could not start sign-in. Check the server address and try again.")
    else:
        flow.update(status="authorization_required", state=begun["state"],
                    authorization_url=begun["authorize_url"])
    return _view(flow)


def _fail(flow: dict, message: str, *, needs_client_id: bool = False) -> None:
    flow.update(status="error", error=message, authorization_url=None, needs_client_id=needs_client_id)


def get(user_id: int, flow_id: str) -> Optional[dict]:
    flow = _FLOWS.get(flow_id)
    if flow is None or flow["user_id"] != user_id:
        return None
    if flow["status"] == "authorization_required" and time.time() - flow["created"] > FLOW_TTL_S:
        if flow.get("state"):
            oauth.discard(flow["state"])
        _fail(flow, "The sign-in window expired. Click Connect to try again.")
    return _view(flow)


def cancel(user_id: int, flow_id: str) -> Optional[dict]:
    flow = _FLOWS.get(flow_id)
    if flow is None or flow["user_id"] != user_id:
        return None
    if flow.get("state"):
        oauth.discard(flow["state"])
    if flow["status"] not in ("approved", "error"):
        _fail(flow, "Cancelled.")
    return {"ok": True, "status": "cancelled"}


def _flow_for_state(state: str) -> Optional[dict]:
    return next((f for f in _FLOWS.values() if f.get("state") == state), None)


async def complete(pool, state: str, code: str, provider_error: str = "") -> tuple[bool, str]:
    """Handle the vendor's redirect. Returns ``(ok, server_name or reason)`` for the page."""
    state = (state or "").strip()
    flow = _flow_for_state(state)
    if provider_error or not code:
        oauth.discard(state)
        reason = provider_error or "the provider returned no authorization code"
        if flow:
            _fail(flow, reason)
        return False, reason
    try:
        done = await oauth.complete_authorization(state, code, pool)
    except oauth.OAuthError as exc:
        if flow:
            _fail(flow, str(exc))
        return False, str(exc)
    except Exception:
        log.exception("hermes_ui: MCP OAuth callback failed")
        if flow:
            _fail(flow, "Sign-in could not be completed.")
        return False, "Sign-in could not be completed."
    tools = await _mark_connected(pool, done["user_id"], done["server_name"])
    if flow:
        flow.update(status="approved", error=None, authorization_url=None, tools=tools, state=None)
    return True, done["server_name"]


async def _mark_connected(pool, user_id: int, server_name: str) -> list:
    """Flip the row to OAuth, drop the session that was holding a 401, list the tools."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE mcp_servers SET auth_method='oauth', updated_at=NOW() "
            "WHERE user_id=$1 AND server_name=$2", user_id, server_name)
    try:
        from plugins.mcp import runtime as mcp_rt
        from plugins.mcp.server_registry import McpServerRegistry

        runtime = mcp_rt.mcp_runtime
        runtime.bind_pool(pool)
        await runtime.disconnect(user_id, server_name)
        cfg = await McpServerRegistry(pool).get(user_id, server_name)
        if cfg is None or not mcp_rt.transport_enabled(cfg.transport):
            return []
        tools = await asyncio.wait_for(runtime.list_tools(cfg), timeout=_PROBE_TIMEOUT_S)
        return [{"name": str(t.get("name") or ""), "description": str(t.get("description") or "")}
                for t in tools if t.get("name")]
    except Exception:
        # Connected is connected; the tab's own status probe will say what is wrong.
        log.info("hermes_ui: tool listing after OAuth failed for %s", server_name, exc_info=True)
        return []


def callback_page(ok: bool, detail: str) -> HTMLResponse:
    """The one page a vendor's redirect renders. Everything interpolated came from
    outside, so it is escaped; the script tells the opener and closes the window."""
    safe = html.escape(detail or "")
    title = "Connected" if ok else "Sign-in failed"
    body = (f"<strong>{safe}</strong> is connected. You can close this window." if ok
            else f"Harvis could not finish signing in.<br><span class='d'>{safe}</span>")
    message = '{"type":"harvis-mcp-oauth","ok":%s}' % ("true" if ok else "false")
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
<script>
try {{ if (window.opener) window.opener.postMessage({message}, location.origin) }} catch (e) {{}}
setTimeout(function () {{ try {{ window.close() }} catch (e) {{}} }}, {1500 if ok else 8000});
</script>""",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
