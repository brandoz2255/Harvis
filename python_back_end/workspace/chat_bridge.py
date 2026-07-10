"""
Bridges workspace background events into the chat-SSE format so a workspace task
launched from /api/chat appears inline in the user's chat bubble.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import AsyncIterator, Optional

from .workspace_router import (
    _workspaces,
    _workspace_broadcasters,
    _start_workspace,
    _db_enable_interactive,
    _db_create_run,
    _resolve_task_brief,
)

logger = logging.getLogger(__name__)


async def stream_workspace_launch_as_chat(
    *,
    message: str,
    history: list[dict],
    user_id: int,
    session_id: Optional[str],
    pool,
    agent_id: str = "local",
    model_name: str = "",
    task_brief: Optional[str] = None,
    launch_mode: str = "user",
) -> AsyncIterator[str]:
    """
    Launch a workspace task and yield chat-SSE lines the frontend can consume.

    Emits, in order:
      status=workspace_acknowledge   once, after workspace is registered (safe for /stream attach)
      status=workspace_status        humanized tool call lines
      status=workspace_tool_call     compact machine-readable tool event
      status=workspace_tool_result   trimmed output, read/edit/write/exec/local_rag
      status=workspace_partial       streaming agent text
      status=workspace_result        terminal success (final_answer + workspace_id)
      status=workspace_error         terminal failure
    """
    workspace_id = uuid.uuid4().hex[:8]
    effective_session = session_id or f"ws-{workspace_id}"
    resolved_brief = _resolve_task_brief(task_brief or message, history)

    started_epoch = time.monotonic()
    interactive_context = None
    if launch_mode == "user":
        try:
            cap_token = await _db_enable_interactive(
                pool,
                workspace_id=workspace_id,
                user_id=user_id,
                ttl_seconds=3600,
            )
            interactive_context = {
                "workspace_id": workspace_id,
                "capability_token": cap_token,
            }
        except Exception as exc:
            logger.warning(
                "chat_bridge: failed to enable interactive workspace %s: %s",
                workspace_id,
                exc,
            )
    else:
        # Auto-detected escalation: withhold the Tier-3 capability token so the
        # run stays on base tools (no /api/tools/browser/* access).
        logger.info(
            "chat_bridge: auto launch %s — Tier-3 interactive withheld", workspace_id
        )

    try:
        await _start_workspace(
            workspace_id=workspace_id,
            session_id=effective_session,
            task_brief=resolved_brief,
            chat_history=history,
            agent_id=agent_id,
            user_id=user_id,
            pool=pool,
            started_epoch=started_epoch,
            model_name=model_name,
            live_web=True,
            parallel=True,
            interactive_context=interactive_context,
            launch_mode=launch_mode,
        )
    except Exception as exc:
        logger.error("chat_bridge: workspace launch failed: %s", exc)
        yield _sse({
            "status": "workspace_error",
            "workspace_id": workspace_id,
            "message": f"Couldn't launch workspace: {exc}",
        })
        return

    # After registration so clients can attach to /api/workspace/stream/{id} immediately
    yield _sse({
        "status": "workspace_acknowledge",
        "workspace_id": workspace_id,
        "task_brief": resolved_brief,
        "message": "On it — launching a workspace task.",
    })

    try:
        await _db_create_run(pool, workspace_id, user_id, effective_session, resolved_brief)
    except Exception as exc:
        logger.warning("chat_bridge: _db_create_run failed (non-fatal): %s", exc)

    broadcaster = _workspace_broadcasters.get(workspace_id)
    if broadcaster is None:
        yield _sse({
            "status": "workspace_error",
            "workspace_id": workspace_id,
            "message": "Workspace broadcaster missing after start.",
        })
        return

    # Dedicated subscriber queue — broadcaster copies every event here (see WorkspaceLiveBroadcaster)
    sub_queue = broadcaster.subscribe()
    try:
        final_summary = ""
        while True:
            try:
                item = await asyncio.wait_for(sub_queue.get(), timeout=180.0)
            except asyncio.TimeoutError:
                yield _sse({
                    "status": "workspace_error",
                    "workspace_id": workspace_id,
                    "message": "Workspace idle for 180s — cancelling stream.",
                })
                return

            if item is None:
                break  # sentinel — background task finished

            _, event = item
            etype = getattr(event, "type", None)
            edata = getattr(event, "data", None) or {}

            if etype == "tool_call":
                yield _sse({
                    "status": "workspace_status",
                    "workspace_id": workspace_id,
                    "message": _humanize_tool_call(edata),
                })
                yield _sse({
                    "status": "workspace_tool_call",
                    "workspace_id": workspace_id,
                    "tool_name": edata.get("tool_name") or edata.get("tool", ""),
                    "args": _compact_args(edata.get("args") or edata.get("arguments") or {}),
                })

            elif etype == "tool_result":
                tool = edata.get("tool_name") or edata.get("tool", "")
                if tool in {"read", "edit", "write", "exec", "bash", "local_rag"}:
                    output = edata.get("output") or edata.get("result") or ""
                    yield _sse({
                        "status": "workspace_tool_result",
                        "workspace_id": workspace_id,
                        "tool_name": tool,
                        "output": str(output)[:800],
                    })

            elif etype == "log":
                msg = edata.get("message") or ""
                if msg:
                    yield _sse({
                        "status": "workspace_status",
                        "workspace_id": workspace_id,
                        "message": msg,
                    })

            elif etype in ("agent_partial", "partial"):
                text = edata.get("text") or edata.get("content") or ""
                if text:
                    yield _sse({
                        "status": "workspace_partial",
                        "workspace_id": workspace_id,
                        "text": text,
                    })

            elif etype in ("done", "cancelled"):
                final_summary = edata.get("summary") or edata.get("final_text") or final_summary
                yield _sse({
                    "status": "workspace_result",
                    "workspace_id": workspace_id,
                    "final_answer": final_summary,
                    "summary": final_summary,
                    "duration_ms": int((time.monotonic() - started_epoch) * 1000),
                })
                return

            elif etype == "error":
                yield _sse({
                    "status": "workspace_error",
                    "workspace_id": workspace_id,
                    "message": edata.get("message") or "Workspace error",
                })
                return

        # Queue ended without an explicit terminal event (None sentinel) — emit a result
        yield _sse({
            "status": "workspace_result",
            "workspace_id": workspace_id,
            "final_answer": final_summary,
            "summary": final_summary,
            "duration_ms": int((time.monotonic() - started_epoch) * 1000),
        })
    finally:
        broadcaster.unsubscribe(sub_queue)


def _humanize_tool_call(data: dict) -> str:
    tool = data.get("tool_name") or data.get("tool", "")
    args = data.get("args") or data.get("arguments") or {}
    if tool in ("read", "read_file"):
        return f"Reading `{args.get('path', '')}`..."
    if tool in ("edit", "edit_file"):
        return f"Editing `{args.get('path', '')}`..."
    if tool in ("write", "write_file"):
        return f"Writing `{args.get('path', '')}`..."
    if tool in ("exec", "bash", "run_code"):
        cmd = str(args.get("command", "") or args.get("cmd", ""))[:80]
        return f"Running `{cmd}`..."
    if tool == "local_rag":
        q = str(args.get("query", ""))[:60]
        return f"Searching knowledge: {q}"
    return f"Using tool: {tool}" if tool else "Working..."


def _compact_args(args: dict) -> dict:
    compact = {}
    for k, v in list(args.items())[:4]:
        compact[k] = str(v)[:120]
    return compact


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
