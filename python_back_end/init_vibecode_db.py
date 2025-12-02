#!/usr/bin/env python3
"""
Initialize VibeCode IDE database tables
This script creates the vibe_sessions and user_prefs tables if they don't exist.
"""

import asyncio
import asyncpg
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")

async def init_database():
    """Initialize database tables for VibeCode IDE."""
    try:
        logger.info("Connecting to database...")
        conn = await asyncpg.connect(DATABASE_URL, timeout=10)
        
        logger.info("Reading schema file...")
        schema_path = os.path.join(os.path.dirname(__file__), "vibecoding_sessions_schema.sql")
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        logger.info("Executing schema...")
        await conn.execute(schema_sql)
        
        logger.info("✓ Database schema initialized successfully")
        
        # Verify tables were created
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('vibe_sessions', 'user_prefs')
        """)
        
        logger.info(f"✓ Found {len(tables)} VibeCode tables:")
        for table in tables:
            logger.info(f"  - {table['table_name']}")
        
        await conn.close()
        logger.info("✓ Database connection closed")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to initialize database: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(init_database())
    exit(0 if success else 1)
