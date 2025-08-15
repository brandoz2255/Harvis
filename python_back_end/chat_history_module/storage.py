"""
Database storage operations for chat history
"""

import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
import asyncpg
from asyncpg import Connection, Pool

from .models import ChatSession, ChatMessage, CreateSessionRequest, CreateMessageRequest
from .exceptions import DatabaseError, SessionNotFoundError, MessageNotFoundError

logger = logging.getLogger(__name__)


class ChatHistoryStorage:
    """Database storage layer for chat history"""
    
    def __init__(self, db_pool: Pool):
        self.db_pool = db_pool
    
    async def create_session(self, user_id: int, request: CreateSessionRequest) -> ChatSession:
        """Create a new chat session"""
        session_id = uuid4()
        now = datetime.utcnow()
        
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at, last_message_at, model_used, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, session_id, user_id, request.title, now, now, now, request.model_used, True)
                
                # Fetch the created session
                row = await conn.fetchrow("""
                    SELECT id, user_id, title, created_at, updated_at, last_message_at, 
                           message_count, model_used, is_active
                    FROM chat_sessions 
                    WHERE id = $1
                """, session_id)
                
                if not row:
                    raise DatabaseError(f"Failed to create session {session_id}")
                
                return ChatSession(**dict(row))
                
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            raise DatabaseError(f"Failed to create session: {e}")
    
    async def get_session(self, session_id: UUID, user_id: int) -> ChatSession:
        """Get a chat session by ID"""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT id, user_id, title, created_at, updated_at, last_message_at, 
                           message_count, model_used, is_active
                    FROM chat_sessions 
                    WHERE id = $1 AND user_id = $2
                """, session_id, user_id)
                
                if not row:
                    raise SessionNotFoundError(str(session_id))
                
                return ChatSession(**dict(row))
                
        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error getting session {session_id}: {e}")
            raise DatabaseError(f"Failed to get session: {e}")
    
    async def get_user_sessions(self, user_id: int, limit: int = 50, offset: int = 0) -> List[ChatSession]:
        """Get all sessions for a user"""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, user_id, title, created_at, updated_at, last_message_at, 
                           message_count, model_used, is_active
                    FROM chat_sessions 
                    WHERE user_id = $1 AND is_active = TRUE
                    ORDER BY last_message_at DESC
                    LIMIT $2 OFFSET $3
                """, user_id, limit, offset)
                
                return [ChatSession(**dict(row)) for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting user sessions: {e}")
            raise DatabaseError(f"Failed to get user sessions: {e}")
    
    async def update_session_title(self, session_id: UUID, user_id: int, title: str) -> ChatSession:
        """Update session title"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE chat_sessions 
                    SET title = $1, updated_at = $2
                    WHERE id = $3 AND user_id = $4
                """, title, datetime.utcnow(), session_id, user_id)
                
                return await self.get_session(session_id, user_id)
                
        except Exception as e:
            logger.error(f"Error updating session title: {e}")
            raise DatabaseError(f"Failed to update session title: {e}")
    
    async def delete_session(self, session_id: UUID, user_id: int) -> bool:
        """Soft delete a session"""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute("""
                    UPDATE chat_sessions 
                    SET is_active = FALSE, updated_at = $1
                    WHERE id = $2 AND user_id = $3
                """, datetime.utcnow(), session_id, user_id)
                
                return result == "UPDATE 1"
                
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            raise DatabaseError(f"Failed to delete session: {e}")
    
    async def add_message(self, user_id: int, request: CreateMessageRequest) -> ChatMessage:
        """Add a message to a session"""
        try:
            async with self.db_pool.acquire() as conn:
                # Start transaction
                async with conn.transaction():
                    # Verify session exists and belongs to user
                    session_exists = await conn.fetchval("""
                        SELECT EXISTS(
                            SELECT 1 FROM chat_sessions 
                            WHERE id = $1 AND user_id = $2 AND is_active = TRUE
                        )
                    """, request.session_id, user_id)
                    
                    if not session_exists:
                        raise SessionNotFoundError(str(request.session_id))
                    
                    # Insert message
                    message_id = await conn.fetchval("""
                        INSERT INTO chat_messages (session_id, user_id, role, content, reasoning, model_used, input_type, metadata, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        RETURNING id
                    """, request.session_id, user_id, request.role, request.content, 
                        request.reasoning, request.model_used, request.input_type, 
                        json.dumps(request.metadata), datetime.utcnow())
                    
                    # Update session counters
                    await conn.execute("""
                        UPDATE chat_sessions 
                        SET message_count = message_count + 1, 
                            last_message_at = $1,
                            updated_at = $1
                        WHERE id = $2
                    """, datetime.utcnow(), request.session_id)
                    
                    # Fetch the created message
                    row = await conn.fetchrow("""
                        SELECT id, session_id, user_id, role, content, reasoning, model_used, 
                               input_type, metadata, created_at
                        FROM chat_messages 
                        WHERE id = $1
                    """, message_id)
                    
                    if not row:
                        raise DatabaseError(f"Failed to create message {message_id}")
                    
                    message_data = dict(row)
                    # Parse metadata if it's a string
                    if isinstance(message_data['metadata'], str):
                        try:
                            message_data['metadata'] = json.loads(message_data['metadata'])
                        except json.JSONDecodeError:
                            message_data['metadata'] = {}
                    
                    return ChatMessage(**message_data)
                    
        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error adding message: {e}")
            raise DatabaseError(f"Failed to add message: {e}")
    
    async def get_session_messages(self, session_id: UUID, user_id: int, limit: int = 100, offset: int = 0) -> List[ChatMessage]:
        """Get messages for a session"""
        try:
            async with self.db_pool.acquire() as conn:
                # Verify session exists and belongs to user
                session_exists = await conn.fetchval("""
                    SELECT EXISTS(
                        SELECT 1 FROM chat_sessions 
                        WHERE id = $1 AND user_id = $2 AND is_active = TRUE
                    )
                """, session_id, user_id)
                
                if not session_exists:
                    raise SessionNotFoundError(str(session_id))
                
                rows = await conn.fetch("""
                    SELECT id, session_id, user_id, role, content, reasoning, model_used, 
                           input_type, metadata, created_at
                    FROM chat_messages 
                    WHERE session_id = $1 AND user_id = $2
                    ORDER BY created_at ASC
                    LIMIT $3 OFFSET $4
                """, session_id, user_id, limit, offset)
                
                messages = []
                for row in rows:
                    message_data = dict(row)
                    # Parse metadata if it's a string
                    if isinstance(message_data['metadata'], str):
                        try:
                            message_data['metadata'] = json.loads(message_data['metadata'])
                        except json.JSONDecodeError:
                            message_data['metadata'] = {}
                    messages.append(ChatMessage(**message_data))
                
                return messages
                
        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error getting session messages: {e}")
            raise DatabaseError(f"Failed to get session messages: {e}")
    
    async def get_message_count(self, session_id: UUID, user_id: int) -> int:
        """Get total message count for a session"""
        try:
            async with self.db_pool.acquire() as conn:
                count = await conn.fetchval("""
                    SELECT COUNT(*) FROM chat_messages 
                    WHERE session_id = $1 AND user_id = $2
                """, session_id, user_id)
                
                return count or 0
                
        except Exception as e:
            logger.error(f"Error getting message count: {e}")
            raise DatabaseError(f"Failed to get message count: {e}")
    
    async def clear_session_messages(self, session_id: UUID, user_id: int) -> bool:
        """Clear all messages from a session"""
        try:
            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    # Delete messages
                    await conn.execute("""
                        DELETE FROM chat_messages 
                        WHERE session_id = $1 AND user_id = $2
                    """, session_id, user_id)
                    
                    # Reset session counters
                    await conn.execute("""
                        UPDATE chat_sessions 
                        SET message_count = 0, updated_at = $1
                        WHERE id = $2 AND user_id = $3
                    """, datetime.utcnow(), session_id, user_id)
                    
                    return True
                    
        except Exception as e:
            logger.error(f"Error clearing session messages: {e}")
            raise DatabaseError(f"Failed to clear session messages: {e}")
