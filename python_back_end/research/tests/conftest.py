"""
Pytest configuration and fixtures for research system tests.
"""

import pytest
import asyncio
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock


# Test data fixtures
@pytest.fixture
def sample_documents() -> List[Dict[str, Any]]:
    """Sample documents for testing"""
    return [
        {
            "url": "https://example.com/doc1",
            "title": "Introduction to Machine Learning",
            "content": "Machine learning is a subset of artificial intelligence that enables computers to learn without being explicitly programmed. It uses algorithms to analyze data and make predictions.",
            "metadata": {"author": "Dr. Smith", "date": "2023-01-15"}
        },
        {
            "url": "https://example.com/doc2", 
            "title": "Python Programming Basics",
            "content": "Python is a high-level programming language known for its simple syntax and powerful libraries. It's widely used for web development, data science, and machine learning applications.",
            "metadata": {"author": "Jane Doe", "date": "2023-02-20"}
        },
        {
            "url": "https://example.com/doc3",
            "title": "Deep Learning with Neural Networks",
            "content": "Deep learning uses neural networks with multiple layers to model and understand complex patterns in data. TensorFlow and PyTorch are popular frameworks for building deep learning models.",
            "metadata": {"author": "AI Research Team", "date": "2023-03-10"}
        }
    ]


@pytest.fixture
def sample_search_results() -> List[Dict[str, Any]]:
    """Sample search results for testing"""
    return [
        {
            "url": "https://example.com/article1",
            "title": "Machine Learning Applications",
            "snippet": "Machine learning has applications in healthcare, finance, and autonomous vehicles...",
            "relevance_score": 0.95
        },
        {
            "url": "https://example.com/article2",
            "title": "Python for Data Science",
            "snippet": "Python provides excellent libraries like pandas, numpy, and scikit-learn for data science...",
            "relevance_score": 0.87
        },
        {
            "url": "https://example.com/article3",
            "title": "Understanding Neural Networks",
            "snippet": "Neural networks are inspired by biological neurons and form the basis of deep learning...",
            "relevance_score": 0.82
        }
    ]


# Mock fixtures
@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing"""
    mock_client = Mock()
    mock_client.generate = AsyncMock(return_value=Mock(
        success=True,
        content="Mock LLM response",
        processing_time=1.0,
        token_count=50
    ))
    mock_client.batch_generate = AsyncMock(return_value=[
        Mock(success=True, content="Response 1"),
        Mock(success=True, content="Response 2")
    ])
    return mock_client


@pytest.fixture 
def mock_search_provider():
    """Mock search provider for testing"""
    mock_provider = Mock()
    mock_provider.search = AsyncMock(return_value=[
        {
            "url": "https://example.com/result1",
            "title": "Mock Search Result 1",
            "snippet": "This is a mock search result snippet",
            "relevance_score": 0.9
        }
    ])
    return mock_provider


@pytest.fixture
def mock_extraction_service():
    """Mock content extraction service"""
    mock_extractor = Mock()
    mock_extractor.extract_content = AsyncMock(return_value={
        "success": True,
        "content": "Mock extracted content",
        "title": "Mock Title",
        "metadata": {"length": 100}
    })
    return mock_extractor


# Async test helpers
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Configuration fixtures
@pytest.fixture
def test_config():
    """Test configuration for research system"""
    from ..pipeline.research_agent import ResearchConfig
    
    return ResearchConfig(
        max_search_results=5,         # Smaller for tests
        enable_verification=False,    # Disable for faster tests
        max_chunks_for_synthesis=3,   # Smaller batches
        enable_reranking=False,       # Simplify for tests
        max_concurrent_maps=2,        # Limit concurrency
        search_timeout=10,            # Shorter timeouts
        extract_timeout=10
    )


@pytest.fixture
def test_cache_config():
    """Test cache configuration"""
    from ..cache.http_cache import CacheConfig
    
    return CacheConfig(
        cache_dir="test_cache",
        cache_name="test_research_cache",
        expire_after=60,  # Short expiration for tests
        max_response_size=1024 * 1024,  # 1MB limit
        max_cache_size=100
    )


# Test utilities
class TestUtils:
    """Utility functions for tests"""
    
    @staticmethod
    def create_mock_chunk(content: str, url: str = "https://example.com/test", chunk_id: str = "test_chunk"):
        """Create mock document chunk"""
        from ..rank.bm25 import DocChunk
        return DocChunk(
            content=content,
            url=url,
            chunk_id=chunk_id,
            metadata={"test": True}
        )
    
    @staticmethod
    def create_mock_ranked_chunk(content: str, score: float = 0.8):
        """Create mock ranked chunk"""
        from ..rank.bm25 import RankedChunk
        chunk = TestUtils.create_mock_chunk(content)
        return RankedChunk(
            chunk=chunk,
            score=score,
            term_matches={"test": 1}
        )
    
    @staticmethod
    def create_mock_research_result(success: bool = True, response: str = "Mock response"):
        """Create mock research result"""
        from ..pipeline.research_agent import ResearchResult
        return ResearchResult(
            query="Test query",
            success=success,
            response=response,
            sources_count=3,
            confidence_score=0.8,
            total_duration=2.0,
            metadata={"test": True}
        )


@pytest.fixture
def test_utils():
    """Test utilities fixture"""
    return TestUtils


# Database fixtures (if needed)
@pytest.fixture(scope="session")
def test_database():
    """Test database setup and teardown"""
    # Would set up test database if needed
    yield "test_db"
    # Cleanup


# Performance testing fixtures
@pytest.fixture
def performance_timer():
    """Timer for performance tests"""
    import time
    
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        def start(self):
            self.start_time = time.time()
        
        def stop(self):
            self.end_time = time.time()
        
        @property
        def elapsed(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return 0
    
    return Timer()


# Parametrized test data
@pytest.fixture(params=[
    "What is machine learning?",
    "How does Python work?",
    "Compare TensorFlow and PyTorch",
    "Benefits of renewable energy"
])
def sample_queries(request):
    """Parametrized sample queries for testing"""
    return request.param


@pytest.fixture(params=[
    ["Python", "JavaScript"],
    ["Machine Learning", "Deep Learning", "AI"],
    ["Solar Power", "Wind Power", "Nuclear Power"]
])
def comparison_topics(request):
    """Parametrized comparison topics for testing"""
    return request.param


# Markers for different test categories
def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "performance: mark test as a performance test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "requires_network: mark test as requiring network access"
    )
    config.addinivalue_line(
        "markers", "requires_llm: mark test as requiring LLM access"
    )


# Skip conditions
skip_if_no_network = pytest.mark.skipif(
    not hasattr(pytest, "_network_available"),
    reason="Network not available"
)

skip_if_no_llm = pytest.mark.skipif(
    not hasattr(pytest, "_llm_available"),
    reason="LLM not available"
)


# Test environment setup
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment"""
    import os
    import tempfile
    
    # Create temporary directory for test files
    test_dir = tempfile.mkdtemp(prefix="research_test_")
    os.environ["RESEARCH_TEST_DIR"] = test_dir
    
    yield test_dir
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    if "RESEARCH_TEST_DIR" in os.environ:
        del os.environ["RESEARCH_TEST_DIR"]


# Logging setup for tests
@pytest.fixture(autouse=True)
def setup_test_logging():
    """Setup logging for tests"""
    import logging
    
    # Set log level to WARNING to reduce noise during tests
    logging.getLogger("research").setLevel(logging.WARNING)
    
    yield
    
    # Reset logging after test
    logging.getLogger("research").setLevel(logging.INFO)