"""``GET /api/exposure`` — admin only: mode, switches and any startup problem.

The tunnel's own check (``/api/tunnel/verify``) lives in ``plugins.tunnel``.
"""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends

from .mode import describe


def create_exposure_router(*, get_current_user: Callable, require_admin: Callable) -> APIRouter:
    router = APIRouter(tags=["exposure"])

    @router.get("/api/exposure")
    async def exposure_card(_admin=Depends(require_admin)):
        return describe()

    return router
