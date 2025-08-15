"""
Pydantic models for chat history
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, Field, validator


class ChatSession(BaseModel):
    """Model for a chat session"""
    id: UUID
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    message_count: int = 0
    model_used: Optional[str] = None
    is_active: bool = True
    
    class Config:
        from_attributes = True


class ChatMessage(BaseModel):
    """Model for a chat message"""
    id: Optional[int] = None
    session_id: UUID
    user_id: int
    role: str = Field(..., pattern=r'^(user|assistant|system)$')
    content: str
    reasoning: Optional[str] = None
    model_used: Optional[str] = None
    input_type: str = Field(default='text', pattern=r'^(text|voice|screen)$')
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
        
    @validator('metadata', pre=True)
    def validate_metadata(cls, v):
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v if isinstance(v, dict) else {}


class CreateSessionRequest(BaseModel):
    """Request model for creating a new chat session"""
    title: str = "New Chat"
    model_used: Optional[str] = None


class CreateMessageRequest(BaseModel):
    """Request model for creating a new message"""
    session_id: UUID
    role: str = Field(..., pattern=r'^(user|assistant|system)$')
    content: str
    reasoning: Optional[str] = None
    model_used: Optional[str] = None
    input_type: str = Field(default='text', pattern=r'^(text|voice|screen)$')
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MessageHistoryResponse(BaseModel):
    """Response model for message history"""
    messages: List[ChatMessage]
    session: Optional[ChatSession] = None
    total_count: int = 0
    has_more: bool = False
    
    
class SessionListResponse(BaseModel):
    """Response model for session list"""
    sessions: List[ChatSession]
    total_count: int = 0
    has_more: bool = False