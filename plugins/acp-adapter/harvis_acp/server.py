"""ACP server — Phase 2C: prompt dispatch + live tool-call streaming.

Flow per prompt:
  1. Extract text from the ACP content blocks.
  2. POST to /api/messaging/inbound to launch a workspace run.
  3. In parallel:
        - Poll /api/messaging/runs/{id}/status until terminal.
        - Poll /api/messaging/runs/{id}/events and map each new workspace
          event to an ACP session_update (ToolCallStart / ToolCallProgress /
          AgentThoughtChunk).
  4. On terminal, send the final summary as an AgentMessageChunk and return
     PromptResponse(stop_reason=...).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

import acp
from acp.schema import (
    AgentCapabilities,
    Implementation,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
)

from harvis_acp import __version__ as HARVIS_ACP_VERSION
from harvis_acp.bridge import HarvisBridge
from harvis_acp.config import ACPConfig, load_config

logger = logging.getLogger(__name__)


def _extract_text_from_blocks(blocks) -> str:
    parts: list[str] = []
    for b in blocks or []:
        text = getattr(b, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts).strip()


def _format_terminal(snap: dict) -> str:
    status = snap.get("status", "unknown")
    if status == "completed":
        return snap.get("final_summary") or "_(harvis: completed with no summary)_"
    if status in ("failed", "error"):
        return f"_(harvis: run failed — {snap.get('error_message') or 'no error message'})_"
    if status == "cancelled":
        return "_(harvis: run cancelled)_"
    if status == "timeout":
        return f"_(harvis: timed out — {snap.get('error_message') or ''})_"
    if status == "missing":
        return "_(harvis: run missing in backend)_"
    return f"_(harvis: unknown terminal status {status})_"


class HarvisACPAgent(acp.Agent):
    def __init__(self, cfg: Optional[ACPConfig] = None) -> None:
        super().__init__()
        self._cfg = cfg or load_config()
        self._conn: Optional[acp.Client] = None
        # session_id -> per-session state (currently just the latest workspace_id)
        self._sessions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def on_connect(self, conn: acp.Client) -> None:
        # Called synchronously by AgentSideConnection.__init__; must not be async.
        self._conn = conn
        logger.info("[acp] client connected")

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

    async def initialize(self, protocol_version, client_capabilities=None, client_info=None, **kwargs):  # noqa: ARG002
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(load_session=False),
            agent_info=Implementation(
                name="harvis-acp",
                version=HARVIS_ACP_VERSION,
                title="Harvis Agent",
            ),
            auth_methods=[],
        )

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def new_session(self, cwd, mcp_servers=None, **kwargs):  # noqa: ARG002
        session_id = f"acp-{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = {"workspace_id": None, "cwd": cwd}
        logger.info("[acp] new_session %s cwd=%s", session_id, cwd)
        return NewSessionResponse(session_id=session_id)

    async def cancel(self, session_id, **kwargs):  # noqa: ARG002
        # Phase 2B: just clear state. Real cancellation of a running workspace
        # is a backend feature — workspace_router doesn't currently expose a
        # cancel endpoint. Wire it up when it does.
        sess = self._sessions.get(session_id)
        if sess is not None:
            sess["workspace_id"] = None
        logger.info("[acp] cancel session=%s (no-op)", session_id)

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    async def prompt(self, prompt, session_id, message_id=None, **kwargs):  # noqa: ARG002
        text = _extract_text_from_blocks(prompt)
        sess = self._sessions.get(session_id)

        if sess is None:
            await self._send_agent_text(session_id, "_(harvis: unknown session)_")
            return PromptResponse(stop_reason="cancelled")

        if not text:
            await self._send_agent_text(session_id, "_(harvis: empty prompt)_")
            return PromptResponse(stop_reason="end_turn")

        if not self._cfg.gateway_token:
            await self._send_agent_text(
                session_id,
                "_(harvis: MESSAGING_GATEWAY_TOKEN not configured on the ACP host)_",
            )
            return PromptResponse(stop_reason="cancelled")

        logger.info("[acp] prompt session=%s text_len=%d", session_id, len(text))

        async with HarvisBridge(self._cfg) as bridge:
            try:
                resp = await bridge.post_inbound_text(
                    chat_id=session_id,
                    sender_id=f"acp:{session_id}",
                    text=text,
                )
            except Exception as e:
                logger.exception("[acp] backend dispatch failed")
                await self._send_agent_text(session_id, f"_(harvis: backend error — {e})_")
                return PromptResponse(stop_reason="cancelled")

            if not resp.get("ok") or not resp.get("workspace_id"):
                err = resp.get("error") or "no workspace_id"
                await self._send_agent_text(session_id, f"_(harvis: rejected — {err})_")
                return PromptResponse(stop_reason="cancelled")

            workspace_id = resp["workspace_id"]
            sess["workspace_id"] = workspace_id
            logger.info("[acp] workspace launched: %s", workspace_id)

            # Stream events while waiting for terminal — parallel coroutines.
            events_task = asyncio.create_task(
                self._stream_events(bridge, workspace_id, session_id),
                name=f"acp-events-{workspace_id}",
            )
            try:
                snap = await bridge.wait_for_terminal(workspace_id)
            finally:
                events_task.cancel()
                try:
                    await events_task
                except (asyncio.CancelledError, Exception):
                    pass

            answer = _format_terminal(snap)
            await self._send_agent_text(session_id, answer)

            stop = "end_turn" if snap.get("status") == "completed" else "cancelled"
            return PromptResponse(stop_reason=stop)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _send_agent_text(self, session_id: str, text: str) -> None:
        if self._conn is None:
            logger.warning("[acp] no conn — dropping agent message %r", text[:80])
            return
        try:
            update = acp.update_agent_message_text(text)
            await self._conn.session_update(session_id, update)
        except Exception:
            logger.exception("[acp] session_update failed")

    async def _send_update(self, session_id: str, update) -> None:
        if self._conn is None:
            logger.warning("[acp] no conn — dropping update %r", type(update).__name__)
            return
        try:
            await self._conn.session_update(session_id, update)
        except Exception:
            logger.exception("[acp] session_update failed")

    # ------------------------------------------------------------------
    # Event streaming (Phase 2C)
    # ------------------------------------------------------------------

    async def _stream_events(self, bridge: HarvisBridge, workspace_id: str, session_id: str) -> None:
        """Poll workspace events and translate them into ACP session updates.

        Cancellation-safe: callers cancel this task once the run is terminal,
        and we swallow CancelledError after one last drain attempt.
        """
        last_seq = 0
        # tool_name -> list of (tool_call_id, seq) — FIFO pairing of tool_call
        # events with their tool_result follow-ups.
        pending: dict[str, list[str]] = {}
        try:
            while True:
                events = await bridge.get_run_events(workspace_id, since=last_seq)
                for ev in events:
                    seq = ev.get("seq", 0)
                    if seq > last_seq:
                        last_seq = seq
                    await self._dispatch_event(session_id, ev, pending)
                await asyncio.sleep(self._cfg.poll_interval_s)
        except asyncio.CancelledError:
            # One last drain so we don't miss the final tool_result that
            # arrived in the same tick as the terminal status update.
            try:
                tail = await bridge.get_run_events(workspace_id, since=last_seq)
                for ev in tail:
                    await self._dispatch_event(session_id, ev, pending)
            except Exception:
                logger.exception("[acp] tail-drain raised")
            raise

    async def _dispatch_event(
        self,
        session_id: str,
        ev: dict,
        pending: dict[str, list[str]],
    ) -> None:
        event_type = ev.get("event_type")
        payload = ev.get("payload") or {}
        seq = ev.get("seq", 0)

        if event_type == "tool_call":
            tool = payload.get("tool", "unknown")
            tcid = f"ws-{seq}"
            pending.setdefault(tool, []).append(tcid)
            args = payload.get("args") or {}
            cmd_preview = args.get("preview") or args.get("command")
            title = f"{tool}" + (f": {cmd_preview[:80]}" if cmd_preview else "")
            await self._send_update(
                session_id,
                acp.start_tool_call(tcid, title, raw_input=args or None),
            )
            return

        if event_type == "tool_result":
            tool = payload.get("tool", "")
            queue = pending.get(tool) or []
            tcid = queue.pop(0) if queue else f"ws-{seq}"
            success = payload.get("success", True)
            status = "completed" if success else "failed"
            await self._send_update(
                session_id,
                acp.update_tool_call(tcid, status=status, raw_output=payload.get("output")),
            )
            return

        if event_type == "log":
            msg = (payload.get("message") or "").strip()
            if msg:
                await self._send_update(
                    session_id,
                    acp.update_agent_thought_text(msg[:500]),
                )
            return

        # agent_start / agent_end / token / done — no-op for ACP for now.
        return
