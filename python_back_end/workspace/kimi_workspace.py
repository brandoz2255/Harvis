"""
Kimi K2.5 workspace backend — direct Moonshot API streaming, no OpenClaw.

Used when the user selects "Kimi K2.5" as the workspace model from the frontend.
Suitable for research, analysis, writing, and reasoning tasks that don't
require local shell/code execution.

Events yielded match the OpenClawEvent format used by workspace_router.py
so the SSE stream is identical regardless of which backend ran the task.
"""

import logging
import os
from typing import AsyncGenerator

from moonshot_api import MoonshotClient, MOONSHOT_BASE_URL
from .openclaw_client import OpenClawEvent

logger = logging.getLogger(__name__)

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")

_KIMI_SYSTEM_PROMPT = (
    "You are the Harvis Workspace Agent powered by Kimi K2.5. "
    "You have been given a specific task by the user. "
    "Execute the task completely and thoroughly. "
    "Provide a detailed, well-structured response. "
    "If the task involves analysis, provide step-by-step reasoning. "
    "If it involves writing or code, provide the complete output. "
    "Do not ask clarifying questions — make reasonable assumptions and proceed."
)


async def stream_kimi_workspace(
    task_message: str,
    chat_history: list[dict],
) -> AsyncGenerator[OpenClawEvent, None]:
    """
    Run a workspace task using Kimi K2.5 directly (bypasses OpenClaw).

    Args:
        task_message: The task brief / user instruction.
        chat_history: Full Harvis chat history for context.

    Yields:
        OpenClawEvent objects (token, done, error) in the same format
        as OpenClawClient.stream() so workspace_router.py can handle them uniformly.
    """
    if not MOONSHOT_API_KEY:
        logger.error("kimi_workspace: MOONSHOT_API_KEY not set")
        yield OpenClawEvent("error", {"message": "Kimi K2.5 API key not configured on backend."})
        return

    # Build context block from recent chat history (cap at 10 messages)
    context_lines = [
        f"{m['role'].upper()}: {m['content']}"
        for m in chat_history[-10:]
        if isinstance(m.get("content"), str) and m["content"].strip()
    ]
    context_block = "\n".join(context_lines)

    if context_lines:
        user_content = (
            f"[RECENT CONVERSATION]\n{context_block}\n\n"
            f"[YOUR TASK]\n{task_message}\n\n"
            "Begin executing the task now. Be specific and thorough."
        )
    else:
        user_content = (
            f"[YOUR TASK]\n{task_message}\n\n"
            "Begin executing the task now. Be specific and thorough."
        )

    client = MoonshotClient(api_key=MOONSHOT_API_KEY, base_url=MOONSHOT_BASE_URL)
    messages = [
        {"role": "system", "content": _KIMI_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    full_text_parts: list[str] = []

    try:
        async for chunk in client.chat_completion_stream(
            model="kimi-k2.5",
            messages=messages,
        ):
            if chunk:
                full_text_parts.append(chunk)
                yield OpenClawEvent("token", {"content": chunk})

        full_text = "".join(full_text_parts)
        summary = full_text[:500].rstrip() if full_text else "Task completed."
        yield OpenClawEvent("done", {"summary": summary})

    except Exception as exc:
        logger.error("kimi_workspace: stream error: %s", exc)
        yield OpenClawEvent("error", {"message": f"Kimi K2.5 error: {exc}"})
