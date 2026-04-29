"""FastAPI routes for the messaging plugin.

Two trust boundaries:
  * /api/messaging/inbound, /api/messaging/outbound, /api/messaging/runs/...
        Service-to-service. The gateway sidecar calls these with a shared
        secret in the X-Gateway-Token header (matching the existing
        OPENCLAW_GATEWAY_TOKEN pattern in tools/discord_proxy.py).
  * /api/messaging/platforms*, /api/messaging/audit
        User-facing. Standard JWT auth via auth_optimized.get_current_user_optimized.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized

from .dispatcher import audit, dispatch_inbound, get_run_events, get_run_status, notify_terminal
from .types import Direction, MessageEvent, MessageType, Platform, SessionSource

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/messaging", tags=["messaging"])


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _gateway_token() -> str:
    return os.getenv("MESSAGING_GATEWAY_TOKEN", "")


def require_gateway_token(x_gateway_token: str = Header(default="")) -> None:
    expected = _gateway_token()
    if not expected:
        raise HTTPException(status_code=503, detail="messaging gateway disabled (no token configured)")
    if x_gateway_token != expected:
        raise HTTPException(status_code=401, detail="invalid gateway token")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class InboundSourcePayload(BaseModel):
    platform: Platform
    chat_id: str
    sender_id: str
    sender_display_name: Optional[str] = None
    thread_id: Optional[str] = None
    is_dm: bool = False
    extra: dict = Field(default_factory=dict)


class InboundMessagePayload(BaseModel):
    source: InboundSourcePayload
    message_id: str
    message_type: MessageType = MessageType.TEXT
    text: Optional[str] = None
    fallback_user_id: Optional[int] = None
    raw: Optional[dict] = None


class InboundResponse(BaseModel):
    ok: bool
    workspace_id: Optional[str] = None
    session_id: Optional[str] = None
    status: Optional[str] = None
    user_id: Optional[int] = None
    error: Optional[str] = None


class OutboundPayload(BaseModel):
    target: InboundSourcePayload
    text: str
    reply_to_message_id: Optional[str] = None
    extra: dict = Field(default_factory=dict)


class PlatformLink(BaseModel):
    platform: Platform
    identifier: str
    sender_display_name: Optional[str] = None
    enabled: bool = True


# ---------------------------------------------------------------------------
# Service-to-service routes (gateway sidecar)
# ---------------------------------------------------------------------------


@router.post("/inbound", response_model=InboundResponse)
async def inbound(
    payload: InboundMessagePayload,
    request: Request,
    _: None = Depends(require_gateway_token),
) -> InboundResponse:
    event = MessageEvent(
        source=SessionSource(
            platform=payload.source.platform,
            chat_id=payload.source.chat_id,
            sender_id=payload.source.sender_id,
            sender_display_name=payload.source.sender_display_name,
            thread_id=payload.source.thread_id,
            is_dm=payload.source.is_dm,
            extra=payload.source.extra,
        ),
        message_id=payload.message_id,
        message_type=payload.message_type,
        text=payload.text,
        raw=payload.raw,
    )
    result = await dispatch_inbound(request, event, fallback_user_id=payload.fallback_user_id)
    return InboundResponse(
        ok=result.ok,
        workspace_id=result.workspace_id,
        session_id=result.session_id,
        status=result.status,
        user_id=result.user_id,
        error=result.error,
    )


@router.get("/runs/{workspace_id}/status")
async def run_status(
    workspace_id: str,
    request: Request,
    _: None = Depends(require_gateway_token),
) -> dict:
    pool = getattr(request.app.state, "pg_pool", None)
    info = await get_run_status(pool, workspace_id)
    if info is None:
        raise HTTPException(status_code=404, detail="workspace run not found")
    return {"workspace_id": workspace_id, **info}


@router.post("/runs/{workspace_id}/notify-terminal")
async def run_notify_terminal(
    workspace_id: str,
    request: Request,
    _: None = Depends(require_gateway_token),
) -> dict:
    """Fire on_session_end + memory.extract_from_session for a terminal run.

    The gateway sidecar calls this exactly once after wait_for_terminal
    returns. Backend re-reads workspace_runs (doesn't trust the sidecar's
    view) and no-ops if the run isn't actually terminal yet.
    """
    return await notify_terminal(request, workspace_id)


@router.get("/runs/{workspace_id}/events")
async def run_events(
    workspace_id: str,
    request: Request,
    since: int = 0,
    limit: int = 100,
    _: None = Depends(require_gateway_token),
) -> dict:
    """Polling endpoint for live workspace events (tool calls, logs, agent
    lifecycle). Adapters track the last seq they consumed and pass it as
    ``since`` on the next call. The status endpoint remains the source of
    truth for terminal state.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    limit = max(1, min(limit, 500))
    events = await get_run_events(pool, workspace_id, since=since, limit=limit)
    return {"workspace_id": workspace_id, "events": events}


