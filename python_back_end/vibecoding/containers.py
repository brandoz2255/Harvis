"""Vibecoding Container Management

This module manages Docker containers for VibeCode IDE sessions, providing isolated
development environments with persistent storage, resource limits, and security controls.
"""

import docker
import os
import socket
import logging
import time
import asyncio
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

# Import auth utilities
from auth_utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vibecode-containers"])


class ContainerInfo:
    """Container information data class"""
    def __init__(self, container_id: str, container_name: str, session_id: str, 
                 user_id: str, volume_name: str, status: str):
        self.container_id = container_id
        self.container_name = container_name
        self.session_id = session_id
        self.user_id = user_id
        self.volume_name = volume_name
        self.status = status
        self.created_at = datetime.now()
        self.last_activity = datetime.now()


class ExecutionResult:
    """Command execution result data class"""
    def __init__(self, command: str, stdout: str, stderr: str, exit_code: int, 
                 execution_time_ms: int):
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.execution_time_ms = execution_time_ms
        self.started_at = int(time.time() * 1000)
        self.finished_at = self.started_at + execution_time_ms


class ContainerManager:
    """Manages Docker containers for VibeCode sessions
    
    Provides container lifecycle management including creation, starting, stopping,
    and cleanup. Ensures containers are properly configured with resource limits,
    security options, and persistent volumes.
    """
    
    def __init__(self):
        """Initialize Docker client and container tracking"""
        try:
            self.docker_client = docker.from_env()
            logger.info("✅ Docker client initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Docker client: {e}")
            self.docker_client = None
        
        # Track active IDE containers in memory for fast reconnection
        self.active_containers: Dict[str, ContainerInfo] = {}
        # Track active runner containers (language/runtime) per session
        self.active_runner_containers: Dict[str, ContainerInfo] = {}
        
        # Background cleanup task
        self._cleanup_task = None
        self._cleanup_running = False
    
    async def create_container(
        self, 
        session_id: str, 
        user_id: str, 
        template: str = "base"
    ) -> ContainerInfo:
        """Create a new Docker container for a VibeCode session
        
        Args:
            session_id: Unique session identifier
            user_id: User ID for container ownership
            template: Container template (default: "base")
            
        Returns:
            ContainerInfo object with container details
            
        Raises:
            HTTPException: If Docker is unavailable or container creation fails
        """
        if not self.docker_client:
            raise HTTPException(status_code=503, detail="Docker service unavailable")
        
        try:
            # Generate container and volume names following spec format
            container_name = f"vibecode-{user_id}-{session_id}"
            volume_name = f"vibecode-{user_id}-{session_id}-ws"
            
            logger.info(f"🆕 Creating container: {container_name}")
            
            # Check if container already exists (reuse logic)
            existing_container = await self._find_existing_container(container_name)
            if existing_container:
                logger.info(f"🔄 Container already exists: {container_name}")
                return await self._handle_existing_container(
                    existing_container, session_id, user_id, volume_name
                )
            
            # Create or get volume for persistent storage
            volume = await self._ensure_volume(volume_name)
            
            # Determine image and runtime settings
            code_server_image = os.getenv("VIBECODING_IDE_IMAGE", "ghcr.io/coder/code-server:latest")
            internal_port = int(os.getenv("IDE_CODE_SERVER_INTERNAL_PORT", "8080"))
            base_network = os.getenv("IDE_BASE_NETWORK")  # Optional docker network to attach
            enable_host_port = os.getenv("IDE_ENABLE_HOST_PORT", "false").lower() == "true"
            host_port = None
            if enable_host_port:
                host_port = self._allocate_ephemeral_port()

            # Pull the image with error handling
            code_server_image = await self._pull_image_with_fallback(code_server_image)

            # Container configuration with resource limits and security
            container_config = {
                "image": code_server_image,
                "name": container_name,
                # Run code-server bound to all interfaces, no auth (secured by backend proxy)
                "command": f"code-server --bind-addr 0.0.0.0:{internal_port} --auth none /workspace",
                "detach": True,
                "tty": True,
                "stdin_open": True,
                "working_dir": "/workspace",
                "volumes": {
                    volume_name: {"bind": "/workspace", "mode": "rw"}
                },
                "environment": {
                    "PYTHONUNBUFFERED": "1",
                    "DEBIAN_FRONTEND": "noninteractive",
                    "TERM": "xterm-256color"
                },
                "mem_limit": "2g",  # 2GB RAM limit
                "nano_cpus": int(1.5 * 1e9),  # 1.5 CPU cores
                "pids_limit": 512,  # Prevent fork bombs
                "security_opt": ["no-new-privileges:true"],  # Security hardening
                "labels": {
                    "app": "vibecode",
                    "user_id": str(user_id),
                    "session_id": session_id,
                    "created_at": datetime.now().isoformat(),
                    "volume_name": volume_name,
                    "vibecode_internal_port": str(internal_port),
                    "vibecode_host_port": str(host_port or "")
                }
            }

            # Publish host port if enabled
            if enable_host_port and host_port:
                container_config["ports"] = {f"{internal_port}/tcp": ("127.0.0.1", host_port)}

            # Attach to base compose network at create time if provided
            if base_network:
                container_config["network"] = base_network
            
            # Create and start container
            start_time = time.time()
            container = self.docker_client.containers.run(**container_config)
            creation_time = time.time() - start_time
            
            logger.info(f"✅ Container created in {creation_time:.2f}s: {container_name}")
            
            # Verify container started successfully
            container.reload()
            if container.status != "running":
                raise Exception(f"Container failed to start: {container.status}")
            
            # Store container info
            container_info = ContainerInfo(
                container_id=container.id,
                container_name=container_name,
                session_id=session_id,
                user_id=user_id,
                volume_name=volume_name,
                status="running"
            )
            self.active_containers[session_id] = container_info
            
            return container_info
            
        except docker.errors.APIError as e:
            logger.error(f"❌ Docker API error creating container: {e}")
            raise HTTPException(status_code=500, detail=f"Docker error: {str(e)}")
        except Exception as e:
            logger.error(f"❌ Failed to create container: {e}")
            raise HTTPException(status_code=500, detail=f"Container creation failed: {str(e)}")
    
    async def get_container(self, session_id: str) -> Optional[docker.models.containers.Container]:
        """Get container by session ID
        
        Args:
            session_id: Session identifier
            
        Returns:
            Docker container object or None if not found
        """
        if not self.docker_client:
            return None
        
        # Check if we have it tracked
        if session_id in self.active_containers:
            try:
                container_info = self.active_containers[session_id]
                container = self.docker_client.containers.get(container_info.container_id)
                
                # Update last activity
                container_info.last_activity = datetime.now()
                
                return container
            except docker.errors.NotFound:
                # Container was removed externally
                logger.warning(f"⚠️ Tracked container not found: {session_id}")
                del self.active_containers[session_id]
            except Exception as e:
                logger.error(f"❌ Error getting tracked container: {e}")
        
        # Try to find by label
        try:
            containers = self.docker_client.containers.list(
                all=True,
                filters={"label": f"session_id={session_id}"}
            )
            
            if containers:
                container = containers[0]
                logger.info(f"🔄 Found untracked container for session: {session_id}")
                
                # Add to tracking
                volume_name = container.labels.get("volume_name", "")
                user_id = container.labels.get("user_id", "unknown")
                
                container_info = ContainerInfo(
                    container_id=container.id,
                    container_name=container.name,
                    session_id=session_id,
                    user_id=user_id,
                    volume_name=volume_name,
                    status=container.status
                )
                self.active_containers[session_id] = container_info
                
                return container
        except Exception as e:
            logger.error(f"❌ Error finding container by label: {e}")
        
        return None

    async def get_runner_container(self, session_id: str) -> Optional[docker.models.containers.Container]:
        """Get runner container (python/node tools) by session ID"""
        if not self.docker_client:
            return None

        # Check tracked runner container
        if session_id in self.active_runner_containers:
            try:
                info = self.active_runner_containers[session_id]
                container = self.docker_client.containers.get(info.container_id)
                info.last_activity = datetime.now()
                return container
            except docker.errors.NotFound:
                logger.warning(f"⚠️ Tracked runner container not found: {session_id}")
                del self.active_runner_containers[session_id]
            except Exception as e:
                logger.error(f"❌ Error getting tracked runner container: {e}")

        # Find by labels
        try:
            containers = self.docker_client.containers.list(
                all=True,
                filters={"label": [f"session_id={session_id}", "runner=true"]}
            )
            if containers:
                container = containers[0]
                logger.info(f"🔄 Found untracked runner container for session: {session_id}")
                user_id = container.labels.get("user_id", "unknown")
                volume_name = container.labels.get("volume_name", "")
                info = ContainerInfo(
                    container_id=container.id,
                    container_name=container.name,
                    session_id=session_id,
                    user_id=user_id,
                    volume_name=volume_name,
                    status=container.status
                )
                self.active_runner_containers[session_id] = info
                return container
        except Exception as e:
            logger.error(f"❌ Error finding runner container by label: {e}")

        return None

    async def create_runner_container(self, session_id: str, user_id: str) -> ContainerInfo:
        """Create per-session runner container with Python/Node tools.

        - Image: VIBECODING_RUNNER_IMAGE (default python:3.11-slim)
        - Mounts the same /workspace volume as the IDE container
        - Command sleeps indefinitely to keep container up for exec/terminal
        """
        if not self.docker_client:
            raise HTTPException(status_code=503, detail="Docker service unavailable")

        # Determine shared volume and network from IDE container
        ide_info = self.active_containers.get(session_id)
        volume_name = ide_info.volume_name if ide_info else f"vibecode-{user_id}-{session_id}-ws"
        base_network = os.getenv("IDE_BASE_NETWORK")

        # Pull runner image (node:18-bullseye-slim has Node.js + we'll add Python during creation)
        runner_image = os.getenv("VIBECODING_RUNNER_IMAGE", "node:18-bullseye-slim")
        try:
            logger.info(f"🔄 Pulling runner image: {runner_image}")
            self.docker_client.images.pull(runner_image)
        except Exception as e:
            logger.error(f"❌ Failed to pull runner image {runner_image}: {e}")
            raise HTTPException(status_code=500, detail=f"Runner image pull failed: {e}")

        # Ensure volume exists
        await self._ensure_volume(volume_name)

        # Reuse if exists
        runner_name = f"vibecode-runner-{user_id}-{session_id}"
        existing = await self._find_existing_container(runner_name)
        if existing:
            logger.info(f"🔄 Runner container already exists: {runner_name}")
            # Ensure running
            if existing.status == "exited":
                existing.start()
            info = ContainerInfo(
                container_id=existing.id,
                container_name=existing.name,
                session_id=session_id,
                user_id=user_id,
                volume_name=volume_name,
                status=existing.status
            )
            self.active_runner_containers[session_id] = info
            return info

        # Create runner container
        try:
            config = {
                "image": runner_image,
                "name": runner_name,
                "command": "sleep infinity",
                "detach": True,
                "tty": True,
                "stdin_open": True,
                "working_dir": "/workspace",
                "volumes": { volume_name: {"bind": "/workspace", "mode": "rw"} },
                "environment": {
                    "PYTHONUNBUFFERED": "1",
                    "DEBIAN_FRONTEND": "noninteractive",
                    "TERM": "xterm-256color"
                },
                "labels": {
                    "app": "vibecode",
                    "runner": "true",
                    "user_id": str(user_id),
                    "session_id": session_id,
                    "volume_name": volume_name,
                    "created_at": datetime.now().isoformat()
                }
            }
            if base_network:
                config["network"] = base_network

            container = self.docker_client.containers.run(**config)
            container.reload()
            
            # Install Python in node:18-bullseye-slim runner
            if runner_image == "node:18-bullseye-slim":
                logger.info(f"🐍 Installing Python in runner container")
                try:
                    container.exec_run("apt-get update -q -y")
                    container.exec_run("apt-get install -y -q python3 python3-pip build-essential")
                    logger.info("✅ Python and build tools installed successfully")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to install Python (non-critical): {e}")
            
            # Fix workspace permissions to be writable
            logger.info(f"🔧 Fixing workspace permissions in new runner container")
            try:
                fix_perms_cmd = "sh -c 'chmod -R 777 /workspace 2>/dev/null || true'"
                container.exec_run(fix_perms_cmd)
            except Exception as e:
                logger.warning(f"⚠️ Failed to fix permissions (non-critical): {e}")
            
            info = ContainerInfo(
                container_id=container.id,
                container_name=container.name,
                session_id=session_id,
                user_id=user_id,
                volume_name=volume_name,
                status=container.status
            )
            self.active_runner_containers[session_id] = info
            logger.info(f"✅ Runner container created: {runner_name}")
            return info
        except Exception as e:
            logger.error(f"❌ Failed to create runner container: {e}")
            raise HTTPException(status_code=500, detail=f"Runner container creation failed: {e}")

    async def ensure_runner_ready(self, session_id: str, user_id: str) -> bool:
        """Ensure runner container exists and passes readiness probes."""
        info = self.active_runner_containers.get(session_id)
        if not info:
            info = await self.create_runner_container(session_id, user_id)

        container = await self.get_runner_container(session_id)
        if not container:
            return False

        # Probes: workspace writable, python present, echo works
        try:
            # Workspace write probe
            probe_cmd = "sh -lc 'touch /workspace/.probe && rm -f /workspace/.probe'"
            res = container.exec_run(probe_cmd)
            if res.exit_code != 0:
                logger.error(f"❌ Runner probe failed (workspace): {res.output}")
                return False

            # Python present probe
            py_cmd = "sh -lc 'command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1'"
            res = container.exec_run(py_cmd)
            if res.exit_code != 0:
                logger.warning("⚠️ Python interpreter not found in runner")
                # Still considered ready for non-python commands

            # Echo test
            echo_cmd = "sh -lc 'echo test'"
            res = container.exec_run(echo_cmd)
            if res.exit_code != 0:
                logger.error(f"❌ Runner probe failed (echo): {res.output}")
                return False

            return True
        except Exception as e:
            logger.error(f"❌ Runner readiness probes failed: {e}")
            return False

    def _allocate_ephemeral_port(self) -> int:
        """Find an available host TCP port for publishing the code-server service.

        Respects optional IDE_PORT_RANGE_START/END; falls back to OS-allocated socket.
        """
        start = int(os.getenv("IDE_PORT_RANGE_START", "10050"))
        end = int(os.getenv("IDE_PORT_RANGE_END", "10150"))
        for port in range(start, end + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        # Fallback: let OS pick a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    async def _pull_image_with_fallback(self, image: str) -> str:
        """Pull Docker image with fallback logic and proper error handling"""
        try:
            logger.info(f"🔄 Pulling image: {image}")
            self.docker_client.images.pull(image)
            logger.info(f"✅ Successfully pulled image: {image}")
            return image
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Failed to pull image {image}: {error_msg}")
            
            # Check if it's a GHCR image and try fallback
            if image.startswith("ghcr.io/coder/code-server"):
                fallback_image = "lscr.io/linuxserver/code-server:latest"
                logger.info(f"🔄 Trying fallback image: {fallback_image}")
                try:
                    self.docker_client.images.pull(fallback_image)
                    logger.info(f"✅ Successfully pulled fallback image: {fallback_image}")
                    return fallback_image
                except Exception as fallback_error:
                    logger.error(f"❌ Fallback image also failed: {fallback_error}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Docker pull failed for both {image} and {fallback_image}. "
                               f"Please check VIBECODING_IDE_IMAGE environment variable. "
                               f"Original error: {error_msg}"
                    )
            else:
                # For non-GHCR images, provide specific error message
                if "pull access denied" in error_msg.lower():
                    raise HTTPException(
                        status_code=500,
                        detail=f"IDE image not found or access denied: {image}. "
                               f"Please set VIBECODING_IDE_IMAGE to a valid image like "
                               f"'ghcr.io/coder/code-server:4.104.3' or 'lscr.io/linuxserver/code-server:latest'"
                    )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Docker pull failed for {image}: {error_msg}"
                    )
    
    async def start_container(self, session_id: str) -> bool:
        """Start a stopped container
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if started successfully, False otherwise
        """
        container = await self.get_container(session_id)
        if not container:
            logger.warning(f"⚠️ Container not found for session: {session_id}")
            return False
        
        try:
            if container.status == "running":
                logger.info(f"✅ Container already running: {session_id}")
                return True
            
            logger.info(f"▶️ Starting container: {session_id}")
            container.start()
            
            # Update tracking
            if session_id in self.active_containers:
                self.active_containers[session_id].status = "running"
                self.active_containers[session_id].last_activity = datetime.now()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start container: {e}")
            return False
    
    async def stop_container(self, session_id: str) -> bool:
        """Stop a running container (preserves volume)
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if stopped successfully, False otherwise
        """
        container = await self.get_container(session_id)
        if not container:
            logger.warning(f"⚠️ Container not found for session: {session_id}")
            return False
        
        try:
            if container.status == "exited":
                logger.info(f"✅ Container already stopped: {session_id}")
                return True
            
            logger.info(f"⏸️ Stopping container: {session_id}")
            container.stop(timeout=10)
            
            # Update tracking
            if session_id in self.active_containers:
                self.active_containers[session_id].status = "stopped"
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to stop container: {e}")
            return False
    
    async def execute_command(
        self, 
        session_id: str, 
        command: str, 
        workdir: str = "/workspace"
    ) -> ExecutionResult:
        """Execute a command in the container
        
        Args:
            session_id: Session identifier
            command: Command to execute
            workdir: Working directory (default: /workspace)
            
        Returns:
            ExecutionResult with command output and timing
            
        Raises:
            HTTPException: If container not found
        """
        # Prefer executing in runner container if available
        container = await self.get_runner_container(session_id)
        if not container:
            container = await self.get_container(session_id)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        
        try:
            start_time = time.time()
            
            # Execute with demux to separate stdout/stderr
            result = container.exec_run(
                command,
                workdir=workdir,
                demux=True
            )
            
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Decode output
            stdout_bytes, stderr_bytes = result.output
            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            
            return ExecutionResult(
                command=command,
                stdout=stdout,
                stderr=stderr,
                exit_code=result.exit_code,
                execution_time_ms=execution_time_ms
            )
            
        except Exception as e:
            logger.error(f"❌ Command execution failed: {e}")
            return ExecutionResult(
                command=command,
                stdout="",
                stderr=f"Error: {str(e)}",
                exit_code=-1,
                execution_time_ms=0
            )
    
    async def cleanup_inactive_containers(
        self, 
        timeout: timedelta = timedelta(hours=2)
    ) -> int:
        """Clean up containers that have been inactive
        
        Stops containers that haven't been accessed for the specified timeout period.
        This helps free up system resources while preserving volumes for later reuse.
        
        Args:
            timeout: Inactivity timeout (default: 2 hours)
            
        Returns:
            Number of containers cleaned up
        """
        if not self.docker_client:
            return 0
        
        current_time = datetime.now()
        cleaned_up = 0
        to_cleanup = []
        
        # Find inactive containers in tracked list
        for session_id, info in list(self.active_containers.items()):
            if info.status == "running" and current_time - info.last_activity > timeout:
                to_cleanup.append(session_id)
                logger.info(f"🧹 Found inactive container: {session_id} (last activity: {info.last_activity})")
        
        # Also check for untracked vibecode containers
        try:
            all_containers = self.docker_client.containers.list(
                all=True,
                filters={"label": "app=vibecode"}
            )
            
            for container in all_containers:
                session_id = container.labels.get("session_id")
                if session_id and session_id not in self.active_containers:
                    # Check container age
                    created_at_str = container.labels.get("created_at")
                    if created_at_str:
                        try:
                            created_at = datetime.fromisoformat(created_at_str)
                            if current_time - created_at > timeout and container.status == "running":
                                to_cleanup.append(session_id)
                                logger.info(f"🧹 Found untracked inactive container: {session_id}")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not parse created_at for {session_id}: {e}")
        except Exception as e:
            logger.error(f"❌ Error listing containers for cleanup: {e}")
        
        # Clean up each inactive container
        for session_id in to_cleanup:
            try:
                logger.info(f"🧹 Stopping inactive container: {session_id}")
                if await self.stop_container(session_id):
                    cleaned_up += 1
            except Exception as e:
                logger.error(f"❌ Failed to cleanup container {session_id}: {e}")
        
        if cleaned_up > 0:
            logger.info(f"✅ Cleaned up {cleaned_up} inactive containers")
        
        return cleaned_up
    
    async def start_cleanup_task(self, interval_minutes: int = 30):
        """Start background task to cleanup inactive containers
        
        Args:
            interval_minutes: How often to run cleanup (default: 30 minutes)
        """
        if self._cleanup_running:
            logger.warning("⚠️ Cleanup task already running")
            return
        
        self._cleanup_running = True
        logger.info(f"🚀 Starting container cleanup task (interval: {interval_minutes}m)")
        
        async def cleanup_loop():
            while self._cleanup_running:
                try:
                    await asyncio.sleep(interval_minutes * 60)
                    logger.info("🧹 Running scheduled container cleanup...")
                    cleaned = await self.cleanup_inactive_containers()
                    if cleaned > 0:
                        logger.info(f"✅ Cleanup completed: {cleaned} containers stopped")
                except asyncio.CancelledError:
                    logger.info("🛑 Cleanup task cancelled")
                    break
                except Exception as e:
                    logger.error(f"❌ Error in cleanup task: {e}")
        
        self._cleanup_task = asyncio.create_task(cleanup_loop())
    
    async def stop_cleanup_task(self):
        """Stop the background cleanup task"""
        if self._cleanup_task and self._cleanup_running:
            logger.info("🛑 Stopping container cleanup task")
            self._cleanup_running = False
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    # Private helper methods
    
    async def _find_existing_container(self, container_name: str):
        """Find existing container by name"""
        try:
            return self.docker_client.containers.get(container_name)
        except docker.errors.NotFound:
            return None
        except Exception as e:
            logger.error(f"❌ Error finding container: {e}")
            return None
    
    async def _handle_existing_container(
        self, 
        container, 
        session_id: str, 
        user_id: str, 
        volume_name: str
    ) -> ContainerInfo:
        """Handle existing container (start if stopped)"""
        if container.status == "exited":
            logger.info(f"▶️ Starting existing container: {container.name}")
            container.start()
        
        # Create container info
        container_info = ContainerInfo(
            container_id=container.id,
            container_name=container.name,
            session_id=session_id,
            user_id=user_id,
            volume_name=volume_name,
            status=container.status
        )
        self.active_containers[session_id] = container_info
        
        return container_info
    
    async def _ensure_volume(self, volume_name: str):
        """Create volume if it doesn't exist"""
        try:
            volume = self.docker_client.volumes.get(volume_name)
            logger.info(f"📦 Using existing volume: {volume_name}")
            return volume
        except docker.errors.NotFound:
            logger.info(f"📦 Creating new volume: {volume_name}")
            return self.docker_client.volumes.create(name=volume_name)
        except Exception as e:
            logger.error(f"❌ Volume error: {e}")
            raise


