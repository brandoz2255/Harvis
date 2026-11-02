"""
Pydantic models for NotebookLM feature
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from enum import Enum
import json

from .chat_config import MAX_LANGUAGE_CHARS, MAX_PERSONA_CHARS, ChatLength, ChatStyle


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
    PPTX = "pptx"
    XLSX = "xlsx"
    EPUB = "epub"


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
    emoji: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    source_count: Optional[int] = 0
    note_count: Optional[int] = 0
    # Configure Chat / output language; None when the notebook predates the columns or the
    # query did not select them.
    chat_persona: Optional[str] = None
    chat_style: Optional[str] = None
    chat_length: Optional[str] = None
    output_language: Optional[str] = None
    # Set by GET /{id} for the caller: "owner" / "editor" / "viewer" / "chat_only". None elsewhere.
    role: Optional[str] = None
    is_owner: Optional[bool] = None

    class Config:
        from_attributes = True


class CreateNotebookRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    emoji: Optional[str] = Field(None, max_length=16)


class UpdateNotebookRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    emoji: Optional[str] = Field(None, max_length=16)
    chat_persona: Optional[str] = Field(None, max_length=MAX_PERSONA_CHARS)
    chat_style: Optional[ChatStyle] = None
    chat_length: Optional[ChatLength] = None
    output_language: Optional[str] = Field(None, max_length=MAX_LANGUAGE_CHARS)


class ChatConfigResponse(BaseModel):
    """What the notebook's chat is configured to do; ``output_language`` None = the question's language."""
    persona: Optional[str] = None
    style: ChatStyle = "default"
    length: ChatLength = "default"
    output_language: Optional[str] = None


class ChatConfigUpdate(BaseModel):
    """Fields left out are unchanged. An empty ``persona`` or ``output_language`` clears it."""
    persona: Optional[str] = Field(None, max_length=MAX_PERSONA_CHARS)
    style: Optional[ChatStyle] = None
    length: Optional[ChatLength] = None
    output_language: Optional[str] = Field(None, max_length=MAX_LANGUAGE_CHARS)


class AutonameResponse(BaseModel):
    title: str
    emoji: Optional[str] = None


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
    # Cosine similarity for vector search; the fused (RRF) rank score for hybrid search.
    score: float
    source_title: Optional[str] = None
    # Cosine similarity of the passage to the query when known, None for keyword-only hits.
    vector_score: Optional[float] = None


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
    # Where the passage sits in the stored source text; text copied from the source, so the
    # chat_only role must never receive ``snippet`` (see notebooks.access).
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    snippet: Optional[str] = None

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
    top_k: Optional[int] = Field(None, ge=1, le=10)  # None: the configured passage limit
    include_reasoning: bool = False
    # Read only these sources (the Sources tab's Off level leaves the rest out). None or empty: the whole notebook.
    source_ids: Optional[List[str]] = Field(None, max_length=200)
    # Sources at the Summary level: the model reads each one's stored summary instead of searched passages.
    # Meant as a subset of source_ids (or of the whole notebook when source_ids is left out).
    summary_source_ids: Optional[List[str]] = Field(None, max_length=200)


class NotebookChatResponse(BaseModel):
    answer: str
    reasoning: Optional[str] = None
    citations: List[Citation] = []
    model_used: str
    message_id: UUID
    raw_chunks: Optional[List[ChunkWithScore]] = None
    # No passage was close enough to the question, so no model was asked (answer is the refusal).
    refused: bool = False
    # The model answered but cited none of the passages it was given.
    unsupported: bool = False
    # What the answer was built from when summaries were involved (see summary_context); None otherwise.
    context: Optional[Dict[str, Any]] = None

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
    BRIEF = "brief"
    CRITIQUE = "critique"


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
