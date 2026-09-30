"""GET /api/capabilities/hosting — which runtime Harvis is on, and what that means.

Built by a factory like the setup router so it takes main.py's ``get_current_user``
and not a second auth dependency: the Notebooks capability next to it is what the
settings page already calls, and the two must gate identically.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from .detect import describe_hosting


def create_hosting_router(*, get_current_user: Callable) -> APIRouter:
    router = APIRouter(tags=["capabilities"])

    @router.get("/api/capabilities/hosting")
    async def capability_hosting(_user=Depends(get_current_user)):
        """Any signed-in user: the hosting card is an ordinary settings surface.

        Nothing privileged is exposed — node names and sizes, an env-derived
        mode, and the documented installer commands. The node listing can block
        for up to 3 s on a cold cache, so it runs off the event loop.
        """
        return await run_in_threadpool(describe_hosting)

    return router
