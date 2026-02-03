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
EMBEDDING_MODEL = os.getenv(
    "RAG_EMBEDDING_MODEL", "nomic-embed-text"
)  # 768 dims, default

# Per-source embedding model configuration
# qwen3-embedding: 4096 dims - for complex technical/code content
# nomic-embed-text: 768 dims - for general devops/docs
SOURCE_EMBEDDING_MODELS = {
    # Technical/Code-heavy sources → qwen3-embedding (full 4096 dims)
    "kubernetes_docs": "qwen3-embedding",  # Complex edge cases, YAML configs
    "github": "qwen3-embedding",  # Code repositories
    "stack_overflow": "qwen3-embedding",  # Code Q&A with nuanced answers
    "docker_docs": "qwen3-embedding",  # Dockerfile DSL, Compose YAML, orchestration
    "python_docs": "qwen3-embedding",  # API signatures, type hints, decorators, async patterns
    "nextjs_docs": "qwen3-embedding",  # React patterns, TypeScript APIs, App Router concepts
    # Process/General docs → nomic-embed-text (768 dims)
    "local_docs": "nomic-embed-text",  # Playbooks, guidelines, best practices (less code density)
}


def get_embedding_model_for_source(source: str) -> str:
    """Get the appropriate embedding model for a source type."""
    # Try dynamic config first
    if _config_manager:
        config = _config_manager.get(source)
        if config:
            return config.get_embedding_model()
    # Fallback to static config
    return SOURCE_EMBEDDING_MODELS.get(source, EMBEDDING_MODEL)


# Collection names based on embedding model (different dims need separate tables)
EMBEDDING_COLLECTIONS = {
    "qwen3-embedding": "local_rag_corpus_code",  # 4096 dims - code/complex
    "nomic-embed-text": "local_rag_corpus_docs",  # 768 dims - general docs
}


def get_collection_for_source(source: str) -> str:
    """Get the vector collection name for a source type."""
    # Try dynamic config first
    if _config_manager:
        config = _config_manager.get(source)
        if config:
            return config.get_collection()
    # Fallback to static config
    model = get_embedding_model_for_source(source)
    return EMBEDDING_COLLECTIONS.get(model, "local_rag_corpus_docs")


def get_valid_sources() -> List[str]:
    """Get list of all valid source IDs."""
    if _config_manager:
        return _config_manager.get_valid_source_ids()
    return list(SOURCE_EMBEDDING_MODELS.keys())


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
                logger.info(
                    f"Initialized embedding adapter: {model_name} ({config['dimensions']} dims)"
                )

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
            raise HTTPException(
                status_code=404, detail=f"Collection not found: {collection}"
            )
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


def get_all_embedding_adapters():
    """Get all embedding adapters."""
    if not _embedding_adapters:
        raise HTTPException(
            status_code=503, detail="RAG corpus service not initialized"
        )
    return _embedding_adapters


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

    # Validate sources using dynamic config
    valid_sources = get_valid_sources()
    for source in request.sources:
        if source not in valid_sources:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid source: {source}. Valid sources: {valid_sources}",
            )

    try:
        # Log what we received
        logger.info(f"RAG Update Request - sources: {request.sources}")

        # Create job - backend automatically selects optimal embedding model per source
        job_id = await job_manager.create_job(
            sources=request.sources,
            keywords=request.keywords,
            extra_urls=request.extra_urls,
            python_libraries=request.python_libraries,
            docker_topics=request.docker_topics,
            kubernetes_topics=request.kubernetes_topics,
        )

        # Start background execution
        asyncio.create_task(job_manager.run_job_async(job_id))

        logger.info(f"Started RAG update job {job_id} for sources: {request.sources}")

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
            available_sources=get_valid_sources(),
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

    valid_sources = get_valid_sources()
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
        logger.info(
            f"Deleted {deleted} vectors for source {request.source} from {collection_name}"
        )

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
    valid_sources = get_valid_sources()
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
    health = {
        "status": "healthy",
        "services": {},
        "collections": {},
        "embedding_models": {},
    }

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
            health["embedding_models"][model_name] = {
                "status": "error",
                "error": str(e),
            }
            health["status"] = "degraded"

    health["services"]["embedding"] = "ok" if _embedding_adapters else "not_initialized"

    return health


