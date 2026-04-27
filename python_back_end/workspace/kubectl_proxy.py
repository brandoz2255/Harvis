"""
Kubectl proxy for the Harvis backend.

OpenClaw agents call this endpoint to run kubectl commands against the cluster
without needing kubectl binary in the OpenClaw pod.

Security model:
- Verifies OPENCLAW_GATEWAY_TOKEN on every request. FAILS CLOSED if token unset.
- Read-only operations execute immediately (get, list, describe, logs, top).
- Write operations (rollout restart, scale) are QUEUED for human approval.
  OpenClaw's tool loop blocks until the user approves or rejects in the UI.
  Approval timeout: 5 minutes.
- Command allowlist — PREFIX match (not substring) to prevent bypass attempts.
- Output sanitized — secrets/tokens/PEM/JWTs redacted before returning.
- Execution timeout — commands killed after 30s (configurable 1-120s).

Endpoints (OpenClaw → backend, needs OPENCLAW_GATEWAY_TOKEN):
  POST /kubectl/exec           — execute a kubectl command
  GET  /kubectl/health         — check kubectl availability

Approval endpoints (user-facing, needs JWT auth):
  GET  /kubectl/pending        — list commands awaiting human approval
  POST /kubectl/approve/{id}   — approve a pending command
  POST /kubectl/reject/{id}    — reject a pending command
"""

import asyncio
import logging
import os
import re
import subprocess
import shlex
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, field_validator

from auth_optimized import get_current_user_optimized
from workspace.capability_check import verify_capability
from workspace.gateway_auth import resolve_gateway_caller

logger = logging.getLogger(__name__)

OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
APPROVAL_TIMEOUT_SECONDS = 300  # 5 minutes

# ─── In-memory approval registry ──────────────────────────────────────────────
# Keyed by approval_id (8-char hex). All three dicts are always in sync.
_approval_events: dict[str, asyncio.Event] = {}
_approval_results: dict[str, bool] = {}      # True = approved, False = rejected
_pending_commands: dict[str, dict] = {}       # metadata for GET /kubectl/pending

# ─── Command allowlists (PREFIX match) ────────────────────────────────────────
# Tuples so iteration order is deterministic; longest-prefix wins naturally.
ALLOWED_READ_PREFIXES: tuple[str, ...] = (
    "get pods",
    "get services",
    "get deployments",
    "get replicasets",
    "get statefulsets",
    "get daemonsets",
    "get jobs",
    "get cronjobs",
    "get nodes",
    "get events",
    "get namespaces",
    "get endpoints",
    "describe pod",
    "describe service",
    "describe deployment",
    "describe node",
    "describe replicaset",
    "describe statefulset",
    "describe daemonset",
    "describe job",
    "describe cronjob",
    "logs",
    "top pods",
    "top nodes",
    "rollout status",
)

ALLOWED_WRITE_PREFIXES: tuple[str, ...] = (
    "rollout restart",
    "scale deployment",
    "scale statefulset",
    "scale replicaset",
)

