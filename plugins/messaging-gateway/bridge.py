"""HTTP bridge to the Harvis backend.

The gateway sidecar uses this client to:
  * post inbound messages to /api/messaging/inbound
  * poll workspace run status via /api/messaging/runs/{id}/status

Authentication is a shared secret in the X-Gateway-Token header (matches the
existing OPENCLAW_GATEWAY_TOKEN pattern in tools/discord_proxy.py).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from config import GatewayConfig
from messaging_types import (
    TERMINAL_RUN_STATUSES,
    InboundMessage,
    InboundResponse,
    RunStatus,
)

logger = logging.getLogger(__name__)


class HarvisBridge:
    def __init__(self, cfg: GatewayConfig):
        self._cfg = cfg
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "HarvisBridge":
        self._client = httpx.AsyncClient(
            base_url=self._cfg.backend_url,
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers={"X-Gateway-Token": self._cfg.gateway_token},
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HarvisBridge used outside of async context manager")
        return self._client

    async def post_inbound(self, msg: InboundMessage) -> InboundResponse:
        client = self._require_client()
        try:
            r = await client.post("/api/messaging/inbound", json=msg.to_payload())
        except httpx.HTTPError as e:
            logger.warning("post_inbound network error: %s", e)
            return InboundResponse(ok=False, error=f"network: {e.__class__.__name__}")

        if r.status_code != 200:
            body = r.text[:300]
            logger.warning("post_inbound non-200 %s: %s", r.status_code, body)
            return InboundResponse(ok=False, error=f"http {r.status_code}: {body}")

        data = r.json()
        return InboundResponse(
            ok=bool(data.get("ok")),
            workspace_id=data.get("workspace_id"),
            session_id=data.get("session_id"),
            status=data.get("status"),
            user_id=data.get("user_id"),
            error=data.get("error"),
        )

    async def get_run_status(self, workspace_id: str) -> Optional[RunStatus]:
        client = self._require_client()
        try:
            r = await client.get(f"/api/messaging/runs/{workspace_id}/status")
        except httpx.HTTPError as e:
            logger.warning("get_run_status network error: %s", e)
            return None
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            logger.warning("get_run_status non-200 %s: %s", r.status_code, r.text[:200])
            return None
        data = r.json()
        return RunStatus(
            workspace_id=data.get("workspace_id", workspace_id),
            status=data.get("status", "unknown"),
            final_summary=data.get("final_summary"),
            error_message=data.get("error_message"),
            updated_at=data.get("updated_at"),
        )

    async def wait_for_terminal(
        self,
        workspace_id: str,
        *,
        on_update=None,
    ) -> Optional[RunStatus]:
        """Poll until the run reaches a terminal state, gives up after timeout.

        on_update (optional): async callable invoked with each non-terminal
        status snapshot — used by adapters that want to edit a 'progress'
        message in the originating chat.
        """
        deadline = asyncio.get_event_loop().time() + self._cfg.poll_timeout_s
        last_status: Optional[str] = None
        while asyncio.get_event_loop().time() < deadline:
            snap = await self.get_run_status(workspace_id)
            if snap is None:
                # Run is missing — treat as terminal failure rather than spinning.
                return RunStatus(
                    workspace_id=workspace_id,
                    status="missing",
                    error_message="workspace run not found in backend",
                )
            if snap.status in TERMINAL_RUN_STATUSES:
                return snap
            if on_update is not None and snap.status != last_status:
                try:
                    await on_update(snap)
                except Exception:
                    logger.exception("on_update raised; continuing polling")
                last_status = snap.status
            await asyncio.sleep(self._cfg.poll_interval_s)
        return RunStatus(
            workspace_id=workspace_id,
            status="timeout",
            error_message=f"polled {self._cfg.poll_timeout_s}s without terminal status",
        )
