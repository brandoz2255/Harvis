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


def _audio_config() -> dict:
    """Voice state as it actually is, not as it was hardcoded.

    A NON-EMPTY ``tts.engine`` is what makes the client's TTS path (the "sound"
    button, the CallOverlay) synthesize at all — its branch is gated on
    ``config.audio.tts.engine !== ''`` — so it stays "openai" even when the
    server refuses to speak, because browser Kokoro lives on the same branch.
    What must not stay hardcoded is ``voice``: it is the default the client
    sends when the user hasn't picked one, and "alloy" is an OpenAI name no
    local engine has. ``harvis`` carries the provider truth so the settings UI
    can say which side of the wire speaks, without a second round-trip.

    Imported lazily and defensively: /api/config is boot-critical for the whole
    frontend, and a voice module that fails to import must not take the app down
    with it.
    """
    tts: dict = {}
    stt: dict = {}
    try:
        import synthesis

        tts = synthesis.status()
    except Exception:  # noqa: BLE001 - see docstring
        pass
    try:
        import transcription

        stt = transcription.status()
    except Exception:  # noqa: BLE001
        pass

    return {
        "tts": {
            "engine": "openai",
            "voice": tts.get("voice") or os.getenv("HARVIS_TTS_VOICE") or "af_heart",
            "split_on": "punctuation",
        },
        "stt": {"engine": "openai"},
        "harvis": {"tts": tts, "stt": stt},
    }


def build_config(onboarding: bool = False) -> dict:
    """Build the static-ish config dict OWUI reads at boot.

    ``onboarding`` is OWUI's stock setup-state signal: true ONLY while no
    user exists yet — the auth page then shows the "Create Admin Account"
    flow instead of sign-in. The caller (router.owui_get_config) queries the
    users table live so the flag flips as soon as the admin is created,
    without a backend restart.

    v1 deliberately disables image-gen, web-search, community sharing,
    autocomplete, channels, notes, etc. so OWUI never invokes routes the facade
    has not implemented yet. They get flipped on in later phases as Harvis
    differentiators are wired in.
    """
    return {
        "status": True,
        "name": HARVIS_OWUI_NAME,
        "version": HARVIS_OWUI_VERSION,
        "onboarding": onboarding,
        "default_locale": "en-US",
        "images": False,
        "default_models": os.getenv("HARVIS_OWUI_DEFAULT_MODEL", ""),
        "default_prompt_suggestions": [],
        "features": {
            "auth": True,
            "auth_trusted_header": False,
            "enable_ldap": False,
            # Must match main.py's _signup_enabled() default exactly. If this
            # says True and the server gate says False, the auth page shows a
            # "Sign up" link that 403s — the worst of both. Self-serve signup
            # is on by default so a fresh deploy has a working front door. The
            # FIRST signup claims admin and is open too; an operator exposing an
            # unclaimed instance gates it by setting HARVIS_SETUP_CODE.
            # Operators who want a closed instance set
            # HARVIS_OWUI_ENABLE_SIGNUP=false.
            "enable_signup": _env_bool("HARVIS_OWUI_ENABLE_SIGNUP", True),
            # Mirrors main.py's first-signup gate exactly: the claim asks for a
            # code only when the operator set one. Off by default, so the
            # signup form shows no code field on an ordinary install.
            "setup_code_required": bool(os.getenv("HARVIS_SETUP_CODE", "").strip()),
            "enable_login_form": True,
            # OPTION A: HTTP-SSE chat, no Socket.IO. Do not flip without also
            # implementing an OWUI-compatible Socket.IO server (owui_compat).
            "enable_websocket": False,
            # Web search is a real, shipped capability (python_back_end/research/ —
            # DuckDuckGo via LangChain, with content extraction). This was a bare
            # `False` with no env var and no comment, unlike every other flag here,
            # so the toggle simply never rendered and the feature was unreachable
            # from the UI. Default ON; set HARVIS_OWUI_WEB_SEARCH=false to hide it.
            "enable_web_search": _env_bool("HARVIS_OWUI_WEB_SEARCH", True),
            # Image-gen v0 (docs/plans/image-generation-v0.md): default OFF in code —
            # the deploy flips this env once a local provider (ComfyUI/A1111) is
            # confirmed ready. Gates POST /api/harvis/image/generate too.
            "enable_image_generation": _env_bool("HARVIS_OWUI_IMAGE_GENERATION", False),
            "enable_admin_export": False,
            "enable_admin_chat_access": False,
            "enable_community_sharing": False,
            "enable_autocomplete_generation": False,
            "enable_message_rating": False,
            "enable_direct_connections": False,
            # Memories / Personalization tab — not wired in the Harvis facade yet.
            "enable_memories": False,
            # OWUI user API-key minting (/auths/api_key) is not implemented here; hide the Account UI.
            "enable_api_keys": False,
            "enable_channels": False,
            "enable_notes": False,
            # Projects = OWUI Folders with custom instructions + knowledge (facade-served).
            "enable_folders": True,
            # Harvis: gates the Agent Studio / Vibe Code sidebar pins + /harvis routes.
            "enable_harvis_studio": _env_bool("HARVIS_OWUI_ENABLE_STUDIO", True),
            # Harvis: Claude-Desktop-style Chat/Notebook/Code mode switcher at the top
            # of the sidebar (route-based; scopes the sidebar body per mode).
            "enable_harvis_mode_switcher": _env_bool("HARVIS_OWUI_MODE_SWITCHER", True),
            # Harvis: VibeCode page = the Claude-Code-desktop layout (session list /
            # attach-repo run + diffs + Create-PR / plan + tasks). Off → the stub.
            "enable_harvis_vibecode": _env_bool("HARVIS_OWUI_VIBECODE", True),
            # Phase E1: external code engines (OpenCode sidecar) — gates the Build engine
            # selector. Default OFF; the engine only runs when the sidecar is deployed.
            "enable_harvis_external_engines": _env_bool("HARVIS_OWUI_EXTERNAL_ENGINES", False),
            # Whether a folder picked via the host browser may be edited IN-PLACE (real files).
            # OFF by default → browsed folders are clone-mode only (held until the permission
            # ladder + an exec sandbox are verified for that path). Mirrors HARVIS_INPLACE_ON_BROWSED.
            "enable_inplace_on_browsed": _env_bool("HARVIS_INPLACE_ON_BROWSED", False),
            # P1.5: opt-in run-level approval gate for workspace tasks (default OFF).
            "enable_harvis_approvals": _env_bool("HARVIS_OWUI_APPROVALS", False),
            # P2 (marathon): manual Shell tab in Build — a user-driven PTY into the
            # SESSION's runner container (never the host). Default OFF pending the
            # user's explicit enable (stop-gate). Backend WS enforces the same flag.
            "enable_harvis_build_shell": _env_bool("HARVIS_BUILD_SHELL", False),
            "enable_version_update_check": False,
            "enable_google_drive_integration": False,
            "enable_onedrive_integration": False,
        },
        "oauth": {"providers": {}},
        # Voice (S4/V5): live provider state — see _audio_config().
        "audio": _audio_config(),
        "ui": {},
    }
