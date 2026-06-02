"""OWUI-facade workspace bridge.

When an OWUI chat-completion request looks like a multi-step *workspace task*,
launch a Harvis workspace run and return a short OpenAI-SSE stream whose only
content is a ``<details type="workspace_run" data-workspace-id="…">`` marker.
The OWUI frontend renders that marker as a live ``WorkspaceRunCard`` which then
attaches to ``GET /api/workspace/stream/{id}`` for the actual run.

This mirrors the native ``/api/chat`` auto-launch (``main.py`` + ``chat_bridge.py``)
but emits a *marker* instead of streaming the whole run inline — so the run is
owned by the card / right-rail, not by the chat-completion request (which returns
immediately). No new backend plumbing: it reuses ``_start_workspace`` etc.
"""

from __future__ import annotations

import html
import json
import logging
import os
import time
import uuid
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Parity with the native /api/chat auto-launch threshold (main.py ~2920).
_AUTO_LAUNCH_CONFIDENCE = 0.8

# ── Opt-in run-level approval gate (P1.5, default OFF) ───────────────────────
# When HARVIS_OWUI_APPROVALS is on, a detected workspace task is NOT launched
# immediately — its launch kwargs are parked here and the run-card shows
# Approve/Deny. POST /api/owui/workspace/{id}/approve launches it; /deny discards.
# When OFF (default) runs launch immediately, exactly as before — zero change to
# the working flow. In-memory by design (single uvicorn worker); a pending run
# lost to a restart simply can't be approved (the card shows it unavailable).
_PENDING_RUNS: dict[str, dict] = {}


def _approvals_enabled() -> bool:
    return os.getenv("HARVIS_OWUI_APPROVALS", "false").strip().lower() in ("1", "true", "yes", "on")


def _messages_to_history(owui_body: dict) -> list[dict]:
    """OWUI sends OpenAI-style messages; the detector wants ``[{role, content}]``
    with plain-string content (flatten multimodal parts to their text)."""
    out: list[dict] = []
    for m in owui_body.get("messages") or []:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        if role and content:
            out.append({"role": role, "content": str(content)})
    return out


def _last_user_message(history: list[dict]) -> str:
    for m in reversed(history):
        if m.get("role") == "user":
            return m.get("content", "") or ""
    return ""


def _marker_content(workspace_id: str, suggestion, needs_approval: bool = False) -> str:
    """Newline-fenced ``<details type="workspace_run">`` block so OWUI's marked
    extension parses it into a token the WorkspaceRunCard renders.

    NOTE: OWUI's ``parseAttributes`` regex only captures ``\\w+`` attribute keys
    (no hyphens), so we use word-only keys — and NOT ``data-task-type`` (would be
    parsed as ``type`` and clobber the ``workspace_run`` discriminator)."""
    label = html.escape(suggestion.task_type_label or "Workspace task", quote=True)
    ttype = html.escape(suggestion.task_type or "", quote=True)
    brief = html.escape((suggestion.task_brief or "")[:240], quote=True)
    approval_attr = ' needsapproval="1"' if needs_approval else ""
    return (
        f'<details type="workspace_run" workspaceid="{workspace_id}" '
        f'tasktype="{ttype}" tasklabel="{label}" taskbrief="{brief}"{approval_attr}>\n'
        f"<summary>Working in a Harvis Workspace…</summary>\n"
        f"</details>\n"
    )


def _openai_sse_lines(workspace_id: str, content: str) -> list[str]:
    """A minimal OpenAI chat.completion.chunk sequence carrying ``content`` then
    ``[DONE]`` — exactly what OWUI's createOpenAITextStream parser expects."""
    cid = f"chatcmpl-ws-{workspace_id}"
    created = int(time.time())
    base = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": "harvis-workspace",
    }
    chunks = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    lines.append("data: [DONE]\n\n")
    return lines


