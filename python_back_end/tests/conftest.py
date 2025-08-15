"""
Pytest configuration and fixtures
"""

import pytest
import os
import sys
from unittest.mock import Mock, patch

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture
def mock_ollama_response():
    """Mock Ollama API response"""
    return {
        "message": {
            "content": "This is a test response from the LLM model."
        }
    }

@pytest.fixture
def mock_search_results():
    """Mock search results for testing"""
    return [
        {
            "title": "Test Article 1",
            "url": "https://example.com/article1",
            "snippet": "This is a test snippet from article 1"
        },
        {
            "title": "Test Article 2", 
            "url": "https://example.com/article2",
            "snippet": "This is a test snippet from article 2"
        }
    ]

@pytest.fixture
def mock_extracted_content():
    """Mock extracted content from URLs"""
    return [
        {
            "title": "Test Article 1",
            "text": "This is the full text content of test article 1. It contains detailed information about the topic.",
            "authors": ["Test Author 1"],
            "publish_date": "2024-01-01",
            "url": "https://example.com/article1",
            "success": True
        },
        {
            "title": "Test Article 2",
            "text": "This is the full text content of test article 2. It provides additional context and information.",
            "authors": ["Test Author 2"],
            "publish_date": "2024-01-02",
            "url": "https://example.com/article2",
            "success": True
        }
    ]

@pytest.fixture
def mock_requests_post():
    """Mock requests.post for LLM API calls"""
    with patch('requests.post') as mock_post:
        yield mock_post

@pytest.fixture
def mock_duckduckgo_search():
    """Mock DuckDuckGo search"""
    with patch('langchain_community.utilities.DuckDuckGoSearchAPIWrapper') as mock_wrapper:
        yield mock_wrapper

@pytest.fixture
def mock_newspaper_article():
    """Mock newspaper Article class"""
    with patch('newspaper.Article') as mock_article:
        yield mock_article