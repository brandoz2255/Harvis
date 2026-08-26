"""Pure translation between Harvis-native shapes and OpenWebUI shapes.

No I/O, no FastAPI — just dict-in/dict-out so these are trivially unit-testable.
"""

from __future__ import annotations

import os
from typing import Optional

# OWUI sends a fat OpenAI body carrying many orchestration fields the upstream
# model providers don't understand. model_proxy ignores unknown keys (it only
# ``.get()``s what it needs), but we strip the OWUI-only fields anyway to keep
# upstream payloads clean and predictable.
_OWUI_ONLY_FIELDS = {
    "tool_ids",
    "skill_ids",
    "filter_ids",
    "terminal_id",
    "tool_servers",
    "features",
    "variables",
    "model_item",
    "session_id",
    "chat_id",
    "folder_id",
    "id",
    "message_ids",
    "parent_id",
    "user_message",
    "regeneration_prompt",
    "assistant_message_id",
    "background_tasks",
    "effort",  # Phase F: cloud-chat reasoning effort — consumed by the cloud proxy, never the native router
}

# Generation params OWUI nests under `params`; model_proxy / upstreams read them
# at top level, so flatten these specific keys up if present.
_FLATTEN_PARAMS = (
    "temperature",
    "top_p",
    "top_k",
    "max_tokens",
    "stop",
    "frequency_penalty",
    "presence_penalty",
    "seed",
)


# Admin id persisted in instance_settings (the user who claimed the instance).
# Loaded by main.py's startup-ensure block; extended live on first signup.
_persisted_admin_ids: set[int] = set()


def add_persisted_admin_id(uid: int) -> None:
    _persisted_admin_ids.add(uid)


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _admin_user_ids() -> set[int]:
    """User ids treated as OWUI ``admin`` (default: the first registrant)."""
    raw = os.getenv("HARVIS_OWUI_ADMIN_USER_IDS", "1")
    ids: set[int] = set(_persisted_admin_ids)
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def _default_permissions(role: str) -> dict:
    """Minimal v1 permission matrix OWUI reads to gate its UI. Chat is allowed;
    workspace/admin features the facade does not back are disabled."""
    is_admin = role == "admin"
    return {
        "workspace": {
            "models": is_admin,
            "knowledge": False,
            "prompts": False,
            "tools": False,
        },
        "sharing": {
            "public_models": False,
            "public_knowledge": False,
            "public_prompts": False,
            "public_tools": False,
        },
        "chat": {
            "controls": True,
            # S3/S4: attachment upload + server STT/TTS are wired in the facade
            # (POST /api/v1/files/, /api/v1/audio/{transcriptions,speech}).
            "file_upload": True,
            "delete": True,
            "edit": True,
            "temporary": True,
            "stt": True,
            "tts": True,
        },
        "features": {
            # Web search is gated TWICE — config.features.enable_web_search AND this
            # per-user permission. Leaving this False kept the toggle hidden for every
            # non-admin even with the server flag on. Searching the public web is not a
            # privileged action here, so it follows the server flag; set
            # HARVIS_OWUI_WEB_SEARCH=false to turn it off for everyone.
            "web_search": _env_bool("HARVIS_OWUI_WEB_SEARCH", True),
            "image_generation": False,
            "code_interpreter": False,
        },
    }


def harvis_user_to_owui(user: dict, token: str, *, expires_at: Optional[int] = None) -> dict:
    """Build OWUI's user object from a Harvis ``users`` row + a minted JWT.

    Harvis has no ``role`` column, so role is synthesized: the first registrant
    (id == 1, override via ``HARVIS_OWUI_ADMIN_USER_IDS``) is ``admin``,
    everyone else is ``user``. OWUI gates its admin UI on this.
    """
    uid = user["id"]
    role = "admin" if int(uid) in _admin_user_ids() else "user"
    return {
        "id": str(uid),
        "email": user.get("email"),
        "name": user.get("username"),
        "role": role,
        "profile_image_url": user.get("avatar") or "/static/favicon.png",
        "token": token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        "permissions": _default_permissions(role),
    }


def harvis_models_to_owui(native_payload: dict) -> list[dict]:
    """Translate Harvis ``list_models()`` output
    (``{"models": [{name, displayName, provider, ...}]}``) into OWUI's
    ``{"data": [{id, name, owned_by, info}]}`` model list."""
    out: list[dict] = []
    for m in (native_payload or {}).get("models", []):
        name = m.get("name")
        if not name:
            continue
        out.append(
            {
                "id": name,
                "name": m.get("displayName") or name,
                "object": "model",
                "owned_by": m.get("provider") or "harvis",
                "info": {"meta": {"capabilities": {}}, "params": {}},
            }
        )
    return out


def owui_body_to_proxy(owui_body: dict) -> dict:
    """Strip OWUI-only orchestration fields and flatten nested generation params,
    leaving a clean OpenAI chat-completions body for model_proxy."""
    body = {k: v for k, v in (owui_body or {}).items() if k not in _OWUI_ONLY_FIELDS}
    params = body.pop("params", None)
    if isinstance(params, dict):
        for k in _FLATTEN_PARAMS:
            if k in params and k not in body:
                body[k] = params[k]
    return body
