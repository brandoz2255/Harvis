"""Inbound message dispatcher.

Resolves a Harvis user from a platform identity, audits the inbound message,
and kicks off a workspace run via the existing internal entry point. Workspace
runs are async — this dispatcher returns the workspace_id immediately. The
gateway sidecar polls workspace status (via /api/messaging/runs/{id}/status)
or subscribes to events to deliver responses back to the originating chat.

Future agents (Hermes-derived, custom) can be added by branching in
``dispatch_inbound`` on user preference; the public adapter contract does not
change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from ..core.hooks import invoke_hook
from .types import Direction, MessageEvent, SessionSource

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    ok: bool
    workspace_id: Optional[str] = None
    session_id: Optional[str] = None
    status: Optional[str] = None
    user_id: Optional[int] = None
    error: Optional[str] = None


async def resolve_user_id(pool, source: SessionSource) -> Optional[int]:
    """Look up the Harvis user_id linked to (platform, sender_id).

    Returns None if no mapping exists.
    """
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_id
                FROM messaging_platforms
                WHERE platform = $1 AND identifier = $2 AND enabled = TRUE
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                source.platform.value,
                source.sender_id,
            )
        return int(row["user_id"]) if row else None
    except Exception:
        logger.exception("messaging.resolve_user_id failed for %s", source.session_key())
        return None


async def audit(
    pool,
    event: MessageEvent,
    *,
    user_id: Optional[int],
    direction: Direction,
    status: str,
) -> None:
    """Persist an audit row. Failures are logged, never raised."""
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messaging_audit
                    (ts, user_id, platform, direction, chat_id, thread_id,
                     sender_id, message_id, kind, text, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                event.received_at,
                user_id,
                event.source.platform.value,
                direction.value,
                event.source.chat_id,
                event.source.thread_id,
                event.source.sender_id,
                event.message_id,
                event.message_type.value,
                event.text,
                status,
            )
    except Exception:
        logger.exception("messaging.audit insert failed for %s", event.message_id)


async def dispatch_inbound(
    request: Request,
    event: MessageEvent,
    *,
    fallback_user_id: Optional[int] = None,
) -> DispatchResult:
    """Route an inbound message to the agent runtime and return run metadata.

    Workspace launch is async — caller polls /api/messaging/runs/{workspace_id}/status
    (or workspace_events) to surface the response back to the platform.
    """
    pool = getattr(request.app.state, "pg_pool", None)

    user_id = await resolve_user_id(pool, event.source)
    if user_id is None:
        user_id = fallback_user_id

    if user_id is None:
        await audit(pool, event, user_id=None, direction=Direction.INBOUND, status="rejected_no_user")
        return DispatchResult(ok=False, error="no harvis user mapped to this sender")

    if not event.text:
        await audit(pool, event, user_id=user_id, direction=Direction.INBOUND, status="rejected_empty")
        return DispatchResult(ok=False, user_id=user_id, error="empty message")

    # Plugin hook — pre_gateway_dispatch. Phase 3 honors a single action
    # vocabulary: {"action": "skip", "reason": ...} drops the message;
    # any other return value (or None) means allow. "rewrite" is reserved
    # for a later phase since MessageEvent is frozen.
    hook_results = await invoke_hook(
        "pre_gateway_dispatch",
        event=event,
        user_id=user_id,
    )
    for r in hook_results:
        if isinstance(r, dict) and r.get("action") == "skip":
            reason = r.get("reason") or "skipped by plugin"
            await audit(
                pool, event,
                user_id=user_id, direction=Direction.INBOUND,
                status=f"rejected_plugin_skip:{reason[:80]}",
            )
            return DispatchResult(ok=False, user_id=user_id, error=reason)

    await audit(pool, event, user_id=user_id, direction=Direction.INBOUND, status="accepted")

    # Lazy import: keeps the plugin importable in environments where the
    # workspace stack is not installed (unit tests, lightweight runs).
    try:
        from workspace.workspace_router import launch_workspace_internal  # type: ignore
    except Exception as e:
        logger.exception("workspace_router import failed")
        return DispatchResult(ok=False, user_id=user_id, error=f"workspace unavailable: {e}")

    # Phase 7B + 4B-pre — Path A enrichment: layer per-user SOUL.md and
    # recalled memories into the task brief preamble. Sidesteps the
    # openclaw_client _load_identity_bundle path (which would touch a
    # pre-session-dirty file) at the cost of injecting at task-context
    # level rather than the identity slot. Both blocks fail-soft: any
    # storage error logs and falls back to whatever subset succeeded.
    enriched_brief = event.text
    if pool is not None:
        persona_block = ""
        recall_block = ""
        try:
            from ..soul.loader import build_persona_block
            persona_block = await build_persona_block(pool, user_id)
        except Exception:
            logger.exception("soul block build failed")
        try:
            from ..memory.preamble import build_recall_block
            recall_block = await build_recall_block(pool, user_id, event.text)
        except Exception:
            logger.exception("memory recall block build failed")

        preamble_parts = [b for b in (persona_block, recall_block) if b]
        if preamble_parts:
            enriched_brief = (
                "\n\n".join(preamble_parts)
                + "\n\n---\n\n"
                + f"USER MESSAGE: {event.text}"
            )

    try:
        data = await launch_workspace_internal(
            request=request,
            user_id=user_id,
            task_brief=enriched_brief,
            chat_history=None,
        )
    except Exception as e:
        logger.exception("launch_workspace_internal failed for message %s", event.message_id)
        return DispatchResult(ok=False, user_id=user_id, error=str(e))

    workspace_id = data.get("workspace_id")
    if workspace_id:
        # Observer hook — return values ignored. Fire AFTER the workspace
        # is actually running so plugins can rely on the workspace_id.
        await invoke_hook(
            "on_session_start",
            workspace_id=workspace_id,
            user_id=user_id,
            platform=event.source.platform.value,
            chat_id=event.source.chat_id,
            thread_id=event.source.thread_id,
            text=event.text,
        )

    return DispatchResult(
        ok=True,
        workspace_id=workspace_id,
        session_id=data.get("session_id"),
        status=data.get("status"),
        user_id=user_id,
    )


async def get_run_status(pool, workspace_id: str) -> Optional[dict]:
    """Read current status + final_summary for a workspace run.

    Returns None if the run is unknown. Returned dict keys mirror the
    workspace_runs columns the adapters care about.
    """
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT status,
                       final_summary,
                       error_message,
                       COALESCE(completed_at, started_at) AS updated_at
                FROM workspace_runs
                WHERE id = $1
                """,
                workspace_id,
            )
        if row is None:
            return None
        return {
            "status": row["status"],
            "final_summary": row["final_summary"],
            "error_message": row["error_message"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    except Exception:
        logger.exception("messaging.get_run_status failed for %s", workspace_id)
        return None


async def notify_terminal(
    request: Request,
    workspace_id: str,
) -> dict:
    """Fire on_session_end + invoke memory.extract_from_session for a workspace run.

    Called by the gateway sidecar exactly once per inbound message after
    wait_for_terminal returns. The backend re-reads workspace_runs to
    avoid trusting sidecar-supplied status (the sidecar could be stale).
    Idempotency is the sidecar's responsibility — backend just no-ops if
    the run isn't terminal yet.

    Returns a small status dict for diagnostic purposes.
    """
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        return {"ok": False, "reason": "no db pool"}

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, session_id, status, final_summary, error_message
                FROM workspace_runs
                WHERE id = $1
                """,
                workspace_id,
            )
    except Exception:
        logger.exception("notify_terminal: workspace_runs lookup failed for %s", workspace_id)
        return {"ok": False, "reason": "lookup failed"}

    if row is None:
        return {"ok": False, "reason": "workspace not found"}

    TERMINAL = {"completed", "failed", "error", "cancelled"}
    if row["status"] not in TERMINAL:
        return {"ok": False, "reason": f"not terminal: {row['status']}"}

    # Fire on_session_end (observer hook — return values ignored).
    from ..core.hooks import invoke_hook
    await invoke_hook(
        "on_session_end",
        workspace_id=row["id"],
        user_id=row["user_id"],
        session_id=row["session_id"],
        status=row["status"],
        final_summary=row["final_summary"],
        error_message=row["error_message"],
    )

    # If the run completed and a memory provider is active, give it the
    # chance to extract long-term memories from the session. Synthetic
    # message list — providers that want richer context can re-query
    # workspace_events themselves.
    extracted_count = 0
    if row["status"] == "completed":
        try:
            from ..memory.manager import get_manager
            mgr = get_manager()
            if mgr.provider is None:
                try:
                    await mgr.activate(config={"pool": pool})
                except Exception:
                    logger.exception("notify_terminal: memory.activate failed")
            provider = mgr.provider
            if provider is not None:
                synthetic = []
                if row["final_summary"]:
                    synthetic.append({
                        "role": "assistant",
                        "content": row["final_summary"],
                    })
                extracted = await provider.extract_from_session(
                    user_id=row["user_id"],
                    session_id=row["session_id"] or row["id"],
                    messages=synthetic,
                )
                extracted_count = len(extracted or [])
        except Exception:
            logger.exception("notify_terminal: memory extract failed for %s", workspace_id)

    return {
        "ok": True,
        "workspace_id": row["id"],
        "status": row["status"],
        "extracted_memories": extracted_count,
    }


async def get_run_events(pool, workspace_id: str, since: int, limit: int = 100) -> list[dict]:
    """Return workspace_events rows with seq > ``since``, ordered by seq.

    The bound is a `seq` watermark — adapters track the last seq they've
    seen and pass it on the next call. Empty list = nothing new (or the run
    doesn't exist; status endpoint distinguishes those).
    """
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT seq, event_type, payload, ts
                FROM workspace_events
                WHERE workspace_id = $1 AND seq > $2
                ORDER BY seq ASC
                LIMIT $3
                """,
                workspace_id,
                int(since),
                int(limit),
            )
        return [
            {
                "seq": r["seq"],
                "event_type": r["event_type"],
                "payload": r["payload"] if isinstance(r["payload"], dict) else {},
                "ts": r["ts"].isoformat() if r["ts"] else None,
            }
            for r in rows
        ]
    except Exception:
        logger.exception("messaging.get_run_events failed for %s", workspace_id)
        return []
