"""Harvis messaging gateway sidecar — main entry.

Architecture
------------
* An AdapterSupervisor keeps one adapter per (platform, Harvis user) whose
  settings the backend exports; env-var platforms (ENABLED_PLATFORMS) are
  the fallback. The set is re-read every SETTINGS_SYNC_INTERVAL_S seconds
  and whenever the backend POSTs /resync on the control port.
* For each inbound message, calls the Harvis backend via HarvisBridge,
  then polls workspace run status until terminal, then delivers the
  final_summary back to the originating chat via the adapter's send_text.
* Unknown senders never get an answer: the backend rejects them, the
  gateway files a pairing request for the adapter owner's Messaging page
  and tells the sender once that they are waiting for approval.

Per-platform protocol details live in plugins/messaging-gateway/platforms/.

Adapted shape from NousResearch/hermes-agent (MIT) — gateway/run.py.
The Hermes original (~12k LOC) carries session caching, agent lifecycle,
auto-TTS, voice modes, and command interception — none of which apply when
the runtime lives in the Harvis backend.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time

from bridge import HarvisBridge
from config import GatewayConfig, env_fallback_specs, load_config
from control import ControlServer
from messaging_types import NO_USER_ERROR, InboundMessage, RunStatus
from platforms.base import BasePlatformAdapter
from supervisor import AdapterSupervisor

logger = logging.getLogger("harvis-messaging-gateway")

# One pairing notice per sender per adapter within this window, so an
# unapproved chat cannot make the bot spam the channel.
PAIRING_NOTICE_TTL_S = 6 * 3600


class GatewayRunner:
    def __init__(self, cfg: GatewayConfig, bridge: HarvisBridge):
        self._cfg = cfg
        self._bridge = bridge
        self._pairing_notified: dict[str, float] = {}
        self.supervisor = AdapterSupervisor(self.process_inbound)

    # ------------------------------------------------------------------
    # Settings sync
    # ------------------------------------------------------------------

    async def resync(self) -> dict:
        desired = env_fallback_specs(self._cfg)
        from_backend = await self._bridge.fetch_config() if self._cfg.gateway_token else None
        self.supervisor.last_sync_ok = from_backend is not None
        if from_backend is not None:
            desired = from_backend + desired
            changed = await self.supervisor.sync(desired)
        elif not self.supervisor.adapters():
            # Backend unreachable and nothing running yet: at least honour env.
            changed = await self.supervisor.sync(desired)
        else:
            # Keep the last known set rather than tearing adapters down on a blip.
            changed = {"started": [], "restarted": [], "stopped": []}
        return {"ok": True, "backend_reachable": from_backend is not None, **changed}

    async def sync_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.resync()
            except Exception:
                logger.exception("settings sync failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._cfg.sync_interval_s)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Inbound → backend → reply
    # ------------------------------------------------------------------

    async def process_inbound(self, adapter: BasePlatformAdapter, msg: InboundMessage) -> None:
        logger.info("[%s] inbound %s text=%r", adapter.key, msg.message_id, (msg.text or "")[:120])

        if msg.fallback_user_id is None:
            msg.fallback_user_id = adapter.fallback_user_for(msg.source.sender_id)

        resp = await self._bridge.post_inbound(msg)
        if not resp.ok or not resp.workspace_id:
            err = resp.error or "no workspace_id"
            if err == NO_USER_ERROR:
                await self._pairing_notice(adapter, msg)
                return
            logger.warning("[%s] backend rejected inbound: %s", adapter.key, err)
            await adapter.send_text(
                target=msg.source,
                text=f"_(harvis: rejected — {err})_",
                reply_to_message_id=msg.message_id,
            )
            return

        workspace_id = resp.workspace_id
        logger.info("[%s] workspace launched: %s", adapter.key, workspace_id)

        final = await self._bridge.wait_for_terminal(workspace_id)
        if final is None:
            await adapter.send_text(
                target=msg.source,
                text="_(harvis: workspace polling failed)_",
                reply_to_message_id=msg.message_id,
            )
            return

        # Tell the backend the run reached terminal so it can fire
        # on_session_end + the memory provider's extract_from_session.
        try:
            await self._bridge.notify_terminal(workspace_id)
        except Exception:
            logger.exception("[%s] notify_terminal raised", adapter.key)

        await adapter.send_text(
            target=msg.source,
            text=_format_terminal(final),
            reply_to_message_id=msg.message_id,
        )

    async def _pairing_notice(self, adapter: BasePlatformAdapter, msg: InboundMessage) -> None:
        """Unknown sender: queue a pairing request, answer once, never relay."""
        owner = adapter.owner_user_id
        if owner is None:
            logger.info("[%s] unknown sender %s and no owner to pair with; ignoring",
                        adapter.key, msg.source.sender_id)
            return
        result = await self._bridge.request_pairing(
            owner_user_id=owner,
            platform=adapter.name,
            sender_id=msg.source.sender_id,
            sender_name=msg.source.sender_display_name,
            chat_id=msg.source.chat_id,
        )
        notice_key = f"{adapter.key}|{msg.source.sender_id}"
        now = time.time()
        self._pairing_notified = {k: t for k, t in self._pairing_notified.items() if now - t < PAIRING_NOTICE_TTL_S}
        if notice_key in self._pairing_notified:
            return
        self._pairing_notified[notice_key] = now
        request_id = (result or {}).get("request_id")
        text = "This chat isn't paired with Harvis yet."
        if request_id:
            text += f" Your pairing code is {request_id}. Ask the owner to approve it on the Harvis Messaging page."
        else:
            text += " Ask the owner to approve you on the Harvis Messaging page."
        await adapter.send_text(target=msg.source, text=text, reply_to_message_id=msg.message_id)


def _format_terminal(snap: RunStatus) -> str:
    if snap.status == "completed":
        return snap.final_summary or "_(harvis: completed with no summary)_"
    if snap.status in ("failed", "error"):
        return f"_(harvis: run failed — {snap.error_message or 'no error message'})_"
    if snap.status == "cancelled":
        return "_(harvis: run cancelled)_"
    if snap.status == "timeout":
        return f"_(harvis: timed out — {snap.error_message or ''})_"
    if snap.status == "missing":
        return "_(harvis: run missing in backend)_"
    return f"_(harvis: unknown terminal status {snap.status})_"


async def _run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    logger.info("backend=%s env_platforms=%s sync_every=%ss control_port=%d",
                cfg.backend_url, cfg.enabled_platforms, cfg.sync_interval_s, cfg.control_port)
    if not cfg.gateway_token:
        logger.error("MESSAGING_GATEWAY_TOKEN is not set — the backend will not accept inbound "
                     "messages and settings cannot be pulled. Only env-var adapters will start.")

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    async with HarvisBridge(cfg) as bridge:
        runner = GatewayRunner(cfg, bridge)
        control = ControlServer(token=cfg.gateway_token, port=cfg.control_port,
                                supervisor=runner.supervisor, resync=runner.resync)
        # The stub adapter mounts its /inject route on the control app.
        from platforms import stub as stub_module
        stub_module.CONTROL_APP = control.app

        control_task = asyncio.create_task(control.serve(), name="control-port")
        sync_task = asyncio.create_task(runner.sync_loop(stop_event), name="settings-sync")

        await stop_event.wait()
        logger.info("stopping adapters")
        await runner.supervisor.stop_all()
        control.stop()
        sync_task.cancel()
        await asyncio.gather(control_task, sync_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(_run())
