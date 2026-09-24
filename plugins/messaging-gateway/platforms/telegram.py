# Adapted from NousResearch/hermes-agent (MIT) — gateway/platforms/telegram.py
#
# Slim port (~250 lines vs. Hermes's 6,888) on the raw Bot API over httpx
# instead of python-telegram-bot, because image size matters and the sidecar
# only needs: getMe, long-polling getUpdates, sendMessage. Hermes-only
# features intentionally omitted:
#   - MarkdownV2 rendering, drafts/streaming previews, reactions
#   - voice notes, stickers, photo/document download, TTS
#   - proxy fallbacks, forum-topic session bookkeeping, slash commands
#
# Preserved behaviours:
#   - private chats always pass; groups need an @mention or a reply to the bot
#   - mention prefix is stripped before dispatch
#   - forum topics reply into the same message_thread_id
#   - 4096-char message splitting on send

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import AdapterSpec, BasePlatformAdapter, split_text

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
TELEGRAM_MAX_LEN = 4096
POLL_TIMEOUT_S = 30
RETRY_BACKOFF_S = (2, 5, 10, 30)


def parse_update(update: dict, *, bot_id: Optional[int], bot_username: Optional[str]) -> Optional[dict]:
    """Turn one getUpdates entry into the fields an InboundMessage needs.

    Returns None for anything the gateway should ignore: non-message
    updates, bot senders, empty text, or group messages that neither
    mention the bot nor reply to it.
    """
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict) or update.get("edited_message"):
        return None
    sender = message.get("from") or {}
    if not sender or sender.get("is_bot"):
        return None
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    text = (message.get("text") or message.get("caption") or "").strip()
    if not text:
        return None

    is_dm = chat.get("type") == "private"
    if not is_dm:
        mention = f"@{bot_username}" if bot_username else None
        reply_to = message.get("reply_to_message") or {}
        replied_to_bot = bool(bot_id) and (reply_to.get("from") or {}).get("id") == bot_id
        mentioned = bool(mention) and mention.lower() in text.lower()
        if not (mentioned or replied_to_bot):
            return None
        if mentioned:
            idx = text.lower().find(mention.lower())
            text = (text[:idx] + text[idx + len(mention):]).strip()
        if not text:
            return None

    first, last = sender.get("first_name") or "", sender.get("last_name") or ""
    display = (" ".join(p for p in (first, last) if p) or sender.get("username") or str(sender.get("id"))).strip()
    thread_id = message.get("message_thread_id") if message.get("is_topic_message") else None
    return {
        "chat_id": str(chat_id),
        "sender_id": str(sender.get("id")),
        "sender_display_name": display,
        "thread_id": str(thread_id) if thread_id is not None else None,
        "is_dm": is_dm,
        "message_id": str(message.get("message_id")),
        "text": text,
        "extra": {"chat_type": chat.get("type") or "", "username": sender.get("username") or ""},
    }


