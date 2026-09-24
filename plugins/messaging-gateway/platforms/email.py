# Adapted from NousResearch/hermes-agent (MIT) — gateway/platforms/email.py
#
# Slim port on the standard library (imaplib + smtplib + email), so no new
# dependency. Blocking mail I/O runs in the default executor. Hermes-only
# features intentionally omitted: attachments, HTML rendering, IMAP IDLE,
# per-thread session files.
#
# Preserved behaviours:
#   - polls INBOX for UNSEEN messages every 15 s, fetching marks them read
#   - automated senders (no-reply, mailer-daemon, list mail, auto-submitted)
#     are skipped so the bot never answers a bounce loop
#   - replies keep the thread: "Re:" subject, In-Reply-To and References
#   - SMTPS on 465, STARTTLS on anything else

from __future__ import annotations

import asyncio
import email
import email.utils
import imaplib
import logging
import re
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from typing import Optional

from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import AdapterSpec, BasePlatformAdapter

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 15
RETRY_BACKOFF_S = (15, 30, 60, 120)
_AUTOMATED_LOCALPARTS = ("noreply", "no-reply", "no_reply", "donotreply", "mailer-daemon", "postmaster", "bounce")


def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 — malformed headers are common
        return value


def _plain_body(msg: email.message.Message) -> str:
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get_content_disposition() == "attachment":
                continue
            if ctype == "text/plain":
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            if ctype == "text/html" and not html:
                html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
    else:
        payload = msg.get_payload(decode=True)
        text = payload.decode(msg.get_content_charset() or "utf-8", "replace") if payload else ""
        if msg.get_content_type() == "text/html":
            html = text
        else:
            return text
    text = re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
    return re.sub(r"<[^>]+>", "", text)


