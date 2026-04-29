"""Per-user MCP server config registry.

Wraps the mcp_servers table so backend code (and a future settings UI)
has a single async API for listing, upserting, enabling/disabling, and
deleting MCP server configurations.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import asyncpg

from .types import AuthMethod, McpServerConfig, Transport

logger = logging.getLogger(__name__)


class McpServerRegistry:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_for_user(self, user_id: int, *, include_disabled: bool = True) -> list[McpServerConfig]:
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT user_id, server_name, transport, url, command,
                           args, env, auth_method, enabled, created_at, updated_at
                    FROM mcp_servers
                    WHERE user_id = $1
                      AND ($2::boolean OR enabled = TRUE)
                    ORDER BY server_name
                    """,
                    int(user_id),
                    include_disabled,
                )
        except Exception:
            logger.exception("mcp.list_for_user failed for %s", user_id)
            return []
        return [_row_to_config(r) for r in rows]

    async def get(self, user_id: int, server_name: str) -> Optional[McpServerConfig]:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT user_id, server_name, transport, url, command,
                           args, env, auth_method, enabled, created_at, updated_at
                    FROM mcp_servers
                    WHERE user_id = $1 AND server_name = $2
                    """,
                    int(user_id),
                    server_name,
                )
        except Exception:
            logger.exception("mcp.get failed for %s/%s", user_id, server_name)
            return None
        return _row_to_config(row) if row else None

    async def upsert(self, cfg: McpServerConfig) -> Optional[McpServerConfig]:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO mcp_servers
                        (user_id, server_name, transport, url, command, args, env,
                         auth_method, enabled, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, NOW(), NOW())
                    ON CONFLICT (user_id, server_name) DO UPDATE
                        SET transport = EXCLUDED.transport,
                            url = EXCLUDED.url,
                            command = EXCLUDED.command,
                            args = EXCLUDED.args,
                            env = EXCLUDED.env,
                            auth_method = EXCLUDED.auth_method,
                            enabled = EXCLUDED.enabled,
                            updated_at = NOW()
                    RETURNING user_id, server_name, transport, url, command,
                              args, env, auth_method, enabled, created_at, updated_at
                    """,
                    cfg.user_id,
                    cfg.server_name,
                    cfg.transport.value,
                    cfg.url,
                    cfg.command,
                    json.dumps(list(cfg.args)),
                    json.dumps(dict(cfg.env)),
                    cfg.auth_method.value,
                    cfg.enabled,
                )
        except Exception:
            logger.exception("mcp.upsert failed for %s/%s", cfg.user_id, cfg.server_name)
            return None
        return _row_to_config(row)

    async def set_enabled(self, user_id: int, server_name: str, enabled: bool) -> bool:
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE mcp_servers
                    SET enabled = $3, updated_at = NOW()
                    WHERE user_id = $1 AND server_name = $2
                    """,
                    int(user_id),
                    server_name,
                    bool(enabled),
                )
        except Exception:
            logger.exception("mcp.set_enabled failed for %s/%s", user_id, server_name)
            return False
        return _changed(result) > 0

    async def delete(self, user_id: int, server_name: str) -> bool:
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM mcp_servers WHERE user_id = $1 AND server_name = $2",
                    int(user_id),
                    server_name,
                )
        except Exception:
            logger.exception("mcp.delete failed for %s/%s", user_id, server_name)
            return False
        return _changed(result) > 0


def _row_to_config(row) -> McpServerConfig:
    return McpServerConfig(
        user_id=row["user_id"],
        server_name=row["server_name"],
        transport=Transport(row["transport"]),
        url=row["url"],
        command=row["command"],
        args=_load_jsonb(row["args"], default=[]),
        env=_load_jsonb(row["env"], default={}),
        auth_method=AuthMethod(row["auth_method"]),
        enabled=row["enabled"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _load_jsonb(value, *, default):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
    return default


def _changed(result: str) -> int:
    """asyncpg returns 'COMMAND N' — extract N (rows affected)."""
    try:
        return int((result or "X 0").split()[-1])
    except (ValueError, IndexError):
        return 0
