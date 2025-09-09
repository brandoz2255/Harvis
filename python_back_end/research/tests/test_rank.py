"""
Tests for ranking module (BM25 and reranking).
"""

import pytest
import asyncio
from typing import List

from ..rank.bm25 import BM25Ranker, quick_bm25_rank, DocChunk
from ..rank.rerank import ReRanker, quick_rerank, CrossEncoderReranker, EmbeddingReranker


class TestBM25Ranker:
    """Test BM25 ranking functionality"""
    
    @pytest.fixture
    def sample_chunks(self) -> List[DocChunk]:
        """Sample document chunks for testing"""
        return [
            DocChunk(
                content="Python is a programming language with simple syntax and powerful libraries",
                url="https://example.com/python-intro",
                chunk_id="chunk_1"
            ),
            DocChunk(
                content="Machine learning algorithms require large datasets for training neural networks",
                url="https://example.com/ml-basics", 
                chunk_id="chunk_2"
            ),
            DocChunk(
                content="Python machine learning libraries include scikit-learn and TensorFlow for data science",
                url="https://example.com/python-ml",
                chunk_id="chunk_3"
            ),
            DocChunk(
                content="Web development using Python frameworks like Django and Flask",
                url="https://example.com/python-web",
                chunk_id="chunk_4"
            )
        ]
    
    def test_bm25_initialization(self):
        """Test BM25 ranker initialization"""
        ranker = BM25Ranker()
        assert ranker.k1 == 1.5
        assert ranker.b == 0.75
        assert ranker.min_score == 0.01
        
        # Custom parameters
        ranker2 = BM25Ranker(k1=2.0, b=0.5, min_score=0.1)
        assert ranker2.k1 == 2.0
        assert ranker2.b == 0.5
        assert ranker2.min_score == 0.1
    
    def test_tokenization(self):
        """Test text tokenization"""
        ranker = BM25Ranker()
        tokens = ranker._tokenize("This is a Test! With punctuation.")
        assert tokens == ["this", "is", "a", "test", "with", "punctuation"]
    
    def test_term_frequencies(self):
        """Test term frequency calculation"""
        ranker = BM25Ranker()
        tokens = ["python", "python", "programming", "language"]
        tf = ranker._compute_term_frequencies(tokens)
        assert tf["python"] == 2
        assert tf["programming"] == 1
        assert tf["language"] == 1
    
    def test_indexing(self, sample_chunks):
        """Test document indexing"""
        ranker = BM25Ranker()
        ranker.index_chunks(sample_chunks)
        
        assert ranker._total_docs == 4
        assert len(ranker._indexed_chunks) == 4
        assert ranker._avg_doc_length > 0
        
        # Check document frequencies
        assert ranker._doc_frequencies["python"] == 3  # Appears in 3 documents
        assert ranker._doc_frequencies["machine"] == 2  # Appears in 2 documents
    
    def test_idf_calculation(self, sample_chunks):
        """Test IDF calculation"""
        ranker = BM25Ranker()
        ranker.index_chunks(sample_chunks)
        
        # Term that appears in 3/4 documents
        python_idf = ranker._compute_idf("python")
        assert python_idf > 0  # Should be positive but low
        
        # Term that appears in 2/4 documents
        machine_idf = ranker._compute_idf("machine")
        assert machine_idf > python_idf  # Should be higher than python
        
        # Non-existent term
        nonexistent_idf = ranker._compute_idf("nonexistent")
        assert nonexistent_idf == 0.0
    
    def test_ranking(self, sample_chunks):
        """Test BM25 ranking"""
        ranker = BM25Ranker()
        ranked = ranker.rank_chunks("python machine learning", sample_chunks)
        
        assert len(ranked) > 0
        assert all(chunk.score >= 0 for chunk in ranked)
        
        # Results should be sorted by score (descending)
        scores = [chunk.score for chunk in ranked]
        assert scores == sorted(scores, reverse=True)
        
        # Document with both "python" and "machine learning" should rank highest
        best_match = ranked[0]
        assert "python" in best_match.chunk.content.lower()
        assert "machine" in best_match.chunk.content.lower()
    
    def test_quick_bm25_rank(self, sample_chunks):
        """Test convenience function"""
        ranked = quick_bm25_rank("Python programming", sample_chunks, top_k=2)
        
        assert len(ranked) <= 2
        assert all("python" in chunk.chunk.content.lower() for chunk in ranked)
    
    def test_empty_query(self, sample_chunks):
        """Test handling of empty query"""
        ranker = BM25Ranker()
        ranked = ranker.rank_chunks("", sample_chunks)
        assert len(ranked) == 0
    
    def test_empty_chunks(self):
        """Test handling of empty chunk list"""
        ranker = BM25Ranker()
        ranked = ranker.rank_chunks("test query", [])
        assert len(ranked) == 0


