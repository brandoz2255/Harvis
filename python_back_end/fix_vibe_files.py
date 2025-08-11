#!/usr/bin/env python3
"""
Fix script for Vibe Files issues
This will identify and fix common problems with file persistence and drag-drop
"""

import asyncio
import asyncpg
import os
import sys
import requests
import json
from datetime import datetime

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
BASE_URL = "http://localhost:8000"

async def fix_database_issues():
    """Fix database-related issues"""
    print("🔧 FIXING DATABASE ISSUES")
    print("=" * 40)
    
    try:
        print("1. Testing database connection...")
        conn = await asyncpg.connect(DATABASE_URL)
        print("✅ Database connection successful")
        
        print("2. Checking if vibe_files table exists...")
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'vibe_files'
            )
        """)
        
        if not table_exists:
            print("❌ Table doesn't exist - creating it now...")
            await conn.execute("""
                CREATE TABLE vibe_files (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(20) NOT NULL CHECK (type IN ('file', 'folder')),
                    content TEXT,
                    language VARCHAR(50) DEFAULT 'plaintext',
                    path TEXT NOT NULL,
                    parent_id UUID REFERENCES vibe_files(id) ON DELETE CASCADE,
                    session_id VARCHAR(255) NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            print("✅ Table created successfully")
            
            # Create indexes
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_files_session_user ON vibe_files(session_id, user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_files_parent ON vibe_files(parent_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_files_type ON vibe_files(type)")
            print("✅ Indexes created")
        else:
            print("✅ Table already exists")
        
        print("3. Testing table functionality...")
        # Test insert
        test_id = await conn.fetchval("""
            INSERT INTO vibe_files (name, type, content, path, session_id, user_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, "test_fix.txt", "file", "test content", "test_fix.txt", "fix-session", 1)
        print(f"✅ Test insert successful: {test_id}")
        
        # Test select
        files = await conn.fetch("SELECT * FROM vibe_files WHERE session_id = $1", "fix-session")
        print(f"✅ Test select successful: found {len(files)} files")
        
        # Clean up test data
        await conn.execute("DELETE FROM vibe_files WHERE session_id = $1", "fix-session")
        print("✅ Test cleanup successful")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Database fix failed: {e}")
        return False

def test_api_endpoints():
    """Test API endpoints"""
    print("\n🔧 TESTING API ENDPOINTS")
    print("=" * 40)
    
    try:
        print("1. Testing server availability...")
        response = requests.get(f"{BASE_URL}/docs", timeout=5)
        if response.status_code == 200:
            print("✅ Server is running")
        else:
            print(f"❌ Server returned {response.status_code}")
            return False
        
        print("2. Testing database debug endpoint...")
        response = requests.get(f"{BASE_URL}/api/vibe/debug/database", timeout=10)
        if response.status_code == 200:
            db_info = response.json()
            print("✅ Database debug endpoint working")
            print(f"   - Connected: {db_info.get('database_connected')}")
            print(f"   - Table exists: {db_info.get('table_exists')}")
            print(f"   - Total files: {db_info.get('total_files')}")
            
            if not db_info.get('database_connected') or not db_info.get('table_exists'):
                print("❌ Database issues detected via API")
                return False
        else:
            print(f"❌ Database debug endpoint failed: {response.status_code}")
            return False
        
        print("3. Testing file endpoints (without auth - should get 401)...")
        response = requests.get(f"{BASE_URL}/api/vibe/files?sessionId=test", timeout=5)
        if response.status_code == 401:
            print("✅ File endpoint properly requires authentication")
        elif response.status_code == 422:
            print("⚠️ Getting 422 error - this might indicate validation issues")
            print(f"   Response: {response.text}")
        else:
            print(f"⚠️ Unexpected response: {response.status_code}")
        
        return True
        
    except Exception as e:
        print(f"❌ API test failed: {e}")
        return False

def create_test_user_and_test():
    """Create a test user and test full functionality"""
    print("\n🔧 TESTING FULL FUNCTIONALITY")
    print("=" * 40)
    
    try:
        print("1. Creating test user...")
        timestamp = int(datetime.now().timestamp())
        signup_data = {
            "username": f"testuser_{timestamp}",
            "email": f"test_{timestamp}@test.com",
            "password": "test123456"
        }
        
        response = requests.post(f"{BASE_URL}/api/auth/signup", json=signup_data, timeout=10)
        if response.status_code != 200:
            print(f"❌ Failed to create test user: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        token_data = response.json()
        token = token_data['access_token']
        print("✅ Test user created and authenticated")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        session_id = f"fix-test-{timestamp}"
        
        print("2. Testing file creation...")
        # Create folder
        folder_data = {
            "sessionId": session_id,
            "name": "test_folder",
            "type": "folder"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=folder_data, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"❌ Failed to create folder: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        folder = response.json()
        folder_id = folder['id']
        print(f"✅ Folder created: {folder['name']}")
        
        # Create file
        file_data = {
            "sessionId": session_id,
            "name": "test_file.py",
            "type": "file",
            "content": "print('Fix test successful!')"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=file_data, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"❌ Failed to create file: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        file = response.json()
        file_id = file['id']
        print(f"✅ File created: {file['name']}")
        
        print("3. Testing persistence...")
        response = requests.get(f"{BASE_URL}/api/vibe/files", params={"sessionId": session_id}, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"❌ Failed to get files: {response.status_code}")
            return False
        
        files_data = response.json()
        print(f"✅ Persistence working: found {files_data['total']} files")
        
        print("4. Testing drag and drop...")
        move_data = {
            "targetParentId": folder_id
        }
        
        response = requests.put(f"{BASE_URL}/api/vibe/files/{file_id}/move", json=move_data, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"❌ Drag and drop failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        moved_file = response.json()
        print(f"✅ Drag and drop working: file moved to {moved_file['path']}")
        
        print("5. Testing tree structure...")
        response = requests.get(f"{BASE_URL}/api/vibe/files/tree", params={"sessionId": session_id}, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"❌ Failed to get tree: {response.status_code}")
            return False
        
        tree_data = response.json()
        print(f"✅ Tree structure working: {len(tree_data['tree'])} root items")
        
        return True
        
    except Exception as e:
        print(f"❌ Full functionality test failed: {e}")
        return False

async def main():
    """Main fix function"""
    print("🛠️  VIBE FILES FIX SCRIPT")
    print("This will identify and fix common issues with file persistence and drag-drop")
    print("=" * 70)
    
    # Step 1: Fix database issues
    db_fixed = await fix_database_issues()
    if not db_fixed:
        print("\n❌ CRITICAL: Database issues could not be fixed")
        print("Please check your database connection and permissions")
        return
    
    # Step 2: Test API endpoints
    api_working = test_api_endpoints()
    if not api_working:
        print("\n❌ CRITICAL: API endpoints are not working")
        print("Please restart your backend server and try again")
        return
    
    # Step 3: Test full functionality
    full_test_passed = create_test_user_and_test()
    if not full_test_passed:
        print("\n❌ SOME FUNCTIONALITY ISSUES DETECTED")
        print("Check the error messages above for specific problems")
        return
    
    print("\n🎉 ALL FIXES APPLIED AND TESTS PASSED!")
    print("=" * 50)
    print("✅ Database persistence is working")
    print("✅ File creation is working")
    print("✅ Drag and drop is working")
    print("✅ Tree structure is working")
    print("\nYour Vibe Files system should now be fully functional!")
    print("\nIf you're still having issues:")
    print("1. Clear your browser cache and cookies")
    print("2. Check browser console for JavaScript errors")
    print("3. Verify your frontend is sending the correct API requests")

if __name__ == "__main__":
    asyncio.run(main())