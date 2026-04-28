# Adapted shape from NousResearch/hermes-agent (MIT) — gateway/platforms/base.py
# Minimal subset. Sidecar adapters dispatch via HarvisBridge, not via a
# Hermes-style message_handler/session_store.

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Optional

from messaging_types import Platform, SessionSource

logger = logging.getLogger(__name__)


class BasePlatformAdapter(abc.ABC):
    """Lifecycle + send contract every platform implements.

    The adapter is responsible for two things only:
      1. Receiving platform events and turning them into ``InboundMessage``
         objects, then handing them to the gateway runner via the inbound
         coroutine the runner provides.
      2. Delivering text back to the originating chat via ``send_text``.

    All session/dispatch/policy logic lives in the Harvis backend.
    """

    def __init__(self, platform: Platform):
        self.platform = platform
        self._connected = False
        self._stop_event = asyncio.Event()

    @property
    def name(self) -> str:
        return self.platform.value

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abc.abstractmethod
    async def start(self) -> None:
        """Open the platform connection and begin dispatching inbound events.

        The runner injects an inbound coroutine via ``set_inbound``.
        """

    @abc.abstractmethod
    async def stop(self) -> None:
        """Close the platform connection."""

    @abc.abstractmethod
    async def send_text(
        self,
        target: SessionSource,
        text: str,
        reply_to_message_id: Optional[str] = None,
    ) -> None: ...

    async def edit_text(
        self,
        target: SessionSource,
        message_id: str,
        text: str,
    ) -> None:
        """Optional: edit a previously-sent message (used for live progress)."""
        return None

    # ------------------------------------------------------------------
    # Inbound plumbing
    # ------------------------------------------------------------------

    def set_inbound(self, handler):
        """Inject the runner's per-message coroutine."""
        self._inbound = handler  # type: ignore[attr-defined]

    async def _emit(self, msg) -> None:
        handler = getattr(self, "_inbound", None)
        if handler is None:
            logger.warning("[%s] inbound handler not set; dropping message", self.name)
            return
        try:
            await handler(self, msg)
        except Exception:
            logger.exception("[%s] inbound handler raised", self.name)
