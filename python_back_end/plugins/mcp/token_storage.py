# Adapted shape from NousResearch/hermes-agent (MIT) — tools/mcp_oauth.py
# (HermesTokenStorage). Hermes persists tokens to JSON files under
# ~/.hermes/mcp-tokens/. Harvis is multi-tenant and Postgres-native, so we
# scope by (user_id, server_name) and store both payloads (tokens +
# client_info) as JSONB rows.
#
# Critical detail preserved from Hermes Fix A: persist an absolute
# expires_at alongside the SDK's expires_in. On read, rewrite expires_in
# to the remaining seconds so the MCP SDK's is_token_valid() correctly
# reports False for tokens that expired while the process was down.

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


class PgTokenStorage:
    """Per-(user, server) Postgres-backed OAuth token storage.

    Payload shapes mirror the MCP Python SDK's OAuthToken /
    OAuthClientInformationFull but we store them as raw dicts to avoid
    pinning the SDK version into our schema.
    """

    def __init__(self, *, pool: asyncpg.Pool, user_id: int, server_name: str):
        if not server_name or not server_name.strip():
            raise ValueError("server_name must be non-empty")
        self._pool = pool
        self._user_id = int(user_id)
        self._server_name = server_name.strip()

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def server_name(self) -> str:
        return self._server_name

    # -- tokens ------------------------------------------------------------

    async def get_tokens(self) -> Optional[dict]:
        """Return the stored token dict (with rewritten expires_in) or None.

        Rehydration logic mirrors Hermes Fix A: read absolute expires_at,
        rewrite expires_in to remaining-seconds-or-zero so the consumer's
        validity check sees an expired token after a process restart.
        """
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT tokens_json, expires_at
                    FROM mcp_oauth_tokens
                    WHERE user_id = $1 AND server_name = $2
                    """,
                    self._user_id,
                    self._server_name,
                )
        except Exception:
            logger.exception("mcp.get_tokens failed for user=%s server=%s", self._user_id, self._server_name)
            return None

        if row is None or row["tokens_json"] is None:
            return None

        data = _ensure_dict(row["tokens_json"])
        expires_at: Optional[datetime] = row["expires_at"]
        if expires_at is not None:
            remaining = max(int(expires_at.timestamp() - time.time()), 0)
            data["expires_in"] = remaining
        return data

    async def set_tokens(self, tokens: dict) -> None:
        """Persist tokens. Computes absolute expires_at from expires_in."""
        payload = dict(tokens or {})
        expires_at: Optional[datetime] = None
        expires_in = payload.get("expires_in")
        if expires_in is not None:
            try:
                expires_at = datetime.fromtimestamp(time.time() + int(expires_in), tz=timezone.utc)
            except (TypeError, ValueError):
                expires_at = None

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO mcp_oauth_tokens (user_id, server_name, tokens_json, expires_at, updated_at)
                    VALUES ($1, $2, $3::jsonb, $4, NOW())
                    ON CONFLICT (user_id, server_name) DO UPDATE
                        SET tokens_json = EXCLUDED.tokens_json,
                            expires_at = EXCLUDED.expires_at,
                            updated_at = NOW()
                    """,
                    self._user_id,
                    self._server_name,
                    json.dumps(payload, default=str),
                    expires_at,
                )
        except Exception:
            logger.exception("mcp.set_tokens failed for user=%s server=%s", self._user_id, self._server_name)

    # -- client info -------------------------------------------------------

    async def get_client_info(self) -> Optional[dict]:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT client_info_json
                    FROM mcp_oauth_tokens
                    WHERE user_id = $1 AND server_name = $2
                    """,
                    self._user_id,
                    self._server_name,
                )
        except Exception:
            logger.exception("mcp.get_client_info failed for user=%s server=%s", self._user_id, self._server_name)
            return None
        if row is None or row["client_info_json"] is None:
            return None
        return _ensure_dict(row["client_info_json"])

    async def set_client_info(self, client_info: dict) -> None:
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO mcp_oauth_tokens (user_id, server_name, client_info_json, updated_at)
                    VALUES ($1, $2, $3::jsonb, NOW())
                    ON CONFLICT (user_id, server_name) DO UPDATE
                        SET client_info_json = EXCLUDED.client_info_json,
                            updated_at = NOW()
                    """,
                    self._user_id,
                    self._server_name,
                    json.dumps(client_info or {}, default=str),
                )
        except Exception:
            logger.exception("mcp.set_client_info failed for user=%s server=%s", self._user_id, self._server_name)

    # -- delete ------------------------------------------------------------

    async def clear(self) -> None:
        """Wipe both tokens and client_info for this (user, server)."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM mcp_oauth_tokens WHERE user_id = $1 AND server_name = $2",
                    self._user_id,
                    self._server_name,
                )
        except Exception:
            logger.exception("mcp.clear failed for user=%s server=%s", self._user_id, self._server_name)


def _ensure_dict(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            return json.loads(value) or {}
        except (TypeError, ValueError):
            return {}
    return {}
