"""
Reranking module for improving relevance scoring beyond lexical matching.

Provides cross-encoder and embedding-based reranking options to refine
initial BM25 results with semantic understanding.
"""

import asyncio
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from abc import ABC, abstractmethod
import logging

# Import from your core module
from .bm25 import RankedChunk
from ..core.types import DocChunk

logger = logging.getLogger(__name__)


@dataclass 
class RerankedChunk:
    """A document chunk with both lexical and semantic relevance scores"""
    chunk: DocChunk
    lexical_score: float  # Original BM25 score
    semantic_score: float # Reranker score  
    combined_score: float # Final weighted combination
    term_matches: Dict[str, int] # Original term matches
    metadata: Dict[str, Any] = None # Additional reranking metadata


class BaseReranker(ABC):
    """Abstract base class for reranking implementations"""
    
    @abstractmethod
    async def rerank(self, query: str, ranked_chunks: List[RankedChunk], top_k: Optional[int] = None) -> List[RerankedChunk]:
        """
        Rerank chunks using semantic similarity.
        
        Args:
            query: Original search query
            ranked_chunks: Initial BM25-ranked chunks
            top_k: Maximum results to return
            
        Returns:
            Reranked chunks with combined scores
        """
        pass


class CrossEncoderReranker(BaseReranker):
    """
    Cross-encoder reranker using sentence transformers or similar models.
    
    This is a placeholder implementation - would integrate with actual
    cross-encoder models like ms-marco-MiniLM-L-12-v2.
    """
    
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2", lexical_weight: float = 0.3):
        self.model_name = model_name
        self.lexical_weight = lexical_weight
        self.semantic_weight = 1.0 - lexical_weight
        self._model = None
    
    async def _load_model(self):
        """Load cross-encoder model (placeholder)"""
        if self._model is None:
            # Placeholder - would load actual sentence-transformers model
            logger.info(f"Loading cross-encoder model: {self.model_name}")
            # self._model = CrossEncoder(self.model_name)
            self._model = "placeholder_model"
    
    async def _score_query_chunk_pair(self, query: str, chunk_text: str) -> float:
        """Score a query-chunk pair using cross-encoder (placeholder)"""
        await self._load_model()
        
        # Placeholder scoring - would use actual model
        # return self._model.predict([(query, chunk_text)])[0]
        
        # Simple heuristic for demo: higher score for more query terms present
        query_terms = set(query.lower().split())
        chunk_terms = set(chunk_text.lower().split())
        overlap = len(query_terms.intersection(chunk_terms))
        return min(1.0, overlap / max(1, len(query_terms)))
    
    async def rerank(self, query: str, ranked_chunks: List[RankedChunk], top_k: Optional[int] = None) -> List[RerankedChunk]:
        """Rerank using cross-encoder semantic scoring"""
        if not ranked_chunks:
            return []
        
        reranked = []
        
        # Score each chunk semantically
        for ranked_chunk in ranked_chunks:
            semantic_score = await self._score_query_chunk_pair(query, ranked_chunk.chunk.text)
            
            # Combine lexical and semantic scores
            combined_score = (
                self.lexical_weight * ranked_chunk.score + 
                self.semantic_weight * semantic_score
            )
            
            reranked.append(RerankedChunk(
                chunk=ranked_chunk.chunk,
                lexical_score=ranked_chunk.score,
                semantic_score=semantic_score,
                combined_score=combined_score,
                term_matches=ranked_chunk.term_matches,
                metadata={"model": self.model_name}
            ))
        
        # Sort by combined score
        reranked.sort(key=lambda x: x.combined_score, reverse=True)
        
        if top_k is not None:
            reranked = reranked[:top_k]
        
        return reranked


