"""Vibe Coding Execution API Routes with Docker SDK"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, Optional, List
import logging
import os
import tempfile
import uuid
import json
from datetime import datetime
from pydantic import BaseModel
import asyncio
import docker
from docker.models.containers import Container
from docker.errors import DockerException, ContainerError

# Import auth dependencies
from auth_utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibe", tags=["vibe-execution"])

# Initialize Docker client
try:
    docker_client = docker.from_env()
    DOCKER_AVAILABLE = True
    logger.info("Docker client initialized successfully")
except DockerException as e:
    docker_client = None
    DOCKER_AVAILABLE = False
    logger.warning(f"Docker not available: {e}")

# Pydantic models
class CodeExecutionRequest(BaseModel):
    session_id: str
    code: str
    language: str = "python"
    filename: Optional[str] = None
    environment: Optional[str] = "python:3.11-slim"  # Docker image
    timeout: Optional[int] = 30  # seconds
    working_directory: Optional[str] = "/workspace"
    dependencies: Optional[List[str]] = None  # pip packages, etc.

class CodeExecutionResponse(BaseModel):
    execution_id: str
    session_id: str
    status: str  # running, completed, failed, timeout
    output: str
    error: Optional[str] = None
    exit_code: Optional[int] = None
    execution_time: Optional[float] = None
    container_id: Optional[str] = None
    created_at: datetime

class ExecutionStatusResponse(BaseModel):
    execution_id: str
    status: str
    is_running: bool
    container_info: Optional[Dict[str, Any]] = None

# In-memory storage for executions
executions_storage: Dict[str, Dict[str, Any]] = {}

# Language to Docker image mapping
LANGUAGE_IMAGES = {
    "python": "python:3.11-slim",
    "javascript": "node:18-alpine", 
    "typescript": "node:18-alpine",
    "java": "openjdk:11-alpine",
    "go": "golang:1.21-alpine",
    "rust": "rust:1.75-slim",
    "cpp": "gcc:latest",
    "c": "gcc:latest",
    "ruby": "ruby:3.2-alpine",
    "php": "php:8.2-alpine",
    "bash": "ubuntu:22.04",
    "shell": "ubuntu:22.04",
}

# Language file extensions
LANGUAGE_EXTENSIONS = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts", 
    "java": ".java",
    "go": ".go",
    "rust": ".rs",
    "cpp": ".cpp",
    "c": ".c",
    "ruby": ".rb",
    "php": ".php",
    "bash": ".sh",
    "shell": ".sh",
}

# Language execution commands
LANGUAGE_COMMANDS = {
    "python": ["python", "{filename}"],
    "javascript": ["node", "{filename}"],
    "typescript": ["npx", "ts-node", "{filename}"],
    "java": ["sh", "-c", "javac {filename} && java {classname}"],
    "go": ["go", "run", "{filename}"],
    "rust": ["sh", "-c", "rustc {filename} -o /tmp/program && /tmp/program"],
    "cpp": ["sh", "-c", "g++ {filename} -o /tmp/program && /tmp/program"],
    "c": ["sh", "-c", "gcc {filename} -o /tmp/program && /tmp/program"], 
    "ruby": ["ruby", "{filename}"],
    "php": ["php", "{filename}"],
    "bash": ["bash", "{filename}"],
    "shell": ["sh", "{filename}"],
}

def get_docker_image(language: str, custom_environment: Optional[str] = None) -> str:
    """Get the appropriate Docker image for a language"""
    if custom_environment:
        return custom_environment
    return LANGUAGE_IMAGES.get(language.lower(), "ubuntu:22.04")

def get_filename(language: str, custom_filename: Optional[str] = None) -> str:
    """Get the appropriate filename for a language"""
    if custom_filename:
        return custom_filename
    
    extension = LANGUAGE_EXTENSIONS.get(language.lower(), ".txt")
    return f"main{extension}"

def get_execution_command(language: str, filename: str) -> List[str]:
    """Get the execution command for a language"""
    command_template = LANGUAGE_COMMANDS.get(language.lower(), ["cat", "{filename}"])
    
    # Special handling for Java classname
    classname = filename.replace(".java", "") if filename.endswith(".java") else "Main"
    
    # Format command with filename and classname
    return [cmd.format(filename=filename, classname=classname) for cmd in command_template]

async def execute_code_in_container(
    code: str,
    language: str,
    filename: str,
    docker_image: str,
    working_dir: str = "/workspace",
    timeout: int = 30,
    dependencies: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Execute code in a Docker container"""
    
    if not DOCKER_AVAILABLE:
        return {
            "status": "failed",
            "output": "",
            "error": "Docker not available on this system",
            "exit_code": -1,
            "execution_time": 0.0
        }
    
    container = None
    start_time = datetime.now()
    
    try:
        # Create temporary directory for code
        with tempfile.TemporaryDirectory() as temp_dir:
            # Write code to file
            code_file_path = os.path.join(temp_dir, filename)
            with open(code_file_path, 'w', encoding='utf-8') as f:
                f.write(code)
            
            # Create setup script for dependencies
            setup_script = ""
            if dependencies and language.lower() == "python":
                pip_packages = " ".join(dependencies)
                setup_script = f"pip install {pip_packages} && "
            elif dependencies and language.lower() in ["javascript", "typescript"]:
                npm_packages = " ".join(dependencies)
                setup_script = f"npm install {npm_packages} && "
            
            # Get execution command
            exec_command = get_execution_command(language, filename)
            full_command = f"{setup_script}" + " ".join(exec_command)
            
            # Container configuration
            container_config = {
                "image": docker_image,
                "command": ["sh", "-c", full_command],
                "volumes": {temp_dir: {"bind": working_dir, "mode": "rw"}},
                "working_dir": working_dir,
                "network_mode": "none",  # No network access for security
                "mem_limit": "512m",     # 512MB memory limit
                "cpu_count": 1,          # 1 CPU core
                "detach": True,
                "remove": False,         # Don't auto-remove for debugging
                "stdout": True,
                "stderr": True
            }
            
            # Pull image if not exists
            try:
                docker_client.images.get(docker_image)
            except docker.errors.ImageNotFound:
                logger.info(f"Pulling Docker image: {docker_image}")
                docker_client.images.pull(docker_image)
            
            # Create and start container
            container = docker_client.containers.run(**container_config)
            container_id = container.id
            
            logger.info(f"Started container {container_id[:12]} for {language} execution")
            
            # Wait for completion with timeout
            try:
                result = container.wait(timeout=timeout)
                exit_code = result["StatusCode"]
            except Exception as e:
                logger.warning(f"Container execution timeout or error: {e}")
                container.kill()
                exit_code = -1
            
            # Get output and logs
            try:
                output = container.logs(stdout=True, stderr=False).decode('utf-8', errors='ignore')
                error = container.logs(stdout=False, stderr=True).decode('utf-8', errors='ignore')
            except Exception as e:
                logger.error(f"Error getting container logs: {e}")
                output = ""
                error = f"Error retrieving logs: {str(e)}"
            
            # Calculate execution time
            execution_time = (datetime.now() - start_time).total_seconds()
            
            # Clean up container
            try:
                container.remove(force=True)
            except Exception as e:
                logger.warning(f"Error removing container: {e}")
            
            status = "completed" if exit_code == 0 else "failed"
            
            return {
                "status": status,
                "output": output.strip(),
                "error": error.strip() if error.strip() else None,
                "exit_code": exit_code,
                "execution_time": execution_time,
                "container_id": container_id
            }
            
    except DockerException as e:
        logger.error(f"Docker error during code execution: {e}")
        return {
            "status": "failed", 
            "output": "",
            "error": f"Docker error: {str(e)}",
            "exit_code": -1,
            "execution_time": (datetime.now() - start_time).total_seconds()
        }
    except Exception as e:
        logger.error(f"Unexpected error during code execution: {e}")
        return {
            "status": "failed",
            "output": "",
            "error": f"Execution error: {str(e)}",
            "exit_code": -1,
            "execution_time": (datetime.now() - start_time).total_seconds()
        }
    finally:
        # Ensure cleanup
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass

