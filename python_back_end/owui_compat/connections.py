"""Harvis MCP Connections — the "Customize" half that lets a user register an
MCP server/plugin connection. Authenticated CRUD over the existing `mcp_servers`
table (migration 013), which the unauthenticated plugins/mcp/routes.py left
unexposed. We deliberately do NOT mount those routes (they hardcode user_id=1);
this module is owner-scoped via get_current_user.

NOTE (honest scope): connections are stored + managed per-user here; wiring a
saved connection into the live OpenClaw agent runtime (so its tools become
callable mid-session) is a deferred follow-up — the registry exists, the runtime
discovery does not.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_TRANSPORTS = {"stdio", "sse", "streamable-http", "http"}


def _conn_to_dict(row) -> dict:
    def _j(v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v

    created = row["created_at"]
    updated = row["updated_at"]
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "name": row["server_name"],
        "transport": row["transport"],
        "url": row["url"],
        "command": row["command"],
        "args": _j(row["args"]) or [],
        "env": _j(row["env"]) or {},
        "auth_method": row["auth_method"],
        "enabled": row["enabled"],
        "created_at": int(created.timestamp()) if created else None,
        "updated_at": int(updated.timestamp()) if updated else None,
    }


class ConnForm(BaseModel):
    name: Optional[str] = None
    server_name: Optional[str] = None
    transport: str = "stdio"
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list] = None
    env: Optional[dict] = None
    auth_method: str = "none"


def register_connection_routes(router: APIRouter, get_current_user: Callable) -> None:
    def _pool(request: Request):
        pool = getattr(request.app.state, "pg_pool", None)
        if pool is None:
            raise HTTPException(status_code=503, detail="Database not ready")
        return pool

    @router.get("/api/owui/mcp/connections")
    async def conn_list(request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM mcp_servers WHERE user_id=$1 ORDER BY updated_at DESC",
                int(user.id),
            )
        return {"items": [_conn_to_dict(r) for r in rows]}

    @router.post("/api/owui/mcp/connections")
    async def conn_upsert(form: ConnForm, request: Request, user=Depends(get_current_user)):
        name = (form.name or form.server_name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Connection name is required.")
        transport = (form.transport or "stdio").strip().lower()
        if transport not in _TRANSPORTS:
            raise HTTPException(status_code=400, detail=f"Unsupported transport: {transport}")
        if transport == "stdio" and not (form.command or "").strip():
            raise HTTPException(status_code=400, detail="stdio connections need a command.")
        if transport != "stdio" and not (form.url or "").strip():
            raise HTTPException(status_code=400, detail="Remote connections need a URL.")
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO mcp_servers (user_id, server_name, transport, url, command, args, env, auth_method) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8) "
                "ON CONFLICT (user_id, server_name) DO UPDATE SET "
                "transport=EXCLUDED.transport, url=EXCLUDED.url, command=EXCLUDED.command, "
                "args=EXCLUDED.args, env=EXCLUDED.env, auth_method=EXCLUDED.auth_method, updated_at=NOW() "
                "RETURNING *",
                int(user.id), name, transport, form.url or None, form.command or None,
                json.dumps(form.args or []), json.dumps(form.env or {}), form.auth_method or "none",
            )
        return _conn_to_dict(row)

    @router.post("/api/owui/mcp/connections/{conn_id}/toggle")
    async def conn_toggle(conn_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE mcp_servers SET enabled = NOT enabled, updated_at = NOW() "
                "WHERE id=$1 AND user_id=$2 RETURNING *",
                int(conn_id), int(user.id),
            )
        if not row:
            raise HTTPException(status_code=404, detail="Connection not found")
        return _conn_to_dict(row)

    @router.delete("/api/owui/mcp/connections/{conn_id}")
    async def conn_delete(conn_id: str, request: Request, user=Depends(get_current_user)):
        pool = _pool(request)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM mcp_servers WHERE id=$1 AND user_id=$2", int(conn_id), int(user.id)
            )
        return True
