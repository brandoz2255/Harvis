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

import json
import logging
import time
from typing import AsyncGenerator

from ..openclaw_client import OpenClawEvent
from .model_router import ModelRouter
from .tools import TOOL_SCHEMA, dispatch_tool, parse_tool_calls

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are {label}, an autonomous coding sub-agent working in an ISOLATED, "
    "initially-empty workspace directory. You can ONLY use the provided tools, and "
    "ONLY touch files inside your workspace using RELATIVE paths. Complete the task "
    "by creating/editing files with edit_file (optionally run exec / run_tests to "
    "check your work). Do NOT ask questions. When the task is fully done, call "
    "finish with a one-line summary."
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
            {"role": "system", "content": _SYSTEM.format(label=label)},
            {"role": "user", "content": task},
        ]
        summary = ""
        ok_overall = True
        steps = 0

        try:
            while steps < max_steps and (time.monotonic() - started) < max_runtime_seconds:
                steps += 1
                msg = await self.router.complete(
                    model_name=model_name, messages=messages, tools=TOOL_SCHEMA, temperature=0.2
                )
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
                    result, ok = await dispatch_tool(workspace_path, name, args)
                    if not ok:
                        ok_overall = False
                    yield ev("tool_result", {"output": result, "success": ok})
                    results_text.append(
                        f"{name}({json.dumps(args)[:140]}) -> {result[:500]}"
                    )
                if finished:
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
            },
        )
