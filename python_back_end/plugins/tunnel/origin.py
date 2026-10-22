"""Wherever a tunnel leads here, refuse Cloudflare traffic that skipped the Access check.

The tunnel's public hostname must point at ``http://nginx:8081``, the entrance
that asks ``/api/tunnel/verify`` before every request. Nothing in Cloudflare
enforces that, so a route typed as ``http://backend:8000`` or ``http://nginx:80``
would hand the internet a server with no Access check. Cloudflare stamps
``CF-Ray`` on everything it forwards; here any request with that stamp must
also carry a valid Access token, wherever it came in. Requests from this
computer or the LAN carry no stamp and pass untouched.
"""
from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from . import access
from plugins.exposure.mode import access_gate_on

MESSAGE = ("This request came through Cloudflare without a valid Access sign-in. Check that the "
           "tunnel's public hostname points at http://nginx:8081 and that an Access app covers it.")


class TunnelOriginGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not access_gate_on():
            await self.app(scope, receive, send)
            return
        headers: dict[str, str] = {}
        for k, v in scope.get("headers") or []:  # first value wins, as in Starlette's Headers.get
            headers.setdefault(k.decode("latin-1").lower(), v.decode("latin-1"))
        if "cf-ray" not in headers or await access.verify(headers.get(access.HEADER.lower())):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await WebSocket(scope, receive=receive, send=send).close(code=4403, reason="no Access sign-in")
            return
        await JSONResponse({"detail": MESSAGE}, status_code=403)(scope, receive, send)
