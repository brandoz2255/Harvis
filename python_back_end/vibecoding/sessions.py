"""Vibe Coding Sessions API Routes"""

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import logging
from pydantic import BaseModel

# Import auth dependencies
from auth_utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibe", tags=["vibe-sessions"])

# Pydantic models for request/response
class VibeSessionCreate(BaseModel):
    name: str
    description: Optional[str] = None

class VibeSessionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class VibeSessionResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    user_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    file_count: Optional[int] = 0

class VibeSessionsListResponse(BaseModel):
    sessions: List[VibeSessionResponse]
    total: int
    
# In-memory storage for sessions (should be database in production)
sessions_storage: Dict[str, Dict[str, Any]] = {}

@router.get("/sessions", response_model=VibeSessionsListResponse)
async def get_vibe_sessions(
    user: Dict = Depends(get_current_user),
    active_only: bool = False
):
    """Get all vibe coding sessions for the current user"""
    try:
        user_sessions = []
        
        for session_id, session_data in sessions_storage.items():
            if session_data.get("user_id") == str(user.get("id")):
                if active_only and not session_data.get("is_active", True):
                    continue
                    
                # Convert to response model
                session_response = VibeSessionResponse(
                    id=session_id,
                    name=session_data.get("name", "Unnamed Session"),
                    description=session_data.get("description"),
                    user_id=session_data.get("user_id"),
                    is_active=session_data.get("is_active", True),
                    created_at=session_data.get("created_at", datetime.now()),
                    updated_at=session_data.get("updated_at", datetime.now()),
                    file_count=len(session_data.get("files", []))
                )
                user_sessions.append(session_response)
        
        # Sort by most recent first
        user_sessions.sort(key=lambda x: x.updated_at, reverse=True)
        
        logger.info(f"Retrieved {len(user_sessions)} vibe sessions for user {user.get('id')}")
        
        return VibeSessionsListResponse(
            sessions=user_sessions,
            total=len(user_sessions)
        )
        
    except Exception as e:
        logger.error(f"Error retrieving vibe sessions: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve sessions")

@router.post("/sessions", response_model=VibeSessionResponse)
async def create_vibe_session(
    session_data: VibeSessionCreate,
    user: Dict = Depends(get_current_user)
):
    """Create a new vibe coding session"""
    try:
        session_id = str(uuid.uuid4())
        now = datetime.now()
        
        # Create default session structure
        new_session = {
            "id": session_id,
            "name": session_data.name,
            "description": session_data.description,
            "user_id": str(user.get("id")),
            "is_active": True,
            "created_at": now,
            "updated_at": now,
            "files": [],  # Will store file references
            "chat_history": [],  # Will store chat messages
            "settings": {
                "default_model": "mistral",
                "theme": "vibe-dark"
            }
        }
        
        sessions_storage[session_id] = new_session
        
        logger.info(f"Created new vibe session {session_id} for user {user.get('id')}")
        
        return VibeSessionResponse(
            id=session_id,
            name=new_session["name"],
            description=new_session["description"],
            user_id=new_session["user_id"],
            is_active=new_session["is_active"],
            created_at=new_session["created_at"],
            updated_at=new_session["updated_at"],
            file_count=0
        )
        
    except Exception as e:
        logger.error(f"Error creating vibe session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session")

@router.get("/sessions/{session_id}")
async def get_vibe_session(
    session_id: str,
    user: Dict = Depends(get_current_user)
):
    """Get a specific vibe coding session with files and chat history"""
    try:
        session = sessions_storage.get(session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
            
        # Check if user owns this session
        if session.get("user_id") != str(user.get("id")):
            raise HTTPException(status_code=403, detail="Access denied")
        
        logger.info(f"Retrieved vibe session {session_id} for user {user.get('id')}")
        
        return {
            "session": VibeSessionResponse(
                id=session["id"],
                name=session["name"],
                description=session.get("description"),
                user_id=session["user_id"],
                is_active=session.get("is_active", True),
                created_at=session["created_at"],
                updated_at=session["updated_at"],
                file_count=len(session.get("files", []))
            ),
            "files": session.get("files", []),
            "chat": session.get("chat_history", []),
            "settings": session.get("settings", {})
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving vibe session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve session")

@router.put("/sessions/{session_id}", response_model=VibeSessionResponse)
async def update_vibe_session(
    session_id: str,
    update_data: VibeSessionUpdate,
    user: Dict = Depends(get_current_user)
):
    """Update a vibe coding session"""
    try:
        session = sessions_storage.get(session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
            
        # Check if user owns this session
        if session.get("user_id") != str(user.get("id")):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Update fields
        now = datetime.now()
        if update_data.name is not None:
            session["name"] = update_data.name
        if update_data.description is not None:
            session["description"] = update_data.description
        if update_data.is_active is not None:
            session["is_active"] = update_data.is_active
            
        session["updated_at"] = now
        
        logger.info(f"Updated vibe session {session_id} for user {user.get('id')}")
        
        return VibeSessionResponse(
            id=session["id"],
            name=session["name"],
            description=session.get("description"),
            user_id=session["user_id"],
            is_active=session.get("is_active", True),
            created_at=session["created_at"],
            updated_at=session["updated_at"],
            file_count=len(session.get("files", []))
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating vibe session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update session")

@router.delete("/sessions/{session_id}")
async def delete_vibe_session(
    session_id: str,
    user: Dict = Depends(get_current_user)
):
    """Delete a vibe coding session"""
    try:
        session = sessions_storage.get(session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
            
        # Check if user owns this session
        if session.get("user_id") != str(user.get("id")):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Remove from storage
        del sessions_storage[session_id]
        
        logger.info(f"Deleted vibe session {session_id} for user {user.get('id')}")
        
        return {"message": "Session deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting vibe session {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete session")