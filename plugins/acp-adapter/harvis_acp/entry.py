"""CLI entry — boots the Harvis ACP server over stdio.

Logs to stderr only (stdout is owned by the JSON-RPC transport).
"""

from __future__ import annotations

import asyncio
import logging
import sys

import acp

from harvis_acp.config import load_config
from harvis_acp.server import HarvisACPAgent


def _configure_logging() -> None:
    import os
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Optional file sink — useful when the parent process captures stderr
    # (e.g. `spawn_agent_process` does). Set HARVIS_ACP_LOG_FILE to enable.
    log_file = os.getenv("HARVIS_ACP_LOG_FILE")
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        root.addHandler(fh)


async def _run() -> None:
    _configure_logging()
    cfg = load_config()
    logger = logging.getLogger("harvis-acp")
    logger.info(
        "starting harvis-acp backend=%s default_user_id=%s",
        cfg.backend_url,
        cfg.default_user_id,
    )
    if not cfg.gateway_token:
        logger.warning(
            "MESSAGING_GATEWAY_TOKEN not set — prompts will fail at backend auth"
        )

    agent = HarvisACPAgent()
    # acp.run_agent reads JSON-RPC from stdin and writes to stdout.
    await acp.run_agent(agent, use_unstable_protocol=True)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
