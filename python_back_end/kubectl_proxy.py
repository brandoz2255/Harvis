"""
Kubectl proxy endpoint for Discord kubectl access.
Provides safe, filtered kubectl command execution.
"""
import subprocess
import re
import json
import os
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

router = APIRouter(
    prefix="/kubectl",
    tags=["kubectl"],
)

class KubectlRequest(BaseModel):
    command: str
    namespace: Optional[str] = None
    args: Optional[List[str]] = []

class KubectlResponse(BaseModel):
    success: bool
    output: str
    summary: Optional[str] = None

# Allowed read-only kubectl commands
ALLOWED_COMMANDS = {
    "get": ["pods", "services", "deployments", "nodes", "events", "jobs", "cronjobs", "replicasets", "statefulsets", "daemonsets", "endpoints", "namespaces"],
    "describe": ["pod", "service", "deployment", "node", "job", "cronjob"],
    "logs": [],
    "top": ["pods", "nodes"],
    "rollout": ["status"],
}

# Redacted patterns (secrets)
REDACT_PATTERNS = [
    r'(token|secret|password|key|cert|private|auth)[\s]*[=\:][\s]*[^\s\n]{4,}',
    r'( eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]* )',  # JWT
    r'([a-f0-9]{32,})',  # Hex secrets
]

def redact_secrets(text: str) -> str:
    """Redact sensitive information from output."""
    for pattern in REDACT_PATTERNS:
        text = re.sub(pattern, '[REDACTED]', text, flags=re.IGNORECASE)
    return text

def sanitize_command(command: str, args: List[str]) -> List[str]:
    """Validate and sanitize kubectl command."""
    cmd_parts = [command] + args
    
    # Check if command is allowed
    if command not in ALLOWED_COMMANDS:
        raise HTTPException(status_code=403, detail=f"Command '{command}' not allowed")
    
    # Build kubectl command
    kubectl_args = ["kubectl", command]
    
    # Validate resource type for get/describe
    if command in ["get", "describe"] and args:
        resource = args[0] if args[0] != "-n" else args[2] if len(args) > 2 else ""
        if resource and resource not in ALLOWED_COMMANDS.get(command, []):
            raise HTTPException(status_code=403, detail=f"Resource '{resource}' not allowed")
    
    kubectl_args.extend(args)
    
    return kubectl_args

def summarize_output(command: str, output: str) -> str:
    """Summarize kubectl output for Discord."""
    lines = output.strip().split('\n')
    
    if len(lines) > 40:
        # Summarize
        not_running = [line for line in lines if 'Running' not in line and 'Completed' not in line]
        errors = [line for line in lines if 'Error' in line or 'Crash' in line]
        
        summary = f"Showing {len(lines)} items. "
        if not_running:
            summary += f"{len(not_running)} not in Running state. "
        if errors:
            summary += f"{len(errors)} errors. "
        return summary + "\n\nFirst 20 lines:\n" + '\n'.join(lines[:20])
    
    return output

@router.post("/exec", response_model=KubectlResponse)
async def exec_kubectl(request: KubectlRequest):
    """Execute a safe kubectl command."""
    try:
        # Build command
        cmd = sanitize_command(request.command, request.args)
        
        # Add namespace if specified
        if request.namespace and "-n" not in request.args:
            cmd.extend(["-n", request.namespace])
        
        # Execute kubectl
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/tmp"
        )
        
        # Combine stdout/stderr
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        
        # Redact secrets
        output = redact_secrets(output)
        
        # Generate summary for long output
        summary = None
        if len(output.split('\n')) > 40:
            summary = summarize_output(request.command, output)
        
        return KubectlResponse(
            success=result.returncode == 0,
            output=output,
            summary=summary
        )
        
    except subprocess.TimeoutExpired:
        return KubectlResponse(
            success=False,
            output="Command timed out after 30 seconds",
            summary=None
        )
    except Exception as e:
        return KubectlResponse(
            success=False,
            output=f"Error: {str(e)}",
            summary=None
        )

@router.get("/health")
async def kubectl_health():
    """Check if kubectl is available."""
    try:
        result = subprocess.run(
            ["kubectl", "version", "--client"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return {
            "available": result.returncode == 0,
            "version": result.stdout.strip() if result.stdout else "unknown"
        }
    except Exception as e:
        return {
            "available": False,
            "error": str(e)
        }
