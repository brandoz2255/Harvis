"""The teammate coordinator — a thin layer above the loops that already exist.

This is deliberately NOT a new agent loop. It plans, picks who runs each step,
and reports; the actual work is done by the same SubAgentRunner the orchestrator
uses (and, from the multi-engine milestone, by the CLI engine adapters). What it
adds over run_orchestrated is the shape of a teammate's run rather than a code
fan-out:

    restate the goal → plan → run the steps IN ORDER, in ONE workspace →
    hand back a finished thing → say what is worth doing next, and stop.

Three differences from the orchestrator are load-bearing:

  * Steps run sequentially in a SHARED workspace. A teammate's second step
    usually needs the first step's files; the orchestrator's parallel lanes each
    get their own scratch dir, which is right for "frontend and backend at once"
    and wrong for "find the laptops, then put them in a sheet".
  * Every tool call runs under the 'agent' rung, so ordinary work proceeds and
    the four hard limits stop and ask. See risk.gate_decision_ex.
  * The run does not end at the deliverable. It proposes what to do next and
    waits — unless the user said to run through, in which case it keeps going
    and still stops at the hard limits.
"""

from __future__ import annotations

import logging
import re
import time
from typing import AsyncGenerator

from ..openclaw_client import OpenClawEvent
from .conversation import conversation_prefix
from .isolation import WorkspaceIsolationManager
from .profiles import get_profile
from .runner import SubAgentRunner
from .runner import _is_narration
from .tools import COMPUTER_PROMPT, COMPUTER_TOOLS, wire_tool_names

logger = logging.getLogger(__name__)

# The rung every teammate tool call runs under. One rung on purpose — an
# override changes whether the run continues, not what it may do.
AGENT_PERMISSION_MODE = "agent"

# How many proposals the teammate offers when it finishes.
_MAX_SUGGESTIONS = 3

_SUGGEST_PROMPT = """You are a working teammate who has just finished a task.

Goal you were given:
{goal}

What you actually did:
{recap}

Suggest at most 3 concrete next steps that would genuinely help. Each must be
something you could do yourself, phrased as an instruction to yourself, one
sentence, no preamble. If nothing is worth doing next, return an empty list.

Reply with JSON only: {{"suggestions": ["...", "..."]}}"""


def choose_engine(step: dict, preferred: str = "auto") -> str:
    """Which runner executes this step.

    Only the native gated loop exists in this milestone, so this always returns
    "native". It is a real function rather than a constant because the multi-
    engine milestone changes only its body: the dispatch seam in ``_run_step``
    already switches on the answer.
    """
    if preferred and preferred not in ("auto", "native"):
        # An explicitly pinned engine is honoured once its adapter is wired in.
        return "native"
    return "native"


# A goal is split into steps only when the user wrote it as more than one
# thing. The planner is a coding planner ("independent sub-tasks for parallel
# agents"); handed "browse for cats" it invents a cat-scraper. One sentence,
# one step — the teammate's own tool loop is already multi-step.
_MULTI_PART = re.compile(
    r"(?:\bthen\b|\bafter that\b|\bnext,|\bfinally\b|^\s*(?:\d+[.)]|[-*•])\s)",
    re.I | re.M,
)


def multi_part(goal: str) -> bool:
    text = (goal or "").strip()
    if not text:
        return False
    if _MULTI_PART.search(text):
        return True
    return len(text) > 400 and text.count(".") >= 3


def computer_context(agent: dict, *, user_id: int, run_id: str, pool=None) -> dict:
    """What the runner needs to act on this teammate's screen (see
    plugins.agents.computer): whose screen, which run, what the user cleared."""
    autonomy = agent.get("autonomy") or {}
    cleared = autonomy.get("cleared_limits") or []
    return {
        "user_id": int(user_id),
        "agent_id": agent.get("id") or "",
        "run_id": run_id,
        "cleared_limits": [str(c) for c in cleared if c],
        "pool": pool,
    }


def _step_cap(agent: dict) -> int:
    budget = agent.get("budget") or {}
    try:
        return max(1, min(int(budget.get("max_child_runs", 8)), 40))
    except (TypeError, ValueError):
        return 8


