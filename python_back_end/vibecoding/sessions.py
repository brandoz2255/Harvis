"""Vibe Coding Sessions Management

This module handles session lifecycle management including:
- Session creation and deletion
- Container association
- Session status tracking
- User authorization
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import logging
from pydantic import BaseModel, Field
import asyncpg

# Import auth dependencies
from auth_utils import get_current_user

# Import validators
from .validators import SessionCreateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibecode", tags=["vibecode-sessions"])

# ─── Pydantic Models ───────────────────────────────────────────────────────────

# Use validated model from validators module
SessionCreate = SessionCreateRequest

class SessionResponse(BaseModel):
    """Response model for session data"""
    session_id: str
    name: str
    description: Optional[str]
    status: str
    container_id: Optional[str]
    volume_name: Optional[str]  # Made optional to handle existing NULL values
    created_at: datetime
    updated_at: datetime
    last_activity: datetime

class SessionInfo(BaseModel):
    """Extended session information including container status"""
    session_id: str
    name: str
    description: Optional[str]
    status: str
    container_id: Optional[str]
    container_status: Optional[str]
    volume_name: Optional[str]  # Made optional to handle existing NULL values
    created_at: datetime
    updated_at: datetime
    last_activity: datetime

class SessionListResponse(BaseModel):
    """Response model for listing sessions"""
    sessions: List[SessionResponse]
    total: int

# ─── Session Manager ───────────────────────────────────────────────────────────

class SessionManager:
    """Manages session lifecycle and database operations"""
    
    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool
    
    async def create_session(
        self,
        user_id: int,
        name: str,
        template: str = "base",
        description: str = ""
    ) -> SessionResponse:
        """Create a new session in the database"""
        
        # Generate unique session_id
        session_id = str(uuid.uuid4())
        
        # Generate volume name
        volume_name = f"vibecode-{user_id}-{session_id}"
        
        async with self.db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow("""
                    INSERT INTO vibecoding_sessions 
                    (session_id, user_id, name, description, volume_name, status)
                    VALUES ($1, $2, $3, $4, $5, 'stopped')
                    RETURNING session_id, name, description, status, container_id, 
                              volume_name, created_at, updated_at, last_activity
                """, session_id, user_id, name, description, volume_name)
                
                logger.info(f"✅ Created session {session_id} for user {user_id}")
                
                return SessionResponse(
                    session_id=row['session_id'],
                    name=row['name'],
                    description=row['description'],
                    status=row['status'],
                    container_id=row['container_id'],
                    volume_name=row['volume_name'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    last_activity=row['last_activity']
                )
                
            except Exception as e:
                logger.error(f"❌ Failed to create session: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")
    
    async def list_sessions(
        self,
        user_id: int,
        active_only: bool = False
    ) -> List[SessionResponse]:
        """List all sessions for a user"""
        
        async with self.db_pool.acquire() as conn:
            try:
                query = """
                    SELECT session_id, name, description, status, container_id, 
                           volume_name, created_at, updated_at, last_activity
                    FROM vibecoding_sessions
                    WHERE user_id = $1 AND deleted_at IS NULL
                """
                
                params = [user_id]
                
                if active_only:
                    query += " AND status != 'stopped'"
                
                query += " ORDER BY last_activity DESC"
                
                rows = await conn.fetch(query, *params)
                
                sessions = [
                    SessionResponse(
                        session_id=row['session_id'],
                        name=row['name'],
                        description=row['description'],
                        status=row['status'],
                        container_id=row['container_id'],
                        volume_name=row['volume_name'],
                        created_at=row['created_at'],
                        updated_at=row['updated_at'],
                        last_activity=row['last_activity']
                    )
                    for row in rows
                ]
                
                logger.info(f"✅ Listed {len(sessions)} sessions for user {user_id}")
                return sessions
                
            except Exception as e:
                logger.error(f"❌ Failed to list sessions: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to list sessions: {str(e)}")
    
    async def get_session(
        self,
        session_id: str,
        user_id: int
    ) -> SessionResponse:
        """Get a specific session with authorization check"""
        
        async with self.db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow("""
                    SELECT session_id, name, description, status, container_id, 
                           volume_name, created_at, updated_at, last_activity, user_id
                    FROM vibecoding_sessions
                    WHERE session_id = $1 AND deleted_at IS NULL
                """, session_id)
                
                if not row:
                    raise HTTPException(status_code=404, detail="Session not found")
                
                # Authorization check
                if row['user_id'] != user_id:
                    raise HTTPException(status_code=403, detail="Access denied")
                
                return SessionResponse(
                    session_id=row['session_id'],
                    name=row['name'],
                    description=row['description'],
                    status=row['status'],
                    container_id=row['container_id'],
                    volume_name=row['volume_name'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    last_activity=row['last_activity']
                )
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"❌ Failed to get session: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to get session: {str(e)}")
    
    async def suspend_session(
        self,
        session_id: str,
        user_id: int
    ) -> bool:
        """Suspend a session (stop container but keep data)"""
        
        # First verify ownership
        await self.get_session(session_id, user_id)
        
        async with self.db_pool.acquire() as conn:
            try:
                await conn.execute("""
                    UPDATE vibecoding_sessions
                    SET status = 'suspended', last_activity = NOW()
                    WHERE session_id = $1
                """, session_id)
                
                logger.info(f"✅ Suspended session {session_id}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Failed to suspend session: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to suspend session: {str(e)}")
    
    async def delete_session(
        self,
        session_id: str,
        user_id: int,
        force: bool = False
    ) -> bool:
        """Delete a session (soft delete by default, hard delete if force=True)"""
        
        # First verify ownership
        await self.get_session(session_id, user_id)
        
        async with self.db_pool.acquire() as conn:
            try:
                if force:
                    # Hard delete - remove from database
                    await conn.execute("""
                        DELETE FROM vibecoding_sessions
                        WHERE session_id = $1
                    """, session_id)
                    logger.info(f"✅ Hard deleted session {session_id}")
                else:
                    # Soft delete - set deleted_at timestamp
                    await conn.execute("""
                        UPDATE vibecoding_sessions
                        SET deleted_at = NOW(), status = 'deleted'
                        WHERE session_id = $1
                    """, session_id)
                    logger.info(f"✅ Soft deleted session {session_id}")
                
                return True
                
            except Exception as e:
                logger.error(f"❌ Failed to delete session: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")
    
    async def update_container_info(
        self,
        session_id: str,
        container_id: str,
        status: str
    ) -> bool:
        """Update container information for a session"""
        
        async with self.db_pool.acquire() as conn:
            try:
                await conn.execute("""
                    UPDATE vibecoding_sessions
                    SET container_id = $1, status = $2, last_activity = NOW()
                    WHERE session_id = $3
                """, container_id, status, session_id)
                
                return True
                
            except Exception as e:
                logger.error(f"❌ Failed to update container info: {e}")
                return False

# Global session manager instance
_session_manager: Optional[SessionManager] = None

def get_session_manager(request: Request) -> SessionManager:
    """Dependency to get session manager instance"""
    global _session_manager
    
    if _session_manager is None:
        if hasattr(request.app.state, 'pg_pool') and request.app.state.pg_pool:
            _session_manager = SessionManager(request.app.state.pg_pool)
        else:
            raise HTTPException(status_code=503, detail="Database not available")
    
    return _session_manager

# ─── API Endpoints ─────────────────────────────────────────────────────────────

@router.post("/sessions/create", response_model=SessionResponse)
async def create_session(
    session_data: SessionCreate,
    user: Dict = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Create a new VibeCode session
    
    Creates a new development session with persistent storage.
    A Docker volume will be created for the session workspace.
    """
    user_id = user.get("id")
    
    return await session_manager.create_session(
        user_id=user_id,
        name=session_data.name,
        template=session_data.template,
        description=session_data.description or ""
    )

