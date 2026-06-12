"""
Task detector — decides whether a chat conversation warrants launching a Harvis Workspace.

Uses Kimi K2.5 to classify the conversation and produce a concise task brief that
OpenClaw will use as its starting instruction. Returns a suggestion object the backend
can forward to the frontend to ask the user for confirmation.
"""

import json
import logging
import os
import re
import httpx
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

Workspaces are STRONGLY preferred when the user mentions anything about code,
programming, components, functions, APIs, or technical implementation — even
if the request seems simple. Err on the side of suggesting a workspace.

Workspaces are NOT appropriate for:
- Simple greetings or casual chat (e.g. "hi", "thanks", "how are you")
- Short factual questions with no coding context (e.g. "what time is it")

Respond with ONLY valid JSON in this exact format:
{
  "should_suggest": true | false,
  "confidence": 0.0 to 1.0,
  "task_type": "code" | "debug" | "file" | "research" | "document" | "shell" | "multi_step" | null,
  "task_brief": "A single clear sentence describing what the workspace should do. Max 150 chars.",
  "reason": "One sentence explaining why this does or does not need a workspace."
}

Only set should_suggest = true if confidence >= 0.4."""

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
# Prefer explicit workspace-detector name; DISCORD_FAST_MODEL kept for backward
# compatibility. Empty default is intentional — when neither env is set, the
# detector resolves a model at call time via plugins.models.resolver so the
# system adapts to whatever's actually installed in Ollama.
FAST_MODEL = (
    os.getenv("WORKSPACE_DETECTOR_OLLAMA_MODEL")
    or os.getenv("DISCORD_FAST_MODEL")
    or ""
).strip()


async def _resolve_detector_model() -> Optional[str]:
    """FAST_MODEL when explicitly configured, otherwise the adaptive resolver."""
    if FAST_MODEL:
        return FAST_MODEL
    try:
        from plugins.models.resolver import resolve_default_local_model
        return await resolve_default_local_model(ollama_url=OLLAMA_URL)
    except Exception:
        logger.exception("task_detector: resolver import/call failed")
        return None


class WorkspaceSuggestion:
    def __init__(self, raw: dict):
        self.should_suggest: bool = raw.get("should_suggest", False)
        self.confidence: float = float(raw.get("confidence", 0.0))
        self.task_type: Optional[str] = raw.get("task_type")
        self.task_brief: str = raw.get("task_brief", "")
        self.reason: str = raw.get("reason", "")
        self.task_type_label: str = TASK_TYPES.get(self.task_type or "", "General task")

    @property
    def confidence_level(self) -> str:
        """Bucketed confidence: high (>=0.8), medium (>=0.4), low (<0.4 or not a task)."""
        if not self.should_suggest:
            return "low"
        if self.confidence >= 0.8:
            return "high"
        if self.confidence >= 0.4:
            return "medium"
        return "low"

    def to_dict(self) -> dict:
        return {
            "should_suggest": self.should_suggest,
            "confidence": round(self.confidence, 2),
            "confidence_level": self.confidence_level,
            "task_type": self.task_type,
            "task_type_label": self.task_type_label,
            "task_brief": self.task_brief,
            "reason": self.reason,
        }


async def _detect_workspace_task_ollama(conversation_text: str) -> WorkspaceSuggestion:
    try:
        base_url = OLLAMA_URL.rstrip("/")
        model = await _resolve_detector_model()
        if not model:
            logger.warning(
                "task_detector: no local model resolvable (Ollama empty + no env override); "
                "skipping workspace detection"
            )
            return WorkspaceSuggestion({"should_suggest": False, "reason": "no model"})
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": DETECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": f"Conversation:\n{conversation_text}"},
            ],
            "stream": False,
            "options": {"num_ctx": 4096, "temperature": 0.1},
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.post(f"{base_url}/api/chat", json={
                "model": model,
                "messages": [
                    {"role": "system", "content": DETECTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Conversation:\n{conversation_text}"},
                ],
                "stream": False,
                "options": {"num_ctx": 4096, "temperature": 0.1},
            })
            
        if resp.status_code != 200:
            logger.error("Ollama detection failed: %s", resp.status_code)
            return WorkspaceSuggestion({"should_suggest": False, "reason": f"Ollama HTTP {resp.status_code}"})

        data = resp.json()
        raw_response = data.get("message", {}).get("content", "")
        
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            else:
                cleaned = cleaned.split("```")[1]

        parsed = json.loads(cleaned.strip())
        suggestion = WorkspaceSuggestion(parsed)
        logger.info(
            f"Ollama Workspace detection: should_suggest={suggestion.should_suggest} "
            f"confidence={suggestion.confidence} type={suggestion.task_type}"
        )
        return suggestion
    except Exception as e:
        logger.error(f"Ollama Workspace detection error: {e}")
        return WorkspaceSuggestion({"should_suggest": False, "reason": f"Ollama fallback error: {e}"})


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


# ── CTF / crypto deterministic override ──────────────────────────────────────
# Hash-cracking, decoding, and cipher tasks OBJECTIVELY need tools — you can't
# crack an MD5 or decode base64 by chatting. The LLM classifier is unreliable on
# them (measured: returns should_suggest=False on raw hashes), so they fall
# through to plain chat where the model just refuses. These patterns force such
# tasks into the workspace, where the hash/decode/crypto skill flow (cracker.py /
# decoders) actually runs. This is TASK detection (workspace vs chat), NOT model
# routing — the model is never swapped.
_CTF_HASH_RE = re.compile(
    r"(?<![a-fA-F0-9])(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{40}|[a-fA-F0-9]{64})(?![a-fA-F0-9])"
)
_CTF_INTENT_RE = re.compile(
    r"\b(crack|decode|decrypt|decipher|unscramble|de-?obfuscate|brute[\s-]?force)\b",
    re.IGNORECASE,
)
_CTF_ENCODING_RE = re.compile(
    r"\b(hashes?|md5|sha-?1|sha-?256|sha-?512|ntlm|bcrypt|base\s?64|base\s?32|hex|"
    r"rot-?13|rot-?\d+|caesar|vigen[eè]re|cipher|ciphertext|xor|morse|atbash)\b",
    re.IGNORECASE,
)


def _ctf_override(chat_history: list[dict]) -> Optional[WorkspaceSuggestion]:
    """Force hash/cipher/encoding tasks into the workspace (they need tools).
    Trigger on a raw hash hex, OR a crack/decode/decrypt intent paired with an
    encoding/cipher keyword. Returns None if it isn't clearly a CTF task."""
    last_user = next(
        (m for m in reversed(chat_history) if m.get("role") == "user"), None
    )
    if not last_user:
        return None
    content = str(last_user.get("content", "")).strip()
    if not content:
        return None

    has_hash = bool(_CTF_HASH_RE.search(content))
    has_intent = bool(_CTF_INTENT_RE.search(content))
    has_encoding = bool(_CTF_ENCODING_RE.search(content))
    if not (has_hash or (has_intent and has_encoding)):
        return None

    logger.info(
        "CTF override triggered (hash=%s intent+enc=%s): %r",
        has_hash, has_intent and has_encoding, content[:80],
    )
    return WorkspaceSuggestion({
        "should_suggest": True,
        "confidence": 1.0,
        "task_type": "multi_step",
        "task_brief": content[:500],  # RAW message — carries the hashes/ciphertext
        "reason": "Hash/cipher/encoding task — needs tools (deterministic override).",
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

    # CTF/crypto shortcut — hash/cipher/encoding tasks objectively need tools, but
    # the LLM classifier punts on them (should_suggest=False on raw hashes). Force
    # them to the workspace so the cracking/decoding skill flow runs.
    ctf = _ctf_override(chat_history)
    if ctf:
        return ctf

    # Build a compact representation of recent conversation for the classifier.
    # Cap at last 10 messages to keep the classifier call cheap and fast.
    recent = chat_history[-10:]
    conversation_text = "\n".join(
        f"{m['role'].upper()}: {str(m.get('content', ''))[:500]}"
        for m in recent
        if m.get("content")
    )

    if not MOONSHOT_API_KEY:
        logger.info("MOONSHOT_API_KEY not set — falling back to local Ollama for workspace detection")
        return await _detect_workspace_task_ollama(conversation_text)

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


async def detect_task_intent(
    message: str,
    chat_history: list[dict],
    user_id: int,
) -> WorkspaceSuggestion:
    """
    Wrapper over detect_workspace_task that takes the current user message
    directly and appends it to chat_history before classification.

    Used by /api/chat to run detection on every incoming message without the
    caller having to pre-assemble the history list.
    """
    history = list(chat_history or [])
    if message:
        history.append({"role": "user", "content": message})
    return await detect_workspace_task(history)
