"""HTTP bridge from the ACP adapter to the Harvis backend.

Reuses the messaging-plugin endpoints — the ACP adapter is, from the
backend's point of view, just another platform sending inbound messages
and polling run status.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

import httpx

from harvis_acp.config import ACPConfig

logger = logging.getLogger(__name__)


# Run statuses we treat as terminal when polling. Mirrors the values written
# by python_back_end/workspace/workspace_router.py.
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "error", "cancelled"})


class HarvisBridge:
    def __init__(self, cfg: ACPConfig):
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

    def _client_or_raise(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HarvisBridge used outside of async context manager")
        return self._client

    async def post_inbound_text(
        self,
        *,
        chat_id: str,
        sender_id: str,
        text: str,
        thread_id: Optional[str] = None,
    ) -> dict:
        client = self._client_or_raise()
        payload = {
            "source": {
                "platform": "stub",  # acp uses "stub" for now — see Phase 2B note
                "chat_id": chat_id,
                "sender_id": sender_id,
                "sender_display_name": "acp",
                "thread_id": thread_id,
                "is_dm": True,
                "extra": {"surface": "acp"},
            },
            "message_id": f"acp-{uuid.uuid4().hex[:12]}",
            "message_type": "text",
            "text": text,
            "fallback_user_id": self._cfg.default_user_id or None,
        }
        r = await client.post("/api/messaging/inbound", json=payload)
        r.raise_for_status()
        return r.json()

    async def get_run_status(self, workspace_id: str) -> Optional[dict]:
        client = self._client_or_raise()
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
        return r.json()

    async def get_run_events(self, workspace_id: str, since: int = 0) -> list[dict]:
        """Fetch workspace events with seq > ``since``. Empty list on error
        (network blip — caller should retry rather than treat as terminal).
        """
        client = self._client_or_raise()
        try:
            r = await client.get(
                f"/api/messaging/runs/{workspace_id}/events",
                params={"since": since, "limit": 200},
            )
        except httpx.HTTPError as e:
            logger.warning("get_run_events network error: %s", e)
            return []
        if r.status_code != 200:
            return []
        return r.json().get("events") or []

    async def wait_for_terminal(self, workspace_id: str) -> dict:
        """Poll until the run reaches a terminal status, give up after timeout.

        Returns a dict with at minimum {"status": ..., "final_summary": ...,
        "error_message": ...}. Synthetic statuses on failure: 'missing',
        'timeout'.
        """
        import asyncio
        deadline = asyncio.get_event_loop().time() + self._cfg.poll_timeout_s
        while asyncio.get_event_loop().time() < deadline:
            snap = await self.get_run_status(workspace_id)
            if snap is None:
                return {
                    "workspace_id": workspace_id,
                    "status": "missing",
                    "final_summary": None,
                    "error_message": "workspace run not found in backend",
                }
            if snap.get("status") in TERMINAL_RUN_STATUSES:
                return snap
            await asyncio.sleep(self._cfg.poll_interval_s)
        return {
            "workspace_id": workspace_id,
            "status": "timeout",
            "final_summary": None,
            "error_message": f"polled {self._cfg.poll_timeout_s}s without terminal status",
        }
