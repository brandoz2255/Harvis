# Adapted shape from NousResearch/hermes-agent (MIT) — gateway/platforms/base.py
# Hermes-specific session-management, voice/auto-TTS, and AIAgent coupling are
# intentionally not ported. Harvis dispatches inbound messages to its own
# orchestrator (workspace router → OpenClaw bridge), not Hermes's AIAgent.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Platform(str, Enum):
    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    EMAIL = "email"
    SMS = "sms"
    STUB = "stub"


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    DOCUMENT = "document"
    SYSTEM = "system"


class Direction(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclass(frozen=True)
class SessionSource:
    """Identifies the origin of a message: which platform, which chat, which sender."""

    platform: Platform
    chat_id: str
    sender_id: str
    sender_display_name: Optional[str] = None
    thread_id: Optional[str] = None
    is_dm: bool = False
    extra: dict = field(default_factory=dict)

    def session_key(self) -> str:
        """Stable key used to resolve a Harvis user/session from this source."""
        thread = f":{self.thread_id}" if self.thread_id else ""
        return f"{self.platform.value}:{self.chat_id}{thread}:{self.sender_id}"


@dataclass(frozen=True)
class MessageEvent:
    """An inbound message from a platform adapter, bound for the Harvis dispatcher."""

    source: SessionSource
    message_id: str
    message_type: MessageType
    text: Optional[str] = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: list = field(default_factory=list)
    raw: Optional[dict] = None  # platform-specific payload, optional


@dataclass
class SendResult:
    ok: bool
    platform_message_id: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class OutboundMessage:
    """Backend → gateway payload telling the gateway to deliver a response."""

    target: SessionSource
    text: str
    reply_to_message_id: Optional[str] = None
    extra: dict = field(default_factory=dict)


def event_to_audit_row(
    event: MessageEvent,
    *,
    user_id: Optional[int],
    direction: Direction,
    status: str,
    text_for_storage: Optional[str] = None,
) -> dict[str, Any]:
    """Build an audit row matching the messaging_audit schema."""
    return {
        "user_id": user_id,
        "platform": event.source.platform.value,
        "direction": direction.value,
        "chat_id": event.source.chat_id,
        "thread_id": event.source.thread_id,
        "sender_id": event.source.sender_id,
        "message_id": event.message_id,
        "kind": event.message_type.value,
        "text": text_for_storage if text_for_storage is not None else event.text,
        "status": status,
        "ts": event.received_at,
    }
