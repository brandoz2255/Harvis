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
            "web_search": False,
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
        meta: dict = {
            # capabilities.usage is what makes the chat ASK for token counts:
            # Chat.svelte only adds `stream_options: {include_usage: true}` when
            # the model declares it, so without this the composer's usage meter
            # sits empty for every local model. Declared for all native entries
            # because model_proxy retries once without the field if an upstream
            # rejects it — so a server that doesn't know it loses the counts,
            # never the answer.
            "capabilities": {"usage": True},
        }
        # The window the frontend measures a conversation against. Only set when the
        # backend actually knows it: a missing key leaves the meter on its own default
        # rather than asserting a size nobody measured.
        _ctx = m.get("contextLength")
        if isinstance(_ctx, int) and _ctx > 0:
            meta["context_length"] = _ctx
        entry: dict = {
            "id": name,
            "name": m.get("displayName") or name,
            "object": "model",
            "owned_by": m.get("provider") or "harvis",
            "info": {"meta": meta, "params": {}},
        }
        # A model whose host is down travels with its state rather than being dropped.
        # `harvis` is our own namespace on the entry: OWUI ignores keys it doesn't know,
        # and keeping it off `owned_by` means provider routing — which reads `owned_by`
        # — never sees a value it has no case for.
        status = m.get("status") or "available"
        host = m.get("host")
        if status != "available":
            reason = m.get("description") or "this model's host is not answering"
            meta["description"] = reason
            entry["harvis"] = {"status": status, "host": host, "reason": reason}
        elif host:
            entry["harvis"] = {"status": "available", "host": host}
        out.append(entry)
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
