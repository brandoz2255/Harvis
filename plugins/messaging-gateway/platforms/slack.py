# Adapted from NousResearch/hermes-agent (MIT) — gateway/platforms/slack.py
#
# This is a deliberately slim port: ~200 lines vs. Hermes's 2,427. Hermes-only
# features intentionally omitted from Phase 1C:
#   - multi-workspace token rotation + token-file persistence
#   - proxy/SOCKS support
#   - thread-context cache, reactions, exec-approval prompts
#   - blocks / unfurl-attachments rich-text extraction (plain text only for v1)
#   - assistant-thread metadata caching
#   - file/voice/image/video upload (text only for v1)
#
# These can be added incrementally if real usage needs them. The minimal port
# preserves: Socket Mode connection, app_mention + DM event handling,
# self-message filter, thread replies, basic auth.

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from config import GatewayConfig
from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import BasePlatformAdapter

logger = logging.getLogger(__name__)

try:
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    SLACK_AVAILABLE = True
except ImportError:  # pragma: no cover — sidecar installs deps in Dockerfile
    SLACK_AVAILABLE = False
    AsyncApp = None  # type: ignore[assignment]
    AsyncSocketModeHandler = None  # type: ignore[assignment]


def _is_dm_channel(channel_id: str) -> bool:
    """Slack DM channel IDs start with 'D' (group DMs start with 'G' or 'C')."""
    return bool(channel_id) and channel_id[0] == "D"


class SlackAdapter(BasePlatformAdapter):
    """Slack adapter using Socket Mode.

    Requires both:
      * SLACK_BOT_TOKEN  (xoxb-...)  — for outbound Web API calls
      * SLACK_APP_TOKEN  (xapp-...)  — for the Socket Mode connection
      * SLACK_SIGNING_SECRET is NOT used by Socket Mode (HTTP events mode only).
    """

    def __init__(self, cfg: GatewayConfig):
        super().__init__(Platform.SLACK)
        self._cfg = cfg
        self._app: Optional[AsyncApp] = None  # type: ignore[valid-type]
        self._handler: Optional[AsyncSocketModeHandler] = None  # type: ignore[valid-type]
        self._bot_user_id: Optional[str] = None
        self._handler_task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not SLACK_AVAILABLE:
            logger.error("[slack] slack-bolt not installed; cannot start adapter")
            return

        if not self._cfg.slack_bot_token or not self._cfg.slack_app_token:
            logger.error("[slack] SLACK_BOT_TOKEN and SLACK_APP_TOKEN must both be set")
            return

        self._app = AsyncApp(token=self._cfg.slack_bot_token)

        # Identify the bot so we can filter our own messages.
        try:
            auth = await self._app.client.auth_test()
            self._bot_user_id = auth.get("user_id")
            logger.info(
                "[slack] authenticated as @%s in team %s (bot_user_id=%s)",
                auth.get("user", "?"), auth.get("team", "?"), self._bot_user_id,
            )
        except Exception:
            logger.exception("[slack] auth_test failed")
            return

        # Register handlers.
        @self._app.event("message")
        async def _on_message(event, say):  # noqa: ARG001
            await self._handle_message(event)

        # app_mention is delivered alongside `message` for channel mentions —
        # acknowledge it so Bolt doesn't log "unhandled request" 404s.
        @self._app.event("app_mention")
        async def _on_app_mention(event, say):  # noqa: ARG001
            return None

        # File events fire around uploads even when the user message is what
        # we care about — ack to silence noise.
        @self._app.event("file_shared")
        async def _on_file_shared(event, say):  # noqa: ARG001
            return None

        @self._app.event("file_created")
        async def _on_file_created(event, say):  # noqa: ARG001
            return None

        @self._app.event("file_change")
        async def _on_file_change(event, say):  # noqa: ARG001
            return None

        self._handler = AsyncSocketModeHandler(self._app, self._cfg.slack_app_token)
        self._mark_connected()
        logger.info("[slack] connecting via Socket Mode")

        try:
            await self._handler.start_async()
        except asyncio.CancelledError:
            logger.info("[slack] handler cancelled")
            raise
        except Exception:
            logger.exception("[slack] socket-mode handler crashed")
            self._mark_disconnected()

    async def stop(self) -> None:
        self._stopping.set()
        if self._handler is not None:
            try:
                await self._handler.close_async()
            except Exception:
                logger.exception("[slack] close_async raised")
        self._mark_disconnected()
        logger.info("[slack] stopped")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send_text(
        self,
        target: SessionSource,
        text: str,
        reply_to_message_id: Optional[str] = None,
    ) -> None:
        if self._app is None:
            logger.warning("[slack] send_text called before start()")
            return

        # Slack threads keys on `thread_ts` (the parent message's ts). We carry
        # it through SessionSource.thread_id; if the inbound was already in a
        # thread we reply in-thread. If it was a top-level message we still
        # reply in-thread by using the original message's ts as thread_ts —
        # mirrors Hermes's _resolve_thread_ts default.
        thread_ts = target.thread_id or reply_to_message_id

        try:
            await self._app.client.chat_postMessage(
                channel=target.chat_id,
                text=text[:40000],  # Slack's 40k char limit
                thread_ts=thread_ts,
            )
        except Exception:
            logger.exception("[slack] chat_postMessage failed for chat=%s", target.chat_id)

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def _handle_message(self, event: dict) -> None:
        # Ignore edits/deletes.
        subtype = event.get("subtype")
        if subtype in ("message_changed", "message_deleted"):
            return

        # Ignore bot/self messages. A safer default than Hermes's allow_bots
        # policy for now; can grow into the same allowlist later.
        if event.get("bot_id") or subtype == "bot_message":
            return
        user_id = event.get("user", "")
        if not user_id:
            return
        if self._bot_user_id and user_id == self._bot_user_id:
            return

        text = (event.get("text") or "").strip()
        if not text:
            return

        chat_id = event.get("channel", "")
        if not chat_id:
            return

        # In channels, only respond when the bot is mentioned. DMs always pass.
        is_dm = _is_dm_channel(chat_id) or event.get("channel_type") == "im"
        if not is_dm:
            mention_token = f"<@{self._bot_user_id}>" if self._bot_user_id else None
            if not mention_token or mention_token not in text:
                return
            # Strip the leading @-mention so the dispatcher sees the user's prompt.
            text = text.replace(mention_token, "").strip()
            if not text:
                return

        # Slack message ts (e.g. "1701234567.000400") — used as the message_id
        # and as thread_ts for in-thread replies.
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts") or ts

        msg = InboundMessage(
            source=SessionSource(
                platform=Platform.SLACK,
                chat_id=chat_id,
                sender_id=user_id,
                sender_display_name=event.get("username") or user_id,
                thread_id=thread_ts,
                is_dm=is_dm,
                extra={"team": event.get("team", "")},
            ),
            message_id=ts,
            message_type=MessageType.TEXT,
            text=text,
        )
        await self._emit(msg)
