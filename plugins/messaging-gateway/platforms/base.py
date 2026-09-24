# Adapted shape from NousResearch/hermes-agent (MIT) — gateway/platforms/base.py
# Minimal subset. Sidecar adapters dispatch via HarvisBridge, not via a
# Hermes-style message_handler/session_store.

from __future__ import annotations

import abc
import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from messaging_types import Platform, SessionSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdapterSpec:
    """One adapter the supervisor should run.

    ``env`` holds the platform's settings under their catalog keys (for
    example ``TELEGRAM_BOT_TOKEN``) whether they came from the Harvis
    settings store or from the container's environment. ``owner_user_id`` is
    the Harvis user whose credentials these are; senders on the allowlist
    are dispatched as that user, everyone else goes through pairing.
    """

    platform: str
    owner_user_id: Optional[int]
    env: dict = field(default_factory=dict)
    source: str = "settings"  # "settings" | "env"
    updated_at: Optional[str] = None

    @property
    def key(self) -> str:
        owner = self.owner_user_id if self.owner_user_id is not None else "env"
        return f"{self.platform}:{owner}"

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({"p": self.platform, "u": self.owner_user_id, "e": self.env}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def get(self, key: str, default: str = "") -> str:
        value = self.env.get(key)
        return str(value).strip() if value is not None and str(value).strip() else default

    def flag(self, key: str, default: bool = False) -> bool:
        raw = self.get(key, "")
        if not raw:
            return default
        return raw.lower() in ("1", "true", "yes", "on")

    def csv(self, key: str) -> frozenset[str]:
        return frozenset(p.strip() for p in self.get(key, "").split(",") if p.strip())


class BasePlatformAdapter(abc.ABC):
    """Lifecycle + send contract every platform implements.

    The adapter is responsible for two things only:
      1. Receiving platform events and turning them into ``InboundMessage``
         objects, then handing them to the gateway runner via the inbound
         coroutine the runner provides.
      2. Delivering text back to the originating chat via ``send_text``.

    All session/dispatch/policy logic lives in the Harvis backend.
    """

    #: Catalog key of the comma-separated sender allowlist, if the platform has one.
    allowed_users_key: Optional[str] = None

    def __init__(self, platform: Platform, spec: Optional[AdapterSpec] = None):
        self.platform = platform
        self.spec = spec or AdapterSpec(platform=platform.value, owner_user_id=None, source="env")
        self._connected = False
        self._stop_event = asyncio.Event()
        self._state = "starting"
        self._error: Optional[str] = None
        self._since = time.time()
        self._last_target: Optional[SessionSource] = None
        self._display: Optional[str] = None

    @property
    def name(self) -> str:
        return self.platform.value

    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def owner_user_id(self) -> Optional[int]:
        return self.spec.owner_user_id

    # ------------------------------------------------------------------
    # Status (read by the control port, shown in the Harvis UI)
    # ------------------------------------------------------------------

    def _mark_connected(self, display: Optional[str] = None) -> None:
        self._connected = True
        self._state = "connected"
        self._error = None
        self._since = time.time()
        if display:
            self._display = display

    def _mark_disconnected(self) -> None:
        self._connected = False
        if self._state == "connected":
            self._state = "stopped"
        self._since = time.time()

    def _mark_error(self, message: str) -> None:
        self._connected = False
        self._state = "error"
        self._error = message[:500]
        self._since = time.time()
        logger.error("[%s] %s", self.key, self._error)

    def status(self) -> dict:
        return {
            "platform": self.name,
            "owner_user_id": self.owner_user_id,
            "state": self._state,
            "error": self._error,
            "since": self._since,
            "display": self._display,
            "source": self.spec.source,
            "fingerprint": self.spec.fingerprint,
            "has_test_target": self._last_target is not None or self.default_test_target() is not None,
        }

    # ------------------------------------------------------------------
    # Sender policy
    # ------------------------------------------------------------------

    def allowed_senders(self) -> frozenset[str]:
        if not self.allowed_users_key:
            return frozenset()
        return self.spec.csv(self.allowed_users_key)

    def fallback_user_for(self, sender_id: str) -> Optional[int]:
        """The owner's Harvis id when the sender is allowlisted, else None.

        Unknown senders carry no fallback, so the backend answers only if a
        pairing approval linked them; otherwise the runner sends a pairing
        notice instead of a reply.
        """
        if self.owner_user_id is None:
            return None
        return self.owner_user_id if sender_id in self.allowed_senders() else None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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
    # Test message ("Send test message" in the Harvis UI)
    # ------------------------------------------------------------------

    def default_test_target(self) -> Optional[SessionSource]:
        """Where a test message goes before anyone has talked to the bot.

        Platforms override this when the settings name a reachable chat
        (email: the mailbox itself; telegram: the first allowed user id).
        """
        return None

    async def send_test(self, text: str) -> tuple[bool, str]:
        if not self._connected:
            return False, f"{self.name} is not connected ({self._state})."
        target = self._last_target or self.default_test_target()
        if target is None:
            return False, "Send the bot a message first so Harvis knows which chat to reply to."
        try:
            await self.send_text(target, text)
        except Exception as e:  # noqa: BLE001 — surfaced to the UI as text
            return False, f"send failed: {e.__class__.__name__}: {e}"[:300]
        return True, f"Test message sent to {target.sender_display_name or target.chat_id}."

    # ------------------------------------------------------------------
    # Inbound plumbing
    # ------------------------------------------------------------------

    def set_inbound(self, handler):
        """Inject the runner's per-message coroutine."""
        self._inbound = handler  # type: ignore[attr-defined]

    async def _emit(self, msg) -> None:
        self._last_target = msg.source
        handler = getattr(self, "_inbound", None)
        if handler is None:
            logger.warning("[%s] inbound handler not set; dropping message", self.name)
            return
        try:
            await handler(self, msg)
        except Exception:
            logger.exception("[%s] inbound handler raised", self.name)


def split_text(text: str, max_len: int) -> list[str]:
    """Split text into <=max_len chunks, preferring newline then word boundaries."""
    if not text:
        return []
    if len(text) <= max_len:
        return [text]
    out: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            out.append(remaining)
            break
        cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, max_len)
        if cut <= 0:
            cut = max_len
        out.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [c for c in out if c]
