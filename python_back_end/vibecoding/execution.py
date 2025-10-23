"""Vibecoding Code Execution

This module handles code execution in VibeCode IDE sessions, providing structured
output with timing information for commands and file execution.
"""

import time
import logging
import os
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends

from .containers import container_manager, ExecutionResult
from auth_utils import get_current_user

# Import validated model
from .validators import ExecuteCodeRequest as ValidatedExecuteCodeRequest

# Import command security
from .command_security import execute_safe_command, build_safe_command, sanitize_arguments

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["vibecode-execution"])


# Language detection mapping
LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "node",
    ".sh": "bash",
    ".bash": "bash",
    ".ts": "node",
    ".mjs": "node",
}

LANGUAGE_COMMANDS = {
    "python": "python",
    "node": "node",
    "bash": "bash",
}


async def execute_code(
    session_id: str,
    cmd: Optional[str] = None,
    file: Optional[str] = None,
    lang: Optional[str] = None,
    args: Optional[List[str]] = None
) -> ExecutionResult:
    """Execute code or command in a VibeCode session container
    
    This function supports two modes:
    1. Direct command execution (cmd parameter)
    2. File execution with language detection (file + lang parameters)
    
    Args:
        session_id: Unique session identifier
        cmd: Direct command to execute (e.g., "echo hello")
        file: Path to file to execute (relative to /workspace)
        lang: Language for file execution (python, node, bash)
        args: Additional arguments to pass to the command
        
    Returns:
        ExecutionResult with stdout, stderr, exit_code, and timing info
        
    Raises:
        ValueError: If neither cmd nor file is provided
        
    Example:
        # Direct command
        result = await execute_code(session_id="abc123", cmd="echo 'hello world'")
        
        # File execution
        result = await execute_code(
            session_id="abc123",
            file="test.py",
            lang="python"
        )
    """
    logger.info(f"🚀 Executing code in session: {session_id}")
    
    # Build the command to execute
    command = None
    
    if file:
        # File execution mode
        logger.info(f"📄 File execution mode: {file}")
        
        # Check for non-executable file types
        _, ext = os.path.splitext(file)
        ext = ext.lower()
        
        if ext == ".json":
            return ExecutionResult(
                command=f"# Cannot execute {file}",
                stdout="",
                stderr="JSON is not executable. Use Format/Validate actions instead.",
                exit_code=126,  # Command cannot execute
                execution_time_ms=0
            )
        
        # Check for Node.js requirements for JS/TS files
        if ext in [".js", ".mjs", ".ts"]:
            # Get capabilities from container
            try:
                runner_container = await container_manager.get_runner_container(session_id)
                if not runner_container:
                    runner_container = await container_manager.get_container(session_id)
                
                if runner_container:
                    # Quick probe for Node.js
                    import docker
                    client = docker.from_env()
                    try:
                        exec_id = client.api.exec_create(
                            container=runner_container.id, 
                            cmd=["/bin/sh", "-lc", "command -v node"]
                        )["Id"]
                        client.api.exec_start(exec_id, stream=False)
                        insp = client.api.exec_inspect(exec_id)
                        has_node = insp.get("ExitCode", 1) == 0
                    except:
                        has_node = False
                    
                    if not has_node:
                        return ExecutionResult(
                            command=f"# Cannot execute {file}",
                            stdout="",
                            stderr="Node runtime not available in runner. Ask admin to enable Node.",
                            exit_code=127,  # Command not found
                            execution_time_ms=0
                        )
            except Exception as e:
                logger.warning(f"Failed to check Node.js availability: {e}")
                return ExecutionResult(
                    command=f"# Cannot execute {file}",
                    stdout="",
                    stderr="Unable to verify Node.js runtime. Please try again.",
                    exit_code=127,
                    execution_time_ms=0
                )
        
        # Detect language if not provided
        if not lang:
            lang = _detect_language(file)
            logger.info(f"🔍 Detected language: {lang}")
        
        # Build command based on language
        command = _build_file_command(file, lang, args)
        
    elif cmd:
        # Direct command mode
        logger.info(f"💻 Direct command mode: {cmd}")
        
        # Validate command for security
        try:
            # Allow pipes for advanced users, but block other dangerous patterns
            command = execute_safe_command(cmd, strict=False, allow_pipes=True)
            logger.info(f"✅ Command validated and sanitized")
        except ValueError as e:
            logger.warning(f"🚫 Command rejected: {e}")
            raise ValueError(f"Unsafe command: {e}")
        
    else:
        raise ValueError("Either 'cmd' or 'file' parameter is required")
    
    logger.info(f"⚙️ Executing command: {command}")
    
    # Execute command in container with timing
    start_time = time.time()
    started_at = int(start_time * 1000)
    
    try:
        # Get runner container for execution (preferred), fallback to IDE container
        container = await container_manager.get_runner_container(session_id)
        if not container:
            container = await container_manager.get_container(session_id)
        
        if not container:
            # Return error result
            return ExecutionResult(
                command=command,
                stdout="",
                stderr="Error: Container not found. Please ensure the session is running.",
                exit_code=-1,
                execution_time_ms=0
            )
        
        # Execute with demux to separate stdout/stderr
        result = container.exec_run(
            command,
            workdir="/workspace",
            demux=True
        )
        
        end_time = time.time()
        finished_at = int(end_time * 1000)
        execution_time_ms = int((end_time - start_time) * 1000)
        
        # Decode output
        stdout_bytes, stderr_bytes = result.output
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        
        logger.info(f"✅ Execution completed in {execution_time_ms}ms with exit code {result.exit_code}")
        
        # Create execution result with proper timing
        exec_result = ExecutionResult(
            command=command,
            stdout=stdout,
            stderr=stderr,
            exit_code=result.exit_code,
            execution_time_ms=execution_time_ms
        )
        
        # Override timing fields to match actual execution
        exec_result.started_at = started_at
        exec_result.finished_at = finished_at
        
        return exec_result
        
    except Exception as e:
        end_time = time.time()
        finished_at = int(end_time * 1000)
        execution_time_ms = int((end_time - start_time) * 1000)
        
        logger.error(f"❌ Execution failed: {e}")
        
        # Return error result
        exec_result = ExecutionResult(
            command=command,
            stdout="",
            stderr=f"Error: {str(e)}",
            exit_code=-1,
            execution_time_ms=execution_time_ms
        )
        exec_result.started_at = started_at
        exec_result.finished_at = finished_at
        
        return exec_result


