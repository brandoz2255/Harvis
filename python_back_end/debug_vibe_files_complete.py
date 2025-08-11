#!/usr/bin/env python3
"""
Complete debugging and testing script for Vibe Files functionality
This will help identify and fix both persistence and drag-drop issues
"""

import requests
import json
import sys
import time
import asyncio
import asyncpg
import os
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
SESSION_ID = f"debug-session-{int(time.time())}"

def print_section(title):
    print(f"\n{'='*60}")
    print(f"🔍 {title}")
    print('='*60)

def print_step(step, description):
    print(f"\n{step}. {description}")

async def test_database_directly():
    """Test database connection and table directly"""
    print_section("DIRECT DATABASE TESTING")
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        print_step(1, "Testing database connection")
        print("✅ Database connection successful")
        
        print_step(2, "Checking if vibe_files table exists")
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'vibe_files'
            )
        """)
        print(f"Table exists: {table_exists}")
        
        if not table_exists:
            print_step(3, "Creating vibe_files table")
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
        
        print_step(4, "Testing direct database insert")
        test_file_id = await conn.fetchval("""
            INSERT INTO vibe_files (name, type, content, path, session_id, user_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, "test_file.txt", "file", "test content", "test_file.txt", SESSION_ID, 1)
        print(f"✅ Inserted test file with ID: {test_file_id}")
        
        print_step(5, "Testing direct database query")
        files = await conn.fetch("""
            SELECT * FROM vibe_files WHERE session_id = $1
        """, SESSION_ID)
        print(f"✅ Found {len(files)} files in database")
        for file in files:
            print(f"   - {file['name']} ({file['type']}) - ID: {file['id']}")
        
        print_step(6, "Cleaning up test data")
        await conn.execute("DELETE FROM vibe_files WHERE session_id = $1", SESSION_ID)
        print("✅ Test data cleaned up")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

def test_api_without_auth():
    """Test API endpoints without authentication"""
    print_section("API TESTING WITHOUT AUTH")
    
    print_step(1, "Testing server availability")
    try:
        response = requests.get(f"{BASE_URL}/docs", timeout=5)
        if response.status_code == 200:
            print("✅ Server is running")
        else:
            print(f"⚠️ Server returned {response.status_code}")
    except Exception as e:
        print(f"❌ Server not accessible: {e}")
        return False
    
    print_step(2, "Testing files endpoint without auth (should fail with 401)")
    try:
        response = requests.get(f"{BASE_URL}/api/vibe/files", params={"sessionId": SESSION_ID})
        print(f"Status: {response.status_code}")
        if response.status_code == 401:
            print("✅ Expected 401 - Authentication required")
        elif response.status_code == 422:
            print("⚠️ 422 Error - This suggests validation issues")
            try:
                error_detail = response.json()
                print(f"Error details: {json.dumps(error_detail, indent=2)}")
            except:
                print(f"Raw response: {response.text}")
        else:
            print(f"Unexpected status: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ API test failed: {e}")
        return False
    
    return True