# Global container manager instance
container_manager = ContainerManager()


def get_container_manager() -> ContainerManager:
    """Dependency to get container manager instance"""
    return container_manager


# Request/Response Models

class CreateContainerRequest(BaseModel):
    session_id: str
    user_id: str
    template: str = "base"


class ContainerStatusResponse(BaseModel):
    session_id: str
    container_id: str
    container_name: str
    status: str
    created_at: str


class ExecuteCommandRequest(BaseModel):
    session_id: str
    command: str
    workdir: str = "/workspace"


# API Endpoints

@router.post("/api/vibecode/container/create")
async def create_container_endpoint(
    req: CreateContainerRequest,
    current_user: dict = Depends(get_current_user)
):
    """Create a new development container for a VibeCode session
    
    Creates a Docker container with:
    - Resource limits (2GB RAM, 1.5 CPU)
    - Security options (no-new-privileges)
    - Persistent volume for /workspace
    - Proper labeling for discovery
    - Automatic legacy Colab file migration on first open
    """
    # Import migration functions
    from vibecoding.migration import (
        check_migration_needed,
        migrate_legacy_colab_files,
        mark_migration_complete
    )
    
    # Verify user owns this session
    if str(current_user["id"]) != req.user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    container_info = await container_manager.create_container(
        session_id=req.session_id,
        user_id=req.user_id,
        template=req.template
    )
    
    # Check if migration is needed (for existing volumes being attached to new containers)
    migration_result = None
    try:
        needs_migration = await check_migration_needed(
            container_manager,
            req.session_id
        )
        
        if needs_migration:
            logger.info(f"🔄 Running legacy Colab migration for session {req.session_id}")
            migration_result = await migrate_legacy_colab_files(
                container_manager,
                req.session_id
            )
            
            # Mark migration as complete
            await mark_migration_complete(
                container_manager,
                req.session_id
            )
            
            logger.info(f"✅ Migration completed: {migration_result.get('total_count', 0)} files migrated")
    except Exception as e:
        logger.warning(f"⚠️ Migration check/execution failed: {e}")
        # Don't fail the create operation if migration fails
    
    response = {
        "session_id": container_info.session_id,
        "container_id": container_info.container_id,
        "container_name": container_info.container_name,
        "status": container_info.status,
        "volume_name": container_info.volume_name,
        "workspace_path": "/workspace"
    }
    
    # Include migration info if it occurred
    if migration_result:
        response["migration"] = migration_result
    
    return response


