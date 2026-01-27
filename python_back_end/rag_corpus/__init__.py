"""
RAG Corpus Manager Module

This module provides functionality for managing local RAG corpus including:
- Source fetching (Next.js docs, Stack Overflow, GitHub, Python docs)
- Document chunking and processing
- Embedding generation via Ollama or HuggingFace
- Vector database operations with pgvector

Usage:
    from rag_corpus import JobManager, SourceStats
    
    job_manager = JobManager(db_pool, rag_dir)
    job_id = await job_manager.create_job(sources=["nextjs_docs"])
    await job_manager.run_job_async(job_id)
"""

from .job_manager import JobManager, Job, JobStatus
from .source_fetchers import (
    BaseFetcher,
    NextJSDocsFetcher,
    StackOverflowFetcher,
    GitHubFetcher,
    PythonDocsFetcher,
    get_fetcher
)
from .chunker import DocumentChunker, Chunk, RawDocument
from .embedding_adapter import EmbeddingAdapter
from .vectordb_adapter import VectorDBAdapter, VectorRecord, SearchResult, LocalRAGRetriever
from .routes import router as rag_router, initialize_rag_corpus

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
    "get_fetcher",
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
    # API
    "rag_router",
    "initialize_rag_corpus",
]

