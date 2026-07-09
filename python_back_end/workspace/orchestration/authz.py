"""Lane-unification choke point (Execution Core Phase 2).

ONE function — ``authorize_action`` — that every execution path calls before
dispatching a tool. It composes the two previously-separate policy layers:

1. **LANE GATE** (structural, ``owui_compat.workspace_method``): which of the 6
   permission lanes the tool lives in, and whether that lane is enabled in this
   deployment. Lanes 1-3 (UI/mock, workspace files, sandbox terminal) are always
   enabled. Lanes 4-6 need an env flag — and in v0: lane 4 (host shell) is
   PARKED (denied regardless of flag), lane 6 (real hardware) is unconditionally
   denied. This is the dormant 6-lane enforcer, now actually wired.
2. **FRICTION GATE** (per-action risk, ``.risk``): the plan/ask/auto-accept/
   full-auto permission ladder → allow / gate (needs human approval) / block.
   Exactly the same ``gate_decision`` semantics the runner used before — when
   ``permission_mode`` is falsy the friction gate is skipped entirely,
   preserving the pre-Phase-2 behavior byte-for-byte.

The RUNNER still owns the approval machinery (``register_pending`` /
``approval_request`` event / ``await_action_decision``) — ``authorize_action``
only DECIDES, and records exactly ONE 'decision' trace event per action through
the caller-supplied ``emit`` callback (sync or async; the runner turns the
payload into a 'decision' OpenClawEvent on its normal event pipeline).
"""

from __future__ import annotations

import inspect
import logging
import os
from dataclasses import dataclass

from owui_compat.workspace_method import (
    DEFAULT_SAFE_LANE,
    LANE_EXTERNAL_SERVICES,
    LANE_LOCAL_DESKTOP,
    tool_can_execute,
)

from .risk import gate_decision

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class AuthzResult:
    """The single authorization verdict for one tool action.

    ``tier`` is the risk tier from the friction gate ('low'|'med'|'high') and is
    None when the friction gate never ran — so on a deny, ``tier is None`` means
    the STRUCTURAL lane gate denied (new lane>3 path) while a non-None tier
    means the risk ladder blocked it (the pre-existing plan-mode block).
    """

    allowed: bool
    reason: str = ""
    tier: str | None = None
    needs_approval: bool = False


def _lane_flag_enabled(lane: int) -> bool:
    """Deployment-level enablement per lane. Lanes 1-3 are always on; higher
    lanes each map to an env flag (truthy set: 1/true/yes/on)."""
    if lane <= DEFAULT_SAFE_LANE:
        return True
    if lane == LANE_LOCAL_DESKTOP:
        # v0: host shell is PARKED — HARVIS_EXEC_HOST_SHELL is reserved as the
        # future enabling flag, but we return False regardless so no code path
        # can reach the host shell until it is deliberately built + reviewed.
        return False
    if lane == LANE_EXTERNAL_SERVICES:
        return (os.getenv("HARVIS_SSH_ENABLED") or "").strip().lower() in _TRUTHY
    # Lane 6 (real hardware) and anything unrecognized: unconditional deny in v0.
    return False


async def _emit_decision(emit, payload: dict) -> None:
    """Fire the caller's emit callback (sync or async). A trace event must never
    be able to break the run, so failures are logged and swallowed."""
    if emit is None:
        return
    try:
        res = emit(payload)
        if inspect.isawaitable(res):
            await res
    except Exception as exc:
        logger.warning("authz decision emit failed: %s", exc)


async def authorize_action(
    *,
    tool_name: str,
    args: dict,
    lane: int,
    permission_mode: str | None,
    run_id: str,
    emit,
) -> AuthzResult:
    """The choke point: lane gate first, then the friction gate. Emits exactly
    one 'decision' payload {tool, lane, tier, policy, reason, source} per call."""

    # ── a. LANE GATE (structural) ─────────────────────────────────────────
    tool = {
        "key": tool_name,
        "label": tool_name,
        "lane": lane,
        "status": "ready",
        "approval": False,
    }
    ok, reason = tool_can_execute(tool, flag_enabled=_lane_flag_enabled(lane), approved=False)
    if not ok:
        await _emit_decision(emit, {
            "tool": tool_name, "lane": lane, "tier": None,
            "policy": "deny", "reason": reason, "source": "lane_gate",
        })
        return AuthzResult(allowed=False, reason=reason, tier=None, needs_approval=False)

    # ── b. FRICTION GATE (permission ladder) ──────────────────────────────
    # Only when permission_mode is set — clone-mode + the orchestrator pass
    # None and have never been risk-gated; that behavior is preserved.
    if permission_mode:
        decision, tier = gate_decision(tool_name, args, permission_mode)
        if decision == "block":
            reason = f"blocked by permission mode '{permission_mode}' (risk: {tier})"
            await _emit_decision(emit, {
                "tool": tool_name, "lane": lane, "tier": tier,
                "policy": "deny", "reason": reason, "source": "risk_gate",
            })
            return AuthzResult(allowed=False, reason=reason, tier=tier, needs_approval=False)
        if decision == "gate":
            await _emit_decision(emit, {
                "tool": tool_name, "lane": lane, "tier": tier,
                "policy": "gate", "reason": "requires human approval", "source": "risk_gate",
            })
            return AuthzResult(allowed=True, reason="requires human approval", tier=tier, needs_approval=True)
        await _emit_decision(emit, {
            "tool": tool_name, "lane": lane, "tier": tier,
            "policy": "allow", "reason": "", "source": "risk_gate",
        })
        return AuthzResult(allowed=True, reason="", tier=tier, needs_approval=False)

    # No permission_mode → friction gate skipped (pre-existing semantics);
    # the lane gate alone decided.
    await _emit_decision(emit, {
        "tool": tool_name, "lane": lane, "tier": None,
        "policy": "allow", "reason": "", "source": "lane_gate",
    })
    return AuthzResult(allowed=True, reason="", tier=None, needs_approval=False)
