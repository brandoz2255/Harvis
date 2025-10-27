# python_back_end/research/core/errors.py

class ResearchError(Exception):
    """Base class for all research errors."""

class SearchError(ResearchError):
    """Raised when a search operation fails."""

class ProviderError(ResearchError):
    """Raised when a search provider fails or returns invalid data."""

class ExtractionError(ResearchError):
    """Raised when content extraction from a URL fails."""

class RankingError(ResearchError):
    """Raised when reranking fails."""

class LLMError(ResearchError):
    """Raised when the LLM query or analysis fails."""