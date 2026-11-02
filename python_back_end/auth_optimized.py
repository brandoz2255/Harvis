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
from jwt_secret import MCP_TOKEN_MINUTES, get_jwt_secret, is_shared  # noqa: F401

SECRET_KEY = get_jwt_secret()
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
            logger.debug(f"Cache hit for user {user_id}")
            return self._user_cache[user_id]
        
        # Cache miss or expired - fetch from database
        # logger.info(f"🔄 Cache miss for user {user_id}, fetching from DB")
        user_data = await self._fetch_user_from_db(user_id)
        
        if user_data:
            # Update cache
            self._user_cache[user_id] = user_data
            self._cache_timestamps[user_id] = current_time
            # logger.info(f"✅ Cached user {user_id}")
        
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

def mint_token(data: dict, expires_delta, iat: Optional[float] = None) -> str:
    """Sign a session token. ``iat`` is what server-side revocation compares (see
    ``revoked``); it is fractional so a sign-in right after a password change is
    never mistaken for one from before it. main.create_access_token calls this."""
    from datetime import datetime, timedelta
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    return jwt.encode({**data, "exp": expire, "iat": time.time() if iat is None else iat},
                      SECRET_KEY, algorithm=ALGORITHM)


# ─── Scoped sidecar tokens ──────────────────────────────────────────────────────
# A sidecar's --mcp-config carries a token an agent can read back out of its own
# process list, so it is minted with scope "mcp" and audience "harvis-mcp" and is
# good only at the four MCP endpoints. python-jose refuses any token carrying `aud`
# unless the caller names it, so a decoder that knows nothing of this rejects it too.
MCP_SCOPE = "mcp"
MCP_AUDIENCE = "harvis-mcp"
MCP_PATHS = frozenset({
    "/api/docs/mcp",
    "/api/cad/mcp",
    "/api/connectors/mcp",
    "/api/workspace/artifact-mcp",
})


def is_mcp_path(path: Optional[str]) -> bool:
    return bool(path) and path.rstrip("/") in MCP_PATHS


def decode_claims(token: str, path: Optional[str] = None) -> Dict:
    """Signature- and expiry-checked claims; raises JWTError for anything unusable here.

    A scoped (MCP) token is accepted only when ``path`` is an MCP endpoint. On a
    shared server a token with no ``iat`` predates revocation and is refused.
    """
    on_mcp = is_mcp_path(path)
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM],
                         audience=MCP_AUDIENCE if on_mcp else None)
    if "scope" in payload or "aud" in payload:
        if not on_mcp or payload.get("scope") != MCP_SCOPE:
            raise JWTError("scoped token used outside its endpoint")
    elif is_shared() and "iat" not in payload:
        raise JWTError("token has no issue time")
    return payload


def predates_revocation(token: str) -> bool:
    """Is this a sign-in this server signed (and has not expired) that carries no issue
    time? Only possible for a token minted before revocation existed, and a shared
    server refuses those outright (decode_claims). Separate from decode_claims so the
    request gate can tell "ended" from "garbage" and clear the browser's cookie."""
    if not token or not is_shared():
        return False
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM],
                             options={"verify_aud": False})
    except JWTError:
        return False
    return "iat" not in payload and "scope" not in payload and "aud" not in payload


def decode_token_fast(token: str, path: Optional[str] = None) -> Optional[Dict]:
    """Fast token decoding with caching. ``path`` is the request path: without it
    a scoped (MCP) token is refused."""
    current_time = time.time()
    on_mcp = is_mcp_path(path)

    # Check token cache first
    if token in TOKEN_CACHE:
        cached_data = TOKEN_CACHE[token]
        payload = cached_data['payload']
        # A cached payload is never trusted past its own expiry, whatever the cache window says.
        expiry = payload.get('exp')
        if (current_time - cached_data['timestamp'] < CACHE_EXPIRY
                and (expiry is None or float(expiry) > current_time)):
            if ('scope' in payload or 'aud' in payload) and not on_mcp:
                return None
            return payload
        # Remove expired token from cache
        TOKEN_CACHE.pop(token, None)

    # Decode token
    try:
        payload = decode_claims(token, path)

        # Cache the decoded payload
        TOKEN_CACHE[token] = {
            'payload': payload,
            'timestamp': current_time
        }

        # Cleanup old tokens (keep cache size manageable)
        if len(TOKEN_CACHE) > 1000:
            cleanup_expired_tokens()

        return payload

    except JWTError as e:
        logger.error(f"❌ JWT decode error: {e}")
        return None


