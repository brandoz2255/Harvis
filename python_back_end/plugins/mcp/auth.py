"""Turning a stored connection into the headers a remote MCP server wants.

Two ways a hosted server authenticates a client, and Harvis supports both:

**A static token the user pastes in.** Most hosted servers just want a bearer
token or a vendor header. Those arrive as sealed credentials on the connection,
under names that say where they go — deliberately explicit rather than the
backend guessing that a credential called ``API_KEY`` was meant to be a bearer:

    MCP_BEARER_TOKEN   ->  Authorization: Bearer <value>
    AUTHORIZATION      ->  Authorization: <value>          (verbatim, any scheme)
    HEADER_X_API_KEY   ->  X-API-Key: <value>              (HEADER_ prefix, _ -> -)

**OAuth.** ``auth_method='oauth'`` means the token lives in ``mcp_oauth_tokens``
from an authorization the user completed in the UI. Expired access tokens are
refreshed here, once, before the connection attempt — a stale token otherwise
surfaces as a bare 401 that looks identical to never having authorized at all.

The unseal happens here and nowhere else on the remote path, mirroring the rule
the stdio path follows (``runtime._spawn_container`` is its one unseal site).
"""

from __future__ import annotations

import logging
from typing import Optional

from .credentials import unseal_env
from .protocol import McpAuthRequired, McpError
from .types import AuthMethod, McpServerConfig

logger = logging.getLogger(__name__)

BEARER_KEYS = ("MCP_BEARER_TOKEN", "MCP_ACCESS_TOKEN", "BEARER_TOKEN")
VERBATIM_KEY = "AUTHORIZATION"
HEADER_PREFIX = "HEADER_"


def static_headers(env: dict) -> dict:
    """Headers derived from a connection's own (sealed) credentials."""
    headers: dict[str, str] = {}
    for key, value in (unseal_env(env or {}) or {}).items():
        if value in (None, ""):
            continue
        name = str(key).strip()
        text = str(value)
        upper = name.upper()
        if upper == VERBATIM_KEY:
            headers["Authorization"] = text
        elif upper in BEARER_KEYS:
            headers["Authorization"] = f"Bearer {text}"
        elif upper.startswith(HEADER_PREFIX):
            header = name[len(HEADER_PREFIX):].replace("_", "-")
            if header:
                headers[header] = text
    return headers


async def oauth_headers(cfg: McpServerConfig, pool) -> dict:
    """Bearer header from the stored OAuth token, refreshing if it has expired."""
    if pool is None:
        raise McpError(
            f"'{cfg.server_name}' is set to OAuth but the backend has no database "
            "handle to read its token from"
        )
    from .oauth import ensure_access_token  # lazy: pulls httpx + discovery

    token = await ensure_access_token(cfg, pool)
    if not token:
        raise McpAuthRequired(
            f"'{cfg.server_name}' has not been authorized yet — open Connectors "
            "and click Authorize",
            url=cfg.url or "",
        )
    return {"Authorization": f"Bearer {token}"}


async def resolve_auth_headers(cfg: McpServerConfig, pool=None) -> dict:
    """Every header this connection should send. Static creds win over OAuth.

    A user who pasted an explicit token meant it; silently preferring a stale
    OAuth grant over it would be the surprising choice.
    """
    headers = static_headers(cfg.env or {})
    if headers.get("Authorization"):
        return headers
    if cfg.auth_method == AuthMethod.OAUTH:
        headers.update(await oauth_headers(cfg, pool))
    return headers


def needs_authorization(cfg: McpServerConfig) -> bool:
    """True when this connection can only work after an OAuth round trip."""
    if cfg.auth_method != AuthMethod.OAUTH:
        return False
    return not static_headers(cfg.env or {}).get("Authorization")
