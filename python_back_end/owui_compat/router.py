"""OpenWebUI-compatibility facade router.

Speaks OpenWebUI's HTTP contract and translates to Harvis-native logic
in-process. Built as a factory (``create_owui_router``) that receives the Harvis
callables it reuses (dependency injection), so this package never imports
``main`` — avoiding circular imports and keeping it unit-testable.

All routes are ADDITIVE (new paths Harvis didn't expose) except ``GET
/api/models``, which the facade owns in OWUI shape (Harvis's native ``{models:
[...]}`` route was moved to ``/api/models/native`` in main.py). Register the
router via ``app.include_router(create_owui_router(deps))`` AFTER main.py's auth
helpers are defined.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt

from . import config as owui_config
from . import persistence
from .chat_completion import run_chat_completion
from .schemas import (
    OwuiChatNewBody,
    OwuiChatUpdateBody,
    OwuiSigninBody,
    OwuiSignupBody,
)
from .translate import harvis_models_to_owui, harvis_user_to_owui

logger = logging.getLogger(__name__)


@dataclass
class OwuiDeps:
    """Harvis callables/constants the facade reuses (injected by main.py)."""

    get_current_user: Callable          # FastAPI dependency → UserResponse
    list_models: Callable               # async (request, user) → {"models": [...]}
    signup_with_connection: Callable    # async (SignupRequest, conn) → TokenResponse
    signup_request_cls: type            # main.SignupRequest
    verify_password: Callable           # (plain, hashed) → bool
    create_access_token: Callable       # (data, expires_delta) → jwt str
    access_token_expire_minutes: int
    secret_key: str
    algorithm: str


def _now() -> int:
    return int(time.time())


def create_owui_router(deps: OwuiDeps) -> APIRouter:
    router = APIRouter()
    get_current_user = deps.get_current_user

    def _require_pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=500, detail="Database unavailable")
        return pool

    def _login_cookie(resp: JSONResponse, token: str) -> JSONResponse:
        resp.set_cookie(
            "access_token", token, httponly=True, samesite="lax", secure=False
        )
        return resp

    # ── boot ──────────────────────────────────────────────────────────────
    @router.get("/api/config")
    async def owui_get_config():
        return owui_config.build_config()

    @router.get("/api/version")
    async def owui_version():
        return {"version": owui_config.HARVIS_OWUI_VERSION}

    # ── auth ──────────────────────────────────────────────────────────────
    @router.post("/api/v1/auths/signin")
    async def owui_signin(payload: OwuiSigninBody, request: Request):
        pool = _require_pool(request)
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT id, username, email, avatar, password FROM users WHERE email = $1",
                payload.email,
            )
        if not user or not deps.verify_password(payload.password, user["password"]):
            raise HTTPException(status_code=401, detail="Incorrect email or password")
        token = deps.create_access_token(
            {"sub": str(user["id"])},
            expires_delta=timedelta(minutes=deps.access_token_expire_minutes),
        )
        owui_user = harvis_user_to_owui(
            dict(user), token, expires_at=_now() + deps.access_token_expire_minutes * 60
        )
        return _login_cookie(JSONResponse(content=owui_user), token)

    @router.post("/api/v1/auths/signup")
    async def owui_signup(payload: OwuiSignupBody, request: Request):
        pool = _require_pool(request)
        signup_req = deps.signup_request_cls(
            username=payload.name, email=payload.email, password=payload.password
        )
        async with pool.acquire() as conn:
            token_resp = await deps.signup_with_connection(signup_req, conn)
            user = await conn.fetchrow(
                "SELECT id, username, email, avatar FROM users WHERE email = $1",
                payload.email,
            )
        token = token_resp.access_token
        owui_user = harvis_user_to_owui(
            dict(user), token, expires_at=_now() + deps.access_token_expire_minutes * 60
        )
        return _login_cookie(JSONResponse(content=owui_user), token)

    @router.get("/api/v1/auths/")
    async def owui_session(request: Request, user=Depends(get_current_user)):
        # Echo the real token + its exp so OWUI's 15s expiry poll is accurate.
        token = request.cookies.get("access_token")
        if token is None:
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if auth and auth.startswith("Bearer "):
                token = auth[len("Bearer ") :]
        expires_at = None
        if token:
            try:
                claims = jwt.decode(token, deps.secret_key, algorithms=[deps.algorithm])
                expires_at = claims.get("exp")
            except JWTError:
                expires_at = None
        return harvis_user_to_owui(
            {"id": user.id, "username": user.username, "email": user.email, "avatar": user.avatar},
            token or "",
            expires_at=expires_at or (_now() + deps.access_token_expire_minutes * 60),
        )

    @router.post("/api/v1/auths/signout")
    async def owui_signout():
        resp = JSONResponse(content={})
        resp.delete_cookie("access_token")
        return resp

    # ── models ────────────────────────────────────────────────────────────
    async def _owui_models(request: Request, user):
        native = await deps.list_models(request, user)
        return {"data": harvis_models_to_owui(native)}

    @router.get("/api/models")
    async def owui_models(request: Request, user=Depends(get_current_user)):
        return await _owui_models(request, user)

    @router.get("/api/models/base")
    async def owui_models_base(request: Request, user=Depends(get_current_user)):
        return await _owui_models(request, user)

    # ── chat completions ────────────────────────────────────────────────────
    @router.post("/api/chat/completions")
    async def owui_chat_completions(request: Request, user=Depends(get_current_user)):
        owui_body = await request.json()
        return await run_chat_completion(request, owui_body)

    @router.post("/api/chat/completed")
    async def owui_chat_completed(request: Request, user=Depends(get_current_user)):
        return {}

    @router.post("/api/chat/actions/{action_id}")
    async def owui_chat_actions(action_id: str, request: Request, user=Depends(get_current_user)):
        return {}

    @router.post("/api/v1/tasks/title/completions")
    async def owui_title(request: Request, user=Depends(get_current_user)):
        # Trivial title from the first user message; avoids a console 404.
        try:
            body = await request.json()
        except Exception:
            body = {}
        title = "New Chat"
        for m in body.get("messages") or []:
            if m.get("role") == "user" and m.get("content"):
                words = str(m["content"]).split()
                title = " ".join(words[:6]) or "New Chat"
                break
        return {"choices": [{"message": {"content": title}}]}

    # ── chat persistence ──────────────────────────────────────────────────
    # NOTE: static sub-paths declared BEFORE /{chat_id} so they aren't captured.
    @router.post("/api/v1/chats/new")
    async def owui_chat_new(payload: OwuiChatNewBody, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.create_chat(pool, user.id, payload.chat, payload.folder_id)

    @router.get("/api/v1/chats/")
    async def owui_chat_list(request: Request, user=Depends(get_current_user), page: int = 1):
        pool = _require_pool(request)
        page = max(1, page)
        return await persistence.list_chats(pool, user.id, limit=60, offset=(page - 1) * 60)

    @router.get("/api/v1/chats/all/tags")
    async def owui_chat_all_tags(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/chats/pinned")
    async def owui_chat_pinned(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/chats/archived")
    async def owui_chat_archived(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/chats/{chat_id}")
    async def owui_chat_get(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        chat = await persistence.get_chat(pool, user.id, chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat

    @router.post("/api/v1/chats/{chat_id}")
    async def owui_chat_update(
        chat_id: str, payload: OwuiChatUpdateBody, request: Request, user=Depends(get_current_user)
    ):
        pool = _require_pool(request)
        chat = await persistence.update_chat(pool, user.id, chat_id, payload.chat)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat

    @router.delete("/api/v1/chats/{chat_id}")
    async def owui_chat_delete(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        await persistence.delete_chat(pool, user.id, chat_id)
        return True

    return router
