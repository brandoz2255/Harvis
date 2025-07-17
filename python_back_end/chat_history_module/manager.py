"""
Chat History Manager - High-level interface for chat history operations
"""

import logging
from typing import List, Optional, Dict, Any
from uuid import UUID
from asyncpg import Pool
import json

from .storage import ChatHistoryStorage
from .models import (
    ChatSession, ChatMessage, CreateSessionRequest, CreateMessageRequest,
    MessageHistoryResponse, SessionListResponse
)
from .exceptions import ChatHistoryError, SessionNotFoundError, MessageNotFoundError

logger = logging.getLogger(__name__)


class ChatHistoryManager:
    """
    High-level manager for chat history operations.
    Follows LangChain patterns for persistent chat message storage.
    """
    
    def __init__(self, db_pool: Pool):
        self.storage = ChatHistoryStorage(db_pool)
    
    async def create_session(self, user_id: int, title: str = "New Chat", model_used: Optional[str] = None) -> ChatSession:
        """
        Create a new chat session for a user.
        
        Args:
            user_id: The user ID
            title: Session title (default: "New Chat")
            model_used: AI model used in this session
            
        Returns:
            ChatSession: The created session
            
        Raises:
            ChatHistoryError: If session creation fails
        """
        try:
            request = CreateSessionRequest(title=title, model_used=model_used)
            session = await self.storage.create_session(user_id, request)
            
            logger.info(f"Created new chat session {session.id} for user {user_id}")
            return session
            
        except Exception as e:
            logger.error(f"Failed to create session for user {user_id}: {e}")
            raise ChatHistoryError(f"Failed to create session: {e}")
    
    async def get_session(self, session_id: UUID, user_id: int) -> ChatSession:
        """
        Get a chat session by ID.
        
        Args:
            session_id: The session UUID
            user_id: The user ID (for authorization)
            
        Returns:
            ChatSession: The session details
            
        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        return await self.storage.get_session(session_id, user_id)
    
    async def get_user_sessions(self, user_id: int, limit: int = 50, offset: int = 0) -> SessionListResponse:
        """
        Get all sessions for a user with pagination.
        
        Args:
            user_id: The user ID
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip
            
        Returns:
            SessionListResponse: List of sessions with pagination info
        """
        try:
            sessions = await self.storage.get_user_sessions(user_id, limit, offset)
            
            # Check if there are more sessions
            has_more = len(sessions) == limit
            
            return SessionListResponse(
                sessions=sessions,
                total_count=len(sessions),
                has_more=has_more
            )
            
        except Exception as e:
            logger.error(f"Failed to get sessions for user {user_id}: {e}")
            raise ChatHistoryError(f"Failed to get sessions: {e}")
    
    async def update_session_title(self, session_id: UUID, user_id: int, title: str) -> ChatSession:
        """
        Update a session's title.
        
        Args:
            session_id: The session UUID
            user_id: The user ID (for authorization)
            title: New title
            
        Returns:
            ChatSession: The updated session
            
        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        return await self.storage.update_session_title(session_id, user_id, title)
    
    async def delete_session(self, session_id: UUID, user_id: int) -> bool:
        """
        Delete a chat session (soft delete).
        
        Args:
            session_id: The session UUID
            user_id: The user ID (for authorization)
            
        Returns:
            bool: True if deletion was successful
            
        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        try:
            result = await self.storage.delete_session(session_id, user_id)
            
            if result:
                logger.info(f"Deleted session {session_id} for user {user_id}")
            else:
                logger.warning(f"Failed to delete session {session_id} for user {user_id}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            raise ChatHistoryError(f"Failed to delete session: {e}")
    
    async def add_message(self, user_id: int, session_id: UUID, role: str, content: str, 
                         reasoning: Optional[str] = None, model_used: Optional[str] = None,
                         input_type: str = "text", metadata: Optional[Dict[str, Any]] = None) -> ChatMessage:
        """
        Add a message to a chat session.
        
        Args:
            user_id: The user ID
            session_id: The session UUID
            role: Message role (user, assistant, system)
            content: Message content
            reasoning: Optional reasoning content for AI models
            model_used: AI model used to generate this message
            input_type: Type of input (text, voice, screen)
            metadata: Additional metadata
            
        Returns:
            ChatMessage: The created message
            
        Raises:
            SessionNotFoundError: If session doesn't exist
            ChatHistoryError: If message creation fails
        """
        try:
            request = CreateMessageRequest(
                session_id=session_id,
                role=role,
                content=content,
                reasoning=reasoning,
                model_used=model_used,
                input_type=input_type,
                metadata=metadata or {}
            )
            
            message = await self.storage.add_message(user_id, request)
            
            logger.debug(f"Added {role} message to session {session_id}")
            return message
            
        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to add message to session {session_id}: {e}")
            raise ChatHistoryError(f"Failed to add message: {e}")
    
    async def get_session_messages(self, session_id: UUID, user_id: int, 
                                  limit: int = 100, offset: int = 0) -> MessageHistoryResponse:
        """
        Get messages for a session with pagination.
        
        Args:
            session_id: The session UUID
            user_id: The user ID (for authorization)
            limit: Maximum number of messages to return
            offset: Number of messages to skip
            
        Returns:
            MessageHistoryResponse: Messages with session info and pagination
            
        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        try:
            # Get session info
            session = await self.storage.get_session(session_id, user_id)
            
            # Get messages
            messages = await self.storage.get_session_messages(session_id, user_id, limit, offset)
            
            # Get total count
            total_count = await self.storage.get_message_count(session_id, user_id)
            
            # Check if there are more messages
            has_more = offset + len(messages) < total_count
            
            logger.debug(f"Retrieved {len(messages)} messages for session {session_id}")
            
            return MessageHistoryResponse(
                messages=messages,
                session=session,
                total_count=total_count,
                has_more=has_more
            )
            
        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get messages for session {session_id}: {e}")
            raise ChatHistoryError(f"Failed to get messages: {e}")
    
    async def clear_session_messages(self, session_id: UUID, user_id: int) -> bool:
        """
        Clear all messages from a session.
        
        Args:
            session_id: The session UUID
            user_id: The user ID (for authorization)
            
        Returns:
            bool: True if clearing was successful
            
        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        try:
            result = await self.storage.clear_session_messages(session_id, user_id)
            
            if result:
                logger.info(f"Cleared messages for session {session_id}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to clear messages for session {session_id}: {e}")
            raise ChatHistoryError(f"Failed to clear messages: {e}")
    
    # LangChain-compatible methods
    async def add_user_message(self, session_id: UUID, user_id: int, content: str, 
                              input_type: str = "text", metadata: Optional[Dict[str, Any]] = None) -> ChatMessage:
        """
        Add a user message (LangChain-compatible).
        
        Args:
            session_id: The session UUID
            user_id: The user ID
            content: Message content
            input_type: Type of input (text, voice, screen)
            metadata: Additional metadata
            
        Returns:
            ChatMessage: The created message
        """
        return await self.add_message(
            user_id=user_id,
            session_id=session_id,
            role="user",
            content=content,
            input_type=input_type,
            metadata=metadata
        )
    
    async def add_ai_message(self, session_id: UUID, user_id: int, content: str, 
                            reasoning: Optional[str] = None, model_used: Optional[str] = None,
                            metadata: Optional[Dict[str, Any]] = None) -> ChatMessage:
        """
        Add an AI message (LangChain-compatible).
        
        Args:
            session_id: The session UUID
            user_id: The user ID
            content: Message content
            reasoning: Optional reasoning content
            model_used: AI model used
            metadata: Additional metadata
            
        Returns:
            ChatMessage: The created message
        """
        return await self.add_message(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=content,
            reasoning=reasoning,
            model_used=model_used,
            metadata=metadata
        )
    
    async def get_messages(self, session_id: UUID, user_id: int, limit: int = 100) -> List[ChatMessage]:
        """
        Get messages for a session (LangChain-compatible).
        
        Args:
            session_id: The session UUID
            user_id: The user ID
            limit: Maximum number of messages to return
            
        Returns:
            List[ChatMessage]: List of messages
        """
        response = await self.get_session_messages(session_id, user_id, limit=limit)
        return response.messages
    
    # Additional methods for compatibility with existing main.py
    async def get_recent_messages(self, session_id: UUID, user_id: int, limit: int = 20) -> List[ChatMessage]:
        """
        Get recent messages for a session (for context).
        
        Args:
            session_id: The session UUID
            user_id: The user ID
            limit: Maximum number of recent messages to return
            
        Returns:
            List[ChatMessage]: List of recent messages
        """
        return await self.get_messages(session_id, user_id, limit=limit)
    
    def format_messages_for_context(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """
        Format messages for AI context (LangChain-compatible).
        
        Args:
            messages: List of ChatMessage objects
            
        Returns:
            List[Dict[str, Any]]: Formatted messages for AI context
        """
        formatted = []
        for message in messages:
            formatted.append({
                "role": message.role,
                "content": message.content,
                "timestamp": message.created_at.isoformat() if message.created_at else None,
                "model_used": message.model_used,
                "input_type": message.input_type
            })
        return formatted
    
    def create_message_from_chat_response(self, session_id: UUID, user_id: int, role: str, 
                                         content: str, model_used: Optional[str] = None,
                                         input_type: str = "text", reasoning: Optional[str] = None,
                                         metadata: Optional[Dict[str, Any]] = None) -> ChatMessage:
        """
        Create a ChatMessage object from chat response data.
        
        Args:
            session_id: The session UUID
            user_id: The user ID
            role: Message role (user, assistant, system)
            content: Message content
            model_used: AI model used
            input_type: Type of input (text, voice, screen)
            reasoning: Optional reasoning content
            metadata: Additional metadata
            
        Returns:
            ChatMessage: The created message object (not yet persisted)
        """
        from .models import CreateMessageRequest
        
        request = CreateMessageRequest(
            session_id=session_id,
            role=role,
            content=content,
            reasoning=reasoning,
            model_used=model_used,
            input_type=input_type,
            metadata=metadata or {}
        )
        
        # Create a temporary message object for compatibility
        # This would typically be persisted using add_message()
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
    
    async def search_messages(self, user_id: int, query: str, limit: int = 50) -> List[ChatMessage]:
        """
        Search messages by content (basic implementation).
        
        Args:
            user_id: The user ID
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List[ChatMessage]: Matching messages
        """
        try:
            async with self.storage.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT m.id, m.session_id, m.user_id, m.role, m.content, m.reasoning, 
                           m.model_used, m.input_type, m.metadata, m.created_at
                    FROM chat_messages m
                    JOIN chat_sessions s ON m.session_id = s.id
                    WHERE m.user_id = $1 AND s.is_active = TRUE
                    AND (m.content ILIKE $2 OR m.reasoning ILIKE $2)
                    ORDER BY m.created_at DESC
                    LIMIT $3
                """, user_id, f"%{query}%", limit)
                
                messages = []
                for row in rows:
                    message_data = dict(row)
                    if isinstance(message_data['metadata'], str):
                        import json
                        try:
                            message_data['metadata'] = json.loads(message_data['metadata'])
                        except json.JSONDecodeError:
                            message_data['metadata'] = {}
                    messages.append(ChatMessage(**message_data))
                
                return messages
                
        except Exception as e:
            logger.error(f"Error searching messages: {e}")
            raise ChatHistoryError(f"Failed to search messages: {e}")
    
    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Get user statistics.
        
        Args:
            user_id: The user ID
            
        Returns:
            Dict[str, Any]: User statistics
        """
        try:
            async with self.storage.db_pool.acquire() as conn:
                stats = await conn.fetchrow("""
                    SELECT 
                        COUNT(DISTINCT s.id) as total_sessions,
                        COUNT(m.id) as total_messages,
                        MAX(s.last_message_at) as last_activity
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON s.id = m.session_id
                    WHERE s.user_id = $1 AND s.is_active = TRUE
                """, user_id)
                
                return {
                    "total_sessions": stats['total_sessions'] or 0,
                    "total_messages": stats['total_messages'] or 0,
                    "last_activity": stats['last_activity'].isoformat() if stats['last_activity'] else None
                }
                
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            raise ChatHistoryError(f"Failed to get user stats: {e}")
    
    async def add_messages_batch(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        """
        Add multiple messages in a batch.
        
        Args:
            messages: List of ChatMessage objects to add
            
        Returns:
            List[ChatMessage]: List of created messages
        """
        try:
            results = []
            for message in messages:
                # Convert to CreateMessageRequest and add
                request = CreateMessageRequest(
                    session_id=message.session_id,
                    role=message.role,
                    content=message.content,
                    reasoning=message.reasoning,
                    model_used=message.model_used,
                    input_type=message.input_type,
                    metadata=message.metadata
                )
                created_message = await self.storage.add_message(message.user_id, request)
                results.append(created_message)
            
            logger.info(f"Added batch of {len(messages)} messages")
            return results
            
        except Exception as e:
            logger.error(f"Error adding message batch: {e}")
            raise ChatHistoryError(f"Failed to add message batch: {e}")
    
    async def get_or_create_session(self, session_id: UUID, user_id: int, title: str = "New Chat") -> ChatSession:
        """
        Get session or create it if it doesn't exist.
        
        Args:
            session_id: The session UUID
            user_id: The user ID
            title: Title for new session if created
            
        Returns:
            ChatSession: The existing or newly created session
        """
        try:
            # Try to get existing session
            session = await self.storage.get_session(session_id, user_id)
            return session
            
        except SessionNotFoundError:
            # Session doesn't exist, create new one
            request = CreateSessionRequest(title=title)
            return await self.storage.create_session(user_id, request)
        
        except Exception as e:
            logger.error(f"Error getting or creating session: {e}")
            raise ChatHistoryError(f"Failed to get or create session: {e}")