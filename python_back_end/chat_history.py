"""
Chat History Module for Jarvis AI
Handles persistent chat history storage using PostgreSQL
"""

import asyncpg
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from pydantic import BaseModel
import json

logger = logging.getLogger(__name__)

# ─── Pydantic Models ───────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    id: Optional[int] = None
    session_id: str
    user_id: int
    role: str  # 'user', 'assistant', 'system'
    content: str
    reasoning: Optional[str] = None
    model_used: Optional[str] = None
    input_type: str = 'text'  # 'text', 'voice', 'screen'
    metadata: Dict[str, Any] = {}
    created_at: Optional[datetime] = None

class ChatSession(BaseModel):
    id: str
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    message_count: int
    model_used: Optional[str] = None
    is_active: bool = True

class CreateSessionRequest(BaseModel):
    user_id: int
    title: Optional[str] = "New Chat"
    model_used: Optional[str] = None

class MessageHistoryResponse(BaseModel):
    messages: List[ChatMessage]
    session: ChatSession
    total_count: int

# ─── Chat History Manager Class ────────────────────────────────────────────────

class ChatHistoryManager:
    """
    Manages chat history with PostgreSQL backend
    Provides session management and message persistence
    """
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        
    async def get_db_connection(self):
        """Get async database connection"""
        return await asyncpg.connect(self.database_url)
    
    # ─── Session Management ────────────────────────────────────────────────────
    
    async def create_session(self, user_id: int, title: str = "New Chat", model_used: Optional[str] = None) -> ChatSession:
        """Create a new chat session"""
        try:
            conn = await self.get_db_connection()
            try:
                session_id = str(uuid.uuid4())
                
                row = await conn.fetchrow("""
                    INSERT INTO chat_sessions (id, user_id, title, model_used)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id, user_id, title, created_at, updated_at, last_message_at, message_count, model_used, is_active
                """, session_id, user_id, title, model_used)
                
                logger.info(f"Created new chat session {session_id} for user {user_id}")
                return ChatSession(**dict(row))
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error creating chat session: {e}")
            raise
    
    async def get_session(self, session_id: str, user_id: int) -> Optional[ChatSession]:
        """Get a specific chat session"""
        try:
            conn = await self.get_db_connection()
            try:
                row = await conn.fetchrow("""
                    SELECT id, user_id, title, created_at, updated_at, last_message_at, message_count, model_used, is_active
                    FROM chat_sessions 
                    WHERE id = $1 AND user_id = $2
                """, session_id, user_id)
                
                if row:
                    return ChatSession(**dict(row))
                return None
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error getting chat session {session_id}: {e}")
            raise
    
    async def get_user_sessions(self, user_id: int, limit: int = 50, offset: int = 0) -> List[ChatSession]:
        """Get all chat sessions for a user, ordered by most recent"""
        try:
            conn = await self.get_db_connection()
            try:
                rows = await conn.fetch("""
                    SELECT id, user_id, title, created_at, updated_at, last_message_at, message_count, model_used, is_active
                    FROM chat_sessions 
                    WHERE user_id = $1 AND is_active = true
                    ORDER BY updated_at DESC
                    LIMIT $2 OFFSET $3
                """, user_id, limit, offset)
                
                return [ChatSession(**dict(row)) for row in rows]
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error getting user sessions for user {user_id}: {e}")
            raise
    
    async def update_session_title(self, session_id: str, user_id: int, title: str) -> bool:
        """Update session title"""
        try:
            conn = await self.get_db_connection()
            try:
                result = await conn.execute("""
                    UPDATE chat_sessions 
                    SET title = $1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $2 AND user_id = $3
                """, title, session_id, user_id)
                
                return result == "UPDATE 1"
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error updating session title: {e}")
            raise
    
    async def delete_session(self, session_id: str, user_id: int) -> bool:
        """Soft delete a chat session"""
        try:
            conn = await self.get_db_connection()
            try:
                result = await conn.execute("""
                    UPDATE chat_sessions 
                    SET is_active = false, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $1 AND user_id = $2
                """, session_id, user_id)
                
                logger.info(f"Deleted session {session_id} for user {user_id}")
                return result == "UPDATE 1"
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            raise
    
    # ─── Message Management ────────────────────────────────────────────────────
    
    async def add_message(self, message: ChatMessage) -> ChatMessage:
        """Add a message to chat history"""
        try:
            conn = await self.get_db_connection()
            try:
                # Ensure session exists
                session = await self.get_session(message.session_id, message.user_id)
                if not session:
                    # Create session if it doesn't exist
                    await self.create_session(message.user_id, "New Chat", message.model_used)
                
                row = await conn.fetchrow("""
                    INSERT INTO chat_messages 
                    (session_id, user_id, role, content, reasoning, model_used, input_type, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id, session_id, user_id, role, content, reasoning, model_used, input_type, metadata, created_at
                """, message.session_id, message.user_id, message.role, message.content, 
                     message.reasoning, message.model_used, message.input_type, json.dumps(message.metadata))
                
                result = ChatMessage(**dict(row))
                logger.info(f"Added {message.role} message to session {message.session_id}")
                return result
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error adding message: {e}")
            raise
    
    async def add_messages_batch(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        """Add multiple messages in a batch"""
        try:
            conn = await self.get_db_connection()
            try:
                # Use transaction for batch insert
                async with conn.transaction():
                    results = []
                    for message in messages:
                        row = await conn.fetchrow("""
                            INSERT INTO chat_messages 
                            (session_id, user_id, role, content, reasoning, model_used, input_type, metadata)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            RETURNING id, session_id, user_id, role, content, reasoning, model_used, input_type, metadata, created_at
                        """, message.session_id, message.user_id, message.role, message.content,
                             message.reasoning, message.model_used, message.input_type, json.dumps(message.metadata))
                        
                        results.append(ChatMessage(**dict(row)))
                    
                    logger.info(f"Added batch of {len(messages)} messages")
                    return results
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error adding message batch: {e}")
            raise
    
    async def get_session_messages(self, session_id: str, user_id: int, limit: int = 100, offset: int = 0) -> MessageHistoryResponse:
        """Get messages for a specific session"""
        try:
            conn = await self.get_db_connection()
            try:
                # Get session info
                session_row = await conn.fetchrow("""
                    SELECT id, user_id, title, created_at, updated_at, last_message_at, message_count, model_used, is_active
                    FROM chat_sessions 
                    WHERE id = $1 AND user_id = $2
                """, session_id, user_id)
                
                if not session_row:
                    raise ValueError(f"Session {session_id} not found for user {user_id}")
                
                session = ChatSession(**dict(session_row))
                
                # Get messages
                message_rows = await conn.fetch("""
                    SELECT id, session_id, user_id, role, content, reasoning, model_used, input_type, metadata, created_at
                    FROM chat_messages 
                    WHERE session_id = $1 AND user_id = $2
                    ORDER BY created_at ASC
                    LIMIT $3 OFFSET $4
                """, session_id, user_id, limit, offset)
                
                messages = [ChatMessage(**dict(row)) for row in message_rows]
                
                # Get total count
                total_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM chat_messages 
                    WHERE session_id = $1 AND user_id = $2
                """, session_id, user_id)
                
                return MessageHistoryResponse(
                    messages=messages,
                    session=session,
                    total_count=total_count
                )
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error getting session messages: {e}")
            raise
    
    async def get_recent_messages(self, session_id: str, user_id: int, count: int = 10) -> List[ChatMessage]:
        """Get most recent messages for context"""
        try:
            conn = await self.get_db_connection()
            try:
                rows = await conn.fetch("""
                    SELECT id, session_id, user_id, role, content, reasoning, model_used, input_type, metadata, created_at
                    FROM chat_messages 
                    WHERE session_id = $1 AND user_id = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                """, session_id, user_id, count)
                
                # Return in chronological order
                messages = [ChatMessage(**dict(row)) for row in reversed(rows)]
                return messages
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error getting recent messages: {e}")
            raise
    
    async def search_messages(self, user_id: int, query: str, session_id: Optional[str] = None, limit: int = 50) -> List[ChatMessage]:
        """Search messages by content"""
        try:
            conn = await self.get_db_connection()
            try:
                if session_id:
                    rows = await conn.fetch("""
                        SELECT id, session_id, user_id, role, content, reasoning, model_used, input_type, metadata, created_at
                        FROM chat_messages 
                        WHERE user_id = $1 AND session_id = $2 AND content ILIKE $3
                        ORDER BY created_at DESC
                        LIMIT $4
                    """, user_id, session_id, f"%{query}%", limit)
                else:
                    rows = await conn.fetch("""
                        SELECT id, session_id, user_id, role, content, reasoning, model_used, input_type, metadata, created_at
                        FROM chat_messages 
                        WHERE user_id = $1 AND content ILIKE $2
                        ORDER BY created_at DESC
                        LIMIT $3
                    """, user_id, f"%{query}%", limit)
                
                return [ChatMessage(**dict(row)) for row in rows]
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error searching messages: {e}")
            raise
    
    # ─── Utility Methods ────────────────────────────────────────────────────────
    
    async def clear_session_messages(self, session_id: str, user_id: int) -> int:
        """Clear all messages from a session"""
        try:
            conn = await self.get_db_connection()
            try:
                result = await conn.execute("""
                    DELETE FROM chat_messages 
                    WHERE session_id = $1 AND user_id = $2
                """, session_id, user_id)
                
                # Reset session message count
                await conn.execute("""
                    UPDATE chat_sessions 
                    SET message_count = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $1 AND user_id = $2
                """, session_id, user_id)
                
                deleted_count = int(result.split()[-1]) if result.split()[-1].isdigit() else 0
                logger.info(f"Cleared {deleted_count} messages from session {session_id}")
                return deleted_count
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error clearing session messages: {e}")
            raise
    
    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Get user chat statistics"""
        try:
            conn = await self.get_db_connection()
            try:
                stats = await conn.fetchrow("""
                    SELECT 
                        COUNT(DISTINCT cs.id) as total_sessions,
                        COUNT(DISTINCT CASE WHEN cs.is_active THEN cs.id END) as active_sessions,
                        COALESCE(SUM(cs.message_count), 0) as total_messages,
                        MAX(cs.updated_at) as last_activity
                    FROM chat_sessions cs
                    WHERE cs.user_id = $1
                """, user_id)
                
                return dict(stats) if stats else {
                    "total_sessions": 0,
                    "active_sessions": 0, 
                    "total_messages": 0,
                    "last_activity": None
                }
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            raise

    # ─── Context Helper Methods ─────────────────────────────────────────────────
    
    def format_messages_for_context(self, messages: List[ChatMessage]) -> List[Dict[str, str]]:
        """Format messages for AI model context (compatible with existing chat format)"""
        formatted = []
        for msg in messages:
            # Only include content in context, not reasoning (reasoning is for insights)
            formatted.append({
                "role": msg.role,
                "content": msg.content
            })
        return formatted
    
    def create_message_from_chat_response(self, session_id: str, user_id: int, role: str, 
                                        content: str, reasoning: Optional[str] = None,
                                        model_used: Optional[str] = None, 
                                        input_type: str = 'text',
                                        metadata: Optional[Dict[str, Any]] = None) -> ChatMessage:
        """Helper to create ChatMessage from chat response"""
        return ChatMessage(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            reasoning=reasoning,
            model_used=model_used,
            input_type=input_type,
            metadata=metadata or {}
        )