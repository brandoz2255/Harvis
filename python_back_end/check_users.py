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
        rows = await conn.fetch('SELECT id, username, email FROM users LIMIT 5')
        print('Users:')
        for r in rows:
            print(f"  ID: {r['id']}, Username: {r['username']}, Email: {r['email']}")
    await pool.close()

asyncio.run(check())
