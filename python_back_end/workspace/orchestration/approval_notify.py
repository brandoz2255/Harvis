"""Tell the user's live Hermes window that a run is waiting on them.

The runner blocks on ``risk.await_action_outcome`` until a person answers. The
workspace page learns about that by polling ``/pending-action``; the Hermes chat
has no such page, so without a push the run just sat there until it timed out.
These two helpers hand the request to ``plugins.hermes_ui.ws_approvals``, which
knows which websocket belongs to which user and which chat is following which
run. Both are best-effort: a failure to notify must never break the run, and
when no Hermes window is attached the workspace page still works exactly as
before.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

TIMEOUT_NOTICE = (
    "Denied: nobody answered the approval prompt within {minutes} minutes, so "
    "'{tool}' was not run. Ask again if you still want it done."
)


async def announce(user_id, run_ids, action_id: str, tool: str, args: dict,
                   tier: str | None, reason: str | None, *, session_scoped: bool) -> bool:
    """Push an approval request to the owner's Hermes connection(s). True if delivered."""
    if user_id is None:
        return False
    try:
        from plugins.hermes_ui import ws_approvals

        return await ws_approvals.push_request(
            int(user_id), [r for r in run_ids if r], action_id, tool, args or {},
            tier, reason, session_scoped=session_scoped)
    except Exception:
        logger.warning("approval notify failed for %s", action_id, exc_info=True)
        return False


async def withdraw(user_id, action_id: str, approved: bool, *, timed_out: bool = False) -> None:
    """Tell the window the request is over (answered elsewhere, or timed out)."""
    if user_id is None:
        return
    try:
        from plugins.hermes_ui import ws_approvals

        await ws_approvals.push_resolved(int(user_id), action_id, approved, timed_out=timed_out)
    except Exception:
        logger.warning("approval withdraw failed for %s", action_id, exc_info=True)
