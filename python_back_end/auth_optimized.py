"""
Optimized authentication module with connection pooling and caching
"""

import os
import time
import asyncio
from typing import Dict, Optional
from functools import lru_cache
import asyncpg
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import logging

logger = logging.getLogger(__name__)

# Auth configuration
SECRET_KEY = os.getenv("JWT_SECRET", "key")
ALGORITHM = "HS256"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")

security = HTTPBearer(auto_error=False)

# In-memory token cache with expiration (5 minutes)
TOKEN_CACHE: Dict[str, Dict] = {}
CACHE_EXPIRY = 300  # 5 minutes

class AuthOptimizer:
    """Optimized authentication with caching and connection pooling"""
    
    def __init__(self, db_pool: Optional[asyncpg.Pool] = None):
        self.db_pool = db_pool
        self._user_cache: Dict[int, Dict] = {}
        self._cache_timestamps: Dict[int, float] = {}
        self.cache_ttl = 300  # 5 minutes
    
    async def get_user_from_cache_or_db(self, user_id: int) -> Optional[Dict]:
        """Get user from cache first, then database if not found or expired"""
        current_time = time.time()
        
        # Check cache first
        if (user_id in self._user_cache and 
            user_id in self._cache_timestamps and 
            current_time - self._cache_timestamps[user_id] < self.cache_ttl):
            logger.info(f"🚀 Cache hit for user {user_id}")
            return self._user_cache[user_id]
        
        # Cache miss or expired - fetch from database
        logger.info(f"🔄 Cache miss for user {user_id}, fetching from DB")
        user_data = await self._fetch_user_from_db(user_id)
        
        if user_data:
            # Update cache
            self._user_cache[user_id] = user_data
            self._cache_timestamps[user_id] = current_time
            logger.info(f"✅ Cached user {user_id}")
        
        return user_data
    
    async def _fetch_user_from_db(self, user_id: int) -> Optional[Dict]:
        """Fetch user from database with optimized connection handling"""
        query = "SELECT id, username, email, avatar FROM users WHERE id = $1"
        
        if self.db_pool:
            # Use connection pool (much faster)
            try:
                async with self.db_pool.acquire() as conn:
                    user_record = await conn.fetchrow(query, user_id)
                    return dict(user_record) if user_record else None
            except Exception as e:
                logger.error(f"❌ Pool connection error for user {user_id}: {e}")
                return None
        else:
            # Fallback to direct connection with timeout
            try:
                conn = await asyncpg.connect(DATABASE_URL, timeout=5)
                try:
                    user_record = await conn.fetchrow(query, user_id)
                    return dict(user_record) if user_record else None
                finally:
                    await conn.close()
            except Exception as e:
                logger.error(f"❌ Direct connection error for user {user_id}: {e}")
                return None
    
    def invalidate_user_cache(self, user_id: int):
        """Invalidate cached user data"""
        self._user_cache.pop(user_id, None)
        self._cache_timestamps.pop(user_id, None)
        logger.info(f"🗑️ Invalidated cache for user {user_id}")
    
    def clear_cache(self):
        """Clear all cached data"""
        self._user_cache.clear()
        self._cache_timestamps.clear()
        TOKEN_CACHE.clear()
        logger.info("🧹 Cleared all auth caches")

# Global auth optimizer instance
auth_optimizer = AuthOptimizer()

def decode_token_fast(token: str) -> Optional[Dict]:
    """Fast token decoding with caching"""
    current_time = time.time()
    
    # Check token cache first
    if token in TOKEN_CACHE:
        cached_data = TOKEN_CACHE[token]
        if current_time - cached_data['timestamp'] < CACHE_EXPIRY:
            logger.info("🚀 Token cache hit")
            return cached_data['payload']
        else:
            # Remove expired token from cache
            del TOKEN_CACHE[token]
    
    # Decode token
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Cache the decoded payload
        TOKEN_CACHE[token] = {
            'payload': payload,
            'timestamp': current_time
        }
        
        # Cleanup old tokens (keep cache size manageable)
        if len(TOKEN_CACHE) > 1000:
            cleanup_expired_tokens()
        
        logger.info("✅ Token decoded and cached")
        return payload
        
    except JWTError as e:
        logger.error(f"❌ JWT decode error: {e}")
        return None

def cleanup_expired_tokens():
    """Remove expired tokens from cache"""
    current_time = time.time()
    expired_tokens = [
        token for token, data in TOKEN_CACHE.items()
        if current_time - data['timestamp'] >= CACHE_EXPIRY
    ]
    
    for token in expired_tokens:
        del TOKEN_CACHE[token]
    
    logger.info(f"🧹 Cleaned up {len(expired_tokens)} expired tokens")

async def get_db_pool(request: Request) -> Optional[asyncpg.Pool]:
    """Get database connection pool from app state"""
    pool = getattr(request.app.state, 'pg_pool', None)
    if pool and not auth_optimizer.db_pool:
        auth_optimizer.db_pool = pool
    return pool

async def get_current_user_optimized(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    request: Request = None,
    pool = Depends(get_db_pool)
) -> Dict:
    """
    Optimized JWT token verification with caching and connection pooling
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    # Fast token decoding with cache
    payload = decode_token_fast(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user ID",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        user_id = int(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: invalid user ID",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user with optimized caching
    user_data = await auth_optimizer.get_user_from_cache_or_db(user_id)
    
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user_data

# Performance monitoring
auth_stats = {
    'token_cache_hits': 0,
    'token_cache_misses': 0,
    'user_cache_hits': 0,
    'user_cache_misses': 0,
    'db_queries': 0
}

def get_auth_stats() -> Dict:
    """Get authentication performance statistics"""
    return {
        **auth_stats,
        'token_cache_size': len(TOKEN_CACHE),
        'user_cache_size': len(auth_optimizer._user_cache)
    }