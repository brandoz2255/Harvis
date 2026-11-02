"""Same-site check for WebSockets that authenticate from the ambient cookie.

A page on another localhost port (a sandbox preview) is same-site with the Harvis
page, so SameSite cookies do not stop it opening one of these sockets as the
signed-in user. Browsers always send Origin on a WebSocket handshake; accept only
this host, the nginx front door, and operator-listed origins. No Origin means a
non-browser client.
"""
from __future__ import annotations

import os

from fastapi import WebSocket

TRUSTED_NETLOCS = {"localhost:9000", "127.0.0.1:9000"} | {
    o.strip().split("://", 1)[-1]
    for o in os.getenv("HARVIS_EXTRA_ORIGINS", "").split(",")
    if o.strip()
}


def origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True
    netloc = origin.split("://", 1)[-1].rstrip("/")
    return netloc == ws.headers.get("host", "") or netloc in TRUSTED_NETLOCS
