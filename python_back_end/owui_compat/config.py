"""OWUI ``GET /api/config`` payload — the boot-critical feature-flag matrix.

OpenWebUI's frontend fetches ``/api/config`` before it renders anything; if the
call fails it redirects to ``/error``. The frontend gates UI affordances on the
``features`` flags below — anything left ``False`` means OWUI hides that
affordance and never calls the backend route behind it, which keeps the v1
facade surface tight.

The single most important flag here is ``enable_websocket: False`` — it tells
OWUI's frontend to skip the Socket.IO connection so the (patched) chat path
streams tokens over HTTP SSE instead. See ``owui_compat`` package docstring.
"""

from __future__ import annotations

import os

HARVIS_OWUI_NAME = os.getenv("HARVIS_OWUI_NAME", "Harvis")
HARVIS_OWUI_VERSION = os.getenv("HARVIS_OWUI_VERSION", "0.1.0")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_config() -> dict:
    """Build the static-ish config dict OWUI reads at boot.

    v1 deliberately disables image-gen, web-search, community sharing,
    autocomplete, channels, notes, etc. so OWUI never invokes routes the facade
    has not implemented yet. They get flipped on in later phases as Harvis
    differentiators are wired in.
    """
    return {
        "status": True,
        "name": HARVIS_OWUI_NAME,
        "version": HARVIS_OWUI_VERSION,
        "default_locale": "en-US",
        "images": False,
        "default_models": os.getenv("HARVIS_OWUI_DEFAULT_MODEL", ""),
        "default_prompt_suggestions": [],
        "features": {
            "auth": True,
            "auth_trusted_header": False,
            "enable_ldap": False,
            "enable_signup": _env_bool("HARVIS_OWUI_ENABLE_SIGNUP", True),
            "enable_login_form": True,
            # OPTION A: HTTP-SSE chat, no Socket.IO. Do not flip without also
            # implementing an OWUI-compatible Socket.IO server (owui_compat).
            "enable_websocket": False,
            "enable_web_search": False,
            "enable_image_generation": False,
            "enable_admin_export": False,
            "enable_admin_chat_access": False,
            "enable_community_sharing": False,
            "enable_autocomplete_generation": False,
            "enable_message_rating": False,
            "enable_direct_connections": False,
            "enable_channels": False,
            "enable_notes": False,
            # Projects = OWUI Folders with custom instructions + knowledge (facade-served).
            "enable_folders": True,
            # Harvis: gates the Agent Studio / Vibe Code sidebar pins + /harvis routes.
            "enable_harvis_studio": _env_bool("HARVIS_OWUI_ENABLE_STUDIO", True),
            # P1.5: opt-in run-level approval gate for workspace tasks (default OFF).
            "enable_harvis_approvals": _env_bool("HARVIS_OWUI_APPROVALS", False),
            "enable_version_update_check": False,
            "enable_google_drive_integration": False,
            "enable_onedrive_integration": False,
        },
        "oauth": {"providers": {}},
        # Voice (S4): a NON-EMPTY tts.engine is what makes the CallOverlay (the
        # "sound" button) actually synthesize + play audio — its TTS branch is
        # gated on `config.audio.tts.engine !== ''`. "openai" = the OpenAI-shaped
        # server contract, which the facade serves at /api/v1/audio/speech (→
        # Harvis TTS). STT in the overlay calls /api/v1/audio/transcriptions
        # directly (not engine-gated). `voice` feeds getVoiceId().
        "audio": {
            "tts": {
                "engine": "openai",
                "voice": "alloy",
                "split_on": "punctuation",
            },
            "stt": {"engine": "openai"},
        },
        "ui": {},
    }