class EmbeddingReranker(BaseReranker):
    """
    Embedding-based reranker using cosine similarity.
    
    Uses sentence embeddings to compute semantic similarity between
    query and document chunks.
    """
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", lexical_weight: float = 0.4):
        self.model_name = model_name
        self.lexical_weight = lexical_weight
        self.semantic_weight = 1.0 - lexical_weight
        self._model = None
    
    async def _load_model(self):
        """Load sentence embedding model (placeholder)"""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            # Would load actual SentenceTransformer model
            # self._model = SentenceTransformer(self.model_name)
            self._model = "placeholder_embedding_model"
    
    async def _compute_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Compute embeddings for text list (placeholder)"""
        await self._load_model()
        
        # Placeholder - would use actual model
        # return self._model.encode(texts).tolist()
        
        # Return dummy embeddings for demo
        return [[0.1] * 384 for _ in texts]
    
    async def _cosine_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """Compute cosine similarity between embeddings"""
        # Simple dot product for demo (assumes normalized embeddings)
        if len(embedding1) != len(embedding2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        return max(0.0, min(1.0, dot_product))  # Clamp to [0,1]
    
    async def rerank(self, query: str, ranked_chunks: List[RankedChunk], top_k: Optional[int] = None) -> List[RerankedChunk]:
        """Rerank using embedding similarity"""
        if not ranked_chunks:
            return []
        
        # Prepare texts for embedding
        texts = [query] + [chunk.chunk.text for chunk in ranked_chunks]
        embeddings = await self._compute_embeddings(texts)
        
        query_embedding = embeddings[0]
        chunk_embeddings = embeddings[1:]
        
        reranked = []
        
        # Score each chunk
        for i, ranked_chunk in enumerate(ranked_chunks):
            chunk_embedding = chunk_embeddings[i]
            semantic_score = await self._cosine_similarity(query_embedding, chunk_embedding)
            
            # Combine scores
            combined_score = (
                self.lexical_weight * ranked_chunk.score +
                self.semantic_weight * semantic_score
            )
            
            reranked.append(RerankedChunk(
                chunk=ranked_chunk.chunk,
                lexical_score=ranked_chunk.score,
                semantic_score=semantic_score,
                combined_score=combined_score,
                term_matches=ranked_chunk.term_matches,
                metadata={"model": self.model_name, "embedding_dim": len(chunk_embedding)}
            ))
        
        # Sort by combined score
        reranked.sort(key=lambda x: x.combined_score, reverse=True)
        
        if top_k is not None:
            reranked = reranked[:top_k]
        
        return reranked


class ReRanker:
    """
    Main reranking orchestrator that can use different reranking strategies.
    """
    
    def __init__(self, strategy: str = "cross_encoder", **kwargs):
        """
        Initialize reranker with specified strategy.
        
        Args:
            strategy: "cross_encoder", "embedding", or "none"
            **kwargs: Parameters for the specific reranker
        """
        self.strategy = strategy
        
        if strategy == "cross_encoder":
            self.reranker = CrossEncoderReranker(**kwargs)
        elif strategy == "embedding":
            self.reranker = EmbeddingReranker(**kwargs)
        elif strategy == "none":
            self.reranker = None
        else:
            raise ValueError(f"Unknown reranking strategy: {strategy}")
    
    async def rerank(self, query: str, ranked_chunks: List[RankedChunk], top_k: Optional[int] = None) -> List[RerankedChunk]:
        """
        Rerank chunks using configured strategy.
        
        If no reranker configured, converts RankedChunk to RerankedChunk format
        with lexical scores only.
        """
        if self.reranker is None or self.strategy == "none":
            # No reranking - just convert format
            reranked = []
            for ranked_chunk in ranked_chunks:
                reranked.append(RerankedChunk(
                    chunk=ranked_chunk.chunk,
                    lexical_score=ranked_chunk.score,
                    semantic_score=0.0,
                    combined_score=ranked_chunk.score,
                    term_matches=ranked_chunk.term_matches,
                    metadata={"strategy": "lexical_only"}
                ))
            
            if top_k is not None:
                reranked = reranked[:top_k]
            
            return reranked
        
        return await self.reranker.rerank(query, ranked_chunks, top_k)
    
    def get_info(self) -> Dict[str, Any]:
        """Get reranker configuration info"""
        info = {"strategy": self.strategy}
        
        if hasattr(self.reranker, "model_name"):
            info["model_name"] = self.reranker.model_name
        if hasattr(self.reranker, "lexical_weight"):
            info["lexical_weight"] = self.reranker.lexical_weight
            info["semantic_weight"] = self.reranker.semantic_weight
            
        return info


async def quick_rerank(query: str, ranked_chunks: List[RankedChunk], strategy: str = "cross_encoder", top_k: int = 10) -> List[RerankedChunk]:
    """
    Convenience function for quick reranking.
    
    Args:
        query: Search query
        ranked_chunks: BM25-ranked chunks  
        strategy: Reranking strategy to use
        top_k: Maximum results to return
        
    Returns:
        Reranked chunks
    """
    reranker = ReRanker(strategy=strategy)
    return await reranker.rerank(query, ranked_chunks, top_k)