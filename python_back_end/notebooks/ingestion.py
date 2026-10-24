"""
Ingestion Service for NotebookLM
Handles text extraction, chunking, and embedding generation
"""

import asyncio
import logging
import os
import re
from typing import List, Tuple, Dict, Any, Optional
from uuid import UUID
import requests

from .extractors import IngestionError, extract_for
from .models import SourceStatus
from .manager import NotebookManager

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
CHUNK_SIZE = 1000  # Target chunk size in characters
CHUNK_OVERLAP = 200  # Overlap between chunks
TARGET_DIM = 4096  # Width of notebook_chunks.embedding
# Stop trying after this many embeddings in a row fail: the model is missing or the
# server is down, and every further attempt would just wait out its timeout.
MAX_CONSECUTIVE_EMBED_FAILURES = 3
# A source where more than this share of chunks could not be embedded is an error,
# because the chunks that remain would give answers from a random slice of it.
MAX_SKIPPED_SHARE = 0.5

NO_EMBEDDER_MESSAGE = (
    "Notebooks could not index this source because no embedding model answered. "
    "Install one (ollama pull nomic-embed-text) and press Retry."
)


class IngestionService:
    """
    Service for ingesting sources into the notebook.
    Handles:
    - Text extraction from PDFs, URLs, plain text, images, audio (see extractors.py)
    - Text chunking with overlap
    - Embedding generation via Ollama
    - Storing chunks in the database
    """

    _working_model: str | None = None

    def __init__(self, manager: NotebookManager):
        self.manager = manager

    async def ingest_source(self, source_id: UUID, user_id: int) -> None:
        """
        Main ingestion pipeline for a source. Runs in the background.

        A source ends in exactly one of two states: ``ready`` (its chunks are
        searchable) or ``error`` with a sentence the user can act on. Nothing
        is left ``ready`` with unsearchable chunks.
        """
        try:
            source = await self.manager.get_source(source_id, user_id)
            await self.manager.update_source_status(source_id, SourceStatus.PROCESSING)
            # Retry must not stack a second copy of the chunks on top of the first.
            await self.manager.clear_chunks(source_id)
            logger.info(f"Starting ingestion for source {source_id} (type: {source.type})")

            text = await self._extract_text(source)
            if not text or len(text.strip()) < 10:
                raise IngestionError("No text could be extracted from this source.")

            async with self.manager.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE notebook_sources SET content_text = $1 WHERE id = $2", text, source_id
                )

            chunks = self._chunk_text(text, source)
            if not chunks:
                raise IngestionError("The text could not be split into passages.")
            logger.info(f"Created {len(chunks)} chunks for source {source_id}")

            chunk_data, skipped = await self._embed_chunks(chunks)
            chunk_count = await self.manager.create_chunks(source_id, source.notebook_id, chunk_data)

            meta: Dict[str, Any] = {"chunk_count": chunk_count, "text_length": len(text), "skipped_chunks": skipped}
            await self.manager.update_source_status(source_id, SourceStatus.READY, metadata_update=meta)
            logger.info(f"Successfully ingested source {source_id} with {chunk_count} chunks ({skipped} skipped)")

        except IngestionError as e:
            logger.warning(f"Ingestion failed for source {source_id}: {e}")
            await self.manager.update_source_status(source_id, SourceStatus.ERROR, error_message=str(e))
        except Exception as e:
            logger.error(f"Ingestion failed for source {source_id}: {e}", exc_info=True)
            await self.manager.update_source_status(
                source_id, SourceStatus.ERROR, error_message=f"Something went wrong reading this source: {str(e)[:200]}"
            )

    async def _embed_chunks(self, chunks) -> Tuple[list, int]:
        """Embed every chunk. Never stores a placeholder vector.

        Raises IngestionError when nothing could be embedded or too much was lost,
        so the source shows as failed and Retry has something to do.
        """
        chunk_data = []
        skipped = 0
        streak = 0
        for i, (chunk_text, metadata) in enumerate(chunks):
            if streak >= MAX_CONSECUTIVE_EMBED_FAILURES:
                skipped += 1
                continue
            embedding = await self._get_embedding(chunk_text)
            if embedding:
                streak = 0
                chunk_data.append((chunk_text, self._normalize_embedding_dimension(embedding, TARGET_DIM), metadata, i))
            else:
                streak += 1
                skipped += 1
        if not chunk_data:
            raise IngestionError(NO_EMBEDDER_MESSAGE)
        if skipped / len(chunks) > MAX_SKIPPED_SHARE:
            raise IngestionError(
                f"Only {len(chunk_data)} of {len(chunks)} passages could be indexed because the embedding model "
                "stopped answering. Check that it is running and press Retry."
            )
        if skipped:
            logger.warning(f"{skipped} of {len(chunks)} chunks could not be embedded and were left out")
        return chunk_data, skipped

    async def _extract_text(self, source) -> str:
        """Extract text from a source. Raises IngestionError with a user-facing reason."""
        logger.info(f"Extracting text for source type: {source.type}, path: {source.storage_path}")
        try:
            return await extract_for(source)
        except IngestionError:
            # Pasted text is stored in the DB as well as on disk; fall back to it
            # if the file was cleaned up.
            if getattr(source.type, "value", source.type) in ("text", "markdown") and not (
                source.storage_path and os.path.exists(source.storage_path)
            ):
                async with self.manager.db_pool.acquire() as conn:
                    stored = await conn.fetchval("SELECT content_text FROM notebook_sources WHERE id = $1", source.id)
                if stored:
                    return stored
            raise

    def _chunk_text(self, text: str, source) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Split text into overlapping chunks.
        Returns list of (chunk_text, metadata) tuples.
        """
        chunks = []

        # Clean up text
        text = text.strip()
        if not text:
            return chunks

        # Split into paragraphs first
        paragraphs = re.split(r'\n\s*\n', text)

        current_chunk = ""
        current_metadata = {"source_title": source.title, "paragraphs": []}

        for i, para in enumerate(paragraphs):
            para = para.strip()
            if not para:
                continue

            # If adding this paragraph exceeds chunk size, save current and start new
            if len(current_chunk) + len(para) > CHUNK_SIZE and current_chunk:
                chunks.append((current_chunk.strip(), current_metadata.copy()))

                # Start new chunk with overlap
                overlap_text = current_chunk[-CHUNK_OVERLAP:] if len(current_chunk) > CHUNK_OVERLAP else current_chunk
                current_chunk = overlap_text + "\n\n" + para
                current_metadata = {"source_title": source.title, "paragraphs": [i]}
            else:
                current_chunk += ("\n\n" if current_chunk else "") + para
                current_metadata["paragraphs"].append(i)

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append((current_chunk.strip(), current_metadata))

        # If we have very few chunks, try to balance them
        if len(chunks) == 1 and len(chunks[0][0]) > CHUNK_SIZE * 2:
            # Re-chunk with sentence-level splitting
            chunks = self._chunk_by_sentences(text, source)

        return chunks

    def _chunk_by_sentences(self, text: str, source) -> List[Tuple[str, Dict[str, Any]]]:
        """Chunk text by sentences for more granular splitting"""
        # Simple sentence splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
        current_chunk = ""
        current_sentences = []

        for i, sentence in enumerate(sentences):
            if len(current_chunk) + len(sentence) > CHUNK_SIZE and current_chunk:
                chunks.append((current_chunk.strip(), {
                    "source_title": source.title,
                    "sentence_indices": current_sentences.copy()
                }))

                # Overlap
                overlap_start = max(0, len(current_sentences) - 2)
                current_chunk = " ".join(sentences[overlap_start:i]) + " " + sentence
                current_sentences = list(range(overlap_start, i + 1))
            else:
                current_chunk += (" " if current_chunk else "") + sentence
                current_sentences.append(i)

        if current_chunk.strip():
            chunks.append((current_chunk.strip(), {
                "source_title": source.title,
                "sentence_indices": current_sentences
            }))

        return chunks

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding vector for text using Ollama with cached model selection.

        The HTTP calls are blocking ``requests`` calls, so they run in a worker
        thread; called directly they froze the whole event loop for up to a
        minute per chunk.
        """
        # If we already found a working model, use it directly
        if IngestionService._working_model:
            result = await asyncio.to_thread(self._try_embedding, OLLAMA_URL, IngestionService._working_model, text)
            if result is not None:
                return result
            IngestionService._working_model = None

        # nomic-embed-text (the default) is the dedicated embedder; the rest are
        # preferred fallbacks. A hardcoded list only works on a deploy that happens
        # to have one of these pulled, so after the preferred names we try whatever
        # embedding model Ollama actually reports as installed. A chat model is
        # never used: its vectors live in a different space, so installing nomic
        # later would leave every earlier chunk unfindable.
        from .embedder_status import is_embedder

        embedding_models = [
            EMBEDDING_MODEL,          # nomic-embed-text (dedicated, default)
            "qwen3-embedding:4b",
            "mxbai-embed-large",
        ]
        for model in await asyncio.to_thread(self._installed_models):
            if model not in embedding_models and is_embedder(model):
                embedding_models.append(model)

        for model in embedding_models:
            result = await asyncio.to_thread(self._try_embedding, OLLAMA_URL, model, text)
            if result is not None:
                IngestionService._working_model = model
                logger.info(f"Locked embedding model to: {model}")
                return result

        logger.error(
            "All embedding models failed - tried %s. Pull an embedding model "
            "(e.g. `ollama pull nomic-embed-text`) or set EMBEDDING_MODEL.",
            ", ".join(embedding_models) or "<none installed>",
        )
        return None

    @staticmethod
    def _installed_models() -> List[str]:
        """
        Models Ollama actually has, embedding-looking names first. Never raises —
        an unreachable Ollama just means we fall back to the preferred list.
        """
        try:
            response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
            if response.status_code != 200:
                return []
            # Cloud-hosted models would send the source text off the machine; never fall back to one.
            from owui_compat.ollama_hosts import drop_cloud

            names = [m.get("name") for m in drop_cloud(response.json().get("models", [])) if m.get("name")]
        except Exception:
            logger.warning("Could not list Ollama models for embedding fallback", exc_info=True)
            return []
        return sorted(names, key=lambda n: "embed" not in n.lower())

    def _try_embedding(self, base_url: str, model: str, text: str) -> Optional[List[float]]:
        """Try to get an embedding from a specific model. Returns None on failure."""
        try:
            response = requests.post(
                f"{base_url}/api/embeddings",
                json={"model": model, "prompt": text[:8000]},
                timeout=60
            )
            if response.status_code == 200:
                embedding = response.json().get("embedding")
                if embedding:
                    return embedding
        except Exception:
            pass
        return None

    def _normalize_embedding_dimension(self, embedding: List[float], target_dim: int) -> List[float]:
        """
        Normalize embedding to target dimension.
        - If embedding is shorter, pad with zeros
        - If embedding is longer, truncate
        """
        current_dim = len(embedding)
        
        if current_dim == target_dim:
            return embedding
        elif current_dim < target_dim:
            # Pad with zeros
            logger.debug(f"Padding embedding from {current_dim} to {target_dim} dimensions")
            return embedding + [0.0] * (target_dim - current_dim)
        else:
            # Truncate
            logger.debug(f"Truncating embedding from {current_dim} to {target_dim} dimensions")
            return embedding[:target_dim]

    async def get_query_embedding(self, query: str) -> Optional[List[float]]:
        """Get embedding for a search query (public method for RAG)"""
        embedding = await self._get_embedding(query)
        if embedding:
            return self._normalize_embedding_dimension(embedding, TARGET_DIM)
        return None


# Background task runner for ingestion
async def run_ingestion_task(
    manager: NotebookManager,
    source_id: UUID,
    user_id: int
) -> None:
    """Run ingestion as a background task"""
    service = IngestionService(manager)
    await service.ingest_source(source_id, user_id)
