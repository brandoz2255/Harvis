# Adapted from NousResearch/hermes-agent (MIT) — gateway/platforms/signal.py
#
# Talks to a signal-cli daemon (``signal-cli daemon --http``) that the user
# runs and links to a phone number themselves: this sidecar never holds the
# Signal keys. Receive is the daemon's Server-Sent-Events stream, send is its
# JSON-RPC endpoint. No new dependency: httpx streams the SSE lines.
#
# Preserved behaviours:
#   - DMs always pass; group messages need an @mention of our number
#   - own messages (sync envelopes) are ignored
#   - reachability check on start so a stopped daemon shows as an error

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Optional

import httpx

from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import AdapterSpec, BasePlatformAdapter

logger = logging.getLogger(__name__)

RETRY_BACKOFF_S = (2, 5, 10, 30)


def parse_envelope(event: dict, *, account: str) -> Optional[dict]:
    """Return the fields an InboundMessage needs from one SSE/JSON-RPC event, or None."""
    envelope = event.get("envelope")
    if envelope is None:
        envelope = (event.get("params") or {}).get("envelope")
    if not isinstance(envelope, dict):
        return None
    data = envelope.get("dataMessage")
    if not isinstance(data, dict):
        return None
    sender = envelope.get("sourceNumber") or envelope.get("sourceUuid") or envelope.get("source") or ""
    if not sender or sender == account:
        return None
    text = (data.get("message") or "").strip()
    if not text:
        return None
    group = data.get("groupInfo") or {}
    group_id = group.get("groupId")
    is_dm = not group_id
    if not is_dm:
        mentions = data.get("mentions") or []
        if not any((m.get("number") or m.get("uuid")) == account for m in mentions):
            return None
        # Mentions are rendered as U+FFFC placeholders in the body.
        text = text.replace("￼", "").strip()
        if not text:
            return None
    return {
        "chat_id": group_id or sender,
        "sender_id": sender,
        "sender_display_name": envelope.get("sourceName") or sender,
        "message_id": str(envelope.get("timestamp") or data.get("timestamp") or ""),
        "text": text,
        "is_dm": is_dm,
    }


class SignalAdapter(BasePlatformAdapter):
    allowed_users_key = "SIGNAL_ALLOWED_USERS"

    def __init__(self, spec: AdapterSpec):
        super().__init__(Platform.SIGNAL, spec)
        self._base = spec.get("SIGNAL_HTTP_URL").rstrip("/")
        if self._base and not self._base.startswith("http"):
            self._base = "http://" + self._base
        self._account = spec.get("SIGNAL_ACCOUNT")
        self._client: Optional[httpx.AsyncClient] = None
        self._ids = itertools.count(1)

    def allowed_senders(self) -> frozenset[str]:
        # "+1 555-123 4567" as typed in the UI must match signal-cli's "+15551234567";
        # UUIDs (no leading "+") pass through untouched.
        out = set()
        for entry in super().allowed_senders():
            out.add("+" + "".join(ch for ch in entry if ch.isdigit()) if entry.startswith("+") else entry)
        return frozenset(out)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._base or not self._account:
            self._mark_error("SIGNAL_HTTP_URL and SIGNAL_ACCOUNT are required.")
            return
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10))
        try:
            try:
                r = await self._client.get(f"{self._base}/api/v1/check", timeout=10)
            except httpx.HTTPError as e:
                self._mark_error(f"signal-cli daemon unreachable at {self._base}: {e.__class__.__name__}")
                return
            if r.status_code >= 400:
                self._mark_error(f"signal-cli daemon answered http {r.status_code} on /api/v1/check")
                return
            self._mark_connected(self._account)
            logger.info("[signal] connected to %s as %s", self._base, self._account)
            await self._event_loop()
        finally:
            await self._client.aclose()
            self._client = None
            self._mark_disconnected()

    async def _event_loop(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            try:
                async with self._client.stream("GET", f"{self._base}/api/v1/events",
                                               params={"account": self._account},
                                               headers={"Accept": "text/event-stream"}) as resp:
                    if resp.status_code >= 400:
                        raise RuntimeError(f"events stream answered http {resp.status_code}")
                    failures = 0
                    if self._state != "connected":
                        self._mark_connected()
                    async for line in resp.aiter_lines():
                        if self._stop_event.is_set():
                            return
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[5:].strip() or "{}")
                        except ValueError:
                            continue
                        await self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, RuntimeError) as e:
                failures += 1
                self._state, self._error = "retrying", f"{e.__class__.__name__}: {e}"[:300]
                await asyncio.sleep(RETRY_BACKOFF_S[min(failures, len(RETRY_BACKOFF_S)) - 1])

    async def stop(self) -> None:
        self._stop_event.set()
        self._mark_disconnected()

    # ------------------------------------------------------------------
    # Inbound / send
    # ------------------------------------------------------------------

    async def _handle_event(self, event: dict) -> None:
        parsed = parse_envelope(event, account=self._account)
        if parsed is None:
            return
        msg = InboundMessage(
            source=SessionSource(
                platform=Platform.SIGNAL,
                chat_id=parsed["chat_id"],
                sender_id=parsed["sender_id"],
                sender_display_name=parsed["sender_display_name"],
                is_dm=parsed["is_dm"],
            ),
            message_id=parsed["message_id"],
            message_type=MessageType.TEXT,
            text=parsed["text"],
        )
        await self._emit(msg)

    async def send_text(
        self,
        target: SessionSource,
        text: str,
        reply_to_message_id: Optional[str] = None,
    ) -> None:
        if self._client is None:
            logger.warning("[signal] send_text called before start()")
            return
        params: dict = {"account": self._account, "message": text}
        if target.is_dm:
            params["recipient"] = [target.chat_id]
        else:
            params["groupId"] = target.chat_id
        body = {"jsonrpc": "2.0", "id": next(self._ids), "method": "send", "params": params}
        r = await self._client.post(f"{self._base}/api/v1/rpc", json=body, timeout=30)
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400 or data.get("error"):
            err = (data.get("error") or {}).get("message") or f"http {r.status_code}"
            raise RuntimeError(f"signal send failed: {err}"[:300])

    def default_test_target(self) -> Optional[SessionSource]:
        for number in sorted(self.allowed_senders()):
            if number.startswith("+"):
                return SessionSource(platform=Platform.SIGNAL, chat_id=number, sender_id=number,
                                     sender_display_name=number, is_dm=True)
        return None
