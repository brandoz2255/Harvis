# Adapted from NousResearch/hermes-agent (MIT) — gateway/platforms/whatsapp.py
#
# WhatsApp Business Cloud API over httpx. Inbound traffic arrives by webhook:
# Meta calls the Harvis backend's public route, which relays the raw body,
# headers and query to the gateway control port, which hands them to this
# adapter (``verify_webhook`` for the GET handshake, ``handle_webhook`` for
# POSTed events). There is no polling alternative in the Cloud API, so this
# platform needs a public HTTPS URL.
#
# Preserved behaviours:
#   - X-Hub-Signature-256 verification against the app secret
#   - routing by metadata.phone_number_id so several numbers can coexist
#   - replies quote the inbound message via ``context.message_id``
#   - 4096-char message splitting

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Optional

import httpx

from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import AdapterSpec, BasePlatformAdapter, split_text

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v21.0"
WHATSAPP_MAX_LEN = 4096


def _digits(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def verify_signature(raw: bytes, header: str, app_secret: str) -> bool:
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], expected)


def parse_events(payload: dict, phone_number_id: str) -> tuple[bool, list[dict]]:
    """Return (addressed_to_us, messages) for a Cloud API webhook body."""
    ours = False
    messages: list[dict] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if (value.get("metadata") or {}).get("phone_number_id") != phone_number_id:
                continue
            ours = True
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
            for m in value.get("messages") or []:
                sender = m.get("from") or ""
                text = ""
                if m.get("type") == "text":
                    text = ((m.get("text") or {}).get("body") or "").strip()
                elif m.get("type") in ("image", "document", "audio", "video"):
                    text = ((m.get(m["type"]) or {}).get("caption") or "").strip()
                elif m.get("type") == "button":
                    text = ((m.get("button") or {}).get("text") or "").strip()
                elif m.get("type") == "interactive":
                    inter = m.get("interactive") or {}
                    text = ((inter.get("button_reply") or inter.get("list_reply") or {}).get("title") or "").strip()
                if not sender or not text:
                    continue
                messages.append({
                    "chat_id": sender,
                    "sender_id": sender,
                    "sender_display_name": names.get(sender) or sender,
                    "message_id": m.get("id") or "",
                    "text": text,
                })
    return ours, messages


