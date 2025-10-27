"""
HTTP caching module for research system.

Provides intelligent caching for web content, search results, and extracted text
to improve performance and reduce redundant network requests.
"""

from .http_cache import HTTPCache, CacheConfig, cache_request, setup_cache

__all__ = [
    "HTTPCache",
    "CacheConfig", 
    "cache_request",
    "setup_cache",
]