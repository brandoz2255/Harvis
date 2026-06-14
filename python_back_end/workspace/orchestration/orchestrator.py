"""P5 orchestrator — the parent that splits a task, spawns isolated sub-agents,
and collects their diffs.

Multi-agent: a rule-based split fans the task into N role sub-agents, each run
CONCURRENTLY in its own isolated scratch workspace on its own model. Their events
are multiplexed into one stream so the existing
workspace_router._run_workspace_bg persist/broadcast loop renders the parent →
many-children tree (one lane per sub-agent, spawn edges, model badges) for free.
Each sub-agent's diff is collected as its own artifact; the final summary
aggregates across all of them.

The orchestrator AGENT node reuses the launched run id as its run_id, so every
child's parent_run_id (spawn edge in the graph) and the child run row's
parent_run_id (DB tree) share that one value.

Per-agent models: by default each sub-agent uses ITS ROLE PROFILE's model
(heterogeneous). When `uniform_model=True`, every sub-agent is forced onto the
chat-selected `model_name` (the "use one model for all sub-agents" toggle).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import AsyncGenerator

from ..openclaw_client import OpenClawEvent
from .isolation import WorkspaceIsolationManager
from .profiles import get_profile
from .runner import SubAgentRunner

logger = logging.getLogger(__name__)

# How many sub-agents may run at once. The dev box is an 8GB GPU and each lane
# loads its own small model, so cap concurrency to avoid thrashing VRAM. Queued
# sub-agents start (and appear in the graph) as slots free up.
_MAX_PARALLEL = max(1, int(os.getenv("HARVIS_ORCH_MAX_PARALLEL", "3")))

# Keyword → role rules. A task that spans several areas spawns one agent per area.
_ROLE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("frontend", ("frontend", "ui", "react", "svelte", "css", "html", "component", "page", "tailwind")),
    ("backend", ("backend", "api", "fastapi", "endpoint", "route", "server", "database", "db", "sql", "schema")),
    ("testing", ("test", "pytest", "unit test", "coverage", "spec")),
    ("security", ("security", "auth", "secret", "vuln", "sanitiz", "csrf", "injection")),
    ("docs", ("doc", "docs", "readme", "comment", "docstring", "changelog")),
]

_ROLE_TASK_FRAMING = {
    "frontend": "Handle the frontend / UI portion of this task: {task}",
    "backend": "Handle the backend / API portion of this task: {task}",
    "testing": "Write and run the tests for this task: {task}",
    "security": "Review and harden the security aspects of this task: {task}",
    "docs": "Write the documentation for this task: {task}",
}


def simple_task_split(user_task: str) -> list[dict]:
    """Rule-based multi-role split. Returns one subtask per area the task spans
    (capped at 4); falls back to a single backend agent for an atomic task.
    Model-decided planning replaces this in a later phase."""
    low = (user_task or "").lower()
    roles = [role for role, kws in _ROLE_RULES if any(k in low for k in kws)]
    # De-dup preserving order, cap at 4 lanes.
    seen: set[str] = set()
    roles = [r for r in roles if not (r in seen or seen.add(r))][:4]
    if not roles:
        roles = ["backend"]
    if len(roles) == 1:
        # Single area → run the whole task as-is (no role re-framing noise).
        return [{"role": roles[0], "task": user_task}]
    return [
        {"role": r, "task": _ROLE_TASK_FRAMING.get(r, "{task}").format(task=user_task)}
        for r in roles
    ]


async def run_orchestrated(
    task_brief: str,
    chat_history: list,
    *,
    model_name: str = "",
    pool=None,
    parent_workspace_id: str = "",
    user_id: int = 0,
    session_id: str = "",
    uniform_model: bool = False,
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
    sess = session_id or f"ws-{parent_workspace_id}"

    def root_ev(etype: str, data: dict) -> OpenClawEvent:
        e = OpenClawEvent(etype, {**data, "agent_label": "Orchestrator Agent", "model": model_name})
        e.run_id = orch_run_id
        e.agent_label = "Orchestrator Agent"
        return e

    def _pick_model(profile: dict) -> str:
        if uniform_model:
            return model_name or profile.get("model_name") or "gemma4:e2b"
        return profile.get("model_name") or model_name or "gemma4:e2b"

    yield root_ev("agent_start", {"label": "Orchestrator Agent"})

    # Resolve role → model up front so the plan line is accurate before we spawn.
    plan: list[dict] = []
    for st in simple_task_split(task_brief):
        profile = get_profile(st["role"])
        plan.append({
            "role": st["role"],
            "task": st["task"],
            "profile": profile,
            "model": _pick_model(profile),
            "label": profile["display_name"],
        })

    planned = "; ".join(f"{p['label']} on {p['model']}" for p in plan)
    mode_note = " (uniform model)" if uniform_model else ""
    yield root_ev(
        "log",
        {"message": f"Planned {len(plan)} sub-agent(s){mode_note}: {planned}."},
    )

    # ── Spawn each sub-agent: isolated workspace + first-class child run row +
    # a drain task feeding a shared queue. ─────────────────────────────────────
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()
    sem = asyncio.Semaphore(_MAX_PARALLEL)
    children: list[dict] = []

    async def _drain(child: dict) -> None:
        # Cap concurrency: a queued sub-agent emits nothing (and stays absent
        # from the graph) until it acquires a slot.
        async with sem:
            try:
                async for ev in runner.run(
                    run_id=child["run_id"],
                    parent_run_id=orch_run_id,
                    label=child["label"],
                    task=child["task"],
                    model_name=child["model"],
                    workspace_path=child["wsinfo"]["workspace_path"],
                    max_steps=int(child["profile"].get("max_steps", 12)),
                    max_runtime_seconds=int(child["profile"].get("max_runtime_seconds", 600)),
                ):
                    await queue.put(ev)
            except Exception as exc:
                logger.warning(
                    "orchestrator: sub-agent %s failed: %s", child["label"], exc, exc_info=True
                )
                err = OpenClawEvent(
                    "agent_end",
                    {
                        "label": child["label"],
                        "summary": f"error: {exc}",
                        "success": False,
                        "parent_run_id": orch_run_id,
                        "model": child["model"],
                    },
                )
                err.run_id = child["run_id"]
                err.agent_label = child["label"]
                await queue.put(err)
            finally:
                await queue.put(sentinel)

    tasks: list[asyncio.Task] = []
    for p in plan:
        child_run_id = uuid.uuid4().hex[:8]
        wsinfo = await iso.create_workspace_for_agent(child_run_id, role=p["role"])
        await _db_create_run(
            pool,
            child_run_id,
            user_id,
            sess,
            p["task"],
            parent_run_id=orch_run_id,
            role=p["role"],
            model_provider=p["profile"].get("model_provider", "local"),
            model_name=p["model"],
            workspace_path=wsinfo["workspace_path"],
            branch_name=wsinfo["branch_name"],
        )
        child = {
            "run_id": child_run_id,
            "role": p["role"],
            "label": p["label"],
            "model": p["model"],
            "wsinfo": wsinfo,
            "profile": p["profile"],
            "task": p["task"],
            "start": time.monotonic(),
            "ok": True,
        }
        children.append(child)
        tasks.append(asyncio.create_task(_drain(child)))

    # ── Multiplex: yield every sub-agent event as it arrives; count sentinels to
    # know when all lanes have finished. ───────────────────────────────────────
    child_by_run = {c["run_id"]: c for c in children}
    remaining = len(tasks)
    while remaining > 0:
        item = await queue.get()
        if item is sentinel:
            remaining -= 1
            continue
        if item.type == "agent_end" and (item.data or {}).get("success") is False:
            c = child_by_run.get(getattr(item, "run_id", None))
            if c:
                c["ok"] = False
        yield item

    # ── Collect each sub-agent's diff → its own artifact; complete its run row;
    # clean up its scratch dir. ────────────────────────────────────────────────
    all_files: list[str] = []
    for c in children:
        diff = await iso.collect_diff(c["wsinfo"]["workspace_path"])
        files = await iso.collect_changed_files(c["wsinfo"]["workspace_path"])
        all_files += files
        await _db_save_artifact(
            pool, parent_workspace_id, "diff",
            path=f"{c['label']} · {c['wsinfo']['branch_name']}",
            content=diff or "(no changes)",
        )
        await _db_complete_run(
            pool, c["run_id"], "done" if c["ok"] else "error",
            f"{c['label']}: {len(files)} file(s) changed", None, 0, 0, c["start"],
        )
        await iso.cleanup(c["wsinfo"]["workspace_path"])

    await _db_save_artifact(
        pool, parent_workspace_id, "changed_files", content="\n".join(all_files),
    )

    files_str = ", ".join(all_files) if all_files else "no files"
    n = len(children)
    summary = (
        f"Orchestrated run complete — {n} agent{'s' if n != 1 else ''} "
        f"changed {len(all_files)} file(s) ({files_str})."
    )
    yield root_ev("done", {"summary": summary, "changed_files": all_files})