def _detect_language(file: str) -> str:
    """Detect programming language from file extension
    
    Args:
        file: Filename or path
        
    Returns:
        Language identifier (python, node, bash) or empty string
    """
    _, ext = os.path.splitext(file)
    ext = ext.lower()
    
    return LANGUAGE_EXTENSIONS.get(ext, "")


def _build_file_command(file: str, lang: str, args: Optional[List[str]] = None) -> str:
    """Build execution command for a file
    
    Args:
        file: File path (relative to /workspace)
        lang: Language identifier
        args: Additional arguments
        
    Returns:
        Complete command string (sanitized for security)
    """
    # Ensure file path is relative to /workspace
    if not file.startswith("/workspace/"):
        if file.startswith("/"):
            file = file[1:]
        file = f"/workspace/{file}"
    
    # Build runtime fallback wrapper for common languages
    file_quoted = file
    arg_str = ""
    if args:
        # Sanitize arguments to prevent injection
        safe_args = sanitize_arguments(args)
        arg_str = " " + " ".join(safe_args)

    if lang == "python":
        # Prefer python, fallback to python3
        return (
            "sh -lc \""
            "if command -v python >/dev/null 2>&1; then python '" + file_quoted + "'" + arg_str + "; "
            "elif command -v python3 >/dev/null 2>&1; then python3 '" + file_quoted + "'" + arg_str + "; "
            "else echo 'python runtime not found (install python or python3)'; exit 127; fi"
            "\""
        )

    if lang == "node":
        # Prefer node, fallback to nodejs
        return (
            "sh -lc \""
            "if command -v node >/dev/null 2>&1; then node '" + file_quoted + "'" + arg_str + "; "
            "elif command -v nodejs >/dev/null 2>&1; then nodejs '" + file_quoted + "'" + arg_str + "; "
            "else echo 'node runtime not found (install node)'; exit 127; fi"
            "\""
        )

    if lang == "bash":
        # Prefer bash, fallback to sh
        return (
            "sh -lc \""
            "if command -v bash >/dev/null 2>&1; then bash '" + file_quoted + "'" + arg_str + "; "
            "elif command -v sh >/dev/null 2>&1; then sh '" + file_quoted + "'" + arg_str + "; "
            "else echo 'shell not found (install bash)'; exit 127; fi"
            "\""
        )

    # Fallback: execute file directly (already validated)
    return file_quoted + arg_str


