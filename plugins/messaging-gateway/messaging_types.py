"""Lightweight type definitions for the gateway sidecar.

These mirror the JSON shapes the Harvis backend expects on /api/messaging/inbound
without sharing Python imports with python_back_end. Keeping the sidecar
import-decoupled lets it ship as a standalone container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


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


@dataclass(frozen=True)
class SessionSource:
    platform: Platform
    chat_id: str
    sender_id: str
    sender_display_name: Optional[str] = None
    thread_id: Optional[str] = None
    is_dm: bool = False
    extra: dict = field(default_factory=dict)

    def to_payload(self) -> dict:
        return {
            "platform": self.platform.value,
            "chat_id": self.chat_id,
            "sender_id": self.sender_id,
            "sender_display_name": self.sender_display_name,
            "thread_id": self.thread_id,
            "is_dm": self.is_dm,
            "extra": dict(self.extra),
        }


@dataclass
class InboundMessage:
    source: SessionSource
    message_id: str
    message_type: MessageType = MessageType.TEXT
    text: Optional[str] = None
    fallback_user_id: Optional[int] = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: Optional[dict] = None

    def to_payload(self) -> dict:
        return {
            "source": self.source.to_payload(),
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "text": self.text,
            "fallback_user_id": self.fallback_user_id,
            "raw": self.raw,
        }


@dataclass
class InboundResponse:
    ok: bool
    workspace_id: Optional[str] = None
    session_id: Optional[str] = None
    status: Optional[str] = None
    user_id: Optional[int] = None
    error: Optional[str] = None


@dataclass
class RunStatus:
    workspace_id: str
    status: str
    final_summary: Optional[str] = None
    error_message: Optional[str] = None
    updated_at: Optional[str] = None


# Run statuses we treat as terminal when polling. Mirrors the values written
# by python_back_end/workspace/workspace_router.py.
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "error", "cancelled"})
