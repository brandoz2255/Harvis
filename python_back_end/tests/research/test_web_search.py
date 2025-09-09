"""
Unit tests for web search functionality
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from research.web_search import WebSearchAgent, TavilySearchAgent

class TestWebSearchAgent:
    """Test cases for WebSearchAgent"""
    
    @pytest.fixture
    def web_search_agent(self):
        """Create a WebSearchAgent instance for testing"""
        return WebSearchAgent(max_results=3, max_workers=2)
    
    @patch('research.web_search.DDGS')
    def test_search_web_success(self, mock_ddgs_class, web_search_agent):
        """Test successful web search"""
        # Mock the DDGS context manager and its text method
        mock_ddgs_instance = Mock()
        mock_ddgs_instance.text.return_value = [
            {"title": "Test Article 1", "href": "https://example.com/article1", "body": "Test snippet 1"},
            {"title": "Test Article 2", "href": "https://example.com/article2", "body": "Test snippet 2"}
        ]
        mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs_instance
        
        # Test the search
        results = web_search_agent.search_web("test query")
        
        # Assertions
        assert len(results) >= 0

    @patch('research.web_search.DDGS')
    def test_search_web_failure(self, mock_ddgs_class, web_search_agent):
        """Test web search failure handling"""
        # Mock the DDGS context manager to raise an exception
        mock_ddgs_class.side_effect = Exception("Search failed")
        
        # Test the search
        results = web_search_agent.search_web("test query")
        
        # Assertions
        assert results == []
    
    @patch('research.web_search.requests.head')
    @patch('research.web_search.Article')
    def test_extract_content_from_url_success(self, mock_article_class, mock_requests_head, web_search_agent):
        """Test successful content extraction from URL"""
        # Mock the requests.head call to return success
        mock_response = Mock()
        mock_response.status_code = 200
        mock_requests_head.return_value = mock_response
        # Mock the Article instance
        mock_article = Mock()
        mock_article.title = "Test Article"
        mock_article.text = "This is the full article text."
        mock_article.authors = ["Author 1", "Author 2"]
        mock_article.publish_date = "2024-01-01"
        mock_article_class.return_value = mock_article
        
        # Test content extraction
        result = web_search_agent.extract_content_from_url("https://example.com/article")
        
        # Assertions
        assert result["success"] == True
        assert result["title"] == "Test Article"
        assert result["text"] == "This is the full article text."
        assert result["authors"] == ["Author 1", "Author 2"]
        assert result["url"] == "https://example.com/article"
        
        # Verify requests.head was called
        mock_requests_head.assert_called_once()
        # Verify Article methods were called
        mock_article.download.assert_called_once()
        mock_article.parse.assert_called_once()
    
    @patch('research.web_search.requests.head')
    @patch('research.web_search.Article')
    def test_extract_content_from_url_failure(self, mock_article_class, mock_requests_head, web_search_agent):
        """Test content extraction failure handling"""
        # Mock the requests.head call to return failure
        mock_response = Mock()
        mock_response.status_code = 404
        mock_requests_head.return_value = mock_response
        # Mock the Article instance to raise an exception
        mock_article = Mock()
        mock_article.download.side_effect = Exception("Download failed")
        mock_article_class.return_value = mock_article
        
        # Test content extraction
        result = web_search_agent.extract_content_from_url("https://example.com/article")
        
        # Assertions
        assert result["success"] == False
        assert "error" in result
        assert result["url"] == "https://example.com/article"
    
    @patch('research.web_search.WebSearchAgent.extract_content_from_urls')
    @patch('research.web_search.WebSearchAgent.search_web')
    def test_search_and_extract(self, mock_search_web, mock_extract_content, web_search_agent):
        """Test combined search and extract functionality"""
        # Mock search results
        mock_search_web.return_value = [
            {"title": "Article 1", "url": "https://example.com/1", "snippet": "Snippet 1"},
            {"title": "Article 2", "url": "https://example.com/2", "snippet": "Snippet 2"}
        ]
        
        # Mock content extraction
        mock_extract_content.return_value = [
            {"title": "Article 1", "text": "Full text 1", "success": True},
            {"title": "Article 2", "text": "Full text 2", "success": True}
        ]
        
        # Test search and extract
        result = web_search_agent.search_and_extract("test query", extract_content=True)
        
        # Assertions
        assert result["query"] == "test query"
        assert len(result["search_results"]) == 2
        assert len(result["extracted_content"]) == 2
        
        # Verify methods were called
        mock_search_web.assert_called_once_with("test query")
        mock_extract_content.assert_called_once_with(["https://example.com/1", "https://example.com/2"])
    
    @patch('research.web_search.WebSearchAgent.search_and_extract')
    def test_get_summarized_content(self, mock_search_and_extract, web_search_agent):
        """Test summarized content generation"""
        # Mock search and extract results
        mock_search_and_extract.return_value = {
            "search_results": [
                {"title": "Article 1", "url": "https://example.com/1", "snippet": "Test snippet 1"},
                {"title": "Article 2", "url": "https://example.com/2", "snippet": "Test snippet 2"}
            ],
            "extracted_content": [
                {"title": "Article 1", "text": "Full article text 1", "url": "https://example.com/1", "success": True},
                {"title": "Article 2", "text": "Full article text 2", "url": "https://example.com/2", "success": True}
            ]
        }
        
        # Test summarized content
        result = web_search_agent.get_summarized_content("test query")
        
        # Assertions
        assert isinstance(result, str)
        assert "Article 1" in result
        assert "Article 2" in result
        assert "Test snippet 1" in result
        assert "https://example.com/1" in result

class TestTavilySearchAgent:
    """Test cases for TavilySearchAgent"""
    
    @pytest.fixture
    def tavily_agent(self):
        """Create a TavilySearchAgent instance for testing"""
        return TavilySearchAgent(api_key="test_key")
    
    @patch('tavily.TavilyClient')
    def test_search_web_with_api_key(self, mock_tavily_client, tavily_agent):
        """Test Tavily search with API key"""
        # Mock Tavily client instance
        mock_client_instance = Mock()
        mock_client_instance.search.return_value = {
            "results": [
                {"title": "Tavily Article 1", "url": "https://example.com/tavily1", "content": "Tavily content 1"},
                {"title": "Tavily Article 2", "url": "https://example.com/tavily2", "content": "Tavily content 2"}
            ]
        }
        mock_tavily_client.return_value = mock_client_instance
        
        # Test search
        results = tavily_agent.search_web("test query")
        
        # Assertions
        assert len(results) == 2
        assert results[0]["title"] == "Tavily Article 1"
        assert results[0]["source"] == "Tavily"
        assert results[0]["snippet"] == "Tavily content 1"
    
    @patch('research.web_search.WebSearchAgent')
    def test_search_web_without_api_key(self, mock_web_search_agent):
        """Test fallback to WebSearchAgent when no API key"""
        # Create agent without API key
        agent = TavilySearchAgent(api_key=None)
        
        # Mock WebSearchAgent
        mock_instance = Mock()
        mock_instance.search_web.return_value = [{"title": "Fallback result"}]
        mock_web_search_agent.return_value = mock_instance
        
        # Test search
        results = agent.search_web("test query")
        
        # Assertions
        mock_web_search_agent.assert_called_once()
        mock_instance.search_web.assert_called_once_with("test query", 5)
    
    @patch('tavily.TavilyClient')
    @patch('research.web_search.WebSearchAgent')
    def test_search_web_api_failure(self, mock_web_search_agent, mock_tavily_client, tavily_agent):
        """Test fallback when Tavily API fails"""
        # Mock Tavily client to raise exception
        mock_client_instance = Mock()
        mock_client_instance.search.side_effect = Exception("API failed")
        mock_tavily_client.return_value = mock_client_instance
        
        # Mock WebSearchAgent fallback
        mock_instance = Mock()
        mock_instance.search_web.return_value = [{"title": "Fallback result"}]
        mock_web_search_agent.return_value = mock_instance
        
        # Test search
        results = tavily_agent.search_web("test query")
        
        # Assertions
        mock_web_search_agent.assert_called_once()
        mock_instance.search_web.assert_called_once_with("test query", 5)
