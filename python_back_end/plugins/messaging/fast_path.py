"""Fast-path bypass for the workspace agent.

The workspace agent is heavily prompted to "ALWAYS use tool calls" and
"Start your response with a tool call, not a text message" (see
openclaw_client.py:874+). That's the right behavior for tool-using
tasks ("write a script that…", "fetch <url> and summarize"), but it's
the WRONG behavior for chat-like questions ("what are your
capabilities?", "what's 2+2", "hi"). The agent confuses itself, emits
nothing, and the user sees the cryptic "produced no answer and did not
call any tools" fallback.

This module provides:

  * ``should_use_fast_path(text)`` — quick classifier. Short messages
    without obvious workspace signals get fast-pathed; longer / signal-
    heavy messages run the workspace task detector for a richer
    decision.

  * ``direct_llm_reply(prompt, *, ollama_url, model_name)`` — single
    Ollama call (no tools, no agent loop), returns the model's text.

  * ``record_synthetic_completed_run(...)`` — inserts a workspace_runs
    row with status='completed' and the fast-path reply as
    final_summary. The gateway sidecar's wait_for_terminal then
    immediately sees a terminal status and delivers the reply, with
    zero changes to the existing polling pipeline.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# Lifted from discord_workspace_bot.py — phrases that strongly imply a
# real workspace task (file ops, web fetch, code execution, etc.).
_WORKSPACE_SIGNALS = re.compile(
    r"\b(write|create|edit|read|run|execute|exec|build|"
    r"compile|deploy|fetch|download|search|google|browse|"
    r"screenshot|render|generate.*(file|image|pdf|doc)|"
    r"clone|git|repo|github|terminal|shell|bash|python3|node|"
    r"open\s+https?://|attach|upload|analyze.*(file|image|pdf))\b",
    re.IGNORECASE,
)


_FAST_PATH_SYSTEM_PROMPT_BASE = (
    "You are Harvis, a helpful AI assistant. Give concise, direct answers.\n"
    "\n"
    "You are running in CONVERSATIONAL mode for this turn: no tools, no web, "
    "no file access, no code execution. If the user actually needs tools "
    "(web search, file read, run code, analyze an attached image), say so "
    "briefly and ask them to rephrase as a workspace task. Do NOT invent "
    "tool output. Do NOT say \"as an AI I can't\" — just route them to the "
    "workspace if they need it.\n"
    "\n"
    "MEMORY: When PERSONA or RECENT FACTS sections appear above this one, "
    "treat them as ground truth about the user. If the user asks \"what do "
    "you remember\", \"what's the last thing you remember\", \"what do you "
    "know about me\", \"do you remember X\", or any similar memory "
    "question, your reply MUST quote from those sections — do NOT answer "
    "as if you have no memory. If those sections are absent or empty, say "
    "so honestly (\"I don't have anything saved for you yet — tell me a "
    "fact and I'll remember it\") instead of fabricating."
)

# Backwards-compat alias for callers that import the constant directly.
_FAST_PATH_SYSTEM_PROMPT = _FAST_PATH_SYSTEM_PROMPT_BASE


def _compose_fast_path_system_prompt(
    persona_block: str = "",
    recall_block: str = "",
) -> str:
    """Build the system prompt for fast-path with persona + recall context.

    Persona and recall live in the SYSTEM role (not the user role) so the
    model treats them as authoritative ground truth, not as something the
    user said to inspect. Same recall data the workspace path uses — the
    dispatcher builds it once and passes it to both paths.
    """
    parts: list[str] = []
    if persona_block and persona_block.strip():
        parts.append(
            "PERSONA (your saved instructions for this user):\n"
            + persona_block.strip()
        )
    if recall_block and recall_block.strip():
        parts.append(recall_block.strip())
    parts.append(_FAST_PATH_SYSTEM_PROMPT_BASE)
    return "\n\n".join(parts)


async def should_use_fast_path(text: str) -> bool:
    """True when the message looks like simple chat (no tools needed).

    Decision order:
      1. Empty / whitespace-only → False (let the dispatcher reject).
      2. Short message (< 20 chars) without workspace signal regex → True.
      3. Workspace signal regex matches → False (probably a real task).
      4. Workspace task detector → False if it says should_suggest=True.
      5. Otherwise → True (chat-like).
    """
    body = (text or "").strip()
    if not body:
        return False

    if len(body) < 20 and not _WORKSPACE_SIGNALS.search(body):
        return True

    if _WORKSPACE_SIGNALS.search(body):
        return False

    try:
        from workspace.task_detector import detect_workspace_task  # type: ignore
        suggestion = await detect_workspace_task([{"role": "user", "content": body}])
        return not bool(getattr(suggestion, "should_suggest", False))
    except Exception:
        logger.exception("fast_path: detect_workspace_task failed; defaulting to fast path")
        return True


async def direct_llm_reply(
    prompt: str,
    *,
    ollama_url: Optional[str] = None,
    model_name: Optional[str] = None,
    system_prompt: Optional[str] = None,
    persona_block: str = "",
    recall_block: str = "",
    timeout_s: Optional[float] = None,
) -> Optional[str]:
    """Single Ollama call (no tools), returns the model's reply or None.

    Model selection cascade: explicit model_name → HARVIS_FAST_PATH_MODEL
    env var → general resolver (user pref → HARVIS_DEFAULT_LOCAL_MODEL →
    first available). The fast-path knob exists because chat-style replies
    need a snappy small model (8B-class), while the general default may
    be a heavier tool-calling model.

    Timeout cascade: explicit timeout_s → HARVIS_FAST_PATH_TIMEOUT_S env
    var → 600s. Long default because constrained GPUs run 9B-class
    models on CPU/swap and a single chat reply can take minutes.
    """
    import os
    from plugins.models.resolver import _normalize_ollama_base, resolve_default_local_model

    base = _normalize_ollama_base(ollama_url)
    if model_name is None:
        model_name = (os.getenv("HARVIS_FAST_PATH_MODEL") or "").strip() or None
    model = model_name or await resolve_default_local_model(ollama_url=ollama_url)
    if not model:
        logger.warning("fast_path: no model resolvable; skipping direct reply")
        return None

    if timeout_s is None:
        try:
            timeout_s = float(os.getenv("HARVIS_FAST_PATH_TIMEOUT_S", "600"))
        except ValueError:
            timeout_s = 600.0

    # Compose the system prompt: caller-provided system_prompt wins; otherwise
    # inject persona + recall blocks (if any) into the SYSTEM role using the
    # default fast-path scaffold. Memory and persona belong in system, not
    # user — that's why the workspace path injects them as preamble blocks
    # and why the model treats them as authoritative there. Same data, same
    # role, same authority for fast-path now.
    if system_prompt is None:
        system_prompt = _compose_fast_path_system_prompt(
            persona_block=persona_block,
            recall_block=recall_block,
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"num_ctx": 8192},
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=10.0)) as client:
            r = await client.post(f"{base}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json() or {}
    except Exception:
        logger.exception("fast_path: direct_llm_reply failed against %s/api/chat", base)
        return None

    msg = (data.get("message") or {}).get("content") if isinstance(data.get("message"), dict) else None
    if not msg:
        # Some Ollama versions wrap differently; try the older shape.
        msg = data.get("response") or ""
    return (msg or "").strip() or None


async def record_running_run(
    pool,
    *,
    user_id: int,
    session_id: str,
    task_brief: str,
) -> Optional[str]:
    """Insert a workspace_runs row marking a fast-path dispatch as running.

    Returns the workspace_id, or None on failure. The dispatcher then
    fires a background task that calls the LLM and eventually flips the
    row to 'completed' or 'failed' via mark_run_terminal — keeps the
    sidecar HTTP timeout well under the LLM's worst-case latency.
    """
    if pool is None:
        return None
    workspace_id = f"fast-{uuid.uuid4().hex[:8]}"
    # status='fastpath' (not 'running') so workspace_router's
    # get_active_workspace orphan-sweeper (which queries
    # WHERE status='running' exact-match) leaves us alone. The gateway
    # bridge's wait_for_terminal only treats {completed, failed, error,
    # cancelled} as terminal, so 'fastpath' just means "keep polling".
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workspace_runs
                    (id, user_id, session_id, task_brief, status, started_at)
                VALUES ($1, $2, $3, $4, 'fastpath', NOW())
                """,
                workspace_id,
                int(user_id),
                session_id,
                task_brief,
            )
    except Exception:
        logger.exception("fast_path: workspace_runs insert failed for user %s", user_id)
        return None
    return workspace_id


