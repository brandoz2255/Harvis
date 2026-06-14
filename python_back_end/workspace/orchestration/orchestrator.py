"""P5 orchestrator — the parent that splits a task, spawns isolated sub-agents,
and collects their diffs. v1 spike: ONE sub-agent (rule-based split), one
isolated scratch workspace, diff → artifact, final summary. Yields OpenClawEvents
that flow through workspace_router._run_workspace_bg's normal persist/broadcast
loop, so the RunView / Neural Map render the parent→child tree for free.

The orchestrator AGENT node reuses the launched run id as its run_id, so the
child's parent_run_id (spawn edge in the graph) and the child run row's
parent_run_id (DB tree) are the same value.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import AsyncGenerator

from ..openclaw_client import OpenClawEvent
from .isolation import WorkspaceIsolationManager
from .profiles import get_profile
from .runner import SubAgentRunner

logger = logging.getLogger(__name__)


def simple_task_split(user_task: str) -> list[dict]:
    """Rule-based split (spike: returns exactly one subtask). Model-decided
    planning replaces this in a later phase."""
    low = (user_task or "").lower()
    if any(k in low for k in ("frontend", "ui", "react", "svelte", "css", "html")):
        role = "frontend"
    elif any(k in low for k in ("test", "pytest", "unit test")):
        role = "testing"
    elif any(k in low for k in ("security", "auth", "secret", "vuln")):
        role = "security"
    elif any(k in low for k in ("doc", "readme", "comment")):
        role = "docs"
    else:
        role = "backend"
    return [{"role": role, "task": user_task}]


async def run_orchestrated(
    task_brief: str,
    chat_history: list,
    *,
    model_name: str = "",
    pool=None,
    parent_workspace_id: str = "",
    user_id: int = 0,
    session_id: str = "",
) -> AsyncGenerator[OpenClawEvent, None]:
    # Lazy import (avoid circular import at module load). Import the FUNCTIONS
    # from the submodule path — `from .. import workspace_router` would resolve to
    # the re-exported APIRouter instance in workspace/__init__.py, not the module.
    from ..workspace_router import _db_create_run, _db_save_artifact, _db_complete_run

    # Ensure the parent (launched) run row exists before any event/artifact FK.
    # The launch starts this background task BEFORE its own _db_create_run commits,
    # and the orchestrator emits its first event instantly — for slower event
    # streams the row lands in time, but ours races it. Idempotent (ON CONFLICT).
    await _db_create_run(
        pool, parent_workspace_id, user_id,
        session_id or f"ws-{parent_workspace_id}", task_brief,
    )

    iso = WorkspaceIsolationManager()
    runner = SubAgentRunner()
    orch_run_id = parent_workspace_id  # orchestrator node == the launched run

    def root_ev(etype: str, data: dict) -> OpenClawEvent:
        e = OpenClawEvent(etype, {**data, "agent_label": "Orchestrator Agent", "model": model_name})
        e.run_id = orch_run_id
        e.agent_label = "Orchestrator Agent"
        return e

    yield root_ev("agent_start", {"label": "Orchestrator Agent"})

    subtasks = simple_task_split(task_brief)
    st = subtasks[0]
    role = st["role"]
    profile = get_profile(role)
    child_model = model_name or profile["model_name"]
    label = profile["display_name"]
    child_run_id = uuid.uuid4().hex[:8]

    yield root_ev(
        "log",
        {"message": f"Planned 1 sub-agent: {label} ({role}) on {child_model}."},
    )

    # Isolated workspace + first-class child run row.
    wsinfo = await iso.create_workspace_for_agent(child_run_id, role=role)
    child_start = time.monotonic()
    await _db_create_run(
        pool,
        child_run_id,
        user_id,
        session_id or f"ws-{parent_workspace_id}",
        st["task"],
        parent_run_id=orch_run_id,
        role=role,
        model_provider=profile.get("model_provider", "local"),
        model_name=child_model,
        workspace_path=wsinfo["workspace_path"],
        branch_name=wsinfo["branch_name"],
    )

    child_ok = True
    try:
        async for ev in runner.run(
            run_id=child_run_id,
            parent_run_id=orch_run_id,
            label=label,
            task=st["task"],
            model_name=child_model,
            workspace_path=wsinfo["workspace_path"],
            max_steps=int(profile.get("max_steps", 12)),
            max_runtime_seconds=int(profile.get("max_runtime_seconds", 600)),
        ):
            if ev.type == "agent_end" and (ev.data or {}).get("success") is False:
                child_ok = False
            yield ev
    except Exception as exc:
        logger.warning("orchestrator: sub-agent run failed: %s", exc, exc_info=True)
        child_ok = False

    # Collect diff + changed files → artifacts (attached to the launched run for
    # easy retrieval by the diff card).
    diff = await iso.collect_diff(wsinfo["workspace_path"])
    files = await iso.collect_changed_files(wsinfo["workspace_path"])
    artifact_id = await _db_save_artifact(
        pool, parent_workspace_id, "diff",
        path=wsinfo["branch_name"], content=diff or "(no changes)",
    )
    await _db_save_artifact(
        pool, parent_workspace_id, "changed_files", content="\n".join(files),
    )
    await _db_complete_run(
        pool, child_run_id, "done" if child_ok else "error",
        f"{label}: {len(files)} file(s) changed", None, 0, 0, child_start,
    )

    files_str = ", ".join(files) if files else "no files"
    summary = f"Orchestrated run complete — {label} changed {len(files)} file(s) ({files_str})."
    done = root_ev(
        "done",
        {"summary": summary, "structured_artifact_id": artifact_id, "changed_files": files},
    )
    yield done

    # Scratch dir is ephemeral — the diff is persisted as an artifact.
    await iso.cleanup(wsinfo["workspace_path"])
