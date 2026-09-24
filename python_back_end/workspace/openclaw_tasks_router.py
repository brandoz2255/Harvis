"""
OpenClaw task/instance REST + WebSocket surface.

The `newjfrontend` OpenClaw UI (hooks/useOpenClawAPI.ts, hooks/useOpenClawWebSocket.ts,
components/openclaw/*) was built against an `/api/openclaw/tasks` + `/ws/openclaw`
API that never existed on the backend, so every call 404'd. This module implements
that contract as a thin, real translation layer over the existing workspace engine
in ``workspace_router`` — it does NOT stand up a second execution stack:

* Creating a task launches a real workspace run (``launch_workspace``), so the
  agent actually executes and streams events.
* The WebSocket subscribes to the same per-workspace live broadcaster the SSE
  ``/api/workspace/stream/{id}`` endpoint uses, and re-frames each ``OpenClawEvent``
  into the ``{type:'event', event:{job_id,type,payload,timestamp}}`` envelope the
  frontend store parses.

Scope note (honest): the frontend models a browser-runner/computer-use agent with
per-step screenshots, VM ``instances`` and ``needs_approval`` gates. That runner is
goal #4 ("Harvis's own computer") and is not built yet, so:
  * task ``steps``/``screenshots`` stay empty and ``instances`` are logical records
    (no VM is provisioned), and
  * ``/approve`` and ``/context`` validate + record the decision but there is no
    interactive runner consuming it yet.
Everything here is a real, authed endpoint with ownership checks — nothing is
faked as "succeeded" — it simply exposes the job_started/completed/failed lifecycle
the current agent path actually emits.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel

from auth_optimized import decode_token_fast, get_current_user_optimized

from .workspace_router import (
    LaunchRequest,
    cancel_workspace_internal,
    launch_workspace,
    _workspace_broadcasters,
    _workspaces,
)

logger = logging.getLogger(__name__)

openclaw_tasks_router = APIRouter(tags=["openclaw-tasks"])

# Default agent route for tasks created through the OpenClaw UI. "main" is the
# OpenClaw gateway route; set OPENCLAW_TASKS_DEFAULT_AGENT=local to run tasks on
# the direct-Ollama path when the gateway is not up.
_DEFAULT_AGENT = os.getenv("OPENCLAW_TASKS_DEFAULT_AGENT", "main")

# ── In-memory records for the OpenClaw-specific metadata the workspace engine
# does not track (instance binding, policy profile, create time). The authoritative
# run state always comes from ``_workspaces``; these only add the task-surface fields.
_oc_tasks: dict[str, dict] = {}       # task_id -> {user_id, instance_id, policy_profile, created_at, task_prompt, session_id}
_oc_instances: dict[str, dict] = {}   # instance_id -> instance record (see _instance_public)

# workspace status -> frontend OpenClawTask.status
_STATUS_MAP = {
    "running": "running",
    "queued": "pending",
    "pending": "pending",
    "done": "completed",
    "completed": "completed",
    "cancelled": "cancelled",
    "error": "failed",
    "failed": "failed",
    "paused": "paused",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────── request models ────────────────────────────────

class CreateTaskRequest(BaseModel):
    task_prompt: str
    session_id: Optional[str] = None
    instance_id: Optional[str] = None
    policy_profile: Optional[str] = "default"
    max_runtime_minutes: Optional[int] = None
    agent_id: Optional[str] = None  # optional override of the default route


class CancelTaskRequest(BaseModel):
    reason: Optional[str] = None


class ApprovalRequest(BaseModel):
    request_id: str
    approved: bool
    reason: Optional[str] = None


class ContextRequest(BaseModel):
    request_id: str
    response: str
    attachments: Optional[list] = None


class CreateInstanceRequest(BaseModel):
    name: str
    vm_type: Optional[str] = "docker"   # 'virtualbox' | 'docker' | 'cloud'
    vm_config: Optional[dict] = None


# ─────────────────────────── serializers ───────────────────────────────────

def _task_public(task_id: str) -> Optional[dict]:
    """Merge OpenClaw metadata with the live workspace run into an OpenClawTask."""
    meta = _oc_tasks.get(task_id)
    ws = _workspaces.get(task_id)
    if meta is None and ws is None:
        return None
    meta = meta or {}
    ws = ws or {}
    raw_status = ws.get("status", "running")
    status = _STATUS_MAP.get(raw_status, "running")
    result = ws.get("result") or ws.get("final_answer")
    return {
        "id": task_id,
        "instanceId": meta.get("instance_id") or "local",
        "sessionId": meta.get("session_id") or ws.get("session_id"),
        "description": meta.get("task_prompt") or ws.get("task_brief") or "",
        "status": status,
        "steps": [],
        "currentStep": 0,
        "result": result if status == "completed" else None,
        "errorMessage": ws.get("error") if status == "failed" else None,
        "startedAt": meta.get("created_at"),
        "completedAt": _now_iso() if status in ("completed", "failed", "cancelled") else None,
        "createdAt": meta.get("created_at") or _now_iso(),
        "progressPercentage": 100 if status in ("completed", "failed", "cancelled") else 0,
        "policyProfile": meta.get("policy_profile"),
    }


def _instance_public(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "name": rec["name"],
        "vmType": rec.get("vm_type", "docker"),
        "status": rec.get("status", "online"),
        "lastConnectedAt": rec.get("last_connected_at"),
        "vmIp": rec.get("vm_ip"),
        "vmPort": rec.get("vm_port"),
    }


def _ensure_default_instance(user_id: int) -> None:
    """Seed a logical 'local' instance so the UI has something selectable.

    Represents the local workspace runtime — no VM is provisioned. Real VM
    instances arrive with the browser-runner (goal #4).
    """
    for rec in _oc_instances.values():
        if rec.get("user_id") == user_id:
            return
    inst_id = f"local-{user_id}"
    _oc_instances[inst_id] = {
        "id": inst_id,
        "user_id": user_id,
        "name": "Local workspace",
        "vm_type": "docker",
        "status": "online",
        "created_at": _now_iso(),
    }


def _owns(task_id: str, user_id: int) -> bool:
    meta = _oc_tasks.get(task_id)
    if meta is not None:
        return int(meta.get("user_id", -1)) == int(user_id)
    ws = _workspaces.get(task_id)
    if ws is not None:
        return int(ws.get("user_id", -1)) == int(user_id)
    return False


# ─────────────────────────────── tasks ─────────────────────────────────────

@openclaw_tasks_router.post("/api/openclaw/tasks")
async def create_task(
    request: Request,
    req: CreateTaskRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Create an OpenClaw task — launches a real workspace run."""
    prompt = (req.task_prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="task_prompt is required")

    launch_req = LaunchRequest(
        task_brief=prompt,
        chat_history=[],
        session_id=req.session_id,
        agent_id=(req.agent_id or _DEFAULT_AGENT),
    )
    # Reuse the workspace launch path in full (registry, broadcaster, DB row,
    # interactive-enable). Returns {workspace_id, session_id, status, ...}.
    launched = await launch_workspace(request, launch_req, current_user)
    task_id = launched["workspace_id"]

    _oc_tasks[task_id] = {
        "user_id": current_user["id"],
        "instance_id": req.instance_id or f"local-{current_user['id']}",
        "policy_profile": req.policy_profile or "default",
        "max_runtime_minutes": req.max_runtime_minutes,
        "created_at": _now_iso(),
        "task_prompt": prompt,
        "session_id": launched.get("session_id"),
    }
    logger.info(
        "OpenClaw task created: id=%s user=%s instance=%s",
        task_id, current_user["id"], _oc_tasks[task_id]["instance_id"],
    )
    return _task_public(task_id)


@openclaw_tasks_router.get("/api/openclaw/tasks")
async def list_tasks(current_user: dict = Depends(get_current_user_optimized)):
    """List the current user's OpenClaw tasks (most recent first)."""
    uid = int(current_user["id"])
    tasks = [
        _task_public(tid)
        for tid, meta in _oc_tasks.items()
        if int(meta.get("user_id", -1)) == uid
    ]
    tasks = [t for t in tasks if t is not None]
    tasks.sort(key=lambda t: t.get("createdAt") or "", reverse=True)
    return {"tasks": tasks}


@openclaw_tasks_router.get("/api/openclaw/tasks/{task_id}")
async def get_task(
    task_id: str,
    current_user: dict = Depends(get_current_user_optimized),
):
    if not _owns(task_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Task not found")
    task = _task_public(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@openclaw_tasks_router.post("/api/openclaw/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    req: CancelTaskRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    if not _owns(task_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Task not found")
    result = await cancel_workspace_internal(task_id, audit_actor=f"user:{current_user['id']}")
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "status": result.get("status"), "detail": result}


@openclaw_tasks_router.post("/api/openclaw/tasks/{task_id}/approve")
async def approve_task(
    task_id: str,
    req: ApprovalRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Record an approval decision for a task's pending gate.

    The interactive approval gate (``needs_approval`` events) is driven by the
    browser-runner (goal #4), which is not built yet — this validates ownership
    and the request shape and records the decision so the flow is wired end to end.
    """
    if not _owns(task_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Task not found")
    logger.info(
        "OpenClaw approval: task=%s request=%s approved=%s",
        task_id, req.request_id, req.approved,
    )
    return {
        "task_id": task_id,
        "request_id": req.request_id,
        "approved": req.approved,
        "status": "recorded",
    }


@openclaw_tasks_router.post("/api/openclaw/tasks/{task_id}/context")
async def submit_context(
    task_id: str,
    req: ContextRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    """Record a context reply the agent asked the user for. See approve_task note."""
    if not _owns(task_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Task not found")
    logger.info(
        "OpenClaw context reply: task=%s request=%s len=%d",
        task_id, req.request_id, len(req.response or ""),
    )
    return {"task_id": task_id, "request_id": req.request_id, "status": "recorded"}


# ───────────────────────────── instances ───────────────────────────────────

@openclaw_tasks_router.get("/api/openclaw/instances")
async def list_instances(current_user: dict = Depends(get_current_user_optimized)):
    uid = int(current_user["id"])
    _ensure_default_instance(uid)
    instances = [
        _instance_public(rec)
        for rec in _oc_instances.values()
        if int(rec.get("user_id", -1)) == uid
    ]
    return {"instances": instances}


@openclaw_tasks_router.post("/api/openclaw/instances")
async def create_instance(
    req: CreateInstanceRequest,
    current_user: dict = Depends(get_current_user_optimized),
):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    inst_id = str(uuid.uuid4())[:12]
    _oc_instances[inst_id] = {
        "id": inst_id,
        "user_id": current_user["id"],
        "name": name,
        "vm_type": req.vm_type or "docker",
        "vm_config": req.vm_config or {},
        "status": "online",
        "created_at": _now_iso(),
    }
    logger.info("OpenClaw instance created: id=%s user=%s name=%r", inst_id, current_user["id"], name)
    return _instance_public(_oc_instances[inst_id])


# ─────────────────────────── websocket bridge ──────────────────────────────

def _event_envelope(task_id: str, ev_type: str, payload: dict) -> dict:
    return {
        "type": "event",
        "event": {
            "job_id": task_id,
            "type": ev_type,
            "payload": payload or {},
            "timestamp": _now_iso(),
        },
    }


def _translate(task_id: str, ev) -> dict:
    """Map a workspace OpenClawEvent into the frontend event envelope."""
    data = getattr(ev, "data", {}) or {}
    etype = getattr(ev, "type", "log")
    if etype in ("done", "completed"):
        payload = dict(data)
        payload.setdefault(
            "result",
            data.get("result") or data.get("summary") or data.get("content") or "",
        )
        return _event_envelope(task_id, "job_completed", payload)
    if etype in ("error", "failed"):
        payload = dict(data)
        payload.setdefault(
            "error_message",
            data.get("error") or data.get("message") or "Task failed",
        )
        return _event_envelope(task_id, "job_failed", payload)
    if etype == "cancelled":
        return _event_envelope(task_id, "job_cancelled", dict(data))
    # Everything else (token/tool_call/tool_result/log/narration) is forwarded
    # verbatim; the store logs it in the activity feed.
    return _event_envelope(task_id, etype, dict(data))


def _ws_authenticate(websocket: WebSocket) -> Optional[int]:
    """Resolve the user id from a ?token= query param or the access_token cookie."""
    token = websocket.query_params.get("token")
    if not token:
        token = websocket.cookies.get("access_token")
    if not token:
        return None
    payload = decode_token_fast(token)
    if not payload:
        return None
    try:
        return int(payload.get("sub"))
    except (TypeError, ValueError):
        return None


@openclaw_tasks_router.websocket("/ws/openclaw/tasks/{task_id}")
async def task_events_ws(websocket: WebSocket, task_id: str):
    """Stream a task's live events to the OpenClaw UI.

    Auth: JWT via ?token= (or the access_token cookie). Ownership is enforced
    against the task's creating user. Bridges the per-workspace broadcaster into
    the frontend's {type:'event', event:{...}} envelope.
    """
    user_id = _ws_authenticate(websocket)
    if user_id is None:
        await websocket.close(code=1008)  # policy violation / unauthenticated
        return
    if not _owns(task_id, user_id):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    # Initial snapshot.
    task = _task_public(task_id)
    try:
        await websocket.send_json({"type": "initial_state", "job": task})
        if task and task["status"] == "running":
            await websocket.send_json(
                _event_envelope(task_id, "job_started", {"started_at": task.get("startedAt")})
            )
    except Exception:
        return

    broadcaster = _workspace_broadcasters.get(task_id)
    if broadcaster is None:
        # Run already terminal (or never had a live broadcaster) — emit a
        # terminal event derived from stored state, then close.
        if task and task["status"] in ("completed", "failed", "cancelled"):
            term = {
                "completed": ("job_completed", {"result": task.get("result") or ""}),
                "failed": ("job_failed", {"error_message": task.get("errorMessage") or "Task failed"}),
                "cancelled": ("job_cancelled", {}),
            }[task["status"]]
            try:
                await websocket.send_json(_event_envelope(task_id, term[0], term[1]))
            except Exception:
                pass
        await websocket.close()
        return

    live_queue = broadcaster.subscribe()
    try:
        while True:
            try:
                item = await asyncio.wait_for(live_queue.get(), timeout=25)
            except asyncio.TimeoutError:
                # Keepalive ping so idle proxies don't drop the socket.
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue

            if item is None:  # broadcaster sentinel — background task ended
                break

            _seq, ev = item
            envelope = _translate(task_id, ev)
            try:
                await websocket.send_json(envelope)
            except Exception:
                break

            if envelope["event"]["type"] in ("job_completed", "job_failed", "job_cancelled"):
                break
    finally:
        try:
            broadcaster.unsubscribe(live_queue)
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
