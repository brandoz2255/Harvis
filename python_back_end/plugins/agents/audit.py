"""What the teammate's computer actually did.

The existing approval flow only leaves a trace for actions that needed a human.
For an agent that works while the user is away, the interesting record is the
opposite one: the long tail of actions it took WITHOUT asking. This writes a
row for every gate decision, allowed ones included.

Fail-open by design: an audit write that fails logs a warning and never blocks
the action. A gate that stops working because the audit table is unhappy is a
worse outcome than a gap in the log, and the gap is visible.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Decisions, as stored.
ALLOWED = "allowed"
GATED = "gated"
APPROVED = "approved"
DENIED = "denied"
BLOCKED = "blocked"


def _short(value: Optional[str], limit: int = 500) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


async def record(
    pool,
    *,
    run_id: str,
    agent_id: Optional[str],
    user_id: Optional[int],
    tool: str,
    target: Optional[str] = None,
    tier: Optional[str] = None,
    decision: str = ALLOWED,
    reason: Optional[str] = None,
    approval_id: Optional[str] = None,
) -> None:
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO agent_action_audit "
                "(run_id, agent_id, user_id, tool, target, tier, decision, reason, approval_id) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                run_id,
                agent_id,
                int(user_id) if user_id is not None else None,
                _short(tool, 120) or "",
                _short(target),
                _short(tier, 32),
                _short(decision, 32) or ALLOWED,
                _short(reason),
                _short(approval_id, 200),
            )
    except Exception as exc:  # noqa: BLE001 — never let logging stop the run
        logger.warning("agent audit write failed (run=%s tool=%s): %s", run_id, tool, exc)


async def update_decision(pool, approval_id: str, decision: str) -> None:
    """Close the loop on a gated row once the user answers."""
    if pool is None or not approval_id:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE agent_action_audit SET decision=$2 WHERE approval_id=$1 AND decision=$3",
                approval_id, _short(decision, 32) or DENIED, GATED,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent audit update failed (%s): %s", approval_id, exc)
