"""
Document Chunker for RAG Corpus

Splits documents into chunks suitable for embedding and retrieval.
Preserves metadata and structure.
"""

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RawDocument:
    """Raw document from a fetcher."""
    id: str
    url: str
    title: str
    content: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Chunk:
    """A chunk of text ready for embedding."""
    id: str
    text: str
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "text": self.text,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chunk":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            text=data["text"],
            metadata=data["metadata"],
        )


class DocumentChunker:
    """
    Splits documents into chunks for embedding.
    
    Uses a simple sentence/paragraph-aware splitting strategy with overlap.
    """
    
    def __init__(
        self,
        chunk_size: int = 1000,
        overlap: int = 200,
        rag_dir: Optional[str] = None
    ):
        """
        Initialize the chunker.
        
        Args:
            chunk_size: Target size of each chunk in characters
            overlap: Overlap between chunks for context
            rag_dir: Directory to persist chunks
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.rag_dir = Path(rag_dir) if rag_dir else None
        
        # Ensure RAG directory exists
        if self.rag_dir:
            self.rag_dir.mkdir(parents=True, exist_ok=True)
    
    def chunk_document(self, doc: RawDocument) -> List[Chunk]:
        """
        Split a document into chunks.
        
        Args:
            doc: Raw document to chunk
            
        Returns:
            List of chunks with metadata
        """
        chunks = []
        
        # Split content into paragraphs
        paragraphs = self._split_paragraphs(doc.content)
        
        current_chunk = []
        current_size = 0
        chunk_index = 0
        
        for para in paragraphs:
            para_size = len(para)
            
            # If adding this paragraph exceeds chunk size, finalize current chunk
            if current_size + para_size > self.chunk_size and current_chunk:
                chunk_text = "\n\n".join(current_chunk)
                chunks.append(self._create_chunk(doc, chunk_text, chunk_index))
                chunk_index += 1
                
                # Keep overlap from end of previous chunk
                overlap_text = chunk_text[-self.overlap:] if len(chunk_text) > self.overlap else ""
                current_chunk = [overlap_text] if overlap_text else []
                current_size = len(overlap_text)
            
            current_chunk.append(para)
            current_size += para_size + 2  # +2 for \n\n
        
        # Don't forget the last chunk
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunks.append(self._create_chunk(doc, chunk_text, chunk_index))
        
        logger.debug(f"Split document {doc.id} into {len(chunks)} chunks")
        return chunks
    
    def _split_paragraphs(self, text: str) -> List[str]:
        """Split text into paragraphs."""
        # Normalize line endings
        text = text.replace("\r\n", "\n")
        
        # Split on double newlines or markdown headers
        parts = re.split(r"\n\n+|(?=^#{1,6}\s)", text, flags=re.MULTILINE)
        
        # Clean and filter
        paragraphs = []
        for part in parts:
            part = part.strip()
            if part:
                paragraphs.append(part)
        
        return paragraphs
    
    def _create_chunk(
        self,
        doc: RawDocument,
        text: str,
        index: int,
        max_chunk_size: int = 6000  # Safe limit for most embedding models
    ) -> Chunk:
        """Create a chunk with metadata."""
        # Hard cap on chunk size to prevent context length errors
        if len(text) > max_chunk_size:
            logger.warning(f"Chunk {index} for doc {doc.id} exceeds max size ({len(text)} > {max_chunk_size}), truncating")
            text = text[:max_chunk_size]
            # Try to end at a sentence boundary
            last_period = text.rfind('. ')
            if last_period > max_chunk_size * 0.8:
                text = text[:last_period + 1]

        # Generate unique chunk ID
        chunk_id = hashlib.sha256(
            f"{doc.id}:{index}:{text[:100]}".encode()
        ).hexdigest()[:16]
        
        # Build metadata
        metadata = {
            "source": doc.source,
            "url": doc.url,
            "title": doc.title,
            "chunk_index": index,
            "doc_id": doc.id,
            "fetched_at": doc.fetched_at.isoformat() if doc.fetched_at else None,
            **doc.metadata  # Include document-specific metadata
        }
        
        return Chunk(
            id=chunk_id,
            text=text,
            metadata=metadata,
        )
    
    def persist_chunks(self, chunks: List[Chunk]) -> None:
        """
        Persist chunks to the RAG directory.
        
        Organizes by source:
        rag_dir/
          nextjs_docs/
            <chunk_id>.json
          stack_overflow/
            <chunk_id>.json
          ...
        """
        if not self.rag_dir:
            logger.warning("No RAG directory configured, skipping persistence")
            return
        
        for chunk in chunks:
            source = chunk.metadata.get("source", "unknown")
            source_dir = self.rag_dir / source
            source_dir.mkdir(exist_ok=True)
            
            chunk_file = source_dir / f"{chunk.id}.json"
            
            with open(chunk_file, "w", encoding="utf-8") as f:
                json.dump(chunk.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.info(f"Persisted {len(chunks)} chunks to {self.rag_dir}")
    
    def load_chunks(self, source: Optional[str] = None) -> List[Chunk]:
        """
        Load chunks from the RAG directory.
        
        Args:
            source: Optional source to filter by
            
        Returns:
            List of chunks
        """
        if not self.rag_dir or not self.rag_dir.exists():
            return []
        
        chunks = []
        
        if source:
            source_dir = self.rag_dir / source
            if source_dir.exists():
                chunks.extend(self._load_from_dir(source_dir))
        else:
            # Load from all subdirectories
            for source_dir in self.rag_dir.iterdir():
                if source_dir.is_dir():
                    chunks.extend(self._load_from_dir(source_dir))
        
        return chunks
    
    def _load_from_dir(self, directory: Path) -> List[Chunk]:
        """Load chunks from a directory."""
        chunks = []
        
        for chunk_file in directory.glob("*.json"):
            try:
                with open(chunk_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    chunks.append(Chunk.from_dict(data))
            except Exception as e:
                logger.warning(f"Error loading {chunk_file}: {e}")
        
        return chunks
    
    def clear_source(self, source: str) -> int:
        """
        Clear all chunks for a source.
        
        Args:
            source: Source to clear
            
        Returns:
            Number of files deleted
        """
        if not self.rag_dir:
            return 0
        
        source_dir = self.rag_dir / source
        if not source_dir.exists():
            return 0
        
        count = 0
        for chunk_file in source_dir.glob("*.json"):
            chunk_file.unlink()
            count += 1
        
        logger.info(f"Cleared {count} chunks from {source}")
        return count
    
    def get_source_stats(self) -> Dict[str, int]:
        """
        Get chunk counts per source.
        
        Returns:
            Dictionary mapping source to chunk count
        """
        stats = {}
        
        if not self.rag_dir or not self.rag_dir.exists():
            return stats
        
        for source_dir in self.rag_dir.iterdir():
            if source_dir.is_dir():
                count = len(list(source_dir.glob("*.json")))
                stats[source_dir.name] = count
        
        return stats


class MarkdownChunker(DocumentChunker):
    """
    Specialized chunker for Markdown documents.
    
    Preserves heading hierarchy and splits at section boundaries.
    """
    
    def _split_paragraphs(self, text: str) -> List[str]:
        """Split markdown at section boundaries."""
        sections = []
        current_section = []
        current_heading = ""
        
        lines = text.split("\n")
        
        for line in lines:
            # Check if this is a heading
            if re.match(r"^#{1,6}\s", line):
                # Save previous section
                if current_section:
                    section_text = "\n".join(current_section)
                    if current_heading:
                        section_text = f"{current_heading}\n{section_text}"
                    sections.append(section_text.strip())
                
                current_heading = line
                current_section = []
            else:
                current_section.append(line)
        
        # Don't forget last section
        if current_section:
            section_text = "\n".join(current_section)
            if current_heading:
                section_text = f"{current_heading}\n{section_text}"
            sections.append(section_text.strip())
        
        # Filter empty sections
        return [s for s in sections if s.strip()]


class CodeAwareChunker(DocumentChunker):
    """
    Chunker that's aware of code blocks.
    
    Tries to keep code blocks intact within chunks.
    """
    
    def chunk_document(self, doc: RawDocument) -> List[Chunk]:
        """Split document while respecting code blocks."""
        chunks = []
        
        # Find all code blocks
        code_block_pattern = r"```[\s\S]*?```"
        
        # Split around code blocks
        parts = re.split(f"({code_block_pattern})", doc.content)
        
        current_chunk = []
        current_size = 0
        chunk_index = 0
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            is_code_block = part.startswith("```")
            part_size = len(part)
            
            # If it's a code block, try to keep it together
            if is_code_block:
                if part_size > self.chunk_size:
                    # Code block too large, chunk it
                    if current_chunk:
                        chunk_text = "\n\n".join(current_chunk)
                        chunks.append(self._create_chunk(doc, chunk_text, chunk_index))
                        chunk_index += 1
                        current_chunk = []
                        current_size = 0
                    
                    # Split large code block
                    code_chunks = self._split_code_block(part)
                    for cc in code_chunks:
                        chunks.append(self._create_chunk(doc, cc, chunk_index))
                        chunk_index += 1
                else:
                    # Code block fits, check if it fits in current chunk
                    if current_size + part_size > self.chunk_size and current_chunk:
                        chunk_text = "\n\n".join(current_chunk)
                        chunks.append(self._create_chunk(doc, chunk_text, chunk_index))
                        chunk_index += 1
                        current_chunk = []
                        current_size = 0
                    
                    current_chunk.append(part)
                    current_size += part_size
            else:
                # Regular text, use parent logic
                for para in self._split_paragraphs(part):
                    para_size = len(para)
                    
                    if current_size + para_size > self.chunk_size and current_chunk:
                        chunk_text = "\n\n".join(current_chunk)
                        chunks.append(self._create_chunk(doc, chunk_text, chunk_index))
                        chunk_index += 1
                        
                        overlap_text = chunk_text[-self.overlap:] if len(chunk_text) > self.overlap else ""
                        current_chunk = [overlap_text] if overlap_text else []
                        current_size = len(overlap_text)
                    
                    current_chunk.append(para)
                    current_size += para_size
        
        # Last chunk
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunks.append(self._create_chunk(doc, chunk_text, chunk_index))
        
        return chunks
    
    def _split_code_block(self, code_block: str) -> List[str]:
        """Split a large code block into smaller chunks."""
        lines = code_block.split("\n")
        chunks = []
        current = []
        current_size = 0
        
        # Preserve the language specifier
        first_line = lines[0] if lines else "```"
        last_line = "```"
        
        for line in lines[1:-1]:  # Skip first and last ```
            line_size = len(line) + 1
            
            if current_size + line_size > self.chunk_size - 10 and current:
                # Create chunk with proper fencing
                chunk_text = f"{first_line}\n" + "\n".join(current) + f"\n{last_line}"
                chunks.append(chunk_text)
                current = []
                current_size = 0
            
            current.append(line)
            current_size += line_size
        
        if current:
            chunk_text = f"{first_line}\n" + "\n".join(current) + f"\n{last_line}"
            chunks.append(chunk_text)
        
        return chunks