def _runner_limits(agent: dict) -> tuple[int, int]:
    budget = agent.get("budget") or {}
    try:
        steps = max(1, min(int(budget.get("max_steps", 12)), 60))
    except (TypeError, ValueError):
        steps = 12
    try:
        minutes = max(1, min(int(budget.get("max_minutes", 30)), 240))
    except (TypeError, ValueError):
        minutes = 30
    return steps, minutes * 60


async def _suggest_next(goal: str, recap: str, model_name: str) -> list[str]:
    """Ask the local planner model what is worth doing next.

    Grounded in what actually happened (``recap`` is built from the steps'
    own summaries), and failure-tolerant: no model, no suggestions, no drama.
    """
    from .planner import _PLANNER_MODELS, _installed, generate_json

    prompt = _SUGGEST_PROMPT.format(goal=goal[:1200], recap=recap[:2500])
    candidates = await _installed(_PLANNER_MODELS)
    if model_name and model_name not in candidates:
        candidates = candidates + [model_name]
    for model in candidates[:3]:
        obj = await generate_json(model, prompt, num_predict=300, temperature=0.4)
        if not obj:
            continue
        raw = obj.get("suggestions")
        if not isinstance(raw, list):
            continue
        out = [" ".join(str(s).split())[:240] for s in raw if str(s).strip()]
        if out:
            return out[:_MAX_SUGGESTIONS]
    return []


