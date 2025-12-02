import asyncio
import asyncpg
import os

async def check():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except:
        pass
    
    pool = await asyncpg.create_pool(dsn=os.getenv('DATABASE_URL'))
    async with pool.acquire() as conn:
        # Check for session tables
        rows = await conn.fetch("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema='public' AND table_name LIKE '%session%'
        """)
        print("Session tables:", [r['table_name'] for r in rows])
        
        # Check vibecoding_sessions columns
        if any(r['table_name'] == 'vibecoding_sessions' for r in rows):
            cols = await conn.fetch("""
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_name = 'vibecoding_sessions'
                ORDER BY ordinal_position
            """)
            print("\nvibecoding_sessions columns:")
            for col in cols:
                print(f"  - {col['column_name']}: {col['data_type']}")
        
        # Check vibe_sessions columns
        if any(r['table_name'] == 'vibe_sessions' for r in rows):
            cols = await conn.fetch("""
                SELECT column_name, data_type FROM information_schema.columns
                WHERE table_name = 'vibe_sessions'
                ORDER BY ordinal_position
            """)
            print("\nvibe_sessions columns:")
            for col in cols:
                print(f"  - {col['column_name']}: {col['data_type']}")
    
    await pool.close()

asyncio.run(check())
