"""
Task detector — decides whether a chat conversation warrants launching a Harvis Workspace.

Uses Kimi K2.5 to classify the conversation and produce a concise task brief that
OpenClaw will use as its starting instruction. Returns a suggestion object the backend
can forward to the frontend to ask the user for confirmation.
"""

import json
import logging
import os
from typing import Optional

from moonshot_api import MoonshotClient, MOONSHOT_BASE_URL

logger = logging.getLogger(__name__)

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")

# Task types that benefit from a workspace (mapped to friendly UI labels).
TASK_TYPES = {
    "code": "Code generation / editing",
    "debug": "Debugging / code analysis",
    "file": "File reading / writing",
    "research": "Research and summarization",
    "document": "Document / report generation",
    "shell": "System / shell task",
    "multi_step": "Multi-step task",
}

DETECTOR_SYSTEM_PROMPT = """You are a task classifier for Harvis AI.

Your job is to analyze a chat conversation and decide whether the user's latest request
would benefit from being executed in a "Harvis Workspace" — an isolated agent that can
run code, read/write files, and execute multi-step tasks autonomously.

Workspaces are appropriate when the user wants something that requires:
- Writing, running, or debugging code
- Reading or editing files
- Generating a document, report, or structured output
- Doing research that requires synthesizing many sources (local only)
- Any multi-step task that would take more than one response to complete

Workspaces are NOT appropriate for:
- Simple questions or explanations
- Short factual answers
- Casual conversation

Respond with ONLY valid JSON in this exact format:
{
  "should_suggest": true | false,
  "confidence": 0.0 to 1.0,
  "task_type": "code" | "debug" | "file" | "research" | "document" | "shell" | "multi_step" | null,
  "task_brief": "A single clear sentence describing what the workspace should do. Max 150 chars.",
  "reason": "One sentence explaining why this does or does not need a workspace."
}

Only set should_suggest = true if confidence >= 0.7."""


class WorkspaceSuggestion:
    def __init__(self, raw: dict):
        self.should_suggest: bool = raw.get("should_suggest", False)
        self.confidence: float = float(raw.get("confidence", 0.0))
        self.task_type: Optional[str] = raw.get("task_type")
        self.task_brief: str = raw.get("task_brief", "")
        self.reason: str = raw.get("reason", "")
        self.task_type_label: str = TASK_TYPES.get(self.task_type or "", "General task")

    def to_dict(self) -> dict:
        return {
            "should_suggest": self.should_suggest,
            "confidence": round(self.confidence, 2),
            "task_type": self.task_type,
            "task_type_label": self.task_type_label,
            "task_brief": self.task_brief,
            "reason": self.reason,
        }


WORKSPACE_KEYWORDS = {"workspace", "/workspace"}


def _keyword_override(chat_history: list[dict]) -> Optional[WorkspaceSuggestion]:
    """
    If the last user message contains 'workspace' or starts with '/workspace',
    skip Kimi detection and force a workspace suggestion immediately.
    Returns a WorkspaceSuggestion or None if no keyword found.
    """
    last_user = next(
        (m for m in reversed(chat_history) if m.get("role") == "user"),
        None,
    )
    if not last_user:
        return None

    content = str(last_user.get("content", "")).strip()
    lower = content.lower()

    if not any(kw in lower for kw in WORKSPACE_KEYWORDS):
        return None

    # Strip the keyword prefix if the user typed it as a command
    brief = content
    for kw in ("/workspace ", "workspace "):
        if lower.startswith(kw):
            brief = content[len(kw):].strip()
            break

    if not brief:
        brief = "Execute the task in a Harvis Workspace"

    # Truncate to 150 chars as the UI expects
    brief = brief[:150]

    logger.info(f"Workspace keyword override triggered: brief={brief!r}")
    return WorkspaceSuggestion({
        "should_suggest": True,
        "confidence": 1.0,
        "task_type": "multi_step",
        "task_brief": brief,
        "reason": "Workspace explicitly requested by user.",
    })


async def detect_workspace_task(chat_history: list[dict]) -> WorkspaceSuggestion:
    """
    Analyze the chat history and return a WorkspaceSuggestion.

    Args:
        chat_history: List of {role, content} dicts from the Harvis chat session.
                      Should include the latest user message as the last entry.

    Returns:
        WorkspaceSuggestion with should_suggest, task_type, task_brief, etc.
    """
    if not chat_history:
        return WorkspaceSuggestion({"should_suggest": False, "reason": "Empty chat history"})

    # Keyword shortcut — bypass Kimi if user explicitly requested a workspace
    override = _keyword_override(chat_history)
    if override:
        return override

    if not MOONSHOT_API_KEY:
        logger.warning("MOONSHOT_API_KEY not set — workspace detection disabled")
        return WorkspaceSuggestion({"should_suggest": False, "reason": "API key not configured"})

    # Build a compact representation of recent conversation for the classifier.
    # Cap at last 10 messages to keep the classifier call cheap and fast.
    recent = chat_history[-10:]
    conversation_text = "\n".join(
        f"{m['role'].upper()}: {str(m.get('content', ''))[:500]}"
        for m in recent
        if m.get("content")
    )

    client = MoonshotClient(api_key=MOONSHOT_API_KEY, base_url=MOONSHOT_BASE_URL)

    try:
        raw_response = await client.chat_completion(
            model="kimi-k2.5",
            messages=[
                {"role": "system", "content": DETECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": f"Conversation:\n{conversation_text}"},
            ],
            max_tokens=256,
        )

        # Strip markdown fences if the model wraps the JSON
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]

        parsed = json.loads(cleaned.strip())
        suggestion = WorkspaceSuggestion(parsed)
        logger.info(
            f"Workspace detection: should_suggest={suggestion.should_suggest} "
            f"confidence={suggestion.confidence} type={suggestion.task_type}"
        )
        return suggestion

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse workspace detector response: {e}")
        return WorkspaceSuggestion({"should_suggest": False, "reason": "Detection parse error"})

    except Exception as e:
        logger.error(f"Workspace detection error: {e}")
        return WorkspaceSuggestion({"should_suggest": False, "reason": f"Detection error: {e}"})
