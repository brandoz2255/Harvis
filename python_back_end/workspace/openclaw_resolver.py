"""
OpenClaw config resolver — finds the gateway a given user's sessions route to.

Harvis no longer bundles an OpenClaw container. A user reaches one only through a link
they made themselves, and this resolver looks in two places, in order:

  1. user_openclaw_config  (mode='byo', verified, with a stored token)
  2. settings.integrations.openclaw_external  (owui_compat/openclaw_connect.py, verified)

A user with neither is "not linked": resolve_openclaw_config returns None straight away,
with no network call, so callers can skip the gateway instead of timing out on a host that
does not exist. require_openclaw_config raises OpenClawNotLinked for callers that need one.

Returns a ResolvedOpenClawConfig with:
  - mode: "byo" (user_openclaw_config) or "external" (settings link)
  - url: WebSocket URL
  - token: decrypted gateway token (never logged)
  - workspace_prefix: always "" (linked gateways are not path-scoped by Harvis)
  - allowed_capabilities: set of capability flags
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Set

logger = logging.getLogger(__name__)


class OpenClawNotLinked(RuntimeError):
    """The user has no verified, linked OpenClaw gateway."""


@dataclass
class ResolvedOpenClawConfig:
    mode: str                        # "byo" | "external"
    url: str
    token: str
    workspace_prefix: str            # "" — kept for OpenClawClient's constructor
    allowed_capabilities: Set[str] = field(default_factory=set)

    def __repr__(self) -> str:
        # Never log the token
        return (
            f"ResolvedOpenClawConfig(mode={self.mode}, url={self.url}, "
            f"prefix={self.workspace_prefix!r}, caps={self.allowed_capabilities})"
        )


# Capabilities gated at the backend proxy level. A linked gateway is the user's own
# machine, so it gets the full set.
_LINKED_CAPABILITIES = frozenset({
    "web_fetch",
    "document_save",
    "rag_search",
    "discord_post_public",
    "github_pr",
    "github_repo",
    "kubectl",
    "discord_post_admin",
    "exec_unrestricted",
})


def _to_ws_url(url: str) -> str:
    """http(s)://host → ws(s)://host; the link feature stores the HTTP form."""
    u = (url or "").strip().rstrip("/")
    for http, ws in (("https://", "wss://"), ("http://", "ws://")):
        if u.lower().startswith(http):
            return ws + u[len(http):]
    return u


async def _resolve_byo_row(pool, user_id: int) -> Optional[ResolvedOpenClawConfig]:
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
        return None

    if not row or row["mode"] != "byo":
        return None

    if not row["byo_url"] or not row["byo_token_encrypted"]:
        logger.warning("resolve_openclaw_config: user %s has mode=byo but missing url/token", user_id)
        return None

    if row["byo_verified_at"] is None:
        logger.warning("resolve_openclaw_config: user %s BYO config never verified", user_id)
        return None

    try:
        from main import decrypt_api_key
        token = decrypt_api_key(row["byo_token_encrypted"])
    except Exception as exc:
        logger.error("resolve_openclaw_config: user %s BYO token decrypt failed: %s", user_id, exc)
        return None

    if not token:
        logger.warning("resolve_openclaw_config: user %s BYO token decrypted to empty", user_id)
        return None

    return ResolvedOpenClawConfig(
        mode="byo",
        url=row["byo_url"],
        token=token,
        workspace_prefix="",
        allowed_capabilities=set(_LINKED_CAPABILITIES),
    )


async def _resolve_external_link(pool, user_id: int) -> Optional[ResolvedOpenClawConfig]:
    try:
        from owui_compat.openclaw_connect import resolve_openclaw_target
        target = await resolve_openclaw_target(pool, user_id)
    except Exception as exc:
        # Includes EndpointValidationError: a saved URL the shared-host rules now refuse
        # is treated as not linked rather than dialled.
        logger.warning("resolve_openclaw_config: user %s external link unusable: %s", user_id, exc)
        return None
    if not target or not target.get("base_url") or not target.get("token"):
        return None
    return ResolvedOpenClawConfig(
        mode="external",
        url=_to_ws_url(target["base_url"]),
        token=target["token"],
        workspace_prefix="",
        allowed_capabilities=set(_LINKED_CAPABILITIES),
    )


async def resolve_openclaw_config(pool, user_id: int) -> Optional[ResolvedOpenClawConfig]:
    """
    The user's linked OpenClaw gateway, or None when they have not linked one.

    Never returns a default host: there is no bundled gateway to fall back to.
    """
    from openclaw_availability import require_openclaw
    require_openclaw()
    if pool is None:
        return None
    return await _resolve_byo_row(pool, user_id) or await _resolve_external_link(pool, user_id)


async def require_openclaw_config(pool, user_id: int) -> ResolvedOpenClawConfig:
    """Like resolve_openclaw_config, but raises OpenClawNotLinked instead of returning None."""
    config = await resolve_openclaw_config(pool, user_id)
    if config is None:
        raise OpenClawNotLinked("OpenClaw is not linked (optional — link one under Settings > Integrations)")
    return config