def test_api_with_mock_auth():
    """Test API endpoints with mock authentication"""
    print_section("API TESTING WITH MOCK AUTH")
    
    # You'll need to replace this with a real JWT token
    # Get this by logging in through the frontend or API
    mock_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzU0NjM2NTY0fQ.mock_token_replace_with_real"
    
    headers = {
        "Authorization": f"Bearer {mock_token}",
        "Content-Type": "application/json"
    }
    
    print("⚠️ MOCK TOKEN - Replace with real JWT token for actual testing")
    print(f"Using token: {mock_token[:50]}...")
    
    print_step(1, "Testing debug auth endpoint")
    try:
        response = requests.get(f"{BASE_URL}/api/vibe/debug/auth", headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            auth_data = response.json()
            print(f"✅ Auth successful: {json.dumps(auth_data, indent=2)}")
        else:
            print(f"❌ Auth failed: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Auth test failed: {e}")
        return False
    
    print_step(2, "Testing file creation")
    file_data = {
        "sessionId": SESSION_ID,
        "name": "test_folder",
        "type": "folder"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=file_data, headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            folder = response.json()
            print(f"✅ Created folder: {folder['name']} (ID: {folder['id']})")
            return folder['id']
        else:
            print(f"❌ Failed to create folder: {response.text}")
            return None
    except Exception as e:
        print(f"❌ File creation test failed: {e}")
        return None

def generate_test_jwt():
    """Generate a test JWT token for debugging"""
    print_section("JWT TOKEN GENERATION")
    
    print("To test the API properly, you need a valid JWT token.")
    print("Here are several ways to get one:")
    print()
    print("1. Login through the frontend and copy the token from browser storage")
    print("2. Use the login API endpoint:")
    print(f"   POST {BASE_URL}/api/auth/login")
    print("   Body: {\"email\": \"your_email\", \"password\": \"your_password\"}")
    print()
    print("3. Create a test user and login:")
    print(f"   POST {BASE_URL}/api/auth/signup")
    print("   Body: {\"username\": \"test\", \"email\": \"test@test.com\", \"password\": \"test123\"}")
    print()
    
    # Try to create a test user
    try:
        print_step(1, "Attempting to create test user")
        signup_data = {
            "username": f"testuser_{int(time.time())}",
            "email": f"test_{int(time.time())}@test.com",
            "password": "test123456"
        }
        
        response = requests.post(f"{BASE_URL}/api/auth/signup", json=signup_data)
        if response.status_code == 200:
            token_data = response.json()
            token = token_data['access_token']
            print(f"✅ Created test user and got token")
            print(f"Token: {token}")
            return token
        else:
            print(f"❌ Failed to create test user: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Test user creation failed: {e}")
        return None

async def run_complete_test():
    """Run the complete test suite"""
    print("🧪 COMPLETE VIBE FILES DEBUG AND TEST SUITE")
    print(f"Session ID: {SESSION_ID}")
    print(f"Base URL: {BASE_URL}")
    print(f"Database URL: {DATABASE_URL}")
    
    # Test 1: Database
    db_success = await test_database_directly()
    if not db_success:
        print("\n❌ Database tests failed - fix database issues first")
        return
    
    # Test 2: API without auth
    api_success = test_api_without_auth()
    if not api_success:
        print("\n❌ API tests failed - fix server issues first")
        return
    
    # Test 3: Generate JWT token
    token = generate_test_jwt()
    if not token:
        print("\n⚠️ Could not generate test token - manual token required")
        return
    
    # Test 4: API with auth
    print_section("COMPLETE API TESTING WITH REAL AUTH")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Test file creation
        print_step(1, "Creating test folder")
        folder_data = {
            "sessionId": SESSION_ID,
            "name": "test_folder",
            "type": "folder"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=folder_data, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to create folder: {response.text}")
            return
        
        folder = response.json()
        folder_id = folder['id']
        print(f"✅ Created folder: {folder['name']} (ID: {folder_id})")
        
        # Test file creation
        print_step(2, "Creating test file")
        file_data = {
            "sessionId": SESSION_ID,
            "name": "test_file.py",
            "type": "file",
            "content": "print('Hello World')"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=file_data, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to create file: {response.text}")
            return
        
        file = response.json()
        file_id = file['id']
        print(f"✅ Created file: {file['name']} (ID: {file_id})")
        
        # Test drag and drop (move file into folder)
        print_step(3, "Testing drag and drop (move file into folder)")
        move_data = {
            "targetParentId": folder_id
        }
        
        response = requests.put(f"{BASE_URL}/api/vibe/files/{file_id}/move", json=move_data, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to move file: {response.text}")
            return
        
        moved_file = response.json()
        print(f"✅ Moved file into folder")
        print(f"   New path: {moved_file['path']}")
        print(f"   Parent ID: {moved_file['parent_id']}")
        
        # Test persistence (get files)
        print_step(4, "Testing persistence (getting files)")
        response = requests.get(f"{BASE_URL}/api/vibe/files", params={"sessionId": SESSION_ID}, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to get files: {response.text}")
            return
        
        files_data = response.json()
        print(f"✅ Retrieved {files_data['total']} files from database")
        for file in files_data['files']:
            print(f"   - {file['name']} (path: {file['path']}, parent: {file['parent_id']})")
        
        # Test tree structure
        print_step(5, "Testing tree structure")
        response = requests.get(f"{BASE_URL}/api/vibe/files/tree", params={"sessionId": SESSION_ID}, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to get tree: {response.text}")
            return
        
        tree_data = response.json()
        print(f"✅ Retrieved tree structure with {len(tree_data['tree'])} root items")
        
        def print_tree(items, indent=0):
            for item in items:
                prefix = "  " * indent
                print(f"{prefix}- {item['name']} ({item['type']})")
                if item.get('children'):
                    print_tree(item['children'], indent + 1)
        
        print("Tree structure:")
        print_tree(tree_data['tree'])
        
        print_section("🎉 ALL TESTS PASSED!")
        print("✅ Database persistence working")
        print("✅ File creation working")
        print("✅ Drag and drop working")
        print("✅ Tree structure working")
        
    except Exception as e:
        print(f"❌ Complete test failed: {e}")

if __name__ == "__main__":
    print("Starting complete Vibe Files debug and test suite...")
    asyncio.run(run_complete_test())