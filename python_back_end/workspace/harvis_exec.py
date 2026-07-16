"""
Harvis Execution Core — Phase 3: governed user-facing SANDBOX SHELL (lane 3).

`POST /api/harvis/exec` lets an authenticated user run a one-shot command in
their per-workspace sandbox container (the same WorkspaceTerminalManager the
agent uses via /api/tools/terminal). Every call routes through the Phase 2
choke point (`authorize_action`, lane 3) and lands a full Phase 1 trace in
`workspace_events`:

    decision → tool_call → terminal_output(s) → tool_result

Auth + ownership:
  • JWT (get_current_user_optimized), same as harvis_trace.
  • The `workspace_id` is scoped per user: if it names an existing
    `workspace_runs` row it must be OWNED by the caller (foreign/missing look
    identical — 404 semantics folded into scoping). Any other id is rewritten
    to a per-user sandbox id (`sbx-u<user_id>-<id>`) with its own
    `workspace_runs` row, so user A can never exec inside user B's container
    — the container NAME is derived from the effective id, and the effective
    id always embeds the caller's user id unless the caller owns the run.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized
from owui_compat.workspace_method import LANE_CONTAINER_TERMINAL

from .harvis_trace import _pool_of
from .orchestration.authz import authorize_action
from .terminal_container import (
    build_tool_call_payload,
    build_tool_result_payload,
    emit_terminal_event,
    get_terminal_manager,
    is_enabled,
    terminal_status,
)

logger = logging.getLogger(__name__)

harvis_exec_router = APIRouter(prefix="/api/harvis", tags=["harvis-exec"])


# ── Request model ────────────────────────────────────────────────────────────

class HarvisExecRequest(BaseModel):
    workspace_id: str = Field(..., min_length=1, max_length=128)
    target: str = Field(default="sandbox")
    command: str = Field(..., min_length=1)
    timeout_s: Optional[float] = Field(default=None, ge=1, le=600)


# ── Permission-mode resolution (Build Space Phase 3) ─────────────────────────

_LADDER_MODES = ("plan", "ask", "auto-accept", "full-auto")


async def _resolve_permission_mode(pool, workspace_id: str) -> tuple[str, Optional[str]]:
    """(permission_mode, vibecode_session_id) governing this workspace's exec.

    A vibecode turn's run row carries session_id = the vibecode session, whose
    stored ladder rung governs it. Anything else (per-user sandbox ids, generic
    runs) has no stored rung → DEFAULT 'ask'. This closes the old bypass where
    permission_mode=None skipped the friction gate entirely (authz.py) — every
    /api/harvis/exec and /api/harvis/jobs call now runs the risk ladder like a
    turn. Fail-safe on DB errors: ('ask', None)."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.id AS session_id, s.permission_mode
                FROM workspace_runs r
                JOIN vibecode_sessions s ON s.id = r.session_id
                WHERE r.id = $1
                """,
                workspace_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[harvis-exec:%s] permission-mode lookup failed (defaulting to 'ask'): %s",
            workspace_id, exc,
        )
        row = None
    if row and (row["permission_mode"] or "") in _LADDER_MODES:
        return row["permission_mode"], row["session_id"]
    return "ask", (row["session_id"] if row else None)


# ── Ownership scoping ────────────────────────────────────────────────────────

def _sanitize_id(raw: str) -> str:
    safe = "".join(c if c.isalnum() or c in "_.-" else "-" for c in raw.strip())
    return safe[:64] or "default"


async def _resolve_scoped_workspace(pool, workspace_id: str, user_id: int) -> str:
    """Return the workspace id this exec is allowed to touch.

    • Existing run owned by the caller → use it as-is (trace lands on that run).
    • Existing run owned by someone else → 404 (identical to missing — no
      existence leak, mirrors harvis_trace._require_owned_run).
    • No run row → derive `sbx-u<uid>-<id>` and upsert a lightweight
      workspace_runs row so the FK-backed workspace_events inserts succeed.
      The derived id embeds the caller's uid, so the sandbox container
      (harvis-ws-term-<id>) is per-user by construction.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM workspace_runs WHERE id = $1", workspace_id
        )
        if row is not None:
            if int(row["user_id"]) != int(user_id):
                raise HTTPException(status_code=404, detail="Workspace not found")
            return workspace_id

        scoped = f"sbx-u{int(user_id)}-{_sanitize_id(workspace_id)}"
        # The scoped id embeds the caller's uid, so a conflicting row can only
        # have been created by the same user — DO NOTHING is safe.
        await conn.execute(
            """
            INSERT INTO workspace_runs (id, user_id, session_id, task_brief, status)
            VALUES ($1, $2, $1, 'Sandbox shell', 'sandbox')
            ON CONFLICT (id) DO NOTHING
            """,
            scoped, int(user_id),
        )
    return scoped