@router.post("/outbound")
async def outbound(
    payload: OutboundPayload,
    request: Request,
    _: None = Depends(require_gateway_token),
) -> dict:
    """Audit-only stub. Gateway sidecar handles platform delivery directly;
    this route exists so the backend can log proactive outbound traffic and,
    in Phase 1B, push messages the gateway didn't initiate (cron, alerts).
    """
    pool = getattr(request.app.state, "pg_pool", None)
    fake_event = MessageEvent(
        source=SessionSource(
            platform=payload.target.platform,
            chat_id=payload.target.chat_id,
            sender_id=payload.target.sender_id,
            thread_id=payload.target.thread_id,
        ),
        message_id="outbound-stub",
        message_type=MessageType.TEXT,
        text=payload.text,
    )
    await audit(pool, fake_event, user_id=None, direction=Direction.OUTBOUND, status="accepted_stub")
    return {"ok": True, "note": "outbound delivery is wired in Phase 1B"}


# ---------------------------------------------------------------------------
# User-facing routes
# ---------------------------------------------------------------------------


@router.get("/platforms")
async def list_platforms(
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    user_id = current_user["id"]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT platform, identifier, sender_display_name, enabled, updated_at
            FROM messaging_platforms
            WHERE user_id = $1
            ORDER BY platform, identifier
            """,
            user_id,
        )
    return {
        "platforms": [
            {
                "platform": r["platform"],
                "identifier": r["identifier"],
                "sender_display_name": r["sender_display_name"],
                "enabled": r["enabled"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]
    }


@router.post("/platforms/link")
async def link_platform(
    body: PlatformLink,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    user_id = current_user["id"]
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO messaging_platforms
                (user_id, platform, identifier, sender_display_name, enabled, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
            ON CONFLICT (platform, identifier) DO UPDATE
                SET user_id = EXCLUDED.user_id,
                    sender_display_name = EXCLUDED.sender_display_name,
                    enabled = EXCLUDED.enabled,
                    updated_at = NOW()
            """,
            user_id,
            body.platform.value,
            body.identifier,
            body.sender_display_name,
            body.enabled,
        )
    return {"ok": True}


@router.get("/audit")
async def audit_log(
    request: Request,
    limit: int = 100,
    current_user: dict = Depends(get_current_user_optimized),
) -> dict:
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    user_id = current_user["id"]
    limit = max(1, min(limit, 500))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ts, platform, direction, chat_id, thread_id, sender_id,
                   message_id, kind, status
            FROM messaging_audit
            WHERE user_id = $1
            ORDER BY ts DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    return {
        "entries": [
            {
                "ts": r["ts"].isoformat(),
                "platform": r["platform"],
                "direction": r["direction"],
                "chat_id": r["chat_id"],
                "thread_id": r["thread_id"],
                "sender_id": r["sender_id"],
                "message_id": r["message_id"],
                "kind": r["kind"],
                "status": r["status"],
            }
            for r in rows
        ]
    }
