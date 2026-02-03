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
_vectordb_adapters = {}  # collection_name -> adapter
_embedding_adapters = {}  # model_name -> adapter
_config_manager = None  # Dynamic source configuration

# Configuration
RAG_DIR = os.getenv("RAG_CORPUS_DIR", "/app/rag_corpus_data")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "nomic-embed-text")  # 768 dims, default

# Per-source embedding model configuration
# qwen3-embedding: 2560 dims - for complex technical/code content
# nomic-embed-text: 768 dims - for general devops/docs
SOURCE_EMBEDDING_MODELS = {
    # Complex/Code-heavy sources → qwen3-embedding (full)
    "kubernetes_docs": "qwen3-embedding",      # Complex edge cases, YAML configs
    "github": "qwen3-embedding",               # Code repositories
    "stack_overflow": "qwen3-embedding",       # Code Q&A with nuanced answers

    # DevOps/General docs → nomic-embed-text
    "docker_docs": "nomic-embed-text",         # DevOps containerization
    "python_docs": "nomic-embed-text",         # API documentation
    "nextjs_docs": "nomic-embed-text",         # Framework docs
    "local_docs": "nomic-embed-text",          # Playbooks, guides, cyber docs
}

def get_embedding_model_for_source(source: str) -> str:
    """Get the appropriate embedding model for a source type."""
    return SOURCE_EMBEDDING_MODELS.get(source, EMBEDDING_MODEL)

# Collection names based on embedding model (different dims need separate tables)
EMBEDDING_COLLECTIONS = {
    "qwen3-embedding": "local_rag_corpus_code",    # 2560 dims - code/complex
    "nomic-embed-text": "local_rag_corpus_docs",   # 768 dims - general docs
}

def get_collection_for_source(source: str) -> str:
    """Get the vector collection name for a source type."""
    model = get_embedding_model_for_source(source)
    return EMBEDDING_COLLECTIONS.get(model, "local_rag_corpus_docs")


# ─── Pydantic Models ──────────────────────────────────────────────────────────


class UpdateRagRequest(BaseModel):
    """Request to start a RAG update job."""

    sources: List[
        str
    ]  # ["nextjs_docs", "stack_overflow", "github", "python_docs", "docker_docs", "kubernetes_docs"]
    keywords: Optional[List[str]] = None
    extra_urls: Optional[List[str]] = None
    python_libraries: Optional[List[str]] = None  # For python_docs source
    docker_topics: Optional[List[str]] = (
        None  # For docker_docs source (engine, compose, swarm, etc.)
    )
    kubernetes_topics: Optional[List[str]] = (
        None  # For kubernetes_docs source (concepts, tasks, networking, etc.)
    )
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


class SourceConfigRequest(BaseModel):
    """Request to add/update a source configuration."""

    id: str
    name: str
    description: str
    category: str = "general"  # code, devops, security, general
    embedding_tier: str = "standard"  # high, standard
    enabled: bool = True
    fetcher_type: str = "generic"
    base_url: str = ""
    sitemap_url: Optional[str] = None
    options: dict = {}
    rate_limit_delay: float = 0.5
    max_pages: int = 100
    url_patterns: List[str] = []
    exclude_patterns: List[str] = []


class SourceToggleRequest(BaseModel):
    """Request to enable/disable a source."""
    enabled: bool


# ─── Initialization ───────────────────────────────────────────────────────────


async def initialize_rag_corpus(db_pool) -> bool:
    """
    Initialize RAG corpus services with multi-model support and dynamic config.

    Args:
        db_pool: Database connection pool

    Returns:
        True if initialized successfully
    """
    global _job_manager, _vectordb_adapters, _embedding_adapters, _config_manager

    try:
        from rag_corpus import JobManager, VectorDBAdapter, EmbeddingAdapter
        from rag_corpus.source_config import get_config_manager, EMBEDDING_TIER_CONFIG

        # Ensure RAG directory exists
        os.makedirs(RAG_DIR, exist_ok=True)

        # Initialize dynamic config manager
        _config_manager = await get_config_manager(db_pool)
        logger.info(f"Loaded {len(_config_manager.get_all())} source configurations")

        # Initialize embedding adapters for each tier
        for tier, config in EMBEDDING_TIER_CONFIG.items():
            model_name = config["model"]
            if model_name not in _embedding_adapters:
                _embedding_adapters[model_name] = EmbeddingAdapter(
                    model_name=model_name, ollama_url=OLLAMA_URL
                )
                logger.info(f"Initialized embedding adapter: {model_name} ({config['dimensions']} dims)")

        # Initialize vector DB adapters for each collection
        for tier, config in EMBEDDING_TIER_CONFIG.items():
            collection_name = config["collection"]
            if collection_name not in _vectordb_adapters:
                _vectordb_adapters[collection_name] = VectorDBAdapter(
                    db_pool=db_pool,
                    collection_name=collection_name,
                )
                logger.info(f"Initialized vector DB adapter: {collection_name}")

        # Initialize job manager
        _job_manager = JobManager(
            db_pool=db_pool,
            rag_dir=RAG_DIR,
            ollama_url=OLLAMA_URL,
            embedding_model=EMBEDDING_MODEL,
        )

        logger.info("✅ RAG corpus services initialized (multi-model + dynamic config)")
        logger.info(f"   Models: {list(_embedding_adapters.keys())}")
        logger.info(f"   Collections: {list(_vectordb_adapters.keys())}")
        logger.info(f"   Sources: {len(_config_manager.get_enabled())} enabled")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to initialize RAG corpus: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_job_manager():
    """Get the job manager instance."""
    if _job_manager is None:
        raise HTTPException(
            status_code=503, detail="RAG corpus service not initialized"
        )
    return _job_manager


