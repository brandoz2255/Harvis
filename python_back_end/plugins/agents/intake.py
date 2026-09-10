"""The one door into an agent run.

Chat (@teammate), the roster's Run button, a scheduled check-in and a Discord
message all arrive here. One door means one place that builds the brief, one
place that decides the lane id, and one place that records which teammate a run
belongs to — so a run started from Discord behaves exactly like a run started
from chat.
"""

from __future__ import annotations

import logging
from typing import Optional

from . import override as override_mod
from .models import resolve_run_model

logger = logging.getLogger(__name__)

# Lane id handed to the workspace router. The coordinator branch matches on the
# "agent:" prefix; the suffix carries the per-run override flag so no extra
# plumbing is needed through _start_workspace's argument list.
LANE_PREFIX = "agent:"
OVERRIDE_SUFFIX = ":override"


def lane_id(agent_id: str, override: bool) -> str:
    return f"{LANE_PREFIX}{agent_id}{OVERRIDE_SUFFIX if override else ''}"


def parse_lane(agent_lane: str) -> tuple[Optional[str], bool]:
    """('<uuid>', override) from a lane id, or (None, False) if it is not ours."""
    if not agent_lane or not agent_lane.startswith(LANE_PREFIX):
        return None, False
    rest = agent_lane[len(LANE_PREFIX):]
    if rest.endswith(OVERRIDE_SUFFIX):
        return (rest[: -len(OVERRIDE_SUFFIX)] or None), True
    return (rest or None), False


def build_brief(agent: dict, goal: str, *, memories: list[str] | None = None) -> str:
    """The teammate's standing job, then this run's goal.

    The job is what the user wrote when they made the teammate ("watch my
    inbox and draft replies"); the goal is what they want now. Both go in, with
    the goal last so it is the freshest thing the model reads.
    """
    parts: list[str] = []
    name = (agent.get("title") or agent.get("name") or "").strip()
    if name:
        parts.append(f"You are {name}, a teammate working for this user.")
    job = (agent.get("job") or "").strip()
    if job:
        parts.append(f"Your standing job:\n{job}")
    if memories:
        joined = "\n".join(f"- {m}" for m in memories[:12])
        parts.append(f"What you have learned about this user and their work:\n{joined}")
    parts.append(f"Right now they have asked you to:\n{goal.strip()}")
    return "\n\n".join(parts)


async def create_agent_run(
    *,
    request,
    user_id: int,
    agent: dict,
    goal: str,
    override: Optional[bool] = None,
    chat_history: list[dict] | None = None,
    session_id: Optional[str] = None,
    attachments: list[dict] | None = None,
    last_pick: Optional[str] = None,
) -> dict:
    """Start a run for ``agent`` on ``goal``. Returns the launch dict.

    ``override`` None means "read it out of the goal text"; an explicit bool
    (the roster's toggle) wins over the wording. ``last_pick`` is the model the
    user last chose in chat; it stands in when the teammate's own model is
    "auto" (see ``models.resolve_run_model``).
    """
    from workspace.workspace_router import launch_workspace_internal

    agent_id = agent["id"]
    run_override = override_mod.parse_override(goal) if override is None else bool(override)

    memories: list[str] = []
    try:
        from . import memory as agent_memory

        memories = await agent_memory.recall(
            getattr(request.app.state, "pg_pool", None), user_id, agent_id, goal
        )
    except Exception:
        # Memory is an enhancement; a run must not fail because recall did.
        logger.debug("agent memory recall unavailable", exc_info=True)

    brief = build_brief(agent, goal, memories=memories)
    pool = getattr(request.app.state, "pg_pool", None)
    model_name, model_source = await resolve_run_model(
        pool, int(user_id), agent, goal=goal, last_pick=last_pick
    )
    logger.info("agent run model for %s: %r (%s)", agent_id, model_name, model_source)
    launch = await launch_workspace_internal(
        request=request,
        user_id=int(user_id),
        task_brief=brief,
        chat_history=chat_history or [],
        agent_id=lane_id(agent_id, run_override),
        model_name=model_name,
        session_id=session_id or f"agent-{agent_id}",
        attachments=attachments or [],
    )

    # Stamp the run so the roster, the resume path and the audit view can find
    # it. launch_workspace_internal has already created the row, so this is an
    # UPDATE rather than a widened create signature.
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE workspace_runs SET agent_id=$2, source='agent' WHERE id=$1",
                    launch["workspace_id"], agent_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent run stamp failed (%s): %s", launch["workspace_id"], exc)

    launch["agent_id"] = agent_id
    launch["agent_name"] = agent.get("name")
    launch["override"] = run_override
    launch["model"] = model_name
    launch["model_source"] = model_source
    return launch
