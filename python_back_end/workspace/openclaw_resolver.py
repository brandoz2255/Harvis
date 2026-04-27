"""
OpenClaw config resolver — determines which OpenClaw instance to route
a given user's sessions to, based on their user_openclaw_config row.

Returns a ResolvedOpenClawConfig with:
  - mode: "bundled" or "byo"
  - url: WebSocket URL
  - token: decrypted gateway token (never logged)
  - workspace_prefix: path prefix to scope file operations (bundled only)
  - allowed_capabilities: set of capability flags
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Set

logger = logging.getLogger(__name__)

BUNDLED_GATEWAY_URL = os.getenv("OPENCLAW_BUNDLED_URL", "ws://openclaw:18789")
BUNDLED_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN_BUNDLED", "")

# Fallback: if BUNDLED token not set, use the single shared token (backwards compat)
_FALLBACK_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")


@dataclass
class ResolvedOpenClawConfig:
    mode: str                        # "bundled" | "byo"
    url: str
    token: str
    workspace_prefix: str            # "" for byo, "bundled/<user_id>/" for bundled
    allowed_capabilities: Set[str] = field(default_factory=set)

    def __repr__(self) -> str:
        # Never log the token
        return (
            f"ResolvedOpenClawConfig(mode={self.mode}, url={self.url}, "
            f"prefix={self.workspace_prefix!r}, caps={self.allowed_capabilities})"
        )


# ── Capability sets ───────────────────────────────────────────────────────────
# Capabilities gated at the backend proxy level.
# Bundled users have the read-only / sandboxed set.
# BYO users have the full set.

_BUNDLED_CAPABILITIES = frozenset({
    "web_fetch",
    "document_save",
    "rag_search",
    "discord_post_public",
})

_BYO_CAPABILITIES = _BUNDLED_CAPABILITIES | frozenset({
    "github_pr",
    "github_repo",
    "kubectl",
    "discord_post_admin",
    "exec_unrestricted",
})


async def resolve_openclaw_config(
    pool,
    user_id: int,
) -> ResolvedOpenClawConfig:
    """
    Look up the user's config and return the resolved routing info.

    If the user has no row, return the bundled defaults.
    If the user has mode='byo' but verification failed or token is empty,
    fall back to bundled and log a warning.
    """
    if pool is None:
        return _bundled_config(user_id)

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT mode, byo_url, byo_token_encrypted, byo_verified_at, byo_last_error
                FROM user_openclaw_config
                WHERE user_id = $1
                """,
                user_id,
            )
    except Exception as exc:
        logger.error("resolve_openclaw_config: DB error for user %s: %s", user_id, exc)
        return _bundled_config(user_id)

    if not row or row["mode"] == "bundled":
        return _bundled_config(user_id)

    # BYO mode requested — validate
    if not row["byo_url"] or not row["byo_token_encrypted"]:
        logger.warning(
            "resolve_openclaw_config: user %s has mode=byo but missing url/token, "
            "falling back to bundled",
            user_id,
        )
        return _bundled_config(user_id)

    if row["byo_verified_at"] is None:
        logger.warning(
            "resolve_openclaw_config: user %s BYO config never verified, "
            "falling back to bundled",
            user_id,
        )
        return _bundled_config(user_id)

    # Decrypt token using the same Fernet pattern from main.py
    try:
        from main import decrypt_api_key
        token = decrypt_api_key(row["byo_token_encrypted"])
    except Exception as exc:
        logger.error(
            "resolve_openclaw_config: user %s BYO token decrypt failed: %s — "
            "falling back to bundled",
            user_id,
            exc,
        )
        return _bundled_config(user_id)

    if not token:
        logger.warning(
            "resolve_openclaw_config: user %s BYO token decrypted to empty, "
            "falling back to bundled",
            user_id,
        )
        return _bundled_config(user_id)

    return ResolvedOpenClawConfig(
        mode="byo",
        url=row["byo_url"],
        token=token,
        workspace_prefix="",
        allowed_capabilities=set(_BYO_CAPABILITIES),
    )


def _bundled_config(user_id: int) -> ResolvedOpenClawConfig:
    """Return the default bundled OpenClaw config for the given user."""
    token = BUNDLED_GATEWAY_TOKEN or _FALLBACK_TOKEN
    return ResolvedOpenClawConfig(
        mode="bundled",
        url=BUNDLED_GATEWAY_URL,
        token=token,
        workspace_prefix=f"bundled/{user_id}/",
        allowed_capabilities=set(_BUNDLED_CAPABILITIES),
    )
