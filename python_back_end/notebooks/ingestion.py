"""
Ingestion Service for NotebookLM
Handles text extraction, chunking, and embedding generation
"""

import asyncio
import inspect
import logging
import os
import re
from bisect import bisect_right
from typing import List, Tuple, Dict, Any, Optional
from uuid import UUID
import requests

from . import embedding_provider
from .extractors import Extracted, IngestionError, extract_document
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
EMBED_BATCH_SIZE = 16  # texts per Ollama /api/embed request
# Text beyond this is not indexed; the source records that it was cut (NOTEBOOK_MAX_SOURCE_CHARS).
DEFAULT_MAX_SOURCE_CHARS = 2_000_000

NO_EMBEDDER_MESSAGE = (
    "Notebooks could not index this source because no embedding model answered. "
    "Install one (ollama pull nomic-embed-text) and press Retry."
)
REMOTE_EMBEDDER_MESSAGE = (
    "Notebooks could not index this source because the embedding service did not answer. "
    "Check NOTEBOOK_EMBED_BASE_URL, NOTEBOOK_EMBED_MODEL and the key on the server, then press Retry."
)


def max_source_chars() -> int:
    try:
        value = int(os.getenv("NOTEBOOK_MAX_SOURCE_CHARS", "") or DEFAULT_MAX_SOURCE_CHARS)
    except ValueError:
        value = DEFAULT_MAX_SOURCE_CHARS
    return max(10_000, value)


def page_of(offset: int, page_starts: Optional[List[int]]) -> Optional[int]:
    """1-based page (or slide) that holds character ``offset``, or None when pages are unknown."""
    if not page_starts:
        return None
    return max(1, bisect_right(page_starts, offset))


