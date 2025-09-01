"""
HTTP caching implementation using requests-cache with intelligent policies.

Provides smart caching for web content, search results, and API responses
with configurable TTL and cache invalidation strategies.
"""

import os
import time
import hashlib
import logging
from typing import Dict, Optional, Any, List, Union, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json

try:
    import requests_cache
    REQUESTS_CACHE_AVAILABLE = True
except ImportError:
    REQUESTS_CACHE_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    """Configuration for HTTP caching behavior"""
    cache_dir: str = "cache"
    cache_name: str = "research_cache"
    expire_after: int = 3600  # Default 1 hour
    
    # URL pattern specific expiration (in seconds)
    url_patterns: Dict[str, int] = field(default_factory=lambda: {
        "duckduckgo.com": 1800,     # 30 minutes for search results
        "wikipedia.org": 86400,     # 24 hours for Wikipedia
        "arxiv.org": 86400,         # 24 hours for papers
        "github.com": 3600,         # 1 hour for GitHub
        "stackoverflow.com": 7200,  # 2 hours for StackOverflow
        "reddit.com": 900,          # 15 minutes for Reddit
        "news": 1800,               # 30 minutes for news sites
    })
    
    # Content type specific expiration
    content_types: Dict[str, int] = field(default_factory=lambda: {
        "text/html": 3600,
        "application/json": 1800,
        "application/xml": 3600,
        "text/xml": 3600,
        "application/pdf": 86400,  # PDFs rarely change
        "text/plain": 7200,
    })
    
    # Size limits
    max_response_size: int = 10 * 1024 * 1024  # 10MB
    max_cache_size: int = 1000  # Maximum entries
    
    # Cache behaviors  
    cache_control_override: bool = False  # Ignore server cache headers
    stale_if_error: int = 86400  # Use stale data if request fails (24h)
    
    def get_expiration(self, url: str, content_type: Optional[str] = None) -> int:
        """Get expiration time for a specific URL/content type"""
        
        # Check URL patterns
        for pattern, ttl in self.url_patterns.items():
            if pattern in url.lower():
                return ttl
        
        # Check content type
        if content_type:
            for ct_pattern, ttl in self.content_types.items():
                if ct_pattern in content_type.lower():
                    return ttl
        
        # Return default
        return self.expire_after


