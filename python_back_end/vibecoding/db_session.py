"""Database Session Management for Vibecoding

This module handles database operations for vibecoding sessions,
including session persistence, file metadata, and terminal history.
"""

import asyncpg
import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pydantic import BaseModel
import uuid

logger = logging.getLogger(__name__)

class VibeCodingSessionDB:
    """Database manager for vibecoding sessions."""
    
    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool
    
    async def create_session(
        self, 
        session_id: str, 
        user_id: int, 
        project_name: str = "Untitled Project",
        description: str = "",
        container_id: str = None,
        volume_name: str = None
    ) -> Dict[str, Any]:
        """Create a new vibecoding session."""
        async with self.db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow("""
                    INSERT INTO vibecoding_sessions 
                    (session_id, user_id, project_name, description, container_id, volume_name)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id, session_id, created_at
                """, session_id, user_id, project_name, description, container_id, volume_name)
                
                logger.info(f"✅ Created session: {session_id} for user: {user_id}")
                return {
                    "id": str(row["id"]),
                    "session_id": row["session_id"],
                    "created_at": row["created_at"].isoformat()
                }
            except Exception as e:
                logger.error(f"Failed to create session: {e}")
                raise
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by session_id."""
        async with self.db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow("""
                    SELECT * FROM vibecoding_session_overview 
                    WHERE session_id = $1
                """, session_id)
                
                if row:
                    return dict(row)
                return None
            except Exception as e:
                logger.error(f"Failed to get session {session_id}: {e}")
                return None
    
    async def update_session_activity(self, session_id: str) -> bool:
        """Update last activity timestamp for session."""
        async with self.db_pool.acquire() as conn:
            try:
                await conn.execute("""
                    UPDATE vibecoding_sessions 
                    SET last_activity = CURRENT_TIMESTAMP
                    WHERE session_id = $1
                """, session_id)
                return True
            except Exception as e:
                logger.error(f"Failed to update activity for {session_id}: {e}")
                return False
    
    async def update_container_status(self, session_id: str, container_id: str, status: str) -> bool:
        """Update container status for session."""
        async with self.db_pool.acquire() as conn:
            try:
                await conn.execute("""
                    UPDATE vibecoding_sessions 
                    SET container_id = $1, container_status = $2, last_activity = CURRENT_TIMESTAMP
                    WHERE session_id = $3
                """, container_id, status, session_id)
                return True
            except Exception as e:
                logger.error(f"Failed to update container status: {e}")
                return False
    
    async def list_user_sessions(self, user_id: int, active_only: bool = True) -> List[Dict[str, Any]]:
        """List sessions for a user."""
        async with self.db_pool.acquire() as conn:
            try:
                query = """
                    SELECT * FROM vibecoding_session_overview 
                    WHERE user_id = $1
                """
                params = [user_id]
                
                if active_only:
                    query += " AND is_active = true"
                
                query += " ORDER BY last_activity DESC"
                
                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to list sessions for user {user_id}: {e}")
                return []
    
    async def add_terminal_command(
        self, 
        session_id: str, 
        command: str, 
        output: str = "", 
        exit_code: int = 0,
        working_directory: str = "/workspace",
        execution_time_ms: int = 0
    ) -> bool:
        """Add terminal command to history."""
        async with self.db_pool.acquire() as conn:
            try:
                # Get session UUID from session_id
                session_uuid = await conn.fetchval("""
                    SELECT id FROM vibecoding_sessions WHERE session_id = $1
                """, session_id)
                
                if not session_uuid:
                    logger.error(f"Session not found: {session_id}")
                    return False
                
                await conn.execute("""
                    INSERT INTO vibecoding_terminal_history 
                    (session_id, command, output, exit_code, working_directory, execution_time_ms)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, session_uuid, command, output, exit_code, working_directory, execution_time_ms)
                
                # Update session activity
                await self.update_session_activity(session_id)
                return True
            except Exception as e:
                logger.error(f"Failed to add terminal command: {e}")
                return False
    
    async def get_terminal_history(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get terminal history for session."""
        async with self.db_pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT th.* FROM vibecoding_terminal_history th
                    JOIN vibecoding_sessions s ON th.session_id = s.id
                    WHERE s.session_id = $1
                    ORDER BY th.executed_at DESC
                    LIMIT $2
                """, session_id, limit)
                
                return [dict(row) for row in reversed(rows)]
            except Exception as e:
                logger.error(f"Failed to get terminal history: {e}")
                return []
    
    async def update_session_file(
        self,
        session_id: str,
        file_path: str,
        file_name: str,
        file_type: str = "text",
        file_size: int = 0,
        content_preview: str = "",
        language: str = None
    ) -> bool:
        """Update or create session file metadata."""
        async with self.db_pool.acquire() as conn:
            try:
                # Get session UUID
                session_uuid = await conn.fetchval("""
                    SELECT id FROM vibecoding_sessions WHERE session_id = $1
                """, session_id)
                
                if not session_uuid:
                    return False
                
                await conn.execute("""
                    INSERT INTO vibecoding_session_files 
                    (session_id, file_path, file_name, file_type, file_size, content_preview, language)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (session_id, file_path) 
                    DO UPDATE SET 
                        file_name = EXCLUDED.file_name,
                        file_type = EXCLUDED.file_type,
                        file_size = EXCLUDED.file_size,
                        content_preview = EXCLUDED.content_preview,
                        language = EXCLUDED.language,
                        updated_at = CURRENT_TIMESTAMP
                """, session_uuid, file_path, file_name, file_type, file_size, content_preview, language)
                
                await self.update_session_activity(session_id)
                return True
            except Exception as e:
                logger.error(f"Failed to update session file: {e}")
                return False
    
    async def get_session_files(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all files for a session."""
        async with self.db_pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT sf.* FROM vibecoding_session_files sf
                    JOIN vibecoding_sessions s ON sf.session_id = s.id
                    WHERE s.session_id = $1
                    ORDER BY sf.updated_at DESC
                """, session_id)
                
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get session files: {e}")
                return []
    
    async def delete_session_file(self, session_id: str, file_path: str) -> bool:
        """Delete session file metadata."""
        async with self.db_pool.acquire() as conn:
            try:
                result = await conn.execute("""
                    DELETE FROM vibecoding_session_files sf
                    USING vibecoding_sessions s
                    WHERE sf.session_id = s.id 
                    AND s.session_id = $1 
                    AND sf.file_path = $2
                """, session_id, file_path)
                
                return "DELETE" in str(result)
            except Exception as e:
                logger.error(f"Failed to delete session file: {e}")
                return False
    
    async def create_snapshot(
        self, 
        session_id: str, 
        snapshot_name: str, 
        description: str = "",
        file_count: int = 0,
        total_size: int = 0,
        metadata: Dict[str, Any] = None
    ) -> Optional[str]:
        """Create a session snapshot."""
        async with self.db_pool.acquire() as conn:
            try:
                session_uuid = await conn.fetchval("""
                    SELECT id FROM vibecoding_sessions WHERE session_id = $1
                """, session_id)
                
                if not session_uuid:
                    return None
                
                snapshot_id = await conn.fetchval("""
                    INSERT INTO vibecoding_snapshots 
                    (session_id, snapshot_name, description, file_count, total_size, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                """, session_uuid, snapshot_name, description, file_count, total_size, 
                json.dumps(metadata or {}))
                
                return str(snapshot_id)
            except Exception as e:
                logger.error(f"Failed to create snapshot: {e}")
                return None
    
    async def get_session_snapshots(self, session_id: str) -> List[Dict[str, Any]]:
        """Get snapshots for a session."""
        async with self.db_pool.acquire() as conn:
            try:
                rows = await conn.fetch("""
                    SELECT snap.* FROM vibecoding_snapshots snap
                    JOIN vibecoding_sessions s ON snap.session_id = s.id
                    WHERE s.session_id = $1
                    ORDER BY snap.created_at DESC
                """, session_id)
                
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"Failed to get snapshots: {e}")
                return []
    
    async def cleanup_inactive_sessions(self, inactive_days: int = 7) -> int:
        """Clean up inactive sessions."""
        async with self.db_pool.acquire() as conn:
            try:
                result = await conn.fetchval("""
                    SELECT cleanup_inactive_sessions($1)
                """, inactive_days)
                
                logger.info(f"🧹 Cleaned up {result} inactive sessions")
                return result
            except Exception as e:
                logger.error(f"Failed to cleanup sessions: {e}")
                return 0

# Global session database instance (will be initialized with db_pool)
session_db = None

async def init_session_db(db_pool: asyncpg.Pool):
    """Initialize the session database manager."""
    global session_db
    session_db = VibeCodingSessionDB(db_pool)
    logger.info("✅ Session database manager initialized")

def get_session_db() -> VibeCodingSessionDB:
    """Get the global session database instance."""
    if session_db is None:
        raise RuntimeError("Session database not initialized")
    return session_db