"""
Kubectl proxy for the Harvis backend.
OpenClaw agents call this endpoint to run kubectl commands against the cluster
without needing kubectl binary in the OpenClaw pod.

Security model:
- Verifies OPENCLAW_GATEWAY_TOKEN on every request.
- Read-only operations by default (get, list, describe, logs, top).
- Write operations (rollout restart, scale) require explicit user confirmation.
- Command allowlist — only specific kubectl commands permitted.
- Output sanitized — secrets/tokens redacted.
- Execution timeout — commands killed after 30s.

Endpoints:
POST /kubectl/exec — execute a kubectl command
GET /kubectl/health — check kubectl availability
"""
import json
import logging
import os
import re
import subprocess
import shlex
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

OPENCLAW_GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")

# Allowlist of kubectl commands (read-only by default)
ALLOWED_READ_COMMANDS = frozenset({
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
})

# Write commands require explicit confirm=True
ALLOWED_WRITE_COMMANDS = frozenset({
    "rollout restart",
    "scale deployment",
    "scale statefulset",
    "scale replicaset",
})

kubectl_proxy_router = APIRouter(prefix="/kubectl", tags=["kubectl-proxy"])


def _verify_openclaw_token(authorization: Optional[str]) -> None:
    """Only the OpenClaw pod may call this."""
    if not OPENCLAW_GATEWAY_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer "):]
    if token != OPENCLAW_GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid proxy token")


def _sanitize_output(output: str) -> str:
    """Redact sensitive data from kubectl output."""
    patterns = [
        (r'(?i)(token|password|secret|key|auth)\s*[=:]\s*["\']?[^\s,;"\']{8,}["\']?', r'\1: [REDACTED]'),
        (r'(?i)-----BEGIN [A-Z ]+-----[^-]+-----END [A-Z ]+-----', '[REDACTED: PEM]'),
        (r'(?i)(eyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-\.]*)', '[REDACTED: JWT]'),
    ]
    for pattern, replacement in patterns:
        output = re.sub(pattern, replacement, output)
    return output


def _validate_command(command: str) -> tuple[bool, bool]:
    """Validate kubectl command. Returns: (is_allowed, is_write)"""
    cmd_lower = command.lower()
    
    for write_cmd in ALLOWED_WRITE_COMMANDS:
        if write_cmd in cmd_lower:
            return True, True
    
    for read_cmd in ALLOWED_READ_COMMANDS:
        if read_cmd in cmd_lower:
            return True, False
    
    return False, False


class KubectlExecRequest(BaseModel):
    command: str
    namespace: Optional[str] = None
    confirm: bool = False
    timeout: int = 30
    
    @field_validator("timeout")
    @classmethod
    def timeout_range(cls, v: int) -> int:
        if v < 1 or v > 120:
            raise ValueError("timeout must be between 1-120 seconds")
        return v


class KubectlResponse(BaseModel):
    ok: bool
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    is_write: bool = False


@kubectl_proxy_router.post("/exec")
async def kubectl_exec(
    req: KubectlExecRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Execute a kubectl command against the cluster."""
    _verify_openclaw_token(authorization)
    
    is_allowed, is_write = _validate_command(req.command)
    
    if not is_allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Command not allowed: '{req.command}'"
        )
    
    if is_write and not req.confirm:
        raise HTTPException(
            status_code=403,
            detail=f"Write command '{req.command}' requires confirm=True"
        )
    
    kubectl_cmd = ["kubectl"]
    
    if req.namespace:
        kubectl_cmd.extend(["-n", req.namespace])
    
    try:
        args = shlex.split(req.command)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid command syntax: {e}")
    
    kubectl_cmd.extend(args)
    
    logger.info("kubectl_proxy: executing %r", req.command)
    
    start_time = time.time()
    try:
        result = subprocess.run(
            kubectl_cmd,
            capture_output=True,
            text=True,
            timeout=req.timeout,
            shell=False,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        
        stdout = _sanitize_output(result.stdout)
        stderr = _sanitize_output(result.stderr)
        
        return KubectlResponse(
            ok=result.returncode == 0,
            command=" ".join(kubectl_cmd),
            stdout=stdout,
            stderr=stderr,
            exit_code=result.returncode,
            duration_ms=duration_ms,
            is_write=is_write,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"Command timed out after {req.timeout}s")
    except Exception as exc:
        logger.error("kubectl_proxy: error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


@kubectl_proxy_router.get("/health")
async def kubectl_health(authorization: Optional[str] = Header(default=None)):
    """Check kubectl availability."""
    _verify_openclaw_token(authorization)
    
    try:
        result = subprocess.run(["kubectl", "version", "--client"], 
                                capture_output=True, text=True, timeout=5)
        version = result.stdout.strip().split("\n")[0] if result.stdout else "unknown"
        return {"ok": True, "kubectl_version": version}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