# ─── Server-side revocation ─────────────────────────────────────────────────────
# users.tokens_valid_after (migration 027) is the moment before which no sign-in
# counts. Password changes set it (a trigger), and so do blocking an account and
# "sign out everywhere". Every token carries the time it was minted (`iat`), so
# the check needs nothing from whoever minted it. Read at most every _CUTOFF_TTL
# seconds per user; a change made by this process applies at once.
_CUTOFF_TTL = 10.0
_cutoffs: Dict[int, tuple] = {}


async def _read_cutoff(conn, user_id: int) -> Optional[float]:
    """Epoch seconds of the cutoff, or None when there is none (or the column is not there yet)."""
    try:
        return await conn.fetchval(
            "SELECT EXTRACT(EPOCH FROM tokens_valid_after)::float8 FROM users WHERE id = $1", int(user_id))
    except asyncpg.UndefinedColumnError:
        return None


async def session_cutoff(pool, user_id: int) -> Optional[float]:
    if pool is None:
        return None
    hit = _cutoffs.get(int(user_id))
    now = time.monotonic()
    if hit and now - hit[1] < _CUTOFF_TTL:
        return hit[0]
    async with pool.acquire() as conn:
        cutoff = await _read_cutoff(conn, user_id)
    if len(_cutoffs) > 5000:
        _cutoffs.clear()
    _cutoffs[int(user_id)] = (cutoff, now)
    return cutoff


def revoked(payload: Dict, cutoff: Optional[float]) -> bool:
    """Was this token minted before the account's cutoff? A token with no issue time
    predates revocation, so any cutoff at all ends it."""
    if cutoff is None:
        return False
    try:
        return float(payload["iat"]) < cutoff
    except (KeyError, TypeError, ValueError):
        return True


def note_cutoff(user_id: int, cutoff: Optional[float]) -> None:
    """Make a cutoff this process just caused apply at once, not after the cache window."""
    _cutoffs[int(user_id)] = (cutoff, time.monotonic())


async def revoke_sessions(conn, user_id: int) -> None:
    """Sign this account out everywhere: every token minted so far stops working."""
    cutoff = await conn.fetchval(
        "UPDATE users SET tokens_valid_after = clock_timestamp() WHERE id = $1 "
        "RETURNING EXTRACT(EPOCH FROM tokens_valid_after)::float8", int(user_id))
    note_cutoff(user_id, cutoff)


async def verified_user_id(token: str, pool, path: Optional[str] = None) -> Optional[int]:
    """The account a sign-in stands for, or None: bad signature, expired, a scoped
    token off its endpoint, no issue time on a shared server, or ended server-side
    (password changed, signed out everywhere, blocked). For the routes that read
    the JWT themselves instead of using a shared auth dependency."""
    try:
        payload = decode_claims(token, path)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        return None
    if revoked(payload, await session_cutoff(pool or auth_optimizer.db_pool, user_id)):
        return None
    return user_id


def cleanup_expired_tokens():
    """Remove expired tokens from cache"""
    current_time = time.time()
    expired_tokens = [
        token for token, data in TOKEN_CACHE.items()
        if current_time - data['timestamp'] >= CACHE_EXPIRY
    ]
    
    for token in expired_tokens:
        del TOKEN_CACHE[token]
    
    # logger.info(f"🧹 Cleaned up {len(expired_tokens)} expired tokens")

async def get_db_pool(request: Request) -> Optional[asyncpg.Pool]:
    """Get database connection pool from app state"""
    pool = getattr(request.app.state, 'pg_pool', None)
    if pool and not auth_optimizer.db_pool:
        auth_optimizer.db_pool = pool
    return pool

async def get_current_user_optimized(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    pool = Depends(get_db_pool)
) -> Dict:
    """
    Optimized JWT token verification with caching and connection pooling
    Accepts JWT from Authorization header or access_token cookie
    """
    token = None
    
    # Try Authorization header first
    if credentials:
        token = credentials.credentials
    
    # Fallback to cookie if header not present
    if not token and request:
        token = request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization missing: provide JWT in Authorization header or access_token cookie",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Fast token decoding with cache
    payload = decode_token_fast(token, request.url.path)
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
    
    if revoked(payload, await session_cutoff(pool or auth_optimizer.db_pool, user_id)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session ended: sign in again",
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