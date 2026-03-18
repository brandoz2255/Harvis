"""
Pydantic models for NotebookLM feature
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from enum import Enum
import json


# Custom JSON encoder for UUIDs
class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


class SourceType(str, Enum):
    PDF = "pdf"
    TEXT = "text"
    URL = "url"
    MARKDOWN = "markdown"
    DOC = "doc"
    TRANSCRIPT = "transcript"
    AUDIO = "audio"
    YOUTUBE = "youtube"
    IMAGE = "image"


class SourceStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class NoteType(str, Enum):
    USER_NOTE = "user_note"
    AI_NOTE = "ai_note"
    SUMMARY = "summary"
    HIGHLIGHT = "highlight"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ─── Notebook Models ───────────────────────────────────────────────────────────

class Notebook(BaseModel):
    id: UUID
    user_id: int
    title: str
    description: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    source_count: Optional[int] = 0
    note_count: Optional[int] = 0

    class Config:
        from_attributes = True


class CreateNotebookRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)


class UpdateNotebookRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)


class NotebookListResponse(BaseModel):
    notebooks: List[Notebook]
    total_count: int
    has_more: bool


# ─── Source Models ─────────────────────────────────────────────────────────────

class NotebookSource(BaseModel):
    id: UUID
    notebook_id: UUID
    type: SourceType
    title: Optional[str] = None
    storage_path: Optional[str] = None
    original_filename: Optional[str] = None
    metadata: Dict[str, Any] = {}
    status: SourceStatus = SourceStatus.PENDING
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    chunk_count: Optional[int] = 0

    class Config:
        from_attributes = True


class SourceUploadResponse(BaseModel):
    source: NotebookSource
    message: str


class SourceUrlRequest(BaseModel):
    url: str = Field(..., min_length=1)
    title: Optional[str] = None


class IngestionStatusResponse(BaseModel):
    source_id: UUID
    status: SourceStatus
    progress: Optional[float] = None  # 0.0 to 1.0
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None


# ─── Chunk Models ──────────────────────────────────────────────────────────────

class NotebookChunk(BaseModel):
    id: UUID
    source_id: UUID
    notebook_id: UUID
    content: str
    metadata: Dict[str, Any] = {}
    chunk_index: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChunkWithScore(BaseModel):
    """Chunk with similarity score for RAG retrieval"""
    chunk: NotebookChunk
    score: float
    source_title: Optional[str] = None


# ─── Note Models ───────────────────────────────────────────────────────────────

class NotebookNote(BaseModel):
    id: UUID
    notebook_id: UUID
    user_id: int
    type: NoteType
    title: Optional[str] = None
    content: str
    source_meta: Dict[str, Any] = {}
    is_pinned: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreateNoteRequest(BaseModel):
    type: NoteType = NoteType.USER_NOTE
    title: Optional[str] = Field(None, max_length=255)
    content: str = Field(..., min_length=1)
    source_meta: Optional[Dict[str, Any]] = None
    is_pinned: bool = False


class UpdateNoteRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    content: Optional[str] = None
    is_pinned: Optional[bool] = None


class NoteListResponse(BaseModel):
    notes: List[NotebookNote]
    total_count: int
    has_more: bool


# ─── Chat Models ───────────────────────────────────────────────────────────────

class Citation(BaseModel):
    """Citation reference to a source"""
    source_id: UUID
    source_title: Optional[str] = None
    chunk_id: Optional[UUID] = None
    page: Optional[int] = None
    section: Optional[str] = None
    quote: Optional[str] = None

    model_config = ConfigDict(
        json_encoders={UUID: str},
        from_attributes=True
    )


class NotebookChatMessage(BaseModel):
    id: UUID
    notebook_id: UUID
    user_id: int
    role: MessageRole
    content: str
    reasoning: Optional[str] = None
    citations: List[Citation] = []
    model_used: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NotebookChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    model: str = "gpt-oss:latest"  # Default to fastest available model
    top_k: int = Field(3, ge=1, le=10)  # Limit chunks for speed
    include_reasoning: bool = False


class NotebookChatResponse(BaseModel):
    answer: str
    reasoning: Optional[str] = None
    citations: List[Citation] = []
    model_used: str
    message_id: UUID
    raw_chunks: Optional[List[ChunkWithScore]] = None

    model_config = ConfigDict(
        json_encoders={UUID: str},
        from_attributes=True
    )


class ChatHistoryResponse(BaseModel):
    messages: List[NotebookChatMessage]
    total_count: int
    has_more: bool


# ─── Search Models ─────────────────────────────────────────────────────────────

class SearchType(str, Enum):
    TEXT = "text"
    VECTOR = "vector"


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    type: SearchType = SearchType.TEXT
    limit: int = Field(50, ge=1, le=200)
    search_sources: bool = True
    search_notes: bool = True
    minimum_score: float = Field(0.2, ge=0.0, le=1.0)


class SearchResult(BaseModel):
    kind: str  # "source" | "note"
    notebook_id: UUID
    notebook_title: Optional[str] = None

    source_id: Optional[UUID] = None
    note_id: Optional[UUID] = None

    title: Optional[str] = None
    snippet: Optional[str] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    results: List[SearchResult]
    total_count: int
    search_type: SearchType


# ─── Transformation Models ────────────────────────────────────────────────────

class TransformationType(str, Enum):
    SUMMARIZE = "summarize"
    KEY_POINTS = "key_points"
    QUESTIONS = "questions"
    OUTLINE = "outline"
    SIMPLIFY = "simplify"
    CRITIQUE = "critique"
    ACTION_ITEMS = "action_items"
    CUSTOM = "custom"


class TransformationRequest(BaseModel):
    source_id: Optional[UUID] = None
    note_id: Optional[UUID] = None
    transformation: TransformationType
    custom_prompt: Optional[str] = Field(None, max_length=5000)
    model: str = "codellama:7b"  # Default to available model


class Transformation(BaseModel):
    id: UUID
    notebook_id: UUID
    source_id: Optional[UUID] = None
    note_id: Optional[UUID] = None
    user_id: int
    transformation_type: TransformationType
    original_content: str
    transformed_content: str
    model_used: Optional[str] = None
    custom_prompt: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TransformationListResponse(BaseModel):
    transformations: List[Transformation]
    total_count: int
    has_more: bool


# ─── Podcast Models ───────────────────────────────────────────────────────────

class PodcastStyle(str, Enum):
    CONVERSATIONAL = "conversational"
    INTERVIEW = "interview"
    EDUCATIONAL = "educational"
    DEBATE = "debate"
    STORYTELLING = "storytelling"


class PodcastStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    ERROR = "error"


class SpeakerProfile(BaseModel):
    id: Optional[UUID] = None
    name: str
    role: str = "Speaker"
    personality: Optional[str] = None
    voice_id: Optional[str] = None


class PodcastRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    style: PodcastStyle = PodcastStyle.CONVERSATIONAL
    speakers: int = Field(2, ge=1, le=4)
    duration_minutes: int = Field(10, ge=1, le=60)
    custom_speakers: Optional[List[SpeakerProfile]] = None
    source_ids: Optional[List[UUID]] = None  # Optional list of specific sources to include
    note_ids: Optional[List[UUID]] = None  # Optional list of notes to include in podcast


class PodcastTranscriptEntry(BaseModel):
    speaker: str
    dialogue: str


class Podcast(BaseModel):
    id: UUID
    notebook_id: UUID
    user_id: int
    title: str
    status: PodcastStatus = PodcastStatus.PENDING
    style: PodcastStyle = PodcastStyle.CONVERSATIONAL
    speakers: int = 2
    duration_minutes: int = 10
    audio_path: Optional[str] = None
    transcript: List[PodcastTranscriptEntry] = []
    outline: Optional[str] = None
    error_message: Optional[str] = None
    duration_seconds: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PodcastListResponse(BaseModel):
    podcasts: List[Podcast]
    total_count: int
    has_more: bool


# ─── YouTube Source Models ────────────────────────────────────────────────────

class YouTubeSourceRequest(BaseModel):
    url: str = Field(..., min_length=1)
    title: Optional[str] = None