def get_vectordb_adapter(collection: str = None):
    """Get the vector DB adapter instance for a collection."""
    if not _vectordb_adapters:
        raise HTTPException(
            status_code=503, detail="RAG corpus service not initialized"
        )
    if collection:
        adapter = _vectordb_adapters.get(collection)
        if not adapter:
            raise HTTPException(status_code=404, detail=f"Collection not found: {collection}")
        return adapter
    # Return first adapter as default (for backwards compatibility)
    return next(iter(_vectordb_adapters.values()))


def get_all_vectordb_adapters():
    """Get all vector DB adapters."""
    if not _vectordb_adapters:
        raise HTTPException(
            status_code=503, detail="RAG corpus service not initialized"
        )
    return _vectordb_adapters


def get_embedding_adapter(model: str = None):
    """Get embedding adapter for a model."""
    if not _embedding_adapters:
        raise HTTPException(
            status_code=503, detail="RAG corpus service not initialized"
        )
    if model:
        adapter = _embedding_adapters.get(model)
        if not adapter:
            raise HTTPException(status_code=404, detail=f"Model not found: {model}")
        return adapter
    return next(iter(_embedding_adapters.values()))


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
    valid_sources = [
        "nextjs_docs",
        "stack_overflow",
        "github",
        "python_docs",
        "local_docs",
        "docker_docs",
        "kubernetes_docs",
    ]
    for source in request.sources:
        if source not in valid_sources:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid source: {source}. Valid sources: {valid_sources}",
            )

    try:
        # Log what we received
        logger.info(
            f"RAG Update Request - sources: {request.sources}, embedding_model: {request.embedding_model}"
        )

        # Create job
        job_id = await job_manager.create_job(
            sources=request.sources,
            keywords=request.keywords,
            extra_urls=request.extra_urls,
            python_libraries=request.python_libraries,
            docker_topics=request.docker_topics,
            kubernetes_topics=request.kubernetes_topics,
            embedding_model=request.embedding_model,
        )

        # Start background execution
        asyncio.create_task(job_manager.run_job_async(job_id))

        logger.info(
            f"Started RAG update job {job_id} for sources: {request.sources} with embedding_model: {request.embedding_model}"
        )

        return JobResponse(
            job_id=job_id,
            status="accepted",
            message=f"Job started for sources: {request.sources}",
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
    return {"jobs": [job.to_dict() for job in jobs], "count": len(jobs)}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running job."""
    job_manager = get_job_manager()

    cancelled = await job_manager.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Job not found or not running")

    return {"message": f"Job {job_id} cancelled"}


@router.get("/sources", response_model=SourceStats)
async def get_source_stats():
    """Get available sources and their index statistics across all collections."""
    adapters = get_all_vectordb_adapters()

    try:
        # Aggregate stats from all collections
        all_stats = {}
        for collection_name, adapter in adapters.items():
            try:
                stats = await adapter.get_source_stats()
                for source, count in stats.items():
                    all_stats[source] = all_stats.get(source, 0) + count
            except Exception as e:
                logger.warning(f"Error getting stats from {collection_name}: {e}")

        total = sum(all_stats.values())

        return SourceStats(
            available_sources=[
                "nextjs_docs",
                "stack_overflow",
                "github",
                "python_docs",
                "local_docs",
                "docker_docs",
                "kubernetes_docs",
            ],
            indexed_stats=all_stats,
            total_documents=total,
        )

    except Exception as e:
        logger.error(f"Failed to get source stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebuild")
async def rebuild_source(request: RebuildSourceRequest):
    """
    Rebuild (delete + re-index) a specific source.

    This will:
    1. Delete all vectors for the source from the appropriate collection
    2. Start a new update job for just that source
    """
    job_manager = get_job_manager()

    valid_sources = [
        "nextjs_docs",
        "stack_overflow",
        "github",
        "python_docs",
        "local_docs",
        "docker_docs",
        "kubernetes_docs",
    ]
    if request.source not in valid_sources:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source: {request.source}. Valid: {valid_sources}",
        )

    try:
        # Get the correct collection for this source
        collection_name = get_collection_for_source(request.source)
        model_name = get_embedding_model_for_source(request.source)
        vectordb = get_vectordb_adapter(collection_name)

        # Delete existing vectors
        deleted = await vectordb.delete_by_source(request.source)
        logger.info(f"Deleted {deleted} vectors for source {request.source} from {collection_name}")

        # Start new job (will auto-select correct model based on source)
        job_id = await job_manager.create_job(sources=[request.source])
        asyncio.create_task(job_manager.run_job_async(job_id))

        return {
            "job_id": job_id,
            "deleted": deleted,
            "collection": collection_name,
            "embedding_model": model_name,
            "message": f"Rebuilding {request.source} with {model_name} → {collection_name}",
        }

    except Exception as e:
        logger.error(f"Failed to rebuild source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sources/{source}")
async def clear_source(source: str):
    """Delete all vectors for a source from the appropriate collection."""
    valid_sources = [
        "nextjs_docs",
        "stack_overflow",
        "github",
        "python_docs",
        "local_docs",
        "docker_docs",
        "kubernetes_docs",
    ]
    if source not in valid_sources:
        raise HTTPException(
            status_code=400, detail=f"Invalid source: {source}. Valid: {valid_sources}"
        )

    try:
        # Get the correct collection for this source
        collection_name = get_collection_for_source(source)
        vectordb = get_vectordb_adapter(collection_name)

        deleted = await vectordb.delete_by_source(source)

        return {
            "source": source,
            "collection": collection_name,
            "deleted": deleted,
            "message": f"Cleared {deleted} documents from {source} in {collection_name}",
        }

    except Exception as e:
        logger.error(f"Failed to clear source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def rag_health_check():
    """Check health of RAG corpus services (multi-model)."""
    health = {"status": "healthy", "services": {}, "collections": {}, "embedding_models": {}}

    # Check job manager
    try:
        job_manager = get_job_manager()
        health["services"]["job_manager"] = "ok"
    except:
        health["services"]["job_manager"] = "unavailable"
        health["status"] = "degraded"

    # Check all vector DB collections
    try:
        adapters = get_all_vectordb_adapters()
        for name, adapter in adapters.items():
            try:
                vdb_health = await adapter.health_check()
                health["collections"][name] = vdb_health
            except Exception as e:
                health["collections"][name] = {"status": "error", "error": str(e)}
                health["status"] = "degraded"
        health["services"]["vectordb"] = "ok" if adapters else "unavailable"
    except Exception as e:
        health["services"]["vectordb"] = "unavailable"
        health["vectordb_error"] = str(e)
        health["status"] = "degraded"

    # Check all embedding adapters
    for model_name, adapter in _embedding_adapters.items():
        try:
            embed_health = await adapter.check_health()
            health["embedding_models"][model_name] = embed_health
        except Exception as e:
            health["embedding_models"][model_name] = {"status": "error", "error": str(e)}
            health["status"] = "degraded"

    health["services"]["embedding"] = "ok" if _embedding_adapters else "not_initialized"

    return health


@router.get("/config")
async def get_rag_config():
    """Get current RAG corpus configuration with multi-model setup."""
    return {
        "rag_dir": RAG_DIR,
        "ollama_url": OLLAMA_URL,
        "default_embedding_model": EMBEDDING_MODEL,
        "source_embedding_models": SOURCE_EMBEDDING_MODELS,
        "collections": EMBEDDING_COLLECTIONS,
        "available_sources": [
            "nextjs_docs",
            "stack_overflow",
            "github",
            "python_docs",
            "local_docs",
            "docker_docs",
            "kubernetes_docs",
        ],
        "source_categories": {
            "code_complex": {
                "sources": ["kubernetes_docs", "github", "stack_overflow"],
                "model": "qwen3-embedding",
                "collection": "local_rag_corpus_code",
                "dimensions": 2560,
            },
            "devops_general": {
                "sources": ["docker_docs", "python_docs", "nextjs_docs", "local_docs"],
                "model": "nomic-embed-text",
                "collection": "local_rag_corpus_docs",
                "dimensions": 768,
            },
        },
    }


@router.get("/models")
async def get_ollama_models():
    """
    Get available Ollama models for embedding.

    Returns list of models with their details, filtering for embedding-capable models.
    """
    import aiohttp

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(f"{OLLAMA_URL}/api/tags") as resp:
                if resp.status != 200:
                    raise HTTPException(
                        status_code=resp.status,
                        detail="Failed to get models from Ollama",
                    )

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

                    model_list.append(
                        {
                            "name": name,
                            "size_gb": round(size / (1024**3), 2) if size else 0,
                            "modified": modified,
                            "is_embedding_model": is_embedding,
                        }
                    )

                # Sort: embedding models first, then alphabetically
                model_list.sort(key=lambda x: (not x["is_embedding_model"], x["name"]))

                return {
                    "models": model_list,
                    "current_model": EMBEDDING_MODEL,
                    "total_count": len(model_list),
                }

    except aiohttp.ClientError as e:
        logger.error(f"Failed to connect to Ollama: {e}")
        raise HTTPException(status_code=503, detail=f"Cannot connect to Ollama: {e}")
    except Exception as e:
        logger.error(f"Error getting models: {e}")
        raise HTTPException(status_code=500, detail=str(e))
