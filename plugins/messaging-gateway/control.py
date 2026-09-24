"""Control port — the backend's window into the running gateway.

Bound on ``CONTROL_PORT`` (default 18800, the port compose already maps).
Every route except ``/health`` requires the shared ``X-Gateway-Token``,
the same secret the gateway presents to the backend, so the facade and the
sidecar authenticate each other with one value.

Routes
------
GET  /health                 liveness (no auth)
GET  /status                 supervisor + per-adapter state for the Messaging page
POST /resync                 pull settings now instead of waiting for the timer
POST /send-test              {"key": "telegram:7", "text": "..."} → adapter.send_test
GET  /webhook/{platform}     provider verification handshake, forwarded by the backend
POST /webhook/{platform}     provider event payload, forwarded by the backend
POST /inject                 stub adapter only (registered by platforms/stub.py)
"""

from __future__ import annotations

import base64
import hmac
import logging
from typing import Awaitable, Callable, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from supervisor import AdapterSupervisor

logger = logging.getLogger(__name__)


class _SendTest(BaseModel):
    key: str
    text: str = "Hello from Harvis — messaging is set up."


class _WebhookForward(BaseModel):
    """What the backend relays: the provider's raw body plus the headers and
    query the adapter needs to verify it."""

    method: str = "POST"
    query: dict = {}
    headers: dict = {}
    body_b64: str = ""


class ControlServer:
    def __init__(
        self,
        *,
        token: str,
        port: int,
        supervisor: AdapterSupervisor,
        resync: Callable[[], Awaitable[dict]],
    ):
        self._token = token
        self._port = port
        self._sup = supervisor
        self._resync = resync
        self.app = FastAPI(title="harvis-messaging-gateway", openapi_url=None)
        self._server: Optional[uvicorn.Server] = None
        self._register()

    # ------------------------------------------------------------------

    def _require(self, header: str) -> None:
        if not self._token:
            raise HTTPException(status_code=503, detail="MESSAGING_GATEWAY_TOKEN not configured")
        if not hmac.compare_digest(header or "", self._token):
            raise HTTPException(status_code=401, detail="invalid gateway token")

    def _register(self) -> None:
        app, sup = self.app, self._sup

        @app.get("/health")
        async def health():
            return {"ok": True, "adapters": len(sup.adapters())}

        @app.get("/status")
        async def status(x_gateway_token: str = Header(default="")):
            self._require(x_gateway_token)
            return sup.status()

        @app.post("/resync")
        async def resync(x_gateway_token: str = Header(default="")):
            self._require(x_gateway_token)
            return await self._resync()

        @app.post("/send-test")
        async def send_test(payload: _SendTest, x_gateway_token: str = Header(default="")):
            self._require(x_gateway_token)
            adapter = sup.get(payload.key)
            if adapter is None:
                return {"ok": False, "message": "That platform is not running in the gateway yet."}
            ok, message = await adapter.send_test(payload.text[:2000])
            return {"ok": ok, "message": message}

        @app.get("/webhook/{platform}")
        async def webhook_verify(platform: str, request: Request, x_gateway_token: str = Header(default="")):
            self._require(x_gateway_token)
            query = dict(request.query_params)
            for adapter in sup.for_platform(platform):
                verify = getattr(adapter, "verify_webhook", None)
                if verify is None:
                    continue
                challenge = verify(query)
                if challenge is not None:
                    return PlainTextResponse(challenge)
            raise HTTPException(status_code=403, detail="no adapter accepted the verification")

        @app.post("/webhook/{platform}")
        async def webhook_event(platform: str, payload: _WebhookForward, x_gateway_token: str = Header(default="")):
            self._require(x_gateway_token)
            try:
                raw = base64.b64decode(payload.body_b64 or "")
            except ValueError:
                raise HTTPException(status_code=400, detail="body_b64 is not base64")
            headers = {str(k).lower(): str(v) for k, v in (payload.headers or {}).items()}
            for adapter in sup.for_platform(platform):
                handle = getattr(adapter, "handle_webhook", None)
                if handle is None:
                    continue
                accepted = await handle(raw, headers, payload.query or {})
                if accepted:
                    return {"ok": True}
            raise HTTPException(status_code=403, detail="no adapter accepted the event")

    # ------------------------------------------------------------------

    async def serve(self) -> None:
        config = uvicorn.Config(self.app, host="0.0.0.0", port=self._port, log_level="warning", access_log=False)
        self._server = uvicorn.Server(config)
        logger.info("control port listening on :%d", self._port)
        await self._server.serve()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
