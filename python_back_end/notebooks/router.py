"""
FastAPI Router for NotebookLM feature
All endpoints are JWT-protected and user-scoped
"""

import logging
import os
import uuid
import shutil
import asyncio
from typing import List, Optional, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .models import (
    Notebook, NotebookSource, NotebookNote, NotebookChatMessage,
    CreateNotebookRequest, UpdateNotebookRequest,
    CreateNoteRequest, UpdateNoteRequest,
    NotebookChatRequest, NotebookChatResponse,
    SourceUploadResponse, IngestionStatusResponse,
    NotebookListResponse, NoteListResponse, ChatHistoryResponse,
    SourceType, SourceStatus, NoteType, SourceUrlRequest,
    # Open Notebook integration models
    TransformationType, TransformationRequest, Transformation, TransformationListResponse,
    PodcastStyle, PodcastStatus, PodcastRequest, Podcast, PodcastListResponse,
    YouTubeSourceRequest
)
from .manager import NotebookManager, NotebookNotFoundError, SourceNotFoundError, NoteNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])

# Storage configuration
NOTEBOOK_STORAGE_PATH = os.getenv("NOTEBOOK_STORAGE_PATH", "/data/notebooks")


# ─── Dependencies ──────────────────────────────────────────────────────────────

def get_notebook_manager(request: Request) -> NotebookManager:
    """Get NotebookManager instance from app state"""
    manager = getattr(request.app.state, 'notebook_manager', None)
    if not manager:
        # Initialize if not exists
        pool = getattr(request.app.state, 'pg_pool', None)
        if pool:
            manager = NotebookManager(pool)
            request.app.state.notebook_manager = manager
        else:
            raise HTTPException(status_code=503, detail="Database not available")
    return manager


async def get_current_user_from_request(request: Request) -> Dict:
    """Get current user from request - uses auth_optimized module"""
    from auth_optimized import get_current_user_optimized
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    security = HTTPBearer(auto_error=False)

    # Get credentials from Authorization header
    auth_header = request.headers.get("Authorization")
    credentials = None
    if auth_header and auth_header.startswith("Bearer "):
        from fastapi.security import HTTPAuthorizationCredentials
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=auth_header[7:]
        )

    # Get database pool
    pool = getattr(request.app.state, 'pg_pool', None)

    return await get_current_user_optimized(request, credentials, pool)


# ─── Notebook CRUD ─────────────────────────────────────────────────────────────

