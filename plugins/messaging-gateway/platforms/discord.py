# Adapted from NousResearch/hermes-agent (MIT) — gateway/platforms/discord.py
#
# Slim port (~250 lines vs. Hermes's 3,931). Phase 1D omits Hermes-only
# features that don't matter when HARVIS owns the runtime:
#   - voice channels, voice memos, attachment uploads
#   - reactions, slash commands, exec-approval prompts
#   - embed/component rendering
#   - assistant-thread state machine
#   - multi-shard support
#
# The behaviors preserved match the legacy python_back_end/integrations/
# discord_workspace_bot.py so the cutover doesn't change UX:
#   - bot/self filtering
#   - DISCORD_ALLOWED_CHANNEL_IDS allowlist (DMs always pass)
#   - DISCORD_MENTION_ONLY for non-DM channels
#   - <@id> / <@!id> mention-prefix stripping
#   - DISCORD_DEFAULT_USER_ID fallback when no platform link exists
#   - 2000-char message splitting on send

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from config import GatewayConfig
from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import BasePlatformAdapter

logger = logging.getLogger(__name__)

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:  # pragma: no cover — sidecar installs deps in Dockerfile
    DISCORD_AVAILABLE = False
    discord = None  # type: ignore[assignment]


_DISCORD_MAX_LEN = 2000


def _split_for_discord(text: str, max_len: int = _DISCORD_MAX_LEN) -> list[str]:
    """Split text into <=max_len chunks, preferring newline + word boundaries.

    Mirrors the behavior of legacy _send_long_message in
    discord_workspace_bot.py without depending on Discord's helpers.
    """
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
    return out


class DiscordAdapter(BasePlatformAdapter):
    def __init__(self, cfg: GatewayConfig):
        super().__init__(Platform.DISCORD)
        self._cfg = cfg
        self._client: Optional["discord.Client"] = None  # type: ignore[name-defined]
        self._client_task: Optional[asyncio.Task] = None
        self._mention_re: Optional[re.Pattern[str]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not DISCORD_AVAILABLE:
            logger.error("[discord] discord.py not installed; cannot start adapter")
            return
        if not self._cfg.discord_token:
            logger.error("[discord] DISCORD_BOT_TOKEN not set")
            return

        intents = discord.Intents.default()
        intents.message_content = True  # privileged — must be enabled in dev portal
        intents.dm_messages = True
        intents.guild_messages = True

        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_ready():  # noqa: ARG001
            self._mark_connected()
            user = client.user
            if user is not None:
                self._mention_re = re.compile(rf"<@!?{user.id}>")
                logger.info("[discord] connected as %s (id=%s)", user.name, user.id)

        @client.event
        async def on_message(message):
            await self._handle_message(message)

        try:
            await client.start(self._cfg.discord_token)
        except asyncio.CancelledError:
            logger.info("[discord] client cancelled")
            raise
        except Exception:
            logger.exception("[discord] client crashed")
        finally:
            self._mark_disconnected()

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                logger.exception("[discord] close raised")
        self._mark_disconnected()
        logger.info("[discord] stopped")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send_text(
        self,
        target: SessionSource,
        text: str,
        reply_to_message_id: Optional[str] = None,
    ) -> None:
        if self._client is None:
            logger.warning("[discord] send_text called before start()")
            return
        try:
            channel_id = int(target.chat_id)
        except (TypeError, ValueError):
            logger.warning("[discord] non-numeric chat_id %r", target.chat_id)
            return

        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except Exception:
                logger.exception("[discord] fetch_channel %s failed", channel_id)
                return

        chunks = _split_for_discord(text)
        if not chunks:
            return

        # Reply to the original message on the first chunk for thread-y context;
        # subsequent chunks just send to the channel.
        first = True
        ref = None
        if reply_to_message_id:
            try:
                ref = discord.MessageReference(
                    message_id=int(reply_to_message_id),
                    channel_id=channel_id,
                    fail_if_not_exists=False,
                )
            except Exception:
                ref = None

        for chunk in chunks:
            try:
                if first and ref is not None:
                    await channel.send(chunk, reference=ref)
                else:
                    await channel.send(chunk)
            except Exception:
                logger.exception("[discord] channel.send failed for chat=%s", channel_id)
                return
            first = False

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def _handle_message(self, message) -> None:
        # Self / other-bot filter — matches legacy bot.
        if message.author.bot:
            return

        channel = message.channel
        is_dm = isinstance(channel, discord.DMChannel) or getattr(channel, "type", None) == discord.ChannelType.private

        # Allowed-channel allowlist (DMs always pass).
        if self._cfg.discord_allowed_channel_ids and not is_dm:
            chan_id = getattr(channel, "id", None)
            if chan_id is None or int(chan_id) not in self._cfg.discord_allowed_channel_ids:
                return

        # Mention-only mode for non-DM channels (matches legacy).
        if self._cfg.discord_mention_only and not is_dm:
            if self._client is None or self._client.user is None:
                return
            if self._client.user not in getattr(message, "mentions", []):
                return

        text = message.content or ""

        # Strip mention prefix (`<@id>` and nickname form `<@!id>`).
        if self._mention_re is not None:
            text = self._mention_re.sub("", text).strip()

        if not text:
            return

        chat_id = str(getattr(channel, "id", "")) if channel is not None else ""
        if not chat_id:
            return

        msg = InboundMessage(
            source=SessionSource(
                platform=Platform.DISCORD,
                chat_id=chat_id,
                sender_id=str(message.author.id),
                sender_display_name=getattr(message.author, "name", None),
                thread_id=None,
                is_dm=is_dm,
                extra={
                    "guild_id": str(getattr(getattr(message, "guild", None), "id", "")),
                },
            ),
            message_id=str(message.id),
            message_type=MessageType.TEXT,
            text=text,
            fallback_user_id=self._cfg.discord_default_user_id or None,
        )
        await self._emit(msg)