_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


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
        # Set by _embed_chunks: the model and native width (before padding) of this source's vectors.
        self.embedding_model: Optional[str] = None
        self.embedding_dim: Optional[int] = None

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

            extracted = await self._extract_document(source)
            text = extracted.text
            if not text or len(text.strip()) < 10:
                raise IngestionError("No text could be extracted from this source.")

            page_starts = extracted.page_starts
            meta: Dict[str, Any] = dict(extracted.meta)
            limit = max_source_chars()
            if len(text) > limit:
                meta["text_truncated_from"] = len(text)
                meta["ingest_notice"] = (
                    f"This source is very long, so only its first {limit:,} characters were indexed."
                )
                text = text[:limit]
                page_starts = [p for p in page_starts if p < limit] if page_starts else page_starts

            async with self.manager.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE notebook_sources SET content_text = $1 WHERE id = $2", text, source_id
                )

            chunks = self._chunk_text(text, source, page_starts)
            if not chunks:
                raise IngestionError("The text could not be split into passages.")
            logger.info(f"Created {len(chunks)} chunks for source {source_id}")

            chunk_data, skipped = await self._embed_chunks(chunks)
            chunk_count = await self._store_chunks(source_id, source.notebook_id, chunk_data)

            # Keys are always written so a Retry replaces what the previous run left behind.
            meta.update(
                chunk_count=chunk_count,
                text_length=len(text),
                skipped_chunks=skipped,
                page_starts=page_starts or None,
                embedding_model=self.embedding_model,
                embedding_dim=self.embedding_dim,
            )
            meta.setdefault("ingest_notice", None)
            from . import auto_insights

            schedule_insights = auto_insights.should_run(len(text))
            meta["insights_status"] = "pending" if schedule_insights else None
            await self.manager.update_source_status(source_id, SourceStatus.READY, metadata_update=meta)
            logger.info(f"Successfully ingested source {source_id} with {chunk_count} chunks ({skipped} skipped)")
            if schedule_insights:
                auto_insights.schedule_default_insights(self.manager, source_id, user_id)

        except IngestionError as e:
            logger.warning(f"Ingestion failed for source {source_id}: {e}")
            await self.manager.update_source_status(source_id, SourceStatus.ERROR, error_message=str(e))
        except Exception as e:
            logger.error(f"Ingestion failed for source {source_id}: {e}", exc_info=True)
            await self.manager.update_source_status(
                source_id, SourceStatus.ERROR, error_message=f"Something went wrong reading this source: {str(e)[:200]}"
            )

    async def _store_chunks(self, source_id: UUID, notebook_id: UUID, chunk_data: list) -> int:
        """create_chunks, passing the embedding model and native width once the manager takes them."""
        extra: Dict[str, Any] = {}
        try:
            params = inspect.signature(self.manager.create_chunks).parameters
        except (TypeError, ValueError):
            params = {}
        takes_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        if takes_any or "embedding_model" in params:
            extra["embedding_model"] = self.embedding_model
        if takes_any or "embedding_dim" in params:
            extra["embedding_dim"] = self.embedding_dim
        return await self.manager.create_chunks(source_id, notebook_id, chunk_data, **extra)

    def _uses_remote(self) -> bool:
        return embedding_provider.configured_provider_name() == "openai"

    def _active_model(self) -> Optional[str]:
        if self._uses_remote():
            try:
                return embedding_provider.remote_settings().model
            except embedding_provider.ProviderConfigError:
                return None
        return IngestionService._working_model

    def _can_batch(self) -> bool:
        """Batching needs the stock single-text embedder (an override, as in tests or a
        subclass, is honoured one text at a time) and, for Ollama, a model already chosen."""
        if "_get_embedding" in vars(self) or type(self)._get_embedding is not IngestionService._get_embedding:
            return False
        return self._uses_remote() or IngestionService._working_model is not None

    async def _embed_group(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Vectors for one group of texts. A group the server rejected outright is retried
        one text at a time, which also lets model selection start over."""
        if len(texts) == 1 or not self._can_batch():
            return [await self._get_embedding(t) for t in texts[:1]]
        if self._uses_remote():
            vectors = await self._embed_remote(texts)
        else:
            model = IngestionService._working_model
            vectors = await asyncio.to_thread(self._try_embedding_batch, OLLAMA_URL, model, texts)
        if any(v is not None for v in vectors):
            return vectors
        return [await self._get_embedding(t) for t in texts]

    async def _embed_chunks(self, chunks) -> Tuple[list, int]:
        """Embed every chunk. Never stores a placeholder vector.

        Raises IngestionError when nothing could be embedded or too much was lost,
        so the source shows as failed and Retry has something to do. All vectors of one
        source must come from one model and one width: a vector that differs from the
        first is dropped like a failed one.
        """
        chunk_data = []
        skipped = 0
        streak = 0
        self.embedding_model = None
        self.embedding_dim = None
        texts = [c for c, _meta in chunks]
        i = 0
        while i < len(texts):
            if streak >= MAX_CONSECUTIVE_EMBED_FAILURES:
                skipped += len(texts) - i
                break
            size = EMBED_BATCH_SIZE if self._can_batch() else 1
            group = texts[i : i + size]
            vectors = await self._embed_group(group)
            model = self._active_model()
            for offset, vector in enumerate(vectors):
                index = i + offset
                if vector and self.embedding_dim is None:
                    self.embedding_dim, self.embedding_model = len(vector), model
                if vector and (len(vector) != self.embedding_dim or (model and model != self.embedding_model)):
                    logger.warning("Dropped a vector from a different embedding model or width")
                    vector = None
                if vector:
                    streak = 0
                    chunk_data.append(
                        (chunks[index][0], self._normalize_embedding_dimension(vector, TARGET_DIM), chunks[index][1], index)
                    )
                else:
                    streak += 1
                    skipped += 1
            i += len(group)
        if not chunk_data:
            raise IngestionError(REMOTE_EMBEDDER_MESSAGE if self._uses_remote() else NO_EMBEDDER_MESSAGE)
        if skipped / len(chunks) > MAX_SKIPPED_SHARE:
            raise IngestionError(
                f"Only {len(chunk_data)} of {len(chunks)} passages could be indexed because the embedding model "
                "stopped answering. Check that it is running and press Retry."
            )
        if skipped:
            logger.warning(f"{skipped} of {len(chunks)} chunks could not be embedded and were left out")
        return chunk_data, skipped

    async def _extract_document(self, source) -> Extracted:
        """Extract text (and page offsets) from a source. Raises IngestionError with a user-facing reason."""
        logger.info(f"Extracting text for source type: {source.type}, path: {source.storage_path}")
        try:
            return await extract_document(source)
        except IngestionError:
            # Pasted text is stored in the DB as well as on disk; fall back to it
            # if the file was cleaned up.
            if getattr(source.type, "value", source.type) in ("text", "markdown") and not (
                source.storage_path and os.path.exists(source.storage_path)
            ):
                async with self.manager.db_pool.acquire() as conn:
                    stored = await conn.fetchval("SELECT content_text FROM notebook_sources WHERE id = $1", source.id)
                if stored:
                    return Extracted(stored)
            raise

    def _chunk_text(
        self, text: str, source, page_starts: Optional[List[int]] = None
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Split text into overlapping chunks.
        Returns list of (chunk_text, metadata) tuples. Metadata carries ``start_char`` and
        ``end_char`` (offsets into ``text`` as given, so into the stored content_text) and,
        when ``page_starts`` is known, the 1-based ``page`` the chunk starts on.
        """
        chunks: List[Tuple[str, Dict[str, Any]]] = []

        lead = len(text) - len(text.lstrip())
        body = text.strip()
        if not body:
            return chunks

        # Paragraph spans in body coordinates; ``i`` is the index in the raw split, as before.
        edges: List[Tuple[int, int]] = []
        position = 0
        for m in _PARAGRAPH_BREAK.finditer(body):
            edges.append((position, m.start()))
            position = m.end()
        edges.append((position, len(body)))
        spans: List[Tuple[int, int, int]] = []
        for i, (a, b) in enumerate(edges):
            piece = body[a:b]
            if piece.strip():
                spans.append((i, a + len(piece) - len(piece.lstrip()), b - (len(piece) - len(piece.rstrip()))))

        def length(pieces: List[Tuple[int, int]]) -> int:
            return sum(b - a for a, b in pieces) + 2 * (len(pieces) - 1) if pieces else 0

        def overlap(pieces: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
            """Pieces covering the last CHUNK_OVERLAP characters of the chunk string."""
            if length(pieces) <= CHUNK_OVERLAP:
                return list(pieces)
            remaining, out = CHUNK_OVERLAP, []
            for a, b in reversed(pieces):
                if remaining <= 0:
                    break
                if b - a >= remaining:
                    out.append((b - remaining, b))
                    break
                out.append((a, b))
                remaining -= (b - a) + 2
            out.reverse()
            return out

        def emit(pieces: List[Tuple[int, int]], paragraphs: List[int]) -> None:
            chunk = "\n\n".join(body[a:b] for a, b in pieces).strip()
            start, end = pieces[0][0] + lead, pieces[-1][1] + lead
            meta: Dict[str, Any] = {
                "source_title": source.title, "paragraphs": paragraphs, "start_char": start, "end_char": end,
            }
            page = page_of(start, page_starts)
            if page:
                meta["page"] = page
            chunks.append((chunk, meta))

        current: List[Tuple[int, int]] = []
        paragraphs: List[int] = []
        for i, a, b in spans:
            # If adding this paragraph exceeds chunk size, save current and start new
            if current and length(current) + (b - a) > CHUNK_SIZE:
                emit(current, paragraphs)
                current = overlap(current) + [(a, b)]
                paragraphs = [i]
            else:
                current.append((a, b))
                paragraphs.append(i)
        if current:
            emit(current, paragraphs)

        # If we have very few chunks, try to balance them
        if len(chunks) == 1 and len(chunks[0][0]) > CHUNK_SIZE * 2:
            # Re-chunk with sentence-level splitting
            chunks = self._chunk_by_sentences(body, source, lead, page_starts)

        return chunks

    def _chunk_by_sentences(
        self, text: str, source, base_offset: int = 0, page_starts: Optional[List[int]] = None
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Chunk text by sentences for more granular splitting.

        ``base_offset`` is where ``text`` begins inside the stored content_text.
        """
        spans: List[Tuple[int, int]] = []
        position = 0
        for m in _SENTENCE_BREAK.finditer(text):
            spans.append((position, m.start()))
            position = m.end()
        spans.append((position, len(text)))

        chunks: List[Tuple[str, Dict[str, Any]]] = []

        def emit(indices: List[int]) -> None:
            start = spans[indices[0]][0] + base_offset
            end = spans[indices[-1]][1] + base_offset
            meta: Dict[str, Any] = {
                "source_title": source.title, "sentence_indices": list(indices), "start_char": start, "end_char": end,
            }
            page = page_of(start, page_starts)
            if page:
                meta["page"] = page
            joined = " ".join(text[a:b] for a, b in (spans[k] for k in indices))
            chunks.append((joined.strip(), meta))

        def size(indices: List[int]) -> int:
            return sum(spans[k][1] - spans[k][0] for k in indices) + len(indices) - 1

        current: List[int] = []
        for i, (a, b) in enumerate(spans):
            if current and size(current) + (b - a) > CHUNK_SIZE:
                emit(current)
                # Carry the last two sentences into the next chunk, unless that alone is half a chunk.
                carried = current[-2:]
                while carried and size(carried) > CHUNK_SIZE // 2:
                    carried = carried[1:]
                current = carried + [i]
            else:
                current.append(i)
        if current:
            emit(current)
        return chunks

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding vector for text using Ollama with cached model selection.

        The HTTP calls are blocking ``requests`` calls, so they run in a worker
        thread; called directly they froze the whole event loop for up to a
        minute per chunk.
        """
        if self._uses_remote():
            return (await self._embed_remote([text]))[0]

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

    async def _embed_remote(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Vectors from the OpenAI-compatible provider the operator configured."""
        try:
            provider = embedding_provider.remote_provider()
        except embedding_provider.ProviderConfigError as exc:
            logger.error("Embedding provider is misconfigured: %s", exc)
            return [None] * len(texts)
        return (await asyncio.to_thread(provider.embed, texts)).vectors

    def _try_embedding_batch(self, base_url: str, model: str, texts: List[str]) -> List[Optional[List[float]]]:
        """Embed several texts with one Ollama request (``/api/embed``); older servers get one request each."""
        return embedding_provider.OllamaProvider(base_url, model).embed(texts).vectors

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
