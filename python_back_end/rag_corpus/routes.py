"""
RAG Corpus API Routes

Provides endpoints for managing the local RAG corpus:
- Start/monitor update jobs
- Manage sources (rebuild, clear)
- Get source stats
"""

import asyncio
import os
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag-corpus"])

# Global references - set during initialization
_job_manager = None
_vectordb_adapter = None
_embedding_adapter = None

# Configuration
RAG_DIR = os.getenv("RAG_CORPUS_DIR", "/app/rag_corpus_data")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "nomic-embed-text")


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class UpdateRagRequest(BaseModel):
    """Request to start a RAG update job."""
    sources: List[str]  # ["nextjs_docs", "stack_overflow", "github", "python_docs"]
    keywords: Optional[List[str]] = None
    extra_urls: Optional[List[str]] = None
    python_libraries: Optional[List[str]] = None  # For python_docs source
    embedding_model: Optional[str] = None  # Ollama embedding model to use


class RebuildSourceRequest(BaseModel):
    """Request to rebuild a specific source."""
    source: str


class JobResponse(BaseModel):
    """Response with job information."""
    job_id: str
    status: str
    message: Optional[str] = None


class SourceStats(BaseModel):
    """Source statistics."""
    available_sources: List[str]
    indexed_stats: dict
    total_documents: int


# ─── Initialization ───────────────────────────────────────────────────────────

async def initialize_rag_corpus(db_pool) -> bool:
    """
    Initialize RAG corpus services.
    
    Args:
        db_pool: Database connection pool
        
    Returns:
        True if initialized successfully
    """
    global _job_manager, _vectordb_adapter, _embedding_adapter
    
    try:
        from rag_corpus import JobManager, VectorDBAdapter, EmbeddingAdapter
        
        # Ensure RAG directory exists
        os.makedirs(RAG_DIR, exist_ok=True)
        
        # Initialize embedding adapter
        _embedding_adapter = EmbeddingAdapter(
            model_name=EMBEDDING_MODEL,
            ollama_url=OLLAMA_URL
        )
        
        # Initialize vector DB adapter (using asyncpg pool)
        # Note: We need a psycopg-compatible pool for the adapter
        # For now, we'll create a wrapper or use asyncpg directly
        _vectordb_adapter = VectorDBAdapter(
            db_pool=db_pool,
            collection_name="local_rag_corpus"
            # embedding_dimension defaults to None (auto-detect)
        )
        
        # Initialize job manager
        _job_manager = JobManager(
            db_pool=db_pool,
            rag_dir=RAG_DIR,
            ollama_url=OLLAMA_URL,
            embedding_model=EMBEDDING_MODEL
        )
        
        logger.info("✅ RAG corpus services initialized")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize RAG corpus: {e}")
        return False


def get_job_manager():
    """Get the job manager instance."""
    if _job_manager is None:
        raise HTTPException(
            status_code=503,
            detail="RAG corpus service not initialized"
        )
    return _job_manager