class HTTPCache:
    """
    Intelligent HTTP cache for research system.
    
    Provides automatic caching with smart TTL policies based on
    content type and URL patterns. Integrates with requests-cache.
    """
    
    def __init__(self, config: Optional[CacheConfig] = None):
        self.config = config or CacheConfig()
        self._session = None
        self._cache_stats = {
            "hits": 0,
            "misses": 0, 
            "errors": 0,
            "size_limited": 0,
            "expired": 0
        }
        
        # Ensure cache directory exists
        cache_path = Path(self.config.cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize cache
        self._setup_cache()
    
    def _setup_cache(self):
        """Setup requests-cache session"""
        if not REQUESTS_CACHE_AVAILABLE:
            logger.warning("requests-cache not available, using non-cached requests")
            import requests
            self._session = requests.Session()
            return
        
        cache_file = os.path.join(self.config.cache_dir, self.config.cache_name)
        
        # Create cached session with SQLite backend
        self._session = requests_cache.CachedSession(
            cache_name=cache_file,
            backend='sqlite',
            expire_after=None,  # We'll handle expiration manually
            stale_if_error=self.config.stale_if_error,
            cache_control=not self.config.cache_control_override
        )
        
        logger.info(f"HTTP cache initialized: {cache_file}")
    
    def _should_cache_response(self, response) -> bool:
        """Determine if response should be cached"""
        # Check response status
        if not (200 <= response.status_code < 300):
            return False
        
        # Check response size
        content_length = response.headers.get('content-length')
        if content_length and int(content_length) > self.config.max_response_size:
            self._cache_stats["size_limited"] += 1
            return False
        
        # Check actual content size
        if hasattr(response, 'content') and len(response.content) > self.config.max_response_size:
            self._cache_stats["size_limited"] += 1
            return False
        
        return True
    
    def _get_cache_key(self, url: str, params: Optional[Dict] = None) -> str:
        """Generate cache key for URL and parameters"""
        key_data = url
        if params:
            # Sort params for consistent hashing
            sorted_params = json.dumps(params, sort_keys=True)
            key_data += sorted_params
        
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(
        self,
        url: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        timeout: int = 30,
        **kwargs
    ) -> Optional[Any]:
        """
        Make cached HTTP GET request.
        
        Args:
            url: URL to fetch
            params: Query parameters
            headers: Request headers
            timeout: Request timeout
            **kwargs: Additional requests arguments
            
        Returns:
            Response object or None if failed
        """
        try:
            # Calculate dynamic expiration
            expire_after = self.config.get_expiration(url)
            
            # Make request
            start_time = time.time()
            
            if REQUESTS_CACHE_AVAILABLE:
                # Use requests-cache session
                response = self._session.get(
                    url=url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                    expire_after=expire_after,
                    **kwargs
                )
                
                # Track cache statistics
                if hasattr(response, 'from_cache') and response.from_cache:
                    self._cache_stats["hits"] += 1
                else:
                    self._cache_stats["misses"] += 1
            else:
                # Fallback to regular requests
                import requests
                response = requests.get(
                    url=url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                    **kwargs
                )
                self._cache_stats["misses"] += 1
            
            request_time = time.time() - start_time
            
            # Validate response
            if not self._should_cache_response(response):
                logger.debug(f"Response not cached: {url} (status: {response.status_code})")
            
            logger.debug(f"HTTP request completed: {url} ({request_time:.2f}s, cached: {getattr(response, 'from_cache', False)})")
            
            return response
            
        except Exception as e:
            self._cache_stats["errors"] += 1
            logger.error(f"HTTP request failed: {url} - {str(e)}")
            return None
    
    def post(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        timeout: int = 30,
        cache_key: Optional[str] = None,
        **kwargs
    ) -> Optional[Any]:
        """
        Make cached HTTP POST request.
        
        POST requests are typically not cached, but this allows
        caching for specific cases (like API endpoints).
        """
        try:
            # For POST requests, we need explicit cache keys
            if cache_key and REQUESTS_CACHE_AVAILABLE:
                expire_after = self.config.get_expiration(url)
                response = self._session.post(
                    url=url,
                    data=data,
                    json=json,
                    headers=headers,
                    timeout=timeout,
                    expire_after=expire_after,
                    **kwargs
                )
                
                if hasattr(response, 'from_cache') and response.from_cache:
                    self._cache_stats["hits"] += 1
                else:
                    self._cache_stats["misses"] += 1
            else:
                # Non-cached POST
                import requests
                session = self._session if not REQUESTS_CACHE_AVAILABLE else requests.Session()
                response = session.post(
                    url=url,
                    data=data,
                    json=json,
                    headers=headers,
                    timeout=timeout,
                    **kwargs
                )
                self._cache_stats["misses"] += 1
            
            return response
            
        except Exception as e:
            self._cache_stats["errors"] += 1
            logger.error(f"HTTP POST failed: {url} - {str(e)}")
            return None
    
    def clear_expired(self):
        """Clear expired cache entries"""
        if not REQUESTS_CACHE_AVAILABLE or not hasattr(self._session.cache, 'delete_expired'):
            logger.warning("Cache expiration cleanup not available")
            return
        
        try:
            expired_count = self._session.cache.delete_expired()
            self._cache_stats["expired"] += expired_count
            logger.info(f"Cleared {expired_count} expired cache entries")
        except Exception as e:
            logger.error(f"Cache cleanup failed: {str(e)}")
    
    def clear_cache(self):
        """Clear all cache entries"""
        if not REQUESTS_CACHE_AVAILABLE:
            return
        
        try:
            self._session.cache.clear()
            logger.info("Cache cleared")
        except Exception as e:
            logger.error(f"Cache clear failed: {str(e)}")
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache information and statistics"""
        info = {
            "stats": dict(self._cache_stats),
            "config": {
                "cache_dir": self.config.cache_dir,
                "default_ttl": self.config.expire_after,
                "max_size": self.config.max_response_size
            }
        }
        
        if REQUESTS_CACHE_AVAILABLE and hasattr(self._session, 'cache'):
            try:
                # Get cache size info if available
                if hasattr(self._session.cache, 'urls'):
                    info["cache_size"] = len(self._session.cache.urls)
                
                # Calculate hit rate
                total_requests = self._cache_stats["hits"] + self._cache_stats["misses"]
                if total_requests > 0:
                    info["hit_rate"] = self._cache_stats["hits"] / total_requests
                else:
                    info["hit_rate"] = 0.0
                    
            except Exception as e:
                logger.debug(f"Could not get cache info: {str(e)}")
        
        return info
    
    def warm_cache(self, urls: List[str], headers: Optional[Dict] = None):
        """Pre-warm cache with list of URLs"""
        logger.info(f"Warming cache with {len(urls)} URLs")
        
        for url in urls:
            try:
                self.get(url, headers=headers)
                time.sleep(0.1)  # Be respectful
            except Exception as e:
                logger.debug(f"Cache warm failed for {url}: {str(e)}")
    
    def close(self):
        """Close cache session and cleanup"""
        if self._session:
            self._session.close()
        
        # Final cleanup
        self.clear_expired()


# Global cache instance
_global_cache = None


def setup_cache(config: Optional[CacheConfig] = None) -> HTTPCache:
    """Setup global cache instance"""
    global _global_cache
    _global_cache = HTTPCache(config)
    return _global_cache


def get_cache() -> HTTPCache:
    """Get global cache instance, creating if needed"""
    global _global_cache
    if _global_cache is None:
        _global_cache = HTTPCache()
    return _global_cache


def cache_request(
    url: str,
    method: str = "GET",
    params: Optional[Dict] = None,
    headers: Optional[Dict] = None,
    **kwargs
) -> Optional[Any]:
    """
    Convenience function for cached requests using global cache.
    
    Args:
        url: URL to request
        method: HTTP method (GET or POST)
        params: Query parameters
        headers: Request headers
        **kwargs: Additional request arguments
        
    Returns:
        Response object or None if failed
    """
    cache = get_cache()
    
    if method.upper() == "GET":
        return cache.get(url, params=params, headers=headers, **kwargs)
    elif method.upper() == "POST":
        return cache.post(url, headers=headers, **kwargs)
    else:
        logger.error(f"Unsupported method for caching: {method}")
        return None


# Context manager for temporary cache configuration
class TempCacheConfig:
    """Temporary cache configuration context manager"""
    
    def __init__(self, **config_overrides):
        self.overrides = config_overrides
        self.original_config = None
        self.temp_cache = None
    
    def __enter__(self) -> HTTPCache:
        # Create temporary config
        base_config = CacheConfig()
        
        # Apply overrides
        for key, value in self.overrides.items():
            if hasattr(base_config, key):
                setattr(base_config, key, value)
        
        # Create temporary cache
        self.temp_cache = HTTPCache(base_config)
        return self.temp_cache
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.temp_cache:
            self.temp_cache.close()


# Convenience functions for common use cases
def cache_search_results(search_func: Callable, query: str, **kwargs) -> Any:
    """Cache search results with short TTL"""
    with TempCacheConfig(expire_after=900) as cache:  # 15 minutes
        # This would integrate with your search functions
        return search_func(query, **kwargs)


def cache_web_content(url: str, long_cache: bool = False) -> Optional[Any]:
    """Cache web content with appropriate TTL"""
    ttl = 86400 if long_cache else 3600  # 24h or 1h
    
    with TempCacheConfig(expire_after=ttl) as cache:
        return cache.get(url)


def get_cache_stats() -> Dict[str, Any]:
    """Get global cache statistics"""
    return get_cache().get_cache_info()