@router.get("/config")
async def get_rag_config():
    """Get current RAG corpus configuration with multi-model setup."""
    # Get dynamic sources if available
    available_sources = get_valid_sources()

    # Build source model mapping from config
    source_model_mapping = {}
    if _config_manager:
        source_model_mapping = _config_manager.get_source_model_mapping()
    else:
        source_model_mapping = SOURCE_EMBEDDING_MODELS

    return {
        "rag_dir": RAG_DIR,
        "ollama_url": OLLAMA_URL,
        "default_embedding_model": EMBEDDING_MODEL,
        "source_embedding_models": source_model_mapping,
        "collections": EMBEDDING_COLLECTIONS,
        "available_sources": available_sources,
        "source_count": len(available_sources),
        "embedding_tiers": {
            "high": {
                "model": "qwen3-embedding",
                "collection": "local_rag_corpus_code",
                "dimensions": 4096,
                "description": "For complex code/technical content",
            },
            "standard": {
                "model": "nomic-embed-text",
                "collection": "local_rag_corpus_docs",
                "dimensions": 768,
                "description": "For general documentation",
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


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE CONFIGURATION MANAGEMENT API
# ═══════════════════════════════════════════════════════════════════════════════


def get_config_manager_instance():
    """Get the config manager instance."""
    if _config_manager is None:
        raise HTTPException(
            status_code=503, detail="Source config manager not initialized"
        )
    return _config_manager


@router.get("/sources/config")
async def list_source_configs():
    """
    List all available source configurations.

    Returns sources grouped by category with their embedding tier info.
    """
    config_mgr = get_config_manager_instance()

    all_configs = config_mgr.get_all()

    # Group by category
    by_category = {}
    for source_id, config in all_configs.items():
        category = config.category.value
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(
            {
                "id": config.id,
                "name": config.name,
                "description": config.description,
                "enabled": config.enabled,
                "embedding_tier": config.embedding_tier.value,
                "embedding_model": config.get_embedding_model(),
                "collection": config.get_collection(),
                "fetcher_type": config.fetcher_type,
                "base_url": config.base_url,
            }
        )

    return {
        "sources": by_category,
        "total_count": len(all_configs),
        "enabled_count": len(config_mgr.get_enabled()),
        "categories": ["code", "devops", "security", "general"],
        "embedding_tiers": {
            "high": {"model": "qwen3-embedding", "dimensions": 2560},
            "standard": {"model": "nomic-embed-text", "dimensions": 768},
        },
    }


@router.get("/sources/config/{source_id}")
async def get_source_config(source_id: str):
    """Get configuration for a specific source."""
    config_mgr = get_config_manager_instance()

    config = config_mgr.get(source_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")

    return config.to_dict()


@router.post("/sources/config")
async def add_source_config(request: SourceConfigRequest):
    """
    Add a new source configuration.

    This allows adding custom documentation sources via the API/UI.
    """
    config_mgr = get_config_manager_instance()

    # Check if source already exists
    if config_mgr.get(request.id):
        raise HTTPException(
            status_code=400,
            detail=f"Source already exists: {request.id}. Use PUT to update.",
        )

    try:
        from rag_corpus.source_config import SourceConfig, SourceCategory, EmbeddingTier

        config = SourceConfig(
            id=request.id,
            name=request.name,
            description=request.description,
            category=SourceCategory(request.category),
            embedding_tier=EmbeddingTier(request.embedding_tier),
            enabled=request.enabled,
            fetcher_type=request.fetcher_type,
            base_url=request.base_url,
            sitemap_url=request.sitemap_url,
            options=request.options,
            rate_limit_delay=request.rate_limit_delay,
            max_pages=request.max_pages,
            url_patterns=request.url_patterns,
            exclude_patterns=request.exclude_patterns,
        )

        await config_mgr.add(config)

        return {
            "message": f"Added source: {request.id}",
            "config": config.to_dict(),
        }

    except Exception as e:
        logger.error(f"Failed to add source config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/sources/config/{source_id}")
async def update_source_config(source_id: str, request: SourceConfigRequest):
    """Update an existing source configuration."""
    config_mgr = get_config_manager_instance()

    if not config_mgr.get(source_id):
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")

    try:
        from rag_corpus.source_config import SourceConfig, SourceCategory, EmbeddingTier

        config = SourceConfig(
            id=source_id,  # Use path param, not body
            name=request.name,
            description=request.description,
            category=SourceCategory(request.category),
            embedding_tier=EmbeddingTier(request.embedding_tier),
            enabled=request.enabled,
            fetcher_type=request.fetcher_type,
            base_url=request.base_url,
            sitemap_url=request.sitemap_url,
            options=request.options,
            rate_limit_delay=request.rate_limit_delay,
            max_pages=request.max_pages,
            url_patterns=request.url_patterns,
            exclude_patterns=request.exclude_patterns,
        )

        await config_mgr.update(config)

        return {
            "message": f"Updated source: {source_id}",
            "config": config.to_dict(),
        }

    except Exception as e:
        logger.error(f"Failed to update source config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sources/config/{source_id}")
async def delete_source_config(source_id: str):
    """Delete a source configuration."""
    config_mgr = get_config_manager_instance()

    if not config_mgr.get(source_id):
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")

    try:
        await config_mgr.delete(source_id)
        return {"message": f"Deleted source: {source_id}"}

    except Exception as e:
        logger.error(f"Failed to delete source config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/config/{source_id}/toggle")
async def toggle_source(source_id: str, request: SourceToggleRequest):
    """Enable or disable a source."""
    config_mgr = get_config_manager_instance()

    if not config_mgr.get(source_id):
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")

    try:
        await config_mgr.toggle_enabled(source_id, request.enabled)

        return {
            "message": f"{'Enabled' if request.enabled else 'Disabled'} source: {source_id}",
            "enabled": request.enabled,
        }

    except Exception as e:
        logger.error(f"Failed to toggle source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/config/reset")
async def reset_source_configs():
    """Reset all source configurations to defaults."""
    config_mgr = get_config_manager_instance()

    try:
        await config_mgr.reset_to_defaults()
        return {
            "message": "Reset all source configurations to defaults",
            "source_count": len(config_mgr.get_all()),
        }

    except Exception as e:
        logger.error(f"Failed to reset configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/categories")
async def get_source_categories():
    """Get available source categories and their descriptions."""
    return {
        "categories": {
            "code": {
                "name": "Code/Complex",
                "description": "Complex technical content, code repositories, Q&A",
                "embedding_tier": "high",
                "model": "qwen3-embedding",
                "dimensions": 2560,
                "examples": ["kubernetes_docs", "github", "stack_overflow"],
            },
            "devops": {
                "name": "DevOps/Infrastructure",
                "description": "DevOps tools, CI/CD, infrastructure documentation",
                "embedding_tier": "standard",
                "model": "nomic-embed-text",
                "dimensions": 768,
                "examples": [
                    "docker_docs",
                    "ansible_docs",
                    "helm_docs",
                    "terraform_docs",
                ],
            },
            "security": {
                "name": "Security/Cyber",
                "description": "Security frameworks, threat intelligence, playbooks",
                "embedding_tier": "standard",
                "model": "nomic-embed-text",
                "dimensions": 768,
                "examples": ["mitre_attack", "owasp_docs"],
            },
            "general": {
                "name": "General Documentation",
                "description": "General programming docs, frameworks, local files",
                "embedding_tier": "standard",
                "model": "nomic-embed-text",
                "dimensions": 768,
                "examples": ["python_docs", "nextjs_docs", "local_docs"],
            },
        },
    }
