"""The one place the backend reads the JWT signing secret.

Every module used to do ``os.getenv("JWT_SECRET", "key")``, so a deployment that
forgot to set it signed tokens with a word anyone can guess. A stable secret is
required by default because it also protects stored credentials. A local-only,
explicit development opt-in permits a random per-process secret.
"""
from __future__ import annotations

import logging
import os
import secrets

logger = logging.getLogger(__name__)

PLACEHOLDERS = frozenset({"key", "secret", "changeme", "change-me", "your-secret-key",
                          "your_jwt_secret", "jwt_secret", "harvis-secret-key"})
_ephemeral: str | None = None


# How long a sidecar's MCP token lives: long enough for a slow run to keep its tools,
# short enough that one read out of a process list dies soon after.
# HARVIS_MCP_TOKEN_MINUTES raises it.
def _mcp_token_minutes() -> int:
    """HARVIS_MCP_TOKEN_MINUTES, tolerantly: anything that is not a whole number falls
    back to 15, and the result stays within 1..1440 (a typo must not stop the backend
    from starting, nor mint a token that outlives the day)."""
    try:
        minutes = int((os.getenv("HARVIS_MCP_TOKEN_MINUTES") or "").strip())
    except ValueError:
        return 15
    return max(1, min(1440, minutes))


MCP_TOKEN_MINUTES = _mcp_token_minutes()

# New passwords: casual use, so short is fine on a laptop; a shared server asks for 12.
# Lives here (not main.py) so routes outside main can ask without importing it.
MIN_PASSWORD_LENGTH = 6
SHARED_MIN_PASSWORD_LENGTH = 12


def is_shared() -> bool:
    """Can other machines reach this server? Same answer as plugins.exposure.shared(),
    kept here so the authentication modules (which plugins.exposure imports) can ask
    it without importing that package."""
    mode = os.getenv("HARVIS_EXPOSURE", "").strip().lower()
    bind = os.getenv("HARVIS_BIND_ADDR_PUBLIC", "").strip().lower()
    network_bind = bind not in {"", "localhost", "::1", "[::1]"} and not bind.startswith("127.")
    return mode not in {"", "local"} or network_bind or bool(os.getenv("KUBERNETES_SERVICE_HOST", "").strip())


def min_password_length() -> int:
    return SHARED_MIN_PASSWORD_LENGTH if is_shared() else MIN_PASSWORD_LENGTH


def access_token_minutes() -> int:
    """Sign-in lifetime: ACCESS_TOKEN_EXPIRE_MINUTES, else a day on a shared server and a week on a laptop."""
    raw = (os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return 1440 if is_shared() else 10080


def get_jwt_secret() -> str:
    global _ephemeral
    value = (os.getenv("JWT_SECRET") or "").strip()
    if not value:
        if os.getenv("HARVIS_ALLOW_EPHEMERAL_JWT_SECRET") != "1" or is_shared():
            raise RuntimeError(
                "JWT_SECRET must be set to a stable random value. For local development only, "
                "HARVIS_ALLOW_EPHEMERAL_JWT_SECRET=1 permits a temporary per-process secret; "
                "sessions and encrypted credentials may be lost on restart."
            )
        if _ephemeral is None:
            _ephemeral = secrets.token_urlsafe(48)
            logger.warning("JWT_SECRET is not set; using a random secret for this process. "
                           "Sessions, and provider API keys saved without API_KEY_ENCRYPTION_SECRET, "
                           "will not survive a restart.")
        return _ephemeral
    if value.lower() in PLACEHOLDERS:
        raise RuntimeError("JWT_SECRET is a known placeholder; set it to a long random value.")
    return value


def api_key_encryption_secret() -> str:
    """What saved provider API keys are encrypted with: its own secret, else the JWT one."""
    return (os.getenv("API_KEY_ENCRYPTION_SECRET") or "").strip() or get_jwt_secret()
