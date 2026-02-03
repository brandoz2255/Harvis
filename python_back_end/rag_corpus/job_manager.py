"""
Job Manager for RAG Corpus Updates

Manages background jobs for fetching, chunking, and embedding documents
into the vector database.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Status of a RAG update job."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class Job:
    """Represents a RAG corpus update job."""

    id: str
    status: JobStatus
    sources: List[str]
    keywords: List[str] = field(default_factory=list)
    extra_urls: List[str] = field(default_factory=list)
    python_libraries: List[str] = field(default_factory=list)
    docker_topics: List[str] = field(default_factory=list)  # For docker_docs source
    kubernetes_topics: List[str] = field(
        default_factory=list
    )  # For kubernetes_docs source
    progress: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for API responses."""
        return {
            "id": self.id,
            "status": self.status.value,
            "sources": self.sources,
            "keywords": self.keywords,
            "extra_urls": self.extra_urls,
            "python_libraries": self.python_libraries,
            "docker_topics": self.docker_topics,
            "kubernetes_topics": self.kubernetes_topics,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class JobManager:
    """
    Manages RAG corpus update jobs.

    Provides in-memory job queue with background execution.
    Jobs are persisted to database for recovery.
    """

    def __init__(
        self,
        db_pool,
        rag_dir: str,
        ollama_url: str = "http://ollama:11434",
        embedding_model: str = "nomic-embed-text",  # 768 dims, excellent quality
    ):
        """
        Initialize the job manager.

        Args:
            db_pool: Database connection pool
            rag_dir: Directory for storing RAG documents
            ollama_url: URL of Ollama server
            embedding_model: Model to use for embeddings
        """
        self.db_pool = db_pool
        self.rag_dir = rag_dir
        self.ollama_url = ollama_url
        self.embedding_model = embedding_model
        self._jobs: Dict[str, Job] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}

        # Will be initialized lazily
        self._embedding_adapter = None
        self._vectordb_adapter = None
        self._fetchers = {}

    def _get_embedding_adapter(self):
        """Lazily initialize embedding adapter."""
        if self._embedding_adapter is None:
            from .embedding_adapter import EmbeddingAdapter

            self._embedding_adapter = EmbeddingAdapter(
                model_name=self.embedding_model, ollama_url=self.ollama_url
            )
        return self._embedding_adapter

    def _get_vectordb_adapter(self):
        """Lazily initialize vector DB adapter."""
        if self._vectordb_adapter is None:
            from .vectordb_adapter import VectorDBAdapter

            self._vectordb_adapter = VectorDBAdapter(
                db_pool=self.db_pool, collection_name="local_rag_corpus"
            )
        return self._vectordb_adapter

    def _get_fetcher(self, source: str, job: Job):
        """Get or create fetcher for a source with job-specific parameters."""
        # Create fetcher with job-specific parameters
        from .source_fetchers import get_fetcher

        fetcher_kwargs = {}
        if source == "python_docs":
            fetcher_kwargs["python_libraries"] = job.python_libraries
        elif source == "docker_docs":
            fetcher_kwargs["docker_topics"] = job.docker_topics
        elif source == "kubernetes_docs":
            fetcher_kwargs["kubernetes_topics"] = job.kubernetes_topics
        elif source == "local_docs":
            fetcher_kwargs["docs_dirs"] = ["./docs"]

        return get_fetcher(source, **fetcher_kwargs)

    async def create_job(
        self,
        sources: List[str],
        keywords: Optional[List[str]] = None,
        extra_urls: Optional[List[str]] = None,
        python_libraries: Optional[List[str]] = None,
        docker_topics: Optional[List[str]] = None,
        kubernetes_topics: Optional[List[str]] = None,
    ) -> str:
        """
        Create a new RAG update job.

        Args:
            sources: List of source types to fetch
            keywords: Optional keywords to filter content
            extra_urls: Optional specific URLs to fetch
            python_libraries: Optional Python library names for python_docs source
            docker_topics: Optional Docker topics for docker_docs source (engine, compose, swarm, etc.)
            kubernetes_topics: Optional Kubernetes topics for kubernetes_docs source (concepts, tasks, networking, etc.)

        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            status=JobStatus.PENDING,
            sources=sources,
            keywords=keywords or [],
            extra_urls=extra_urls or [],
            python_libraries=python_libraries or [],
            docker_topics=docker_topics or [],
            kubernetes_topics=kubernetes_topics or [],
            progress={
                "total_docs": 0,
                "processed": 0,
                "current_source": None,
                "current_phase": "pending",
            },
        )
        self._jobs[job_id] = job
        logger.info(f"Created RAG update job {job_id} for sources: {sources}")
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 10) -> List[Job]:
        """List recent jobs."""
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def run_job_async(self, job_id: str) -> None:
        """
        Run a job asynchronously in the background.

        Args:
            job_id: ID of the job to run
        """
        job = self._jobs.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        # Create background task
        task = asyncio.create_task(self._execute_job(job))
        self._running_tasks[job_id] = task

        # Clean up task reference when done
        def cleanup(t):
            self._running_tasks.pop(job_id, None)

        task.add_done_callback(cleanup)

    async def _execute_job(self, job: Job) -> None:
        """Execute the job pipeline with per-source embedding models."""
        try:
            job.status = JobStatus.RUNNING
            job.updated_at = datetime.utcnow()
            job.progress["current_phase"] = "fetching"

            from .chunker import DocumentChunker

            chunker = DocumentChunker(
                chunk_size=1000, overlap=200, rag_dir=self.rag_dir
            )

            # Import source-to-model mapping
            try:
                from rag_corpus.routes import (
                    get_embedding_model_for_source,
                    get_collection_for_source,
                )
            except ImportError:
                # Fallback if routes not available - use default model
                def get_embedding_model_for_source(s):
                    return self.embedding_model

                def get_collection_for_source(s):
                    return "local_rag_corpus"

            # Group sources by their embedding model
            sources_by_model = {}
            for source in job.sources:
                # Always use source-specific model for optimal embeddings
                model = get_embedding_model_for_source(source)

                if model not in sources_by_model:
                    sources_by_model[model] = []
                sources_by_model[model].append(source)

            logger.info(
                f"Job {job.id}: Processing sources grouped by model: {sources_by_model}"
            )

            total_processed = 0

            # Process each model group separately
            for model_name, sources in sources_by_model.items():
                logger.info(
                    f"Job {job.id}: Processing {sources} with model {model_name}"
                )

                # Create embedding adapter for this model
                from .embedding_adapter import EmbeddingAdapter

                embedding_adapter = EmbeddingAdapter(
                    model_name=model_name,
                    ollama_url=self.ollama_url,
                )

                # Get collection for this model
                collection_name = get_collection_for_source(sources[0])

                # Create vectordb adapter for this collection
                from .vectordb_adapter import VectorDBAdapter

                vectordb_adapter = VectorDBAdapter(
                    db_pool=self.db_pool,
                    collection_name=collection_name,
                )

                logger.info(
                    f"Job {job.id}: Using model '{model_name}' → collection '{collection_name}'"
                )

                all_chunks = []

                # Phase 1: Fetch and chunk documents from each source in this group
                for source in sources:
                    job.progress["current_source"] = source
                    job.progress["current_model"] = model_name
                    job.updated_at = datetime.utcnow()
                    logger.info(f"Job {job.id}: Fetching from {source}")

                    try:
                        # Try to get source config for dynamic fetcher creation
                        source_config = None
                        try:
                            from rag_corpus.source_config import get_config_manager

                            config_mgr = await get_config_manager()
                            source_config = config_mgr.get(source)
                        except Exception:
                            pass  # Fall back to legacy fetcher selection

                        if source_config:
                            # Use dynamic config-based fetcher
                            from .source_fetchers import get_fetcher_for_config

                            fetcher = get_fetcher_for_config(source_config)
                            documents = await fetcher.fetch(
                                keywords=job.keywords, extra_urls=job.extra_urls
                            )
                        # Legacy handling for python_docs source
                        elif source == "python_docs":
                            from .source_fetchers import PythonDocsFetcher

                            fetcher = PythonDocsFetcher(
                                python_libraries=job.python_libraries
                            )
                            documents = await fetcher.fetch(
                                keywords=job.keywords,
                                extra_urls=job.extra_urls,
                                python_libraries=job.python_libraries,
                            )
                        # Legacy handling for local_docs source
                        elif source == "local_docs":
                            from .source_fetchers import LocalDocsFetcher

                            fetcher = LocalDocsFetcher(
                                docs_dirs=[
                                    self.rag_dir,
                                    "/app/docs",
                                    "./docs",
                                ]
                            )
                            documents = await fetcher.fetch(
                                keywords=job.keywords, extra_urls=job.extra_urls
                            )
                        else:
                            fetcher = self._get_fetcher(source, job)
                            documents = await fetcher.fetch(
                                keywords=job.keywords, extra_urls=job.extra_urls
                            )

                        logger.info(
                            f"Job {job.id}: Fetched {len(documents)} documents from {source}"
                        )

                        # Chunk documents
                        for doc in documents:
                            chunks = chunker.chunk_document(doc)
                            all_chunks.extend(chunks)

                    except Exception as e:
                        logger.error(f"Job {job.id}: Error fetching from {source}: {e}")
                        # Continue with other sources

                if not all_chunks:
                    logger.warning(
                        f"Job {job.id}: No chunks for model group {model_name}"
                    )
                    continue

                job.progress["total_docs"] = job.progress.get("total_docs", 0) + len(
                    all_chunks
                )
                job.progress["current_phase"] = "embedding"
                job.updated_at = datetime.utcnow()

                # Phase 2: Generate embeddings
                logger.info(
                    f"Job {job.id}: Generating embeddings for {len(all_chunks)} chunks with {model_name}"
                )

                # Persist chunks to RAG directory
                chunker.persist_chunks(all_chunks)

                # Generate embeddings in batches
                texts = [chunk.text for chunk in all_chunks]
                embeddings = await embedding_adapter.embed_batch(texts, batch_size=32)

                # Phase 3: Upsert to vector database
                job.progress["current_phase"] = "upserting"
                job.updated_at = datetime.utcnow()
                logger.info(f"Job {job.id}: Upserting to {collection_name}")

                from .vectordb_adapter import VectorRecord

                records = []
                for chunk, embedding in zip(all_chunks, embeddings):
                    records.append(
                        VectorRecord(
                            id=chunk.id,
                            embedding=embedding,
                            text=chunk.text,
                            metadata=chunk.metadata,
                        )
                    )

                await vectordb_adapter.upsert_vectors(records)
                total_processed += len(records)
                job.progress["processed"] = total_processed

                # Close embedding adapter session
                await embedding_adapter.close()

            # Done!
            job.status = JobStatus.COMPLETED
            job.progress["current_phase"] = "completed"
            job.updated_at = datetime.utcnow()
            logger.info(
                f"Job {job.id}: Completed successfully. Processed {total_processed} chunks across {len(sources_by_model)} model groups."
            )

        except Exception as e:
            logger.exception(f"Job {job.id}: Failed with error: {e}")
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.progress["current_phase"] = "failed"
            job.updated_at = datetime.utcnow()

    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a running job.

        Args:
            job_id: ID of the job to cancel

        Returns:
            True if cancelled, False if job not found or not running
        """
        task = self._running_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            job = self._jobs.get(job_id)
            if job:
                job.status = JobStatus.FAILED
                job.error = "Cancelled by user"
                job.updated_at = datetime.utcnow()
            return True
        return False
