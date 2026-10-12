"""On a shared server, keep the features that run commands on this computer for admins.

Build Space, terminals, sandbox apps, kubectl and engine sign-ins all reach a
container or the Docker socket, which is root on the host. On a local install
everyone signed in is the owner, so nothing changes. On a shared one
(``HARVIS_EXPOSURE`` lan or tunnel) a non-admin gets a 403 that says why, for
HTTP and WebSocket alike, whichever auth dependency the route itself uses.

Paths not listed here are checked in code where the danger depends on the body:
stdio MCP servers (``require_build_space``) and chat turns that would launch a
workspace run (``owui_compat.workspace_bridge``).
"""
from __future__ import annotations

import re

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from owui_compat.authz import is_admin
from owui_compat.translate import _admin_user_ids

from .mode import build_space_open_to_all

ADMIN_ONLY_PREFIXES = (
    "/api/workspace/",
    "/api/harvis/exec",
    "/api/harvis/jobs",
    "/api/harvis/runs",
    "/api/harvis/terminal",
    "/api/tools/terminal/",
    "/api/vibecode/",
    "/api/vibecoding/",
    "/ws/vibecoding/",
    "/api/run-command",
    "/api/kubectl/",
    "/api/cad/",
    "/api/opencode/",
    "/api/openclaw/",
    "/api/remote/ssh/",
    "/api/owui/engine-auth/",
    "/api/owui/engine/",
    "/api/owui/openclaw/",
    "/hermes-api/api/terminal/",
    "/hermes-api/api/sandbox/",
    "/hermes-api/sandbox-app/",
)
# Adaptive spaces are a planning surface; only these steps run code.
# An artifact build runs npm in an executor pod; reading its status stays open.
_ADMIN_ONLY_RE = re.compile(
    r"^(/api/adaptive/spaces/[^/]+/(repo/|cad/execute|mock-execute)"
    r"|/api/artifacts/[^/]+/build(/stop)?$)")
# A non-admin's chat still starts runs that execute nothing (image generation),
# and the UI reads their results and the model list from /api/workspace. Each
# handler here only returns or stops the caller's own runs, so they stay open.
_OPEN_TO_USERS = (
    ({"GET", "HEAD"}, re.compile(
        r"^/api/workspace/(providers|history|artifacts|stream/[^/]+|status/[^/]+"
        r"|run/[^/]+/(events|artifacts)|artifact/[^/]+(/raw|/download)?)$")),
    ({"POST"}, re.compile(r"^/api/workspace/cancel/[^/]+$")),
    ({"GET", "HEAD"}, re.compile(r"^/api/artifacts/[^/]+/build$")),
)

MESSAGE = ("This server is shared, so running code on it (Build Space, terminals, "
           "CAD, engines) is for admins. Ask the admin if you need it.")


def admin_only_path(path: str) -> bool:
    # A prefix's bare form ("/api/tools/terminal") is the same route group.
    return (path.startswith(ADMIN_ONLY_PREFIXES)
            or any(path == p.rstrip("/") for p in ADMIN_ONLY_PREFIXES if p.endswith("/"))
            or bool(_ADMIN_ONLY_RE.match(path)))


def open_to_users(method, path: str) -> bool:
    return any(method in methods and rx.fullmatch(path) for methods, rx in _OPEN_TO_USERS)


def require_build_space(user, detail: str = MESSAGE) -> None:
    """For routes where the body decides the danger (a stdio MCP command)."""
    if not build_space_open_to_all() and not is_admin(user):
        raise HTTPException(status_code=403, detail=detail)


def build_space_allowed(user_id) -> bool:
    if build_space_open_to_all():
        return True
    try:
        return int(user_id) in _admin_user_ids()
    except (TypeError, ValueError):
        return False


class BuildSpaceGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] not in ("http", "websocket") or build_space_open_to_all()
                or not admin_only_path(scope.get("path") or "")
                or open_to_users(scope.get("method"), scope.get("path") or "")):
            await self.app(scope, receive, send)
            return
        from plugins.people.gate import _user_ids
        ids = _user_ids(scope)
        if ids and all(uid in _admin_user_ids() for uid in ids):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await WebSocket(scope, receive=receive, send=send).close(code=4403, reason="admins only")
            return
        status = 403 if ids else 401
        await JSONResponse({"detail": MESSAGE if ids else "Not signed in"}, status_code=status)(
            scope, receive, send)
