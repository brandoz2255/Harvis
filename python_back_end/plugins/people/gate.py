"""Refuse every request and socket carrying a turned-off account's sign-in.

Harvis has several auth dependencies (main.get_current_user, auth_optimized,
per-router helpers) and the Hermes socket decodes the JWT itself, so a check in
any one of them would leave the others open. This sits in front of all of them.

Sign-in, sign-up and sign-out stay open: a browser still holding a turned-off
person's cookie must be able to sign someone else in. The sign-in routes refuse
the turned-off account themselves.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from starlette.requests import cookie_parser
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from auth_optimized import decode_token_fast

from .controls import BLOCKED_MESSAGE, is_blocked

_OPEN_PATHS = frozenset({
    "/api/v1/auths/signin", "/api/v1/auths/signup", "/api/v1/auths/signout",
    "/api/auth/login", "/api/auth/signup", "/api/auth/logout",
})


def _tokens(scope: Scope) -> set[str]:
    """Every sign-in the request carries. Routes differ in which one they read
    first (Bearer, the ``access_token`` cookie, the terminal's ``token`` cookie
    or ``?token=``), so a turned-off token in any of them is refused."""
    found: set[str] = set()
    cookie_header = ""
    for k, v in scope.get("headers") or []:
        name = k.decode("latin-1").lower()
        if name == "authorization":
            value = v.decode("latin-1")
            if value[:7].lower() == "bearer ":
                found.add(value[7:].strip())
        elif name == "cookie":
            cookie_header += "; " + v.decode("latin-1")
    cookies = cookie_parser(cookie_header)
    found.update(cookies.get(n, "") for n in ("access_token", "token"))
    found.update(parse_qs(scope.get("query_string", b"").decode("latin-1")).get("token", []))
    found.discard("")
    return found


def _user_ids(scope: Scope) -> set[int]:
    ids: set[int] = set()
    for token in _tokens(scope):
        payload = decode_token_fast(token)
        try:
            if payload and payload.get("sub") is not None:
                ids.add(int(payload["sub"]))
        except (TypeError, ValueError):
            continue
    return ids


class BlockedAccountGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or scope.get("path") in _OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        app = scope.get("app")
        pool = getattr(getattr(app, "state", None), "pg_pool", None)
        for uid in _user_ids(scope):
            if await is_blocked(pool, uid):
                if scope["type"] == "websocket":
                    await WebSocket(scope, receive=receive, send=send).close(code=4401, reason=BLOCKED_MESSAGE)
                else:
                    # Drop the cookie too, so the browser falls back to the sign-in page.
                    refused = JSONResponse({"detail": BLOCKED_MESSAGE}, status_code=401)
                    refused.delete_cookie("access_token", path="/")
                    refused.delete_cookie("token", path="/")
                    await refused(scope, receive, send)
                return
        await self.app(scope, receive, send)
