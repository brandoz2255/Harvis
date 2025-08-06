"""Vibe Coding Files API Routes"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import logging
from pydantic import BaseModel

# Import auth dependencies
from auth_utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibe", tags=["vibe-files"])

# Pydantic models for request/response
class VibeFileCreate(BaseModel):
    sessionId: str
    parentId: Optional[str] = None
    name: str
    type: str = "file"  # file or folder
    content: Optional[str] = ""
    language: Optional[str] = "plaintext"

class VibeFileUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    language: Optional[str] = None

class VibeFileResponse(BaseModel):
    id: str
    name: str
    type: str
    content: Optional[str]
    language: Optional[str]
    path: str
    parent_id: Optional[str]
    session_id: str
    created_at: datetime
    updated_at: datetime

# In-memory storage for files (should be database in production)
files_storage: Dict[str, Dict[str, Any]] = {}

@router.post("/files", response_model=VibeFileResponse)
async def create_vibe_file(
    file_data: VibeFileCreate,
    user: Dict = Depends(get_current_user)
):
    """Create a new file or folder in a vibe session"""
    try:
        # Verify user owns the session (simplified - in production check session ownership)
        file_id = str(uuid.uuid4())
        now = datetime.now()
        
        # Determine path
        path = file_data.name
        if file_data.parentId:
            parent_file = files_storage.get(file_data.parentId)
            if parent_file:
                path = f"{parent_file['path']}/{file_data.name}"
        
        # Determine language from file extension
        language = file_data.language or "plaintext"
        if file_data.type == "file" and "." in file_data.name:
            ext = file_data.name.split(".")[-1].lower()
            language_map = {
                "py": "python",
                "js": "javascript", 
                "ts": "typescript",
                "java": "java",
                "go": "go",
                "rs": "rust",
                "cpp": "cpp",
                "c": "c",
                "rb": "ruby",
                "php": "php",
                "sh": "bash",
                "md": "markdown",
                "html": "html",
                "css": "css",
                "json": "json",
                "xml": "xml",
                "yaml": "yaml",
                "yml": "yaml"
            }
            language = language_map.get(ext, "plaintext")
        
        new_file = {
            "id": file_id,
            "name": file_data.name,
            "type": file_data.type,
            "content": file_data.content or ("" if file_data.type == "file" else None),
            "language": language,
            "path": path,
            "parent_id": file_data.parentId,
            "session_id": file_data.sessionId,
            "user_id": str(user.get("id")),
            "created_at": now,
            "updated_at": now
        }
        
        files_storage[file_id] = new_file
        
        logger.info(f"Created vibe file {file_id} ({file_data.type}): {file_data.name} for user {user.get('id')}")
        
        return VibeFileResponse(
            id=file_id,
            name=new_file["name"],
            type=new_file["type"],
            content=new_file["content"],
            language=new_file["language"],
            path=new_file["path"],
            parent_id=new_file["parent_id"],
            session_id=new_file["session_id"],
            created_at=new_file["created_at"],
            updated_at=new_file["updated_at"]
        )
        
    except Exception as e:
        logger.error(f"Error creating vibe file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create file: {str(e)}")

@router.get("/files/{file_id}", response_model=VibeFileResponse)
async def get_vibe_file(
    file_id: str,
    user: Dict = Depends(get_current_user)
):
    """Get a specific vibe file"""
    try:
        file_data = files_storage.get(file_id)
        
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Check if user owns this file (simplified)
        if file_data.get("user_id") != str(user.get("id")):
            raise HTTPException(status_code=403, detail="Access denied")
        
        return VibeFileResponse(
            id=file_data["id"],
            name=file_data["name"],
            type=file_data["type"],
            content=file_data["content"],
            language=file_data["language"],
            path=file_data["path"],
            parent_id=file_data["parent_id"],
            session_id=file_data["session_id"],
            created_at=file_data["created_at"],
            updated_at=file_data["updated_at"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving vibe file {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve file")

@router.put("/files/{file_id}", response_model=VibeFileResponse)
async def update_vibe_file(
    file_id: str,
    update_data: VibeFileUpdate,
    user: Dict = Depends(get_current_user)
):
    """Update a vibe file"""
    try:
        file_data = files_storage.get(file_id)
        
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Check if user owns this file
        if file_data.get("user_id") != str(user.get("id")):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Update fields
        now = datetime.now()
        if update_data.name is not None:
            file_data["name"] = update_data.name
            # Update path if name changed
            if file_data.get("parent_id"):
                parent_file = files_storage.get(file_data["parent_id"])
                if parent_file:
                    file_data["path"] = f"{parent_file['path']}/{update_data.name}"
            else:
                file_data["path"] = update_data.name
                
        if update_data.content is not None:
            file_data["content"] = update_data.content
            
        if update_data.language is not None:
            file_data["language"] = update_data.language
            
        file_data["updated_at"] = now
        
        logger.info(f"Updated vibe file {file_id} for user {user.get('id')}")
        
        return VibeFileResponse(
            id=file_data["id"],
            name=file_data["name"],
            type=file_data["type"],
            content=file_data["content"],
            language=file_data["language"],
            path=file_data["path"],
            parent_id=file_data["parent_id"],
            session_id=file_data["session_id"],
            created_at=file_data["created_at"],
            updated_at=file_data["updated_at"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating vibe file {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update file")

@router.delete("/files/{file_id}")
async def delete_vibe_file(
    file_id: str,
    user: Dict = Depends(get_current_user)
):
    """Delete a vibe file"""
    try:
        file_data = files_storage.get(file_id)
        
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found")
        
        # Check if user owns this file
        if file_data.get("user_id") != str(user.get("id")):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Remove from storage
        del files_storage[file_id]
        
        logger.info(f"Deleted vibe file {file_id} for user {user.get('id')}")
        
        return {"message": "File deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting vibe file {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete file")

@router.get("/files")
async def get_session_files(
    session_id: str = Query(..., description="Session ID to get files for"),
    user: Dict = Depends(get_current_user)
):
    """Get all files for a vibe session"""
    try:
        session_files = []
        
        for file_id, file_data in files_storage.items():
            if (file_data.get("session_id") == session_id and 
                file_data.get("user_id") == str(user.get("id"))):
                
                session_files.append(VibeFileResponse(
                    id=file_data["id"],
                    name=file_data["name"],
                    type=file_data["type"],
                    content=file_data["content"],
                    language=file_data["language"],
                    path=file_data["path"],
                    parent_id=file_data["parent_id"],
                    session_id=file_data["session_id"],
                    created_at=file_data["created_at"],
                    updated_at=file_data["updated_at"]
                ))
        
        # Sort by creation time
        session_files.sort(key=lambda x: x.created_at)
        
        return {
            "files": session_files,
            "total": len(session_files),
            "session_id": session_id
        }
        
    except Exception as e:
        logger.error(f"Error retrieving session files: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve session files")