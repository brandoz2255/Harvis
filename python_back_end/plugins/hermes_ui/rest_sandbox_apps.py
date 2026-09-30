"""Serve an app running inside a chat's sandbox: ``/hermes-api/sandbox-app/<cap>/<port>/…``.

When Harvis installs something in a chat's sandbox (a repo, ComfyUI, Pinokio's
server…) and starts it on a port, this proxies that port to the browser over
HTTP and WebSocket. The backend reaches the runner by name on the
``repo-sandbox`` network; nothing is published on the host.

The app is untrusted code, so it must never act as the signed-in user:

* Every response carries ``Content-Security-Policy: sandbox …`` WITHOUT
  ``allow-same-origin``. The browser then runs the page on an opaque origin: its
  scripts can't read Harvis's storage, and its requests to Harvis are
  cross-site, so the SameSite=Lax ``access_token`` cookie is never attached.
  That is also why auth here is not the cookie: ``<cap>`` is a capability
  signed with the sandbox's own secret (sandbox.app_prefix / verify_cap), which
  dies when the sandbox is deleted.
* Requests go out with no Cookie / Authorization; responses lose Set-Cookie and
  frame-blocking headers so the app can show in the right panel.

Cost of the opaque origin: apps that insist on localStorage or cookies of their
own may misbehave. That trade is deliberate — the alternative hands the app the
user's account.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.websockets import WebSocketDisconnect

from . import sandbox

log = logging.getLogger("hermes_ui.sandbox_apps")

router = APIRouter(tags=["hermes-ui"])

CSP = ("sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox "
       "allow-modals allow-downloads allow-pointer-lock")
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
        "transfer-encoding", "upgrade", "host", "content-length"}
_DROP_REQ = _HOP | {"cookie", "authorization", "x-forwarded-for", "x-real-ip", "origin", "referer"}
_DROP_RESP = _HOP | {"set-cookie", "x-frame-options", "content-security-policy-report-only",
                     "strict-transport-security", "content-encoding"}
_BLOCKED_PORTS = {22}
_client: Optional[httpx.AsyncClient] = None


def _target(cap: str, port: int) -> str:
    who = sandbox.verify_cap(cap)
    if who is None or not (1024 <= port <= 65535) or port in _BLOCKED_PORTS:
        raise HTTPException(404, "not found")  # one answer for bad links and bad ports
    uid, sid = who
    return f"{sandbox.container_name(uid, sid)}:{port}"


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # No redirects followed: the app's own redirects go back to the browser, which
        # stays inside the proxy prefix for relative Locations.
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0), follow_redirects=False)
    return _client


@router.api_route(f"{sandbox.APP_PREFIX}/{{cap}}/{{port}}", methods=["GET", "HEAD"])
async def app_root(cap: str, port: int):
    _target(cap, port)
    # Relative asset paths only resolve under the port "folder" with a trailing slash.
    return RedirectResponse(f"{sandbox.APP_PREFIX}/{cap}/{port}/", status_code=307)


@router.api_route(f"{sandbox.APP_PREFIX}/{{cap}}/{{port}}/{{path:path}}",
                  methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def app_http(cap: str, port: int, path: str, request: Request):
    host = _target(cap, port)
    url = f"http://{host}/{path}"
    if request.url.query:
        url += "?" + request.url.query
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQ}
    headers["accept-encoding"] = "identity"  # stream bytes through untouched
    try:
        upstream = await _http().send(
            _http().build_request(request.method, url, headers=headers,
                                  content=None if request.method in ("GET", "HEAD") else request.stream()),
            stream=True)
    except httpx.HTTPError:
        raise HTTPException(502, f"Nothing is answering on port {port} in this sandbox yet.")
    out = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESP}
    out["content-security-policy"] = CSP
    out["x-content-type-options"] = "nosniff"
    out["referrer-policy"] = "no-referrer"
    return StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code, headers=out,
                             background=BackgroundTask(upstream.aclose))


@router.websocket(f"{sandbox.APP_PREFIX}/{{cap}}/{{port}}/{{path:path}}")
async def app_ws(ws: WebSocket, cap: str, port: int, path: str):
    try:
        host = _target(cap, port)
    except HTTPException:
        await ws.close(code=4404)
        return
    import websockets

    url = f"ws://{host}/{path}" + (f"?{ws.url.query}" if ws.url.query else "")
    protocols = [p.strip() for p in (ws.headers.get("sec-websocket-protocol") or "").split(",") if p.strip()]
    try:
        upstream = await websockets.connect(url, subprotocols=protocols or None, max_size=None,
                                            open_timeout=10)
    except Exception:  # noqa: BLE001
        await ws.close(code=1011)
        return
    await ws.accept(subprotocol=upstream.subprotocol)

    async def down() -> None:
        async for msg in upstream:
            if isinstance(msg, bytes):
                await ws.send_bytes(msg)
            else:
                await ws.send_text(msg)

    async def up() -> None:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                await upstream.send(msg["bytes"])
            elif msg.get("text") is not None:
                await upstream.send(msg["text"])

    tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await upstream.close()
        try:
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
