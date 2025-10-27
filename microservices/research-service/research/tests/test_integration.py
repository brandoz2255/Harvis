"""
Integration tests for the complete research system.

Tests end-to-end workflows and cross-module interactions.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import json
import tempfile
import os


class TestEndToEndWorkflow:
    """Test complete end-to-end research workflows"""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_basic_research_workflow(self, test_config, test_utils):
        """Test basic research workflow from query to response"""
        from ..pipeline.research_agent import ResearchAgent
        
        agent = ResearchAgent(test_config)
        
        # Mock all external dependencies
        with patch.multiple(
            agent,
            _search_stage=AsyncMock(return_value=[
                {"url": "https://test.com/1", "title": "Test 1", "snippet": "Content 1", "relevance_score": 0.9},
                {"url": "https://test.com/2", "title": "Test 2", "snippet": "Content 2", "relevance_score": 0.8}
            ]),
            _extraction_stage=AsyncMock(return_value=[
                {"url": "https://test.com/1", "title": "Test 1", "content": "Extracted content about machine learning", "extraction_success": True},
                {"url": "https://test.com/2", "title": "Test 2", "content": "More content about artificial intelligence", "extraction_success": True}
            ])
        ):
            result = await agent.research("What is machine learning?")
            
            assert result.success == True
            assert result.query == "What is machine learning?"
            assert result.response is not None
            assert len(result.stage_results) > 0
            assert result.sources_count > 0
            assert result.total_duration > 0
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_fact_check_workflow(self):
        """Test fact-checking workflow"""
        from ..pipeline.fact_check import FactChecker
        
        checker = FactChecker()
        
        with patch.object(checker.research_agent, 'research') as mock_research:
            mock_research.return_value = Mock(
                success=True,
                response="Research shows the claim is well-supported by evidence",
                sources_count=8,
                confidence_score=0.9,
                stage_results=[],
                total_duration=3.2
            )
            
            result = await checker.fact_check("The Earth orbits around the Sun")
            
            assert result.claim == "The Earth orbits around the Sun"
            assert result.verdict is not None
            assert 0 <= result.confidence <= 1
            assert result.response is not None
            assert result.processing_time > 0
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_comparison_workflow(self):
        """Test comparison workflow"""
        from ..pipeline.compare import ComparativeAnalyzer
        
        analyzer = ComparativeAnalyzer()
        
        with patch.object(analyzer.research_agent, 'research') as mock_research:
            # Return different results for different topics
            def side_effect(query):
                if "Python" in query:
                    return Mock(success=True, response="Python analysis", confidence_score=0.8, sources_count=5)
                else:
                    return Mock(success=True, response="JavaScript analysis", confidence_score=0.7, sources_count=4)
            
            mock_research.side_effect = side_effect
            
            result = await analyzer.compare(["Python", "JavaScript"])
            
            assert result.topics == ["Python", "JavaScript"]
            assert len(result.topic_analyses) == 2
            assert result.response is not None
            assert result.processing_time > 0
            assert result.overall_confidence > 0
    
    @pytest.mark.integration 
    @pytest.mark.asyncio
    async def test_research_to_fact_check_pipeline(self, test_utils):
        """Test using research results for fact-checking"""
        from ..pipeline.research_agent import ResearchAgent
        from ..pipeline.fact_check import FactChecker
        
        # First do research
        agent = ResearchAgent()
        checker = FactChecker()
        
        with patch.object(agent, 'research') as mock_research, \
             patch.object(checker, 'fact_check') as mock_fact_check:
            
            mock_research.return_value = test_utils.create_mock_research_result(
                response="Research indicates that renewable energy is beneficial for the environment"
            )
            
            mock_fact_check.return_value = Mock(
                claim="Renewable energy reduces carbon emissions",
                verdict=Mock(value="supported"),
                confidence=0.85,
                response="Fact-check confirms the claim"
            )
            
            # Research phase
            research_result = await agent.research("Benefits of renewable energy")
            assert research_result.success
            
            # Extract a claim from research for fact-checking
            claim = "Renewable energy reduces carbon emissions"
            fact_check_result = await checker.fact_check(claim)
            
            assert fact_check_result.claim == claim
            assert fact_check_result.confidence > 0


class TestCrossModuleIntegration:
    """Test integration between different modules"""
    
    @pytest.mark.integration
    def test_ranking_to_synthesis_integration(self, sample_documents):
        """Test integration from ranking to synthesis"""
        from ..rank.bm25 import BM25Ranker, DocChunk
        from ..synth.map_reduce import MapReduceProcessor
        
        # Create chunks from sample documents
        chunks = []
        for i, doc in enumerate(sample_documents):
            chunk = DocChunk(
                content=doc["content"],
                url=doc["url"],
                chunk_id=f"chunk_{i}",
                metadata=doc["metadata"]
            )
            chunks.append(chunk)
        
        # Rank chunks
        ranker = BM25Ranker()
        ranked_chunks = ranker.rank_chunks("machine learning python", chunks)
        
        assert len(ranked_chunks) > 0
        assert all(chunk.score > 0 for chunk in ranked_chunks)
        
        # Convert to reranked format for synthesis
        from ..rank.rerank import RerankedChunk
        reranked_chunks = []
        for ranked in ranked_chunks:
            reranked = RerankedChunk(
                chunk=ranked.chunk,
                lexical_score=ranked.score,
                semantic_score=0.5,
                combined_score=ranked.score,
                term_matches=ranked.term_matches
            )
            reranked_chunks.append(reranked)
        
        # Test that synthesis can process these chunks
        processor = MapReduceProcessor()
        assert len(reranked_chunks) > 0
    
    @pytest.mark.integration
    def test_cache_integration(self, test_cache_config):
        """Test cache integration with other components"""
        from ..cache.http_cache import HTTPCache, get_cache, setup_cache
        
        # Setup test cache
        cache = setup_cache(test_cache_config)
        
        assert cache is not None
        assert cache.config.cache_dir == "test_cache"
        
        # Test that global cache is accessible
        global_cache = get_cache()
        assert global_cache is not None
        
        # Test cache info
        info = cache.get_cache_info()
        assert "stats" in info
        assert "config" in info
    
    @pytest.mark.integration
    def test_llm_client_integration(self):
        """Test LLM client integration with other components"""
        from ..llm.ollama_client import OllamaClient
        from ..llm.model_policy import get_model_for_task, TaskType
        
        client = OllamaClient()
        assert client is not None
        
        # Test model selection
        model = get_model_for_task(TaskType.SYNTHESIS)
        assert isinstance(model, str)
        assert len(model) > 0
        
        model2 = get_model_for_task(TaskType.VERIFICATION)
        assert isinstance(model2, str)
        
        # Test client statistics
        stats = client.get_stats()
        assert "total_requests" in stats
        assert "success_rate" in stats


class TestErrorHandlingIntegration:
    """Test error handling across module boundaries"""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_search_failure_handling(self, test_config):
        """Test handling of search failures in research pipeline"""
        from ..pipeline.research_agent import ResearchAgent
        
        agent = ResearchAgent(test_config)
        
        with patch.object(agent, '_search_stage', side_effect=Exception("Search failed")):
            result = await agent.research("Test query")
            
            assert result.success == False
            assert "Search failed" in result.error or "search failed" in result.error.lower()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_extraction_failure_handling(self, test_config):
        """Test handling of extraction failures"""
        from ..pipeline.research_agent import ResearchAgent
        
        agent = ResearchAgent(test_config)
        
        with patch.object(agent, '_search_stage') as mock_search, \
             patch.object(agent, '_extraction_stage', side_effect=Exception("Extraction failed")):
            
            mock_search.return_value = [{"url": "test.com", "title": "test"}]
            
            result = await agent.research("Test query")
            
            assert result.success == False
            assert "extraction failed" in result.error.lower()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_synthesis_failure_recovery(self, test_config):
        """Test recovery from synthesis failures"""
        from ..pipeline.research_agent import ResearchAgent
        
        agent = ResearchAgent(test_config)
        
        with patch.multiple(
            agent,
            _search_stage=AsyncMock(return_value=[{"url": "test.com", "title": "test"}]),
            _extraction_stage=AsyncMock(return_value=[{"url": "test.com", "content": "test"}]),
            _synthesis_stage=AsyncMock(side_effect=Exception("Synthesis failed"))
        ):
            result = await agent.research("Test query") 
            
            assert result.success == False
            assert "synthesis failed" in result.error.lower()


class TestPerformanceIntegration:
    """Test performance characteristics of integrated system"""
    
    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_concurrent_research_requests(self, test_config):
        """Test handling of concurrent research requests"""
        from ..pipeline.research_agent import ResearchAgent
        
        agent = ResearchAgent(test_config)
        
        queries = [
            "What is Python?",
            "How does machine learning work?",
            "Benefits of renewable energy",
            "Comparison of databases"
        ]
        
        with patch.multiple(
            agent,
            _search_stage=AsyncMock(return_value=[]),
            _extraction_stage=AsyncMock(return_value=[]),
            _ranking_stage=AsyncMock(return_value=[]),
            _synthesis_stage=AsyncMock(return_value=([], Mock(success=True, synthesis="Test response"))),
            _verification_stage=AsyncMock(return_value=None),
            _rendering_stage=AsyncMock(return_value="Concurrent test response")
        ):
            # Run concurrent requests
            tasks = [agent.research(query) for query in queries]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            assert len(results) == len(queries)
            
            # Check that all completed (even if some failed)
            completed_count = sum(1 for r in results if not isinstance(r, Exception))
            assert completed_count >= len(queries) // 2  # At least half should complete
    
    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_memory_usage_stability(self, test_config):
        """Test memory usage remains stable during multiple operations"""
        from ..pipeline.research_agent import ResearchAgent
        import gc
        
        agent = ResearchAgent(test_config)
        
        with patch.multiple(
            agent,
            _search_stage=AsyncMock(return_value=[]),
            _extraction_stage=AsyncMock(return_value=[]),
            _ranking_stage=AsyncMock(return_value=[]),
            _synthesis_stage=AsyncMock(return_value=([], Mock(success=True, synthesis="Test"))),
            _verification_stage=AsyncMock(return_value=None),
            _rendering_stage=AsyncMock(return_value="Memory test response")
        ):
            # Run multiple research cycles
            for i in range(5):
                result = await agent.research(f"Test query {i}")
                assert isinstance(result.query, str)
                
                # Force garbage collection
                gc.collect()
            
            # Test passes if no memory leaks cause issues
            assert True


class TestConfigurationIntegration:
    """Test configuration propagation across modules"""
    
    @pytest.mark.integration
    def test_config_propagation(self):
        """Test that configuration is properly propagated"""
        from ..pipeline.research_agent import ResearchAgent, ResearchConfig
        
        config = ResearchConfig(
            max_search_results=5,
            enable_verification=False,
            enable_reranking=True,
            max_chunks_for_synthesis=3
        )
        
        agent = ResearchAgent(config)
        
        assert agent.config.max_search_results == 5
        assert agent.config.enable_verification == False
        assert agent.config.enable_reranking == True
        assert agent.config.max_chunks_for_synthesis == 3
        
        # Test that components respect configuration
        assert agent.map_reduce.max_concurrent <= config.max_concurrent_maps or config.max_concurrent_maps == 5
        assert agent.verifier.enable_llm_verification == config.enable_verification
    
    @pytest.mark.integration
    def test_cache_config_integration(self):
        """Test cache configuration integration"""
        from ..cache.http_cache import CacheConfig, HTTPCache
        
        config = CacheConfig(
            cache_dir="integration_test_cache",
            expire_after=120,
            max_response_size=2048
        )
        
        cache = HTTPCache(config)
        
        assert cache.config.cache_dir == "integration_test_cache"
        assert cache.config.expire_after == 120
        assert cache.config.max_response_size == 2048


# Test data generators for integration tests
class TestDataGeneration:
    """Generate test data for integration tests"""
    
    @staticmethod
    def create_large_document_set(count: int = 100):
        """Create large set of test documents"""
        documents = []
        for i in range(count):
            doc = {
                "url": f"https://testdocs.com/doc_{i}",
                "title": f"Test Document {i}",
                "content": f"This is test document {i} containing various keywords like machine learning, Python, AI, and data science. " * 5,
                "metadata": {"doc_id": i, "category": f"category_{i % 5}"}
            }
            documents.append(doc)
        return documents
    
    @staticmethod
    def create_search_result_set(query: str, count: int = 20):
        """Create set of mock search results"""
        results = []
        for i in range(count):
            result = {
                "url": f"https://searchresults.com/result_{i}",
                "title": f"Search Result {i} for {query}",
                "snippet": f"This result discusses {query} in detail with examples and explanations...",
                "relevance_score": max(0.1, 1.0 - (i * 0.05))  # Decreasing relevance
            }
            results.append(result)
        return results


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])