# Pydantic models for API

# Use validated model from validators module
ExecuteCodeRequest = ValidatedExecuteCodeRequest


class ExecutionResultResponse(BaseModel):
    """Response model for execution results"""
    command: str
    stdout: str
    stderr: str
    exit_code: int
    started_at: int
    finished_at: int
    execution_time_ms: int


# API Endpoints

@router.post("/api/vibecode/exec")
async def execute_code_endpoint(
    req: ExecuteCodeRequest,
    current_user: dict = Depends(get_current_user)
):
    """Execute code or command in a VibeCode session container
    
    This endpoint supports two execution modes:
    1. Direct command execution using the 'cmd' parameter
    2. File execution using 'file' and optionally 'lang' parameters
    
    The endpoint will:
    - Execute the command/file in the session's container
    - Capture stdout and stderr separately
    - Record execution timing (started_at, finished_at, execution_time_ms)
    - Return structured results with exit code
    
    Examples:
        Direct command:
        {
            "session_id": "abc123",
            "cmd": "echo 'hello world'"
        }
        
        File execution:
        {
            "session_id": "abc123",
            "file": "test.py",
            "lang": "python"
        }
        
        File with auto-detection:
        {
            "session_id": "abc123",
            "file": "script.js"
        }
    """
    logger.info(f"🚀 Execution request from user {current_user['id']} for session {req.session_id}")
    
    # Verify container exists and user has access
    # Prefer runner container
    container = await container_manager.get_runner_container(req.session_id)
    if not container:
        container = await container_manager.get_container(req.session_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")
    
    # Verify user owns this session
    user_id_label = container.labels.get("user_id")
    if user_id_label and str(current_user["id"]) != user_id_label:
        raise HTTPException(status_code=403, detail="Unauthorized: You don't own this session")
    
    # Verify container is running
    container.reload()
    if container.status != "running":
        raise HTTPException(
            status_code=400, 
            detail=f"Container is not running (status: {container.status})"
        )
    
    # Execute the code
    try:
        result = await execute_code(
            session_id=req.session_id,
            cmd=req.cmd,
            file=req.file,
            lang=req.lang,
            args=req.args
        )
        
        # Convert to response model
        return ExecutionResultResponse(
            command=result.command,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            started_at=result.started_at,
            finished_at=result.finished_at,
            execution_time_ms=result.execution_time_ms
        )
        
    except ValueError as e:
        # Return structured error without 500
        return ExecutionResultResponse(
            command=req.cmd or (req.file or ''),
            stdout="",
            stderr=str(e),
            exit_code=127,
            started_at=int(time.time()*1000),
            finished_at=int(time.time()*1000),
            execution_time_ms=0
        )
    except Exception as e:
        logger.error(f"❌ Execution error: {e}")
        return ExecutionResultResponse(
            command=req.cmd or (req.file or ''),
            stdout="",
            stderr=f"Execution failed: {str(e)}",
            exit_code=127,
            started_at=int(time.time()*1000),
            finished_at=int(time.time()*1000),
            execution_time_ms=0
        )
