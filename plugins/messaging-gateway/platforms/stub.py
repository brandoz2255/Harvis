"""Stub adapter — exposes a tiny HTTP endpoint that injects synthetic messages.

Used for E2E smoke tests of the inbound → backend → workspace → poll → reply
flow without needing real platform credentials. Never enable in production.

Activated by STUB_ENABLED=true; binds to STUB_PORT (default 18800).
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from config import GatewayConfig
from messaging_types import InboundMessage, MessageType, Platform, SessionSource
from platforms.base import BasePlatformAdapter

logger = logging.getLogger(__name__)


class _InjectPayload(BaseModel):
    chat_id: str = "stub-chat"
    sender_id: str = "stub-user"
    text: str
    fallback_user_id: Optional[int] = None
    is_dm: bool = True


class StubAdapter(BasePlatformAdapter):
    def __init__(self, cfg: GatewayConfig):
        super().__init__(Platform.STUB)
        self._cfg = cfg
        self._server: Optional[uvicorn.Server] = None
        # Holds the most recent reply produced by the runner so the inject
        # caller can pick it up synchronously. Stub-only convenience.
        self._last_reply: dict[str, str] = {}

    async def start(self) -> None:
        app = FastAPI(title="harvis-messaging-gateway-stub", openapi_url=None)

        @app.post("/inject")
        async def inject(
            payload: _InjectPayload,
            x_stub_token: str = Header(default=""),
        ):
            expected = os.getenv("STUB_TOKEN", "")
            if expected and x_stub_token != expected:
                raise HTTPException(status_code=401, detail="invalid stub token")

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

        @app.get("/health")
        async def health():
            return {"ok": True, "platform": self.platform.value, "connected": self.is_connected}

        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=self._cfg.stub_port,
            log_level="info",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._connected = True
        logger.info("[stub] HTTP inject endpoint listening on :%d", self._cfg.stub_port)
        # Run until cancelled. uvicorn.serve() returns when self._server.should_exit
        # is set, which happens via stop().
        await self._server.serve()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        self._connected = False

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
