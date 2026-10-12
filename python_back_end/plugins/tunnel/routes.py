"""``GET /api/tunnel/verify`` — nginx's tunnel listener asks this before every
request (``auth_request``). 204 lets it through, 403 stops it. With no
Cloudflare Access configured, every tunnel request is stopped. Registered only
while the tunnel is on; otherwise nginx gets a 404 here and refuses too.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response

from . import access


def create_tunnel_router() -> APIRouter:
    router = APIRouter(tags=["tunnel"])

    @router.get("/api/tunnel/verify", include_in_schema=False)
    async def tunnel_verify(request: Request):
        claims = await access.request_identity(request.headers)
        if claims is None:
            return Response(status_code=403)
        return Response(status_code=204, headers={"X-Harvis-Access-Email": access.email_of(claims)})

    return router
