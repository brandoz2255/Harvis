"""
FastAPI routes for the persistent per-session workspace terminal.

The agent inside the OpenClaw container calls these endpoints to run shell
commands in a dedicated Docker container per Discord/workspace session.
Each session keeps:
  • A named container (`harvis-ws-term-<id>`) on the openclaw-internal network
  • A named volume mounted at `/workspace` so files persist across container
    restarts, OOM kills, image bumps, redeploys

Persistence model (HARVIS_TERMINAL_PERSISTENT=true, default ON):
  - First `exec` lazily spawns the container + volume.
  - Subsequent execs from the same session_id REUSE the running container.
  - If the container was stopped (idle sweep, manual stop), it's restarted —
    /workspace contents intact via the named volume.
  - Idle sweep STOPS but does NOT remove containers; the next exec restarts.
  - Explicit teardown is required to wipe a session's container + volume.

Auth: all endpoints require the same `OPENCLAW_GATEWAY_TOKEN` the OpenClaw
agent uses for backend tool calls (see workspace/gateway_auth.py).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field

from .terminal_container import (
    build_tool_call_payload,
    build_tool_result_payload,
    emit_terminal_event,
    get_terminal_manager,
    is_enabled,
    terminal_status,
)

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/tools/terminal",
    tags=["workspace-terminal"],
)


# ── Auth dependency ────────────────────────────────────────────────────────

def _check_gateway_token(authorization: Optional[str] = Header(default=None)) -> None:
    """Verify Bearer <OPENCLAW_GATEWAY_TOKEN>. Same shape as gateway_auth.py."""
    from . import gateway_auth  # local import to avoid module-load cycle

    expected = (
        gateway_auth._BUNDLED_TOKEN or gateway_auth._LEGACY_TOKEN  # noqa: SLF001
    )
    if not expected:
        # No token configured — DO NOT silently allow. Fail closed in prod.
        raise HTTPException(503, "terminal not configured: OPENCLAW_GATEWAY_TOKEN unset")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing or malformed Authorization header")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(401, "invalid proxy token")


# ── Request / response models ───────────────────────────────────────────────

class ExecRequest(BaseModel):
    cmd: str = Field(..., min_length=1, description="Shell command to run inside the container")
    timeout_s: Optional[float] = Field(default=None, ge=1, le=600)
    workdir: str = Field(default="/workspace")


class ExecResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    truncated: bool
    container: str


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/status")
async def status() -> dict:
    """Probe Docker daemon + network + base image. Cheap; safe to poll."""
    return await terminal_status(force_probe=False)


@router.post(
    "/{workspace_id}/exec",
    response_model=ExecResponse,
    dependencies=[Depends(_check_gateway_token)],
)
async def exec_in_terminal(
    workspace_id: str,
    body: ExecRequest,
    request: Request,
) -> ExecResponse:
    """Run a shell command in the workspace's persistent terminal container.

    Lazy-spawn semantics: if the container doesn't exist yet, one is created
    (with the volume mount) before the command runs. If the container exists
    but was stopped, it's restarted with /workspace state intact.

    Emits two `workspace_events` rows for live Discord progress display:
      tool_call   → "⚙️ Harvis terminal: `<cmd>`"
      tool_result → "✅ complete (exit=0)" or "❌ failed (exit=N)"
    """
    if not is_enabled():
        raise HTTPException(
            503,
            "terminal disabled (HARVIS_TERMINAL_ENABLED=false)",
        )
    mgr = get_terminal_manager()
    report = await mgr.probe()
    if not report.ready:
        raise HTTPException(503, f"terminal not ready: {report.reason}")

    pool = getattr(request.app.state, "pg_pool", None)

    # Emit tool_call banner BEFORE running so Discord shows "starting…" early
    call_payload = build_tool_call_payload(body.cmd)
    await emit_terminal_event(pool, workspace_id, event_type="tool_call", payload=call_payload)

    try:
        result = await mgr.exec(
            workspace_id=workspace_id,
            cmd=body.cmd,
            timeout_s=body.timeout_s,
            workdir=body.workdir,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))

    result_payload = build_tool_result_payload(body.cmd, result)
    await emit_terminal_event(pool, workspace_id, event_type="tool_result", payload=result_payload)

    return ExecResponse(**result)


@router.post(
    "/{workspace_id}/teardown",
    dependencies=[Depends(_check_gateway_token)],
)
async def teardown_terminal(workspace_id: str) -> dict:
    """Stop + remove the workspace's container.

    Does NOT remove the named volume — the user's /workspace state is
    preserved for the next session that uses the same workspace_id. Use the
    separate `/wipe` endpoint to also delete the volume.
    """
    mgr = get_terminal_manager()
    removed = await mgr.teardown(workspace_id)
    return {"ok": True, "removed": removed, "workspace_id": workspace_id}


@router.post(
    "/{workspace_id}/wipe",
    dependencies=[Depends(_check_gateway_token)],
)
async def wipe_terminal(workspace_id: str) -> dict:
    """Tear down the container AND delete its named volume.

    Destructive — the agent's /workspace files for this session are gone.
    Intended for explicit cleanup (manual reset, user-requested fresh start).
    """
    import asyncio

    from docker.errors import NotFound

    mgr = get_terminal_manager()
    await mgr.teardown(workspace_id)
    vol_name = mgr._volume_name(workspace_id)  # noqa: SLF001
    if mgr._client is None:  # noqa: SLF001
        return {"ok": False, "reason": "docker client unavailable"}
    try:
        vol = await asyncio.to_thread(mgr._client.volumes.get, vol_name)  # noqa: SLF001
        await asyncio.to_thread(vol.remove, force=True)
        return {"ok": True, "wiped_volume": vol_name, "workspace_id": workspace_id}
    except NotFound:
        return {"ok": True, "wiped_volume": None, "workspace_id": workspace_id,
                "note": "volume did not exist"}
    except Exception as exc:
        logger.warning("[terminal:%s] volume remove failed: %s", workspace_id, exc)
        return {"ok": False, "reason": str(exc)[:200]}


@router.get(
    "/{workspace_id}/info",
    dependencies=[Depends(_check_gateway_token)],
)
async def terminal_info(workspace_id: str) -> dict:
    """Look up the container + volume names for a workspace without spawning."""
    mgr = get_terminal_manager()
    state = mgr._terminals.get(workspace_id)  # noqa: SLF001
    return {
        "workspace_id": workspace_id,
        "container_name": mgr._container_name(workspace_id),  # noqa: SLF001
        "volume_name": mgr._volume_name(workspace_id),  # noqa: SLF001
        "tracked": state is not None,
        "last_used_at": getattr(state, "last_used_at", None) if state else None,
    }
