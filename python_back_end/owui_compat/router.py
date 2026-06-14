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
from .stubs import register_stub_routes
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
        # Auto-detect workspace tasks → launch a run + return a WorkspaceRunCard
        # marker (the OWUI card attaches to /api/workspace/stream/{id}). Falls
        # through to a normal chat completion when it's not a workspace task.
        from .workspace_bridge import maybe_handle_workspace

        ws = await maybe_handle_workspace(request, owui_body, user)
        if ws is not None:
            return ws
        return await run_chat_completion(request, owui_body, user_id=user.id)

    # ── workspace approval gate (P1.5, opt-in) — resolve a parked run ────────
    @router.post("/api/owui/workspace/{workspace_id}/approve")
    async def owui_ws_approve(workspace_id: str, request: Request, user=Depends(get_current_user)):
        from .workspace_bridge import resolve_workspace_approval

        return await resolve_workspace_approval(request, workspace_id, True)

    @router.post("/api/owui/workspace/{workspace_id}/deny")
    async def owui_ws_deny(workspace_id: str, request: Request, user=Depends(get_current_user)):
        from .workspace_bridge import resolve_workspace_approval

        return await resolve_workspace_approval(request, workspace_id, False)

    @router.post("/api/chat/completed")
    async def owui_chat_completed(request: Request, user=Depends(get_current_user)):
        return {}

    @router.post("/api/chat/actions/{action_id}")
    async def owui_chat_actions(action_id: str, request: Request, user=Depends(get_current_user)):
        return {}

    @router.post("/api/v1/tasks/title/completions")
    async def owui_title(request: Request, user=Depends(get_current_user)):
        # Trivial title from the conversation. OWUI sends `messages` as a STRING
        # (rendered conversation) for task-gen, but a list in some paths — handle
        # both, or a non-list/str would crash (str.get → 500).
        try:
            body = await request.json()
        except Exception:
            body = {}
        msgs = body.get("messages")
        text = ""
        if isinstance(msgs, str):
            text = msgs
        elif isinstance(msgs, list):
            for m in msgs:
                if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                    text = str(m["content"])
                    break
        title = " ".join(text.split()[:6]) or "New Chat"
        return {"choices": [{"message": {"content": title}}]}

    # Tag / follow-up / emoji / autocomplete task-gen. The facade has no
    # generation backend, but the OWUI frontend fires these after each response
    # (e.g. ResponseMessage → generateTags, per message). Without these the calls
    # 404 and the client throws "Not Found" (a lot of console noise + uncaught
    # rejections). Return empty, parseable completions so the client resolves.
    @router.post("/api/v1/tasks/tags/completions")
    async def owui_tags(request: Request, user=Depends(get_current_user)):
        return {"choices": [{"message": {"content": '{"tags": []}'}}]}

    @router.post("/api/v1/tasks/follow_ups/completions")
    async def owui_follow_ups(request: Request, user=Depends(get_current_user)):
        return {"choices": [{"message": {"content": '{"follow_ups": []}'}}]}

    @router.post("/api/v1/tasks/emoji/completions")
    async def owui_emoji(request: Request, user=Depends(get_current_user)):
        return {"choices": [{"message": {"content": ""}}]}

    @router.post("/api/v1/tasks/auto/completions")
    async def owui_auto_completion(request: Request, user=Depends(get_current_user)):
        return {"choices": [{"message": {"content": ""}}]}

    @router.post("/api/v1/tasks/queries/completions")
    async def owui_queries(request: Request, user=Depends(get_current_user)):
        return {"choices": [{"message": {"content": '{"queries": []}'}}]}

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

    # ── Folders = Projects ────────────────────────────────────────────────
    # A folder owns chats (owui_chats.folder_id) + project settings
    # (data.system_prompt = custom instructions, injected per chat). The
    # frontend folders API client (lib/apis/folders) defines this exact contract.
    @router.post("/api/v1/folders/")
    async def owui_folder_create(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        form = await request.json()
        return await persistence.create_folder(pool, user.id, form)

    @router.get("/api/v1/folders/")
    async def owui_folder_list(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.list_folders(pool, user.id)

    # chats-in-a-folder listing (declared before /chats/{chat_id}; static
    # 'folder' segment keeps it distinct from the parameterized chat route).
    @router.get("/api/v1/chats/folder/{folder_id}/list")
    async def owui_chats_in_folder_list(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.list_chats_by_folder(pool, user.id, folder_id)

    @router.get("/api/v1/chats/folder/{folder_id}")
    async def owui_chats_in_folder(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        return await persistence.list_chats_by_folder(pool, user.id, folder_id)

    @router.post("/api/v1/chats/{chat_id}/folder")
    async def owui_chat_set_folder(chat_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        chat = await persistence.update_chat_folder_id(pool, user.id, chat_id, body.get("folder_id"))
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat

    @router.get("/api/v1/folders/{folder_id}")
    async def owui_folder_get(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        folder = await persistence.get_folder(pool, user.id, folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.post("/api/v1/folders/{folder_id}/update")
    async def owui_folder_update(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        form = await request.json()
        folder = await persistence.update_folder(pool, user.id, folder_id, form)
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.post("/api/v1/folders/{folder_id}/update/expanded")
    async def owui_folder_expanded(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        folder = await persistence.update_folder_expanded(pool, user.id, folder_id, bool(body.get("is_expanded")))
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.post("/api/v1/folders/{folder_id}/update/parent")
    async def owui_folder_parent(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        folder = await persistence.update_folder_parent(pool, user.id, folder_id, body.get("parent_id"))
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.post("/api/v1/folders/{folder_id}/update/items")
    async def owui_folder_items(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        folder = await persistence.update_folder_items(pool, user.id, folder_id, body.get("items") or {})
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder

    @router.delete("/api/v1/folders/{folder_id}")
    async def owui_folder_delete(folder_id: str, request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        delete_contents = (request.query_params.get("delete_contents") or "").lower() == "true"
        return await persistence.delete_folder(pool, user.id, folder_id, delete_contents)

    # ── model comparison runs (Agent Studio Comparison surface → Analytics) ──
    @router.post("/api/owui/comparisons")
    async def owui_comparison_save(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        n = await persistence.save_comparison(
            pool, user.id,
            str(body.get("run_id") or ""),
            str(body.get("prompt") or ""),
            body.get("results") or [],
        )
        return {"saved": n}

    @router.post("/api/owui/comparisons/judge")
    async def owui_comparison_judge(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        body = await request.json()
        n = await persistence.save_comparison_judge(
            pool, user.id,
            str(body.get("run_id") or ""),
            str(body.get("judge_model") or ""),
            body.get("scores") or {},
        )
        return {"updated": n}

    @router.get("/api/owui/comparisons")
    async def owui_comparison_list(request: Request, user=Depends(get_current_user)):
        pool = _require_pool(request)
        try:
            limit = int(request.query_params.get("limit", 300))
        except (TypeError, ValueError):
            limit = 300
        runs = await persistence.list_comparisons(pool, user.id, limit=max(1, min(limit, 1000)))
        stats = await persistence.comparison_stats(pool, user.id)
        return {"runs": runs, "stats": stats}

    # Stub v1 routes (settings, tools, tags, profile images, …) — must be
    # registered before parameterized chat routes where paths overlap.
    register_stub_routes(router, get_current_user)

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
