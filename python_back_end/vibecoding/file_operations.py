"""VibeCode File Operations Module

This module handles file operations within Docker container workspaces,
including path sanitization, file tree generation, and CRUD operations.
"""

import os
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from fastapi import HTTPException
from vibecoding.file_cache import get_file_tree_cache

logger = logging.getLogger(__name__)

# Constants
WORKSPACE_BASE = "/workspace"
TRASH_DIR = ".vibe_trash"


class SecurityError(Exception):
    """Raised when a security violation is detected"""
    pass


def sanitize_path(path: str, base: str = WORKSPACE_BASE) -> str:
    """
    Ensure path is within workspace and safe from traversal attacks.
    
    Args:
        path: The path to sanitize
        base: The base directory (default: /workspace)
        
    Returns:
        Sanitized absolute path
        
    Raises:
        SecurityError: If path traversal or escape attempt detected
    """
    # Remove any leading/trailing whitespace
    path = path.strip()
    
    # Handle empty path
    if not path:
        return base
    
    # Convert to absolute path if relative
    if not path.startswith('/'):
        path = os.path.join(base, path)
    
    # Normalize the path (removes .., ., and redundant slashes)
    normalized_path = os.path.normpath(path)
    
    # Ensure the path starts with the base directory
    if not normalized_path.startswith(base):
        raise SecurityError(f"Path traversal attempt detected: {path}")
    
    # Additional check: ensure no .. components remain after normalization
    if '..' in Path(normalized_path).parts:
        raise SecurityError(f"Path contains invalid '..' component: {path}")
    
    # Check for absolute path attempts outside workspace
    if normalized_path != base and not normalized_path.startswith(base + '/'):
        raise SecurityError(f"Path escape attempt detected: {path}")
    
    return normalized_path


def validate_symlink(path: str, base: str = WORKSPACE_BASE) -> bool:
    """
    Verify that symlinks don't escape the workspace.
    
    Args:
        path: The path to check
        base: The base directory
        
    Returns:
        True if path is safe, False otherwise
    """
    try:
        # Get the real path (resolves symlinks)
        real_path = os.path.realpath(path)
        real_base = os.path.realpath(base)
        
        # Ensure the real path is still within the base
        if not real_path.startswith(real_base):
            logger.warning(f"Symlink escape detected: {path} -> {real_path}")
            return False
        
        return True
    except Exception as e:
        logger.error(f"Error validating symlink {path}: {e}")
        return False


