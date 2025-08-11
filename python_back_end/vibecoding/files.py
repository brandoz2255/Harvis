"""Vibe Coding Files API Routes"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import logging
import asyncpg
import os
from pydantic import BaseModel

# Import auth dependencies
from auth_utils import get_current_user

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vibe", tags=["vibe-files"])

# Debug endpoints
@router.get("/debug/auth")
async def debug_auth(user: Dict = Depends(get_current_user)):
    """Debug endpoint to test authentication"""
    return {
        "user": user,
        "user_id": str(user.get("id")) if user.get("id") is not None else str(user.get("user_id", "")),
        "user_keys": list(user.keys()) if user else []
    }

@router.get("/debug/database")
async def debug_database():
    """Debug endpoint to test database connection and table"""
    try:
        conn = await get_db_connection()
        try:
            # Test connection
            version = await conn.fetchval("SELECT version()")
            
            # Check table exists
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'vibe_files'
                )
            """)
            
            # Count total files
            total_files = 0
            if table_exists:
                total_files = await conn.fetchval("SELECT COUNT(*) FROM vibe_files")
            
            return {
                "database_connected": True,
                "database_version": version,
                "table_exists": table_exists,
                "total_files": total_files,
                "database_url": DATABASE_URL.replace(DATABASE_URL.split('@')[0].split('//')[1], "***") if '@' in DATABASE_URL else "***"
            }
        finally:
            await conn.close()
    except Exception as e:
        return {
            "database_connected": False,
            "error": str(e),
            "database_url": DATABASE_URL.replace(DATABASE_URL.split('@')[0].split('//')[1], "***") if '@' in DATABASE_URL else "***"
        }

@router.post("/debug/test-create")
async def debug_test_create(user: Dict = Depends(get_current_user)):
    """Debug endpoint to test file creation"""
    try:
        await ensure_vibe_files_table()
        
        user_id = int(user.get("id")) if user.get("id") is not None else int(user.get("user_id", 0))
        session_id = f"debug-{int(datetime.now().timestamp())}"
        
        conn = await get_db_connection()
        try:
            # Create a test file
            new_file = await conn.fetchrow("""
                INSERT INTO vibe_files (name, type, content, language, path, session_id, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
            """, "debug_test.txt", "file", "Debug test content", "plaintext", "debug_test.txt", session_id, user_id)
            
            return {
                "success": True,
                "file_created": {
                    "id": str(new_file["id"]),
                    "name": new_file["name"],
                    "session_id": new_file["session_id"],
                    "user_id": new_file["user_id"]
                }
            }
        finally:
            await conn.close()
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

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

class VibeFileMoveRequest(BaseModel):
    targetParentId: Optional[str] = None  # None means move to root

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

# Database helper functions
async def get_db_connection():
    """Get database connection"""
    return await asyncpg.connect(DATABASE_URL)

