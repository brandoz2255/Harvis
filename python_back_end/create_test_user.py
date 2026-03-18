"""Create or update test user for API testing"""

import asyncio
import asyncpg
import os
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def create_test_user():
    database_url = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
    
    pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=2)
    
    async with pool.acquire() as conn:
        # Check if test user exists
        user = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1",
            "test@example.com"
        )
        
        # Hash password
        hashed_password = pwd_context.hash("testpass123")
        
        if user:
            # Update password
            await conn.execute(
                "UPDATE users SET password = $1 WHERE email = $2",
                hashed_password,
                "test@example.com"
            )
            print(f"✅ Updated test user password")
        else:
            # Create new user
            await conn.execute(
                "INSERT INTO users (username, email, password) VALUES ($1, $2, $3)",
                "testuser",
                "test@example.com",
                hashed_password
            )
            print(f"✅ Created test user")
        
        print(f"Email: test@example.com")
        print(f"Password: testpass123")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(create_test_user())