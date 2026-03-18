"""
NotebookLM-style notebooks module for Harvis AI
Provides RAG-based chat over user-uploaded sources with notes management

Enhanced with Open Notebook integration:
- LangGraph transformations (summarize, key points, questions, etc.)
- Podcast generation from notebook content
- YouTube source ingestion
"""

from .router import router as notebooks_router
from .models import (
    Notebook, NotebookSource, NotebookChunk, NotebookNote, NotebookChatMessage,
    CreateNotebookRequest, UpdateNotebookRequest,
    CreateNoteRequest, UpdateNoteRequest,
    NotebookChatRequest, NotebookChatResponse,
    SourceUploadResponse, IngestionStatusResponse,
    # Open Notebook integration models
    TransformationType, TransformationRequest, Transformation, TransformationListResponse,
    PodcastStyle, PodcastStatus, PodcastRequest, Podcast, PodcastListResponse,
    YouTubeSourceRequest
)
from .manager import NotebookManager

__all__ = [
    'notebooks_router',
    'NotebookManager',
    'Notebook', 'NotebookSource', 'NotebookChunk', 'NotebookNote', 'NotebookChatMessage',
    'CreateNotebookRequest', 'UpdateNotebookRequest',
    'CreateNoteRequest', 'UpdateNoteRequest',
    'NotebookChatRequest', 'NotebookChatResponse',
    'SourceUploadResponse', 'IngestionStatusResponse',
    # Open Notebook integration
    'TransformationType', 'TransformationRequest', 'Transformation', 'TransformationListResponse',
    'PodcastStyle', 'PodcastStatus', 'PodcastRequest', 'Podcast', 'PodcastListResponse',
    'YouTubeSourceRequest'
]