async def mark_run_terminal(
    pool,
    workspace_id: str,
    *,
    success: bool,
    final_summary: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Flip a running fast-path workspace_runs row to completed or failed."""
    if pool is None or not workspace_id:
        return
    status = "completed" if success else "failed"
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workspace_runs
                SET status = $2,
                    completed_at = NOW(),
                    final_summary = COALESCE($3, final_summary),
                    error_message = COALESCE($4, error_message)
                WHERE id = $1
                """,
                workspace_id,
                status,
                final_summary,
                error_message,
            )
    except Exception:
        logger.exception("fast_path: workspace_runs UPDATE failed for %s", workspace_id)


async def finish_fast_path_run(
    pool,
    *,
    workspace_id: str,
    enriched_brief: str,
    persona_block: str = "",
    recall_block: str = "",
    ollama_url: Optional[str] = None,
) -> None:
    """Fire-and-forget body: run the LLM call, then mark the row terminal.

    Called from asyncio.create_task in the dispatcher; never awaited by
    the request handler. Exceptions are caught and converted to a failed
    status so the sidecar's polling pipeline always sees a terminal
    state instead of hanging.

    persona_block + recall_block are the same SOUL.md persona and Hermes-
    derived memory recall blocks the workspace path receives. They land in
    the SYSTEM role (via direct_llm_reply) so memory questions get
    authoritative context, not buried-in-the-user-message context.
    """
    try:
        answer = await direct_llm_reply(
            enriched_brief,
            ollama_url=ollama_url,
            persona_block=persona_block,
            recall_block=recall_block,
        )
    except Exception as exc:
        logger.exception("fast_path background LLM call raised")
        await mark_run_terminal(
            pool, workspace_id,
            success=False, error_message=f"fast_path: {exc}",
        )
        return

    if answer:
        await mark_run_terminal(pool, workspace_id, success=True, final_summary=answer)
    else:
        await mark_run_terminal(
            pool, workspace_id,
            success=False, error_message="fast_path: empty reply from model",
        )