@router.get("/api/vibecode/container/{session_id}/status")
async def get_container_status(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get container status for a session"""
    try:
        container = await container_manager.get_container(session_id)
        
        if not container:
            # Return a default status instead of 404
            return {
                "session_id": session_id,
                "container_id": None,
                "container_name": None,
                "status": "not_created",
                "created_at": "",
                "message": "Container not created yet"
            }
        
        # Verify user owns this session
        user_id_label = container.labels.get("user_id")
        if user_id_label and str(current_user["id"]) != user_id_label:
            raise HTTPException(status_code=403, detail="Unauthorized")
        
        container.reload()
        
        return {
            "session_id": session_id,
            "container_id": container.id,
            "container_name": container.name,
            "status": container.status,
            "created_at": container.labels.get("created_at", "")
        }
    except Exception as e:
        logger.error(f"Error getting container status for {session_id}: {e}")
        # Return a safe default status
        return {
            "session_id": session_id,
            "container_id": None,
            "container_name": None,
            "status": "error",
            "created_at": "",
            "message": f"Error checking container status: {str(e)}"
        }


@router.post("/api/vibecode/container/{session_id}/start")
async def start_container_endpoint(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Start a stopped container and run migration if needed"""
    # Import migration functions
    from vibecoding.migration import (
        check_migration_needed,
        migrate_legacy_colab_files,
        mark_migration_complete
    )
    
    # Verify ownership
    container = await container_manager.get_container(session_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")
    
    user_id_label = container.labels.get("user_id")
    if user_id_label and str(current_user["id"]) != user_id_label:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    success = await container_manager.start_container(session_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to start container")
    
    # Check if migration is needed (first time opening session)
    migration_result = None
    try:
        needs_migration = await check_migration_needed(
            container_manager,
            session_id
        )
        
        if needs_migration:
            logger.info(f"🔄 Running legacy Colab migration for session {session_id}")
            migration_result = await migrate_legacy_colab_files(
                container_manager,
                session_id
            )
            
            # Mark migration as complete
            await mark_migration_complete(
                container_manager,
                session_id
            )
            
            logger.info(f"✅ Migration completed: {migration_result.get('total_count', 0)} files migrated")
    except Exception as e:
        logger.warning(f"⚠️ Migration check/execution failed: {e}")
        # Don't fail the start operation if migration fails
    
    response = {
        "session_id": session_id,
        "status": "running",
        "message": "Container started successfully"
    }
    
    # Include migration info if it occurred
    if migration_result:
        response["migration"] = migration_result
    
    return response


@router.post("/api/vibecode/container/{session_id}/stop")
async def stop_container_endpoint(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Stop a running container (preserves volume)"""
    # Verify ownership
    container = await container_manager.get_container(session_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")
    
    user_id_label = container.labels.get("user_id")
    if user_id_label and str(current_user["id"]) != user_id_label:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    success = await container_manager.stop_container(session_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop container")
    
    return {
        "session_id": session_id,
        "status": "stopped",
        "message": "Container stopped successfully"
    }
