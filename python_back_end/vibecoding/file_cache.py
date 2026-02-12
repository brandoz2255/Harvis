"""File Tree Caching Module

Provides in-memory caching for file tree operations to improve performance.
Cache entries expire after 30 seconds and are invalidated on file operations.
"""

import time
import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class FileTreeCache:
    """In-memory cache for file tree structures
    
    Features:
    - 30-second TTL (time-to-live) for cache entries
    - Automatic invalidation on file operations
    - Session-scoped caching
    - Memory-efficient with automatic cleanup
    """
    
    def __init__(self, ttl_seconds: int = 30):
        """Initialize cache
        
        Args:
            ttl_seconds: Time-to-live for cache entries (default: 30)
        """
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._last_cleanup = time.time()
        self._cleanup_interval = 60  # Cleanup every 60 seconds
        
        logger.info(f"✅ FileTreeCache initialized (TTL: {ttl_seconds}s)")
    
    def _make_key(self, session_id: str, path: str) -> str:
        """Create cache key from session and path"""
        return f"{session_id}:{path}"
    
    def get(self, session_id: str, path: str) -> Optional[Dict[str, Any]]:
        """Get cached file tree if available and not expired
        
        Args:
            session_id: Session identifier
            path: File path
            
        Returns:
            Cached file tree or None if not found/expired
        """
        key = self._make_key(session_id, path)
        
        # Check if entry exists
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        
        # Check if expired
        age = time.time() - entry['timestamp']
        if age > self.ttl_seconds:
            logger.debug(f"🕐 Cache expired for {key} (age: {age:.1f}s)")
            del self._cache[key]
            return None
        
        logger.debug(f"✅ Cache hit for {key} (age: {age:.1f}s)")
        entry['hits'] += 1
        return entry['data']
    
    def set(self, session_id: str, path: str, data: Dict[str, Any]) -> None:
        """Store file tree in cache
        
        Args:
            session_id: Session identifier
            path: File path
            data: File tree data to cache
        """
        key = self._make_key(session_id, path)
        
        self._cache[key] = {
            'data': data,
            'timestamp': time.time(),
            'hits': 0
        }
        
        logger.debug(f"💾 Cached file tree for {key}")
        
        # Periodic cleanup
        self._maybe_cleanup()
    
    def invalidate(self, session_id: str, path: Optional[str] = None) -> int:
        """Invalidate cache entries
        
        Args:
            session_id: Session identifier
            path: Specific path to invalidate, or None for entire session
            
        Returns:
            Number of entries invalidated
        """
        if path:
            # Invalidate specific path and parent directories
            key = self._make_key(session_id, path)
            count = 0
            
            # Invalidate the path itself
            if key in self._cache:
                del self._cache[key]
                count += 1
            
            # Invalidate parent directories (they need to show updated children)
            parts = path.rstrip('/').split('/')
            for i in range(len(parts)):
                parent_path = '/'.join(parts[:i+1]) or '/'
                parent_key = self._make_key(session_id, parent_path)
                if parent_key in self._cache:
                    del self._cache[parent_key]
                    count += 1
            
            if count > 0:
                logger.debug(f"🗑️ Invalidated {count} cache entries for {session_id}:{path}")
            
            return count
        else:
            # Invalidate entire session
            keys_to_delete = [k for k in self._cache.keys() if k.startswith(f"{session_id}:")]
            for key in keys_to_delete:
                del self._cache[key]
            
            if keys_to_delete:
                logger.debug(f"🗑️ Invalidated {len(keys_to_delete)} cache entries for session {session_id}")
            
            return len(keys_to_delete)
    
    def _maybe_cleanup(self) -> None:
        """Cleanup expired entries periodically"""
        now = time.time()
        
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        # Find expired entries
        expired_keys = []
        for key, entry in self._cache.items():
            age = now - entry['timestamp']
            if age > self.ttl_seconds:
                expired_keys.append(key)
        
        # Remove expired entries
        for key in expired_keys:
            del self._cache[key]
        
        if expired_keys:
            logger.debug(f"🧹 Cleaned up {len(expired_keys)} expired cache entries")
        
        self._last_cleanup = now
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics
        
        Returns:
            Dictionary with cache stats
        """
        total_entries = len(self._cache)
        total_hits = sum(entry['hits'] for entry in self._cache.values())
        
        # Calculate average age
        now = time.time()
        ages = [now - entry['timestamp'] for entry in self._cache.values()]
        avg_age = sum(ages) / len(ages) if ages else 0
        
        return {
            'total_entries': total_entries,
            'total_hits': total_hits,
            'avg_age_seconds': avg_age,
            'ttl_seconds': self.ttl_seconds
        }
    
    def clear(self) -> int:
        """Clear all cache entries
        
        Returns:
            Number of entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        
        if count > 0:
            logger.info(f"🗑️ Cleared {count} cache entries")
        
        return count


# Global cache instance
_file_tree_cache = FileTreeCache(ttl_seconds=30)


def get_file_tree_cache() -> FileTreeCache:
    """Get the global file tree cache instance"""
    return _file_tree_cache
