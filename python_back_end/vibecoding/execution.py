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
    # Python
    ".py": "python",
    ".pyw": "python",
    ".python": "python",
    
    # Node.js
    ".js": "node",
    ".mjs": "node",
    ".cjs": "node",
    
    # TypeScript
    ".ts": "typescript",
    ".tsx": "typescript",
    
    # Shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    
    # C/C++
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c++": "cpp",
    ".hpp": "cpp",
    
    # Java
    ".java": "java",
    
    # Go
    ".go": "go",
    
    # Rust
    ".rs": "rust",
    
    # Ruby
    ".rb": "ruby",
    ".rbx": "ruby",
    
    # PHP
    ".php": "php",
    
    # Perl
    ".pl": "perl",
    ".pm": "perl",
    
    # Swift
    ".swift": "swift",
    
    # Kotlin
    ".kt": "kotlin",
    ".kts": "kotlin",
    
    # Scala
    ".scala": "scala",
    ".sc": "scala",
    
    # R
    ".r": "r",
    
    # Julia
    ".jl": "julia",
    
    # Lua
    ".lua": "lua",
    
    # Haskell
    ".hs": "haskell",
    ".lhs": "haskell",
}

LANGUAGE_COMMANDS = {
    "python": "python3",
    "node": "node",
    "typescript": "npx ts-node",
    "bash": "bash",
    "c": "gcc",
    "cpp": "g++",
    "java": "java",
    "go": "go",
    "rust": "rustc",
    "ruby": "ruby",
    "php": "php",
    "perl": "perl",
    "swift": "swift",
    "kotlin": "kotlinc",
    "scala": "scala",
    "r": "R",
    "julia": "julia",
    "lua": "lua",
    "haskell": "ghc",
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
        # Get container and execute
        container = await container_manager.get_container(session_id)
        if not container:
            # Return error result
            return ExecutionResult(
                command=command,
                stdout="",
                stderr="Error: Container not found",
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
    """Build execution command for a file with multi-language support
    
    Args:
        file: File path (relative to /workspace)
        lang: Language identifier
        args: Additional arguments
        
    Returns:
        Complete command string (sanitized for security)
    """
    # Ensure file path is absolute
    if not file.startswith("/workspace/"):
        if file.startswith("/"):
            file = file[1:]
        file = f"/workspace/{file}"
    
    file_quoted = file
    arg_str = ""
    if args:
        safe_args = sanitize_arguments(args)
        arg_str = " " + " ".join(safe_args)
    
    cmd_name = LANGUAGE_COMMANDS.get(lang, lang)
    
    # Runtime commands (direct execution)
    if lang == "python":
        return f"python3 '{file_quoted}'{arg_str}"
    
    elif lang == "node":
        return f"node '{file_quoted}'{arg_str}"
    
    elif lang == "bash":
        return f"bash '{file_quoted}'{arg_str}"
    
    elif lang == "typescript":
        return f"npx ts-node '{file_quoted}'{arg_str}"
    
    # Compiled languages (compile then run)
    elif lang == "c":
        # Compile to a.out, then run it
        return f"gcc '{file_quoted}' -o /tmp/a.out && /tmp/a.out{arg_str}"
    
    elif lang == "cpp":
        # Compile to a.out, then run it
        return f"g++ '{file_quoted}' -o /tmp/a.out && /tmp/a.out{arg_str}"
    
    elif lang == "java":
        # Compile and run Java
        # Extract class name from file path
        file_base = os.path.basename(file_quoted).replace('.java', '')
        return f"cd /workspace && javac '{file_quoted}' && java {file_base}{arg_str}"
    
    elif lang == "rust":
        # Compile and run Rust
        file_base = os.path.basename(file_quoted).replace('.rs', '')
        return f"rustc '{file_quoted}' -o /tmp/{file_base} && /tmp/{file_base}{arg_str}"
    
    elif lang == "go":
        # Go run compiles and runs
        return f"go run '{file_quoted}'{arg_str}"
    
    # Interpreted languages (direct run)
    elif lang in ["ruby", "perl", "php", "lua", "r", "julia", "haskell", "scala", "kotlin", "swift"]:
        return f"{cmd_name} '{file_quoted}'{arg_str}"
    
    # Fallback
    return f"{cmd_name} '{file_quoted}'{arg_str}"


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
