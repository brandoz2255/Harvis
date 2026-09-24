# Adapted from NousResearch/hermes-agent (MIT) — gateway/platforms/matrix.py
#
# Slim port on the Client-Server API over httpx instead of matrix-nio, so the
# sidecar image stays small. Talks plain (unencrypted) rooms only: E2EE would
# pull in libolm/vodozemac and device verification, which is out of scope for
# this sidecar. Encrypted rooms are detected and reported once per room.
#
# Preserved behaviours:
#   - long-poll /sync with the server-side timeout, resuming from next_batch
#   - the initial sync is history-free (timeline limit 0) so old messages
#     are never replayed as new commands
#   - auto-join invites from allowlisted users
#   - own messages are ignored; group rooms need an @mention of the bot
#   - replies carry m.relates_to/m.in_reply_to so clients thread them

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Optional
from urllib.parse import quote

import httpx

from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import AdapterSpec, BasePlatformAdapter

logger = logging.getLogger(__name__)

SYNC_TIMEOUT_MS = 30000
RETRY_BACKOFF_S = (2, 5, 10, 30)
_INITIAL_FILTER = json.dumps({"room": {"timeline": {"limit": 0}}, "presence": {"types": []}})


def parse_room_event(
    room_id: str,
    event: dict,
    *,
    self_user_id: str,
    self_display: Optional[str],
    is_dm: bool,
) -> Optional[dict]:
    """Return the fields an InboundMessage needs, or None to ignore the event."""
    if event.get("type") != "m.room.message":
        return None
    sender = event.get("sender") or ""
    if not sender or sender == self_user_id:
        return None
    content = event.get("content") or {}
    if content.get("msgtype") not in ("m.text", "m.notice", None):
        return None
    text = (content.get("body") or "").strip()
    if not text:
        return None
    # Edits arrive as a new event whose body starts with "* "; skip them.
    if (content.get("m.relates_to") or {}).get("rel_type") == "m.replace":
        return None

    if not is_dm:
        mentioned_ids = (content.get("m.mentions") or {}).get("user_ids") or []
        mention_forms = [self_user_id]
        if self_display:
            mention_forms.append(self_display)
        lowered = text.lower()
        hit = self_user_id in mentioned_ids or any(m.lower() in lowered for m in mention_forms)
        if not hit:
            return None
        for form in mention_forms:
            idx = lowered.find(form.lower())
            if idx >= 0:
                text = (text[:idx] + text[idx + len(form):]).strip().lstrip(":,").strip()
                lowered = text.lower()
        if not text:
            return None

    return {
        "chat_id": room_id,
        "sender_id": sender,
        "sender_display_name": sender.split(":", 1)[0].lstrip("@") or sender,
        "message_id": event.get("event_id") or "",
        "text": text,
        "is_dm": is_dm,
    }


