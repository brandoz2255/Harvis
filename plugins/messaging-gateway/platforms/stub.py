"""Stub adapter — an HTTP endpoint that injects synthetic messages.

Used for E2E smoke tests of the inbound → backend → workspace → poll → reply
flow without needing real platform credentials. Never enable in production.

Activated by STUB_ENABLED=true; mounts POST /inject on the gateway's control
port (the app is handed over in ``CONTROL_APP`` by gateway.py at boot).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import AdapterSpec, BasePlatformAdapter

logger = logging.getLogger(__name__)

CONTROL_APP: Optional[FastAPI] = None


class _InjectPayload(BaseModel):
    chat_id: str = "stub-chat"
    sender_id: str = "stub-user"
    text: str
    fallback_user_id: Optional[int] = None
    is_dm: bool = True


class StubAdapter(BasePlatformAdapter):
    def __init__(self, spec: AdapterSpec):
        super().__init__(Platform.STUB, spec)
        # Holds the most recent reply produced by the runner so the inject
        # caller can pick it up synchronously. Stub-only convenience.
        self._last_reply: dict[str, str] = {}
        self._mounted = False

    async def start(self) -> None:
        app = CONTROL_APP
        if app is None:
            self._mark_error("stub adapter has no control app to mount on")
            return
        if not self._mounted:
            self._mount(app)
            self._mounted = True
        self._mark_connected("stub")
        logger.info("[stub] /inject mounted on the control port")
        await self._stop_event.wait()

    def _mount(self, app: FastAPI) -> None:
        @app.post("/inject")
        async def inject(payload: _InjectPayload, x_stub_token: str = Header(default="")):
            expected = os.getenv("STUB_TOKEN", "")
            if expected and x_stub_token != expected:
                raise HTTPException(status_code=401, detail="invalid stub token")
            if not self._connected:
                raise HTTPException(status_code=503, detail="stub adapter is stopped")
            message_id = f"stub-{uuid.uuid4().hex[:12]}"
            msg = InboundMessage(
                source=SessionSource(
                    platform=Platform.STUB,
                    chat_id=payload.chat_id,
                    sender_id=payload.sender_id,
                    sender_display_name=payload.sender_id,
                    is_dm=payload.is_dm,
                ),
                message_id=message_id,
                message_type=MessageType.TEXT,
                text=payload.text,
                fallback_user_id=payload.fallback_user_id,
            )
            await self._emit(msg)
            return {"ok": True, "message_id": message_id, "reply": self._last_reply.pop(message_id, None)}

    async def stop(self) -> None:
        self._stop_event.set()
        self._mark_disconnected()

    async def send_text(
        self,
        target: SessionSource,
        text: str,
        reply_to_message_id: Optional[str] = None,
    ) -> None:
        # Stub doesn't have a real platform to send to — record the reply so
        # the inject endpoint can return it for synchronous test assertions.
        if reply_to_message_id:
            self._last_reply[reply_to_message_id] = text
        logger.info("[stub] reply for %s: %s", reply_to_message_id, text[:200])
        await asyncio.sleep(0)
