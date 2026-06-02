"""No-op OWUI v1 endpoints the Harvis facade has not fully implemented yet.

Returning empty collections / default settings prevents the OWUI SPA from
getting stuck on 404s during layout boot and when re-opening a chat (tags,
tools, folders, profile images, etc.).
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

# Minimal settings blob OWUI expects (`settings.set(userSettings.ui)`).
DEFAULT_USER_SETTINGS: dict = {
    "ui": {},
    "version": 0,
}

# 1×1 transparent SVG — satisfies <img src=".../profile/image"> without 404 noise.
_PLACEHOLDER_AVATAR = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">'
    b'<rect width="32" height="32" fill="#334155" rx="6"/>'
    b"</svg>"
)


def register_stub_routes(router: APIRouter, get_current_user: Callable) -> None:
    """Attach stub routes to the OWUI facade router."""

    # ── user settings / profile ─────────────────────────────────────────────
    @router.get("/api/v1/users/user/settings")
    async def owui_user_settings(user=Depends(get_current_user)):
        return DEFAULT_USER_SETTINGS

    @router.post("/api/v1/users/user/settings/update")
    async def owui_user_settings_update(request: Request, user=Depends(get_current_user)):
        try:
            body = await request.json()
        except Exception:
            body = {}
        merged = {**DEFAULT_USER_SETTINGS, **body}
        if "ui" not in merged:
            merged["ui"] = {}
        return merged

    @router.get("/api/v1/users/{user_id}/profile/image")
    async def owui_user_profile_image(user_id: str):
        return Response(content=_PLACEHOLDER_AVATAR, media_type="image/svg+xml")

    # ── auth misc ───────────────────────────────────────────────────────────
    @router.post("/api/v1/auths/update/timezone")
    async def owui_update_timezone():
        return True

    # ── layout boot (folders, banners, tools) ───────────────────────────────
    @router.get("/api/v1/folders/")
    async def owui_folders_list(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/configs/banners")
    async def owui_banners(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/tools/")
    async def owui_tools_list(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/tools/list")
    async def owui_tools_list_alias(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/terminals/")
    async def owui_terminals_list(user=Depends(get_current_user)):
        return []

    # ── models (profile avatars in chat UI) ─────────────────────────────────
    @router.get("/api/v1/models/list")
    async def owui_models_list_v1(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/models/tags")
    async def owui_models_tags(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/models/base")
    async def owui_models_base_v1(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/models/model/profile/image")
    async def owui_model_profile_image():
        return Response(content=_PLACEHOLDER_AVATAR, media_type="image/svg+xml")

    # ── chat tags (re-open chat path) ───────────────────────────────────────
    @router.get("/api/v1/chats/{chat_id}/tags")
    async def owui_chat_tags_get(chat_id: str, user=Depends(get_current_user)):
        return []

    @router.post("/api/v1/chats/{chat_id}/tags")
    async def owui_chat_tags_add(chat_id: str, user=Depends(get_current_user)):
        return []

    @router.delete("/api/v1/chats/{chat_id}/tags")
    async def owui_chat_tags_delete(chat_id: str, user=Depends(get_current_user)):
        return True

    @router.get("/api/v1/chats/{chat_id}/tags/all")
    async def owui_chat_tags_all(chat_id: str, user=Depends(get_current_user)):
        return []

    # ── optional task helpers (avoid console noise) ─────────────────────────
    @router.get("/api/v1/tasks/")
    async def owui_tasks_list(user=Depends(get_current_user)):
        return []

    @router.get("/api/v1/chats/{chat_id}/tasks")
    async def owui_chat_tasks(chat_id: str, user=Depends(get_current_user)):
        return {"task_ids": []}

    # Functions list — Chat boot fires getFunctions() inside a reactive effect
    # with NO .catch, so a 404 became an UNCAUGHT "Not Found" (and likely wedged
    # the new-chat flow). Empty list = no custom functions.
    @router.get("/api/v1/functions/")
    async def owui_functions_list(user=Depends(get_current_user)):
        return []

    # Active-task tracking. The facade runs no background task queue, so report
    # none active. Sidebar.checkActiveChats reads `active_chat_ids`;
    # Chat.getTaskIdsByChatId reads `task_ids`. Note: /api/tasks (no /v1).
    @router.post("/api/v1/tasks/active/chats")
    async def owui_tasks_active_chats(request: Request, user=Depends(get_current_user)):
        return {"active_chat_ids": []}

    @router.get("/api/tasks/chat/{chat_id}")
    async def owui_tasks_chat_by_id(chat_id: str, user=Depends(get_current_user)):
        return {"task_ids": []}
