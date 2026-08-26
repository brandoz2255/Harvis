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

# Two avatars, because they answer two different questions.
#
# Both used to be one 32x32 slate rectangle, which was fine while nothing but a
# 20px <img> asked for it. The voice call overlay then started drawing the model
# avatar as its speech orb — a `rounded-full bg-cover` div that grows to 13rem
# while the assistant talks (CallOverlay.svelte). A 32px flat rectangle blown up
# to 208px and clipped to a circle is a featureless grey disc, which is exactly
# what the orb looked like.
#
# Both are square and full-bleed on purpose: the consumer clips them to a circle,
# so any corner the artwork leaves unpainted becomes a notch.

# The model's face. Geometry and palette come from static/harvis-logo.svg — the
# robot's screen and its three glowing features — cropped to just the head so it
# still reads at 48px. It paints its own near-black ground, which is why the
# lighter #6FA0FF is correct here: same rule the logo file states, that blue is
# only ever drawn on the robot's own screen, never on the page.
_MODEL_AVATAR = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 64 64">'
    b"<defs>"
    b'<radialGradient id="hvOrb" cx="50%" cy="38%" r="72%">'
    b'<stop offset="0%" stop-color="#22386E"/>'
    b'<stop offset="60%" stop-color="#12203F"/>'
    b'<stop offset="100%" stop-color="#0D152A"/>'
    b"</radialGradient>"
    b'<filter id="hvGlow" x="-50%" y="-50%" width="200%" height="200%">'
    b'<feGaussianBlur stdDeviation="1.1" result="b"/>'
    b'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
    b"</filter>"
    b"</defs>"
    b'<rect width="64" height="64" fill="url(#hvOrb)"/>'
    b'<circle cx="32" cy="32" r="29" fill="none" stroke="#3B76E0" stroke-width="1.5" opacity="0.55"/>'
    b'<g stroke="#6FA0FF" stroke-linecap="round" fill="none" filter="url(#hvGlow)">'
    b'<path d="M20 28 Q24 22 28 28" stroke-width="3.4"/>'
    b'<path d="M36 28 Q40 22 44 28" stroke-width="3.4"/>'
    b'<path d="M24 39 Q32 46 40 39" stroke-width="2.8"/>'
    b"</g>"
    b"</svg>"
)

# A person we have no picture of. Deliberately NOT the Harvis mark: this answers
# "who is this user", and stamping the assistant's face on every account would
# be a worse lie than a blank tile. Neutral slate reads on either theme.
_PLACEHOLDER_AVATAR = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 64 64">'
    b'<rect width="64" height="64" fill="#334155"/>'
    b'<circle cx="32" cy="25" r="11" fill="#94A3B8"/>'
    b'<path d="M11 60a21 21 0 0 1 42 0z" fill="#94A3B8"/>'
    b"</svg>"
)


def register_stub_routes(router: APIRouter, get_current_user: Callable) -> None:
    """Attach stub routes to the OWUI facade router."""

    # ── user settings: now REAL persisted endpoints in user_settings.py ──
    # ── profile image ───────────────────────────────────────────────────────
    @router.get("/api/v1/users/{user_id}/profile/image")
    async def owui_user_profile_image(user_id: str):
        return Response(content=_PLACEHOLDER_AVATAR, media_type="image/svg+xml")

    # ── auth misc ───────────────────────────────────────────────────────────
    @router.post("/api/v1/auths/update/timezone")
    async def owui_update_timezone():
        return True

    # ── layout boot (banners, tools) ─────────────────────────────────────────
    # NOTE: /api/v1/folders/ is now served for real by the facade router
    # (Projects feature) — no longer stubbed here.
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
        # Also the voice call overlay's speech orb — see _MODEL_AVATAR.
        return Response(content=_MODEL_AVATAR, media_type="image/svg+xml")

    # ── chat tags: now REAL endpoints in router.py (persist to owui_chats.tags) ──

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

    # ── skills: now REAL endpoints in skills.py (owui_skills table + CRUD) ──
    # The Customize area (Agent Studio) creates/edits user skills; the Brain
    # panel + composer list them via getSkills() → /api/v1/skills/.
