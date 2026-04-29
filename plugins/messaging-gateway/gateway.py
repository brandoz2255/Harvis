"""Harvis messaging gateway sidecar — main entry.

Architecture
------------
* Loads platform adapters listed in ENABLED_PLATFORMS.
* For each inbound message, calls the Harvis backend via HarvisBridge,
  then polls workspace run status until terminal, then delivers the
  final_summary back to the originating chat via the adapter's send_text.

This is the only orchestration in the sidecar. Per-platform protocol details
live in plugins/messaging-gateway/platforms/<name>.py.

Adapted shape from NousResearch/hermes-agent (MIT) — gateway/run.py.
The Hermes original (~12k LOC) carries session caching, agent lifecycle,
auto-TTS, voice modes, and command interception — none of which apply when
the runtime lives in the Harvis backend.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import List

from bridge import HarvisBridge
from config import GatewayConfig, load_config
from messaging_types import InboundMessage, RunStatus
from platforms.base import BasePlatformAdapter

logger = logging.getLogger("harvis-messaging-gateway")


def _build_adapters(cfg: GatewayConfig) -> List[BasePlatformAdapter]:
    adapters: list[BasePlatformAdapter] = []
    for name in cfg.enabled_platforms:
        if name == "stub":
            if not cfg.stub_enabled:
                logger.info("stub adapter listed in ENABLED_PLATFORMS but STUB_ENABLED=false; skipping")
                continue
            from platforms.stub import StubAdapter
            adapters.append(StubAdapter(cfg))
        elif name == "slack":
            from platforms.slack import SlackAdapter
            adapters.append(SlackAdapter(cfg))
        elif name == "discord":
            from platforms.discord import DiscordAdapter
            adapters.append(DiscordAdapter(cfg))
        else:
            logger.warning("unknown platform %r — skipping", name)
    return adapters


async def _process_inbound(
    bridge: HarvisBridge,
    adapter: BasePlatformAdapter,
    msg: InboundMessage,
) -> None:
    logger.info("[%s] inbound %s text=%r", adapter.name, msg.message_id, (msg.text or "")[:120])

    resp = await bridge.post_inbound(msg)
    if not resp.ok or not resp.workspace_id:
        err = resp.error or "no workspace_id"
        logger.warning("[%s] backend rejected inbound: %s", adapter.name, err)
        await adapter.send_text(
            target=msg.source,
            text=f"_(harvis: rejected — {err})_",
            reply_to_message_id=msg.message_id,
        )
        return

    workspace_id = resp.workspace_id
    logger.info("[%s] workspace launched: %s", adapter.name, workspace_id)

    final = await bridge.wait_for_terminal(workspace_id)
    if final is None:
        await adapter.send_text(
            target=msg.source,
            text="_(harvis: workspace polling failed)_",
            reply_to_message_id=msg.message_id,
        )
        return

    # Phase 4B-post — tell the backend the run reached terminal so it
    # can fire on_session_end + invoke memory provider's
    # extract_from_session. Best-effort; logs on failure.
    try:
        await bridge.notify_terminal(workspace_id)
    except Exception:
        logger.exception("[%s] notify_terminal raised", adapter.name)

    text = _format_terminal(final)
    await adapter.send_text(
        target=msg.source,
        text=text,
        reply_to_message_id=msg.message_id,
    )


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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    if not cfg.gateway_token:
        logger.error("MESSAGING_GATEWAY_TOKEN is not set — refusing to start")
        return

    logger.info("backend=%s platforms=%s", cfg.backend_url, cfg.enabled_platforms)

    adapters = _build_adapters(cfg)
    if not adapters:
        logger.error("no adapters enabled; exiting")
        return

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows / restricted env — fallback handled in container exit.
            pass

    async with HarvisBridge(cfg) as bridge:
        async def inbound_for(adapter, msg):
            await _process_inbound(bridge, adapter, msg)

        adapter_tasks: list[asyncio.Task] = []
        for adapter in adapters:
            adapter.set_inbound(inbound_for)
            adapter_tasks.append(asyncio.create_task(adapter.start(), name=f"adapter-{adapter.name}"))

        # Block until shutdown signal or any adapter dies (whichever first).
        stop_task = asyncio.create_task(stop_event.wait(), name="stop-watcher")
        done, _pending = await asyncio.wait(
            adapter_tasks + [stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in done:
            if t is stop_task:
                continue
            exc = t.exception()
            if exc is not None:
                logger.error("adapter %s exited with error: %s", t.get_name(), exc)

        logger.info("stopping adapters")
        for adapter in adapters:
            try:
                await adapter.stop()
            except Exception:
                logger.exception("adapter stop raised")
        for t in adapter_tasks:
            t.cancel()
        await asyncio.gather(*adapter_tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(_run())
