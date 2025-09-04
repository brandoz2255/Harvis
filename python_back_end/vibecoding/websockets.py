"""
WebSocket handler for interactive terminal sessions.

Provides real-time terminal access to development containers with:
- JSON message protocol and raw text fallback
- Per-user persistent volumes and containers
- Automatic container lifecycle management
- Authentication integration
- Resize support for responsive terminals
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Callable

from fastapi import WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.routing import APIRouter
import docker
from docker.errors import APIError, NotFound, ImageNotFound

from .models import get_current_user_websocket

logger = logging.getLogger(__name__)

router = APIRouter()

# Environment configuration
TERMINAL_IMAGE = os.getenv("TERMINAL_IMAGE", "python:3.12-alpine")
CONTAINERS_NETWORK = os.getenv("CONTAINERS_NETWORK", "")  # Optional network attachment
DOCKER_HOST = os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock")

# Active connections tracking
active_connections: Dict[str, WebSocket] = {}
container_sessions: Dict[str, Dict[str, Any]] = {}


class TerminalWebSocketManager:
    """Manages WebSocket connections and container sessions for terminal access."""

    def __init__(self):
        self.docker_client = None
        self._initialize_docker()

    def _initialize_docker(self):
        """Initialize Docker client with proper error handling."""
        try:
            self.docker_client = docker.from_env(timeout=30)
            # Test connection
            self.docker_client.ping()
            logger.info(f"Docker client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            self.docker_client = None

    async def connect(self, websocket: WebSocket, session_id: str, user_id: str):
        """Accept WebSocket connection and initialize terminal session."""
        await websocket.accept()
        
        connection_key = f"{user_id}:{session_id}"
        active_connections[connection_key] = websocket
        
        logger.info(f"WebSocket connected: user={user_id}, session={session_id}")
        
        try:
            # Initialize or reuse existing container session
            container_info = await self._ensure_container_session(user_id, session_id)
            
            # Send initial container status
            await self._send_message(websocket, {
                "type": "container_status",
                "status": container_info.get("status", "stopped"),
                "message": f"Container session initialized"
            })
            
            # Start terminal session in the container
            await self._start_terminal_session(websocket, container_info, user_id, session_id)
            
        except Exception as e:
            logger.error(f"Failed to initialize terminal session: {e}")
            await self._send_error(websocket, f"Failed to initialize terminal: {str(e)}")

    async def disconnect(self, session_id: str, user_id: str):
        """Clean up WebSocket connection."""
        connection_key = f"{user_id}:{session_id}"
        if connection_key in active_connections:
            del active_connections[connection_key]
        
        # Keep container running but cleanup exec sessions
        if connection_key in container_sessions:
            session_info = container_sessions[connection_key]
            if "exec_id" in session_info:
                try:
                    # Gracefully terminate exec session
                    exec_instance = session_info["exec_id"]
                    # Note: Docker API doesn't provide direct way to kill exec,
                    # it will be cleaned up when container stops
                except Exception as e:
                    logger.warning(f"Failed to cleanup exec session: {e}")
        
        logger.info(f"WebSocket disconnected: user={user_id}, session={session_id}")

    async def _ensure_container_session(self, user_id: str, session_id: str) -> Dict[str, Any]:
        """Ensure container and volume exist for the user session."""
        if not self.docker_client:
            raise RuntimeError("Docker client not available")

        connection_key = f"{user_id}:{session_id}"
        
        # Check if session already exists
        if connection_key in container_sessions:
            container_info = container_sessions[connection_key]
            try:
                container = self.docker_client.containers.get(container_info["container_id"])
                if container.status == "running":
                    return container_info
            except NotFound:
                # Container was removed, create new one
                pass

        # Create or reuse volume
        volume_name = f"vibe-ws-{user_id}"
        try:
            volume = self.docker_client.volumes.get(volume_name)
        except NotFound:
            volume = self.docker_client.volumes.create(
                name=volume_name,
                labels={
                    "app": "harvis",
                    "role": "terminal",
                    "user": str(user_id)
                }
            )
            logger.info(f"Created volume: {volume_name}")

        # Create container
        container_name = f"vibe-{user_id}-{session_id}"
        
        # Prepare container configuration
        container_config = {
            "image": TERMINAL_IMAGE,
            "name": container_name,
            "detach": True,
            "tty": True,
            "stdin_open": True,
            "working_dir": "/workspace",
            "volumes": {volume.name: {"bind": "/workspace", "mode": "rw"}},
            "labels": {
                "app": "harvis",
                "role": "terminal",
                "user": str(user_id),
                "session": session_id
            },
            "environment": {
                "TERM": "xterm-256color",
                "USER": "developer"
            },
            "command": ["/bin/sh"]
        }

        # Add network if specified
        if CONTAINERS_NETWORK:
            container_config["network"] = CONTAINERS_NETWORK

        try:
            # Remove existing container if it exists
            try:
                existing = self.docker_client.containers.get(container_name)
                existing.remove(force=True)
                logger.info(f"Removed existing container: {container_name}")
            except NotFound:
                pass

            # Create and start new container
            container = self.docker_client.containers.run(**container_config)
            logger.info(f"Created container: {container_name}")

            container_info = {
                "container_id": container.id,
                "container_name": container_name,
                "volume_name": volume_name,
                "status": "running"
            }
            
            container_sessions[connection_key] = container_info
            return container_info

        except (APIError, ImageNotFound) as e:
            logger.error(f"Failed to create container: {e}")
            raise RuntimeError(f"Container creation failed: {str(e)}")

    async def _start_terminal_session(self, websocket: WebSocket, container_info: Dict[str, Any], user_id: str, session_id: str):
        """Start interactive shell session in the container."""
        if not self.docker_client:
            return

        connection_key = f"{user_id}:{session_id}"
        
        try:
            container = self.docker_client.containers.get(container_info["container_id"])
            
            # Create exec instance for interactive shell
            exec_instance = self.docker_client.api.exec_create(
                container.id,
                ["/bin/sh"],
                stdout=True,
                stderr=True,
                stdin=True,
                tty=True
            )
            
            exec_socket = self.docker_client.api.exec_start(
                exec_instance["Id"],
                detach=False,
                tty=True,
                stream=True,
                socket=True
            )
            
            # Store exec info
            if connection_key in container_sessions:
                container_sessions[connection_key]["exec_id"] = exec_instance["Id"]
                container_sessions[connection_key]["socket"] = exec_socket

            # Start reading from container in background
            asyncio.create_task(
                self._read_container_output(websocket, exec_socket, user_id, session_id)
            )

        except Exception as e:
            logger.error(f"Failed to start terminal session: {e}")
            await self._send_error(websocket, f"Failed to start terminal: {str(e)}")

    async def _read_container_output(self, websocket: WebSocket, socket, user_id: str, session_id: str):
        """Read output from container and send to WebSocket."""
        connection_key = f"{user_id}:{session_id}"
        
        try:
            while connection_key in active_connections:
                try:
                    # Read data from socket with timeout
                    data = socket._sock.recv(4096)
                    if not data:
                        break
                        
                    # Send as structured message
                    await self._send_message(websocket, {
                        "type": "output",
                        "data": data.decode("utf-8", errors="replace")
                    })
                    
                except Exception as e:
                    if connection_key in active_connections:
                        logger.error(f"Error reading container output: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"Container output reader failed: {e}")
        finally:
            try:
                socket.close()
            except:
                pass

    async def handle_message(self, websocket: WebSocket, data: str, user_id: str, session_id: str):
        """Handle incoming WebSocket message."""
        connection_key = f"{user_id}:{session_id}"
        
        try:
            # Try to parse as JSON first
            try:
                message = json.loads(data)
                msg_type = message.get("type", "")
                
                if msg_type == "stdin":
                    await self._handle_stdin(message.get("data", ""), user_id, session_id)
                elif msg_type == "resize":
                    await self._handle_resize(
                        message.get("cols", 80),
                        message.get("rows", 24),
                        user_id,
                        session_id
                    )
                else:
                    logger.warning(f"Unknown message type: {msg_type}")
                    
            except json.JSONDecodeError:
                # Fallback: treat as raw stdin
                await self._handle_stdin(data, user_id, session_id)
                
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
            await self._send_error(websocket, f"Message handling failed: {str(e)}")

    async def _handle_stdin(self, data: str, user_id: str, session_id: str):
        """Send input data to container terminal."""
        connection_key = f"{user_id}:{session_id}"
        
        if connection_key not in container_sessions:
            return
            
        session_info = container_sessions[connection_key]
        socket = session_info.get("socket")
        
        if socket:
            try:
                socket._sock.send(data.encode("utf-8"))
            except Exception as e:
                logger.error(f"Failed to send stdin: {e}")

    async def _handle_resize(self, cols: int, rows: int, user_id: str, session_id: str):
        """Handle terminal resize."""
        connection_key = f"{user_id}:{session_id}"
        
        if connection_key not in container_sessions:
            return
            
        session_info = container_sessions[connection_key]
        exec_id = session_info.get("exec_id")
        
        if exec_id and self.docker_client:
            try:
                self.docker_client.api.exec_resize(exec_id, height=rows, width=cols)
                logger.debug(f"Terminal resized: {cols}x{rows}")
            except Exception as e:
                logger.error(f"Failed to resize terminal: {e}")

    async def _send_message(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send structured message to WebSocket."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {e}")

    async def _send_error(self, websocket: WebSocket, error_message: str):
        """Send error message to WebSocket."""
        await self._send_message(websocket, {
            "type": "error",
            "message": error_message
        })

    def cleanup_user_resources(self, user_id: str):
        """Cleanup containers and volumes for a user (optional maintenance)."""
        if not self.docker_client:
            return

        try:
            # Find and clean up containers
            containers = self.docker_client.containers.list(
                all=True,
                filters={"label": [f"app=harvis", f"user={user_id}"]}
            )
            
            for container in containers:
                try:
                    container.remove(force=True)
                    logger.info(f"Cleaned up container: {container.name}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup container {container.name}: {e}")

        except Exception as e:
            logger.error(f"Failed to cleanup user resources: {e}")


# Global manager instance
manager = TerminalWebSocketManager()


@router.websocket("/terminal/{session_id}")
async def websocket_terminal(
    websocket: WebSocket,
    session_id: str,
    current_user: dict = Depends(get_current_user_websocket)
):
    """WebSocket endpoint for terminal access."""
    user_id = current_user.get("user_id", current_user.get("id", "dev"))
    
    try:
        await manager.connect(websocket, session_id, str(user_id))
        
        while True:
            try:
                data = await websocket.receive_text()
                await manager.handle_message(websocket, data, str(user_id), session_id)
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await manager._send_error(websocket, str(e))
                break
                
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        await manager.disconnect(session_id, str(user_id))

@router.websocket("/fs/{session_id}")
async def websocket_fs_watcher(
    websocket: WebSocket,
    session_id: str,
    current_user: dict = Depends(get_current_user_websocket)
):
    """WebSocket endpoint for filesystem monitoring."""
    from vibecoding.session_lifecycle import session_manager
    
    try:
        await websocket.accept()
        
        # SESSION GUARD: Check if session is ready
        if not session_manager.is_session_ready(session_id):
            logger.warning(f"FS watcher requested for non-running session {session_id}")
            await websocket.send_json({
                "type": "error",
                "error": "Session not ready",
                "message": "Session must be in 'running' state before filesystem monitoring",
                "session_id": session_id
            })
            await websocket.close(code=4100, reason="Session not running")  # 410 Gone equivalent
            return
        
        # Register with session manager for updates
        await session_manager.register_websocket(session_id, websocket)
        
        user_id = str(current_user.get("user_id", current_user.get("id", "dev")))
        logger.info(f"FS watcher connected for session {session_id}, user {user_id}")
        
        # Send initial status
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "message": "Filesystem watcher connected"
        })
        
        # Get container for filesystem monitoring
        from vibecoding.containers import container_manager
        container = await container_manager.get_container(session_id)
        
        if not container:
            await websocket.send_json({
                "type": "error",
                "error": "Container not found",
                "session_id": session_id
            })
            await websocket.close(code=4040, reason="Container not found")  # 404 equivalent
            return
        
        # Track last known state for diff detection
        last_snapshot = {}
        
        # Main monitoring loop
        while True:
            try:
                # Check if session is still ready
                if not session_manager.is_session_ready(session_id):
                    await websocket.send_json({
                        "type": "session_stopped",
                        "session_id": session_id,
                        "message": "Session is no longer running"
                    })
                    break
                
                # Get current directory snapshot
                try:
                    result = container.exec_run("ls -la /workspace", workdir="/workspace")
                    if result.exit_code == 0:
                        current_snapshot = result.output.decode("utf-8").strip()
                        
                        # Check if anything changed
                        if current_snapshot != last_snapshot.get("workspace", ""):
                            # Parse and send file changes
                            files = []
                            lines = current_snapshot.split("\n")
                            
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
                                                "path": f"/workspace/{name}"
                                            })
                            
                            # Send filesystem update
                            await websocket.send_json({
                                "type": "fs_update",
                                "session_id": session_id,
                                "path": "/workspace",
                                "files": files,
                                "timestamp": datetime.now().isoformat()
                            })
                            
                            last_snapshot["workspace"] = current_snapshot
                
                except Exception as e:
                    logger.warning(f"Error getting fs snapshot for {session_id}: {e}")
                
                # Wait before next check
                await asyncio.sleep(2.0)  # Check every 2 seconds
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"FS watcher error: {e}")
                await websocket.send_json({
                    "type": "error", 
                    "error": str(e),
                    "session_id": session_id
                })
                break
    
    except Exception as e:
        logger.error(f"FS watcher connection error: {e}")
    finally:
        # Unregister from session manager
        try:
            await session_manager.unregister_websocket(session_id, websocket)
        except:
            pass
        logger.info(f"FS watcher disconnected for session {session_id}")


@router.get("/health")
async def websocket_health():
    """WebSocket service health check."""
    try:
        if manager.docker_client:
            manager.docker_client.ping()
            docker_status = "healthy"
        else:
            docker_status = "unavailable"
            
        return {
            "status": "healthy" if docker_status == "healthy" else "degraded",
            "docker": docker_status,
            "active_connections": len(active_connections),
            "active_sessions": len(container_sessions)
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "docker": "error",
            "error": str(e),
            "active_connections": len(active_connections),
            "active_sessions": len(container_sessions)
        }