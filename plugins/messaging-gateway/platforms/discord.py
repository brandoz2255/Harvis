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
#   - DISCORD_DEFAULT_USER_ID fallback when no platform link exists (env
#     fallback path only; settings-driven adapters use DISCORD_ALLOWED_USERS
#     plus pairing, like every other platform)
#   - 2000-char message splitting on send
#
# Settings arrive through AdapterSpec.env (catalog keys), whether they came
# from the Harvis Messaging page or the container environment.

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import AdapterSpec, BasePlatformAdapter, split_text

logger = logging.getLogger(__name__)

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:  # pragma: no cover — sidecar installs deps in Dockerfile
    DISCORD_AVAILABLE = False
    discord = None  # type: ignore[assignment]


_DISCORD_MAX_LEN = 2000


def _split_for_discord(text: str, max_len: int = _DISCORD_MAX_LEN) -> list[str]:
    return split_text(text, max_len)


def _csv_int_set(raw: str) -> frozenset[int]:
    out: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return frozenset(out)


class DiscordAdapter(BasePlatformAdapter):
    allowed_users_key = "DISCORD_ALLOWED_USERS"

    def __init__(self, spec: AdapterSpec):
        super().__init__(Platform.DISCORD, spec)
        self._token = spec.get("DISCORD_BOT_TOKEN")
        self._mention_only = spec.flag("DISCORD_MENTION_ONLY", default=True)
        self._allowed_channel_ids = _csv_int_set(spec.get("DISCORD_ALLOWED_CHANNEL_IDS"))
        raw_default = spec.get("DISCORD_DEFAULT_USER_ID", "0")
        self._legacy_default_user = int(raw_default) if raw_default.isdigit() and int(raw_default) > 0 else None
        self._client: Optional["discord.Client"] = None  # type: ignore[name-defined]
        self._client_task: Optional[asyncio.Task] = None
        self._mention_re: Optional[re.Pattern[str]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not DISCORD_AVAILABLE:
            self._mark_error("discord.py not installed; cannot start adapter")
            return
        if not self._token:
            self._mark_error("DISCORD_BOT_TOKEN not set")
            return

        intents = discord.Intents.default()
        intents.message_content = True  # privileged — must be enabled in dev portal
        intents.dm_messages = True
        intents.guild_messages = True

        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_ready():  # noqa: ARG001
            user = client.user
            self._mark_connected(f"@{user.name}" if user is not None else None)
            if user is not None:
                self._mention_re = re.compile(rf"<@!?{user.id}>")
                logger.info("[discord] connected as %s (id=%s)", user.name, user.id)

        @client.event
        async def on_message(message):
            await self._handle_message(message)

        try:
            await client.start(self._token)
        except asyncio.CancelledError:
            logger.info("[discord] client cancelled")
            raise
        except discord.LoginFailure as e:
            self._mark_error(f"Discord rejected the bot token: {e}")
        except discord.PrivilegedIntentsRequired:
            self._mark_error("Enable the MESSAGE CONTENT intent for this bot in the Discord Developer Portal.")
        except Exception as e:
            self._mark_error(f"client crashed: {e.__class__.__name__}: {e}")
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
                raise

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
                raise
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
        if self._allowed_channel_ids and not is_dm:
            chan_id = getattr(channel, "id", None)
            if chan_id is None or int(chan_id) not in self._allowed_channel_ids:
                return

        # Mention-only mode for non-DM channels (matches legacy).
        if self._mention_only and not is_dm:
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
        )
        await self._emit(msg)

    def fallback_user_for(self, sender_id: str) -> Optional[int]:
        # Legacy env install: DISCORD_DEFAULT_USER_ID answered everyone in the
        # allowed channels. Keep that only for env-sourced adapters; settings
        # from the Messaging page use the allowlist + pairing like the rest.
        if self.spec.source == "env" and self._legacy_default_user is not None:
            return self._legacy_default_user
        return super().fallback_user_for(sender_id)
