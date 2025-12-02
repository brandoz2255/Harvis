"""VibeCode File API Endpoints

API endpoints for file operations within Docker container workspaces.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Optional, Any
import logging

from auth_utils import get_current_user
from vibecoding.containers import container_manager
from vibecoding import file_operations
# Rate limiting removed - slowapi dependency eliminated
from vibecoding.file_cache import get_file_tree_cache

# Import validated models
from vibecoding.validators import (
    FilePathRequest,
    FileCreateRequest as ValidatedFileCreateRequest,
    FileSaveRequest as ValidatedFileSaveRequest,
    FileRenameRequest as ValidatedFileRenameRequest,
    FileMoveRequest as ValidatedFileMoveRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibecode", tags=["vibecode-files"])


# ─── Request/Response Models ───────────────────────────────────────────────────

class FileTreeRequest(BaseModel):
    session_id: str
    path: str = "/workspace"


# Use validated models from validators module
FileCreateRequest = ValidatedFileCreateRequest

class FileReadRequest(BaseModel):
    session_id: str
    path: str


FileSaveRequest = ValidatedFileSaveRequest

# Custom rename request (slightly different from validator)
class FileRenameRequest(BaseModel):
    session_id: str
    old_path: str
    new_name: str  # Note: This is just the new name, not full path


FileMoveRequest = ValidatedFileMoveRequest


class FileDeleteRequest(BaseModel):
    session_id: str
    path: str
    soft: bool = True


class FileOperationResponse(BaseModel):
    success: bool
    message: Optional[str] = None


class FileContentResponse(BaseModel):
    content: str
    path: str


# ─── API Endpoints ─────────────────────────────────────────────────────────────

@router.post("/files/tree")
async def get_file_tree_endpoint(
    request: FileTreeRequest,
    user: Dict = Depends(get_current_user)
):
    """
    Get directory tree structure for a session.
    
    Returns hierarchical file/folder structure with metadata.
    Uses 30-second cache for improved performance.
    """
    try:
        # Get the container for this session
        container = await container_manager.get_container(request.session_id)
        
        if not container:
            raise HTTPException(
                status_code=404,
                detail=f"Container not found for session {request.session_id}"
            )
        
        # Get file tree (with caching)
        tree = await file_operations.get_file_tree(
            container, 
            request.path,
            session_id=request.session_id,
            use_cache=True
        )
        
        logger.debug(f"Retrieved file tree for session {request.session_id}, path {request.path}")
        
        return tree
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting file tree: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/create")
async def create_file_endpoint(
    request: FileCreateRequest,
    user: Dict = Depends(get_current_user)
):
    """
    Create a new file or folder in the session workspace.
    """
    try:
        # Get the container for this session
        container = await container_manager.get_container(request.session_id)
        
        if not container:
            raise HTTPException(
                status_code=404,
                detail=f"Container not found for session {request.session_id}"
            )
        
        # Validate type
        if request.type not in ["file", "folder"]:
            raise HTTPException(
                status_code=400,
                detail="Type must be 'file' or 'folder'"
            )
        
        # Create file or folder
        is_folder = request.type == "folder"
        success = await file_operations.create_file(
            container,
            request.path,
            is_folder=is_folder
        )
        
        # Invalidate cache for this path and parents
        cache = get_file_tree_cache()
        cache.invalidate(request.session_id, request.path)
        
        logger.debug(f"Created {request.type} at {request.path} in session {request.session_id}")
        
        return FileOperationResponse(
            success=success,
            message=f"{request.type.capitalize()} created successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating file/folder: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/read")
async def read_file_endpoint(
    request: FileReadRequest,
    user: Dict = Depends(get_current_user)
):
    """
    Read file content from the session workspace.
    """
    try:
        # Get the container for this session
        container = await container_manager.get_container(request.session_id)
        
        if not container:
            raise HTTPException(
                status_code=404,
                detail=f"Container not found for session {request.session_id}"
            )
        
        # Read file content
        content = await file_operations.read_file(container, request.path)
        
        logger.debug(f"Read file {request.path} from session {request.session_id}")
        
        return FileContentResponse(
            content=content,
            path=request.path
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/save")
async def save_file_endpoint(
    http_request: Request,
    request: FileSaveRequest,
    user: Dict = Depends(get_current_user)
):
    """
    Save content to a file in the session workspace.
    """
    try:
        # Get the container for this session
        container = await container_manager.get_container(request.session_id)
        
        if not container:
            raise HTTPException(
                status_code=404,
                detail=f"Container not found for session {request.session_id}"
            )
        
        # Save file content
        success = await file_operations.save_file(
            container,
            request.path,
            request.content
        )
        
        # Note: We don't invalidate cache on save since file content changes
        # don't affect the file tree structure. Only invalidate on create/delete/move/rename.
        
        logger.debug(f"Saved file {request.path} in session {request.session_id} ({len(request.content)} bytes)")
        
        return FileOperationResponse(
            success=success,
            message="File saved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/rename")
async def rename_file_endpoint(
    request: FileRenameRequest,
    user: Dict = Depends(get_current_user)
):
    """
    Rename a file or folder in the session workspace.
    """
    try:
        # Get the container for this session
        container = await container_manager.get_container(request.session_id)
        
        if not container:
            raise HTTPException(
                status_code=404,
                detail=f"Container not found for session {request.session_id}"
            )
        
        # Rename file/folder
        success = await file_operations.rename_file(
            container,
            request.old_path,
            request.new_name
        )
        
        # Invalidate cache for old and new paths
        cache = get_file_tree_cache()
        cache.invalidate(request.session_id, request.old_path)
        # Also invalidate parent directory
        import os
        parent_dir = os.path.dirname(request.old_path)
        cache.invalidate(request.session_id, parent_dir)
        
        logger.info(f"Renamed {request.old_path} to {request.new_name} in session {request.session_id}")
        
        return FileOperationResponse(
            success=success,
            message="File/folder renamed successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error renaming file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/move")
async def move_file_endpoint(
    request: FileMoveRequest,
    user: Dict = Depends(get_current_user)
):
    """
    Move a file or folder to a different directory (drag-and-drop support).
    """
    try:
        # Get the container for this session
        container = await container_manager.get_container(request.session_id)
        
        if not container:
            raise HTTPException(
                status_code=404,
                detail=f"Container not found for session {request.session_id}"
            )
        
        # Move file/folder
        success = await file_operations.move_file(
            container,
            request.source_path,
            request.target_dir
        )
        
        # Invalidate cache for source, target, and their parents
        cache = get_file_tree_cache()
        cache.invalidate(request.session_id, request.source_path)
        cache.invalidate(request.session_id, request.target_dir)
        import os
        cache.invalidate(request.session_id, os.path.dirname(request.source_path))
        
        logger.info(f"Moved {request.source_path} to {request.target_dir} in session {request.session_id}")
        
        return FileOperationResponse(
            success=success,
            message="File/folder moved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error moving file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/files/delete")
async def delete_file_endpoint(
    request: FileDeleteRequest,
    user: Dict = Depends(get_current_user)
):
    """
    Delete a file or folder (soft delete to trash by default).
    """
    try:
        # Get the container for this session
        container = await container_manager.get_container(request.session_id)
        
        if not container:
            raise HTTPException(
                status_code=404,
                detail=f"Container not found for session {request.session_id}"
            )
        
        # Delete file/folder
        success = await file_operations.delete_file(
            container,
            request.path,
            soft=request.soft
        )
        
        # Invalidate cache for this path and parent
        cache = get_file_tree_cache()
        cache.invalidate(request.session_id, request.path)
        import os
        cache.invalidate(request.session_id, os.path.dirname(request.path))
        
        delete_type = "soft deleted (moved to trash)" if request.soft else "permanently deleted"
        logger.info(f"{delete_type.capitalize()} {request.path} in session {request.session_id}")
        
        return FileOperationResponse(
            success=success,
            message=f"File/folder {delete_type}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))
