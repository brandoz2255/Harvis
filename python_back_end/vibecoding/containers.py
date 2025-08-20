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
import time
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import asyncpg
from .db_session import get_session_db

# Import auth utilities
from auth_utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vibe-dev-containers"])

# Container configuration
from .config import VIBECODING_IMAGE, ensure_image
CONTAINER_TIMEOUT = timedelta(hours=2)  # Auto-cleanup after 2 hours of inactivity
VOLUME_PREFIX = "vibecoding_"
TEMPLATE_VOLUME = "vibe_template"

# Performance tracking
import time
from contextlib import contextmanager

@contextmanager
def timer(operation_name: str):
    """Context manager for timing operations with logging."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(f"[{operation_name}] {duration_ms:.1f}ms")

# Session status store - in production, use Redis for scalability
SESSION_STATUS_STORE: Dict[str, Dict[str, Any]] = {}
ETA_HISTORY: Dict[str, Dict[str, float]] = {}  # image -> phase -> avg_duration_seconds

# Progress tracking models
class ProgressInfo(BaseModel):
    percent: Optional[int] = None
    eta_ms: Optional[int] = None

class SessionStatus(BaseModel):
    ok: bool = True
    ready: bool = False
    phase: str = "Starting"  # Starting|PullingImage|CreatingVolume|CreatingContainer|StartingContainer|Ready
    progress: ProgressInfo = Field(default_factory=ProgressInfo)
    error: Optional[str] = None
    session_id: Optional[str] = None
    message: Optional[str] = None

class CreateSessionRequest(BaseModel):
    workspace_id: str
    template: Optional[str] = None
    image: Optional[str] = Field(default="vibecoding-optimized:latest")
    project_name: Optional[str] = None
    description: Optional[str] = None

class CreateSessionResponse(BaseModel):
    ok: bool = True
    session_id: str
    phase: str = "Starting"
    message: Optional[str] = None

def update_session_status(session_id: str, phase: str, percent: Optional[int] = None, 
                         eta_ms: Optional[int] = None, ready: bool = False, 
                         error: Optional[str] = None, user_id: Optional[str] = None):
    """Update session status in the store with progress tracking."""
    if session_id not in SESSION_STATUS_STORE:
        SESSION_STATUS_STORE[session_id] = {
            "ready": False,
            "phase": "Starting",
            "progress": {"percent": 0, "eta_ms": None},
            "error": None,
            "owner_user_id": user_id,
            "created_at": datetime.now(),
            "last_updated": datetime.now()
        }
    
    session_status = SESSION_STATUS_STORE[session_id]
    session_status["phase"] = phase
    session_status["ready"] = ready
    session_status["last_updated"] = datetime.now()
    
    if percent is not None:
        session_status["progress"]["percent"] = percent
    if eta_ms is not None:
        session_status["progress"]["eta_ms"] = eta_ms
    if error is not None:
        session_status["error"] = error
        session_status["ready"] = False
    
    logger.info(f"[{session_id}] Status: {phase} ({percent}%) - ETA: {eta_ms}ms")

def calculate_eta(image: str, phase: str, start_time: float) -> Optional[int]:
    """Calculate ETA based on historical data or conservative defaults."""
    elapsed = time.perf_counter() - start_time
    
    # Conservative defaults per phase (seconds)
    phase_defaults = {
        "Starting": 2,
        "PullingImage": 30,  # Conservative for large images
        "CreatingVolume": 5,
        "CreatingContainer": 10, 
        "StartingContainer": 15,
        "Ready": 0
    }
    
    # Use historical data if available
    if image in ETA_HISTORY and phase in ETA_HISTORY[image]:
        estimated_duration = ETA_HISTORY[image][phase]
    else:
        estimated_duration = phase_defaults.get(phase, 30)
    
    remaining = max(0, estimated_duration - elapsed)
    return int(remaining * 1000)  # Convert to milliseconds

def update_eta_history(image: str, phase: str, duration_seconds: float):
    """Update ETA history with exponential moving average."""
    if image not in ETA_HISTORY:
        ETA_HISTORY[image] = {}
    
    if phase not in ETA_HISTORY[image]:
        ETA_HISTORY[image][phase] = duration_seconds
    else:
        # Exponential moving average with alpha=0.3
        current = ETA_HISTORY[image][phase]
        ETA_HISTORY[image][phase] = 0.7 * current + 0.3 * duration_seconds

class ContainerManager:
    """Manages Docker containers for vibecoding sessions."""
    
    def __init__(self):
        try:
            self.docker_client = docker.from_env()
            logger.info("✅ Docker client initialized")
            
            # Initialize optimizations
            asyncio.create_task(self._initialize_optimizations())
        except Exception as e:
            logger.error(f"❌ Failed to initialize Docker client: {e}")
            self.docker_client = None
        
        self.active_containers: Dict[str, Dict[str, Any]] = {}
        self.image_ready = False
        self.template_volume_ready = False
        
    async def _initialize_optimizations(self):
        """Initialize performance optimizations on startup."""
        if not self.docker_client:
            return
            
        try:
            # Ensure the container image is available
            with timer("image_ensure"):
                try:
                    ensure_image(self.docker_client, VIBECODING_IMAGE)
                    logger.info(f"✅ Image {VIBECODING_IMAGE} is ready")
                    self.image_ready = True
                except Exception as e:
                    logger.error(f"❌ Failed to ensure image {VIBECODING_IMAGE}: {e}")
                    self.image_ready = False
                    raise
            
            # Create or verify template volume
            with timer("template_volume_init"):
                await self._ensure_template_volume()
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize optimizations: {e}")
    
    async def _ensure_template_volume(self):
        """Ensure template volume exists with basic project structure."""
        try:
            # Check if template volume exists
            try:
                volume = self.docker_client.volumes.get(TEMPLATE_VOLUME)
                logger.info(f"✅ Template volume {TEMPLATE_VOLUME} exists")
                self.template_volume_ready = True
                return
            except docker.errors.NotFound:
                pass
            
            # Create template volume
            volume = self.docker_client.volumes.create(name=TEMPLATE_VOLUME)
            logger.info(f"📦 Created template volume: {TEMPLATE_VOLUME}")
            
            # Initialize template with basic structure if using fallback image
            fallback_image = "alpine:latest"
            init_container = self.docker_client.containers.run(
                image=fallback_image,
                command=[
                    "sh", "-c", 
                    "mkdir -p /to/src /to/tests /to/docs && "
                    "echo '# Welcome to VibeCoading' > /to/README.md && "
                    "echo 'print(\"🚀 Ready to code!\")' > /to/hello.py && "
                    "echo 'FROM_TEMPLATE=true' > /to/.vibe_ready"
                ],
                volumes={TEMPLATE_VOLUME: {"bind": "/to", "mode": "rw"}},
                remove=True,
                detach=False
            )
            
            logger.info(f"✅ Template volume {TEMPLATE_VOLUME} initialized")
            self.template_volume_ready = True
            
        except Exception as e:
            logger.error(f"❌ Failed to create template volume: {e}")
            # Continue without template volume
            self.template_volume_ready = False
        
    async def create_dev_container(self, session_id: str, image: str = None, user_id: str = None) -> Dict[str, Any]:
        """Create a new development container with progress tracking and ETA estimation."""
        if not self.docker_client:
            update_session_status(session_id, "Error", error="DOCKER_UNAVAILABLE")
            raise HTTPException(status_code=503, detail="Docker not available")
        
        start_time = time.perf_counter()
        image = image or VIBECODING_IMAGE
        
        try:
            container_name = f"vibecoding_{session_id}"
            volume_name = f"{VOLUME_PREFIX}{session_id}"
            
            # Initialize session status with progress tracking
            update_session_status(session_id, "Starting", 0, calculate_eta(image, "Starting", start_time), user_id=user_id)
            
            # Set initial container info
            initial_container_info = {
                "container_id": None,
                "container_name": container_name,
                "session_id": session_id,
                "user_id": user_id,
                "volume_name": volume_name,
                "created_at": datetime.now(),
                "last_activity": datetime.now(),
                "status": "starting",
                "ready": False
            }
            self.active_containers[session_id] = initial_container_info
            
            # Phase 1: Check existing container (5% progress)
            phase_start = time.perf_counter()
            update_session_status(session_id, "Starting", 5, calculate_eta(image, "Starting", start_time))
            
            with timer("existing_container_check"):
                try:
                    existing_container = self.docker_client.containers.get(container_name)
                    logger.info(f"🔄 Found existing container: {container_name}")
                    
                    # If container exists but is stopped, start it with readiness check
                    if existing_container.status == "exited":
                        update_session_status(session_id, "StartingContainer", 75, calculate_eta(image, "StartingContainer", start_time))
                        
                        with timer("container_start"):
                            existing_container.start()
                        
                        # Wait for readiness
                        update_session_status(session_id, "StartingContainer", 90, calculate_eta(image, "StartingContainer", start_time))
                        with timer("ready_wait"):
                            await self._wait_for_container_ready(existing_container)
                        
                        logger.info(f"▶️ Started existing container: {container_name}")
                    elif existing_container.status == "running":
                        logger.info(f"✅ Container already running: {container_name}")
                    
                    # Mark as ready and update ETA history
                    update_session_status(session_id, "Ready", 100, 0, ready=True)
                    phase_duration = time.perf_counter() - phase_start
                    update_eta_history(image, "StartingContainer", phase_duration)
                    
                    # Store container info and return
                    container_info = {
                        "container_id": existing_container.id,
                        "container_name": container_name,
                        "session_id": session_id,
                        "user_id": user_id,
                        "volume_name": volume_name,
                        "created_at": datetime.now(),
                        "last_activity": datetime.now(),
                        "status": existing_container.status,
                        "ready": True
                    }
                    self.active_containers[session_id] = container_info
                    
                    total_time = (time.perf_counter() - start_time) * 1000
                    logger.info(f"[create:total_existing] {total_time:.1f}ms")
                    
                    return {
                        "session_id": session_id,
                        "container_id": existing_container.id,
                        "container_name": container_name,
                        "status": existing_container.status,
                        "workspace_path": "/workspace",
                        "ready": True
                    }
                    
                except docker.errors.NotFound:
                    # Container doesn't exist, create new one
                    logger.info(f"🆕 Creating new container: {container_name}")
            
            # Phase 2: Pull/ensure image (10-25% progress)
            phase_start = time.perf_counter()
            update_session_status(session_id, "PullingImage", 10, calculate_eta(image, "PullingImage", start_time))
            
            with timer("image_ensure_before_create"):
                try:
                    ensure_image(self.docker_client, image)
                    phase_duration = time.perf_counter() - phase_start
                    update_eta_history(image, "PullingImage", phase_duration)
                except Exception as e:
                    update_session_status(session_id, "Error", error="IMAGE_UNAVAILABLE")
                    raise docker.errors.ImageNotFound(f"Failed to pull image {image}: {e}")
            
            # Phase 3: Create volume (25-45% progress)
            phase_start = time.perf_counter()
            update_session_status(session_id, "CreatingVolume", 25, calculate_eta(image, "CreatingVolume", start_time))
            
            with timer("volume_create"):
                await self._create_session_volume(volume_name)
                phase_duration = time.perf_counter() - phase_start
                update_eta_history(image, "CreatingVolume", phase_duration)
            
            # Phase 4: Create container (45-70% progress)
            phase_start = time.perf_counter()
            update_session_status(session_id, "CreatingContainer", 45, calculate_eta(image, "CreatingContainer", start_time))
            
            # Container configuration with optimized settings
            container_config = {
                "image": image,
                "name": container_name,
                "detach": True,
                "tty": True,
                "stdin_open": True,
                "init": True,  # Add --init for proper signal handling
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
                },
                # Optimized resource limits
                "mem_limit": "1g",
                "cpu_count": 2,
                "ulimits": [
                    {"name": "nofile", "soft": 65536, "hard": 65536}
                ],
                "log_config": {
                    "type": "json-file",
                    "config": {
                        "max-size": "10m",
                        "max-file": "3"
                    }
                },
                # Command that touches readiness file and idles
                "command": ["bash", "-lc", "test -d /workspace && touch /tmp/ready && sleep infinity"]
            }
            
            # Create and start container
            with timer("container_create"):
                container = self.docker_client.containers.run(**container_config)
                phase_duration = time.perf_counter() - phase_start
                update_eta_history(image, "CreatingContainer", phase_duration)
            
            # Phase 5: Start container and wait for readiness (70-100% progress)
            phase_start = time.perf_counter()
            update_session_status(session_id, "StartingContainer", 70, calculate_eta(image, "StartingContainer", start_time))
            
            # Wait for container readiness
            with timer("ready_wait"):
                await self._wait_for_container_ready(container)
                phase_duration = time.perf_counter() - phase_start
                update_eta_history(image, "StartingContainer", phase_duration)
            
            # Phase 6: Ready! (100% progress)
            update_session_status(session_id, "Ready", 100, 0, ready=True)
            
            # Store container info
            container_info = {
                "container_id": container.id,
                "container_name": container_name,
                "session_id": session_id,
                "user_id": user_id,
                "volume_name": volume_name,
                "created_at": datetime.now(),
                "last_activity": datetime.now(),
                "status": "running",
                "ready": True
            }
            
            self.active_containers[session_id] = container_info
            
            # Update database with container info
            try:
                session_db = get_session_db()
                await session_db.update_container_status(session_id, container.id, "running")
            except Exception as e:
                logger.warning(f"Failed to update container status in database: {e}")
            
            total_time = (time.perf_counter() - start_time) * 1000
            logger.info(f"[create:total_new] {total_time:.1f}ms")
            logger.info(f"✅ Created dev container: {container_name} for session: {session_id}")
            
            return {
                "session_id": session_id,
                "container_id": container.id,
                "container_name": container_name,
                "status": "running",
                "workspace_path": "/workspace",
                "ready": True
            }
            
        except docker.errors.ImageNotFound as e:
            logger.error(f"Image not found for container creation: {e}")
            update_session_status(session_id, "Error", error="IMAGE_UNAVAILABLE")
            raise HTTPException(status_code=404, detail=f"Container image not available: {str(e)}")
        except docker.errors.APIError as e:
            logger.error(f"Docker API error during container creation: {e}")
            update_session_status(session_id, "Error", error="CREATE_FAILED")
            raise HTTPException(status_code=500, detail=f"Container creation failed: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to create dev container: {e}")
            update_session_status(session_id, "Error", error="CREATE_FAILED")
            raise HTTPException(status_code=500, detail=f"Failed to create container: {str(e)}")
    
    async def _create_session_volume(self, volume_name: str):
        """Create session volume, optionally cloning from template for speed."""
        try:
            # Check if volume already exists
            try:
                volume = self.docker_client.volumes.get(volume_name)
                logger.info(f"📦 Using existing volume: {volume_name}")
                return volume
            except docker.errors.NotFound:
                pass
            
            # Create new volume
            volume = self.docker_client.volumes.create(name=volume_name)
            logger.info(f"📦 Created volume: {volume_name}")
            
            # Clone template if available for fast initialization
            if self.template_volume_ready:
                with timer("volume_clone"):
                    clone_container = self.docker_client.containers.run(
                        image="alpine:latest",
                        command=["sh", "-c", "cp -a /from/. /to/ 2>/dev/null || echo 'Template clone complete'"],
                        volumes={
                            TEMPLATE_VOLUME: {"bind": "/from", "mode": "ro"},
                            volume_name: {"bind": "/to", "mode": "rw"}
                        },
                        remove=True,
                        detach=False
                    )
                    logger.info(f"📋 Cloned template to volume: {volume_name}")
            
            return volume
            
        except Exception as e:
            logger.error(f"❌ Failed to create session volume: {e}")
            raise
    
    async def _wait_for_container_ready(self, container, max_retries: int = 50, interval: float = 0.1):
        """Wait for container to be ready using readiness probe."""
        logger.info(f"⏳ Waiting for container {container.name} to be ready...")
        
        for attempt in range(max_retries):
            try:
                # Check if readiness file exists
                result = container.exec_run("test -f /tmp/ready && echo READY || echo WAIT", workdir="/")
                if result.exit_code == 0 and b"READY" in result.output:
                    logger.info(f"✅ Container {container.name} is ready")
                    return True
                    
                if attempt % 10 == 0:  # Log every 10 attempts (1 second)
                    logger.debug(f"Container {container.name} not ready yet (attempt {attempt + 1})")
                    
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.warning(f"Readiness check failed on attempt {attempt + 1}: {e}")
                await asyncio.sleep(interval)
        
        logger.error(f"❌ Container {container.name} failed to become ready after {max_retries * interval}s")
        return False
    
    async def get_container(self, session_id: str) -> Optional[docker.models.containers.Container]:
        """Get container by session ID."""
        if not self.docker_client:
            return None
        
        # First try to get from active_containers if we have it
        if session_id in self.active_containers:
            try:
                container_info = self.active_containers[session_id]
                container = self.docker_client.containers.get(container_info["container_id"])
                
                # Update last activity
                container_info["last_activity"] = datetime.now()
                
                return container
            except docker.errors.NotFound:
                # Container was removed externally
                del self.active_containers[session_id]
            except Exception as e:
                logger.error(f"Error getting tracked container: {e}")
        
        # If not in active_containers or failed, try to find by container name
        try:
            container_name = f"vibecoding_{session_id}"
            container = self.docker_client.containers.get(container_name)
            
            # Container exists but not tracked, add it to active_containers
            volume_name = f"{VOLUME_PREFIX}{session_id}"
            container_info = {
                "container_id": container.id,
                "container_name": container_name,
                "session_id": session_id,
                "user_id": "unknown",  # We don't know the user_id from existing containers
                "volume_name": volume_name,
                "created_at": datetime.now(),
                "last_activity": datetime.now(),
                "status": container.status
            }
            self.active_containers[session_id] = container_info
            logger.info(f"🔄 Re-tracked existing container: {container_name}")
            
            return container
        except docker.errors.NotFound:
            logger.info(f"🚫 Container not found for session: {session_id}")
            return None
        except Exception as e:
            logger.error(f"Error finding container by name: {e}")
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
            import os
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
@router.post("/api/vibecoding/sessions/create")
async def create_session_new(
    request: CreateSessionRequest, 
    current_user: dict = Depends(get_current_user)
) -> CreateSessionResponse:
    """Create a new vibecoding session with progress tracking."""
    try:
        session_id = str(uuid.uuid4())
        user_id = str(current_user["id"])
        
        logger.info(f"Creating session {session_id} for user {user_id} with image {request.image}")
        
        # Create session in database first
        if request.project_name:
            session_db = get_session_db()
            await session_db.create_session(
                session_id, current_user["id"], request.project_name, 
                request.description or "", volume_name=f"{VOLUME_PREFIX}{session_id}"
            )
        
        # Start container creation asynchronously (don't await here)
        asyncio.create_task(container_manager.create_dev_container(
            session_id, request.image, user_id
        ))
        
        return CreateSessionResponse(
            ok=True,
            session_id=session_id,
            phase="Starting",
            message="Session creation started"
        )
        
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

@router.post("/api/vibecoding/container/files/tree")
async def get_file_tree(req: ListFilesRequest):
    """Get complete file tree structure for better performance."""
    container = await container_manager.get_container(req.session_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")
    
    try:
        # Get full directory tree in one command for better performance
        result = container.exec_run(
            f"find {req.path} -type f -o -type d 2>/dev/null | head -1000"
        )
        
        if result.exit_code != 0:
            return {"files": [], "path": req.path}
        
        paths = result.output.decode("utf-8").strip().split("\n")
        paths = [p for p in paths if p and p != req.path]
        
        # Build tree structure
        tree_dict = {}
        for path in paths:
            if path:
                relative_path = path.replace(req.path, "").strip("/")
                if relative_path:
                    parts = relative_path.split("/")
                    current = tree_dict
                    
                    for i, part in enumerate(parts):
                        if part not in current:
                            # Check if it's the final part (file/directory)
                            is_final = i == len(parts) - 1
                            if is_final:
                                # Check if it's a directory
                                stat_result = container.exec_run(f"test -d '{path}' && echo dir || echo file")
                                is_dir = "dir" in stat_result.output.decode().strip()
                                
                                current[part] = {
                                    "type": "directory" if is_dir else "file",
                                    "path": path,
                                    "name": part,
                                    "children": {} if is_dir else None
                                }
                            else:
                                # Intermediate directory
                                current[part] = current.get(part, {
                                    "type": "directory",
                                    "path": "/".join(path.split("/")[:-len(parts)+i+1]),
                                    "name": part,
                                    "children": {}
                                })
                                current = current[part]["children"]
                        else:
                            if "children" in current[part]:
                                current = current[part]["children"]
        
        def tree_to_list(tree_dict):
            result = []
            for name, node in tree_dict.items():
                node_data = {
                    "name": name,
                    "type": node["type"],
                    "path": node["path"],
                }
                if node["type"] == "directory" and node.get("children"):
                    node_data["children"] = tree_to_list(node["children"])
                else:
                    node_data["children"] = []
                result.append(node_data)
            
            # Sort: directories first, then files, both alphabetically
            result.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
            return result
        
        file_list = tree_to_list(tree_dict)
        logger.info(f"Built file tree with {len(file_list)} root items for {req.session_id}")
        
        return {"files": file_list, "path": req.path}
        
    except Exception as e:
        logger.error(f"File tree listing failed: {e}")
        return {"files": [], "path": req.path}

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
        return {"status": "not_found", "session_id": session_id, "ready": False}
    
    try:
        container.reload()
        
        # Check readiness if container is running
        ready = False
        if container.status == "running":
            try:
                result = container.exec_run("ready-check", workdir="/")
                ready = result.exit_code == 0 and b"READY" in result.output
            except Exception:
                ready = False
        
        return {
            "status": container.status,
            "session_id": session_id,
            "created": container.attrs["Created"],
            "image": container.image.tags[0] if container.image.tags else "unknown",
            "ready": ready
        }
    except Exception as e:
        logger.error(f"Error getting container status: {e}")
        return {"status": "error", "session_id": session_id, "error": str(e), "ready": False}

@router.get("/api/vibecoding/session/status")
async def get_session_status_by_query(id: str):
    """Get comprehensive session status for UI gating (query param version)."""
    return await get_session_status_internal(id)

@router.get("/api/vibecoding/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """Get comprehensive session status for UI gating (path param version)."""
    return await get_session_status_internal(session_id)

async def get_session_status_internal(session_id: str) -> JSONResponse:
    """Internal function for session status checking - always returns JSON."""
    try:
        # Guard against empty/undefined session ID
        if not session_id or session_id == "undefined":
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "ready": False,
                    "error": "SESSION_ID_MISSING",
                    "message": "Session ID is required"
                }
            )
        
        # Check session status store first
        if session_id in SESSION_STATUS_STORE:
            session_status = SESSION_STATUS_STORE[session_id]
            
            # If session has error, return it
            if session_status.get("error"):
                return JSONResponse(
                    status_code=200,
                    content={
                        "ok": False,
                        "ready": False,
                        "phase": session_status["phase"],
                        "progress": session_status["progress"],
                        "error": session_status["error"],
                        "session_id": session_id,
                        "message": f"Session failed: {session_status['error']}"
                    }
                )
            
            # Return current status with progress
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "ready": session_status["ready"],
                    "phase": session_status["phase"],
                    "progress": session_status["progress"],
                    "error": None,
                    "session_id": session_id,
                    "message": "Session is ready" if session_status["ready"] else f"Session {session_status['phase'].lower()}..."
                }
            )
        
        # Session not in store - check if container exists
        container = await container_manager.get_container(session_id)
        if not container:
            return JSONResponse(
                status_code=404,
                content={
                    "ok": False,
                    "ready": False,
                    "error": "SESSION_NOT_FOUND",
                    "session_id": session_id,
                    "message": "Session not found"
                }
            )
        
        # Container exists but not tracked - assume ready if running
        container.reload()
        container_ready = container.status == "running"
        
        if container_ready:
            try:
                result = container.exec_run("test -f /tmp/ready && echo READY || echo WAIT", workdir="/")
                container_ready = result.exit_code == 0 and b"READY" in result.output
            except Exception:
                container_ready = False
        
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "ready": container_ready,
                "phase": "Ready" if container_ready else "Starting",
                "progress": {"percent": 100 if container_ready else 0, "eta_ms": 0},
                "error": None,
                "session_id": session_id,
                "message": "Session is ready" if container_ready else "Session starting..."
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting session status for {session_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "ready": False,
                "error": "INTERNAL",
                "session_id": session_id,
                "message": f"Internal server error: {str(e)}"
            }
        )

# WebSocket endpoint for real-time terminal with binary optimization
@router.websocket("/api/vibecoding/container/{session_id}/terminal")
async def terminal_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time terminal interaction with binary I/O optimization."""
    # Accept WebSocket with binary support (no compression for lower latency)
    await websocket.accept()
    
    # Log connection with timing
    start_time = time.perf_counter()
    logger.info(f"🔌 Terminal WebSocket connected for session: {session_id}")
    
    container = await container_manager.get_container(session_id)
    if not container:
        await websocket.send_json({"type": "error", "message": "Container not found"})
        await websocket.close()
        return
    
    # Check if container is ready before allowing terminal access
    try:
        result = container.exec_run("ready-check", workdir="/")
        if result.exit_code != 0 or b"READY" not in result.output:
            await websocket.send_json({"type": "error", "message": "Container not ready"})
            await websocket.close()
            return
    except Exception as e:
        await websocket.send_json({"type": "error", "message": f"Container readiness check failed: {e}"})
        await websocket.close()
        return
    
    try:
        # Start interactive shell with optimized settings
        with timer("exec_create"):
            exec_id = container.client.api.exec_create(
                container.id,
                ["/bin/bash", "-l"],  # Login shell for better environment
                stdin=True,
                tty=True,
                workdir="/workspace",
                environment={"TERM": "xterm-256color"}
            )
        
        with timer("exec_start"):
            socket = container.client.api.exec_start(
                exec_id["Id"],
                detach=False,
                tty=True,
                stream=True,
                socket=True
            )
        
        # Configure socket for optimal performance
        raw = getattr(socket, "_sock", socket)
        try:
            raw.settimeout(0.1)  # Shorter timeout for better responsiveness
            raw.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)  # Disable Nagle's algorithm
        except Exception:
            pass
        
        connect_time = (time.perf_counter() - start_time) * 1000
        logger.info(f"[terminal:connect] {connect_time:.1f}ms")
        
        # Send ready signal to client
        await websocket.send_json({"type": "ready", "message": "Terminal ready"})
            
        async def read_from_container():
            """Read from container and send to WebSocket using binary frames."""
            import socket as pysock
            read_count = 0
            try:
                while True:
                    try:
                        data = raw.recv(8192)  # Larger buffer for better throughput
                        if not data:
                            break
                        
                        # Send as binary for better performance
                        await websocket.send_bytes(data)
                        
                        read_count += 1
                        if read_count % 100 == 0:  # Log every 100 reads to avoid spam
                            logger.debug(f"Terminal read {read_count} messages")
                            
                    except pysock.timeout:
                        # Normal when no output - continue
                        await asyncio.sleep(0.01)  # Shorter sleep for responsiveness
                    except Exception as e:
                        if "closed" not in str(e).lower():
                            logger.error(f"Error reading from container: {e}")
                        break
                        
            except Exception as e:
                logger.error(f"Terminal read error: {e}")
                try:
                    await websocket.send_json({"type": "error", "message": str(e)})
                except:
                    pass
        
        async def write_to_container():
            """Write from WebSocket to container using binary frames."""
            write_count = 0
            try:
                while True:
                    try:
                        # Handle both binary and text messages
                        message = await websocket.receive()
                        
                        if message["type"] == "websocket.receive":
                            if "bytes" in message:
                                # Binary message
                                data = message["bytes"]
                            elif "text" in message:
                                # Text message - encode to bytes
                                data = message["text"].encode("utf-8")
                            else:
                                continue
                                
                            raw.send(data)
                            write_count += 1
                            
                    except WebSocketDisconnect:
                        logger.info(f"Terminal WebSocket disconnected after {write_count} writes")
                        break
                    except Exception as e:
                        logger.error(f"Error writing to container: {e}")
                        break
                        
            except Exception as e:
                logger.error(f"Terminal write error: {e}")
        
        # Run both coroutines concurrently
        await asyncio.gather(
            read_from_container(),
            write_to_container(),
            return_exceptions=True
        )
    
    except Exception as e:
        logger.error(f"Terminal WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        try:
            socket.close()
        except:
            pass
        
        total_time = (time.perf_counter() - start_time) * 1000
        logger.info(f"[terminal:total] {total_time:.1f}ms")

# Get sessions for authenticated user
@router.get("/api/vibecoding/sessions")
async def get_sessions(
    current_user: dict = Depends(get_current_user),
    active_only: bool = True
):
    """Get all sessions for the authenticated user."""
    try:
        session_db = get_session_db()
        sessions = await session_db.list_user_sessions(current_user["id"], active_only)
        return {"sessions": sessions, "user_id": current_user["id"]}
    except Exception as e:
        logger.error(f"Failed to get user sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/vibecoding/sessions/{user_id}")
async def get_user_sessions(user_id: int, active_only: bool = True):
    """Get all sessions for a user (admin endpoint)."""
    try:
        session_db = get_session_db()
        sessions = await session_db.list_user_sessions(user_id, active_only)
        return {"sessions": sessions, "user_id": user_id}
    except Exception as e:
        logger.error(f"Failed to get user sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Remove old models as they're now at the top
# class SessionCreateRequest(BaseModel):
#     project_name: str
#     description: str = ""

# Session creation with proper authentication
@router.post("/api/vibecoding/sessions/create")
async def create_session_new(
    request: CreateSessionRequest, 
    current_user: dict = Depends(get_current_user)
) -> CreateSessionResponse:
    """Create a new vibecoding session with progress tracking."""
    try:
        session_id = str(uuid.uuid4())
        user_id = str(current_user["id"])
        
        logger.info(f"Creating session {session_id} for user {user_id} with image {request.image}")
        
        # Create session in database first
        if request.project_name:
            session_db = get_session_db()
            await session_db.create_session(
                session_id, current_user["id"], request.project_name, 
                request.description or "", volume_name=f"{VOLUME_PREFIX}{session_id}"
            )
        
        # Start container creation asynchronously (don't await here)
        asyncio.create_task(container_manager.create_dev_container(
            session_id, request.image, user_id
        ))
        
        return CreateSessionResponse(
            ok=True,
            session_id=session_id,
            phase="Starting",
            message="Session creation started"
        )
        
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Legacy endpoint for backward compatibility (no authentication required)
@router.post("/api/vibecoding/sessions")
async def create_session_legacy(request: Request) -> JSONResponse:
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

# Session status endpoints with authentication
@router.get("/api/vibecoding/session/status")
async def get_session_status_by_query(
    id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get comprehensive session status for UI gating (query param version)."""
    return await get_session_status_internal(id, current_user["id"])

@router.get("/api/vibecoding/sessions/{session_id}/status")
async def get_session_status(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get comprehensive session status for UI gating (path param version)."""
    return await get_session_status_internal(session_id, current_user["id"])

async def get_session_status_internal(session_id: str, user_id: int) -> JSONResponse:
    """Internal function for session status checking - always returns JSON."""
    try:
        # Guard against empty/undefined session ID
        if not session_id or session_id == "undefined":
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "ready": False,
                    "error": "SESSION_ID_MISSING",
                    "message": "Session ID is required"
                }
            )
        
        # Check session status store first
        if session_id in SESSION_STATUS_STORE:
            session_status = SESSION_STATUS_STORE[session_id]
            
            # Verify session ownership
            if session_status.get("owner_user_id") != str(user_id):
                return JSONResponse(
                    status_code=403,
                    content={
                        "ok": False,
                        "ready": False,
                        "error": "FORBIDDEN",
                        "session_id": session_id,
                        "message": "Access denied"
                    }
                )
            
            # If session has error, return it
            if session_status.get("error"):
                return JSONResponse(
                    status_code=200,
                    content={
                        "ok": False,
                        "ready": False,
                        "phase": session_status["phase"],
                        "progress": session_status["progress"],
                        "error": session_status["error"],
                        "session_id": session_id,
                        "message": f"Session failed: {session_status['error']}"
                    }
                )
            
            # Return current status with progress
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "ready": session_status["ready"],
                    "phase": session_status["phase"],
                    "progress": session_status["progress"],
                    "error": None,
                    "session_id": session_id,
                    "message": "Session is ready" if session_status["ready"] else f"Session {session_status['phase'].lower()}..."
                }
            )
        
        # Session not in store - check if container exists
        container = await container_manager.get_container(session_id)
        if not container:
            return JSONResponse(
                status_code=404,
                content={
                    "ok": False,
                    "ready": False,
                    "error": "SESSION_NOT_FOUND",
                    "session_id": session_id,
                    "message": "Session not found"
                }
            )
        
        # Container exists but not tracked - assume ready if running
        container.reload()
        container_ready = container.status == "running"
        
        if container_ready:
            try:
                result = container.exec_run("test -f /tmp/ready && echo READY || echo WAIT", workdir="/")
                container_ready = result.exit_code == 0 and b"READY" in result.output
            except Exception:
                container_ready = False
        
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "ready": container_ready,
                "phase": "Ready" if container_ready else "Starting",
                "progress": {"percent": 100 if container_ready else 0, "eta_ms": 0},
                "error": None,
                "session_id": session_id,
                "message": "Session is ready" if container_ready else "Session starting..."
            }
        )
        
    except Exception as e:
        logger.error(f"Error getting session status for {session_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "ready": False,
                "error": "INTERNAL",
                "session_id": session_id,
                "message": f"Internal server error: {str(e)}"
            }
        )

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