"""Check user_prefs table schema"""

import asyncio
import asyncpg
import os

async def check_user_prefs():
    database_url = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
    
    pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=2)
    
    async with pool.acquire() as conn:
        # Check if user_prefs table exists
        exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'user_prefs'
            )
        """)
        
        print(f"user_prefs table exists: {exists}")
        
        if exists:
            # Get columns
            columns = await conn.fetch("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'user_prefs'
                ORDER BY ordinal_position
            """)
            
            print("\nuser_prefs columns:")
            for col in columns:
                print(f"  - {col['column_name']}: {col['data_type']}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(check_user_prefs())
