"""SSH TARGET REGISTRY — GET /api/harvis/targets (Execution Core Phase 4).

A single read-only view the frontend uses to render "where can I run things":
  * the built-in ``sandbox`` container target (lane 3), synthesized from the
    live terminal readiness probe, and
  * the caller's stored SSH host profiles (lane 5) — id/name/host/port/user/
    auth_method/risk_lane/trusted only. **No secrets** are ever returned: the
    encrypted credential column is never selected here.

This module owns no storage — it reads user_ssh_hosts (schema owned by
ssh_manager) and the terminal probe (terminal_container). JWT-auth'd per user;
ownership is enforced by the ``user_id`` filter so one user never sees another's
targets. Registered in main.py next to the other /api/harvis routers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from auth_optimized import get_current_user_optimized
from owui_compat.workspace_method import (
    LANE_CONTAINER_TERMINAL,
    LANE_EXTERNAL_SERVICES,
)
from remote.ssh_manager import ensure_ssh_schema, ssh_enabled

logger = logging.getLogger(__name__)

targets_router = APIRouter(prefix="/api/harvis", tags=["harvis-targets"])


def _uid(user) -> int:
    return int(user["id"] if isinstance(user, dict) else user.id)


@targets_router.get("/targets")
async def list_targets(request: Request, user=Depends(get_current_user_optimized)):
    """List the execution targets available to this user (no secrets)."""
    uid = _uid(user)

    # Built-in sandbox container (lane 3), honest availability from the probe.
    try:
        from workspace.terminal_container import terminal_status

        status = await terminal_status(force_probe=False)
        sandbox_available = bool(status.get("available"))
        sandbox_reason = status.get("reason") or ""
    except Exception as exc:  # docker/probe unavailable — report honestly, don't crash
        sandbox_available = False
        sandbox_reason = f"probe failed: {exc}"

    targets = [{
        "id": "sandbox",
        "kind": "container",
        "name": "Sandbox terminal",
        "lane": LANE_CONTAINER_TERMINAL,
        "available": sandbox_available,
        "reason": sandbox_reason,
        "trusted": True,
    }]

    pool = getattr(request.app.state, "pg_pool", None)
    if pool is not None:
        await ensure_ssh_schema(pool)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, host, port, username, auth_method, risk_lane, "
                "host_key_fingerprint FROM user_ssh_hosts WHERE user_id=$1 "
                "ORDER BY updated_at DESC",
                uid,
            )
        for r in rows:
            targets.append({
                "id": r["id"],
                "kind": "ssh",
                "name": r["name"],
                "host": r["host"],
                "port": r["port"],
                "user": r["username"],
                "auth_method": r["auth_method"] or "agent",
                "lane": r["risk_lane"] or LANE_EXTERNAL_SERVICES,
                "risk_lane": r["risk_lane"] or LANE_EXTERNAL_SERVICES,
                # trusted ⇒ a host-key fingerprint is pinned ⇒ exec-eligible.
                "trusted": bool(r["host_key_fingerprint"]),
            })

    return {"targets": targets, "ssh_enabled": ssh_enabled()}
