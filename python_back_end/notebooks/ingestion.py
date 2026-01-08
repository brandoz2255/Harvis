"""
Ingestion Service for NotebookLM
Handles text extraction, chunking, and embedding generation
"""

import logging
import os
import io
import asyncio
import json
import re
from typing import List, Tuple, Dict, Any, Optional
from uuid import UUID
import aiohttp
import requests

from .models import SourceType, SourceStatus
from .manager import NotebookManager

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
CHUNK_SIZE = 1000  # Target chunk size in characters
CHUNK_OVERLAP = 200  # Overlap between chunks


class IngestionService:
    """
    Service for ingesting sources into the notebook.
    Handles:
    - Text extraction from PDFs, URLs, plain text
    - Text chunking with overlap
    - Embedding generation via Ollama
    - Storing chunks in the database
    """

    def __init__(self, manager: NotebookManager):
        self.manager = manager

    async def ingest_source(self, source_id: UUID, user_id: int) -> None:
        """
        Main ingestion pipeline for a source.
        Runs asynchronously to not block the API.
        """
        try:
            # Get source details
            source = await self.manager.get_source(source_id, user_id)

            # Update status to processing
            await self.manager.update_source_status(source_id, SourceStatus.PROCESSING)

            logger.info(f"Starting ingestion for source {source_id} (type: {source.type})")

            # Extract text based on source type
            text = await self._extract_text(source)

            if not text or len(text.strip()) < 10:
                await self.manager.update_source_status(
                    source_id,
                    SourceStatus.ERROR,
                    error_message="No text could be extracted from the source"
                )
                return

            # Update source with extracted text
            async with self.manager.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE notebook_sources SET content_text = $1 WHERE id = $2
                """, text, source_id)

            # Chunk the text
            chunks = self._chunk_text(text, source)

            if not chunks:
                await self.manager.update_source_status(
                    source_id,
                    SourceStatus.ERROR,
                    error_message="Failed to create chunks from the text"
                )
                return

            logger.info(f"Created {len(chunks)} chunks for source {source_id}")

            # Generate embeddings and store chunks
            chunk_data = []
            embedding_failures = 0
            target_dim = 4096  # Target dimension for our database (supports codellama)
            
            for i, (chunk_text, metadata) in enumerate(chunks):
                embedding = await self._get_embedding(chunk_text)
                if embedding:
                    # Normalize embedding to target dimension
                    embedding = self._normalize_embedding_dimension(embedding, target_dim)
                    chunk_data.append((chunk_text, embedding, metadata, i))
                else:
                    embedding_failures += 1
                    # Still create chunk with zero embedding so the content is searchable
                    logger.warning(f"Failed to get embedding for chunk {i}, using zero vector")
                    zero_embedding = [0.0] * target_dim
                    chunk_data.append((chunk_text, zero_embedding, metadata, i))

            if not chunk_data:
                await self.manager.update_source_status(
                    source_id,
                    SourceStatus.ERROR,
                    error_message="Failed to create any chunks"
                )
                return
            
            if embedding_failures > 0:
                logger.warning(f"Created {len(chunk_data)} chunks but {embedding_failures} had embedding failures")

            # Store chunks in database
            chunk_count = await self.manager.create_chunks(
                source_id,
                source.notebook_id,
                chunk_data
            )

            # Update status to ready
            await self.manager.update_source_status(
                source_id,
                SourceStatus.READY,
                metadata_update={"chunk_count": chunk_count, "text_length": len(text)}
            )

            logger.info(f"Successfully ingested source {source_id} with {chunk_count} chunks")

        except Exception as e:
            logger.error(f"Ingestion failed for source {source_id}: {e}")
            await self.manager.update_source_status(
                source_id,
                SourceStatus.ERROR,
                error_message=str(e)
            )

    async def _extract_text(self, source) -> str:
        """Extract text from source based on its type"""
        logger.info(f"Extracting text for source type: {source.type}, path: {source.storage_path}")

        if source.type == SourceType.PDF:
            text = await self._extract_pdf(source.storage_path)
            logger.info(f"PDF extraction result: {len(text)} chars")
            return text

        elif source.type == SourceType.URL:
            text = await self._extract_url(source.storage_path)
            logger.info(f"URL extraction result: {len(text)} chars")
            return text

        elif source.type in [SourceType.TEXT, SourceType.MARKDOWN]:
            # Text is already stored in storage_path or we need to read the file
            if source.storage_path and os.path.exists(source.storage_path):
                with open(source.storage_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                    logger.info(f"Text file read: {len(text)} chars")
                    return text
            # Check if content_text was already set
            async with self.manager.db_pool.acquire() as conn:
                text = await conn.fetchval(
                    "SELECT content_text FROM notebook_sources WHERE id = $1",
                    source.id
                )
                logger.info(f"Text from DB: {len(text) if text else 0} chars")
                return text or ""

        elif source.type == SourceType.DOC:
            text = await self._extract_doc(source.storage_path)
            logger.info(f"DOC extraction result: {len(text)} chars")
            return text

        elif source.type == SourceType.TRANSCRIPT:
            # Transcripts are usually plain text
            if source.storage_path and os.path.exists(source.storage_path):
                with open(source.storage_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                    logger.info(f"Transcript read: {len(text)} chars")
                    return text
            return ""

        elif source.type == SourceType.YOUTUBE:
            text = await self._extract_youtube(source.storage_path)
            logger.info(f"YouTube extraction result: {len(text)} chars")
            return text

        else:
            logger.warning(f"Unsupported source type: {source.type}")
            return ""

    async def _extract_pdf(self, file_path: str) -> str:
        """Extract text from a PDF file"""
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.error("pypdf not installed")
            return ""

        try:
            reader = PdfReader(file_path)
            texts = []
            for page in reader.pages:
                try:
                    text = page.extract_text() or ""
                    texts.append(text)
                except Exception as e:
                    logger.warning(f"Failed to extract text from PDF page: {e}")
                    continue

            return "\n\n".join(texts)
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return ""

    async def _extract_url(self, url: str) -> str:
        """Extract text from a URL using trafilatura"""
        logger.info(f"Extracting URL content from: {url}")
        
        try:
            import trafilatura
        except ImportError:
            logger.warning("trafilatura not installed, falling back to basic extraction")
            return await self._extract_url_basic(url)

        try:
            # Fetch the page with better settings
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                logger.warning(f"trafilatura.fetch_url returned None for {url}")
                return await self._extract_url_basic(url)

            # Extract main content with settings for better extraction
            text = trafilatura.extract(
                downloaded,
                include_tables=True,
                include_comments=False,
                include_formatting=False,
                no_fallback=False
            )
            
            if text and len(text.strip()) > 50:
                logger.info(f"trafilatura extracted {len(text)} chars from {url}")
                return text
            else:
                logger.warning(f"trafilatura extracted too little content ({len(text) if text else 0} chars), trying fallback")
                return await self._extract_url_basic(url)
                
        except Exception as e:
            logger.error(f"URL extraction failed for {url}: {e}")
            return await self._extract_url_basic(url)

    async def _extract_url_basic(self, url: str) -> str:
        """Basic URL text extraction without trafilatura"""
        logger.info(f"Using basic URL extraction for: {url}")
        
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error("beautifulsoup4 not installed")
            return ""

        try:
            # Try with aiohttp first
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30), headers=headers) as response:
                    if response.status != 200:
                        logger.warning(f"URL returned status {response.status}")
                        return ""
                    html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')

            # Remove script, style, nav, footer elements
            for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                element.decompose()

            # Try to find main content areas first
            main_content = soup.find('main') or soup.find('article') or soup.find('div', {'class': re.compile(r'content|main|article|post|entry', re.I)})
            
            if main_content:
                text = main_content.get_text(separator='\n')
            else:
                # Fall back to body
                body = soup.find('body')
                text = body.get_text(separator='\n') if body else soup.get_text(separator='\n')

            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk and len(chunk) > 1)

            logger.info(f"Basic extraction got {len(text)} chars from {url}")
            return text
            
        except asyncio.TimeoutError:
            logger.error(f"URL extraction timed out for {url}")
            return ""
        except Exception as e:
            logger.error(f"Basic URL extraction failed for {url}: {e}")
            return ""

    async def _extract_doc(self, file_path: str) -> str:
        """Extract text from a DOC/DOCX file"""
        try:
            from docx import Document
        except ImportError:
            logger.error("python-docx not installed")
            return ""

        try:
            doc = Document(file_path)
            paragraphs = [para.text for para in doc.paragraphs]
            return "\n\n".join(paragraphs)
        except Exception as e:
            logger.error(f"DOC extraction failed: {e}")
            return ""

    async def _extract_youtube(self, url: str) -> str:
        """Extract transcript from a YouTube video"""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            logger.error("youtube_transcript_api not installed")
            return ""

        try:
            # Extract video ID from URL
            video_id = self._extract_youtube_video_id(url)
            if not video_id:
                logger.error(f"Could not extract video ID from URL: {url}")
                return ""

            # Get transcript
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            
            # Combine all transcript entries
            text_parts = []
            for entry in transcript_list:
                text = entry.get('text', '').strip()
                if text:
                    text_parts.append(text)
            
            full_text = ' '.join(text_parts)
            logger.info(f"Extracted YouTube transcript with {len(text_parts)} segments, {len(full_text)} chars")
            return full_text

        except Exception as e:
            logger.error(f"YouTube transcript extraction failed for {url}: {e}")
            return ""

    def _extract_youtube_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats"""
        import re
        
        patterns = [
            r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
            r'(?:embed/)([a-zA-Z0-9_-]{11})',
            r'(?:watch\?v=)([a-zA-Z0-9_-]{11})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # If URL is just the video ID
        if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
            return url
        
        return None

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
        """Get embedding vector for text using Ollama with multiple model fallbacks"""
        cloud_ollama_url = os.getenv("OLLAMA_CLOUD_URL", "https://coyotegpt.ngrok.app/ollama")
        
        # List of embedding models to try (in order of preference)
        # Ollama can generate embeddings from any model, not just embedding-specific ones
        embedding_models = [
            EMBEDDING_MODEL,  # nomic-embed-text (preferred)
            "mxbai-embed-large",
            "all-minilm",
            "codellama:7b",  # Available on local
            "deepseek-coder:6.7b",  # Available on local
            "gpt-oss:latest",  # Available on local
            "llama3.2",
            "mistral",
        ]
        
        # Try local Ollama first with multiple models
        for model in embedding_models:
            try:
                response = requests.post(
                    f"{OLLAMA_URL}/api/embeddings",
                    json={
                        "model": model,
                        "prompt": text[:8000]  # Limit text length
                    },
                    timeout=60
                )

                if response.status_code == 200:
                    data = response.json()
                    embedding = data.get("embedding")
                    if embedding:
                        logger.info(f"Got embedding using local Ollama model: {model}")
                        return embedding
                elif response.status_code == 404:
                    logger.debug(f"Local model {model} not found, trying next...")
                    continue
                else:
                    logger.warning(f"Local Ollama embedding failed with {model}: {response.status_code}")
                    
            except requests.exceptions.ConnectionError:
                logger.warning(f"Local Ollama not accessible, will try cloud...")
                break
            except Exception as e:
                logger.warning(f"Local Ollama error with {model}: {e}")
                continue

        # Try cloud Ollama as fallback with multiple models
        for model in embedding_models:
            try:
                response = requests.post(
                    f"{cloud_ollama_url}/api/embeddings",
                    json={
                        "model": model,
                        "prompt": text[:8000]
                    },
                    timeout=60
                )

                if response.status_code == 200:
                    data = response.json()
                    embedding = data.get("embedding")
                    if embedding:
                        logger.info(f"Got embedding using cloud Ollama model: {model}")
                        return embedding
                elif response.status_code == 404:
                    logger.debug(f"Cloud model {model} not found, trying next...")
                    continue
                else:
                    logger.warning(f"Cloud Ollama embedding failed with {model}: {response.status_code}")

            except Exception as e:
                logger.warning(f"Cloud Ollama error with {model}: {e}")
                continue

        logger.error("All embedding providers and models failed")
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
            return self._normalize_embedding_dimension(embedding, 4096)
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
