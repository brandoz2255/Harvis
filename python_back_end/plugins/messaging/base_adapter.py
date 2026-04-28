# Adapted shape from NousResearch/hermes-agent (MIT) — gateway/platforms/base.py
# This is a deliberately thin subset. The Hermes original (~2900 lines) carries
# session-store coupling, auto-TTS state, voice modes, fatal-error broadcast,
# and per-session Task tracking that are tied to Hermes's AIAgent runtime.
# Harvis dispatches via HTTP to the backend, which owns session state — adapters
# only need to send/receive and report connection status.

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Awaitable, Callable, Optional

from .types import MessageEvent, Platform, SendResult, SessionSource

logger = logging.getLogger(__name__)

InboundHandler = Callable[[MessageEvent], Awaitable[None]]


class BasePlatformAdapter(abc.ABC):
    """Minimal adapter contract every platform must implement.

    Lifecycle: ``connect()`` starts background listeners; ``disconnect()`` stops
    them. Inbound messages are dispatched via ``handle_inbound()`` which the
    subclass calls when a platform event arrives. Outbound delivery uses
    ``send_text()`` (and optional media variants).

    State that lives on the adapter is kept to "is this adapter connected?".
    Session state lives in the backend.
    """

    def __init__(self, platform: Platform):
        self.platform = platform
        self._inbound_handler: Optional[InboundHandler] = None
        self._connected = False
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API used by the gateway runner
    # ------------------------------------------------------------------

    def set_inbound_handler(self, handler: InboundHandler) -> None:
        self._inbound_handler = handler

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def name(self) -> str:
        return self.platform.value

    # ------------------------------------------------------------------
    # Subclass hooks — must implement
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def connect(self) -> bool:
        """Open the platform connection. Return True on success."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Close the platform connection and stop listeners."""

    @abc.abstractmethod
    async def send_text(
        self,
        target: SessionSource,
        text: str,
        reply_to_message_id: Optional[str] = None,
    ) -> SendResult:
        """Deliver a text message. Subclasses chunk for platform limits."""

    # ------------------------------------------------------------------
    # Optional hooks — default to no-op so adapters can opt in
    # ------------------------------------------------------------------

    async def send_typing(self, target: SessionSource) -> None:
        return None

    async def send_image(
        self,
        target: SessionSource,
        image_url: str,
        caption: Optional[str] = None,
    ) -> SendResult:
        return SendResult(ok=False, error="send_image not implemented")

    # ------------------------------------------------------------------
    # Helpers for subclasses
    # ------------------------------------------------------------------

    async def handle_inbound(self, event: MessageEvent) -> None:
        """Subclasses call this when a platform event arrives."""
        if self._inbound_handler is None:
            logger.warning("[%s] inbound handler not set; dropping message %s", self.name, event.message_id)
            return
        try:
            await self._inbound_handler(event)
        except Exception:
            logger.exception("[%s] inbound handler raised for message %s", self.name, event.message_id)

    def _mark_connected(self) -> None:
        self._connected = True

    def _mark_disconnected(self) -> None:
        self._connected = False