def get_vectordb_adapter():
    """Get the vector DB adapter instance."""
    if _vectordb_adapter is None:
        raise HTTPException(
            status_code=503,
            detail="RAG corpus service not initialized"
        )
    return _vectordb_adapter


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/update-local", response_model=JobResponse)
async def start_rag_update(request: UpdateRagRequest):
    """
    Start a background job to update the local RAG corpus.
    
    The job will:
    1. Fetch content from specified sources
    2. Chunk documents
    3. Generate embeddings
    4. Upsert to vector database
    """
    job_manager = get_job_manager()
    
    # Validate sources
    valid_sources = ["nextjs_docs", "stack_overflow", "github", "python_docs"]
    for source in request.sources:
        if source not in valid_sources:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid source: {source}. Valid sources: {valid_sources}"
            )
    
    try:
        # Log what we received
        logger.info(f"RAG Update Request - sources: {request.sources}, embedding_model: {request.embedding_model}")
        
        # Create job
        job_id = await job_manager.create_job(
            sources=request.sources,
            keywords=request.keywords,
            extra_urls=request.extra_urls,
            python_libraries=request.python_libraries,
            embedding_model=request.embedding_model
        )
        
        # Start background execution
        asyncio.create_task(job_manager.run_job_async(job_id))
        
        logger.info(f"Started RAG update job {job_id} for sources: {request.sources} with embedding_model: {request.embedding_model}")
        
        return JobResponse(
            job_id=job_id,
            status="accepted",
            message=f"Job started for sources: {request.sources}"
        )
        
    except Exception as e:
        logger.error(f"Failed to start RAG update job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of a RAG update job."""
    job_manager = get_job_manager()
    
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job.to_dict()


@router.get("/jobs")
async def list_jobs(limit: int = 10):
    """List recent RAG update jobs."""
    job_manager = get_job_manager()
    
    jobs = job_manager.list_jobs(limit=limit)
    return {
        "jobs": [job.to_dict() for job in jobs],
        "count": len(jobs)
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running job."""
    job_manager = get_job_manager()
    
    cancelled = await job_manager.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=404,
            detail="Job not found or not running"
        )
    
    return {"message": f"Job {job_id} cancelled"}


@router.get("/sources", response_model=SourceStats)
async def get_source_stats():
    """Get available sources and their index statistics."""
    vectordb = get_vectordb_adapter()
    
    try:
        stats = await vectordb.get_source_stats()
        total = sum(stats.values())
        
        return SourceStats(
            available_sources=["nextjs_docs", "stack_overflow", "github", "python_docs"],
            indexed_stats=stats,
            total_documents=total
        )
        
    except Exception as e:
        logger.error(f"Failed to get source stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebuild")
async def rebuild_source(request: RebuildSourceRequest):
    """
    Rebuild (delete + re-index) a specific source.
    
    This will:
    1. Delete all vectors for the source
    2. Start a new update job for just that source
    """
    job_manager = get_job_manager()
    vectordb = get_vectordb_adapter()
    
    valid_sources = ["nextjs_docs", "stack_overflow", "github", "python_docs"]
    if request.source not in valid_sources:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source: {request.source}. Valid: {valid_sources}"
        )
    
    try:
        # Delete existing vectors
        deleted = await vectordb.delete_by_source(request.source)
        logger.info(f"Deleted {deleted} vectors for source {request.source}")
        
        # Start new job
        job_id = await job_manager.create_job(sources=[request.source])
        asyncio.create_task(job_manager.run_job_async(job_id))
        
        return {
            "job_id": job_id,
            "deleted": deleted,
            "message": f"Rebuilding {request.source}"
        }
        
    except Exception as e:
        logger.error(f"Failed to rebuild source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sources/{source}")
async def clear_source(source: str):
    """Delete all vectors for a source."""
    vectordb = get_vectordb_adapter()
    
    valid_sources = ["nextjs_docs", "stack_overflow", "github", "python_docs"]
    if source not in valid_sources:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source: {source}. Valid: {valid_sources}"
        )
    
    try:
        deleted = await vectordb.delete_by_source(source)
        
        return {
            "source": source,
            "deleted": deleted,
            "message": f"Cleared {deleted} documents from {source}"
        }
        
    except Exception as e:
        logger.error(f"Failed to clear source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def rag_health_check():
    """Check health of RAG corpus services."""
    health = {
        "status": "healthy",
        "services": {}
    }
    
    # Check job manager
    try:
        job_manager = get_job_manager()
        health["services"]["job_manager"] = "ok"
    except:
        health["services"]["job_manager"] = "unavailable"
        health["status"] = "degraded"
    
    # Check vector DB
    try:
        vectordb = get_vectordb_adapter()
        vdb_health = await vectordb.health_check()
        health["services"]["vectordb"] = vdb_health.get("status", "unknown")
        health["vectordb_details"] = vdb_health
    except Exception as e:
        health["services"]["vectordb"] = "unavailable"
        health["vectordb_error"] = str(e)
        health["status"] = "degraded"
    
    # Check embedding adapter
    if _embedding_adapter:
        try:
            embed_health = await _embedding_adapter.check_health()
            health["services"]["embedding"] = embed_health.get("status", "unknown")
            health["embedding_details"] = embed_health
        except Exception as e:
            health["services"]["embedding"] = "unavailable"
            health["embedding_error"] = str(e)
            health["status"] = "degraded"
    else:
        health["services"]["embedding"] = "not_initialized"
    
    return health


@router.get("/config")
async def get_rag_config():
    """Get current RAG corpus configuration."""
    return {
        "rag_dir": RAG_DIR,
        "ollama_url": OLLAMA_URL,
        "embedding_model": EMBEDDING_MODEL,
        "available_sources": ["nextjs_docs", "stack_overflow", "github", "python_docs"]
    }


@router.get("/models")
async def get_ollama_models():
    """
    Get available Ollama models for embedding.
    
    Returns list of models with their details, filtering for embedding-capable models.
    """
    import aiohttp
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(f"{OLLAMA_URL}/api/tags") as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail="Failed to get models from Ollama")
                
                data = await resp.json()
                models = data.get("models", [])
                
                # Format response
                model_list = []
                embedding_keywords = ["embed", "nomic", "bge", "e5", "gte", "minilm"]
                
                for model in models:
                    name = model.get("name", "")
                    size = model.get("size", 0)
                    modified = model.get("modified_at", "")
                    
                    # Check if this is likely an embedding model
                    is_embedding = any(kw in name.lower() for kw in embedding_keywords)
                    
                    model_list.append({
                        "name": name,
                        "size_gb": round(size / (1024**3), 2) if size else 0,
                        "modified": modified,
                        "is_embedding_model": is_embedding
                    })
                
                # Sort: embedding models first, then alphabetically
                model_list.sort(key=lambda x: (not x["is_embedding_model"], x["name"]))
                
                return {
                    "models": model_list,
                    "current_model": EMBEDDING_MODEL,
                    "total_count": len(model_list)
                }
                
    except aiohttp.ClientError as e:
        logger.error(f"Failed to connect to Ollama: {e}")
        raise HTTPException(status_code=503, detail=f"Cannot connect to Ollama: {e}")
    except Exception as e:
        logger.error(f"Error getting models: {e}")
        raise HTTPException(status_code=500, detail=str(e))