async def execute_code_fallback(
    code: str,
    language: str,
    filename: str,
    timeout: int = 30
) -> Dict[str, Any]:
    """Fallback execution without Docker - runs code directly on host"""
    import subprocess
    import sys
    
    start_time = datetime.now()
    
    try:
        # Create temporary directory for code
        with tempfile.TemporaryDirectory() as temp_dir:
            # Write code to file
            code_file_path = os.path.join(temp_dir, filename)
            with open(code_file_path, 'w', encoding='utf-8') as f:
                f.write(code)
            
            # Check for non-executable file types
            non_executable_languages = ["json", "yaml", "yml", "xml", "html", "css", "md", "txt"]
            if language.lower() in non_executable_languages:
                return {
                    "status": "completed",
                    "output": f"File content displayed (not executable):\n\n{code}",
                    "error": None,
                    "exit_code": 0,
                    "execution_time": (datetime.now() - start_time).total_seconds()
                }
            
            # Determine execution command based on language
            lang = language.lower()
            
            if lang == "python":
                cmd = [sys.executable, code_file_path]
            elif lang in ["javascript", "js"]:
                cmd = ["node", code_file_path]
            elif lang in ["typescript", "ts"]:
                # Try ts-node first, fallback to tsc + node
                try:
                    subprocess.run(["ts-node", "--version"], capture_output=True, check=True)
                    cmd = ["ts-node", code_file_path]
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Fallback: compile with tsc then run with node
                    js_file = code_file_path.replace('.ts', '.js')
                    compile_result = subprocess.run(
                        ["tsc", code_file_path, "--outFile", js_file],
                        capture_output=True, text=True
                    )
                    if compile_result.returncode != 0:
                        return {
                            "status": "failed",
                            "output": "",
                            "error": f"TypeScript compilation failed: {compile_result.stderr}",
                            "exit_code": compile_result.returncode,
                            "execution_time": (datetime.now() - start_time).total_seconds()
                        }
                    cmd = ["node", js_file]
            elif lang == "java":
                # Compile and run Java
                class_name = filename.replace('.java', '')
                compile_result = subprocess.run(
                    ["javac", code_file_path],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True
                )
                if compile_result.returncode != 0:
                    return {
                        "status": "failed",
                        "output": "",
                        "error": f"Java compilation failed: {compile_result.stderr}",
                        "exit_code": compile_result.returncode,
                        "execution_time": (datetime.now() - start_time).total_seconds()
                    }
                cmd = ["java", class_name]
            elif lang in ["cpp", "c++"]:
                # Compile and run C++
                exe_file = os.path.join(temp_dir, "program")
                compile_result = subprocess.run(
                    ["g++", code_file_path, "-o", exe_file],
                    capture_output=True,
                    text=True
                )
                if compile_result.returncode != 0:
                    return {
                        "status": "failed",
                        "output": "",
                        "error": f"C++ compilation failed: {compile_result.stderr}",
                        "exit_code": compile_result.returncode,
                        "execution_time": (datetime.now() - start_time).total_seconds()
                    }
                cmd = [exe_file]
            elif lang == "c":
                # Compile and run C
                exe_file = os.path.join(temp_dir, "program")
                compile_result = subprocess.run(
                    ["gcc", code_file_path, "-o", exe_file],
                    capture_output=True,
                    text=True
                )
                if compile_result.returncode != 0:
                    return {
                        "status": "failed",
                        "output": "",
                        "error": f"C compilation failed: {compile_result.stderr}",
                        "exit_code": compile_result.returncode,
                        "execution_time": (datetime.now() - start_time).total_seconds()
                    }
                cmd = [exe_file]
            elif lang == "go":
                cmd = ["go", "run", code_file_path]
            elif lang == "rust":
                # Compile and run Rust
                exe_file = os.path.join(temp_dir, "program")
                compile_result = subprocess.run(
                    ["rustc", code_file_path, "-o", exe_file],
                    capture_output=True,
                    text=True
                )
                if compile_result.returncode != 0:
                    return {
                        "status": "failed",
                        "output": "",
                        "error": f"Rust compilation failed: {compile_result.stderr}",
                        "exit_code": compile_result.returncode,
                        "execution_time": (datetime.now() - start_time).total_seconds()
                    }
                cmd = [exe_file]
            elif lang == "ruby":
                cmd = ["ruby", code_file_path]
            elif lang == "php":
                cmd = ["php", code_file_path]
            elif lang in ["bash", "shell", "sh"]:
                cmd = ["bash", code_file_path]
            elif lang == "perl":
                cmd = ["perl", code_file_path]
            elif lang == "lua":
                cmd = ["lua", code_file_path]
            elif lang in ["r", "rscript"]:
                cmd = ["Rscript", code_file_path]
            elif lang == "scala":
                cmd = ["scala", code_file_path]
            elif lang == "kotlin":
                # Compile and run Kotlin
                jar_file = os.path.join(temp_dir, "program.jar")
                compile_result = subprocess.run(
                    ["kotlinc", code_file_path, "-include-runtime", "-d", jar_file],
                    capture_output=True,
                    text=True
                )
                if compile_result.returncode != 0:
                    return {
                        "status": "failed",
                        "output": "",
                        "error": f"Kotlin compilation failed: {compile_result.stderr}",
                        "exit_code": compile_result.returncode,
                        "execution_time": (datetime.now() - start_time).total_seconds()
                    }
                cmd = ["java", "-jar", jar_file]
            elif lang in ["powershell", "ps1"]:
                cmd = ["powershell", "-File", code_file_path]
            elif lang == "dart":
                cmd = ["dart", code_file_path]
            elif lang == "swift":
                cmd = ["swift", code_file_path]
            else:
                return {
                    "status": "failed",
                    "output": "",
                    "error": f"Language {language} not supported in fallback mode. Supported languages: python, javascript, typescript, java, cpp, c, go, rust, ruby, php, bash, shell, perl, lua, r, scala, kotlin, powershell, dart, swift",
                    "exit_code": -1,
                    "execution_time": 0.0
                }
            
            # Execute the code
            try:
                result = subprocess.run(
                    cmd,
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False  # Don't raise exception on non-zero exit
                )
                
                output = result.stdout
                error = result.stderr
                exit_code = result.returncode
                
                execution_time = (datetime.now() - start_time).total_seconds()
                status = "completed" if exit_code == 0 else "failed"
                
                return {
                    "status": status,
                    "output": output.strip(),
                    "error": error.strip() if error.strip() else None,
                    "exit_code": exit_code,
                    "execution_time": execution_time
                }
                
            except subprocess.TimeoutExpired:
                return {
                    "status": "timeout",
                    "output": "",
                    "error": f"Code execution timed out after {timeout} seconds",
                    "exit_code": -1,
                    "execution_time": timeout
                }
            except FileNotFoundError as e:
                return {
                    "status": "failed",
                    "output": "",
                    "error": f"Interpreter not found: {str(e)}. Make sure {language} is installed.",
                    "exit_code": -1,
                    "execution_time": (datetime.now() - start_time).total_seconds()
                }
                
    except Exception as e:
        logger.error(f"Fallback execution error: {e}")
        return {
            "status": "failed",
            "output": "",
            "error": f"Execution error: {str(e)}",
            "exit_code": -1,
            "execution_time": (datetime.now() - start_time).total_seconds()
        }

