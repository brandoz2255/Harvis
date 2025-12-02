"""
User Preferences Module for VibeCode IDE

This module handles user preference storage and retrieval for theme, layout,
and other personalization settings.
"""

import asyncpg
from typing import Dict, Optional
from datetime import datetime
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)

# Create router for user preferences endpoints
router = APIRouter(prefix="/api/user", tags=["user-preferences"])


class UserPreferences:
    """Data class for user preferences"""
    
    def __init__(
        self,
        user_id: int,
        theme: str = "dark",
        left_panel_width: int = 280,
        right_panel_width: int = 384,
        terminal_height: int = 200,
        default_model: str = "mistral",
        font_size: int = 14,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.user_id = user_id
        self.theme = theme
        self.left_panel_width = left_panel_width
        self.right_panel_width = right_panel_width
        self.terminal_height = terminal_height
        self.default_model = default_model
        self.font_size = font_size
        self.created_at = created_at
        self.updated_at = updated_at
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses"""
        return {
            "user_id": self.user_id,
            "theme": self.theme,
            "left_panel_width": self.left_panel_width,
            "right_panel_width": self.right_panel_width,
            "terminal_height": self.terminal_height,
            "default_model": self.default_model,
            "font_size": self.font_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


async def get_user_prefs(pool: asyncpg.Pool, user_id: int) -> UserPreferences:
    """
    Get user preferences from database.
    Creates default preferences if none exist.
    
    Args:
        pool: Database connection pool
        user_id: User ID to fetch preferences for
        
    Returns:
        UserPreferences object with user's preferences
    """
    async with pool.acquire() as conn:
        # Try to fetch existing preferences
        row = await conn.fetchrow(
            """
            SELECT user_id, theme, left_panel_width, right_panel_width,
                   terminal_height, default_model, font_size,
                   created_at, updated_at
            FROM user_prefs
            WHERE user_id = $1
            """,
            user_id
        )
        
        if row:
            # Return existing preferences
            return UserPreferences(
                user_id=row['user_id'],
                theme=row['theme'],
                left_panel_width=row['left_panel_width'],
                right_panel_width=row['right_panel_width'],
                terminal_height=row['terminal_height'],
                default_model=row['default_model'],
                font_size=row['font_size'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
        else:
            # Create default preferences
            logger.info(f"Creating default preferences for user {user_id}")
            row = await conn.fetchrow(
                """
                INSERT INTO user_prefs (user_id)
                VALUES ($1)
                RETURNING user_id, theme, left_panel_width, right_panel_width,
                          terminal_height, default_model, font_size,
                          created_at, updated_at
                """,
                user_id
            )
            
            return UserPreferences(
                user_id=row['user_id'],
                theme=row['theme'],
                left_panel_width=row['left_panel_width'],
                right_panel_width=row['right_panel_width'],
                terminal_height=row['terminal_height'],
                default_model=row['default_model'],
                font_size=row['font_size'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )


async def save_user_prefs(
    pool: asyncpg.Pool,
    user_id: int,
    theme: Optional[str] = None,
    left_panel_width: Optional[int] = None,
    right_panel_width: Optional[int] = None,
    terminal_height: Optional[int] = None,
    default_model: Optional[str] = None,
    font_size: Optional[int] = None
) -> UserPreferences:
    """
    Save user preferences to database.
    Only updates provided fields (partial updates supported).
    
    Args:
        pool: Database connection pool
        user_id: User ID to save preferences for
        theme: UI theme (light/dark)
        left_panel_width: Width of left panel in pixels
        right_panel_width: Width of right panel in pixels
        terminal_height: Height of terminal in pixels
        default_model: Default AI model
        font_size: Font size for editor and terminal
        
    Returns:
        Updated UserPreferences object
    """
    async with pool.acquire() as conn:
        # Build dynamic update query for only provided fields
        update_fields = []
        params = [user_id]
        param_idx = 2
        
        if theme is not None:
            update_fields.append(f"theme = ${param_idx}")
            params.append(theme)
            param_idx += 1
        
        if left_panel_width is not None:
            update_fields.append(f"left_panel_width = ${param_idx}")
            params.append(left_panel_width)
            param_idx += 1
        
        if right_panel_width is not None:
            update_fields.append(f"right_panel_width = ${param_idx}")
            params.append(right_panel_width)
            param_idx += 1
        
        if terminal_height is not None:
            update_fields.append(f"terminal_height = ${param_idx}")
            params.append(terminal_height)
            param_idx += 1
        
        if default_model is not None:
            update_fields.append(f"default_model = ${param_idx}")
            params.append(default_model)
            param_idx += 1
        
        if font_size is not None:
            update_fields.append(f"font_size = ${param_idx}")
            params.append(font_size)
            param_idx += 1
        
        if not update_fields:
            # No fields to update, just return current preferences
            return await get_user_prefs(pool, user_id)
        
        # Check if preferences exist
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM user_prefs WHERE user_id = $1)",
            user_id
        )
        
        if exists:
            # Update existing preferences
            update_query = f"""
                UPDATE user_prefs
                SET {', '.join(update_fields)}
                WHERE user_id = $1
                RETURNING user_id, theme, left_panel_width, right_panel_width,
                          terminal_height, default_model, font_size,
                          created_at, updated_at
            """
            row = await conn.fetchrow(update_query, *params)
        else:
            # Insert new preferences with provided values
            insert_fields = ["user_id"]
            insert_values = ["$1"]
            insert_params = [user_id]
            param_idx = 2
            
            if theme is not None:
                insert_fields.append("theme")
                insert_values.append(f"${param_idx}")
                insert_params.append(theme)
                param_idx += 1
            
            if left_panel_width is not None:
                insert_fields.append("left_panel_width")
                insert_values.append(f"${param_idx}")
                insert_params.append(left_panel_width)
                param_idx += 1
            
            if right_panel_width is not None:
                insert_fields.append("right_panel_width")
                insert_values.append(f"${param_idx}")
                insert_params.append(right_panel_width)
                param_idx += 1
            
            if terminal_height is not None:
                insert_fields.append("terminal_height")
                insert_values.append(f"${param_idx}")
                insert_params.append(terminal_height)
                param_idx += 1
            
            if default_model is not None:
                insert_fields.append("default_model")
                insert_values.append(f"${param_idx}")
                insert_params.append(default_model)
                param_idx += 1
            
            if font_size is not None:
                insert_fields.append("font_size")
                insert_values.append(f"${param_idx}")
                insert_params.append(font_size)
                param_idx += 1
            
            insert_query = f"""
                INSERT INTO user_prefs ({', '.join(insert_fields)})
                VALUES ({', '.join(insert_values)})
                RETURNING user_id, theme, left_panel_width, right_panel_width,
                          terminal_height, default_model, font_size,
                          created_at, updated_at
            """
            row = await conn.fetchrow(insert_query, *insert_params)
        
        logger.info(f"Saved preferences for user {user_id}")
        
        return UserPreferences(
            user_id=row['user_id'],
            theme=row['theme'],
            left_panel_width=row['left_panel_width'],
            right_panel_width=row['right_panel_width'],
            terminal_height=row['terminal_height'],
            default_model=row['default_model'],
            font_size=row['font_size'],
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )


# ============================================================================
# API Endpoints
# ============================================================================

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional as OptionalType


class UserPrefsUpdate(BaseModel):
    """Request model for updating user preferences"""
    theme: OptionalType[str] = Field(None, description="UI theme (light/dark)")
    left_panel_width: OptionalType[int] = Field(None, ge=200, le=500, description="Left panel width in pixels")
    right_panel_width: OptionalType[int] = Field(None, ge=300, le=600, description="Right panel width in pixels")
    terminal_height: OptionalType[int] = Field(None, ge=100, le=600, description="Terminal height in pixels")
    default_model: OptionalType[str] = Field(None, max_length=100, description="Default AI model")
    font_size: OptionalType[int] = Field(None, ge=10, le=24, description="Font size for editor and terminal")


class UserPrefsResponse(BaseModel):
    """Response model for user preferences"""
    user_id: int
    theme: str
    left_panel_width: int
    right_panel_width: int
    terminal_height: int
    default_model: str
    font_size: int
    created_at: str
    updated_at: str


# Import dependencies
from auth_utils import get_current_user
from fastapi import Request


def get_db_pool(request: Request):
    """Get database pool from app state"""
    if hasattr(request.app.state, 'pg_pool') and request.app.state.pg_pool:
        return request.app.state.pg_pool
    else:
        raise HTTPException(status_code=503, detail="Database not available")


@router.get("/prefs", response_model=UserPrefsResponse)
async def get_preferences(
    user: Dict = Depends(get_current_user),
    pool = Depends(get_db_pool)
):
    """
    Get user preferences.
    
    Returns the current user's preferences for theme, layout, and other settings.
    Creates default preferences if none exist.
    """
    try:
        user_id = user.get("user_id") or user.get("id")
        
        prefs = await get_user_prefs(pool, user_id)
        
        return UserPrefsResponse(
            user_id=prefs.user_id,
            theme=prefs.theme,
            left_panel_width=prefs.left_panel_width,
            right_panel_width=prefs.right_panel_width,
            terminal_height=prefs.terminal_height,
            default_model=prefs.default_model,
            font_size=prefs.font_size,
            created_at=prefs.created_at.isoformat() if prefs.created_at else "",
            updated_at=prefs.updated_at.isoformat() if prefs.updated_at else ""
        )
    
    except Exception as e:
        logger.error(f"Error getting user preferences: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get preferences: {str(e)}")


@router.post("/prefs", response_model=UserPrefsResponse)
async def update_preferences(
    prefs_update: UserPrefsUpdate,
    user: Dict = Depends(get_current_user),
    pool = Depends(get_db_pool)
):
    """
    Update user preferences.
    
    Updates the current user's preferences. Only provided fields are updated.
    Supports partial updates.
    """
    try:
        user_id = user.get("user_id") or user.get("id")
        
        # Update preferences with provided values
        prefs = await save_user_prefs(
            pool,
            user_id,
            theme=prefs_update.theme,
            left_panel_width=prefs_update.left_panel_width,
            right_panel_width=prefs_update.right_panel_width,
            terminal_height=prefs_update.terminal_height,
            default_model=prefs_update.default_model,
            font_size=prefs_update.font_size
        )
        
        return UserPrefsResponse(
            user_id=prefs.user_id,
            theme=prefs.theme,
            left_panel_width=prefs.left_panel_width,
            right_panel_width=prefs.right_panel_width,
            terminal_height=prefs.terminal_height,
            default_model=prefs.default_model,
            font_size=prefs.font_size,
            created_at=prefs.created_at.isoformat() if prefs.created_at else "",
            updated_at=prefs.updated_at.isoformat() if prefs.updated_at else ""
        )
    
    except Exception as e:
        logger.error(f"Error updating user preferences: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update preferences: {str(e)}")
