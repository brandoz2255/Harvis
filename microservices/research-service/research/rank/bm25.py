"""
BM25 lexical ranking implementation for document chunks.

Provides fast lexical relevance scoring using the BM25 algorithm,
optimized for research document chunks.
"""

import math
import re
from collections import Counter, defaultdict
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass

# Import from your core module
from ..core.types import DocChunk


@dataclass
class RankedChunk:
    """A document chunk with its BM25 relevance score"""
    chunk: DocChunk
    score: float
    term_matches: Dict[str, int]  # Which query terms matched and how often


class BM25Ranker:
    """
    BM25 ranking implementation optimized for research document chunks.
    
    Uses standard BM25 parameters:
    - k1: Controls term frequency saturation (default: 1.5)
    - b: Controls length normalization (default: 0.75)
    """
    
    def __init__(self, k1: float = 1.5, b: float = 0.75, min_score: float = 0.01):
        self.k1 = k1
        self.b = b
        self.min_score = min_score
        
        # Index state
        self._doc_frequencies: Dict[str, int] = defaultdict(int)
        self._doc_lengths: Dict[str, int] = {}
        self._avg_doc_length: float = 0.0
        self._total_docs: int = 0
        self._indexed_chunks: Dict[str, DocChunk] = {}
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization - splits on whitespace and punctuation"""
        # Convert to lowercase and split on word boundaries
        tokens = re.findall(r'\b\w+\b', text.lower())
        return tokens
    
    def _compute_term_frequencies(self, tokens: List[str]) -> Dict[str, int]:
        """Count term frequencies in token list"""
        return Counter(tokens)
    
    def index_chunks(self, chunks: List[DocChunk]) -> None:
        """
        Build BM25 index from document chunks.
        
        Args:
            chunks: List of document chunks to index
        """
        self._indexed_chunks = {}
        self._doc_frequencies = defaultdict(int)
        self._doc_lengths = {}
        total_length = 0
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"chunk_{i}_{hash(chunk.url + str(chunk.start))}"
            tokens = self._tokenize(chunk.text)  # Use 'text' field from your DocChunk
            doc_length = len(tokens)
            
            # Store chunk and length
            self._indexed_chunks[chunk_id] = chunk
            self._doc_lengths[chunk_id] = doc_length
            total_length += doc_length
            
            # Count document frequencies (how many docs contain each term)
            unique_terms = set(tokens)
            for term in unique_terms:
                self._doc_frequencies[term] += 1
        
        self._total_docs = len(chunks)
        self._avg_doc_length = total_length / max(1, self._total_docs)
    
    def _compute_idf(self, term: str) -> float:
        """Compute inverse document frequency for a term"""
        df = self._doc_frequencies.get(term, 0)
        if df == 0:
            return 0.0
        
        # Standard BM25 IDF formula
        return math.log((self._total_docs - df + 0.5) / (df + 0.5))
    
    def _compute_chunk_score(self, chunk_id: str, query_terms: Dict[str, int]) -> Tuple[float, Dict[str, int]]:
        """
        Compute BM25 score for a single chunk against query terms.
        
        Returns:
            Tuple of (score, term_matches)
        """
        chunk = self._indexed_chunks[chunk_id]
        chunk_tokens = self._tokenize(chunk.text)  # Use 'text' field from your DocChunk
        chunk_term_frequencies = self._compute_term_frequencies(chunk_tokens)
        doc_length = self._doc_lengths[chunk_id]
        
        score = 0.0
        term_matches = {}
        
        for term, query_tf in query_terms.items():
            chunk_tf = chunk_term_frequencies.get(term, 0)
            if chunk_tf == 0:
                continue
                
            # Store term match count
            term_matches[term] = chunk_tf
            
            # BM25 formula components
            idf = self._compute_idf(term)
            
            # Term frequency component with saturation
            tf_component = (chunk_tf * (self.k1 + 1)) / (
                chunk_tf + self.k1 * (
                    1 - self.b + self.b * (doc_length / self._avg_doc_length)
                )
            )
            
            # Add to total score
            score += idf * tf_component
        
        return score, term_matches
    
    def rank_chunks(self, query: str, chunks: Optional[List[DocChunk]] = None, top_k: Optional[int] = None) -> List[RankedChunk]:
        """
        Rank document chunks by BM25 relevance to query.
        
        Args:
            query: Search query string
            chunks: Optional list of chunks to rank (uses indexed chunks if None)
            top_k: Maximum number of results to return
            
        Returns:
            List of RankedChunk objects sorted by relevance (highest first)
        """
        if chunks is not None:
            # Re-index if new chunks provided
            self.index_chunks(chunks)
        
        if not self._indexed_chunks:
            return []
        
        # Tokenize and count query terms
        query_tokens = self._tokenize(query)
        query_term_frequencies = self._compute_term_frequencies(query_tokens)
        
        # Score all chunks
        ranked_chunks = []
        for chunk_id in self._indexed_chunks:
            score, term_matches = self._compute_chunk_score(chunk_id, query_term_frequencies)
            
            # Filter out very low scores
            if score >= self.min_score:
                ranked_chunks.append(RankedChunk(
                    chunk=self._indexed_chunks[chunk_id],
                    score=score,
                    term_matches=term_matches
                ))
        
        # Sort by score (descending)
        ranked_chunks.sort(key=lambda x: x.score, reverse=True)
        
        # Apply top_k limit
        if top_k is not None:
            ranked_chunks = ranked_chunks[:top_k]
        
        return ranked_chunks
    
    def get_statistics(self) -> Dict:
        """Get indexing statistics for debugging"""
        return {
            "total_docs": self._total_docs,
            "avg_doc_length": self._avg_doc_length,
            "vocab_size": len(self._doc_frequencies),
            "indexed_chunks": len(self._indexed_chunks)
        }


def quick_bm25_rank(query: str, chunks: List[DocChunk], top_k: int = 10) -> List[RankedChunk]:
    """
    Convenience function for quick BM25 ranking.
    
    Args:
        query: Search query
        chunks: Document chunks to rank
        top_k: Maximum results to return
        
    Returns:
        List of top-ranked chunks
    """
    ranker = BM25Ranker()
    return ranker.rank_chunks(query=query, chunks=chunks, top_k=top_k)