def _strip_quoted(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith(">") or re.match(r"^On .+ wrote:$", line.strip()):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def parse_email(raw: bytes) -> Optional[dict]:
    """Return the fields an InboundMessage needs, or None if the mail is automated/empty."""
    msg = email.message_from_bytes(raw)
    sender_name, sender_addr = email.utils.parseaddr(_decode(msg.get("From")))
    sender_addr = sender_addr.lower()
    if not sender_addr:
        return None
    localpart = sender_addr.split("@", 1)[0]
    if any(tag in localpart for tag in _AUTOMATED_LOCALPARTS):
        return None
    if (msg.get("Auto-Submitted") or "no").lower() != "no":
        return None
    if (msg.get("Precedence") or "").lower() in ("bulk", "list", "junk") or msg.get("List-Id"):
        return None
    body = _strip_quoted(_plain_body(msg)).strip()
    subject = _decode(msg.get("Subject")).strip()
    if not body and not subject:
        return None
    message_id = (msg.get("Message-ID") or "").strip()
    references = (msg.get("References") or "").split()
    return {
        "sender_id": sender_addr,
        "sender_display_name": sender_name or sender_addr,
        "message_id": message_id,
        "subject": subject,
        "text": body or subject,
        "references": references + ([message_id] if message_id else []),
    }


class EmailAdapter(BasePlatformAdapter):
    allowed_users_key = "EMAIL_ALLOWED_USERS"

    def __init__(self, spec: AdapterSpec):
        super().__init__(Platform.EMAIL, spec)
        self._address = spec.get("EMAIL_ADDRESS").lower()
        self._password = spec.get("EMAIL_PASSWORD")
        self._imap_host = spec.get("EMAIL_IMAP_HOST")
        self._imap_port = int(spec.get("EMAIL_IMAP_PORT", "993") or 993)
        self._smtp_host = spec.get("EMAIL_SMTP_HOST")
        self._smtp_port = int(spec.get("EMAIL_SMTP_PORT", "587") or 587)
        self._imap: Optional[imaplib.IMAP4_SSL] = None
        self._threads: dict[str, dict] = {}  # sender -> {"subject", "references"}

    def allowed_senders(self) -> frozenset[str]:
        return frozenset(s.lower() for s in super().allowed_senders())

    # ------------------------------------------------------------------
    # Blocking mail I/O (run in the executor)
    # ------------------------------------------------------------------

    def _imap_connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=30)
        conn.login(self._address, self._password)
        conn.select("INBOX")
        return conn

    def _imap_fetch_unseen(self) -> list[bytes]:
        if self._imap is None:
            self._imap = self._imap_connect()
        try:
            self._imap.noop()
            status, data = self._imap.uid("search", None, "UNSEEN")
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError):
            self._imap = self._imap_connect()
            status, data = self._imap.uid("search", None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return []
        out: list[bytes] = []
        for uid in data[0].split()[:20]:
            status, parts = self._imap.uid("fetch", uid, "(RFC822)")
            if status == "OK":
                for part in parts:
                    if isinstance(part, tuple) and len(part) > 1:
                        out.append(part[1])
        return out

    def _imap_close(self) -> None:
        if self._imap is not None:
            try:
                self._imap.logout()
            except Exception:  # noqa: BLE001
                pass
            self._imap = None

    def _smtp_send(self, mail: EmailMessage) -> None:
        if self._smtp_port == 465:
            with smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=30) as smtp:
                smtp.login(self._address, self._password)
                smtp.send_message(mail)
            return
        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(self._address, self._password)
            smtp.send_message(mail)

    def _smtp_check(self) -> None:
        if self._smtp_port == 465:
            with smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=30) as smtp:
                smtp.login(self._address, self._password)
            return
        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(self._address, self._password)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        missing = [k for k, v in (("EMAIL_ADDRESS", self._address), ("EMAIL_PASSWORD", self._password),
                                  ("EMAIL_IMAP_HOST", self._imap_host), ("EMAIL_SMTP_HOST", self._smtp_host)) if not v]
        if missing:
            self._mark_error(f"missing {', '.join(missing)}.")
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._imap_connect_and_keep)
            await loop.run_in_executor(None, self._smtp_check)
        except imaplib.IMAP4.error as e:
            self._mark_error(f"IMAP login failed: {e}. Gmail and Outlook need an app password, not the account password.")
            return
        except smtplib.SMTPAuthenticationError:
            self._mark_error("SMTP login failed: the server rejected EMAIL_ADDRESS/EMAIL_PASSWORD.")
            return
        except (smtplib.SMTPException, OSError) as e:
            self._mark_error(f"mail server unreachable: {e.__class__.__name__}: {e}"[:300])
            return
        self._mark_connected(self._address)
        logger.info("[email] connected as %s (imap %s, smtp %s)", self._address, self._imap_host, self._smtp_host)
        try:
            await self._poll_loop()
        finally:
            await loop.run_in_executor(None, self._imap_close)
            self._mark_disconnected()

    def _imap_connect_and_keep(self) -> None:
        self._imap_close()
        self._imap = self._imap_connect()

    async def _poll_loop(self) -> None:
        loop = asyncio.get_running_loop()
        failures = 0
        while not self._stop_event.is_set():
            try:
                raws = await loop.run_in_executor(None, self._imap_fetch_unseen)
                failures = 0
                if self._state != "connected":
                    self._mark_connected()
                for raw in raws:
                    await self._handle_raw(raw)
                delay = POLL_INTERVAL_S
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — imaplib raises a zoo of types
                failures += 1
                self._state, self._error = "retrying", f"{e.__class__.__name__}: {e}"[:300]
                await loop.run_in_executor(None, self._imap_close)
                delay = RETRY_BACKOFF_S[min(failures, len(RETRY_BACKOFF_S)) - 1]
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop_event.set()
        self._mark_disconnected()

    # ------------------------------------------------------------------
    # Inbound / send
    # ------------------------------------------------------------------

    async def _handle_raw(self, raw: bytes) -> None:
        parsed = parse_email(raw)
        if parsed is None or parsed["sender_id"] == self._address:
            return
        self._threads[parsed["sender_id"]] = {"subject": parsed["subject"], "references": parsed["references"]}
        msg = InboundMessage(
            source=SessionSource(
                platform=Platform.EMAIL,
                chat_id=parsed["sender_id"],
                sender_id=parsed["sender_id"],
                sender_display_name=parsed["sender_display_name"],
                is_dm=True,
                extra={"subject": parsed["subject"]},
            ),
            message_id=parsed["message_id"] or f"email-{abs(hash(raw))}",
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
        thread = self._threads.get(target.chat_id, {})
        subject = thread.get("subject") or "Message from Harvis"
        if thread.get("subject") and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        mail = EmailMessage()
        mail["From"] = self._address
        mail["To"] = target.chat_id
        mail["Subject"] = subject
        if reply_to_message_id and reply_to_message_id.startswith("<"):
            mail["In-Reply-To"] = reply_to_message_id
            mail["References"] = " ".join(thread.get("references") or [reply_to_message_id])
        mail.set_content(text)
        await asyncio.get_running_loop().run_in_executor(None, self._smtp_send, mail)

    def default_test_target(self) -> Optional[SessionSource]:
        if not self._address:
            return None
        return SessionSource(platform=Platform.EMAIL, chat_id=self._address, sender_id=self._address,
                             sender_display_name=self._address, is_dm=True)