# ── Routes ───────────────────────────────────────────────────────────────────

@harvis_exec_router.get("/exec/status")
async def exec_status(
    current_user: dict = Depends(get_current_user_optimized),
):
    """Kill-switch + readiness probe for the lane-3 sandbox shell."""
    return await terminal_status(force_probe=False)


@harvis_exec_router.post("/exec")
async def harvis_exec(
    body: HarvisExecRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Run one command in the caller's sandbox container (lane 3, governed).

    Trace invariant: every call emits exactly one `decision` (from the Phase 2
    choke point), one `tool_call`, `terminal_output` per non-empty stream, and
    one `tool_result` — all through emit_terminal_event so they persist in
    workspace_events AND fan out on the live SSE stream.
    """
    if body.target != "sandbox":
        raise HTTPException(400, "only target='sandbox' (lane 3) is supported in v0")

    # a. Hard gate: disabled/unready terminal must 503, never silently no-op.
    if not is_enabled():
        raise HTTPException(503, "terminal disabled (HARVIS_TERMINAL_ENABLED=false)")
    mgr = get_terminal_manager()
    report = await mgr.probe()
    if not report.ready:
        raise HTTPException(503, f"terminal not ready: {report.reason}")

    pool = _pool_of(request)
    user_id = int(current_user["id"])
    workspace_id = await _resolve_scoped_workspace(pool, body.workspace_id, user_id)

    # b. Phase 2 choke point — now with the REAL permission mode (Phase 3):
    # the session's stored ladder rung when the run belongs to a vibecode
    # session, else 'ask'. permission_mode=None (the old friction-gate bypass)
    # is gone. tool_name 'exec' (not 'terminal.exec') so risk.py classifies the
    # actual COMMAND (med ordinary / high destructive) instead of med-always.
    async def _emit_decision(payload: dict) -> None:
        await emit_terminal_event(
            pool, workspace_id, event_type="decision", payload=payload
        )

    permission_mode, vc_session_id = await _resolve_permission_mode(pool, workspace_id)
    res = await authorize_action(
        tool_name="exec",
        args={"command": body.command},
        lane=LANE_CONTAINER_TERMINAL,
        permission_mode=permission_mode,
        run_id=workspace_id,
        emit=_emit_decision,
        session_id=vc_session_id,
        pool=pool,
    )
    if not res.allowed:
        raise HTTPException(403, res.reason or "denied by execution policy")
    if res.needs_approval:
        # One-shot REST call — there is no interactive approval loop here, so a
        # gated action is REFUSED (fail closed), with the risk tier + why. Approve
        # it for the session in the Build UI or raise the session's permission mode.
        raise HTTPException(
            403,
            f"requires approval under permission mode '{permission_mode}' "
            f"(risk: {res.tier}): {res.reason or 'gated action'} — approve it for "
            "the session in the Build UI or raise the session's permission mode.",
        )

    # c. tool_call banner BEFORE running, then ensure + exec.
    await emit_terminal_event(
        pool, workspace_id,
        event_type="tool_call",
        payload=build_tool_call_payload(body.command),
    )
    try:
        await mgr.ensure(workspace_id)
        result = await mgr.exec(
            workspace_id=workspace_id,
            cmd=body.command,
            timeout_s=body.timeout_s,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:  # docker APIError etc.
        logger.error("[harvis-exec:%s] exec failed: %s", workspace_id, exc)
        raise HTTPException(503, f"sandbox exec failed: {exc}")

    # d. terminal_output per non-empty stream (exec already caps output), then
    # the tool_result banner.
    for stream in ("stdout", "stderr"):
        text = result.get(stream) or ""
        if text:
            await emit_terminal_event(
                pool, workspace_id,
                event_type="terminal_output",
                payload={
                    "tool": "harvis-terminal",
                    "stream": stream,
                    "text": text,
                    "run_id": workspace_id,
                },
            )
    await emit_terminal_event(
        pool, workspace_id,
        event_type="tool_result",
        payload=build_tool_result_payload(body.command, result),
    )

    return {
        "workspace_id": workspace_id,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
        "duration_ms": result["duration_ms"],
        "truncated": result["truncated"],
    }