class MatrixAdapter(BasePlatformAdapter):
    allowed_users_key = "MATRIX_ALLOWED_USERS"

    def __init__(self, spec: AdapterSpec):
        super().__init__(Platform.MATRIX, spec)
        self._homeserver = spec.get("MATRIX_HOMESERVER").rstrip("/")
        if self._homeserver and not self._homeserver.startswith("http"):
            self._homeserver = "https://" + self._homeserver
        self._token = spec.get("MATRIX_ACCESS_TOKEN")
        self._user_id = spec.get("MATRIX_USER_ID")
        self._client: Optional[httpx.AsyncClient] = None
        self._since: Optional[str] = None
        self._display_name: Optional[str] = None
        self._encrypted_rooms: set[str] = set()

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._homeserver}/_matrix/client/v3{path}"

    async def _request(self, method: str, path: str, *, timeout: float = 30.0, **kwargs) -> dict:
        assert self._client is not None
        r = await self._client.request(method, self._url(path), timeout=timeout, **kwargs)
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"{method} {path}: non-JSON response (http {r.status_code})")
        if r.status_code >= 400:
            raise MatrixApiError(r.status_code, str(data.get("errcode") or ""), str(data.get("error") or ""))
        return data

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not (self._homeserver and self._token and self._user_id):
            self._mark_error("MATRIX_HOMESERVER, MATRIX_ACCESS_TOKEN and MATRIX_USER_ID are all required.")
            return
        self._client = httpx.AsyncClient(headers={"Authorization": f"Bearer {self._token}"},
                                         timeout=httpx.Timeout(SYNC_TIMEOUT_MS / 1000 + 15, connect=10))
        try:
            try:
                who = await self._request("GET", "/account/whoami", timeout=15)
            except MatrixApiError as e:
                if e.status in (401, 403):
                    self._mark_error(f"homeserver rejected the access token ({e.errcode or e.status}).")
                else:
                    self._mark_error(f"whoami failed: {e}")
                return
            except httpx.HTTPError as e:
                self._mark_error(f"cannot reach {self._homeserver}: {e.__class__.__name__}")
                return
            actual = who.get("user_id") or ""
            if actual != self._user_id:
                self._mark_error(f"token belongs to {actual}, not MATRIX_USER_ID {self._user_id}.")
                return
            try:
                profile = await self._request("GET", f"/profile/{quote(self._user_id)}/displayname", timeout=15)
                self._display_name = profile.get("displayname") or None
            except (MatrixApiError, httpx.HTTPError):
                self._display_name = None
            initial = await self._request("GET", "/sync", params={"filter": _INITIAL_FILTER, "timeout": 0}, timeout=60)
            self._since = initial.get("next_batch")
            await self._handle_invites(initial)
            self._mark_connected(self._user_id)
            logger.info("[matrix] connected as %s on %s", self._user_id, self._homeserver)
            await self._sync_loop()
        finally:
            await self._client.aclose()
            self._client = None
            self._mark_disconnected()

    async def _sync_loop(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            try:
                data = await self._request("GET", "/sync", params={"since": self._since, "timeout": SYNC_TIMEOUT_MS},
                                           timeout=SYNC_TIMEOUT_MS / 1000 + 15)
                failures = 0
                if self._state != "connected":
                    self._mark_connected()
                self._since = data.get("next_batch") or self._since
                await self._handle_invites(data)
                await self._handle_joined(data)
            except asyncio.CancelledError:
                raise
            except MatrixApiError as e:
                if e.status in (401, 403):
                    self._mark_error(f"homeserver rejected the access token ({e.errcode or e.status}).")
                    return
                failures += 1
                self._state, self._error = "retrying", str(e)[:300]
                await asyncio.sleep(RETRY_BACKOFF_S[min(failures, len(RETRY_BACKOFF_S)) - 1])
            except httpx.HTTPError as e:
                failures += 1
                self._state, self._error = "retrying", f"network: {e.__class__.__name__}"
                await asyncio.sleep(RETRY_BACKOFF_S[min(failures, len(RETRY_BACKOFF_S)) - 1])

    async def stop(self) -> None:
        self._stop_event.set()
        self._mark_disconnected()

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def _handle_invites(self, data: dict) -> None:
        invites = ((data.get("rooms") or {}).get("invite") or {})
        for room_id, room in invites.items():
            inviter = None
            for ev in (room.get("invite_state") or {}).get("events") or []:
                if ev.get("type") == "m.room.member" and ev.get("state_key") == self._user_id:
                    inviter = ev.get("sender")
            if inviter and inviter in self.allowed_senders():
                try:
                    await self._request("POST", f"/join/{quote(room_id)}", json={}, timeout=20)
                    logger.info("[matrix] joined %s on invite from %s", room_id, inviter)
                except (MatrixApiError, httpx.HTTPError) as e:
                    logger.warning("[matrix] join %s failed: %s", room_id, e)
            else:
                logger.info("[matrix] ignoring invite to %s from %s (not on MATRIX_ALLOWED_USERS)", room_id, inviter)

    async def _handle_joined(self, data: dict) -> None:
        joined = ((data.get("rooms") or {}).get("join") or {})
        for room_id, room in joined.items():
            summary = room.get("summary") or {}
            is_dm = summary.get("m.joined_member_count") == 2
            for ev in (room.get("timeline") or {}).get("events") or []:
                if ev.get("type") == "m.room.encrypted":
                    if room_id not in self._encrypted_rooms:
                        self._encrypted_rooms.add(room_id)
                        logger.warning("[matrix] room %s is encrypted; Harvis only reads unencrypted rooms", room_id)
                    continue
                parsed = parse_room_event(room_id, ev, self_user_id=self._user_id,
                                          self_display=self._display_name, is_dm=is_dm)
                if parsed is None:
                    continue
                msg = InboundMessage(
                    source=SessionSource(
                        platform=Platform.MATRIX,
                        chat_id=parsed["chat_id"],
                        sender_id=parsed["sender_id"],
                        sender_display_name=parsed["sender_display_name"],
                        is_dm=parsed["is_dm"],
                        extra={"homeserver": self._homeserver},
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
            logger.warning("[matrix] send_text called before start()")
            return
        content: dict = {"msgtype": "m.text", "body": text}
        if reply_to_message_id:
            content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to_message_id}}
        txn = f"harvis-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        path = f"/rooms/{quote(target.chat_id)}/send/m.room.message/{txn}"
        try:
            await self._request("PUT", path, json=content, timeout=20)
        except (MatrixApiError, httpx.HTTPError) as e:
            logger.warning("[matrix] send to %s failed: %s", target.chat_id, e)
            raise


class MatrixApiError(RuntimeError):
    def __init__(self, status: int, errcode: str, error: str):
        super().__init__(f"http {status} {errcode}: {error}".strip())
        self.status = status
        self.errcode = errcode