async def ensure_vibe_files_table():
    """Ensure the vibe_files table exists"""
    try:
        conn = await get_db_connection()
        try:
            # First check if table exists
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'vibe_files'
                )
            """)
            
            if not table_exists:
                logger.info("🔧 Creating vibe_files table...")
                await conn.execute("""
                    CREATE TABLE vibe_files (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        name VARCHAR(255) NOT NULL,
                        type VARCHAR(20) NOT NULL CHECK (type IN ('file', 'folder')),
                        content TEXT,
                        language VARCHAR(50) DEFAULT 'plaintext',
                        path TEXT NOT NULL,
                        parent_id UUID REFERENCES vibe_files(id) ON DELETE CASCADE,
                        session_id VARCHAR(255) NOT NULL,
                        user_id INTEGER NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """)
                logger.info("✅ Created vibe_files table")
            
            # Create indexes
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_files_session_user ON vibe_files(session_id, user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_files_parent ON vibe_files(parent_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_files_type ON vibe_files(type)")
            
            # Test the connection by counting rows
            count = await conn.fetchval("SELECT COUNT(*) FROM vibe_files")
            logger.info(f"✅ Vibe files table ready with {count} existing files")
            
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to ensure vibe_files table: {e}")
        raise HTTPException(status_code=500, detail=f"Database setup failed: {str(e)}")

async def calculate_file_path(file_name: str, parent_id: Optional[str]) -> str:
    """Calculate the full path for a file based on its parent hierarchy"""
    if not parent_id:
        return file_name
    
    conn = await get_db_connection()
    try:
        parent_file = await conn.fetchrow(
            "SELECT path FROM vibe_files WHERE id = $1", 
            uuid.UUID(parent_id)
        )
        if not parent_file:
            return file_name
        
        return f"{parent_file['path']}/{file_name}"
    finally:
        await conn.close()

async def update_child_paths(file_id: str, new_parent_path: str):
    """Recursively update paths for all children when a folder is moved"""
    conn = await get_db_connection()
    try:
        # Get the file data
        file_data = await conn.fetchrow(
            "SELECT name, type FROM vibe_files WHERE id = $1", 
            uuid.UUID(file_id)
        )
        if not file_data:
            return
        
        # Update this file's path
        new_path = f"{new_parent_path}/{file_data['name']}" if new_parent_path else file_data['name']
        await conn.execute(
            "UPDATE vibe_files SET path = $1, updated_at = NOW() WHERE id = $2",
            new_path, uuid.UUID(file_id)
        )
        
        # If this is a folder, update all its children recursively
        if file_data['type'] == 'folder':
            children = await conn.fetch(
                "SELECT id FROM vibe_files WHERE parent_id = $1", 
                uuid.UUID(file_id)
            )
            for child in children:
                await update_child_paths(str(child['id']), new_path)
    finally:
        await conn.close()

async def validate_move_operation(file_id: str, target_parent_id: Optional[str]) -> bool:
    """Validate that a move operation is allowed (prevent circular references)"""
    if not target_parent_id:
        return True  # Moving to root is always allowed
    
    conn = await get_db_connection()
    try:
        # Check if target parent exists and is a folder
        target_parent = await conn.fetchrow(
            "SELECT type FROM vibe_files WHERE id = $1", 
            uuid.UUID(target_parent_id)
        )
        if not target_parent or target_parent['type'] != 'folder':
            return False
        
        # Check for circular reference (can't move a folder into itself or its descendants)
        file_data = await conn.fetchrow(
            "SELECT type FROM vibe_files WHERE id = $1", 
            uuid.UUID(file_id)
        )
        if not file_data or file_data['type'] != 'folder':
            return True  # Files can be moved anywhere
        
        # Walk up the target parent hierarchy to check for circular reference
        current_parent_id = target_parent_id
        while current_parent_id:
            if current_parent_id == file_id:
                return False  # Circular reference detected
            
            current_parent = await conn.fetchrow(
                "SELECT parent_id FROM vibe_files WHERE id = $1", 
                uuid.UUID(current_parent_id)
            )
            if not current_parent:
                break
            current_parent_id = str(current_parent['parent_id']) if current_parent['parent_id'] else None
        
        return True
    finally:
        await conn.close()

# Add startup event to main.py to initialize database
# This will be handled by the main FastAPI app startup event

@router.post("/files", response_model=VibeFileResponse)
async def create_vibe_file(
    file_data: VibeFileCreate,
    user: Dict = Depends(get_current_user)
):
    """Create a new file or folder in a vibe session"""
    try:
        # Ensure database table exists
        await ensure_vibe_files_table()
        
        # Get user ID - handle both dict formats
        user_id = int(user.get("id")) if user.get("id") is not None else int(user.get("user_id", 0))
        
        # Calculate path based on parent
        path = await calculate_file_path(file_data.name, file_data.parentId)
        
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
        
        # Insert into database
        conn = await get_db_connection()
        try:
            parent_uuid = uuid.UUID(file_data.parentId) if file_data.parentId else None
            
            new_file = await conn.fetchrow("""
                INSERT INTO vibe_files (name, type, content, language, path, parent_id, session_id, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id, name, type, content, language, path, parent_id, session_id, user_id, created_at, updated_at
            """, file_data.name, file_data.type, file_data.content or ("" if file_data.type == "file" else None),
                language, path, parent_uuid, file_data.sessionId, user_id)
            
            logger.info(f"Created vibe file {new_file['id']} ({file_data.type}): {file_data.name} for user {user_id}")
            
            return VibeFileResponse(
                id=str(new_file["id"]),
                name=new_file["name"],
                type=new_file["type"],
                content=new_file["content"],
                language=new_file["language"],
                path=new_file["path"],
                parent_id=str(new_file["parent_id"]) if new_file["parent_id"] else None,
                session_id=new_file["session_id"],
                created_at=new_file["created_at"],
                updated_at=new_file["updated_at"]
            )
        finally:
            await conn.close()
        
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
        # Get user ID - handle both dict formats
        user_id = int(user.get("id")) if user.get("id") is not None else int(user.get("user_id", 0))
        
        conn = await get_db_connection()
        try:
            file_data = await conn.fetchrow(
                "SELECT * FROM vibe_files WHERE id = $1 AND user_id = $2",
                uuid.UUID(file_id), user_id
            )
            
            if not file_data:
                raise HTTPException(status_code=404, detail="File not found")
            
            return VibeFileResponse(
                id=str(file_data["id"]),
                name=file_data["name"],
                type=file_data["type"],
                content=file_data["content"],
                language=file_data["language"],
                path=file_data["path"],
                parent_id=str(file_data["parent_id"]) if file_data["parent_id"] else None,
                session_id=file_data["session_id"],
                created_at=file_data["created_at"],
                updated_at=file_data["updated_at"]
            )
        finally:
            await conn.close()
        
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
        # Get user ID - handle both dict formats
        user_id = int(user.get("id")) if user.get("id") is not None else int(user.get("user_id", 0))
        
        conn = await get_db_connection()
        try:
            # Get current file data
            file_data = await conn.fetchrow(
                "SELECT * FROM vibe_files WHERE id = $1 AND user_id = $2",
                uuid.UUID(file_id), user_id
            )
            
            if not file_data:
                raise HTTPException(status_code=404, detail="File not found")
            
            # Prepare update fields
            updates = []
            values = []
            param_count = 1
            
            if update_data.name is not None:
                updates.append(f"name = ${param_count}")
                values.append(update_data.name)
                param_count += 1
                
                # Update path if name changed
                if file_data["parent_id"]:
                    new_path = await calculate_file_path(update_data.name, str(file_data["parent_id"]))
                else:
                    new_path = update_data.name
                updates.append(f"path = ${param_count}")
                values.append(new_path)
                param_count += 1
                
            if update_data.content is not None:
                updates.append(f"content = ${param_count}")
                values.append(update_data.content)
                param_count += 1
                
            if update_data.language is not None:
                updates.append(f"language = ${param_count}")
                values.append(update_data.language)
                param_count += 1
            
            # Always update the updated_at timestamp
            updates.append(f"updated_at = NOW()")
            
            if not updates:
                # No updates to make, return current data
                return VibeFileResponse(
                    id=str(file_data["id"]),
                    name=file_data["name"],
                    type=file_data["type"],
                    content=file_data["content"],
                    language=file_data["language"],
                    path=file_data["path"],
                    parent_id=str(file_data["parent_id"]) if file_data["parent_id"] else None,
                    session_id=file_data["session_id"],
                    created_at=file_data["created_at"],
                    updated_at=file_data["updated_at"]
                )
            
            # Execute update
            values.append(uuid.UUID(file_id))
            updated_file = await conn.fetchrow(f"""
                UPDATE vibe_files 
                SET {', '.join(updates)}
                WHERE id = ${param_count}
                RETURNING *
            """, *values)
            
            logger.info(f"Updated vibe file {file_id} for user {user_id}")
            
            return VibeFileResponse(
                id=str(updated_file["id"]),
                name=updated_file["name"],
                type=updated_file["type"],
                content=updated_file["content"],
                language=updated_file["language"],
                path=updated_file["path"],
                parent_id=str(updated_file["parent_id"]) if updated_file["parent_id"] else None,
                session_id=updated_file["session_id"],
                created_at=updated_file["created_at"],
                updated_at=updated_file["updated_at"]
            )
        finally:
            await conn.close()
        
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
        # Get user ID - handle both dict formats
        user_id = int(user.get("id")) if user.get("id") is not None else int(user.get("user_id", 0))
        
        conn = await get_db_connection()
        try:
            # Check if file exists and user owns it
            file_data = await conn.fetchrow(
                "SELECT * FROM vibe_files WHERE id = $1 AND user_id = $2",
                uuid.UUID(file_id), user_id
            )
            
            if not file_data:
                raise HTTPException(status_code=404, detail="File not found")
            
            # Delete the file (CASCADE will handle children)
            await conn.execute(
                "DELETE FROM vibe_files WHERE id = $1",
                uuid.UUID(file_id)
            )
            
            logger.info(f"Deleted vibe file {file_id} for user {user_id}")
            
            return {"message": "File deleted successfully"}
        finally:
            await conn.close()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting vibe file {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete file")

@router.put("/files/{file_id}/move", response_model=VibeFileResponse)
async def move_vibe_file(
    file_id: str,
    move_data: VibeFileMoveRequest,
    user: Dict = Depends(get_current_user)
):
    """Move a file or folder to a different parent (drag and drop functionality)"""
    try:
        # Get user ID - handle both dict formats
        user_id = int(user.get("id")) if user.get("id") is not None else int(user.get("user_id", 0))
        
        conn = await get_db_connection()
        try:
            # Get current file data
            file_data = await conn.fetchrow(
                "SELECT * FROM vibe_files WHERE id = $1 AND user_id = $2",
                uuid.UUID(file_id), user_id
            )
            
            if not file_data:
                raise HTTPException(status_code=404, detail="File not found")
            
            # Validate the move operation
            if not await validate_move_operation(file_id, move_data.targetParentId):
                raise HTTPException(status_code=400, detail="Invalid move operation: would create circular reference or target is not a folder")
            
            # If target parent is specified, verify it exists and user owns it
            if move_data.targetParentId:
                target_parent = await conn.fetchrow(
                    "SELECT * FROM vibe_files WHERE id = $1 AND user_id = $2",
                    uuid.UUID(move_data.targetParentId), user_id
                )
                if not target_parent:
                    raise HTTPException(status_code=404, detail="Target parent folder not found")
                
                if target_parent["session_id"] != file_data["session_id"]:
                    raise HTTPException(status_code=400, detail="Cannot move files between different sessions")
            
            # Calculate new path
            new_path = await calculate_file_path(file_data["name"], move_data.targetParentId)
            
            # Update the file's parent and path
            target_parent_uuid = uuid.UUID(move_data.targetParentId) if move_data.targetParentId else None
            updated_file = await conn.fetchrow("""
                UPDATE vibe_files 
                SET parent_id = $1, path = $2, updated_at = NOW()
                WHERE id = $3
                RETURNING *
            """, target_parent_uuid, new_path, uuid.UUID(file_id))
            
            # If this is a folder, update all children paths recursively
            if file_data["type"] == "folder":
                await update_child_paths(file_id, new_path)
            
            logger.info(f"Moved file {file_id} from parent {file_data['parent_id']} to {move_data.targetParentId}")
            
            return VibeFileResponse(
                id=str(updated_file["id"]),
                name=updated_file["name"],
                type=updated_file["type"],
                content=updated_file["content"],
                language=updated_file["language"],
                path=updated_file["path"],
                parent_id=str(updated_file["parent_id"]) if updated_file["parent_id"] else None,
                session_id=updated_file["session_id"],
                created_at=updated_file["created_at"],
                updated_at=updated_file["updated_at"]
            )
        finally:
            await conn.close()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error moving vibe file {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to move file")

@router.get("/files")
async def get_session_files(
    sessionId: str = Query(..., description="Session ID to get files for"),
    user: Dict = Depends(get_current_user)
):
    """Get all files for a vibe session"""
    try:
        # Get user ID - handle both dict formats
        user_id = int(user.get("id")) if user.get("id") is not None else int(user.get("user_id", 0))
        
        logger.info(f"Getting files for session {sessionId}, user {user_id}")
        
        conn = await get_db_connection()
        try:
            # Get all files for the session and user
            files = await conn.fetch(
                "SELECT * FROM vibe_files WHERE session_id = $1 AND user_id = $2 ORDER BY created_at",
                sessionId, user_id
            )
            
            session_files = []
            for file_data in files:
                session_files.append(VibeFileResponse(
                    id=str(file_data["id"]),
                    name=file_data["name"],
                    type=file_data["type"],
                    content=file_data["content"],
                    language=file_data["language"],
                    path=file_data["path"],
                    parent_id=str(file_data["parent_id"]) if file_data["parent_id"] else None,
                    session_id=file_data["session_id"],
                    created_at=file_data["created_at"],
                    updated_at=file_data["updated_at"]
                ))
            
            logger.info(f"Found {len(session_files)} files for session {sessionId}")
            
            return {
                "files": session_files,
                "total": len(session_files),
                "session_id": sessionId
            }
        finally:
            await conn.close()
        
    except Exception as e:
        logger.error(f"Error retrieving session files: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve session files")

@router.get("/files/tree")
async def get_session_files_tree(
    sessionId: str = Query(..., description="Session ID to get files for"),
    user: Dict = Depends(get_current_user)
):
    """Get all files for a vibe session organized in a tree structure"""
    try:
        # Get user ID - handle both dict formats
        user_id = int(user.get("id")) if user.get("id") is not None else int(user.get("user_id", 0))
        
        logger.info(f"Building tree structure for session {sessionId}, user {user_id}")
        
        conn = await get_db_connection()
        try:
            # Get all files for the session and user
            files = await conn.fetch(
                "SELECT * FROM vibe_files WHERE session_id = $1 AND user_id = $2 ORDER BY created_at",
                sessionId, user_id
            )
            
            # Convert to dict format for easier processing
            session_files = []
            for file_data in files:
                session_files.append({
                    "id": str(file_data["id"]),
                    "name": file_data["name"],
                    "type": file_data["type"],
                    "content": file_data["content"],
                    "language": file_data["language"],
                    "path": file_data["path"],
                    "parent_id": str(file_data["parent_id"]) if file_data["parent_id"] else None,
                    "session_id": file_data["session_id"],
                    "created_at": file_data["created_at"],
                    "updated_at": file_data["updated_at"]
                })
            
            # Build tree structure
            def build_tree_node(file_data):
                return {
                    "id": file_data["id"],
                    "name": file_data["name"],
                    "type": file_data["type"],
                    "content": file_data["content"],
                    "language": file_data["language"],
                    "path": file_data["path"],
                    "parent_id": file_data["parent_id"],
                    "session_id": file_data["session_id"],
                    "created_at": file_data["created_at"],
                    "updated_at": file_data["updated_at"],
                    "children": []
                }
            
            # Create a map of all files
            file_map = {file["id"]: build_tree_node(file) for file in session_files}
            
            # Build the tree by organizing children under parents
            root_files = []
            for file_data in session_files:
                file_node = file_map[file_data["id"]]
                
                if file_data["parent_id"] is None:
                    # Root level file/folder
                    root_files.append(file_node)
                else:
                    # Child file/folder - add to parent's children
                    parent_node = file_map.get(file_data["parent_id"])
                    if parent_node:
                        parent_node["children"].append(file_node)
            
            # Sort files: folders first, then files, both alphabetically
            def sort_tree_node(node):
                node["children"].sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
                for child in node["children"]:
                    sort_tree_node(child)
            
            # Sort root level
            root_files.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
            for root_file in root_files:
                sort_tree_node(root_file)
            
            logger.info(f"Built tree structure with {len(root_files)} root items for session {sessionId}")
            
            return {
                "tree": root_files,
                "total": len(session_files),
                "session_id": sessionId
            }
        finally:
            await conn.close()
        
    except Exception as e:
        logger.error(f"Error building file tree: {e}")
        raise HTTPException(status_code=500, detail="Failed to build file tree")