async def get_file_tree(container, path: str = WORKSPACE_BASE, session_id: Optional[str] = None, use_cache: bool = True) -> Dict[str, Any]:
    """
    Get directory tree structure from container filesystem.
    
    Uses in-memory caching with 30-second TTL to improve performance.
    Cache is automatically invalidated on file operations.
    
    Args:
        container: Docker container object
        path: Root path to start from (default: /workspace)
        session_id: Session ID for cache scoping (optional)
        use_cache: Whether to use caching (default: True)
        
    Returns:
        Dictionary representing the file tree structure
    """
    try:
        # Sanitize the path
        safe_path = sanitize_path(path)
        
        # Try to get from cache if enabled and session_id provided
        if use_cache and session_id:
            cache = get_file_tree_cache()
            cached_tree = cache.get(session_id, safe_path)
            if cached_tree is not None:
                logger.debug(f"📦 Using cached file tree for {session_id}:{safe_path}")
                return cached_tree
        
        # Use find command to get directory structure
        # -type f: files, -type d: directories
        # -printf: custom format with type, path, size, permissions
        cmd = f'find {safe_path} -maxdepth 10 -printf "%y|%p|%s|%M\\n" 2>/dev/null || echo ""'
        
        result = container.exec_run(
            cmd=["sh", "-c", cmd],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            logger.error(f"Failed to get file tree: {result.output.decode()}")
            return {
                "name": os.path.basename(safe_path) or "workspace",
                "type": "directory",
                "path": safe_path,
                "children": []
            }
        
        # Parse the output
        output = result.output.decode('utf-8', errors='ignore').strip()
        if not output:
            return {
                "name": os.path.basename(safe_path) or "workspace",
                "type": "directory",
                "path": safe_path,
                "children": []
            }
        
        lines = output.split('\n')
        
        # Build file tree structure
        file_map = {}
        root_node = None
        
        for line in lines:
            if not line.strip():
                continue
            
            parts = line.split('|')
            if len(parts) != 4:
                continue
            
            file_type, file_path, size, permissions = parts
            
            # Skip if outside workspace
            if not file_path.startswith(WORKSPACE_BASE):
                continue
            
            # Ensure file_path is a string
            if not isinstance(file_path, str):
                continue
                
            node = {
                "name": os.path.basename(file_path) or "workspace",
                "type": "directory" if file_type == 'd' else "file",
                "path": file_path,
                "size": int(size) if size.isdigit() else 0,
                "permissions": permissions,
                "children": [] if file_type == 'd' else None
            }
            
            file_map[file_path] = node
            
            if file_path == safe_path:
                root_node = node
        
        # Build parent-child relationships
        for file_path, node in file_map.items():
            if file_path == safe_path:
                continue
            
            parent_path = os.path.dirname(file_path)
            parent_node = file_map.get(parent_path)
            
            if parent_node and parent_node.get('children') is not None:
                parent_node['children'].append(node)
        
        # Sort children: directories first, then files, alphabetically
        def sort_children(node):
            if node.get('children'):
                node['children'].sort(key=lambda x: (x['type'] == 'file', x['name'].lower()))
                for child in node['children']:
                    sort_children(child)
        
        if root_node:
            sort_children(root_node)
            result = root_node
        else:
            result = {
                "name": os.path.basename(safe_path) or "workspace",
                "type": "directory",
                "path": safe_path,
                "children": []
            }
        
        # Cache the result if enabled and session_id provided
        if use_cache and session_id:
            cache = get_file_tree_cache()
            cache.set(session_id, safe_path, result)
            logger.debug(f"💾 Cached file tree for {session_id}:{safe_path}")
        
        return result
        
    except SecurityError:
        raise
    except Exception as e:
        logger.error(f"Error getting file tree: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get file tree: {str(e)}")


async def create_file(container, path: str, is_folder: bool = False) -> bool:
    """
    Create a file or folder in the container.
    
    Args:
        container: Docker container object
        path: Path to create
        is_folder: True to create folder, False for file
        
    Returns:
        True if successful
    """
    try:
        # Sanitize the path
        safe_path = sanitize_path(path)
        
        # Create parent directories if needed
        parent_dir = os.path.dirname(safe_path)
        if parent_dir != WORKSPACE_BASE:
            result = container.exec_run(
                cmd=["mkdir", "-p", parent_dir],
                workdir=WORKSPACE_BASE
            )
            if result.exit_code != 0:
                raise HTTPException(status_code=500, detail="Failed to create parent directory")
        
        # Create the file or folder
        if is_folder:
            result = container.exec_run(
                cmd=["mkdir", "-p", safe_path],
                workdir=WORKSPACE_BASE
            )
        else:
            result = container.exec_run(
                cmd=["touch", safe_path],
                workdir=WORKSPACE_BASE
            )
        
        if result.exit_code != 0:
            error_msg = result.output.decode() if result.output else "Unknown error"
            raise HTTPException(status_code=500, detail=f"Failed to create: {error_msg}")
        
        logger.info(f"Created {'folder' if is_folder else 'file'}: {safe_path}")
        return True
        
    except SecurityError:
        raise HTTPException(status_code=400, detail="Invalid path: security violation")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating file/folder: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def create_folder(container, path: str) -> bool:
    """Create a folder in the container."""
    return await create_file(container, path, is_folder=True)


async def read_file(container, path: str) -> str:
    """
    Read file content from container filesystem.
    
    Args:
        container: Docker container object
        path: Path to file
        
    Returns:
        File content as string
    """
    try:
        # Sanitize the path
        safe_path = sanitize_path(path)
        
        # Check if file exists and is a regular file
        result = container.exec_run(
            cmd=["test", "-f", safe_path],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            raise HTTPException(status_code=404, detail="File not found or is not a regular file")
        
        # Read the file content
        result = container.exec_run(
            cmd=["cat", safe_path],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            error_msg = result.output.decode() if result.output else "Unknown error"
            raise HTTPException(status_code=500, detail=f"Failed to read file: {error_msg}")
        
        content = result.output.decode('utf-8', errors='replace')
        logger.debug(f"Read file: {safe_path} ({len(content)} bytes)")
        return content
        
    except SecurityError:
        raise HTTPException(status_code=400, detail="Invalid path: security violation")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def save_file(container, path: str, content: str, skip_unchanged: bool = True) -> bool:
    """
    Save content to a file in the container.
    
    Optimized to avoid saving unchanged content (Task 20.3).
    
    Args:
        container: Docker container object
        path: Path to file
        content: Content to write
        skip_unchanged: Skip save if content hasn't changed (default: True)
        
    Returns:
        True if successful
    """
    try:
        # Sanitize the path
        safe_path = sanitize_path(path)
        
        # Optimization: Check if content has changed before saving
        if skip_unchanged:
            try:
                # Try to read existing content
                result = container.exec_run(
                    cmd=["cat", safe_path],
                    workdir=WORKSPACE_BASE
                )
                
                if result.exit_code == 0:
                    existing_content = result.output.decode('utf-8', errors='replace')
                    
                    # If content is identical, skip the save
                    if existing_content == content:
                        logger.debug(f"Skipping save for {safe_path} (content unchanged)")
                        return True
            except Exception:
                # File doesn't exist or can't be read - proceed with save
                pass
        
        # Create parent directories if needed
        parent_dir = os.path.dirname(safe_path)
        if parent_dir != WORKSPACE_BASE:
            result = container.exec_run(
                cmd=["mkdir", "-p", parent_dir],
                workdir=WORKSPACE_BASE
            )
            if result.exit_code != 0:
                raise HTTPException(status_code=500, detail="Failed to create parent directory")
        
        # Write content to file using sh -c with here-doc to handle special characters
        # This is safer than echo as it handles newlines and special chars properly
        cmd = f"cat > {safe_path} << 'VIBECODE_EOF'\n{content}\nVIBECODE_EOF"
        
        result = container.exec_run(
            cmd=["sh", "-c", cmd],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            error_msg = result.output.decode() if result.output else "Unknown error"
            raise HTTPException(status_code=500, detail=f"Failed to save file: {error_msg}")
        
        logger.info(f"Saved file: {safe_path} ({len(content)} bytes)")
        return True
        
    except SecurityError:
        raise HTTPException(status_code=400, detail="Invalid path: security violation")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def rename_file(container, old_path: str, new_name: str) -> bool:
    """
    Rename a file or folder.
    
    Args:
        container: Docker container object
        old_path: Current path
        new_name: New name (not full path, just the name)
        
    Returns:
        True if successful
    """
    try:
        # Sanitize the old path
        safe_old_path = sanitize_path(old_path)
        
        # Build new path in same directory
        parent_dir = os.path.dirname(safe_old_path)
        new_path = os.path.join(parent_dir, new_name)
        safe_new_path = sanitize_path(new_path)
        
        # Check if source exists
        result = container.exec_run(
            cmd=["test", "-e", safe_old_path],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            raise HTTPException(status_code=404, detail="Source file/folder not found")
        
        # Check if destination already exists
        result = container.exec_run(
            cmd=["test", "-e", safe_new_path],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code == 0:
            raise HTTPException(status_code=409, detail="Destination already exists")
        
        # Rename using mv
        result = container.exec_run(
            cmd=["mv", safe_old_path, safe_new_path],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            error_msg = result.output.decode() if result.output else "Unknown error"
            raise HTTPException(status_code=500, detail=f"Failed to rename: {error_msg}")
        
        logger.info(f"Renamed: {safe_old_path} -> {safe_new_path}")
        return True
        
    except SecurityError:
        raise HTTPException(status_code=400, detail="Invalid path: security violation")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error renaming file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def move_file(container, source_path: str, target_dir: str) -> bool:
    """
    Move a file or folder to a different directory.
    
    Args:
        container: Docker container object
        source_path: Path to move
        target_dir: Destination directory
        
    Returns:
        True if successful
    """
    try:
        # Sanitize paths
        safe_source = sanitize_path(source_path)
        safe_target_dir = sanitize_path(target_dir)
        
        # Check if source exists
        result = container.exec_run(
            cmd=["test", "-e", safe_source],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            raise HTTPException(status_code=404, detail="Source file/folder not found")
        
        # Check if target directory exists and is a directory
        result = container.exec_run(
            cmd=["test", "-d", safe_target_dir],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            raise HTTPException(status_code=404, detail="Target directory not found")
        
        # Build destination path
        source_name = os.path.basename(safe_source)
        destination = os.path.join(safe_target_dir, source_name)
        safe_destination = sanitize_path(destination)
        
        # Check if destination already exists
        result = container.exec_run(
            cmd=["test", "-e", safe_destination],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code == 0:
            raise HTTPException(status_code=409, detail="Destination already exists")
        
        # Move using mv
        result = container.exec_run(
            cmd=["mv", safe_source, safe_destination],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            error_msg = result.output.decode() if result.output else "Unknown error"
            raise HTTPException(status_code=500, detail=f"Failed to move: {error_msg}")
        
        logger.info(f"Moved: {safe_source} -> {safe_destination}")
        return True
        
    except SecurityError:
        raise HTTPException(status_code=400, detail="Invalid path: security violation")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error moving file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def delete_file(container, path: str, soft: bool = True) -> bool:
    """
    Delete a file or folder (soft delete to trash by default).
    
    Args:
        container: Docker container object
        path: Path to delete
        soft: If True, move to trash; if False, permanently delete
        
    Returns:
        True if successful
    """
    try:
        # Sanitize the path
        safe_path = sanitize_path(path)
        
        # Don't allow deleting the workspace root
        if safe_path == WORKSPACE_BASE:
            raise HTTPException(status_code=400, detail="Cannot delete workspace root")
        
        # Check if file/folder exists
        result = container.exec_run(
            cmd=["test", "-e", safe_path],
            workdir=WORKSPACE_BASE
        )
        
        if result.exit_code != 0:
            raise HTTPException(status_code=404, detail="File/folder not found")
        
        if soft:
            # Soft delete: move to trash
            trash_path = os.path.join(WORKSPACE_BASE, TRASH_DIR)
            
            # Create trash directory if it doesn't exist
            result = container.exec_run(
                cmd=["mkdir", "-p", trash_path],
                workdir=WORKSPACE_BASE
            )
            
            if result.exit_code != 0:
                raise HTTPException(status_code=500, detail="Failed to create trash directory")
            
            # Generate unique name in trash (append timestamp)
            import time
            timestamp = int(time.time() * 1000)
            item_name = os.path.basename(safe_path)
            trash_item = os.path.join(trash_path, f"{item_name}.{timestamp}")
            
            # Move to trash
            result = container.exec_run(
                cmd=["mv", safe_path, trash_item],
                workdir=WORKSPACE_BASE
            )
            
            if result.exit_code != 0:
                error_msg = result.output.decode() if result.output else "Unknown error"
                raise HTTPException(status_code=500, detail=f"Failed to move to trash: {error_msg}")
            
            logger.info(f"Soft deleted (moved to trash): {safe_path} -> {trash_item}")
        else:
            # Hard delete: permanently remove
            result = container.exec_run(
                cmd=["rm", "-rf", safe_path],
                workdir=WORKSPACE_BASE
            )
            
            if result.exit_code != 0:
                error_msg = result.output.decode() if result.output else "Unknown error"
                raise HTTPException(status_code=500, detail=f"Failed to delete: {error_msg}")
            
            logger.info(f"Hard deleted: {safe_path}")
        
        return True
        
    except SecurityError:
        raise HTTPException(status_code=400, detail="Invalid path: security violation")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))
