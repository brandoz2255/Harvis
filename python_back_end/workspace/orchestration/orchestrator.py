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
from .tools import wire_tool_names

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
    model_pool: list[str] | None = None,
    isolation_mode: str = "scratch",
    repo_config: dict | None = None,
    launch_mode: str = "user",   # "auto" (auto-detected launch) → heavy tools withheld from the offered schema
    single_agent: bool = False,  # Agent-pill turn: ONE agent on the task as written, no planner
) -> AsyncGenerator[OpenClawEvent, None]:
    # Lazy import (avoid circular import at module load). Import the FUNCTIONS
    # from the submodule path — `from .. import workspace_router` would resolve to
    # the re-exported APIRouter instance in workspace/__init__.py, not the module.
    from ..workspace_router import _db_create_run, _db_save_artifact, _db_complete_run, _db_set_run_repo

    # Ensure the parent (launched) run row exists before any event/artifact FK.
    # The launch starts this background task BEFORE its own _db_create_run commits,
    # and the orchestrator emits its first event instantly — for slower event
    # streams the row lands in time, but ours races it. Idempotent (ON CONFLICT).
    await _db_create_run(
        pool, parent_workspace_id, user_id,
        session_id or f"ws-{parent_workspace_id}", task_brief,
    )
    # Persist the attached repo on the parent run (the create above is ON CONFLICT
    # DO NOTHING, so this UPDATE is how repo_path lands) → Create-PR can resolve the
    # GitHub origin + base from the run long after the clone is torn down.
    _attached_repo = (repo_config or {}).get("repo_path")
    if _attached_repo:
        await _db_set_run_repo(pool, parent_workspace_id, _attached_repo)

    # "attached" mode → each sub-agent runs in a git clone-local of the attached repo
    # (real diff vs HEAD); default "scratch" → empty dir + difflib (unchanged).
    iso = WorkspaceIsolationManager(isolation_mode=isolation_mode, repo_config=repo_config)
    runner = SubAgentRunner()
    orch_run_id = parent_workspace_id  # orchestrator node == the launched run
    sess = session_id or f"ws-{parent_workspace_id}"

    # A single-agent run has no crew to orchestrate, so calling the parent node
    # "Orchestrator Agent" would put a coordinator on the graph that never
    # coordinated anything. Same stream, honest label.
    root_label = "Harvis Agent" if single_agent else "Orchestrator Agent"

    def root_ev(etype: str, data: dict) -> OpenClawEvent:
        e = OpenClawEvent(etype, {**data, "agent_label": root_label, "model": model_name})
        e.run_id = orch_run_id
        e.agent_label = root_label
        return e

    def _pick_model(profile: dict) -> str:
        if uniform_model:
            return model_name or profile.get("model_name") or "gemma4:e2b"
        return profile.get("model_name") or model_name or "gemma4:e2b"

    yield root_ev("agent_start", {"label": root_label})

    if single_agent:
        # Agent-pill turn: ONE agent, on the task exactly as the user wrote it. The
        # planner is skipped rather than asked for a plan of one — it costs an extra
        # model round-trip, and its whole job is splitting work that this lane has
        # already decided not to split. "Read this page and tell me X" is one agent's
        # job; fanning it into a frontend/backend/testing crew is noise on the graph.
        profile = get_profile("backend")  # the generic coding profile (tools + limits)
        profile["display_name"] = "Harvis Agent"
        profile["model_name"] = model_name
        plan = [{
            "role": "agent",
            "task": task_brief,
            "profile": profile,
            "model": model_name,
            "label": "Harvis Agent",
        }]
        yield root_ev("log", {"message": f"Running one agent on {model_name}."})
    else:
        # LLM task-delegation: split the task into N **task-named** sub-agents (3–10,
        # scaling to complexity), each on its own model. Replaces the old rule-based
        # frontend/backend/testing keyword split; falls back to it on any LLM failure.
        # See planner.plan_agents. (`_pick_model` above is the uniform/per-role policy
        # the planner now applies internally.)
        from .planner import plan_agents
        from .subagent_defs import load_subagents
        # Custom sub-agents (Customize → Sub-agents): the planner uses their name+description
        # roster to auto-delegate a step to the right specialist; each resolved profile then
        # carries that sub-agent's model / system prompt / tool-allowlist / skills / connectors.
        subagents = await load_subagents(pool, user_id)
        plan = await plan_agents(
            task_brief, model_name=model_name, uniform_model=uniform_model,
            model_pool=model_pool, subagents=subagents,
        )

        planned = "; ".join(f"{p['label']} on {p['model']}" for p in plan)
        mode_note = " (uniform model)" if uniform_model else ""
        yield root_ev(
            "log",
            {"message": f"Planned {len(plan)} sub-agent(s){mode_note}: {planned}."},
        )
    # Structured plan for the VibeCode right-rail Plan panel — the log above is the
    # human line; this carries the steps so the UI can render per-step status.
    yield root_ev("plan", {
        "steps": [
            {"role": p["role"], "label": p["label"], "model": p["model"], "task": p["task"]}
            for p in plan
        ],
        "uniform": uniform_model,
    })

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
                    launch_mode=launch_mode,
                    system_prompt=child.get("system_prompt"),
                    disabled_tools=child.get("disabled_tools"),
                    skill_blocks=child.get("skill_blocks"),
                    pool=pool,
                    user_id=user_id,
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
            "tool_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
        # ── Custom sub-agent equipment (empty for generic delegated agents) ──
        # allowed_tools is an ALLOWLIST → invert to the runner's offer-time WITHHOLD set
        # (all offered - allowed - finish). authorize_action stays the dispatch authority.
        prof = p["profile"]
        _allowed = set(prof.get("allowed_tools") or [])
        child["disabled_tools"] = (wire_tool_names() - _allowed - {"finish"}) if _allowed else set()
        child["system_prompt"] = (prof.get("system_prompt") or "") or None
        # Sub-agent skills through the SAME fail-closed gate as chat (human 'supported'
        # verdict etc.). No capability resolver in the run context → capability-gated
        # skills honestly degrade to an 'unavailable' note rather than injecting a body.
        _skill_ids = prof.get("skill_ids") or []
        child["skill_blocks"] = []
        if _skill_ids:
            try:
                from owui_compat.skills import gated_skill_blocks
                child["skill_blocks"] = await gated_skill_blocks(pool, user_id, _skill_ids)
            except Exception:
                logger.warning("orchestrator: sub-agent skill gate failed for %s", p["label"], exc_info=True)
        # Connectors are stored + surfaced but NOT live in runs yet (Phase G) unless
        # HARVIS_MCP_LIVE — say so honestly instead of silently dropping them.
        _mcp_ids = prof.get("mcp_ids") or []
        if _mcp_ids and os.getenv("HARVIS_MCP_LIVE", "").lower() not in ("1", "true", "yes", "on"):
            yield root_ev("log", {
                "message": f"{p['label']}: {len(_mcp_ids)} connector(s) attached (config only) — "
                           "live MCP tool-calling is deferred.",
            })
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
        rid = getattr(item, "run_id", None)
        if item.type == "tool_call":
            c = child_by_run.get(rid)
            if c:
                c["tool_calls"] += 1  # per-agent Tools column for the Background-tasks table
        elif item.type == "agent_end":
            c = child_by_run.get(rid)
            if c:
                data = item.data or {}
                # Capture the sub-agent's own finish() summary + real token usage for its row.
                if data.get("summary"):
                    c["summary"] = data["summary"]
                if data.get("success") is False:
                    c["ok"] = False
                c["prompt_tokens"] = int(data.get("prompt_tokens") or 0)
                c["completion_tokens"] = int(data.get("completion_tokens") or 0)
        yield item

    # ── Collect each sub-agent's diff → its own artifact; complete its run row;
    # clean up its scratch dir. ────────────────────────────────────────────────
    all_files: list[str] = []
    for c in children:
        ws_path = c["wsinfo"]["workspace_path"]
        diff = await iso.collect_diff(ws_path)
        files = await iso.collect_changed_files(ws_path)
        contents = await iso.collect_file_contents(ws_path)  # before cleanup wipes the dir
        all_files += files
        await _db_save_artifact(
            pool, parent_workspace_id, "diff",
            path=f"{c['label']} · {c['wsinfo']['branch_name']}",
            content=diff or "(no changes)",
        )
        # Full file contents → 'file' artifacts so the UI can PREVIEW (render the
        # page), not just show a diff. Capped; the frontend picks the primary one.
        for rel, content in contents.items():
            await _db_save_artifact(
                pool, parent_workspace_id, "file",
                path=rel, content=(content or ""),
            )
        # Prefer the sub-agent's own finish() summary (captured from its agent_end)
        # so the run tree / history / Neural Map show what it actually did; fall
        # back to a generic file-count line.
        child_summary = c.get("summary") or f"{c['label']}: {len(files)} file(s) changed"
        await _db_complete_run(
            pool, c["run_id"], "done" if c["ok"] else "error",
            child_summary, None, c["tool_calls"], 0, c["start"],
            prompt_tokens=c["prompt_tokens"], completion_tokens=c["completion_tokens"],
        )
        await iso.cleanup(ws_path)

    await _db_save_artifact(
        pool, parent_workspace_id, "changed_files", content="\n".join(all_files),
    )

    files_str = ", ".join(all_files) if all_files else "no files"
    n = len(children)
    # A LONE agent's summary is the answer itself, not one row of a roll-up. The recap
    # below collapses each summary to a single line and clips it at 240 chars, which is
    # right for "here's what each of my four agents did" and destroys "here's the answer
    # to your question": a 2,984-char reply reached the user as 237 chars ending mid-word
    # ("…current details reg…"), and because the Build Narrator embeds this same string
    # under "What I did", the truncation was all the user ever saw. Auto mode now runs
    # single_agent=True, so this is the common path, not an edge case.
    if n == 1:
        c = children[0]
        answer = (c.get("summary") or "").strip()
        if not answer:
            answer = "Done." if c.get("ok") else "The agent didn't finish cleanly."
        # Whole, with its markdown intact. The file line only earns space when there
        # are files — a question answered in chat shouldn't open with "changed 0 files".
        summary = (
            f"Changed {len(all_files)} file{'s' if len(all_files) != 1 else ''} "
            f"({files_str}).\n\n{answer}"
            if all_files
            else answer
        )
    else:
        # Conversational results recap — the orchestrator "talking back" to the user about
        # what each agent did, built from the sub-agents' OWN finish() summaries (grounded,
        # no extra LLM call / no fabrication). The frontend renders the markdown list.
        parts: list[str] = []
        for c in children:
            label = c.get("label") or c.get("role") or "agent"
            s = " ".join((c.get("summary") or "").split())  # collapse to one line
            if len(s) > 240:
                s = s[:237].rstrip() + "…"
            if s:
                parts.append(f"- **{label}** — {s}")
            elif c.get("ok"):
                parts.append(f"- **{label}** — done.")
            else:
                parts.append(f"- **{label}** — didn't finish cleanly.")
        summary = (
            f"Done! I ran {n} agents and changed "
            f"{len(all_files)} file{'s' if len(all_files) != 1 else ''}"
            + (f" ({files_str})" if all_files else "")
            + ".\n\nHere's what each did:\n\n"
            + "\n".join(parts)
        )
    # The run reached its end, which is not the same as the work succeeding. Every
    # child could have died and this still emitted a bare 'done' — the run row said
    # "done" and the narrator headline said "**Build complete**" over a run the user
    # watched fail. Report it; the router decides what to do with it.
    yield root_ev("done", {
        "summary": summary,
        "changed_files": all_files,
        "success": all(bool(c.get("ok")) for c in children),
    })