@router.get("", response_model=NotebookListResponse)
async def list_notebooks(
    limit: int = 50,
    offset: int = 0,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """List all notebooks for the current user"""
    try:
        notebooks, total = await manager.list_notebooks(
            user_id=current_user["id"],
            limit=limit,
            offset=offset
        )
        return NotebookListResponse(
            notebooks=notebooks,
            total_count=total,
            has_more=offset + len(notebooks) < total
        )
    except Exception as e:
        logger.error(f"Failed to list notebooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=Notebook)
async def create_notebook(
    request_body: CreateNotebookRequest,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Create a new notebook"""
    try:
        notebook = await manager.create_notebook(
            user_id=current_user["id"],
            request=request_body
        )
        logger.info(f"Created notebook {notebook.id} for user {current_user['id']}")
        return notebook
    except Exception as e:
        logger.error(f"Failed to create notebook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}", response_model=Notebook)
async def get_notebook(
    notebook_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Get a single notebook by ID"""
    try:
        return await manager.get_notebook(notebook_id, current_user["id"])
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to get notebook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{notebook_id}", response_model=Notebook)
async def update_notebook(
    notebook_id: UUID,
    request_body: UpdateNotebookRequest,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Update a notebook's title or description"""
    try:
        return await manager.update_notebook(notebook_id, current_user["id"], request_body)
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to update notebook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}")
async def delete_notebook(
    notebook_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Delete a notebook and all its contents"""
    try:
        deleted = await manager.delete_notebook(notebook_id, current_user["id"])
        if not deleted:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return {"message": "Notebook deleted successfully"}
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to delete notebook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Source Management ─────────────────────────────────────────────────────────

@router.get("/{notebook_id}/sources", response_model=List[NotebookSource])
async def list_sources(
    notebook_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """List all sources for a notebook"""
    try:
        return await manager.list_sources(notebook_id, current_user["id"])
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to list sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{notebook_id}/sources/upload", response_model=SourceUploadResponse)
async def upload_source(
    notebook_id: UUID,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    background_tasks: BackgroundTasks = None,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Upload a file as a source (PDF, text, markdown, doc)"""
    try:
        # Verify notebook ownership
        await manager.get_notebook(notebook_id, current_user["id"])

        # Determine source type from file extension
        filename = file.filename or "unknown"
        ext = filename.lower().split(".")[-1] if "." in filename else ""

        type_map = {
            "pdf": SourceType.PDF,
            "txt": SourceType.TEXT,
            "md": SourceType.MARKDOWN,
            "markdown": SourceType.MARKDOWN,
            "doc": SourceType.DOC,
            "docx": SourceType.DOC,
        }

        source_type = type_map.get(ext, SourceType.TEXT)

        # Create storage directory
        user_dir = os.path.join(NOTEBOOK_STORAGE_PATH, str(current_user["id"]), str(notebook_id))
        os.makedirs(user_dir, exist_ok=True)

        # Save file
        file_id = str(uuid.uuid4())
        storage_path = os.path.join(user_dir, f"{file_id}.{ext}")

        with open(storage_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Create source record
        source = await manager.create_source(
            notebook_id=notebook_id,
            user_id=current_user["id"],
            source_type=source_type,
            title=title or filename,
            storage_path=storage_path,
            original_filename=filename,
            metadata={"size": len(content), "extension": ext}
        )

        # Start ingestion in background
        if background_tasks:
            from .ingestion import run_ingestion_task
            background_tasks.add_task(
                run_ingestion_task,
                manager,
                source.id,
                current_user["id"]
            )

        return SourceUploadResponse(
            source=source,
            message="Source uploaded successfully. Processing in background."
        )

    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to upload source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{notebook_id}/sources/url", response_model=SourceUploadResponse)
async def add_url_source(
    notebook_id: UUID,
    url_request: SourceUrlRequest,
    background_tasks: BackgroundTasks = None,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Add a URL as a source"""
    try:
        # Verify notebook ownership
        await manager.get_notebook(notebook_id, current_user["id"])

        # Create source record with URL as storage_path
        source = await manager.create_source(
            notebook_id=notebook_id,
            user_id=current_user["id"],
            source_type=SourceType.URL,
            title=url_request.title or url_request.url,
            storage_path=url_request.url,
            metadata={"url": url_request.url}
        )

        # Start ingestion in background
        if background_tasks:
            from .ingestion import run_ingestion_task
            background_tasks.add_task(
                run_ingestion_task,
                manager,
                source.id,
                current_user["id"]
            )

        return SourceUploadResponse(
            source=source,
            message="URL source added successfully. Processing in background."
        )

    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to add URL source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{notebook_id}/sources/text", response_model=SourceUploadResponse)
async def add_text_source(
    notebook_id: UUID,
    title: str = Form(...),
    content: str = Form(...),
    background_tasks: BackgroundTasks = None,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Add plain text or pasted content as a source"""
    try:
        # Verify notebook ownership
        await manager.get_notebook(notebook_id, current_user["id"])

        # Create storage directory
        user_dir = os.path.join(NOTEBOOK_STORAGE_PATH, str(current_user["id"]), str(notebook_id))
        os.makedirs(user_dir, exist_ok=True)

        # Save text to file
        file_id = str(uuid.uuid4())
        storage_path = os.path.join(user_dir, f"{file_id}.txt")

        with open(storage_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Create source record
        source = await manager.create_source(
            notebook_id=notebook_id,
            user_id=current_user["id"],
            source_type=SourceType.TEXT,
            title=title,
            storage_path=storage_path,
            content_text=content,
            metadata={"size": len(content)}
        )

        # Start ingestion in background
        if background_tasks:
            from .ingestion import run_ingestion_task
            background_tasks.add_task(
                run_ingestion_task,
                manager,
                source.id,
                current_user["id"]
            )

        return SourceUploadResponse(
            source=source,
            message="Text source added successfully. Processing in background."
        )

    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to add text source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}/sources/{source_id}/status", response_model=IngestionStatusResponse)
async def get_source_status(
    notebook_id: UUID,
    source_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Get the ingestion status of a source"""
    try:
        source = await manager.get_source(source_id, current_user["id"])
        return IngestionStatusResponse(
            source_id=source.id,
            status=source.status,
            chunk_count=source.chunk_count,
            error_message=source.error_message
        )
    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    except Exception as e:
        logger.error(f"Failed to get source status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}/sources/{source_id}")
async def delete_source(
    notebook_id: UUID,
    source_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Delete a source and its chunks"""
    try:
        # Get source to find storage path
        source = await manager.get_source(source_id, current_user["id"])

        # Delete from database (cascade deletes chunks)
        deleted = await manager.delete_source(source_id, current_user["id"])

        if not deleted:
            raise HTTPException(status_code=404, detail="Source not found")

        # Delete file from storage if it exists
        if source.storage_path and os.path.exists(source.storage_path):
            try:
                os.remove(source.storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete source file: {e}")

        return {"message": "Source deleted successfully"}

    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    except Exception as e:
        logger.error(f"Failed to delete source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Notes Management ──────────────────────────────────────────────────────────

@router.get("/{notebook_id}/notes", response_model=NoteListResponse)
async def list_notes(
    notebook_id: UUID,
    note_type: Optional[NoteType] = None,
    limit: int = 50,
    offset: int = 0,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """List all notes for a notebook"""
    try:
        notes, total = await manager.list_notes(
            notebook_id=notebook_id,
            user_id=current_user["id"],
            note_type=note_type,
            limit=limit,
            offset=offset
        )
        return NoteListResponse(
            notes=notes,
            total_count=total,
            has_more=offset + len(notes) < total
        )
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to list notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{notebook_id}/notes", response_model=NotebookNote)
async def create_note(
    notebook_id: UUID,
    note_request: CreateNoteRequest,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Create a new note in a notebook"""
    try:
        return await manager.create_note(
            notebook_id=notebook_id,
            user_id=current_user["id"],
            request=note_request
        )
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to create note: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}/notes/{note_id}", response_model=NotebookNote)
async def get_note(
    notebook_id: UUID,
    note_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Get a specific note"""
    try:
        return await manager.get_note(note_id, current_user["id"])
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except Exception as e:
        logger.error(f"Failed to get note: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{notebook_id}/notes/{note_id}", response_model=NotebookNote)
async def update_note(
    notebook_id: UUID,
    note_id: UUID,
    note_request: UpdateNoteRequest,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Update a note"""
    try:
        return await manager.update_note(note_id, current_user["id"], note_request)
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except Exception as e:
        logger.error(f"Failed to update note: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}/notes/{note_id}")
async def delete_note(
    notebook_id: UUID,
    note_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Delete a note"""
    try:
        deleted = await manager.delete_note(note_id, current_user["id"])
        if not deleted:
            raise HTTPException(status_code=404, detail="Note not found")
        return {"message": "Note deleted successfully"}
    except NoteNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")
    except Exception as e:
        logger.error(f"Failed to delete note: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── RAG Chat ──────────────────────────────────────────────────────────────────

@router.post("/{notebook_id}/chat")
async def chat_with_notebook(
    notebook_id: UUID,
    chat_request: NotebookChatRequest,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Chat with a notebook using RAG"""
    try:
        from .rag_chat import RAGChatService

        rag_service = RAGChatService(manager)
        response = await rag_service.chat(
            notebook_id=notebook_id,
            user_id=current_user["id"],
            request=chat_request
        )
        
        # Convert response to dict with proper UUID serialization
        response_dict = {
            "answer": response.answer,
            "reasoning": response.reasoning,
            "citations": [
                {
                    "source_id": str(c.source_id) if c.source_id else None,
                    "source_title": c.source_title,
                    "chunk_id": str(c.chunk_id) if c.chunk_id else None,
                    "page": c.page,
                    "section": c.section,
                    "quote": c.quote
                }
                for c in response.citations
            ],
            "model_used": response.model_used,
            "message_id": str(response.message_id) if response.message_id else None,
        }
        
        # Include raw_chunks if present (for debugging)
        if response.raw_chunks:
            response_dict["raw_chunks"] = [
                {
                    "chunk": {
                        "id": str(c.chunk.id),
                        "source_id": str(c.chunk.source_id),
                        "notebook_id": str(c.chunk.notebook_id),
                        "content": c.chunk.content[:500],  # Truncate for response
                        "chunk_index": c.chunk.chunk_index,
                    },
                    "score": c.score,
                    "source_title": c.source_title
                }
                for c in response.raw_chunks
            ]
        
        return response_dict
        
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to chat with notebook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}/chat/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    notebook_id: UUID,
    limit: int = 50,
    offset: int = 0,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Get chat history for a notebook"""
    try:
        messages, total = await manager.get_chat_history(
            notebook_id=notebook_id,
            user_id=current_user["id"],
            limit=limit,
            offset=offset
        )
        return ChatHistoryResponse(
            messages=messages,
            total_count=total,
            has_more=offset + len(messages) < total
        )
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to get chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}/chat/history")
async def clear_chat_history(
    notebook_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Clear chat history for a notebook"""
    try:
        await manager.clear_chat_history(notebook_id, current_user["id"])
        return {"message": "Chat history cleared"}
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to clear chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Stats & Utilities ─────────────────────────────────────────────────────────

@router.get("/{notebook_id}/stats")
async def get_notebook_stats(
    notebook_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Get statistics for a notebook"""
    try:
        return await manager.get_notebook_stats(notebook_id, current_user["id"])
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to get notebook stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/embedding-status")
async def check_embedding_status():
    """Check Ollama embedding service status and available models"""
    import requests
    import os
    
    ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
    cloud_ollama_url = os.getenv("OLLAMA_CLOUD_URL", "https://coyotegpt.ngrok.app/ollama")
    
    result = {
        "local_ollama": {"url": ollama_url, "status": "unknown", "models": []},
        "cloud_ollama": {"url": cloud_ollama_url, "status": "unknown", "models": []},
        "embedding_models_to_try": ["nomic-embed-text", "mxbai-embed-large", "all-minilm", "llama3.2", "mistral"]
    }
    
    # Check local Ollama
    try:
        response = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            result["local_ollama"]["status"] = "connected"
            result["local_ollama"]["models"] = [m["name"] for m in data.get("models", [])]
        else:
            result["local_ollama"]["status"] = f"error: {response.status_code}"
    except requests.exceptions.ConnectionError:
        result["local_ollama"]["status"] = "connection_refused"
    except Exception as e:
        result["local_ollama"]["status"] = f"error: {str(e)}"
    
    # Check cloud Ollama
    try:
        response = requests.get(f"{cloud_ollama_url}/api/tags", timeout=10)
        if response.status_code == 200:
            data = response.json()
            result["cloud_ollama"]["status"] = "connected"
            result["cloud_ollama"]["models"] = [m["name"] for m in data.get("models", [])]
        else:
            result["cloud_ollama"]["status"] = f"error: {response.status_code}"
    except requests.exceptions.ConnectionError:
        result["cloud_ollama"]["status"] = "connection_refused"
    except Exception as e:
        result["cloud_ollama"]["status"] = f"error: {str(e)}"
    
    # Determine which embedding models are available
    all_models = set(result["local_ollama"]["models"] + result["cloud_ollama"]["models"])
    
    # Check for dedicated embedding models OR any LLM that can generate embeddings
    dedicated_embedding_models = [
        m for m in result["embedding_models_to_try"] 
        if any(m in model or model in m for model in all_models)
    ]
    
    # Any Ollama model can generate embeddings, so list all available
    result["available_embedding_models"] = dedicated_embedding_models if dedicated_embedding_models else list(all_models)
    result["all_available_models"] = list(all_models)
    
    if all_models:
        result["recommendation"] = f"Embedding will use: {list(all_models)[0]} (any Ollama model can generate embeddings)"
    else:
        result["recommendation"] = "No Ollama models available. Please run: ollama pull nomic-embed-text"
    
    return result


# ─── YouTube Sources ──────────────────────────────────────────────────────────

@router.post("/{notebook_id}/sources/youtube", response_model=SourceUploadResponse)
async def add_youtube_source(
    notebook_id: UUID,
    youtube_request: "YouTubeSourceRequest",
    background_tasks: BackgroundTasks = None,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Add a YouTube video as a source (transcript will be extracted)"""
    from .models import YouTubeSourceRequest
    try:
        # Verify notebook ownership
        await manager.get_notebook(notebook_id, current_user["id"])

        # Create source record with YouTube URL
        source = await manager.create_source(
            notebook_id=notebook_id,
            user_id=current_user["id"],
            source_type=SourceType.YOUTUBE,
            title=youtube_request.title or youtube_request.url,
            storage_path=youtube_request.url,
            metadata={"url": youtube_request.url, "type": "youtube"}
        )

        # Start ingestion in background
        if background_tasks:
            from .ingestion import run_ingestion_task
            background_tasks.add_task(
                run_ingestion_task,
                manager,
                source.id,
                current_user["id"]
            )

        return SourceUploadResponse(
            source=source,
            message="YouTube source added successfully. Extracting transcript..."
        )

    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to add YouTube source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Transformations ──────────────────────────────────────────────────────────

@router.get("/transformations/types")
async def list_transformation_types():
    """List available transformation types"""
    from open_notebook.graphs.transform_graph import get_available_transformations
    return {"transformations": get_available_transformations()}


@router.post("/{notebook_id}/sources/{source_id}/transform")
async def transform_source(
    notebook_id: UUID,
    source_id: UUID,
    transform_request: "TransformationRequest",
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Apply an AI transformation to a source"""
    from .models import TransformationRequest, Transformation
    from open_notebook.graphs.transform_graph import build_transform_graph
    
    try:
        # Get source
        source = await manager.get_source(source_id, current_user["id"])
        
        # Get content from source
        async with manager.db_pool.acquire() as conn:
            content_text = await conn.fetchval(
                "SELECT content_text FROM notebook_sources WHERE id = $1",
                source_id
            )
        
        if not content_text:
            raise HTTPException(status_code=400, detail="Source has no content to transform")
        
        # Run transformation
        graph = build_transform_graph()
        result = await graph.ainvoke({
            "content": content_text,
            "transformation": transform_request.transformation.value,
            "model": transform_request.model,
            "custom_prompt": transform_request.custom_prompt
        })
        
        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])
        
        # Save transformation to database
        async with manager.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO notebook_transformations 
                    (notebook_id, source_id, user_id, transformation_type, original_content, transformed_content, model_used, custom_prompt)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id, notebook_id, source_id, note_id, user_id, transformation_type, original_content, transformed_content, model_used, custom_prompt, created_at
            """, notebook_id, source_id, current_user["id"], 
                transform_request.transformation.value, content_text, result["result"],
                transform_request.model, transform_request.custom_prompt)
        
        return dict(row)
        
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    except Exception as e:
        logger.error(f"Transformation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}/transformations")
async def list_transformations(
    notebook_id: UUID,
    limit: int = 50,
    offset: int = 0,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """List transformations for a notebook"""
    try:
        await manager.get_notebook(notebook_id, current_user["id"])
        
        async with manager.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, notebook_id, source_id, note_id, user_id, transformation_type, 
                       original_content, transformed_content, model_used, custom_prompt, created_at
                FROM notebook_transformations
                WHERE notebook_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """, notebook_id, limit, offset)
            
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM notebook_transformations WHERE notebook_id = $1",
                notebook_id
            )
        
        return {
            "transformations": [dict(row) for row in rows],
            "total_count": total,
            "has_more": offset + len(rows) < total
        }
        
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to list transformations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Podcasts ─────────────────────────────────────────────────────────────────

@router.get("/podcasts/styles")
async def list_podcast_styles():
    """List available podcast styles"""
    from open_notebook.podcast import PodcastGenerator
    return {"styles": PodcastGenerator.get_available_styles()}


# Standalone podcast generation endpoint (for Open Notebook integration)
class StandalonePodcastRequest(BaseModel):
    """Request for generating a podcast without notebook ownership verification"""
    notebook_id: str  # String ID from Open Notebook (e.g., "notebook:xyz")
    title: str
    style: str = "conversational"
    speakers: int = 2
    duration_minutes: int = 10
    generate_audio: bool = True
    source_ids: Optional[List[str]] = None
    note_ids: Optional[List[str]] = None
    content: Optional[str] = None  # Direct content to use
    custom_speakers: Optional[List[Dict[str, Any]]] = None

    class Config:
        extra = "allow"


class StandalonePodcastAudioRequest(BaseModel):
    """Generate audio from an already-created (and optionally edited) transcript."""
    podcast_id: Optional[str] = None  # If provided, updates existing standalone_podcasts row
    notebook_id: str
    title: str
    style: str = "conversational"
    speakers: int = 2
    duration_minutes: int = 10
    transcript: List[Dict[str, Any]]
    custom_speakers: Optional[List[Dict[str, Any]]] = None

    class Config:
        extra = "allow"


async def _fetch_podcast_content(podcast_request: StandalonePodcastRequest, logger) -> str:
    """Helper to fetch content from sources/notes for podcast generation"""
    import httpx
    
    content = podcast_request.content or ""
    
    # If source_ids provided, fetch content from Open Notebook
    if podcast_request.source_ids and not content:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for source_id in podcast_request.source_ids[:5]:  # Limit to 5 sources
                try:
                    # Fetch source from Open Notebook API
                    resp = await client.get(
                        f"http://open-notebook:5055/api/sources/{source_id}"
                    )
                    if resp.status_code == 200:
                        source_data = resp.json()
                        source_content = source_data.get("full_text") or source_data.get("content") or ""
                        if source_content:
                            content += f"\n\n=== SOURCE: {source_data.get('title', 'Untitled')} ===\n{source_content}"
                except Exception as e:
                    logger.warning(f"Failed to fetch source {source_id}: {e}")
    
    # If note_ids provided, fetch content from Open Notebook
    if podcast_request.note_ids and not content:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for note_id in podcast_request.note_ids[:5]:  # Limit to 5 notes
                try:
                    resp = await client.get(
                        f"http://open-notebook:5055/api/notes/{note_id}"
                    )
                    if resp.status_code == 200:
                        note_data = resp.json()
                        note_content = note_data.get("content") or ""
                        if note_content:
                            content += f"\n\n=== NOTE: {note_data.get('title', 'Untitled')} ===\n{note_content}"
                except Exception as e:
                    logger.warning(f"Failed to fetch note {note_id}: {e}")
    
    return content


async def _save_podcast_to_db(
    manager,
    user_id: int,
    podcast_request: StandalonePodcastRequest,
    result: dict
) -> dict:
    """Save podcast result to database and return formatted response"""
    import json
    
    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO standalone_podcasts 
                (notebook_id, user_id, title, status, style, speakers, duration_minutes,
                 audio_path, audio_url, transcript, outline, error_message, duration_seconds,
                 source_ids, note_ids, speaker_profiles, script, completed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17,
                    CASE WHEN $4 IN ('completed', 'script_only', 'error') THEN CURRENT_TIMESTAMP ELSE NULL END)
            RETURNING id, notebook_id, user_id, title, status, style, speakers, duration_minutes,
                      audio_path, audio_url, transcript, outline, error_message, duration_seconds,
                      source_ids, note_ids, speaker_profiles, script, created_at, completed_at
        """,
            podcast_request.notebook_id,
            user_id,
            podcast_request.title,
            result.get("status", "completed"),
            podcast_request.style,
            podcast_request.speakers,
            podcast_request.duration_minutes,
            result.get("audio_path"),
            result.get("audio_url"),
            json.dumps(result.get("transcript", [])),
            result.get("outline"),
            json.dumps(result.get("error") or result.get("audio_error")) if isinstance(result.get("error") or result.get("audio_error"), dict) else (result.get("error") or result.get("audio_error")),
            result.get("duration_seconds"),
            podcast_request.source_ids or [],
            podcast_request.note_ids or [],
            json.dumps(podcast_request.custom_speakers or []),
            json.dumps(result.get("script") or None)
        )
    
    return {
        "id": str(row["id"]),
        "notebook_id": row["notebook_id"],
        "title": row["title"],
        "status": row["status"],
        "style": row["style"],
        "speakers": row["speakers"],
        "duration_minutes": row["duration_minutes"],
        "audio_path": row["audio_path"],
        "audio_url": row["audio_url"],
        "transcript": json.loads(row["transcript"]) if row["transcript"] else [],
        "outline": row["outline"],
        "error_message": row["error_message"],
        "duration_seconds": row["duration_seconds"],
        "source_ids": row["source_ids"],
        "note_ids": row["note_ids"],
        "speaker_profiles": json.loads(row["speaker_profiles"]) if row["speaker_profiles"] else [],
        "script": json.loads(row["script"]) if row["script"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None
    }


async def _update_standalone_podcast_audio_in_db(
    manager,
    user_id: int,
    podcast_id: str,
    podcast_request: StandalonePodcastAudioRequest,
    result: dict
) -> dict:
    """Update an existing standalone_podcasts row with audio generation result."""
    import json
    from uuid import UUID

    try:
        podcast_uuid = UUID(podcast_id)
    except ValueError:
        raise HTTPException(400, "Invalid podcast ID")

    async with manager.db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE standalone_podcasts
            SET title = $1,
                status = $2,
                style = $3,
                speakers = $4,
                duration_minutes = $5,
                audio_path = $6,
                audio_url = $7,
                transcript = $8,
                script = $9,
                speaker_profiles = $10,
                error_message = $11,
                duration_seconds = $12,
                completed_at = CASE WHEN $2 IN ('completed', 'script_only', 'error') THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE id = $13 AND user_id = $14
            RETURNING id, notebook_id, user_id, title, status, style, speakers, duration_minutes,
                      audio_path, audio_url, transcript, outline, error_message, duration_seconds,
                      source_ids, note_ids, speaker_profiles, script, created_at, completed_at
        """,
            podcast_request.title,
            result.get("status", "completed"),
            podcast_request.style,
            podcast_request.speakers,
            podcast_request.duration_minutes,
            result.get("audio_path"),
            result.get("audio_url"),
            json.dumps(result.get("transcript", [])),
            json.dumps(result.get("script") or None),
            json.dumps(podcast_request.custom_speakers or []),
            json.dumps(result.get("error") or result.get("audio_error")) if isinstance(result.get("error") or result.get("audio_error"), dict) else (result.get("error") or result.get("audio_error")),
            result.get("duration_seconds"),
            podcast_uuid,
            user_id
        )

        if not row:
            raise HTTPException(404, "Podcast not found")

    return {
        "id": str(row["id"]),
        "notebook_id": row["notebook_id"],
        "title": row["title"],
        "status": row["status"],
        "style": row["style"],
        "speakers": row["speakers"],
        "duration_minutes": row["duration_minutes"],
        "audio_path": row["audio_path"],
        "audio_url": row["audio_url"],
        "transcript": json.loads(row["transcript"]) if row["transcript"] else [],
        "outline": row["outline"],
        "error_message": row["error_message"],
        "duration_seconds": row["duration_seconds"],
        "source_ids": row["source_ids"],
        "note_ids": row["note_ids"],
        "speaker_profiles": json.loads(row["speaker_profiles"]) if row["speaker_profiles"] else [],
        "script": json.loads(row["script"]) if row["script"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None
    }


@router.get("/podcasts/by-notebook/{notebook_id}")
async def list_standalone_podcasts(
    notebook_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """List all podcasts for an Open Notebook notebook"""
    import json
    
    async with manager.db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, notebook_id, user_id, title, status, style, speakers, duration_minutes,
                   audio_path, audio_url, transcript, outline, error_message, duration_seconds,
                   source_ids, note_ids, speaker_profiles, script, created_at, completed_at
            FROM standalone_podcasts
            WHERE notebook_id = $1 AND user_id = $2
            ORDER BY created_at DESC
        """, notebook_id, current_user["id"])
    
    podcasts = []
    for row in rows:
        podcasts.append({
            "id": str(row["id"]),
            "notebook_id": row["notebook_id"],
            "title": row["title"],
            "status": row["status"],
            "style": row["style"],
            "speakers": row["speakers"],
            "duration_minutes": row["duration_minutes"],
            "audio_path": row["audio_path"],
            "audio_url": row["audio_url"],
            "transcript": json.loads(row["transcript"]) if row["transcript"] else [],
            "outline": row["outline"],
            "error_message": row["error_message"],
            "duration_seconds": row["duration_seconds"],
            "source_ids": row["source_ids"],
            "note_ids": row["note_ids"],
            "speaker_profiles": json.loads(row["speaker_profiles"]) if row["speaker_profiles"] else [],
            "script": json.loads(row["script"]) if row["script"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None
        })
    
    return {"podcasts": podcasts, "count": len(podcasts)}


@router.delete("/podcasts/{podcast_id}")
async def delete_standalone_podcast(
    podcast_id: str,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Delete a standalone podcast"""
    import os
    from uuid import UUID
    
    try:
        podcast_uuid = UUID(podcast_id)
    except ValueError:
        raise HTTPException(400, "Invalid podcast ID")
    
    async with manager.db_pool.acquire() as conn:
        # Get podcast to check ownership and get audio path
        row = await conn.fetchrow("""
            SELECT audio_path FROM standalone_podcasts
            WHERE id = $1 AND user_id = $2
        """, podcast_uuid, current_user["id"])
        
        if not row:
            raise HTTPException(404, "Podcast not found")
        
        # Delete audio file if exists
        if row["audio_path"] and os.path.exists(row["audio_path"]):
            try:
                os.remove(row["audio_path"])
            except Exception:
                pass
        
        # Delete from database
        await conn.execute("""
            DELETE FROM standalone_podcasts WHERE id = $1
        """, podcast_uuid)
    
    return {"success": True, "message": "Podcast deleted"}


@router.post("/podcasts/generate")
async def generate_standalone_podcast(
    podcast_request: StandalonePodcastRequest,
    background_tasks: BackgroundTasks = None,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """
    Generate a podcast from content (standalone, works with Open Notebook IDs).
    This endpoint doesn't require notebook ownership verification.
    Saves the podcast to the database for persistence.
    """
    from open_notebook.podcast import PodcastGenerator
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        content = await _fetch_podcast_content(podcast_request, logger)
        
        if not content.strip():
            raise HTTPException(400, "No content available. Provide content, source_ids, or note_ids.")
        
        # Generate podcast directly
        generator = PodcastGenerator()
        result = await generator.generate(
            content=content,
            title=podcast_request.title,
            speakers=podcast_request.speakers,
            duration_minutes=podcast_request.duration_minutes,
            style=podcast_request.style,
            custom_speakers=podcast_request.custom_speakers,
            generate_audio=podcast_request.generate_audio
        )
        
        # Save to database
        saved_podcast = await _save_podcast_to_db(manager, current_user["id"], podcast_request, result)
        return saved_podcast
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate podcast: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/podcasts/generate/stream")
async def generate_standalone_podcast_stream(
    podcast_request: StandalonePodcastRequest,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """
    Generate a podcast with Server-Sent Events (SSE) progress streaming.
    Returns progress updates and final result as SSE events.
    Saves the podcast to the database for persistence.
    
    Event types:
    - progress: {step: 'outline'|'script'|'audio', message: string}
    - result: Final podcast data (saved to database)
    - error: Error message
    """
    from open_notebook.podcast import PodcastGenerator
    from fastapi.responses import StreamingResponse
    import json
    import logging
    
    logger = logging.getLogger(__name__)
    user_id = current_user["id"]
    
    async def generate_sse_events():
        try:
            content = await _fetch_podcast_content(podcast_request, logger)
            
            if not content.strip():
                yield f"event: error\ndata: {json.dumps({'error': 'No content available. Provide content, source_ids, or note_ids.'})}\n\n"
                return
            
            # Generate podcast with progress streaming
            generator = PodcastGenerator()
            
            async for event in generator.generate_with_progress(
                content=content,
                title=podcast_request.title,
                speakers=podcast_request.speakers,
                duration_minutes=podcast_request.duration_minutes,
                style=podcast_request.style,
                custom_speakers=podcast_request.custom_speakers,
                generate_audio=podcast_request.generate_audio
            ):
                event_type = event.get("event", "progress")
                event_data = event.get("data", {})
                
                if event_type == "result":
                    # Save to database
                    result = event_data
                    try:
                        saved_podcast = await _save_podcast_to_db(manager, user_id, podcast_request, result)
                        yield f"event: result\ndata: {json.dumps(saved_podcast)}\n\n"
                    except Exception as db_error:
                        logger.error(f"Failed to save podcast to database: {db_error}")
                        # Still return result even if DB save fails
                        final_data = {
                            "id": result.get("title", "").replace(" ", "_").lower()[:20],
                            "title": podcast_request.title,
                            "status": result.get("status", "completed"),
                            "style": podcast_request.style,
                            "speakers": podcast_request.speakers,
                            "duration_minutes": podcast_request.duration_minutes,
                            "audio_path": result.get("audio_path"),
                            "audio_url": result.get("audio_url"),
                            "transcript": result.get("transcript", []),
                            "outline": result.get("outline"),
                            "error_message": json.dumps(result.get("error") or result.get("audio_error")) if isinstance(result.get("error") or result.get("audio_error"), dict) else (result.get("error") or result.get("audio_error")),
                            "duration_seconds": result.get("duration_seconds"),
                            "created_at": result.get("started_at"),
                            "completed_at": result.get("completed_at")
                        }
                        yield f"event: result\ndata: {json.dumps(final_data)}\n\n"
                else:
                    yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"
                    
        except Exception as e:
            logger.error(f"Failed to generate podcast: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        generate_sse_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.get("/podcasts/audio/{filename}")
async def serve_standalone_podcast_audio(
    filename: str,
    current_user: Dict = Depends(get_current_user_from_request)
):
    """Serve audio file for standalone podcast generation"""
    import os
    
    from open_notebook.podcast.audio import PODCAST_OUTPUT_PATH

    # Sanitize filename to prevent directory traversal
    safe_filename = os.path.basename(filename)
    audio_path = os.path.join(PODCAST_OUTPUT_PATH, "audio", safe_filename)
    
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    media_type = "audio/mpeg" if audio_path.endswith(".mp3") else "audio/wav"
    return FileResponse(audio_path, media_type=media_type, filename=safe_filename)


@router.post("/podcasts/generate/audio")
async def generate_standalone_podcast_audio_from_script(
    audio_request: StandalonePodcastAudioRequest,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """
    Generate podcast audio from a provided transcript (no LLM call).
    Intended for the \"script-only -> edit -> generate audio\" flow.
    """
    import logging
    from open_notebook.podcast.audio import AudioGenerator
    from open_notebook.podcast.script import get_default_speakers

    logger = logging.getLogger(__name__)
    user_id = current_user["id"]

    try:
        speaker_profiles = (audio_request.custom_speakers or get_default_speakers())[: audio_request.speakers]

        # Build a script dict in the shape AudioGenerator expects
        transcript = audio_request.transcript or []
        cleaned_transcript = []
        for seg in transcript:
            speaker = (seg.get("speaker") or "").strip()
            dialogue = (seg.get("dialogue") or seg.get("text") or "").strip()
            if speaker and dialogue:
                cleaned_transcript.append({"speaker": speaker, "dialogue": dialogue})

        if not cleaned_transcript:
            raise HTTPException(400, "No valid transcript segments provided")

        script = {
            "title": audio_request.title,
            "style": audio_request.style,
            "duration_minutes": audio_request.duration_minutes,
            "speakers": speaker_profiles,
            "transcript": cleaned_transcript
        }

        audio_generator = AudioGenerator()
        audio_result = await audio_generator.generate_audio(script)

        result = {
            "title": audio_request.title,
            "style": audio_request.style,
            "duration_minutes": audio_request.duration_minutes,
            "transcript": cleaned_transcript,
            "script": script
        }

        if "error" in audio_result:
            result["status"] = "error"
            result["error"] = audio_result.get("error")
        else:
            result["audio_path"] = audio_result.get("audio_path")
            result["audio_url"] = audio_generator.get_audio_url(audio_result.get("audio_path", ""))
            result["duration_seconds"] = audio_result.get("duration_seconds")
            result["status"] = "completed"

        # Persist (update existing if podcast_id provided, otherwise insert new)
        if audio_request.podcast_id:
            return await _update_standalone_podcast_audio_in_db(
                manager=manager,
                user_id=user_id,
                podcast_id=audio_request.podcast_id,
                podcast_request=audio_request,
                result=result
            )

        # Insert new row
        standalone_req = StandalonePodcastRequest(
            notebook_id=audio_request.notebook_id,
            title=audio_request.title,
            style=audio_request.style,
            speakers=audio_request.speakers,
            duration_minutes=audio_request.duration_minutes,
            generate_audio=True,
            custom_speakers=audio_request.custom_speakers
        )
        return await _save_podcast_to_db(manager, user_id, standalone_req, result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate podcast audio from script: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{notebook_id}/podcasts")
async def generate_podcast(
    notebook_id: UUID,
    podcast_request: "PodcastRequest",
    background_tasks: BackgroundTasks = None,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Generate a podcast from notebook content"""
    from .models import PodcastRequest, PodcastStatus
    
    try:
        # Verify notebook ownership
        notebook = await manager.get_notebook(notebook_id, current_user["id"])
        
        # Create podcast record
        async with manager.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO notebook_podcasts 
                    (notebook_id, user_id, title, status, style, speakers, duration_minutes)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, notebook_id, user_id, title, status, style, speakers, duration_minutes, 
                          audio_path, transcript, outline, error_message, duration_seconds, created_at, completed_at
            """, notebook_id, current_user["id"], podcast_request.title, 
                PodcastStatus.PENDING.value, podcast_request.style.value,
                podcast_request.speakers, podcast_request.duration_minutes)
        
        podcast_id = row["id"]
        
        # Start generation in background
        if background_tasks:
            background_tasks.add_task(
                _run_podcast_generation,
                manager.db_pool,
                podcast_id,
                notebook_id,
                current_user["id"],
                podcast_request
            )
        
        return dict(row)
        
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to create podcast: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _run_podcast_generation(db_pool, podcast_id: UUID, notebook_id: UUID, user_id: int, request):
    """Background task for podcast generation"""
    from open_notebook.podcast import PodcastGenerator
    from .models import PodcastStatus
    import json
    
    try:
        # Update status to generating
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE notebook_podcasts SET status = $1 WHERE id = $2",
                PodcastStatus.GENERATING.value, podcast_id
            )
            
            # Get source content - either selected sources or all ready sources
            source_ids = getattr(request, 'source_ids', None)
            note_ids = getattr(request, 'note_ids', None)
            
            source_content = []
            note_content = []
            
            # Fetch source content
            if source_ids and len(source_ids) > 0:
                # Use selected sources
                rows = await conn.fetch("""
                    SELECT title, content_text FROM notebook_sources 
                    WHERE notebook_id = $1 AND id = ANY($2) AND status = 'ready' AND content_text IS NOT NULL
                """, notebook_id, source_ids)
            else:
                # Use all ready sources from notebook
                rows = await conn.fetch("""
                    SELECT title, content_text FROM notebook_sources 
                    WHERE notebook_id = $1 AND status = 'ready' AND content_text IS NOT NULL
                """, notebook_id)
            
            for row in rows:
                if row["content_text"]:
                    header = f"=== SOURCE: {row['title'] or 'Untitled'} ==="
                    source_content.append(f"{header}\n{row['content_text']}")
            
            # Fetch note content
            if note_ids and len(note_ids) > 0:
                note_rows = await conn.fetch("""
                    SELECT title, content FROM notebook_notes 
                    WHERE notebook_id = $1 AND id = ANY($2) AND content IS NOT NULL
                """, notebook_id, note_ids)
                
                for row in note_rows:
                    if row["content"]:
                        header = f"=== NOTE: {row['title'] or 'Untitled Note'} ==="
                        note_content.append(f"{header}\n{row['content']}")
        
        # Combine all content
        all_content_parts = []
        if source_content:
            all_content_parts.append("SOURCES:\n" + "\n\n".join(source_content))
        if note_content:
            all_content_parts.append("NOTES:\n" + "\n\n".join(note_content))
        
        content = "\n\n".join(all_content_parts)
        
        if not content:
            raise Exception("No content available in selected sources or notes. Make sure sources have been processed.")
        
        # Generate podcast
        generator = PodcastGenerator()
        result = await generator.generate(
            content=content,
            title=request.title,
            speakers=request.speakers,
            duration_minutes=request.duration_minutes,
            style=request.style.value,
            custom_speakers=getattr(request, "custom_speakers", None)
        )
        
        # Update database with result
        async with db_pool.acquire() as conn:
            if result.get("status") == "error":
                await conn.execute("""
                    UPDATE notebook_podcasts 
                    SET status = $1, error_message = $2
                    WHERE id = $3
                """, PodcastStatus.ERROR.value, result.get("error", "Unknown error"), podcast_id)
            else:
                transcript_json = json.dumps(result.get("transcript", []))
                await conn.execute("""
                    UPDATE notebook_podcasts 
                    SET status = $1, audio_path = $2, transcript = $3, outline = $4, 
                        duration_seconds = $5, completed_at = CURRENT_TIMESTAMP
                    WHERE id = $6
                """, PodcastStatus.COMPLETED.value, result.get("audio_path"),
                    transcript_json, result.get("outline"), result.get("duration_seconds"), podcast_id)
    
    except Exception as e:
        logger.error(f"Podcast generation failed: {e}")
        async with db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE notebook_podcasts SET status = $1, error_message = $2 WHERE id = $3
            """, PodcastStatus.ERROR.value, str(e), podcast_id)


@router.get("/{notebook_id}/podcasts")
async def list_podcasts(
    notebook_id: UUID,
    limit: int = 20,
    offset: int = 0,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """List podcasts for a notebook"""
    try:
        await manager.get_notebook(notebook_id, current_user["id"])
        
        async with manager.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, notebook_id, user_id, title, status, style, speakers, duration_minutes,
                       audio_path, transcript, outline, error_message, duration_seconds, created_at, completed_at
                FROM notebook_podcasts
                WHERE notebook_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """, notebook_id, limit, offset)
            
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM notebook_podcasts WHERE notebook_id = $1",
                notebook_id
            )
        
        return {
            "podcasts": [dict(row) for row in rows],
            "total_count": total,
            "has_more": offset + len(rows) < total
        }
        
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to list podcasts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}/podcasts/{podcast_id}")
async def get_podcast(
    notebook_id: UUID,
    podcast_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Get a specific podcast"""
    try:
        await manager.get_notebook(notebook_id, current_user["id"])
        
        async with manager.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, notebook_id, user_id, title, status, style, speakers, duration_minutes,
                       audio_path, transcript, outline, error_message, duration_seconds, created_at, completed_at
                FROM notebook_podcasts
                WHERE id = $1 AND notebook_id = $2
            """, podcast_id, notebook_id)
        
        if not row:
            raise HTTPException(status_code=404, detail="Podcast not found")
        
        return dict(row)
        
    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Failed to get podcast: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}/podcasts/{podcast_id}/audio")
async def get_podcast_audio(
    notebook_id: UUID,
    podcast_id: UUID,
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """Stream/download the generated podcast audio file"""
    try:
        await manager.get_notebook(notebook_id, current_user["id"])

        async with manager.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT audio_path FROM notebook_podcasts
                WHERE id = $1 AND notebook_id = $2
            """, podcast_id, notebook_id)

        if not row:
            raise HTTPException(status_code=404, detail="Podcast not found")

        audio_path = row["audio_path"]
        if not audio_path:
            raise HTTPException(status_code=404, detail="Podcast has no audio yet")

        import os
        if not os.path.exists(audio_path):
            raise HTTPException(status_code=404, detail="Audio file not found on disk")

        media_type = "audio/mpeg" if audio_path.endswith(".mp3") else "audio/wav"
        filename = os.path.basename(audio_path)
        return FileResponse(audio_path, media_type=media_type, filename=filename)

    except NotebookNotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve podcast audio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Global Search (Open Notebook-style) ───────────────────────────────────────

@router.post("/search")
async def search_knowledge_base(
    search_request: "SearchRequest",
    request: Request = None,
    current_user: Dict = Depends(get_current_user_from_request),
    manager: NotebookManager = Depends(get_notebook_manager)
):
    """
    Search across all notebooks for this user.
    - type=text: ILIKE search in sources + notes
    - type=vector: pgvector search over notebook_chunks (sources only)
    """
    from .models import SearchRequest, SearchResponse, SearchResult, SearchType

    q = (search_request.query or "").strip()
    if not q:
        return SearchResponse(results=[], total_count=0, search_type=search_request.type)

    results: list[SearchResult] = []

    async with manager.db_pool.acquire() as conn:
        # Text search
        if search_request.type == SearchType.TEXT:
            if search_request.search_sources:
                rows = await conn.fetch(
                    """
                    SELECT
                      n.id as notebook_id,
                      n.title as notebook_title,
                      s.id as source_id,
                      COALESCE(s.title, s.original_filename) as title,
                      LEFT(COALESCE(s.content_text, ''), 300) as snippet
                    FROM notebook_sources s
                    JOIN notebooks n ON n.id = s.notebook_id
                    WHERE n.user_id = $1
                      AND (
                        COALESCE(s.title,'') ILIKE '%' || $2 || '%'
                        OR COALESCE(s.original_filename,'') ILIKE '%' || $2 || '%'
                        OR COALESCE(s.content_text,'') ILIKE '%' || $2 || '%'
                      )
                    ORDER BY s.updated_at DESC
                    LIMIT $3
                    """,
                    current_user["id"],
                    q,
                    search_request.limit,
                )
                for r in rows:
                    results.append(
                        SearchResult(
                            kind="source",
                            notebook_id=r["notebook_id"],
                            notebook_title=r["notebook_title"],
                            source_id=r["source_id"],
                            title=r["title"],
                            snippet=r["snippet"],
                        )
                    )

            if search_request.search_notes and len(results) < search_request.limit:
                remaining = search_request.limit - len(results)
                rows = await conn.fetch(
                    """
                    SELECT
                      n.id as notebook_id,
                      n.title as notebook_title,
                      nn.id as note_id,
                      COALESCE(nn.title, 'Untitled Note') as title,
                      LEFT(COALESCE(nn.content, ''), 300) as snippet
                    FROM notebook_notes nn
                    JOIN notebooks n ON n.id = nn.notebook_id
                    WHERE n.user_id = $1
                      AND (
                        COALESCE(nn.title,'') ILIKE '%' || $2 || '%'
                        OR COALESCE(nn.content,'') ILIKE '%' || $2 || '%'
                      )
                    ORDER BY nn.updated_at DESC
                    LIMIT $3
                    """,
                    current_user["id"],
                    q,
                    remaining,
                )
                for r in rows:
                    results.append(
                        SearchResult(
                            kind="note",
                            notebook_id=r["notebook_id"],
                            notebook_title=r["notebook_title"],
                            note_id=r["note_id"],
                            title=r["title"],
                            snippet=r["snippet"],
                        )
                    )

        # Vector search (sources only via chunks)
        else:
            if not search_request.search_sources:
                return SearchResponse(results=[], total_count=0, search_type=search_request.type)

            from .ingestion import IngestionService
            service = IngestionService(manager)
            embedding = await service.get_query_embedding(q)
            if not embedding:
                return SearchResponse(results=[], total_count=0, search_type=search_request.type)

            # Normalize to 4096 to match table definition
            embedding = service._normalize_embedding_dimension(embedding, 4096)  # noqa: SLF001
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

            rows = await conn.fetch(
                """
                SELECT
                  n.id as notebook_id,
                  n.title as notebook_title,
                  s.id as source_id,
                  COALESCE(s.title, s.original_filename) as title,
                  LEFT(COALESCE(s.content_text, ''), 300) as snippet,
                  1 - (c.embedding <=> $1::vector) as score
                FROM notebook_chunks c
                JOIN notebook_sources s ON s.id = c.source_id
                JOIN notebooks n ON n.id = c.notebook_id
                WHERE n.user_id = $2
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> $1::vector
                LIMIT $3
                """,
                embedding_str,
                current_user["id"],
                search_request.limit,
            )

            for r in rows:
                score = float(r["score"]) if r["score"] is not None else None
                if score is not None and score < search_request.minimum_score:
                    continue
                results.append(
                    SearchResult(
                        kind="source",
                        notebook_id=r["notebook_id"],
                        notebook_title=r["notebook_title"],
                        source_id=r["source_id"],
                        title=r["title"],
                        snippet=r["snippet"],
                        score=score,
                    )
                )

    return SearchResponse(results=results, total_count=len(results), search_type=search_request.type)
