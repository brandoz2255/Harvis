"""
RAG Corpus Manager Module

This module provides functionality for managing local RAG corpus including:
- Dynamic source configuration (DevOps, Security, Code, General)
- Source fetching (K8s, Docker, Ansible, Helm, GitLab, GitHub, etc.)
- Document chunking and processing
- Embedding generation via Ollama (multi-model support)
- Vector database operations with pgvector (multi-collection)

Usage:
    from rag_corpus import JobManager, SourceConfigManager

    job_manager = JobManager(db_pool, rag_dir)
    job_id = await job_manager.create_job(sources=["kubernetes_docs", "ansible_docs"])
    await job_manager.run_job_async(job_id)
"""

from .job_manager import JobManager, Job, JobStatus
from .source_fetchers import (
    BaseFetcher,
    NextJSDocsFetcher,
    StackOverflowFetcher,
    GitHubFetcher,
    PythonDocsFetcher,
    DockerDocsFetcher,
    KubernetesDocsFetcher,
    GenericDocsFetcher,
    get_fetcher,
    get_fetcher_for_config,
)
from .chunker import DocumentChunker, Chunk, RawDocument
from .embedding_adapter import EmbeddingAdapter
from .vectordb_adapter import (
    VectorDBAdapter,
    VectorRecord,
    SearchResult,
    LocalRAGRetriever,
    MultiCollectionRetriever,
)
from .source_config import (
    SourceConfig,
    SourceCategory,
    EmbeddingTier,
    SourceConfigManager,
    get_config_manager,
    DEFAULT_SOURCES,
    EMBEDDING_TIER_CONFIG,
)
from .routes import (
    router as rag_router,
    initialize_rag_corpus,
    get_all_vectordb_adapters,
    get_all_embedding_adapters,
    get_config_manager_instance,
    EMBEDDING_COLLECTIONS,
)

__all__ = [
    # Job Management
    "JobManager",
    "Job",
    "JobStatus",
    # Fetchers
    "BaseFetcher",
    "NextJSDocsFetcher",
    "StackOverflowFetcher",
    "GitHubFetcher",
    "PythonDocsFetcher",
    "DockerDocsFetcher",
    "KubernetesDocsFetcher",
    "GenericDocsFetcher",
    "get_fetcher",
    "get_fetcher_for_config",
    # Processing
    "DocumentChunker",
    "Chunk",
    "RawDocument",
    # Adapters
    "EmbeddingAdapter",
    "VectorDBAdapter",
    "VectorRecord",
    "SearchResult",
    "LocalRAGRetriever",
    "MultiCollectionRetriever",
    # Source Configuration
    "SourceConfig",
    "SourceCategory",
    "EmbeddingTier",
    "SourceConfigManager",
    "get_config_manager",
    "DEFAULT_SOURCES",
    "EMBEDDING_TIER_CONFIG",
    # API
    "rag_router",
    "initialize_rag_corpus",
    "get_all_vectordb_adapters",
    "get_all_embedding_adapters",
    "get_config_manager_instance",
    "EMBEDDING_COLLECTIONS",
]

