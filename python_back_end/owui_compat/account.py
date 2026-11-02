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

``POST /api/v1/auths/update/profile`` lives here too, and needed schema work
first: three of the five fields the Account pane posts had no column at all, and
``users.avatar`` was VARCHAR(255) — smaller than any data-URI image that pane
produces. Migration 017 adds ``name``/``bio``/``gender``/``date_of_birth`` and
widens ``avatar``. The display name is the new ``name`` column and deliberately
NOT ``username``: ``username`` is UNIQUE and is the login identity, so writing a
display name to it would stop two people sharing a first name and would silently
change what they sign in with.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date as _date
from datetime import timedelta
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from pydantic import BaseModel

# Neither imports main, so this package still never does.
from auth_optimized import _read_cutoff, mint_token, note_cutoff
from jwt_secret import access_token_minutes, min_password_length

from .translate import harvis_user_to_owui

logger = logging.getLogger(__name__)

# Same scheme + defaults as main.py:161. Keep in sync.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")



class OwuiPasswordUpdateBody(BaseModel):
    password: str
    new_password: str


class OwuiProfileUpdateBody(BaseModel):
    name: str | None = None
    profile_image_url: str | None = None
    bio: str | None = None
    gender: str | None = None
    date_of_birth: str | None = None


# Caps exist so one account cannot put an arbitrarily large blob in a row that
# get_current_user reads on every authenticated request. The avatar limit is
# generous because the pane sends a cropped image as a data URI; the frontend
# already compresses, this is the backstop.
MAX_NAME_LENGTH = 255
MAX_BIO_LENGTH = 4096
MAX_GENDER_LENGTH = 100
MAX_AVATAR_LENGTH = 1_048_576


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

        # The same minimum as sign-up: 6 on a laptop, 12 on a shared server.
        new_password = payload.new_password or ""
        min_length = min_password_length()
        if len(new_password) < min_length:
            raise HTTPException(
                status_code=400,
                detail=f"New password must be at least {min_length} characters.",
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
            # A trigger (migration 027) just set users.tokens_valid_after: every sign-in
            # minted before now, on any device, has ended. Read it back so this
            # process applies it at once and the cookie below is minted after it.
            cutoff = await _read_cutoff(conn, user.id)
        note_cutoff(user.id, cutoff)

        # The person who changed it stays signed in: a fresh token, issued after the
        # cutoff, replaces their cookie. Every other session is gone.
        token = mint_token(
            {"sub": str(user.id)},
            timedelta(minutes=access_token_minutes()),
            iat=max(time.time(), cutoff or 0.0),
        )
        response = JSONResponse(content=True)
        # Same cookie flags as the sign-in routes (HARVIS_COOKIE_SECURE, or HTTPS at the proxy).
        secure = os.getenv("HARVIS_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"} or (
            (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower() == "https"
        )
        response.set_cookie("access_token", token, httponly=True, samesite="lax", secure=secure)
        logger.info("owui: password changed for user id=%s; other sessions ended", user.id)
        return response

    @router.post("/api/v1/auths/update/profile")
    async def owui_update_profile(
        payload: OwuiProfileUpdateBody, request: Request, user=Depends(get_current_user)
    ):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=500, detail="Database unavailable")

        def _clean(value: str | None, limit: int, label: str) -> str | None:
            """Empty string means "cleared" and is stored as NULL, not ''.

            The Account pane sends '' for every field the user has not filled in,
            so treating '' as a value would write blanks over a name the user
            never touched.
            """
            if value is None:
                return None
            text = value.strip()
            if not text:
                return None
            if len(text) > limit:
                raise HTTPException(
                    status_code=400, detail=f"{label} must be {limit} characters or fewer."
                )
            return text

        name = _clean(payload.name, MAX_NAME_LENGTH, "Name")
        bio = _clean(payload.bio, MAX_BIO_LENGTH, "Bio")
        gender = _clean(payload.gender, MAX_GENDER_LENGTH, "Gender")
        avatar = _clean(payload.profile_image_url, MAX_AVATAR_LENGTH, "Profile image")

        # The pane's default avatar is the served favicon, not an upload. Storing
        # it would pin the user to today's favicon path forever; NULL lets
        # harvis_user_to_owui keep resolving the default at read time.
        if avatar == "/static/favicon.png":
            avatar = None

        dob_raw = (payload.date_of_birth or "").strip()
        dob: _date | None = None
        if dob_raw:
            try:
                dob = _date.fromisoformat(dob_raw)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Date of birth must be in YYYY-MM-DD format."
                )

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE users
                   SET name = $1, bio = $2, gender = $3, date_of_birth = $4, avatar = $5
                 WHERE id = $6
             RETURNING id, username, email, avatar, name, bio, gender, date_of_birth
                """,
                name,
                bio,
                gender,
                dob,
                avatar,
                user.id,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="User not found")

        logger.info("owui: profile updated for user id=%s", user.id)
        return harvis_user_to_owui(dict(row))
