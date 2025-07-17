"""
Custom exceptions for chat history module
"""


class ChatHistoryError(Exception):
    """Base exception for chat history operations"""
    pass


class SessionNotFoundError(ChatHistoryError):
    """Raised when a chat session is not found"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session {session_id} not found")


class MessageNotFoundError(ChatHistoryError):
    """Raised when a message is not found"""
    
    def __init__(self, message_id: int):
        self.message_id = message_id
        super().__init__(f"Message {message_id} not found")


class DatabaseError(ChatHistoryError):
    """Raised when database operations fail"""
    pass


class ValidationError(ChatHistoryError):
    """Raised when validation fails"""
    pass