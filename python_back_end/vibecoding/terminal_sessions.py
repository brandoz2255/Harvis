"""Terminal-session REST API over the VibeCode PTY (Execution Core Phase 3).

The existing `/ws/vibecoding/terminal` WebSocket (terminal.py) is a raw byte
pump — great for keystrokes, but it has no side-channel for `resize`, so xterm
reflow never reaches the docker exec's PTY. This module adds a small JWT-authed
session registry:

    POST   /api/harvis/terminal/sessions            → pre-create the bash PTY
                                                       exec (NOT started) and
                                                       hand back a ws_url
    GET    /api/harvis/terminal/sessions/{sid}      → session meta (owner-only)
    POST   /api/harvis/terminal/sessions/{sid}/resize → docker exec_resize
    DELETE /api/harvis/terminal/sessions/{sid}      → drop the session

Wiring with the WS: the returned ws_url carries `harvis_sid=<sid>`; the WS
handler (terminal.py) looks the session up here, verifies the SAME user owns
it AND that it targets the SAME container the WS resolved, and starts the
pre-created exec instead of making its own. That gives resize an exec_id to
target while leaving the plain (no harvis_sid) WS path byte-for-byte intact.

Gating: the whole feature sits behind HARVIS_BUILD_SHELL exactly like the WS
(default OFF → every endpoint 503s). Registry is in-process — sessions do not
survive a backend restart, which matches the lifetime of the WS pump itself.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_optimized import get_current_user_optimized

from .containers import container_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/harvis/terminal", tags=["harvis-terminal-sessions"])

# session_id -> {exec_id, container_id, container_name, user_id, workspace_id,
#                created_at, started}
_sessions: dict[str, dict] = {}


def _shell_enabled() -> bool:
    """Same gate as the WS handler in terminal.py (HARVIS_BUILD_SHELL, default OFF)."""
    return os.getenv("HARVIS_BUILD_SHELL", "").strip().lower() in ("1", "true", "yes", "on")


def _require_shell_enabled() -> None:
    if not _shell_enabled():
        raise HTTPException(
            503, "Shell access is disabled (HARVIS_BUILD_SHELL is off, pending review)"
        )


def get_session(session_id: str) -> Optional[dict]:
    """Registry lookup used by terminal.py's WS handler (harvis_sid param)."""
    return _sessions.get(session_id)


def _owned_session(session_id: str, current_user: dict) -> dict:
    """Owner-scoped fetch: missing and foreign sessions look identical (404)."""
    entry = _sessions.get(session_id)
    if not entry or int(entry.get("user_id", -1)) != int(current_user["id"]):
        raise HTTPException(404, "Terminal session not found")
    return entry


# ── Request models ───────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    workspace_id: Optional[str] = Field(default=None, max_length=128)


class ResizeRequest(BaseModel):
    rows: int = Field(..., ge=1, le=500)
    cols: int = Field(..., ge=1, le=1000)


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/sessions")
async def create_terminal_session(
    body: CreateSessionRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Pre-create a bash PTY exec in the user's runner container.

    The exec is created but NOT started — the WS (`ws_url`) starts the socket
    pump. Resolution mirrors terminal.py: runner container first, IDE container
    as fallback, plus the same user_id-label ownership check.
    """
    _require_shell_enabled()

    workspace_id = (body.workspace_id or f"harvis-{int(current_user['id'])}").strip()

    container = await container_manager.get_runner_container(workspace_id)
    if not container:
        container = await container_manager.get_container(workspace_id)
    if not container:
        raise HTTPException(
            404, "No container for this session — start a Build/VibeCode session first"
        )

    # Ownership: fail CLOSED — a container without a user_id label, or one owned by
    # someone else, is not attachable (a missing label must never mean "anyone").
    user_id_label = container.labels.get("user_id")
    if not user_id_label or str(current_user["id"]) != user_id_label:
        raise HTTPException(404, "No container for this session")

    await asyncio.to_thread(container.reload)
    if container.status != "running":
        raise HTTPException(409, f"Container not running: {container.status}")

    try:
        exec_instance = await asyncio.to_thread(
            container.client.api.exec_create,
            container.id,
            cmd="/bin/bash -l",
            stdin=True,
            tty=True,
            environment={
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "HOME": "/workspace",
                "USER": "root",
            },
            workdir="/workspace",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("terminal session exec_create failed (%s): %s", workspace_id, exc)
        raise HTTPException(503, f"failed to create PTY: {exc}")

    session_id = uuid.uuid4().hex
    _sessions[session_id] = {
        "session_id": session_id,
        "exec_id": exec_instance["Id"],
        "container_id": container.id,
        "container_name": container.name,
        "user_id": int(current_user["id"]),
        "workspace_id": workspace_id,
        "created_at": time.time(),
        "started": False,
    }
    logger.info(
        "🖥️ terminal session %s created (user=%s container=%s)",
        session_id, current_user["id"], container.name,
    )
    return {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "ws_url": (
            f"/ws/vibecoding/terminal?session_id={quote(workspace_id)}"
            f"&harvis_sid={session_id}"
        ),
    }


@router.get("/sessions/{session_id}")
async def get_terminal_session(
    session_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    _require_shell_enabled()
    entry = _owned_session(session_id, current_user)
    return {
        "session_id": entry["session_id"],
        "workspace_id": entry["workspace_id"],
        "container_name": entry["container_name"],
        "created_at": entry["created_at"],
        "started": entry["started"],
    }


@router.post("/sessions/{session_id}/resize")
async def resize_terminal_session(
    session_id: str,
    body: ResizeRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Resize the PTY behind the session's docker exec (the missing piece the
    raw byte-pump WS cannot carry)."""
    _require_shell_enabled()
    entry = _owned_session(session_id, current_user)

    client = container_manager.docker_client
    if client is None:
        raise HTTPException(503, "docker client unavailable")
    try:
        await asyncio.to_thread(
            client.api.exec_resize,
            entry["exec_id"],
            height=body.rows,
            width=body.cols,
        )
    except Exception as exc:  # APIError: exec not started yet / already exited
        logger.debug("terminal session %s resize skipped: %s", session_id, exc)
        raise HTTPException(409, f"resize unavailable: {exc}")
    return {"ok": True, "rows": body.rows, "cols": body.cols}


@router.delete("/sessions/{session_id}")
async def delete_terminal_session(
    session_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Drop the session. Docker has no exec-kill API — the bash process ends
    when the WS pump closes its socket (or the container stops); this is a
    best-effort registry cleanup."""
    _require_shell_enabled()
    _owned_session(session_id, current_user)
    _sessions.pop(session_id, None)
    return {"ok": True, "session_id": session_id}
