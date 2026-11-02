"""Refuse every request and socket carrying a turned-off, waiting or deleted account's sign-in.

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

from auth_optimized import decode_token_fast, predates_revocation, revoked, session_cutoff

from .approval import GONE_MESSAGE, PENDING_MESSAGE, is_gone, is_pending
from .controls import BLOCKED_MESSAGE, is_blocked

SESSION_ENDED_MESSAGE = "This sign-in has ended. Sign in again."

_OPEN_PATHS = frozenset({
    "/api/v1/auths/signin", "/api/v1/auths/signup", "/api/v1/auths/signout",
    "/api/auth/login", "/api/auth/signup", "/api/auth/logout",
})

# All a person in the waiting room may reach: the session probe (which reports
# role "pending", so the app shows the waiting room), the public config the
# sign-in screen reads, the public legal text it links, and the session check nginx
# asks before its own paths (which answers 401 for them). Everything else, HTTP or
# socket, is refused.
_WAITING_ROOM_GET = frozenset({"/api/v1/auths/", "/api/config", "/api/legal", "/api/session/check"})


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


def _inspect(scope: Scope) -> tuple[list[dict], bool]:
    """The claims of every sign-in the request carries that is signed, unexpired and
    allowed on this path (a scoped sidecar token only on its own MCP endpoint), and
    whether any other was signed but predates revocation (no issue time, shared
    server). That one has no id to check, yet some routes decode the signature alone,
    so it must end the request here, not pass as "no sign-in"."""
    path = scope.get("path") or ""
    found = []
    legacy = False
    for token in _tokens(scope):
        payload = decode_token_fast(token, path=path)
        if payload and payload.get("sub") is not None:
            found.append(payload)
        elif not payload and predates_revocation(token):
            legacy = True
    return found, legacy


def _payloads(scope: Scope) -> list[dict]:
    return _inspect(scope)[0]


def _user_ids(scope: Scope) -> set[int]:
    ids: set[int] = set()
    for payload in _payloads(scope):
        try:
            ids.add(int(payload["sub"]))
        except (TypeError, ValueError):
            continue
    return ids


async def live_user_ids(scope: Scope, pool) -> tuple[set[int], bool]:
    """Ids of the sign-ins that still count, and whether any was ended server-side
    (password changed, account turned off, "sign out everywhere")."""
    ids: set[int] = set()
    payloads, ended = _inspect(scope)
    for payload in payloads:
        try:
            uid = int(payload["sub"])
        except (TypeError, ValueError):
            continue
        if revoked(payload, await session_cutoff(pool, uid)):
            ended = True
        else:
            ids.add(uid)
    return ids, ended


class BlockedAccountGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or scope.get("path") in _OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        app = scope.get("app")
        pool = getattr(getattr(app, "state", None), "pg_pool", None)
        ids, ended = await live_user_ids(scope, pool)
        if ended and not _waiting_room_path(scope):
            # The sign-in page's own probes (session, config) pass so it can still load.
            await _sign_out(scope, receive, send, SESSION_ENDED_MESSAGE)
            return
        for uid in ids:
            if await is_blocked(pool, uid):
                await _sign_out(scope, receive, send, BLOCKED_MESSAGE)
                return
            # A turned-away or forgotten sign-up: its token is still signed, and
            # some routes only check the signature. The waiting-room paths answer
            # it themselves (401 / public config), so the sign-in page still loads.
            if await is_gone(pool, uid) and not _waiting_room_path(scope):
                await _sign_out(scope, receive, send, GONE_MESSAGE)
                return
            if await is_pending(pool, uid) and not _waiting_room_path(scope):
                if scope["type"] == "websocket":
                    await WebSocket(scope, receive=receive, send=send).close(code=4403, reason=PENDING_MESSAGE)
                else:
                    # Keep the cookie: the waiting room polls with it and opens
                    # the app as soon as the host approves.
                    await JSONResponse({"detail": PENDING_MESSAGE, "pending": True},
                                       status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def _sign_out(scope: Scope, receive: Receive, send: Send, message: str) -> None:
    if scope["type"] == "websocket":
        await WebSocket(scope, receive=receive, send=send).close(code=4401, reason=message)
        return
    # Drop the cookie too, so the browser falls back to the sign-in page.
    refused = JSONResponse({"detail": message}, status_code=401)
    refused.delete_cookie("access_token", path="/")
    refused.delete_cookie("token", path="/")
    await refused(scope, receive, send)


def _waiting_room_path(scope: Scope) -> bool:
    return (scope["type"] == "http" and scope.get("method") in ("GET", "HEAD")
            and scope.get("path") in _WAITING_ROOM_GET)
