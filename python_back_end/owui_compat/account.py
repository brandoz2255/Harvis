"""Account self-service for the OWUI facade.

Settings → Account carries a "Change Password" form that posts to
``POST /api/v1/auths/update/password``. The facade never implemented it, so the
frontend shipped a hard-coded ``PASSWORD_CHANGE_AVAILABLE = false`` gate rather
than a button that 404s. This module is the route that gate was waiting on: a
self-hosted install where nobody can rotate their own password is not a finished
install.

Hashing is done here with the same passlib bcrypt scheme main.py configures
(``CryptContext(schemes=["bcrypt"])``), so hashes written by this route verify
against main.py's ``verify_password`` and vice versa. It is duplicated rather
than injected because this package deliberately never imports ``main``.

Scope is password only. Name / avatar / bio live behind
``POST /api/v1/auths/update/profile``, which needs schema work first —
``users.username`` is UNIQUE and ``users.avatar`` is VARCHAR(255), too small for
the data-URI images the Account pane produces.
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from passlib.context import CryptContext
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Same scheme + defaults as main.py:161. Keep in sync.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

MIN_PASSWORD_LENGTH = 8


class OwuiPasswordUpdateBody(BaseModel):
    password: str
    new_password: str


def register_account_routes(
    router: APIRouter, get_current_user: Callable, verify_password: Callable
) -> None:
    """Attach account self-service routes to the OWUI facade router."""

    @router.post("/api/v1/auths/update/password")
    async def owui_update_password(
        payload: OwuiPasswordUpdateBody, request: Request, user=Depends(get_current_user)
    ):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=500, detail="Database unavailable")

        new_password = payload.new_password or ""
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters.",
            )

        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT password FROM users WHERE id = $1", user.id)
            if row is None:
                raise HTTPException(status_code=404, detail="User not found")
            # Wrong current password is a 400, not a 401: the caller's token is
            # valid, so a 401 would make the SPA log them out mid-form.
            if not verify_password(payload.password or "", row["password"]):
                raise HTTPException(status_code=400, detail="Current password is incorrect")
            await conn.execute(
                "UPDATE users SET password = $1 WHERE id = $2",
                _pwd_context.hash(new_password),
                user.id,
            )

        # Existing tokens stay valid — they carry only `sub` and `exp`, and
        # revoking them would need a token store this deployment doesn't have.
        logger.info("owui: password changed for user id=%s", user.id)
        return True