@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    active_only: bool = False,
    user: Dict = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """List all sessions for the current user
    
    Returns a list of sessions with their current status.
    Use active_only=true to filter out stopped sessions.
    """
    user_id = user.get("id")
    
    sessions = await session_manager.list_sessions(
        user_id=user_id,
        active_only=active_only
    )
    
    return SessionListResponse(
        sessions=sessions,
        total=len(sessions)
    )

@router.post("/sessions/open")
async def open_session(
    request: Request,
    user: Dict = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Open/resume a session and ensure container is running"""
    # Get session_id from request body
    try:
        body = await request.json()
        session_id = body.get("session_id")
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid request body")
    
    user_id = user.get("id")
    logger.info(f"🔄 Opening session {session_id} for user {user_id}")
    
    session = await session_manager.get_session(session_id, user_id)
    
    # Import container manager
    from .containers import container_manager
    
    # Get or create container
    container = await container_manager.get_container(session_id)
    logger.info(f"📦 Container lookup result: {container is not None}")
    
    if not container:
        # Create new container
        logger.info(f"🆕 Creating container for session {session_id}")
        try:
            await container_manager.create_container(
                session_id=session_id,
                user_id=str(user_id),
                template='base'
            )
            container = await container_manager.get_container(session_id)
            logger.info(f"✅ Container created successfully: {container.id if container else 'None'}")
        except Exception as e:
            logger.error(f"❌ Failed to create container: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create container: {str(e)}")
    else:
        # Start existing stopped container
        logger.info(f"▶️ Starting existing container for session {session_id}")
        try:
            await container_manager.start_container(session_id)
            container.reload()
            logger.info(f"✅ Container started successfully: {container.status}")
        except Exception as e:
            logger.error(f"❌ Failed to start container: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start container: {str(e)}")
    
    # Update database with container info
    try:
        await session_manager.update_container_info(
            session_id=session_id,
            container_id=container.id,
            status='running'
        )
        logger.info(f"✅ Database updated with container info")
    except Exception as e:
        logger.error(f"❌ Failed to update database: {e}")
    
    # Ensure runner container exists and is ready
    try:
        user_id_str = str(user_id)
        await container_manager.ensure_runner_ready(session_id, user_id_str)
        logger.info("✅ Runner container ready")
    except Exception as e:
        logger.warning(f"⚠️ Runner container not ready: {e}")
        # Don't fail the request, just log the error
    
    return {
        "message": "Session opened",
        "session": {
            "session_id": session.session_id,
            "name": session.name,
            "status": "running",
            "container_id": container.id
        },
        "container": {
            "id": container.id,
            "status": container.status
        }
    }

@router.post("/sessions/suspend")
async def suspend_session(
    session_id: str,
    user: Dict = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Suspend a session
    
    Stops the container but preserves all data in the volume.
    """
    user_id = user.get("id")
    
    success = await session_manager.suspend_session(session_id, user_id)
    
    return {
        "message": "Session suspended",
        "success": success
    }

@router.post("/sessions/delete")
async def delete_session(
    session_id: str,
    force: bool = False,
    user: Dict = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Delete a session
    
    By default, performs a soft delete (keeps volume).
    Use force=true to permanently delete the volume.
    """
    user_id = user.get("id")
    
    success = await session_manager.delete_session(session_id, user_id, force)
    
    return {
        "message": "Session deleted" if not force else "Session permanently deleted",
        "success": success
    }

@router.get("/status/{session_id}")
async def get_session_status(
    session_id: str,
    user: Dict = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Get session status with runtime capabilities"""
    user_id = user.get("id")
    
    # Get session info
    session = await session_manager.get_session(session_id, user_id)
    
    # Import container manager
    from .containers import container_manager
    
    # Get container status
    container = await container_manager.get_container(session_id)
    
    if not container:
        return {
            "status": "not_created",
            "message": "Container not created yet",
            "capabilities": {}
        }
    
    # Verify user owns this session
    user_id_label = container.labels.get("user_id")
    if user_id_label and str(user_id) != user_id_label:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    container.reload()
    
    # Probe runtime capabilities if container is running
    capabilities = {}
    if container.status == "running":
        try:
            import docker
            client = docker.from_env()
            
            def _probe(cmd: str) -> bool:
                """Probe if command exists in container"""
                try:
                    exec_id = client.api.exec_create(
                        container=container.id, 
                        cmd=["/bin/sh", "-lc", cmd]
                    )["Id"]
                    result = client.api.exec_start(exec_id, stream=False)
                    insp = client.api.exec_inspect(exec_id)
                    return insp.get("ExitCode", 1) == 0
                except:
                    return False
            
            # Probe each runtime
            capabilities = {
                "python": _probe("command -v python || command -v python3"),
                "bash": _probe("command -v bash"),
                "node": _probe("command -v node"),
                "tsnode": _probe("node -e \"require('ts-node')\" >/dev/null 2>&1"),
                "ruby": _probe("command -v ruby"),
                "go": _probe("command -v go"),
                "java": _probe("command -v javac && command -v java"),
                "gcc": _probe("command -v gcc || command -v g++"),
            }
        except Exception as e:
            logger.warning(f"Failed to probe capabilities for {session_id}: {e}")
            capabilities = {}
    
    return {
        "status": container.status,
        "message": f"Container {container.status}",
        "capabilities": capabilities,
        "container_id": container.id,
        "session_id": session_id
    }