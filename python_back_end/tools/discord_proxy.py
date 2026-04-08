"""
Discord posting proxy — lets OpenClaw agents (including heartbeat) post
to designated Discord channels via the Harvis bot.

Security:
- Requires OPENCLAW_GATEWAY_TOKEN auth
- Channel names resolved server-side from env vars
- Agent never sees DISCORD_BOT_TOKEN
- Messages truncated to Discord's 2000-char limit
"""

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

discord_proxy_router = APIRouter(prefix="/api/tools/discord", tags=["discord-proxy"])

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

# Channel name → channel ID mapping (resolved from env vars at startup)
DISCORD_CHANNELS: dict[str, str] = {
    "heartbeat": os.getenv("DISCORD_HEARTBEAT_CHANNEL_ID", ""),
    "alerts": os.getenv("DISCORD_ALERTS_CHANNEL_ID", ""),
    "general": os.getenv("DISCORD_GENERAL_CHANNEL_ID", ""),
}


class DiscordPostRequest(BaseModel):
    channel: str
    content: str

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        if v not in DISCORD_CHANNELS:
            raise ValueError(f"Unknown channel '{v}'. Valid: {list(DISCORD_CHANNELS.keys())}")
        if not DISCORD_CHANNELS[v]:
            raise ValueError(f"Channel '{v}' has no DISCORD_{v.upper()}_CHANNEL_ID configured")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Content cannot be empty")
        return v


def _verify_token(authorization: Optional[str]) -> None:
    """Verify the request carries a valid OPENCLAW_GATEWAY_TOKEN."""
    if not OPENCLAW_GATEWAY_TOKEN:
        # No token configured — allow all (dev mode)
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if authorization[len("Bearer "):] != OPENCLAW_GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


@discord_proxy_router.post("/post")
async def post_to_discord(
    req: DiscordPostRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Post a message to a named Discord channel via the bot token."""
    _verify_token(authorization)

    if not DISCORD_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="DISCORD_BOT_TOKEN not configured")

    channel_id = DISCORD_CHANNELS[req.channel]
    content = req.content[:1990]  # Discord's 2000-char limit with margin

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    logger.info("discord_proxy: posting to channel=%s (%s) length=%d", req.channel, channel_id, len(content))

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"content": content}, headers=headers)

        if resp.status_code not in (200, 201):
            logger.error("discord_proxy: failed status=%s body=%s", resp.status_code, resp.text[:500])
            raise HTTPException(
                status_code=502,
                detail=f"Discord API error {resp.status_code}: {resp.text[:200]}",
            )

        return {"ok": True, "message_id": resp.json().get("id", "")}

    except httpx.RequestError as exc:
        logger.error("discord_proxy: request error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Could not reach Discord: {exc}")
