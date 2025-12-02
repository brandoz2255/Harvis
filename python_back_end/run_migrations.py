"""Database Migration Runner for VibeCode IDE

This script runs database migrations to set up the required schema.
"""

import asyncio
import asyncpg
import os
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_migrations():
    """Run all pending database migrations"""
    
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
    
    logger.info(f"Connecting to database...")
    
    try:
        # Create connection pool
        pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=2)
        
        # Get migrations directory
        migrations_dir = Path(__file__).parent / "migrations"
        
        if not migrations_dir.exists():
            logger.error(f"Migrations directory not found: {migrations_dir}")
            return False
        
        # Get all SQL migration files
        migration_files = sorted(migrations_dir.glob("*.sql"))
        
        if not migration_files:
            logger.warning("No migration files found")
            return True
        
        logger.info(f"Found {len(migration_files)} migration file(s)")
        
        # Run each migration
        async with pool.acquire() as conn:
            for migration_file in migration_files:
                logger.info(f"Running migration: {migration_file.name}")
                
                try:
                    # Read migration SQL
                    sql = migration_file.read_text()
                    
                    # Execute migration
                    await conn.execute(sql)
                    
                    logger.info(f"✅ Successfully applied: {migration_file.name}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to apply {migration_file.name}: {e}")
                    raise
        
        # Close pool
        await pool.close()
        
        logger.info("✅ All migrations completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        return False

async def verify_schema():
    """Verify that the schema was created correctly"""
    
    database_url = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
    
    try:
        pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=2)
        
        async with pool.acquire() as conn:
            # Check if vibe_sessions table exists
            result = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'vibe_sessions'
                )
            """)
            
            if result:
                logger.info("✅ vibe_sessions table exists")
                
                # Check indexes
                indexes = await conn.fetch("""
                    SELECT indexname FROM pg_indexes 
                    WHERE tablename = 'vibe_sessions'
                """)
                
                logger.info(f"✅ Found {len(indexes)} indexes on vibe_sessions")
                for idx in indexes:
                    logger.info(f"  - {idx['indexname']}")
                
            else:
                logger.error("❌ vibe_sessions table does not exist")
                return False
        
        await pool.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Schema verification failed: {e}")
        return False

if __name__ == "__main__":
    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # Run migrations
    success = asyncio.run(run_migrations())
    
    if success:
        # Verify schema
        asyncio.run(verify_schema())
        sys.exit(0)
    else:
        sys.exit(1)
