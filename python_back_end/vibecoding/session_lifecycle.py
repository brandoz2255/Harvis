"""
Session Lifecycle Management

Provides robust session state management with Docker integration,
preventing blocking operations and ensuring consistent state across
frontend connections, WebSocket endpoints, and file operations.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional, Any, Set
from dataclasses import dataclass, asdict
import docker
from threading import Lock
import weakref

logger = logging.getLogger(__name__)

class SessionState(Enum):
    """Session states for lifecycle management"""
    STOPPED = "stopped"
    STARTING = "starting" 
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"

@dataclass
class SessionInfo:
    """Complete session information"""
    session_id: str
    state: SessionState
    container_exists: bool
    volume_exists: bool
    container_id: Optional[str] = None
    volume_name: Optional[str] = None
    last_ready_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    error_message: Optional[str] = None
    user_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        result = asdict(self)
        # Convert datetime objects to ISO strings
        for key in ['last_ready_at', 'created_at']:
            if result[key]:
                result[key] = result[key].isoformat()
        # Convert enum to string
        result['state'] = result['state'].value
        return result

class SessionManager:
    """Manages session lifecycle with Docker integration"""
    
    def __init__(self):
        self._sessions: Dict[str, SessionInfo] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._background_tasks: Set[asyncio.Task] = set()
        self._websocket_connections: Dict[str, Set[weakref.ref]] = {}
        
        # Docker client setup
        try:
            self.docker_client = docker.from_env()
            logger.info("✅ SessionManager: Docker client initialized")
        except Exception as e:
            logger.error(f"❌ SessionManager: Docker client failed: {e}")
            self.docker_client = None
    
    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create lock for session"""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]
    
    async def get_session_status(self, session_id: str) -> SessionInfo:
        """Get current session status with Docker state check"""
        async with self._get_lock(session_id):
            if session_id not in self._sessions:
                # Initialize session info by checking Docker state
                await self._discover_session_state(session_id)
            
            session_info = self._sessions[session_id]
            
            # Refresh container state if it should be running
            if session_info.state in [SessionState.RUNNING, SessionState.STARTING]:
                await self._refresh_container_state(session_id, session_info)
            
            return session_info
    
    async def _discover_session_state(self, session_id: str) -> None:
        """Discover current state of session from Docker resources"""
        container_name = f"vibecoding_{session_id}"
        volume_name = f"vibecoding_{session_id}"
        
        container_exists = False
        container_id = None
        container_status = None
        
        # Check container
        if self.docker_client:
            try:
                container = self.docker_client.containers.get(container_name)
                container_exists = True
                container_id = container.id
                container.reload()
                container_status = container.status
                logger.info(f"📋 Found existing container {container_name}: {container_status}")
            except docker.errors.NotFound:
                logger.info(f"📋 No existing container found: {container_name}")
            except Exception as e:
                logger.warning(f"⚠️ Error checking container {container_name}: {e}")
        
        # Check volume
        volume_exists = False
        if self.docker_client:
            try:
                volume = self.docker_client.volumes.get(volume_name)
                volume_exists = True
                logger.info(f"📦 Found existing volume: {volume_name}")
            except docker.errors.NotFound:
                logger.info(f"📦 No existing volume found: {volume_name}")
            except Exception as e:
                logger.warning(f"⚠️ Error checking volume {volume_name}: {e}")
        
        # Determine initial state
        if container_exists and container_status == "running":
            state = SessionState.RUNNING
            last_ready_at = datetime.now()
        elif container_exists and container_status == "exited":
            state = SessionState.STOPPED
            last_ready_at = None
        elif container_exists:
            state = SessionState.STARTING  # Assume container is starting if in other states
            last_ready_at = None
        else:
            state = SessionState.STOPPED
            last_ready_at = None
        
        # Store session info
        self._sessions[session_id] = SessionInfo(
            session_id=session_id,
            state=state,
            container_exists=container_exists,
            volume_exists=volume_exists,
            container_id=container_id,
            volume_name=volume_name,
            last_ready_at=last_ready_at,
            created_at=datetime.now()
        )
    
    async def _refresh_container_state(self, session_id: str, session_info: SessionInfo) -> None:
        """Refresh container state from Docker"""
        if not self.docker_client or not session_info.container_id:
            return
        
        try:
            container = self.docker_client.containers.get(session_info.container_id)
            container.reload()
            
            if container.status == "running" and session_info.state != SessionState.RUNNING:
                session_info.state = SessionState.RUNNING
                session_info.last_ready_at = datetime.now()
                logger.info(f"✅ Container {session_id} is now running")
                
            elif container.status == "exited" and session_info.state == SessionState.RUNNING:
                session_info.state = SessionState.STOPPED
                session_info.last_ready_at = None
                logger.info(f"🛑 Container {session_id} has stopped")
                
        except docker.errors.NotFound:
            logger.warning(f"⚠️ Container {session_info.container_id} no longer exists")
            session_info.container_exists = False
            session_info.container_id = None
            session_info.state = SessionState.STOPPED
            session_info.last_ready_at = None
        except Exception as e:
            logger.error(f"❌ Error refreshing container state for {session_id}: {e}")
    
    async def start_session(self, session_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Start session with idempotent behavior and job-based execution"""
        async with self._get_lock(session_id):
            # Get current status
            session_info = await self.get_session_status(session_id)
            
            # If already running, return immediately
            if session_info.state == SessionState.RUNNING:
                logger.info(f"✅ Session {session_id} already running")
                return {"status": "already_running", "job_id": None}
            
            # If already starting, return job info
            if session_info.state == SessionState.STARTING:
                logger.info(f"⏳ Session {session_id} already starting")
                return {"status": "already_starting", "job_id": f"start_{session_id}"}
            
            # Mark as starting
            session_info.state = SessionState.STARTING
            session_info.error_message = None
            if user_id:
                session_info.user_id = user_id
            
            # Generate job ID
            job_id = f"start_{session_id}_{uuid.uuid4().hex[:8]}"
            
            # Start container in background
            task = asyncio.create_task(self._start_container_job(session_id, job_id))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            
            logger.info(f"🚀 Starting session {session_id} with job {job_id}")
            return {"status": "starting", "job_id": job_id}
    
    async def _start_container_job(self, session_id: str, job_id: str) -> None:
        """Background task to start container"""
        try:
            session_info = self._sessions[session_id]
            container_name = f"vibecoding_{session_id}"
            volume_name = f"vibecoding_{session_id}"
            
            if not self.docker_client:
                raise Exception("Docker client not available")
            
            # Create/ensure volume exists
            try:
                volume = self.docker_client.volumes.create(name=volume_name)
                logger.info(f"📦 Created volume: {volume_name}")
            except docker.errors.APIError as e:
                if "already exists" in str(e):
                    volume = self.docker_client.volumes.get(volume_name)
                    logger.info(f"📦 Using existing volume: {volume_name}")
                else:
                    raise
            
            session_info.volume_exists = True
            session_info.volume_name = volume_name
            
            # Create or start container
            container = None
            try:
                # Try to get existing container
                container = self.docker_client.containers.get(container_name)
                logger.info(f"🔄 Found existing container: {container_name}")
                
                if container.status == "exited":
                    container.start()
                    logger.info(f"▶️ Started existing container: {container_name}")
                elif container.status != "running":
                    # Container in unexpected state, remove and recreate
                    container.remove(force=True)
                    logger.info(f"🗑️ Removed container in state {container.status}: {container_name}")
                    container = None
            
            except docker.errors.NotFound:
                logger.info(f"🆕 No existing container found: {container_name}")
            
            # Create new container if needed
            if not container or container.status != "running":
                container_config = {
                    "image": "python:3.10-slim",
                    "name": container_name,
                    "detach": True,
                    "tty": True,
                    "stdin_open": True,
                    "working_dir": "/workspace",
                    "volumes": {volume_name: {"bind": "/workspace", "mode": "rw"}},
                    "environment": {
                        "PYTHONUNBUFFERED": "1",
                        "DEBIAN_FRONTEND": "noninteractive"
                    },
                    "network_mode": "bridge",
                    "labels": {
                        "vibecoding.session_id": session_id,
                        "vibecoding.user_id": session_info.user_id or "anonymous",
                        "vibecoding.created": datetime.now().isoformat(),
                        "vibecoding.job_id": job_id
                    }
                }
                
                container = self.docker_client.containers.run(**container_config)
                logger.info(f"🚀 Created new container: {container_name}")
            
            # Update session info
            async with self._get_lock(session_id):
                session_info.container_exists = True
                session_info.container_id = container.id
                session_info.state = SessionState.RUNNING
                session_info.last_ready_at = datetime.now()
                session_info.error_message = None
                
            logger.info(f"✅ Session {session_id} started successfully (job {job_id})")
            
            # Notify connected WebSocket clients
            await self._notify_websocket_clients(session_id, {
                "type": "session_ready",
                "session_id": session_id,
                "status": "running"
            })
            
        except Exception as e:
            logger.error(f"❌ Failed to start session {session_id} (job {job_id}): {e}")
            
            # Update session with error
            async with self._get_lock(session_id):
                if session_id in self._sessions:
                    self._sessions[session_id].state = SessionState.ERROR
                    self._sessions[session_id].error_message = str(e)
            
            # Notify WebSocket clients of error
            await self._notify_websocket_clients(session_id, {
                "type": "session_error", 
                "session_id": session_id,
                "error": str(e)
            })
    
    async def stop_session(self, session_id: str) -> Dict[str, Any]:
        """Stop session idempotently"""
        async with self._get_lock(session_id):
            session_info = await self.get_session_status(session_id)
            
            if session_info.state == SessionState.STOPPED:
                logger.info(f"✅ Session {session_id} already stopped")
                return {"status": "already_stopped"}
            
            if session_info.state == SessionState.STOPPING:
                logger.info(f"⏳ Session {session_id} already stopping")
                return {"status": "already_stopping"}
            
            # Mark as stopping
            session_info.state = SessionState.STOPPING
            
            try:
                if session_info.container_id and self.docker_client:
                    container = self.docker_client.containers.get(session_info.container_id)
                    container.stop(timeout=10)
                    logger.info(f"🛑 Stopped container for session {session_id}")
                
                # Update state
                session_info.state = SessionState.STOPPED
                session_info.last_ready_at = None
                
                # Close WebSocket connections
                await self._close_websocket_connections(session_id)
                
                logger.info(f"✅ Session {session_id} stopped successfully")
                return {"status": "stopped"}
                
            except Exception as e:
                logger.error(f"❌ Error stopping session {session_id}: {e}")
                session_info.state = SessionState.ERROR
                session_info.error_message = str(e)
                return {"status": "error", "error": str(e)}
    
    def is_session_ready(self, session_id: str) -> bool:
        """Quick check if session is ready for operations"""
        if session_id not in self._sessions:
            return False
        return self._sessions[session_id].state == SessionState.RUNNING
    
    async def register_websocket(self, session_id: str, websocket) -> None:
        """Register WebSocket connection for session updates"""
        if session_id not in self._websocket_connections:
            self._websocket_connections[session_id] = set()
        
        self._websocket_connections[session_id].add(weakref.ref(websocket))
        logger.info(f"📡 Registered WebSocket for session {session_id}")
    
    async def unregister_websocket(self, session_id: str, websocket) -> None:
        """Unregister WebSocket connection"""
        if session_id in self._websocket_connections:
            # Remove any matching weak references
            self._websocket_connections[session_id] = {
                ws_ref for ws_ref in self._websocket_connections[session_id] 
                if ws_ref() is not None and ws_ref() != websocket
            }
            logger.info(f"📡 Unregistered WebSocket for session {session_id}")
    
    async def _notify_websocket_clients(self, session_id: str, message: Dict[str, Any]) -> None:
        """Notify all WebSocket clients connected to session"""
        if session_id not in self._websocket_connections:
            return
        
        # Clean up dead references and send to active ones
        active_connections = set()
        for ws_ref in self._websocket_connections[session_id]:
            websocket = ws_ref()
            if websocket is not None:
                try:
                    await websocket.send_json(message)
                    active_connections.add(ws_ref)
                except Exception as e:
                    logger.warning(f"Failed to notify WebSocket client: {e}")
        
        self._websocket_connections[session_id] = active_connections
    
    async def _close_websocket_connections(self, session_id: str) -> None:
        """Close all WebSocket connections for session"""
        if session_id not in self._websocket_connections:
            return
        
        for ws_ref in self._websocket_connections[session_id]:
            websocket = ws_ref()
            if websocket is not None:
                try:
                    await websocket.close(code=1012, reason="Session stopped")
                except Exception as e:
                    logger.warning(f"Failed to close WebSocket: {e}")
        
        self._websocket_connections[session_id] = set()
    
    async def cleanup_inactive_sessions(self, max_inactive_hours: int = 2) -> int:
        """Cleanup sessions inactive for too long"""
        cutoff_time = datetime.now() - timedelta(hours=max_inactive_hours)
        sessions_cleaned = 0
        
        sessions_to_cleanup = []
        for session_id, session_info in self._sessions.items():
            if (session_info.last_ready_at and 
                session_info.last_ready_at < cutoff_time and
                session_info.state == SessionState.RUNNING):
                sessions_to_cleanup.append(session_id)
        
        for session_id in sessions_to_cleanup:
            logger.info(f"🧹 Cleaning up inactive session: {session_id}")
            await self.stop_session(session_id)
            sessions_cleaned += 1
        
        return sessions_cleaned

# Global session manager instance
session_manager = SessionManager()