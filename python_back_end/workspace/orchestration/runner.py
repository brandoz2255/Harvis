"""Native sub-agent runner — the in-process agent tool-loop for P5.

One step = ModelRouter completion (with tool schema) → parse tool_calls →
dispatch via tools.py inside the isolated workspace → feed results back → repeat
until the agent calls finish() / stops emitting tool calls / hits a limit.
Emits OpenClawEvents tagged run_id/parent_run_id/agent_label/model, so the
existing persistence + RunView / Neural Map render it with no changes.

Tool results are fed back as a plain user turn (not the strict OpenAI tool-role
protocol) — more robust across heterogeneous local models, which is the recurring
Harvis tool-call-discipline concern.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import AsyncGenerator

from ..openclaw_client import OpenClawEvent
from .model_router import ModelRouter
from .risk import await_action_decision, gate_decision, register_pending
from .tools import TOOL_SCHEMA, dispatch_tool, parse_tool_calls

logger = logging.getLogger(__name__)

# No-progress guard: how many consecutive steps with ZERO file change before we
# stop a churning sub-agent (the finish-reluctance loop — re-reading/re-writing
# the same file without ever calling finish). Tunable via env.
_MAX_IDLE_STEPS = max(1, int(os.getenv("HARVIS_ORCH_MAX_IDLE_STEPS", "3")))
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
_BASELINE_FILE = ".harvis-baseline.json"


def _ws_fingerprint(path: str) -> str:
    """SHA-256 over every (small) file in the workspace — lets the runner detect
    when an agent has stopped producing real changes."""
    h = hashlib.sha256()
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fn in sorted(files):
                if fn == _BASELINE_FILE:
                    continue
                fp = os.path.join(root, fn)
                try:
                    h.update(os.path.relpath(fp, path).encode("utf-8", "replace"))
                    with open(fp, "rb") as f:
                        h.update(f.read(256 * 1024))
                except Exception:
                    continue
    except Exception:
        return ""
    return h.hexdigest()


_SYSTEM = (
    "You are {label}, an autonomous coding sub-agent working in an ISOLATED, "
    "initially-empty workspace directory. You can ONLY use the provided tools, and "
    "ONLY touch files inside your workspace using RELATIVE paths. Create new files "
    "with edit_file. To CHANGE a file you already created, use str_replace (it "
    "edits a snippet and keeps the rest intact) rather than rewriting the whole "
    "file. Optionally run exec / run_tests to check your work. Do NOT ask "
    "questions. When the task is fully done, call finish with a one-line summary."
)


class SubAgentRunner:
    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    async def run(
        self,
        *,
        run_id: str,
        parent_run_id: str,
        label: str,
        task: str,
        model_name: str,
        workspace_path: str,
        max_steps: int = 12,
        max_runtime_seconds: int = 600,
        system_prompt: str | None = None,
        permission_mode: str | None = None,
    ) -> AsyncGenerator[OpenClawEvent, None]:
        def ev(etype: str, data: dict) -> OpenClawEvent:
            e = OpenClawEvent(
                etype,
                {**data, "agent_label": label, "parent_run_id": parent_run_id, "model": model_name},
            )
            e.run_id = run_id
            e.agent_label = label
            return e

        started = time.monotonic()
        yield ev("agent_start", {"label": label})

        messages = [
            {"role": "system", "content": (system_prompt or _SYSTEM).format(label=label)},
            {"role": "user", "content": task},
        ]
        summary = ""
        ok_overall = True
        steps = 0
        last_fp = _ws_fingerprint(workspace_path)  # baseline (empty scratch dir)
        made_edit = False
        idle = 0
        action_seq = 0  # per-action ids for the in-place permission gate
        # Token accounting (real OpenAI usage surfaced by ModelRouter). The LAST step's
        # prompt_tokens ≈ current context occupancy; completion/total accumulate over steps.
        last_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens_sum = 0
        ctx_window = int(os.getenv("HARVIS_OLLAMA_NUM_CTX", "24576") or 24576)

        try:
            while steps < max_steps and (time.monotonic() - started) < max_runtime_seconds:
                steps += 1
                msg = await self.router.complete(
                    model_name=model_name, messages=messages, tools=TOOL_SCHEMA, temperature=0.2
                )
                _usage = msg.get("_usage") or {}
                if _usage:
                    last_prompt_tokens = int(_usage.get("prompt_tokens") or last_prompt_tokens)
                    total_completion_tokens += int(_usage.get("completion_tokens") or 0)
                    total_tokens_sum += int(_usage.get("total_tokens") or 0)
                content = (msg.get("content") or "").strip()
                tcs = parse_tool_calls(msg)

                if not tcs:
                    # No tool call → the model is done (its content is the summary).
                    if content:
                        yield ev("token", {"content": content[:600]})
                    summary = content or summary or "Task complete."
                    break

                if content:
                    yield ev("token", {"content": content[:600]})

                results_text: list[str] = []
                finished = False
                for tc in tcs:
                    name, args = tc["name"], tc["args"]
                    if name == "finish":
                        summary = str(args.get("summary") or "Task complete.")
                        finished = True
                        break
                    yield ev("tool_call", {"tool": name, "args": args})
                    # In-place permission gate. Only active when permission_mode is set
                    # (in-place sessions); clone-mode + the orchestrator pass None → no
                    # gating, byte-for-byte unchanged.
                    if permission_mode:
                        decision, tier = gate_decision(name, args, permission_mode)
                        if decision == "block":
                            msg_b = (
                                f"BLOCKED: '{name}' was NOT executed. This turn is PLAN MODE "
                                "(read-only) — every edit and command will fail, so do NOT "
                                "retry it or try another edit. Call finish NOW with `summary` "
                                "= a NUMBERED plan written in PLAIN ENGLISH: one FULL SENTENCE "
                                "per step saying what you would change and why, naming files in "
                                "words (e.g. \"1. Add a SUMMARY.md at the repo root describing "
                                "what hello.txt contains.\"). Do NOT put tool calls, function "
                                "names, JSON, or code in the plan — describe each step in words."
                            )
                            yield ev("tool_result", {"output": msg_b, "success": False})
                            results_text.append(f"{name} BLOCKED (plan mode) — finish with a plan instead")
                            continue
                        if decision == "gate":
                            action_seq += 1
                            action_id = f"{run_id}-{steps}-{action_seq}"
                            register_pending(action_id, {"tool": name, "args": args, "risk": tier})
                            yield ev("approval_request", {
                                "action_id": action_id, "tool": name, "args": args, "risk": tier,
                            })
                            approved = await await_action_decision(action_id)
                            yield ev("approval_resolved", {"action_id": action_id, "approved": approved})
                            if not approved:
                                yield ev("tool_result", {"output": "Denied by the user.", "success": False})
                                results_text.append(f"{name} DENIED by user")
                                continue
                    result, ok = await dispatch_tool(workspace_path, name, args)
                    if not ok:
                        ok_overall = False
                    # Count as a real edit only AFTER a successful dispatch — a blocked
                    # (Plan) or denied (Ask) edit never reached the filesystem, so it must
                    # not trip the no-progress guard.
                    if ok and name in ("edit_file", "str_replace", "write"):
                        made_edit = True
                    yield ev("tool_result", {"output": result, "success": ok})
                    results_text.append(
                        f"{name}({json.dumps(args)[:140]}) -> {result[:500]}"
                    )
                if finished:
                    break

                # ── No-progress guard: stop the finish-reluctance churn (the model
                # re-reading / re-writing the same file without ever calling finish).
                # Only after a real edit, and only when the workspace has been
                # unchanged for _MAX_IDLE_STEPS in a row — so edit→test→edit loops
                # (which DO change files) keep going. ──────────────────────────────
                fp = _ws_fingerprint(workspace_path)
                idle = idle + 1 if fp == last_fp else 0
                last_fp = fp
                if made_edit and idle >= _MAX_IDLE_STEPS:
                    summary = summary or (
                        f"Stopped — no further changes after {idle} idle steps."
                    )
                    logger.info(
                        "subagent %s: no-progress guard tripped at step %d", label, steps
                    )
                    break

                # Feed tool results back as a user turn (robust for local models).
                messages.append({"role": "assistant", "content": content or "(used tools)"})
                messages.append(
                    {
                        "role": "user",
                        "content": "Tool results:\n"
                        + "\n".join(results_text)
                        + "\n\nContinue the task. Call finish(summary) once it is fully done.",
                    }
                )

            if not summary:
                summary = f"Reached step limit ({steps})."
        except Exception as exc:
            logger.warning("subagent runner error (%s): %s", label, exc, exc_info=True)
            yield ev(
                "agent_end",
                {
                    "label": label,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "summary": f"error: {exc}",
                    "success": False,
                },
            )
            return

        yield ev(
            "agent_end",
            {
                "label": label,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "summary": summary,
                "success": ok_overall,
                "prompt_tokens": last_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_tokens_sum or (last_prompt_tokens + total_completion_tokens),
                "context_window": ctx_window,
            },
        )