class TelegramAdapter(BasePlatformAdapter):
    allowed_users_key = "TELEGRAM_ALLOWED_USERS"

    def __init__(self, spec: AdapterSpec):
        super().__init__(Platform.TELEGRAM, spec)
        self._token = spec.get("TELEGRAM_BOT_TOKEN")
        self._client: Optional[httpx.AsyncClient] = None
        self._bot_id: Optional[int] = None
        self._bot_username: Optional[str] = None
        self._offset: Optional[int] = None

    # ------------------------------------------------------------------
    # Bot API plumbing
    # ------------------------------------------------------------------

    def _url(self, method: str) -> str:
        return f"{API_BASE}/bot{self._token}/{method}"

    async def _call(self, method: str, timeout: float = 30.0, **params) -> dict:
        assert self._client is not None
        r = await self._client.post(self._url(method), json=params, timeout=timeout)
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"{method}: non-JSON response (http {r.status_code})")
        if not data.get("ok"):
            raise TelegramApiError(r.status_code, str(data.get("description") or "unknown error"))
        return data.get("result")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._token or ":" not in self._token:
            self._mark_error("TELEGRAM_BOT_TOKEN is missing or not a BotFather token (digits:secret).")
            return
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(POLL_TIMEOUT_S + 10, connect=10))
        try:
            try:
                me = await self._call("getMe", timeout=15)
            except TelegramApiError as e:
                if e.status == 401:
                    self._mark_error("Telegram rejected the bot token (401 Unauthorized).")
                else:
                    self._mark_error(f"getMe failed: {e}")
                return
            except httpx.HTTPError as e:
                self._mark_error(f"cannot reach api.telegram.org: {e.__class__.__name__}")
                return
            self._bot_id = int(me.get("id"))
            self._bot_username = me.get("username")
            self._mark_connected(f"@{self._bot_username}")
            logger.info("[telegram] connected as @%s (id=%s)", self._bot_username, self._bot_id)
            await self._poll_loop()
        finally:
            await self._client.aclose()
            self._client = None
            self._mark_disconnected()

    async def _poll_loop(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            try:
                params = {"timeout": POLL_TIMEOUT_S, "allowed_updates": ["message"]}
                if self._offset is not None:
                    params["offset"] = self._offset
                updates = await self._call("getUpdates", timeout=POLL_TIMEOUT_S + 5, **params)
                failures = 0
                if self._state != "connected":
                    self._mark_connected()
                for update in updates or []:
                    self._offset = int(update.get("update_id", 0)) + 1
                    await self._handle_update(update)
            except asyncio.CancelledError:
                raise
            except TelegramApiError as e:
                if e.status == 409:
                    self._mark_error("Another process is polling this bot (409 Conflict). Delete its webhook or "
                                     "stop the other instance, then save again.")
                    return
                if e.status == 401:
                    self._mark_error("Telegram rejected the bot token (401 Unauthorized).")
                    return
                failures += 1
                self._state = "retrying"
                self._error = str(e)[:300]
                await asyncio.sleep(RETRY_BACKOFF_S[min(failures, len(RETRY_BACKOFF_S)) - 1])
            except httpx.HTTPError as e:
                failures += 1
                self._state = "retrying"
                self._error = f"network: {e.__class__.__name__}"
                await asyncio.sleep(RETRY_BACKOFF_S[min(failures, len(RETRY_BACKOFF_S)) - 1])

    async def stop(self) -> None:
        self._stop_event.set()
        self._mark_disconnected()

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def _handle_update(self, update: dict) -> None:
        parsed = parse_update(update, bot_id=self._bot_id, bot_username=self._bot_username)
        if parsed is None:
            return
        msg = InboundMessage(
            source=SessionSource(
                platform=Platform.TELEGRAM,
                chat_id=parsed["chat_id"],
                sender_id=parsed["sender_id"],
                sender_display_name=parsed["sender_display_name"],
                thread_id=parsed["thread_id"],
                is_dm=parsed["is_dm"],
                extra=parsed["extra"],
            ),
            message_id=parsed["message_id"],
            message_type=MessageType.TEXT,
            text=parsed["text"],
        )
        await self._emit(msg)

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
            logger.warning("[telegram] send_text called before start()")
            return
        first = True
        for chunk in split_text(text, TELEGRAM_MAX_LEN):
            params: dict = {"chat_id": target.chat_id, "text": chunk}
            if target.thread_id:
                params["message_thread_id"] = int(target.thread_id)
            if first and reply_to_message_id and reply_to_message_id.isdigit():
                params["reply_parameters"] = {"message_id": int(reply_to_message_id), "allow_sending_without_reply": True}
            try:
                await self._call("sendMessage", timeout=20, **params)
            except (TelegramApiError, httpx.HTTPError) as e:
                logger.warning("[telegram] sendMessage to %s failed: %s", target.chat_id, e)
                if isinstance(e, TelegramApiError) and e.status in (400, 403):
                    raise RuntimeError(f"Telegram refused the message: {e.description}. The user has to press "
                                       "Start on the bot once before it can write to them.") from e
                raise
            first = False

    def default_test_target(self) -> Optional[SessionSource]:
        # A private chat's id equals the user's id, so the first allowed user
        # is reachable before they ever message the bot — as long as they
        # pressed Start on it once (Telegram bots cannot open a DM first).
        for user_id in sorted(self.allowed_senders()):
            if user_id.lstrip("-").isdigit():
                return SessionSource(platform=Platform.TELEGRAM, chat_id=user_id, sender_id=user_id,
                                     sender_display_name=user_id, is_dm=True)
        return None


class TelegramApiError(RuntimeError):
    def __init__(self, status: int, description: str):
        super().__init__(f"http {status}: {description}")
        self.status = status
        self.description = description