async def maybe_handle_workspace(
    request: Request, owui_body: dict, user
) -> Optional[StreamingResponse]:
    """If this chat turn is a workspace task, launch the run and return an SSE
    carrying the run marker. Otherwise return ``None`` (caller falls through to a
    normal chat completion). Never raises — any failure → ``None`` → normal chat.
    """
    history = _messages_to_history(owui_body)
    if not _last_user_message(history).strip():
        return None

    # Lazy imports — keep the package free of import-time coupling to workspace/.
    try:
        from workspace.task_detector import detect_workspace_task
        from workspace.workspace_router import (
            _start_workspace,
            _db_enable_interactive,
            _db_create_run,
            _resolve_task_brief,
        )
    except Exception:
        logger.exception("owui workspace_bridge: import failed; skipping detection")
        return None

    try:
        suggestion = await detect_workspace_task(history)
    except Exception:
        logger.exception("owui workspace_bridge: detect_workspace_task failed")
        return None

    if not (suggestion.should_suggest and suggestion.confidence >= _AUTO_LAUNCH_CONFIDENCE):
        return None

    pool = getattr(request.app.state, "pg_pool", None)
    user_id = getattr(user, "id", None)
    if pool is None or user_id is None:
        return None

    message = _last_user_message(history)
    workspace_id = uuid.uuid4().hex[:8]
    session_id = owui_body.get("chat_id") or owui_body.get("session_id") or f"owui-{workspace_id}"
    model_name = owui_body.get("model") or ""
    resolved_brief = _resolve_task_brief(suggestion.task_brief or message, history)
    started_epoch = time.monotonic()

    interactive_context = None
    try:
        cap = await _db_enable_interactive(
            pool, workspace_id=workspace_id, user_id=user_id, ttl_seconds=3600
        )
        interactive_context = {"workspace_id": workspace_id, "capability_token": cap}
    except Exception:
        logger.warning("owui workspace_bridge: enable_interactive failed for %s", workspace_id)

    launch_kwargs = dict(
        workspace_id=workspace_id,
        session_id=session_id,
        task_brief=resolved_brief,
        chat_history=history,
        agent_id="local",
        user_id=user_id,
        model_name=model_name,
        live_web=True,
        parallel=True,
        interactive_context=interactive_context,
    )

    needs_approval = _approvals_enabled()
    if needs_approval:
        # Opt-in gate: park the run; the card asks Approve/Deny before it launches.
        _PENDING_RUNS[workspace_id] = {
            "kwargs": launch_kwargs,
            "user_id": user_id,
            "session_id": session_id,
            "task_brief": resolved_brief,
        }
        logger.info(
            "owui workspace_bridge: %s awaiting approval (conf=%.2f type=%s)",
            workspace_id, suggestion.confidence, suggestion.task_type,
        )
    else:
        try:
            await _start_workspace(pool=pool, started_epoch=started_epoch, **launch_kwargs)
            await _db_create_run(pool, workspace_id, user_id, session_id, resolved_brief)
        except Exception:
            logger.exception("owui workspace_bridge: launch failed for %s", workspace_id)
            return None
        logger.info(
            "owui workspace_bridge: launched %s (conf=%.2f type=%s)",
            workspace_id, suggestion.confidence, suggestion.task_type,
        )

    lines = _openai_sse_lines(
        workspace_id, _marker_content(workspace_id, suggestion, needs_approval=needs_approval)
    )

    async def _gen():
        for ln in lines:
            yield ln

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def resolve_workspace_approval(request: Request, workspace_id: str, approved: bool) -> dict:
    """Resolve a parked (opt-in) workspace run: launch it on approve, discard on
    deny. Returns a small JSON status the run-card uses to switch to streaming or
    show 'cancelled'. Safe no-op if the workspace isn't pending (already resolved,
    or lost to a restart)."""
    pending = _PENDING_RUNS.pop(workspace_id, None)
    if pending is None:
        return {"ok": False, "status": "not_pending"}
    if not approved:
        logger.info("owui workspace_bridge: %s denied", workspace_id)
        return {"ok": True, "status": "denied"}

    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"ok": False, "status": "no_pool"}
    try:
        from workspace.workspace_router import _start_workspace, _db_create_run

        await _start_workspace(pool=pool, started_epoch=time.monotonic(), **pending["kwargs"])
        await _db_create_run(
            pool, workspace_id, pending["user_id"], pending["session_id"], pending["task_brief"]
        )
    except Exception:
        logger.exception("owui workspace_bridge: approve-launch failed for %s", workspace_id)
        return {"ok": False, "status": "launch_failed"}
    logger.info("owui workspace_bridge: %s approved + launched", workspace_id)
    return {"ok": True, "status": "approved"}
