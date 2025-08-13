"""Authentication utilities for FastAPI backend"""

import os
import asyncpg
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from typing import Optional, Dict

# Auth configuration
SECRET_KEY = os.getenv("JWT_SECRET", "key")
ALGORITHM = "HS256"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")

security = HTTPBearer(auto_error=False)

async def get_db_pool(request: Request):
    """Get database connection pool from app state"""
    return getattr(request.app.state, 'pg_pool', None)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    request: Request = None,
    pool = Depends(get_db_pool)
) -> Dict:
    """
    Verify JWT token and return current user info
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    try:
        # Decode JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Get user from database
        if pool:
            # Use connection pool (preferred)
            async with pool.acquire() as conn:
                user_record = await conn.fetchrow(
                    "SELECT id, username, email, avatar FROM users WHERE id = $1",
                    int(user_id)
                )
        else:
            # Fallback to direct connection
            conn = await asyncpg.connect(DATABASE_URL, timeout=10)
            try:
                user_record = await conn.fetchrow(
                    "SELECT id, username, email, avatar FROM users WHERE id = $1",
                    int(user_id)
                )
            finally:
                await conn.close()
        
        if not user_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return dict(user_record)
            
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )