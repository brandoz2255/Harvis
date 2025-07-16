"""
Chat History Module

A robust chat history implementation following LangChain patterns
for persistent storage and retrieval of chat messages.
"""

from .manager import ChatHistoryManager
from .models import (
    ChatSession, 
    ChatMessage, 
    CreateSessionRequest, 
    CreateMessageRequest,
    MessageHistoryResponse,
    SessionListResponse
)
from .exceptions import ChatHistoryError, SessionNotFoundError, MessageNotFoundError

__all__ = [
    "ChatHistoryManager",
    "ChatSession", 
    "ChatMessage",
    "CreateSessionRequest",
    "CreateMessageRequest",
    "MessageHistoryResponse",
    "SessionListResponse",
    "ChatHistoryError",
    "SessionNotFoundError", 
    "MessageNotFoundError"
]