class WhatsAppCloudAdapter(BasePlatformAdapter):
    allowed_users_key = "WHATSAPP_ALLOWED_USERS"

    def __init__(self, spec: AdapterSpec):
        super().__init__(Platform.WHATSAPP_CLOUD, spec)
        self._token = spec.get("WHATSAPP_ACCESS_TOKEN")
        self._phone_id = spec.get("WHATSAPP_PHONE_NUMBER_ID")
        self._verify_token = spec.get("WHATSAPP_VERIFY_TOKEN")
        self._app_secret = spec.get("WHATSAPP_APP_SECRET")
        self._version = spec.get("WHATSAPP_API_VERSION", DEFAULT_API_VERSION)
        self._client: Optional[httpx.AsyncClient] = None
        self._seen: list[str] = []

    def allowed_senders(self) -> frozenset[str]:
        # Meta sends wa_id as bare digits; people type "+1 555-123 4567".
        return frozenset(_digits(n) for n in super().allowed_senders() if _digits(n))

    # ------------------------------------------------------------------
    # Lifecycle: verify the token once, then sit waiting for webhooks
    # ------------------------------------------------------------------

    async def start(self) -> None:
        missing = [k for k, v in (("WHATSAPP_ACCESS_TOKEN", self._token), ("WHATSAPP_PHONE_NUMBER_ID", self._phone_id),
                                  ("WHATSAPP_VERIFY_TOKEN", self._verify_token)) if not v]
        if missing:
            self._mark_error(f"missing {', '.join(missing)}.")
            return
        self._client = httpx.AsyncClient(headers={"Authorization": f"Bearer {self._token}"},
                                         timeout=httpx.Timeout(20, connect=10))
        try:
            try:
                r = await self._client.get(f"{GRAPH_BASE}/{self._version}/{self._phone_id}",
                                           params={"fields": "display_phone_number,verified_name"})
                data = r.json()
            except httpx.HTTPError as e:
                self._mark_error(f"cannot reach graph.facebook.com: {e.__class__.__name__}")
                return
            except ValueError:
                self._mark_error("graph.facebook.com returned a non-JSON response.")
                return
            if r.status_code >= 400 or "error" in data:
                err = (data.get("error") or {}).get("message") or f"http {r.status_code}"
                self._mark_error(f"Meta rejected the access token or phone number id: {err}"[:300])
                return
            display = data.get("display_phone_number") or self._phone_id
            if not self._app_secret:
                logger.warning("[whatsapp_cloud] WHATSAPP_APP_SECRET not set; webhook signatures are not verified")
            self._mark_connected(display)
            logger.info("[whatsapp_cloud] connected as %s (%s)", data.get("verified_name"), display)
            await self._stop_event.wait()
        finally:
            await self._client.aclose()
            self._client = None
            self._mark_disconnected()

    async def stop(self) -> None:
        self._stop_event.set()
        self._mark_disconnected()

    # ------------------------------------------------------------------
    # Webhooks (relayed by the backend through the control port)
    # ------------------------------------------------------------------

    def verify_webhook(self, query: dict) -> Optional[str]:
        if query.get("hub.mode") != "subscribe":
            return None
        if not hmac.compare_digest(str(query.get("hub.verify_token") or ""), self._verify_token):
            return None
        return str(query.get("hub.challenge") or "")

    async def handle_webhook(self, raw: bytes, headers: dict, query: dict) -> bool:
        if self._app_secret and not verify_signature(raw, headers.get("x-hub-signature-256", ""), self._app_secret):
            logger.warning("[whatsapp_cloud] webhook signature mismatch; dropping")
            return False
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return False
        ours, messages = parse_events(payload, self._phone_id)
        if not ours:
            return False
        for parsed in messages:
            mid = parsed["message_id"]
            if mid and mid in self._seen:
                continue
            if mid:
                self._seen = (self._seen + [mid])[-200:]
            msg = InboundMessage(
                source=SessionSource(
                    platform=Platform.WHATSAPP_CLOUD,
                    chat_id=parsed["chat_id"],
                    sender_id=parsed["sender_id"],
                    sender_display_name=parsed["sender_display_name"],
                    is_dm=True,
                    extra={"phone_number_id": self._phone_id},
                ),
                message_id=mid,
                message_type=MessageType.TEXT,
                text=parsed["text"],
            )
            await self._emit(msg)
        return True

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
            logger.warning("[whatsapp_cloud] send_text called before start()")
            return
        url = f"{GRAPH_BASE}/{self._version}/{self._phone_id}/messages"
        first = True
        for chunk in split_text(text, WHATSAPP_MAX_LEN):
            body: dict = {"messaging_product": "whatsapp", "to": target.chat_id, "type": "text",
                          "text": {"body": chunk, "preview_url": False}}
            if first and reply_to_message_id:
                body["context"] = {"message_id": reply_to_message_id}
            r = await self._client.post(url, json=body)
            if r.status_code >= 400:
                try:
                    err = (r.json().get("error") or {}).get("message") or r.text
                except ValueError:
                    err = r.text
                raise RuntimeError(f"WhatsApp send failed (http {r.status_code}): {err}"[:300])
            first = False

    def default_test_target(self) -> Optional[SessionSource]:
        # Free-form text only reaches a number that wrote to us in the last
        # 24 h; outside that window Meta answers with an error we surface.
        for digits in sorted(self.allowed_senders()):
            return SessionSource(platform=Platform.WHATSAPP_CLOUD, chat_id=digits, sender_id=digits,
                                 sender_display_name=f"+{digits}", is_dm=True)
        return None