@router.post("/execute", response_model=CodeExecutionResponse)
async def execute_code(
    request: CodeExecutionRequest,
    user: Dict = Depends(get_current_user)
):
    """Execute code in a secure Docker container"""
    try:
        execution_id = str(uuid.uuid4())
        created_at = datetime.now()
        
        # Validate inputs
        if not request.code.strip():
            raise HTTPException(status_code=400, detail="Code cannot be empty")
        
        if request.language.lower() not in LANGUAGE_IMAGES:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported language: {request.language}. Supported: {list(LANGUAGE_IMAGES.keys())}"
            )
        
        # Get execution parameters
        docker_image = get_docker_image(request.language, request.environment)
        filename = get_filename(request.language, request.filename)
        
        logger.info(f"Executing {request.language} code in container for user {user.get('id')}")
        logger.info(f"Using image: {docker_image}, filename: {filename}")
        
        # Store execution info
        execution_info = {
            "execution_id": execution_id,
            "session_id": request.session_id,
            "user_id": str(user.get("id")),
            "status": "running",
            "language": request.language,
            "filename": filename,
            "docker_image": docker_image,
            "created_at": created_at,
            "code": request.code[:1000]  # Store first 1000 chars for debugging
        }
        executions_storage[execution_id] = execution_info
        
        # Execute code - use fallback if Docker is not available
        if DOCKER_AVAILABLE:
            result = await execute_code_in_container(
                code=request.code,
                language=request.language,
                filename=filename,
                docker_image=docker_image,
                working_dir=request.working_directory or "/workspace",
                timeout=request.timeout or 30,
                dependencies=request.dependencies
            )
        else:
            logger.info(f"Using fallback execution for {request.language} (Docker not available)")
            result = await execute_code_fallback(
                code=request.code,
                language=request.language,
                filename=filename,
                timeout=request.timeout or 30
            )
        
        # Update execution info with results
        execution_info.update({
            "status": result["status"],
            "output": result["output"],
            "error": result["error"],
            "exit_code": result["exit_code"],
            "execution_time": result["execution_time"],
            "container_id": result.get("container_id"),
            "completed_at": datetime.now()
        })
        
        logger.info(f"Code execution {execution_id} completed with status: {result['status']}")
        
        return CodeExecutionResponse(
            execution_id=execution_id,
            session_id=request.session_id,
            status=result["status"],
            output=result["output"],
            error=result["error"],
            exit_code=result["exit_code"],
            execution_time=result["execution_time"],
            container_id=result.get("container_id"),
            created_at=created_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing code: {e}")
        raise HTTPException(status_code=500, detail=f"Code execution failed: {str(e)}")

@router.get("/execute/{execution_id}/status", response_model=ExecutionStatusResponse)
async def get_execution_status(
    execution_id: str,
    user: Dict = Depends(get_current_user)
):
    """Get the status of a code execution"""
    try:
        execution = executions_storage.get(execution_id)
        
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")
        
        # Check if user owns this execution
        if execution.get("user_id") != str(user.get("id")):
            raise HTTPException(status_code=403, detail="Access denied")
        
        is_running = execution.get("status") == "running"
        container_info = None
        
        # If we have a container ID and Docker is available, get container info
        if DOCKER_AVAILABLE and execution.get("container_id"):
            try:
                container = docker_client.containers.get(execution["container_id"])
                container_info = {
                    "id": container.id,
                    "status": container.status,
                    "image": container.image.tags[0] if container.image.tags else "unknown"
                }
            except docker.errors.NotFound:
                # Container no longer exists
                if is_running:
                    execution["status"] = "failed"
                    execution["error"] = "Container no longer exists"
                    is_running = False
            except Exception as e:
                logger.warning(f"Error getting container info: {e}")
        
        return ExecutionStatusResponse(
            execution_id=execution_id,
            status=execution.get("status", "unknown"),
            is_running=is_running,
            container_info=container_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting execution status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get execution status")

@router.get("/execute/history")
async def get_execution_history(
    user: Dict = Depends(get_current_user),
    session_id: Optional[str] = None,
    limit: int = 50
):
    """Get execution history for the user"""
    try:
        user_executions = []
        
        for exec_id, execution in executions_storage.items():
            if execution.get("user_id") == str(user.get("id")):
                if session_id and execution.get("session_id") != session_id:
                    continue
                    
                # Remove code content for history (privacy/size)
                exec_copy = execution.copy()
                exec_copy.pop("code", None)
                user_executions.append(exec_copy)
        
        # Sort by creation time, most recent first
        user_executions.sort(
            key=lambda x: x.get("created_at", datetime.min), 
            reverse=True
        )
        
        # Limit results
        user_executions = user_executions[:limit]
        
        return {
            "executions": user_executions,
            "total": len(user_executions),
            "docker_available": DOCKER_AVAILABLE
        }
        
    except Exception as e:
        logger.error(f"Error getting execution history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get execution history")

@router.get("/docker/status")
async def get_docker_status(
    user: Dict = Depends(get_current_user)
):
    """Get Docker service status"""
    try:
        if not DOCKER_AVAILABLE:
            return {
                "available": False,
                "error": "Docker client not initialized"
            }
        
        # Test Docker connection
        try:
            info = docker_client.info()
            version = docker_client.version()
            
            return {
                "available": True,
                "version": version.get("Version", "unknown"),
                "api_version": version.get("ApiVersion", "unknown"),
                "containers": info.get("Containers", 0),
                "images": info.get("Images", 0),
                "server_version": info.get("ServerVersion", "unknown")
            }
        except Exception as e:
            return {
                "available": False,
                "error": str(e)
            }
            
    except Exception as e:
        logger.error(f"Error checking Docker status: {e}")
        return {
            "available": False,
            "error": str(e)
        }

@router.get("/languages")
async def get_supported_languages(
    user: Dict = Depends(get_current_user)
):
    """Get list of supported programming languages"""
    return {
        "languages": [
            {
                "name": lang,
                "display_name": lang.title(),
                "docker_image": image,
                "extension": LANGUAGE_EXTENSIONS.get(lang, ".txt"),
                "available": DOCKER_AVAILABLE
            }
            for lang, image in LANGUAGE_IMAGES.items()
        ],
        "docker_available": DOCKER_AVAILABLE
    }