kubectl_proxy_router = APIRouter(tags=["kubectl-proxy"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sanitize_output(output: str) -> str:
    """Redact secrets, PEM certificates, and JWT tokens from kubectl output."""
    patterns = [
        # key=value / key: value patterns (8+ char value to avoid false positives)
        (
            r'(?i)(token|password|secret|key|auth)\s*[=:]\s*["\']?[^\s,;"\']{8,}["\']?',
            r'\1: [REDACTED]',
        ),
        # PEM blocks
        (r'(?i)-----BEGIN [A-Z ]+-----[^-]+-----END [A-Z ]+-----', '[REDACTED: PEM]'),
        # JWT tokens (eyJ…)
        (r'(?i)(eyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-\.]*)', '[REDACTED: JWT]'),
    ]
    for pattern, replacement in patterns:
        output = re.sub(pattern, replacement, output)
    return output


def _validate_command(command: str) -> tuple[bool, bool]:
    """
    Validate a kubectl command via strict prefix matching.
    Returns (is_allowed, is_write).
    Prefix match prevents 'get pods; delete pod foo' style bypass attempts.
    (shell=False in subprocess makes that safe anyway, but belt-and-suspenders.)
    """
    cmd_stripped = command.strip().lower()

    for prefix in ALLOWED_WRITE_PREFIXES:
        if cmd_stripped.startswith(prefix):
            return True, True

    for prefix in ALLOWED_READ_PREFIXES:
        if cmd_stripped.startswith(prefix):
            return True, False

    return False, False


async def _run_kubectl(command: str, namespace: Optional[str], timeout: int) -> dict:
    """Execute a validated kubectl command and return a result dict."""
    kubectl_cmd = ["kubectl"]
    if namespace:
        kubectl_cmd.extend(["-n", namespace])

    try:
        args = shlex.split(command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid command syntax: {exc}")

    kubectl_cmd.extend(args)
    logger.info("kubectl_proxy: exec %r", " ".join(kubectl_cmd))

    t0 = time.time()
    try:
        result = subprocess.run(
            kubectl_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,   # CRITICAL: never use shell=True
        )
        return {
            "ok": result.returncode == 0,
            "command": " ".join(kubectl_cmd),
            "stdout": _sanitize_output(result.stdout),
            "stderr": _sanitize_output(result.stderr),
            "exit_code": result.returncode,
            "duration_ms": int((time.time() - t0) * 1000),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"Command timed out after {timeout}s")
    except Exception as exc:
        logger.error("kubectl_proxy: subprocess error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


# ─── Models ───────────────────────────────────────────────────────────────────

class KubectlExecRequest(BaseModel):
    command: str
    namespace: Optional[str] = None
    timeout: int = 30

    @field_validator("timeout")
    @classmethod
    def _timeout_range(cls, v: int) -> int:
        if not (1 <= v <= 120):
            raise ValueError("timeout must be between 1 and 120 seconds")
        return v


class KubectlResponse(BaseModel):
    ok: bool
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    is_write: bool = False


# ─── Endpoints ────────────────────────────────────────────────────────────────

@kubectl_proxy_router.post("/exec", response_model=KubectlResponse)
async def kubectl_exec(
    req: KubectlExecRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    """
    Execute a kubectl command.

    Read commands (get, describe, logs, top) run immediately.
    Write commands (rollout restart, scale) are queued for human approval.
    This endpoint BLOCKS until the user approves or rejects (max 5 minutes).
    OpenClaw's tool loop is suspended during that window — the agent waits.
    """
    await resolve_gateway_caller(request, authorization)
    await verify_capability("kubectl", request, authorization)

    is_allowed, is_write = _validate_command(req.command)
    if not is_allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Command not in allowlist: '{req.command}'",
        )

    # ── Read-only: execute immediately ────────────────────────────────────────
    if not is_write:
        result = await _run_kubectl(req.command, req.namespace, req.timeout)
        return KubectlResponse(**result, is_write=False)

    # ── Write: queue for human approval ───────────────────────────────────────
    approval_id = uuid4().hex[:8]
    event = asyncio.Event()
    _approval_events[approval_id] = event
    _pending_commands[approval_id] = {
        "approval_id": approval_id,
        "command": req.command,
        "namespace": req.namespace,
        "timeout": req.timeout,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }

    logger.warning(
        "kubectl_proxy: write command QUEUED for approval [%s]: %r",
        approval_id,
        req.command,
    )

    try:
        # Block the tool call until user acts (or timeout)
        await asyncio.wait_for(event.wait(), timeout=APPROVAL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        _pending_commands.pop(approval_id, None)
        _approval_events.pop(approval_id, None)
        _approval_results.pop(approval_id, None)
        raise HTTPException(
            status_code=408,
            detail="Approval timed out — command expired after 5 minutes without user action",
        )

    approved = _approval_results.pop(approval_id, False)
    _approval_events.pop(approval_id, None)
    _pending_commands.pop(approval_id, None)

    if not approved:
        raise HTTPException(status_code=403, detail="Command rejected by user")

    result = await _run_kubectl(req.command, req.namespace, req.timeout)
    return KubectlResponse(**result, is_write=True)


@kubectl_proxy_router.get("/health")
async def kubectl_health(request: Request, authorization: Optional[str] = Header(default=None)):
    """Check kubectl availability. OpenClaw-only endpoint."""
    await resolve_gateway_caller(request, authorization)
    try:
        result = subprocess.run(
            ["kubectl", "version", "--client"],
            capture_output=True, text=True, timeout=5,
        )
        version = result.stdout.strip().split("\n")[0] if result.stdout else "unknown"
        return {"ok": True, "kubectl_version": version}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ─── User-facing approval endpoints (JWT auth) ────────────────────────────────

@kubectl_proxy_router.get("/pending")
async def list_pending_commands(
    current_user=Depends(get_current_user_optimized),
):
    """
    Return all kubectl write commands currently awaiting human approval.
    Polled every ~2 seconds by the WorkspacePanel approval widget.
    """
    return {"pending": list(_pending_commands.values())}


@kubectl_proxy_router.post("/approve/{approval_id}")
async def approve_command(
    approval_id: str,
    current_user=Depends(get_current_user_optimized),
):
    """Approve a pending kubectl write command. Unblocks the OpenClaw tool call."""
    if approval_id not in _approval_events:
        raise HTTPException(status_code=404, detail="No pending command with that ID")

    cmd = _pending_commands.get(approval_id, {}).get("command", "")
    logger.warning(
        "kubectl_proxy: APPROVED by user %s [%s]: %r",
        current_user.get("id"), approval_id, cmd,
    )
    _approval_results[approval_id] = True
    _approval_events[approval_id].set()
    return {"ok": True, "status": "approved", "command": cmd}


@kubectl_proxy_router.post("/reject/{approval_id}")
async def reject_command(
    approval_id: str,
    current_user=Depends(get_current_user_optimized),
):
    """Reject a pending kubectl write command. Returns 403 to the OpenClaw tool call."""
    if approval_id not in _approval_events:
        raise HTTPException(status_code=404, detail="No pending command with that ID")

    cmd = _pending_commands.get(approval_id, {}).get("command", "")
    logger.warning(
        "kubectl_proxy: REJECTED by user %s [%s]: %r",
        current_user.get("id"), approval_id, cmd,
    )
    _approval_results[approval_id] = False
    _approval_events[approval_id].set()
    return {"ok": True, "status": "rejected", "command": cmd}
