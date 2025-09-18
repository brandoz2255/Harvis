"""
Research module for Jarvis AI
Provides comprehensive research capabilities with advanced pipeline architecture
"""

# Legacy components (backward compatibility)
from .web_search import WebSearchAgent
from .research_agent import ResearchAgent

# Try to import advanced components - they might not exist in all environments
try:
    # Core components
    from .core.types import Hit, DocChunk, Quote, ResearchArtifacts
    from .core.errors import ResearchError, SearchError, ExtractionError
    from .core.utils import canonicalize_url, compute_hash

    # Configuration
    from .config.settings import Settings as ResearchSettings
    from .config.logging import configure_logging as setup_research_logging

    # Search and extraction
    from .search.aggregator import SearchAggregator
    from .search.scoring import score_hit as score_results
    from .extract.router import ExtractionRouter

    # Ranking and synthesis
    from .rank.bm25 import BM25Ranker, quick_bm25_rank
    from .rank.rerank import ReRanker, quick_rerank
    from .synth.map_reduce import MapReduceProcessor, quick_map_reduce
    from .synth.verify import QuoteVerifier, quick_verify
    from .synth.render import MarkdownRenderer, create_source_info

    # LLM and caching
    from .llm.ollama_client import OllamaClient, quick_generate
    from .llm.model_policy import get_model_for_task, TaskType
    from .cache.http_cache import get_cache, setup_cache

    # Main pipeline
    from .pipeline.research_agent import ResearchAgent as AdvancedResearchAgent, ResearchConfig, quick_research
    from .pipeline.fact_check import FactChecker, quick_fact_check
    from .pipeline.compare import ComparativeAnalyzer, quick_compare

    # MCP integration
    from .mcp.tool import StandaloneResearchTool, create_research_server
    
    # Advanced components available
    ADVANCED_AVAILABLE = True

except ImportError as e:
    # Advanced components not available - use legacy only
    ADVANCED_AVAILABLE = False
    
    # Provide fallback functions
    def setup_research_logging():
        import logging
        logging.basicConfig(level=logging.INFO)
    
    def create_source_info(url, title):
        return {"url": url, "title": title}

# Export list depends on availability
if ADVANCED_AVAILABLE:
    __all__ = [
        # Legacy (backward compatibility)
        "WebSearchAgent", 
        "ResearchAgent",
        
        # Core types
        "Hit", 
        "DocChunk", 
        "Quote", 
        "ResearchArtifacts",
        "ResearchError", 
        "SearchError", 
        "ExtractionError",
        
        # Main pipeline components
        "AdvancedResearchAgent",
        "ResearchConfig", 
        "FactChecker",
        "ComparativeAnalyzer",
        "StandaloneResearchTool",
        
        # Convenience functions
        "quick_research",
        "quick_fact_check", 
        "quick_compare",
        "quick_bm25_rank",
        "quick_rerank",
        "quick_map_reduce",
        "quick_verify",
        "quick_generate",
        
        # Utilities
        "get_cache",
        "setup_cache",
        "get_model_for_task",
        "TaskType",
        "create_source_info",
        "setup_research_logging"
    ]
else:
    __all__ = [
        "WebSearchAgent", 
        "ResearchAgent",
        "create_source_info",
        "setup_research_logging"
    ]