class TestReRanker:
    """Test reranking functionality"""
    
    @pytest.fixture
    def sample_ranked_chunks(self):
        """Sample BM25-ranked chunks for reranking tests"""
        from ..rank.bm25 import RankedChunk
        
        chunks = [
            DocChunk(
                content="Python machine learning with scikit-learn library",
                url="https://example.com/python-ml",
                chunk_id="chunk_1"
            ),
            DocChunk(
                content="Machine learning algorithms and neural networks",
                url="https://example.com/ml-algorithms", 
                chunk_id="chunk_2"
            )
        ]
        
        return [
            RankedChunk(chunk=chunks[0], score=0.8, term_matches={"python": 1, "machine": 1}),
            RankedChunk(chunk=chunks[1], score=0.6, term_matches={"machine": 1, "learning": 1})
        ]
    
    def test_cross_encoder_reranker_init(self):
        """Test cross-encoder reranker initialization"""
        reranker = CrossEncoderReranker()
        assert reranker.model_name == "cross-encoder/ms-marco-MiniLM-L-12-v2"
        assert reranker.lexical_weight == 0.3
        assert reranker.semantic_weight == 0.7
    
    def test_embedding_reranker_init(self):
        """Test embedding reranker initialization"""
        reranker = EmbeddingReranker()
        assert reranker.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert reranker.lexical_weight == 0.4
        assert reranker.semantic_weight == 0.6
    
    @pytest.mark.asyncio
    async def test_cross_encoder_reranking(self, sample_ranked_chunks):
        """Test cross-encoder reranking"""
        reranker = CrossEncoderReranker()
        reranked = await reranker.rerank("python machine learning", sample_ranked_chunks)
        
        assert len(reranked) == len(sample_ranked_chunks)
        assert all(hasattr(chunk, 'semantic_score') for chunk in reranked)
        assert all(hasattr(chunk, 'combined_score') for chunk in reranked)
        
        # Scores should be between 0 and 1
        for chunk in reranked:
            assert 0 <= chunk.semantic_score <= 1
            assert chunk.combined_score >= 0
    
    @pytest.mark.asyncio
    async def test_embedding_reranking(self, sample_ranked_chunks):
        """Test embedding-based reranking"""
        reranker = EmbeddingReranker()
        reranked = await reranker.rerank("python machine learning", sample_ranked_chunks)
        
        assert len(reranked) == len(sample_ranked_chunks)
        assert all(chunk.semantic_score >= 0 for chunk in reranked)
        assert all(chunk.combined_score >= 0 for chunk in reranked)
    
    @pytest.mark.asyncio
    async def test_reranker_orchestrator(self, sample_ranked_chunks):
        """Test main ReRanker orchestrator"""
        reranker = ReRanker(strategy="cross_encoder")
        reranked = await reranker.rerank("python machine learning", sample_ranked_chunks)
        
        assert len(reranked) > 0
        assert all(hasattr(chunk, 'combined_score') for chunk in reranked)
        
        # Test no reranking strategy
        no_reranker = ReRanker(strategy="none")
        no_reranked = await no_reranker.rerank("test", sample_ranked_chunks)
        
        assert len(no_reranked) == len(sample_ranked_chunks)
        assert all(chunk.semantic_score == 0.0 for chunk in no_reranked)
    
    @pytest.mark.asyncio
    async def test_quick_rerank(self, sample_ranked_chunks):
        """Test convenience function"""
        reranked = await quick_rerank(
            "python machine learning",
            sample_ranked_chunks,
            strategy="embedding",
            top_k=1
        )
        
        assert len(reranked) <= 1
    
    def test_reranker_info(self):
        """Test reranker configuration info"""
        reranker = ReRanker(strategy="cross_encoder", lexical_weight=0.4)
        info = reranker.get_info()
        
        assert info["strategy"] == "cross_encoder"
        assert "lexical_weight" in info
        assert "semantic_weight" in info
    
    @pytest.mark.asyncio
    async def test_empty_chunks_reranking(self):
        """Test reranking with empty chunk list"""
        reranker = ReRanker(strategy="cross_encoder")
        reranked = await reranker.rerank("test query", [])
        assert len(reranked) == 0


if __name__ == "__main__":
    pytest.main([__file__])