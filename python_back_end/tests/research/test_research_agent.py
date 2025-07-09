"""
Unit tests for research agent functionality
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from research.research_agent import ResearchAgent

class TestResearchAgent:
    """Test cases for ResearchAgent"""
    
    @pytest.fixture
    def research_agent(self):
        """Create a ResearchAgent instance for testing"""
        return ResearchAgent(
            search_engine="duckduckgo",
            ollama_url="http://test-ollama:11434",
            default_model="test-model",
            max_search_results=3
        )
    
    @patch('research.research_agent.requests.post')
    def test_query_llm_success(self, mock_post, research_agent, mock_ollama_response):
        """Test successful LLM query"""
        # Mock the requests response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        
        # Test LLM query
        result = research_agent.query_llm("test prompt", "test-model", "test system prompt")
        
        # Assertions
        assert result == "This is a test response from the LLM model."
        mock_post.assert_called_once()
        
        # Verify the request payload
        call_args = mock_post.call_args
        assert call_args[1]['json']['model'] == 'test-model'
        assert len(call_args[1]['json']['messages']) == 2
        assert call_args[1]['json']['messages'][0]['role'] == 'system'
        assert call_args[1]['json']['messages'][1]['role'] == 'user'
    
    @patch('research.research_agent.requests.post')
    def test_query_llm_failure(self, mock_post, research_agent):
        """Test LLM query failure handling"""
        # Mock the requests response to raise an exception
        mock_post.side_effect = Exception("Connection failed")
        
        # Test LLM query
        result = research_agent.query_llm("test prompt")
        
        # Assertions
        assert "Error querying LLM" in result
        assert "Connection failed" in result
    
    @patch('research.research_agent.ResearchAgent.query_llm')
    @patch('research.research_agent.ResearchAgent._get_timestamp')
    def test_research_topic_standard(self, mock_timestamp, mock_query_llm, research_agent):
        """Test standard research topic functionality"""
        # Mock timestamp
        mock_timestamp.return_value = "2024-01-01T12:00:00"
        
        # Mock LLM response
        mock_query_llm.return_value = "This is a comprehensive analysis of the research topic."
        
        # Mock search agent
        mock_search_agent = Mock()
        mock_search_agent.search_and_extract.return_value = {
            "query": "test topic",
            "search_results": [
                {"title": "Article 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
                {"title": "Article 2", "url": "https://example.com/2", "snippet": "Snippet 2"}
            ],
            "extracted_content": [
                {"title": "Article 1", "text": "Full text 1", "success": True},
                {"title": "Article 2", "text": "Full text 2", "success": True}
            ]
        }
        research_agent.search_agent = mock_search_agent
        
        # Test research
        result = research_agent.research_topic("test topic", "test-model", "standard", True)
        
        # Assertions
        assert result["topic"] == "test topic"
        assert result["analysis"] == "This is a comprehensive analysis of the research topic."
        assert result["research_depth"] == "standard"
        assert result["model_used"] == "test-model"
        assert result["sources_found"] == 2
        assert "sources" in result
        assert len(result["sources"]) == 2
        
        # Verify search agent was called
        mock_search_agent.search_and_extract.assert_called_once_with("test topic", extract_content=True)
    
    @patch('research.research_agent.ResearchAgent.query_llm')
    @patch('research.research_agent.ResearchAgent._get_timestamp')
    def test_fact_check(self, mock_timestamp, mock_query_llm, research_agent):
        """Test fact-checking functionality"""
        # Mock timestamp
        mock_timestamp.return_value = "2024-01-01T12:00:00"
        
        # Mock LLM response
        mock_query_llm.return_value = "Based on the evidence, this claim is FALSE. The sources clearly contradict this statement."
        
        # Mock search agent
        mock_search_agent = Mock()
        mock_search_agent.search_and_extract.return_value = {
            "query": "fact check: test claim",
            "search_results": [
                {"title": "Fact Check Article", "url": "https://factcheck.com/1", "snippet": "This claim is false"},
                {"title": "Scientific Study", "url": "https://science.com/1", "snippet": "Evidence shows otherwise"}
            ],
            "extracted_content": [
                {"title": "Fact Check Article", "text": "Detailed fact check analysis", "success": True}
            ]
        }
        research_agent.search_agent = mock_search_agent
        
        # Test fact check
        result = research_agent.fact_check("test claim", "test-model")
        
        # Assertions
        assert result["claim"] == "test claim"
        assert "FALSE" in result["analysis"]
        assert result["model_used"] == "test-model"
        assert len(result["sources"]) == 2
        
        # Verify search agent was called with fact check query
        mock_search_agent.search_and_extract.assert_called_once_with("fact check: test claim", extract_content=True)
    
    @patch('research.research_agent.ResearchAgent.query_llm')
    @patch('research.research_agent.ResearchAgent.research_topic')
    @patch('research.research_agent.ResearchAgent._get_timestamp')
    def test_comparative_research(self, mock_timestamp, mock_research_topic, mock_query_llm, research_agent):
        """Test comparative research functionality"""
        # Mock timestamp
        mock_timestamp.return_value = "2024-01-01T12:00:00"
        
        # Mock individual research results
        mock_research_topic.side_effect = [
            {"analysis": "Analysis of topic A", "sources": []},
            {"analysis": "Analysis of topic B", "sources": []},
            {"analysis": "Analysis of topic C", "sources": []}
        ]
        
        # Mock comparative analysis
        mock_query_llm.return_value = "Comparative analysis shows significant differences between the topics."
        
        # Test comparative research
        result = research_agent.comparative_research(["Topic A", "Topic B", "Topic C"], "test-model")
        
        # Assertions
        assert result["topics"] == ["Topic A", "Topic B", "Topic C"]
        assert "Topic A" in result["individual_research"]
        assert "Topic B" in result["individual_research"]
        assert "Topic C" in result["individual_research"]
        assert "significant differences" in result["comparative_analysis"]
        assert result["model_used"] == "test-model"
        
        # Verify research_topic was called for each topic
        assert mock_research_topic.call_count == 3
    
    def test_prepare_research_context(self, research_agent):
        """Test research context preparation"""
        # Mock search data
        search_data = {
            "search_results": [
                {"title": "Article 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
                {"title": "Article 2", "url": "https://example.com/2", "snippet": "Snippet 2"}
            ],
            "extracted_content": [
                {"title": "Article 1", "text": "Full text content 1", "url": "https://example.com/1", "success": True},
                {"title": "Article 2", "text": "Full text content 2", "url": "https://example.com/2", "success": True}
            ]
        }
        
        # Test context preparation
        context = research_agent._prepare_research_context(search_data)
        
        # Assertions
        assert "Source 1: Article 1" in context
        assert "Source 2: Article 2" in context
        assert "Full Content 1: Article 1" in context
        assert "Full Content 2: Article 2" in context
        assert "https://example.com/1" in context
        assert "https://example.com/2" in context
    
    def test_get_research_system_prompt(self, research_agent):
        """Test research system prompt generation"""
        # Test different depths
        quick_prompt = research_agent._get_research_system_prompt("quick")
        standard_prompt = research_agent._get_research_system_prompt("standard")
        deep_prompt = research_agent._get_research_system_prompt("deep")
        
        # Assertions
        assert "research assistant" in quick_prompt.lower()
        assert "research assistant" in standard_prompt.lower()
        assert "research assistant" in deep_prompt.lower()
        
        assert "concise" in quick_prompt.lower()
        assert "thorough" in standard_prompt.lower()
        assert "comprehensive" in deep_prompt.lower()
    
    def test_format_sources(self, research_agent):
        """Test source formatting"""
        # Mock search results
        search_results = [
            {"title": "Article 1", "url": "https://example.com/1", "source": "DuckDuckGo"},
            {"title": "Article 2", "url": "https://example.com/2", "source": "Tavily"}
        ]
        
        # Test source formatting
        formatted_sources = research_agent._format_sources(search_results)
        
        # Assertions
        assert len(formatted_sources) == 2
        assert formatted_sources[0]["title"] == "Article 1"
        assert formatted_sources[0]["url"] == "https://example.com/1"
        assert formatted_sources[0]["source"] == "DuckDuckGo"
        assert formatted_sources[1]["title"] == "Article 2"
        assert formatted_sources[1]["url"] == "https://example.com/2"
        assert formatted_sources[1]["source"] == "Tavily"
    
    def test_get_timestamp(self, research_agent):
        """Test timestamp generation"""
        timestamp = research_agent._get_timestamp()
        
        # Assertions
        assert isinstance(timestamp, str)
        assert "T" in timestamp  # ISO format contains T
        assert len(timestamp) > 10  # Should be a reasonable timestamp length

class TestResearchAgentInitialization:
    """Test ResearchAgent initialization with different parameters"""
    
    @patch('research.research_agent.TavilySearchAgent')
    def test_init_with_tavily(self, mock_tavily_agent):
        """Test initialization with Tavily search engine"""
        agent = ResearchAgent(search_engine="tavily")
        
        # Assertions
        mock_tavily_agent.assert_called_once()
        assert agent.search_engine == "tavily"
    
    @patch('research.research_agent.WebSearchAgent')
    def test_init_with_duckduckgo(self, mock_web_search_agent):
        """Test initialization with DuckDuckGo search engine"""
        agent = ResearchAgent(search_engine="duckduckgo")
        
        # Assertions
        mock_web_search_agent.assert_called_once()
        assert agent.search_engine == "duckduckgo"
    
    def test_init_with_custom_parameters(self):
        """Test initialization with custom parameters"""
        agent = ResearchAgent(
            search_engine="duckduckgo",
            ollama_url="http://custom-ollama:8080",
            default_model="custom-model",
            max_search_results=10
        )
        
        # Assertions
        assert agent.ollama_url == "http://custom-ollama:8080"
        assert agent.default_model == "custom-model"
        assert agent.max_search_results == 10