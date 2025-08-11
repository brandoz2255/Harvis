"""Vibecoding Development Container Management

This module manages Docker containers for vibecoding sessions, providing isolated
development environments with real terminal access and file system management.
"""

import docker
import os
import uuid
import logging
import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel
import asyncpg
from .db_session import get_session_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vibe-dev-containers"])

# Container configuration
DEV_CONTAINER_IMAGE = "python:3.10-slim"
CONTAINER_TIMEOUT = timedelta(hours=2)  # Auto-cleanup after 2 hours of inactivity
VOLUME_PREFIX = "vibecoding_"

class ContainerManager:
    """Manages Docker containers for vibecoding sessions."""
    
    def __init__(self):
        try:
            self.docker_client = docker.from_env()
            logger.info("✅ Docker client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Docker client: {e}")
            self.docker_client = None
        
        self.active_containers: Dict[str, Dict[str, Any]] = {}
        
    async def create_dev_container(self, session_id: str, user_id: str = None) -> Dict[str, Any]:
        """Create a new development container for a vibecoding session."""
        if not self.docker_client:
            raise HTTPException(status_code=503, detail="Docker not available")
        
        try:
            container_name = f"vibecoding_{session_id}"
            volume_name = f"{VOLUME_PREFIX}{session_id}"
            
            # Create volume for persistent storage
            try:
                volume = self.docker_client.volumes.create(name=volume_name)
                logger.info(f"📦 Created volume: {volume_name}")
            except docker.errors.APIError as e:
                if "already exists" in str(e):
                    volume = self.docker_client.volumes.get(volume_name)
                    logger.info(f"📦 Using existing volume: {volume_name}")
                else:
                    raise
            
            # Container configuration
            container_config = {
                "image": DEV_CONTAINER_IMAGE,
                "name": container_name,
                "detach": True,
                "tty": True,
                "stdin_open": True,
                "working_dir": "/workspace",
                "volumes": {
                    volume_name: {"bind": "/workspace", "mode": "rw"}
                },
                "environment": {
                    "PYTHONUNBUFFERED": "1",
                    "DEBIAN_FRONTEND": "noninteractive"
                },
                "network_mode": "bridge",
                "labels": {
                    "vibecoding.session_id": session_id,
                    "vibecoding.user_id": user_id or "anonymous",
                    "vibecoding.created": datetime.now().isoformat()
                }
            }
            
            # Create and start container
            container = self.docker_client.containers.run(**container_config)
            
            # Install common development tools
            setup_commands = [
                "apt-get update",
                "apt-get install -y git curl wget nano vim nodejs npm",
                "pip install --upgrade pip",
                "pip install requests fastapi uvicorn flask django pandas numpy matplotlib jupyter"
            ]
            
            for cmd in setup_commands:
                try:
                    result = container.exec_run(cmd)
                    if result.exit_code != 0:
                        logger.warning(f"Setup command failed: {cmd} - {result.output.decode()}")
                except Exception as e:
                    logger.warning(f"Failed to run setup command: {cmd} - {e}")
            
            # Store container info
            container_info = {
                "container_id": container.id,
                "container_name": container_name,
                "session_id": session_id,
                "user_id": user_id,
                "volume_name": volume_name,
                "created_at": datetime.now(),
                "last_activity": datetime.now(),
                "status": "running"
            }
            
            self.active_containers[session_id] = container_info
            
            # Update database with container info
            try:
                session_db = get_session_db()
                await session_db.update_container_status(session_id, container.id, "running")
            except Exception as e:
                logger.warning(f"Failed to update container status in database: {e}")
            
            logger.info(f"✅ Created dev container: {container_name} for session: {session_id}")
            
            return {
                "session_id": session_id,
                "container_id": container.id,
                "container_name": container_name,
                "status": "running",
                "workspace_path": "/workspace"
            }
            
        except Exception as e:
            logger.error(f"Failed to create dev container: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create container: {str(e)}")
    
    async def get_container(self, session_id: str) -> Optional[docker.models.containers.Container]:
        """Get container by session ID."""
        if not self.docker_client or session_id not in self.active_containers:
            return None
            
        try:
            container_info = self.active_containers[session_id]
            container = self.docker_client.containers.get(container_info["container_id"])
            
            # Update last activity
            container_info["last_activity"] = datetime.now()
            
            return container
        except docker.errors.NotFound:
            # Container was removed externally
            if session_id in self.active_containers:
                del self.active_containers[session_id]
            return None
        except Exception as e:
            logger.error(f"Error getting container: {e}")
            return None
    
    async def execute_command(self, session_id: str, command: str) -> Dict[str, Any]:
        """Execute command in container."""
        container = await self.get_container(session_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        
        try:
            import time
            start_time = time.time()
            
            result = container.exec_run(command, workdir="/workspace")
            
            execution_time_ms = int((time.time() - start_time) * 1000)
            output = result.output.decode("utf-8", errors="replace")
            
            # Log to database
            try:
                session_db = get_session_db()
                await session_db.add_terminal_command(
                    session_id, command, output, result.exit_code, 
                    "/workspace", execution_time_ms
                )
            except Exception as e:
                logger.warning(f"Failed to log command to database: {e}")
            
            return {
                "command": command,
                "exit_code": result.exit_code,
                "output": output,
                "success": result.exit_code == 0,
                "execution_time_ms": execution_time_ms
            }
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return {
                "command": command,
                "exit_code": -1,
                "output": f"Error: {str(e)}",
                "success": False
            }
    
    async def list_files(self, session_id: str, path: str = "/workspace") -> List[Dict[str, Any]]:
        """List files in container directory."""
        container = await self.get_container(session_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        
        try:
            result = container.exec_run(f"ls -la {path}")
            if result.exit_code != 0:
                return []
            
            files = []
            lines = result.output.decode("utf-8").strip().split("\n")
            
            for line in lines[1:]:  # Skip total line
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 9:
                        permissions = parts[0]
                        size = parts[4] if parts[4].isdigit() else "0"
                        name = " ".join(parts[8:])
                        
                        if name not in [".", ".."]:
                            files.append({
                                "name": name,
                                "type": "directory" if permissions.startswith("d") else "file",
                                "size": int(size),
                                "permissions": permissions,
                                "path": f"{path.rstrip('/')}/{name}"
                            })
            
            return files
        except Exception as e:
            logger.error(f"File listing failed: {e}")
            return []
    
    async def read_file(self, session_id: str, file_path: str) -> str:
        """Read file content from container."""
        container = await self.get_container(session_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        
        try:
            result = container.exec_run(f"cat {file_path}")
            if result.exit_code != 0:
                raise HTTPException(status_code=404, detail="File not found")
            
            return result.output.decode("utf-8", errors="replace")
        except Exception as e:
            logger.error(f"File read failed: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")
    
    async def write_file(self, session_id: str, file_path: str, content: str) -> bool:
        """Write content to file in container."""
        container = await self.get_container(session_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        
        try:
            # Create directory if it doesn't exist
            dir_path = os.path.dirname(file_path)
            if dir_path:
                container.exec_run(f"mkdir -p {dir_path}")
            
            # Write content using tee command to handle special characters
            import shlex
            escaped_content = shlex.quote(content)
            result = container.exec_run(f"echo {escaped_content} | tee {file_path}")
            
            success = result.exit_code == 0
            
            if success:
                # Update file metadata in database
                try:
                    import os
                    file_name = os.path.basename(file_path)
                    file_ext = os.path.splitext(file_name)[1].lower()
                    
                    # Detect file type and language
                    language_map = {
                        '.py': 'python',
                        '.js': 'javascript',
                        '.ts': 'typescript',
                        '.html': 'html',
                        '.css': 'css',
                        '.json': 'json',
                        '.md': 'markdown',
                        '.txt': 'text',
                        '.sh': 'bash',
                        '.yml': 'yaml',
                        '.yaml': 'yaml'
                    }
                    
                    language = language_map.get(file_ext, 'text')
                    file_type = 'text' if file_ext in language_map else 'binary'
                    content_preview = content[:500] if len(content) > 500 else content
                    
                    session_db = get_session_db()
                    await session_db.update_session_file(
                        session_id, file_path, file_name, file_type,
                        len(content), content_preview, language
                    )
                except Exception as e:
                    logger.warning(f"Failed to update file metadata: {e}")
            
            return success
        except Exception as e:
            logger.error(f"File write failed: {e}")
            return False
    
    async def stop_container(self, session_id: str) -> bool:
        """Stop and remove container."""
        if session_id not in self.active_containers:
            return False
        
        try:
            container_info = self.active_containers[session_id]
            container = self.docker_client.containers.get(container_info["container_id"])
            
            container.stop(timeout=10)
            container.remove()
            
            # Keep volume for data persistence, but remove from active containers
            del self.active_containers[session_id]
            
            logger.info(f"✅ Stopped container for session: {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop container: {e}")
            return False
    
    async def cleanup_inactive_containers(self):
        """Cleanup containers that have been inactive."""
        if not self.docker_client:
            return
        
        current_time = datetime.now()
        to_cleanup = []
        
        for session_id, info in self.active_containers.items():
            if current_time - info["last_activity"] > CONTAINER_TIMEOUT:
                to_cleanup.append(session_id)
        
        for session_id in to_cleanup:
            logger.info(f"🧹 Cleaning up inactive container: {session_id}")
            await self.stop_container(session_id)

# Global container manager instance
container_manager = ContainerManager()

# Request/Response models
class CreateContainerRequest(BaseModel):
    session_id: Optional[str] = None
    user_id: Optional[str] = None

class ExecuteCommandRequest(BaseModel):
    session_id: str
    command: str

class FileOperationRequest(BaseModel):
    session_id: str
    file_path: str
    content: Optional[str] = None

class ListFilesRequest(BaseModel):
    session_id: str
    path: str = "/workspace"

# API Endpoints
@router.post("/api/vibecoding/container/create")
async def create_container(req: CreateContainerRequest):
    """Create a new development container for vibecoding session."""
    session_id = req.session_id or str(uuid.uuid4())
    
    result = await container_manager.create_dev_container(session_id, req.user_id)
    return result

@router.post("/api/vibecoding/container/execute")
async def execute_command(req: ExecuteCommandRequest):
    """Execute command in development container."""
    result = await container_manager.execute_command(req.session_id, req.command)
    return result

@router.post("/api/vibecoding/container/files/list")
async def list_files(req: ListFilesRequest):
    """List files in container directory."""
    files = await container_manager.list_files(req.session_id, req.path)
    return {"files": files, "path": req.path}

@router.post("/api/vibecoding/container/files/read")
async def read_file(req: FileOperationRequest):
    """Read file content from container."""
    content = await container_manager.read_file(req.session_id, req.file_path)
    return {"content": content, "file_path": req.file_path}

@router.post("/api/vibecoding/container/files/write")
async def write_file(req: FileOperationRequest):
    """Write content to file in container."""
    if req.content is None:
        raise HTTPException(status_code=400, detail="Content is required")
    
    success = await container_manager.write_file(req.session_id, req.file_path, req.content)
    return {"success": success, "file_path": req.file_path}

@router.delete("/api/vibecoding/container/{session_id}")
async def stop_container(session_id: str):
    """Stop and remove development container."""
    success = await container_manager.stop_container(session_id)
    return {"success": success, "session_id": session_id}

@router.get("/api/vibecoding/container/{session_id}/status")
async def get_container_status(session_id: str):
    """Get container status."""
    container = await container_manager.get_container(session_id)
    if not container:
        return {"status": "not_found", "session_id": session_id}
    
    try:
        container.reload()
        return {
            "status": container.status,
            "session_id": session_id,
            "created": container.attrs["Created"],
            "image": container.image.tags[0] if container.image.tags else "unknown"
        }
    except Exception as e:
        logger.error(f"Error getting container status: {e}")
        return {"status": "error", "session_id": session_id, "error": str(e)}

# WebSocket endpoint for real-time terminal
@router.websocket("/api/vibecoding/container/{session_id}/terminal")
async def terminal_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time terminal interaction."""
    await websocket.accept()
    
    container = await container_manager.get_container(session_id)
    if not container:
        await websocket.send_json({"type": "error", "message": "Container not found"})
        await websocket.close()
        return
    
    try:
        # Start interactive shell
        exec_id = container.client.api.exec_create(
            container.id,
            "/bin/bash",
            stdin=True,
            tty=True,
            workdir="/workspace"
        )
        
        socket = container.client.api.exec_start(
            exec_id["Id"],
            detach=False,
            tty=True,
            stream=True,
            socket=True
        )
        
        # Handle WebSocket communication
        async def read_from_container():
            try:
                while True:
                    data = socket.recv(1024)
                    if not data:
                        break
                    await websocket.send_text(data.decode("utf-8", errors="replace"))
            except Exception as e:
                logger.error(f"Error reading from container: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})
        
        async def write_to_container():
            try:
                while True:
                    message = await websocket.receive_text()
                    socket.send(message.encode("utf-8"))
            except WebSocketDisconnect:
                logger.info("Terminal WebSocket disconnected")
            except Exception as e:
                logger.error(f"Error writing to container: {e}")
        
        # Run both coroutines concurrently
        await asyncio.gather(
            read_from_container(),
            write_to_container()
        )
    
    except Exception as e:
        logger.error(f"Terminal WebSocket error: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        try:
            socket.close()
        except:
            pass

@router.get("/api/vibecoding/sessions/{user_id}")
async def get_user_sessions(user_id: int, active_only: bool = True):
    """Get all sessions for a user."""
    try:
        session_db = get_session_db()
        sessions = await session_db.list_user_sessions(user_id, active_only)
        return {"sessions": sessions, "user_id": user_id}
    except Exception as e:
        logger.error(f"Failed to get user sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/vibecoding/sessions/create")
async def create_session_endpoint(
    user_id: int, 
    project_name: str = "Untitled Project", 
    description: str = ""
):
    """Create a new vibecoding session."""
    try:
        session_id = str(uuid.uuid4())
        volume_name = f"{VOLUME_PREFIX}{session_id}"
        
        session_db = get_session_db()
        result = await session_db.create_session(
            session_id, user_id, project_name, description, 
            volume_name=volume_name
        )
        
        return {
            "session_id": session_id,
            "project_name": project_name,
            "volume_name": volume_name,
            **result
        }
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class SessionCreateRequest(BaseModel):
    user_id: int
    project_name: str
    description: Optional[str] = ""

@router.post("/api/vibecoding/sessions")
async def create_session_json(request: Request):
    """Create a new vibecoding session (JSON endpoint for frontend)."""
    try:
        # Parse JSON request body
        body = await request.body()
        logger.info(f"[DEBUG] Raw request body: {body}")
        
        try:
            data = json.loads(body)
            logger.info(f"[DEBUG] Parsed JSON data: {data}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            raise HTTPException(status_code=422, detail=f"Invalid JSON: {e}")
        
        # Validate required fields
        user_id = data.get('user_id')
        project_name = data.get('project_name')
        description = data.get('description', '')
        
        logger.info(f"[DEBUG] Extracted fields - user_id: {user_id} (type: {type(user_id)}), project_name: {project_name} (type: {type(project_name)}), description: {description}")
        
        if user_id is None:
            logger.error(f"[DEBUG] Validation failed: user_id is None")
            raise HTTPException(status_code=422, detail="user_id is required")
        if project_name is None:
            logger.error(f"[DEBUG] Validation failed: project_name is None")
            raise HTTPException(status_code=422, detail="project_name is required")
            
        session_id = str(uuid.uuid4())
        volume_name = f"{VOLUME_PREFIX}{session_id}"
        
        session_db = get_session_db()
        result = await session_db.create_session(
            session_id, int(user_id), project_name, description,
            volume_name=volume_name
        )
        
        return {
            "session_id": session_id,
            "project_name": project_name,
            "volume_name": volume_name,
            **result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/vibecoding/sessions/{session_id}/history")
async def get_terminal_history(session_id: str, limit: int = 50):
    """Get terminal history for session."""
    try:
        session_db = get_session_db()
        history = await session_db.get_terminal_history(session_id, limit)
        return {"history": history, "session_id": session_id}
    except Exception as e:
        logger.error(f"Failed to get terminal history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/vibecoding/sessions/{session_id}/files")
async def get_session_files_endpoint(session_id: str):
    """Get file metadata for session."""
    try:
        session_db = get_session_db()
        files = await session_db.get_session_files(session_id)
        return {"files": files, "session_id": session_id}
    except Exception as e:
        logger.error(f"Failed to get session files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Cleanup task (should be called periodically)
@router.post("/api/vibecoding/container/cleanup")
async def cleanup_containers():
    """Manually trigger container cleanup."""
    await container_manager.cleanup_inactive_containers()
    
    # Also cleanup database
    try:
        session_db = get_session_db()
        cleaned = await session_db.cleanup_inactive_sessions()
        return {"message": "Cleanup completed", "sessions_cleaned": cleaned}
    except Exception as e:
        logger.error(f"Database cleanup failed: {e}")
        return {"message": "Container cleanup completed, database cleanup failed"}