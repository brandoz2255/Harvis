"""
Integration tests for research pipeline.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from ..pipeline.research_agent import ResearchAgent, ResearchConfig, ResearchResult, ResearchStage
from ..pipeline.fact_check import FactChecker, FactCheckResult, FactCheckVerdict
from ..pipeline.compare import ComparativeAnalyzer, ComparisonResult


class TestResearchAgent:
    """Test main research agent pipeline"""
    
    @pytest.fixture
    def research_config(self):
        """Test configuration"""
        return ResearchConfig(
            max_search_results=10,
            enable_verification=True,
            max_chunks_for_synthesis=5,
            enable_reranking=True
        )
    
    def test_research_config_defaults(self):
        """Test default configuration values"""
        config = ResearchConfig()
        assert config.enable_query_expansion == True
        assert config.max_queries == 3
        assert config.max_search_results == 20
        assert config.enable_reranking == True
        assert config.enable_verification == True
    
    def test_research_agent_initialization(self, research_config):
        """Test research agent initialization"""
        agent = ResearchAgent(research_config)
        
        assert agent.config == research_config
        assert agent.llm_client is not None
        assert agent.ranker is not None
        assert agent.reranker is not None
        assert agent.map_reduce is not None
        assert agent.verifier is not None
        assert agent.renderer is not None
    
    @pytest.mark.asyncio
    async def test_planning_stage(self, research_config):
        """Test query planning stage"""
        agent = ResearchAgent(research_config)
        
        # Test basic planning
        queries = await agent._planning_stage("machine learning")
        assert len(queries) >= 1
        assert "machine learning" in queries
        
        # Test with query expansion disabled
        agent.config.enable_query_expansion = False
        queries_no_expansion = await agent._planning_stage("AI")
        assert queries_no_expansion == ["AI"]
    
    @pytest.mark.asyncio
    async def test_search_stage(self, research_config):
        """Test search stage (placeholder implementation)"""
        agent = ResearchAgent(research_config)
        
        queries = ["machine learning", "AI algorithms"]
        results = await agent._search_stage(queries)
        
        assert isinstance(results, list)
        assert len(results) <= research_config.max_search_results
        
        # Check result structure
        if results:
            result = results[0]
            assert "url" in result
            assert "title" in result
            assert "snippet" in result
    
    @pytest.mark.asyncio
    async def test_extraction_stage(self, research_config):
        """Test content extraction stage"""
        agent = ResearchAgent(research_config)
        
        search_results = [
            {
                "url": "https://example.com/article1",
                "title": "Test Article",
                "snippet": "Test snippet",
                "relevance_score": 0.8
            }
        ]
        
        extracted = await agent._extraction_stage(search_results)
        
        assert isinstance(extracted, list)
        assert len(extracted) == len(search_results)
        
        if extracted:
            content = extracted[0]
            assert "url" in content
            assert "title" in content
            assert "content" in content
            assert "extraction_success" in content
    
    @pytest.mark.asyncio
    async def test_ranking_stage(self, research_config):
        """Test ranking stage"""
        agent = ResearchAgent(research_config)
        
        extracted_content = [
            {
                "url": "https://example.com/test",
                "title": "Test Article",
                "content": "Machine learning algorithms use neural networks for pattern recognition"
            }
        ]
        
        ranked = await agent._ranking_stage("machine learning", extracted_content)
        
        assert isinstance(ranked, list)
        if ranked:
            chunk = ranked[0]
            assert hasattr(chunk, 'chunk')
            assert hasattr(chunk, 'combined_score')
    
    @pytest.mark.asyncio 
    async def test_full_research_pipeline(self, research_config):
        """Test complete research pipeline"""
        agent = ResearchAgent(research_config)
        
        result = await agent.research("What is machine learning?")
        
        assert isinstance(result, ResearchResult)
        assert result.query == "What is machine learning?"
        assert len(result.stage_results) > 0
        
        # Check that we have results from multiple stages
        stage_names = [stage_result.stage.value for stage_result in result.stage_results]
        assert "planning" in stage_names
        assert "search" in stage_names
        assert "extraction" in stage_names
        
        # Check metadata
        assert "queries_used" in result.metadata
        assert result.total_duration > 0
    
    def test_pipeline_stats(self, research_config):
        """Test pipeline statistics"""
        agent = ResearchAgent(research_config)
        stats = agent.get_pipeline_stats()
        
        assert "total_pipelines" in stats
        assert "total_duration" in stats
        assert "avg_duration" in stats
        assert "stage_stats" in stats
        assert "config" in stats


class TestFactChecker:
    """Test fact-checking pipeline"""
    
    def test_fact_checker_initialization(self):
        """Test fact checker initialization"""
        checker = FactChecker()
        
        assert checker.config.max_search_results == 25  # More for fact-checking
        assert checker.config.enable_verification == True
        assert checker.authority_weights["gov"] == 1.0
        assert checker.authority_weights["edu"] == 0.9
        assert checker.authority_weights["reddit.com"] == 0.3
    
    def test_source_authority_assessment(self):
        """Test source authority scoring"""
        checker = FactChecker()
        
        # High authority sources
        high_auth_sources = ["https://example.gov/article", "https://university.edu/research"]
        high_score = checker._assess_source_authority(high_auth_sources)
        assert high_score > 0.8
        
        # Low authority sources
        low_auth_sources = ["https://reddit.com/post", "https://twitter.com/user"]
        low_score = checker._assess_source_authority(low_auth_sources)
        assert low_score < 0.3
        
        # Empty sources
        assert checker._assess_source_authority([]) == 0.0
    
    def test_verdict_determination(self):
        """Test fact-check verdict logic"""
        checker = FactChecker()
        
        # Strong support
        strong_support = {
            "supporting_evidence": 5,
            "contradicting_evidence": 0,
            "support_ratio": 0.9
        }
        verdict = checker._determine_verdict(strong_support, authority_score=0.8, verification_accuracy=0.9)
        assert verdict == FactCheckVerdict.SUPPORTED
        
        # Contradiction
        contradiction = {
            "supporting_evidence": 1,
            "contradicting_evidence": 3,
            "support_ratio": 0.25
        }
        verdict = checker._determine_verdict(contradiction, authority_score=0.7, verification_accuracy=0.8)
        assert verdict == FactCheckVerdict.CONTRADICTED
        
        # Insufficient evidence
        insufficient = {
            "supporting_evidence": 0,
            "contradicting_evidence": 0,
            "support_ratio": 0.0
        }
        verdict = checker._determine_verdict(insufficient, authority_score=0.2, verification_accuracy=0.3)
        assert verdict == FactCheckVerdict.INSUFFICIENT_EVIDENCE
    
    @pytest.mark.asyncio
    async def test_fact_check_execution(self):
        """Test fact-checking execution"""
        checker = FactChecker()
        
        # Mock the research agent to avoid actual web requests
        with patch.object(checker.research_agent, 'research', new_callable=AsyncMock) as mock_research:
            # Mock successful research result
            mock_research.return_value = Mock(
                success=True,
                response="Test response about the claim",
                sources_count=5,
                confidence_score=0.8,
                stage_results=[],
                total_duration=2.5
            )
            
            result = await checker.fact_check("The Earth is round")
            
            assert isinstance(result, FactCheckResult)
            assert result.claim == "The Earth is round"
            assert result.verdict in FactCheckVerdict
            assert 0 <= result.confidence <= 1
            assert result.processing_time > 0
            assert isinstance(result.response, str)
    
    @pytest.mark.asyncio
    async def test_batch_fact_check(self):
        """Test batch fact-checking"""
        checker = FactChecker()
        
        claims = ["Claim 1", "Claim 2", "Claim 3"]
        
        with patch.object(checker, 'fact_check', new_callable=AsyncMock) as mock_fact_check:
            mock_fact_check.return_value = FactCheckResult(
                claim="Test claim",
                verdict=FactCheckVerdict.SUPPORTED,
                confidence=0.8,
                evidence_count=3,
                contradicting_evidence=0,
                supporting_sources=[],
                contradicting_sources=[],
                authority_score=0.7,
                response="Test response",
                processing_time=1.0,
                metadata={}
            )
            
            results = await checker.batch_fact_check(claims)
            
            assert len(results) == len(claims)
            assert all(isinstance(result, FactCheckResult) for result in results)
            assert mock_fact_check.call_count == len(claims)


class TestComparativeAnalyzer:
    """Test comparative analysis pipeline"""
    
    def test_comparative_analyzer_initialization(self):
        """Test analyzer initialization"""
        analyzer = ComparativeAnalyzer()
        
        assert analyzer.config.max_search_results == 15
        assert analyzer.config.enable_verification == True
        assert len(analyzer.default_dimensions) == 5
    
    @pytest.mark.asyncio
    async def test_single_topic_analysis(self):
        """Test analysis of single topic"""
        analyzer = ComparativeAnalyzer()
        
        with patch.object(analyzer.research_agent, 'research', new_callable=AsyncMock) as mock_research:
            mock_research.return_value = Mock(
                success=True,
                response="Test analysis of the topic",
                confidence_score=0.8,
                sources_count=5
            )
            
            analysis = await analyzer._analyze_single_topic("Python programming")
            
            assert analysis.topic == "Python programming"
            assert analysis.research_result.success == True
            assert analysis.confidence == 0.8
            assert analysis.source_count == 5
            assert len(analysis.key_points) > 0
    
    def test_comparison_matrix_extraction(self):
        """Test extraction of comparison matrix"""
        analyzer = ComparativeAnalyzer()
        
        # Mock topic analyses
        from ..pipeline.compare import TopicAnalysis, ComparisonDimension
        mock_analyses = [
            Mock(
                topic="Python",
                key_points={
                    ComparisonDimension.DEFINITION: "Python is a programming language",
                    ComparisonDimension.FEATURES: "Simple syntax, powerful libraries"
                }
            ),
            Mock(
                topic="Java", 
                key_points={
                    ComparisonDimension.DEFINITION: "Java is a programming language",
                    ComparisonDimension.FEATURES: "Object-oriented, platform independent"
                }
            )
        ]
        
        matrix = analyzer._extract_comparison_dimensions(mock_analyses)
        
        assert ComparisonDimension.DEFINITION in matrix
        assert ComparisonDimension.FEATURES in matrix
        assert "Python" in matrix[ComparisonDimension.DEFINITION]
        assert "Java" in matrix[ComparisonDimension.DEFINITION]
    
    def test_similarities_differences_identification(self):
        """Test identification of similarities and differences"""
        analyzer = ComparativeAnalyzer()
        
        # Mock data
        mock_analyses = []
        mock_matrix = {
            analyzer.default_dimensions[0]: {
                "Topic1": "Similar description",
                "Topic2": "Similar description"  # Same value
            },
            analyzer.default_dimensions[1]: {
                "Topic1": "Different feature 1",
                "Topic2": "Different feature 2"  # Different values
            }
        }
        
        similarities, differences = analyzer._identify_similarities_differences(mock_analyses, mock_matrix)
        
        assert len(similarities) > 0
        assert len(differences) > 0
    
    @pytest.mark.asyncio
    async def test_full_comparison(self):
        """Test complete comparison pipeline"""
        analyzer = ComparativeAnalyzer()
        
        topics = ["Python", "JavaScript"]
        
        with patch.object(analyzer, '_analyze_single_topic', new_callable=AsyncMock) as mock_analyze:
            from ..pipeline.compare import TopicAnalysis
            mock_analyze.side_effect = [
                Mock(
                    topic="Python",
                    research_result=Mock(success=True),
                    key_points={},
                    confidence=0.8,
                    source_count=5,
                    processing_time=1.0
                ),
                Mock(
                    topic="JavaScript", 
                    research_result=Mock(success=True),
                    key_points={},
                    confidence=0.7,
                    source_count=4,
                    processing_time=1.2
                )
            ]
            
            result = await analyzer.compare(topics)
            
            assert isinstance(result, ComparisonResult)
            assert result.topics == topics
            assert len(result.topic_analyses) == 2
            assert result.overall_confidence > 0
            assert result.processing_time > 0
            assert isinstance(result.response, str)
    
    @pytest.mark.asyncio
    async def test_comparison_with_template(self):
        """Test comparison with predefined template"""
        analyzer = ComparativeAnalyzer()
        
        with patch.object(analyzer, 'compare', new_callable=AsyncMock) as mock_compare:
            mock_compare.return_value = Mock(response="Template comparison result")
            
            result = await analyzer.compare_with_template(
                topics=["Topic1", "Topic2"],
                template="business_analysis"
            )
            
            mock_compare.assert_called_once()
            assert result.response == "Template comparison result"
    
    @pytest.mark.asyncio
    async def test_comparison_error_handling(self):
        """Test error handling in comparison"""
        analyzer = ComparativeAnalyzer()
        
        # Test insufficient topics
        with pytest.raises(ValueError):
            await analyzer.compare(["single_topic"])
        
        # Test exception handling
        with patch.object(analyzer, '_analyze_single_topic', side_effect=Exception("Test error")):
            result = await analyzer.compare(["Topic1", "Topic2"])
            
            # Should handle exceptions gracefully
            assert isinstance(result, ComparisonResult)
            assert result.overall_confidence == 0.0


# Integration tests
class TestPipelineIntegration:
    """Integration tests across pipeline components"""
    
    @pytest.mark.asyncio
    async def test_research_to_fact_check_integration(self):
        """Test research pipeline feeding into fact-checking"""
        # This would test actual integration between components
        pass
    
    @pytest.mark.asyncio
    async def test_research_to_comparison_integration(self):
        """Test research pipeline feeding into comparison"""
        pass
    
    @pytest.mark.asyncio 
    async def test_end_to_end_pipeline(self):
        """Test complete end-to-end pipeline"""
        # This would test the full pipeline with real components
        pass


# Performance tests
class TestPipelinePerformance:
    """Performance tests for pipeline components"""
    
    @pytest.mark.asyncio
    async def test_research_performance(self):
        """Test research pipeline performance"""
        # Could include timing benchmarks
        pass
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """Test handling of concurrent requests"""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])