async def run_agent_coordinated(
    task_brief: str,
    chat_history: list,
    *,
    agent: dict,
    override: bool = False,
    model_name: str = "",
    pool=None,
    parent_workspace_id: str = "",
    user_id: int = 0,
    session_id: str = "",
    launch_mode: str = "user",
) -> AsyncGenerator[OpenClawEvent, None]:
    from ..workspace_router import (
        _db_complete_run,
        _db_create_run,
        _db_save_artifact,
    )

    # The launch starts this task before its own run row commits; the
    # orchestrator has the same race and the same idempotent fix.
    sess = session_id or f"agent-{agent.get('id', 'x')}"
    await _db_create_run(pool, parent_workspace_id, user_id, sess, task_brief)

    label = (agent.get("title") or agent.get("name") or "Teammate").strip()
    agent_id = agent.get("id") or ""
    run_id = parent_workspace_id

    def root_ev(etype: str, data: dict) -> OpenClawEvent:
        e = OpenClawEvent(
            etype,
            {
                **data,
                "agent_label": label,
                "agent_id": agent_id,
                "agent_name": agent.get("name"),
                "model": model_name,
            },
        )
        e.run_id = run_id
        e.agent_label = label
        return e

    yield root_ev("agent_start", {"label": label})

    # The goal, said back in the teammate's own words. This is the first thing
    # the user sees and it is where a misread goal gets caught — before the
    # agent spends ten minutes doing the wrong job.
    goal_text = (task_brief or "").strip()
    yield root_ev("restated_goal", {
        "restated_goal": goal_text.splitlines()[-1][:400] if goal_text else "",
        "status": "planning",
    })

    # ── Plan ────────────────────────────────────────────────────────────────
    # Reuses the orchestrator's planner (LLM with a keyword-split fallback) so
    # there is exactly one planner in the codebase.
    from .planner import plan_agents

    plan: list = []
    if multi_part(goal_text):
        try:
            plan = await plan_agents(goal_text, model_name=model_name, uniform_model=True)
        except Exception:
            logger.warning("agent coordinator: planner failed, running the goal as one step",
                           exc_info=True)
            plan = []
    if not plan:
        profile = get_profile("backend")
        profile["display_name"] = label
        profile["model_name"] = model_name
        plan = [{"role": "step", "task": goal_text, "profile": profile,
                 "model": model_name, "label": label}]
    plan = plan[: _step_cap(agent)]

    yield root_ev("plan", {
        "steps": [
            {"role": p["role"], "label": p["label"], "model": p["model"], "task": p["task"]}
            for p in plan
        ],
        "uniform": True,
    })

    # ── One workspace for the whole run ─────────────────────────────────────
    iso = WorkspaceIsolationManager()
    wsinfo = await iso.create_workspace_for_agent(run_id, role="agent")
    workspace_path = wsinfo["workspace_path"]
    runner = SubAgentRunner()

    max_steps, max_seconds = _runner_limits(agent)
    allowed = set(agent.get("allowed_tools") or [])
    # A tool allowlist narrows the coding tools; the computer is part of being
    # a teammate, not something to opt into.
    disabled_tools = (
        (wire_tool_names() - allowed - {"finish"} - COMPUTER_TOOLS) if allowed else set()
    )
    computer = computer_context(agent, user_id=user_id, run_id=run_id, pool=pool)

    skill_blocks: list = []
    skill_ids = agent.get("skill_ids") or []
    if skill_ids:
        try:
            from owui_compat.skills import gated_skill_blocks

            skill_blocks = await gated_skill_blocks(pool, user_id, skill_ids)
        except Exception:
            logger.warning("agent coordinator: skill gate failed for %s", label, exc_info=True)

    system_prompt = (agent.get("system_prompt") or "").strip() or None
    if system_prompt:
        # A custom prompt replaces the runner's default wholesale, and the default
        # is where the computer is explained — so the explanation rides along.
        system_prompt = f"{system_prompt}\n\n{COMPUTER_PROMPT}"
    deadline = time.monotonic() + max_seconds
    done_steps: list[dict] = []

    async def _run_step(step: dict, n: int, task_text: str) -> AsyncGenerator[OpenClawEvent, None]:
        """One step: a child run in the shared workspace, on the chosen engine."""
        engine = choose_engine(step, agent.get("engine") or "auto")
        child_run_id = f"{run_id}-s{n}"
        started = time.monotonic()
        await _db_create_run(
            pool, child_run_id, user_id, sess, task_text,
            parent_run_id=run_id,
            role="step",
            model_provider=step["profile"].get("model_provider", "local"),
            model_name=step["model"],
            workspace_path=workspace_path,
            branch_name=wsinfo["branch_name"],
        )
        record = {"n": n, "label": step["label"], "engine": engine, "ok": True,
                  "summary": "", "tool_calls": 0, "run_id": child_run_id}
        done_steps.append(record)

        start_ev = root_ev("step_started", {
            "n": n, "label": step["label"], "engine": engine,
            "status": "running", "step_run_id": child_run_id,
        })
        # The header line belongs to the parent lane, so `run_id` is the parent's.
        # OpenClawEvent.to_sse writes self.run_id over any data["run_id"], which is
        # why the child id travels under its own key — otherwise the card could
        # never match a step's ending to the step that started it.
        start_ev.run_id = run_id
        yield start_ev

        try:
            async for ev in runner.run(
                run_id=child_run_id,
                parent_run_id=run_id,
                label=step["label"],
                task=conversation_prefix(task_text, chat_history),
                model_name=step["model"],
                workspace_path=workspace_path,
                max_steps=max_steps,
                max_runtime_seconds=max(30, int(deadline - time.monotonic())),
                launch_mode=launch_mode,
                permission_mode=AGENT_PERMISSION_MODE,
                system_prompt=system_prompt,
                disabled_tools=disabled_tools,
                skill_blocks=skill_blocks,
                pool=pool,
                user_id=user_id,
                session_id=sess,
                computer=computer,
            ):
                if ev.type == "tool_call":
                    record["tool_calls"] += 1
                elif ev.type == "agent_end":
                    data = ev.data or {}
                    if data.get("summary"):
                        record["summary"] = data["summary"]
                    if data.get("success") is False:
                        record["ok"] = False
                yield ev
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent coordinator: step %s failed: %s", step["label"], exc,
                           exc_info=True)
            record["ok"] = False
            record["summary"] = f"error: {exc}"
            err = OpenClawEvent("agent_end", {
                "label": step["label"], "summary": f"error: {exc}", "success": False,
                "parent_run_id": run_id, "model": step["model"],
            })
            err.run_id = child_run_id
            err.agent_label = step["label"]
            yield err

        await _db_complete_run(
            pool, child_run_id, "done" if record["ok"] else "error",
            record["summary"] or f"{step['label']}: finished",
            None, record["tool_calls"], 0, started,
        )

    # ── Run the plan, in order ──────────────────────────────────────────────
    step_no = 0
    for step in plan:
        if time.monotonic() >= deadline:
            yield root_ev("log", {"message": "Budget reached — stopping here."})
            break
        step_no += 1
        async for ev in _run_step(step, step_no, step["task"]):
            yield ev
        last = done_steps[-1]
        if not last["ok"] and time.monotonic() < deadline:
            # One retry, with what went wrong in front of it. A second failure
            # is reported rather than papered over.
            yield root_ev("log", {"message": f"Retrying: {step['label']}."})
            step_no += 1
            retry_task = (
                f"{step['task']}\n\nA previous attempt failed with: "
                f"{last['summary'][:400]}. Try a different approach."
            )
            async for ev in _run_step(step, step_no, retry_task):
                yield ev

    # ── The deliverable ─────────────────────────────────────────────────────
    diff = await iso.collect_diff(workspace_path)
    files = await iso.collect_changed_files(workspace_path)
    contents = await iso.collect_file_contents(workspace_path)
    if diff:
        await _db_save_artifact(
            pool, run_id, "diff",
            path=f"{label} · {wsinfo['branch_name']}", content=diff,
        )
    for rel, content in contents.items():
        await _db_save_artifact(pool, run_id, "file", path=rel, content=(content or ""))
    await _db_save_artifact(pool, run_id, "changed_files", content="\n".join(files))

    ok = all(bool(s["ok"]) for s in done_steps) if done_steps else False
    # A step that ended on "Let me try a different site" narrated its next move
    # instead of reporting; putting that in the delivery card tells the user
    # nothing and reads like the agent gave up mid-sentence. Say what happened.
    def _recap_line(s: dict) -> str:
        text = " ".join((s["summary"] or "").split())
        if not text or _is_narration(text):
            text = "done" if s.get("ok") else "no result"
        return f"- {s['label']}: {text[:240]}"

    recap_lines = [_recap_line(s) for s in done_steps]
    recap = "\n".join(recap_lines)

    yield root_ev("delivery", {
        "status": "done" if ok else "partial",
        "artifacts": files,
        "touched": len(files),
        "summary": recap,
    })

    # ── What's worth doing next ─────────────────────────────────────────────
    suggestions = await _suggest_next(goal_text, recap, model_name)
    if suggestions:
        yield root_ev("propose_next", {
            "suggestions": suggestions,
            "status": "running" if override else "waiting",
        })

    # With an override the teammate keeps going through its own proposals,
    # still stopping at the hard limits. Without one it stops here, which is
    # the default the user chose when they did not say "just do all of it".
    if override and suggestions:
        for suggestion in suggestions:
            if time.monotonic() >= deadline or step_no >= _step_cap(agent):
                yield root_ev("log", {"message": "Budget reached — stopping here."})
                break
            step_no += 1
            follow = {
                "role": "step",
                "task": suggestion,
                "profile": plan[0]["profile"],
                "model": plan[0]["model"],
                "label": suggestion[:60],
            }
            async for ev in _run_step(follow, step_no, suggestion):
                yield ev
        files = await iso.collect_changed_files(workspace_path)
        yield root_ev("delivery", {
            "status": "done",
            "artifacts": files,
            "touched": len(files),
            "summary": "Ran the follow-ups you cleared me for.",
        })

    await iso.cleanup(workspace_path)

    files_str = ", ".join(files) if files else "no files"
    body = recap or "Nothing to report."
    summary = (
        f"{body}\n\nFiles: {files_str}." if files else body
    )
    if suggestions and not override:
        summary += "\n\nWorth doing next:\n" + "\n".join(f"- {s}" for s in suggestions)

    yield root_ev("done", {
        "summary": summary,
        "changed_files": files,
        "success": ok,
    })
