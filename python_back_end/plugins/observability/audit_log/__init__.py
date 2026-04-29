"""audit_log — Harvis plugin example: log every inbound message dispatch.

Demonstrates the Hermes-style plugin manifest convention adapted for Harvis
(Phase 3B). Module-level functions named after VALID_HOOKS are auto-discovered
and registered by the plugin loader at backend startup.

This plugin observes only — never returns a skip/rewrite directive — so it
won't change dispatch behavior. Useful as a smoke-test for the loader.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("plugin.audit_log")


def pre_gateway_dispatch(*, event=None, user_id=None, **kwargs):  # noqa: ARG001
    platform = getattr(getattr(event, "source", None), "platform", None)
    chat_id = getattr(getattr(event, "source", None), "chat_id", "")
    text_preview = (getattr(event, "text", "") or "")[:80]
    logger.info(
        "audit user=%s platform=%s chat=%s text=%r",
        user_id,
        getattr(platform, "value", platform),
        chat_id,
        text_preview,
    )
