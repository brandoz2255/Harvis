"""
Vibe Session Lifecycle API Routes

Provides session status, start, and stop endpoints with proper
Docker integration and state management.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional
import logging
from datetime import datetime

from vibecoding.session_lifecycle import session_manager, SessionState
from auth_utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibe-sessions", tags=["vibe-session-lifecycle"])

# Pydantic models
class SessionStartResponse(BaseModel):
    status: str
    job_id: Optional[str] = None
    message: Optional[str] = None

class SessionStopResponse(BaseModel):
    status: str
    message: Optional[str] = None

class SessionStatusResponse(BaseModel):
    state: str
    container_exists: bool
    volume_exists: bool
    last_ready_at: Optional[str] = None
    created_at: Optional[str] = None
    error_message: Optional[str] = None
    session_id: str
    container_id: Optional[str] = None
    volume_name: Optional[str] = None

@router.get("/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(
    session_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """
    Get current session status with Docker container and volume state.
    
    Returns:
    - state: starting|running|stopping|stopped|error
    - container_exists: bool
    - volume_exists: bool  
    - last_ready_at: ISO timestamp when session was last ready
    """
    try:
        logger.info(f"Getting status for session {session_id}")
        
        session_info = await session_manager.get_session_status(session_id)
        
        response_data = session_info.to_dict()
        
        logger.info(f"Session {session_id} status: {response_data['state']}")
        
        return SessionStatusResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Error getting session status {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get session status: {str(e)}")

@router.post("/{session_id}/start", response_model=SessionStartResponse)
async def start_session(
    session_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """
    Start a session with job-based execution.
    
    - Idempotent: safe to call multiple times
    - Locks prevent concurrent starts for same session
    - Reuses existing container/volume if available
    - Returns job_id for tracking progress
    
    Returns immediately with job_id, doesn't wait for completion.
    """
    try:
        user_id = str(current_user.get("id", current_user.get("user_id", "unknown")))
        logger.info(f"Starting session {session_id} for user {user_id}")
        
        result = await session_manager.start_session(session_id, user_id)
        
        response = SessionStartResponse(
            status=result["status"],
            job_id=result.get("job_id"),
        )
        
        if result["status"] == "already_running":
            response.message = "Session is already running"
        elif result["status"] == "already_starting":
            response.message = "Session is already starting"
        elif result["status"] == "starting":
            response.message = f"Session start job {result['job_id']} initiated"
        
        logger.info(f"Session {session_id} start result: {result['status']}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error starting session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start session: {str(e)}")

@router.post("/{session_id}/stop", response_model=SessionStopResponse)
async def stop_session(
    session_id: str,
    current_user: Dict = Depends(get_current_user)
):
    """
    Stop a session idempotently.
    
    - Closes WebSocket connections
    - Stops container gracefully (10s timeout)
    - Sets state to stopped
    - Safe to call multiple times
    """
    try:
        user_id = str(current_user.get("id", current_user.get("user_id", "unknown")))
        logger.info(f"Stopping session {session_id} for user {user_id}")
        
        result = await session_manager.stop_session(session_id)
        
        response = SessionStopResponse(status=result["status"])
        
        if result["status"] == "already_stopped":
            response.message = "Session was already stopped"
        elif result["status"] == "already_stopping":
            response.message = "Session is already stopping"
        elif result["status"] == "stopped":
            response.message = "Session stopped successfully"
        elif result["status"] == "error":
            response.message = f"Error stopping session: {result.get('error', 'Unknown error')}"
        
        logger.info(f"Session {session_id} stop result: {result['status']}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error stopping session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop session: {str(e)}")

@router.post("/cleanup")
async def cleanup_inactive_sessions(
    max_inactive_hours: int = Query(2, description="Hours of inactivity before cleanup"),
    current_user: Dict = Depends(get_current_user)
):
    """
    Manually trigger cleanup of inactive sessions.
    
    Stops sessions that have been running but inactive for the specified time.
    """
    try:
        logger.info(f"Starting cleanup of sessions inactive for {max_inactive_hours}h")
        
        sessions_cleaned = await session_manager.cleanup_inactive_sessions(max_inactive_hours)
        
        logger.info(f"Cleanup completed: {sessions_cleaned} sessions cleaned")
        
        return {
            "message": "Cleanup completed successfully",
            "sessions_cleaned": sessions_cleaned,
            "max_inactive_hours": max_inactive_hours
        }
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check for session management system"""
    try:
        # Check if Docker is available
        docker_available = session_manager.docker_client is not None
        
        # Get basic stats
        total_sessions = len(session_manager._sessions)
        running_sessions = sum(
            1 for session in session_manager._sessions.values()
            if session.state == SessionState.RUNNING
        )
        
        return {
            "status": "healthy",
            "docker_available": docker_available,
            "total_sessions": total_sessions,
            "running_sessions": running_sessions,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")