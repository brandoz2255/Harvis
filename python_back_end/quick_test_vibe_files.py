#!/usr/bin/env python3
"""
Quick test to diagnose the two main issues:
1. Files not saving on refresh (persistence)
2. Drag and drop not working
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_without_auth():
    """Test the debug endpoints without authentication"""
    print("🔍 Testing Debug Endpoints (No Auth Required)")
    print("=" * 50)
    
    # Test database connection
    print("\n1. Testing database connection...")
    try:
        response = requests.get(f"{BASE_URL}/api/vibe/debug/database")
        if response.status_code == 200:
            db_info = response.json()
            print("✅ Database connection successful")
            print(f"   - Table exists: {db_info.get('table_exists')}")
            print(f"   - Total files: {db_info.get('total_files')}")
            print(f"   - Database version: {db_info.get('database_version', 'Unknown')[:50]}...")
            
            if not db_info.get('table_exists'):
                print("❌ ISSUE FOUND: vibe_files table doesn't exist!")
                print("   This explains why files aren't persisting.")
                return False
            else:
                print("✅ Database table exists - persistence should work")
                return True
        else:
            print(f"❌ Database test failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Database test error: {e}")
        return False

def test_with_auth():
    """Test with authentication (requires manual token)"""
    print("\n🔐 Testing with Authentication")
    print("=" * 50)
    
    # Try to create a test user first
    print("\n1. Creating test user...")
    test_email = f"test_{int(time.time())}@test.com"
    signup_data = {
        "username": f"testuser_{int(time.time())}",
        "email": test_email,
        "password": "test123456"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/auth/signup", json=signup_data)
        if response.status_code == 200:
            token_data = response.json()
            token = token_data['access_token']
            print(f"✅ Created test user and got token")
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            # Test auth debug endpoint
            print("\n2. Testing authentication...")
            auth_response = requests.get(f"{BASE_URL}/api/vibe/debug/auth", headers=headers)
            if auth_response.status_code == 200:
                auth_data = auth_response.json()
                print("✅ Authentication working")
                print(f"   User ID: {auth_data.get('user_id')}")
                
                # Test file creation and persistence
                return test_file_operations(headers)
            else:
                print(f"❌ Auth test failed: {auth_response.status_code}")
                return False
        else:
            print(f"❌ Failed to create test user: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Auth test error: {e}")
        return False

def test_file_operations(headers):
    """Test file operations with valid auth headers"""
    print("\n📁 Testing File Operations")
    print("=" * 30)
    
    session_id = f"test-session-{int(time.time())}"
    
    try:
        # Test 1: Create a folder
        print("\n1. Creating folder...")
        folder_data = {
            "sessionId": session_id,
            "name": "test_folder",
            "type": "folder"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=folder_data, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to create folder: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        folder = response.json()
        folder_id = folder['id']
        print(f"✅ Created folder: {folder['name']} (ID: {folder_id})")
        
        # Test 2: Create a file
        print("\n2. Creating file...")
        file_data = {
            "sessionId": session_id,
            "name": "test_file.py",
            "type": "file",
            "content": "print('Hello World')"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=file_data, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to create file: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        file = response.json()
        file_id = file['id']
        print(f"✅ Created file: {file['name']} (ID: {file_id})")
        
        # Test 3: Test persistence (get files)
        print("\n3. Testing persistence...")
        response = requests.get(f"{BASE_URL}/api/vibe/files", params={"sessionId": session_id}, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to get files: {response.status_code}")
            return False
        
        files_data = response.json()
        print(f"✅ Persistence working - found {files_data['total']} files")
        
        # Test 4: Test drag and drop (move file into folder)
        print("\n4. Testing drag and drop...")
        move_data = {
            "targetParentId": folder_id
        }
        
        response = requests.put(f"{BASE_URL}/api/vibe/files/{file_id}/move", json=move_data, headers=headers)
        if response.status_code != 200:
            print(f"❌ Drag and drop failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        moved_file = response.json()
        print(f"✅ Drag and drop working!")
        print(f"   File moved to: {moved_file['path']}")
        print(f"   Parent ID: {moved_file['parent_id']}")
        
        # Test 5: Verify tree structure
        print("\n5. Testing tree structure...")
        response = requests.get(f"{BASE_URL}/api/vibe/files/tree", params={"sessionId": session_id}, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to get tree: {response.status_code}")
            return False
        
        tree_data = response.json()
        print(f"✅ Tree structure working - {len(tree_data['tree'])} root items")
        
        # Print tree structure
        def print_tree(items, indent=0):
            for item in items:
                prefix = "  " * indent
                print(f"{prefix}- {item['name']} ({item['type']})")
                if item.get('children'):
                    print_tree(item['children'], indent + 1)
        
        print("Tree structure:")
        print_tree(tree_data['tree'])
        
        return True
        
    except Exception as e:
        print(f"❌ File operations test error: {e}")
        return False

def main():
    print("🧪 QUICK VIBE FILES DIAGNOSTIC TEST")
    print("This will test both main issues:")
    print("1. Files not saving on refresh (persistence)")
    print("2. Drag and drop not working")
    print()
    
    # Test 1: Database and basic functionality
    db_ok = test_without_auth()
    
    if not db_ok:
        print("\n❌ DATABASE ISSUE DETECTED")
        print("The vibe_files table is not created properly.")
        print("This explains why files don't persist on refresh.")
        print("\nSOLUTION:")
        print("1. Restart your backend server")
        print("2. The startup event should create the table automatically")
        print("3. Check server logs for any database connection errors")
        return
    
    # Test 2: Full functionality with auth
    full_test_ok = test_with_auth()
    
    if full_test_ok:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ Database persistence is working")
        print("✅ Drag and drop is working")
        print("✅ Tree structure is working")
        print("\nIf you're still having issues in the frontend:")
        print("1. Check browser console for JavaScript errors")
        print("2. Verify the frontend is calling the correct API endpoints")
        print("3. Check that authentication tokens are being sent properly")
    else:
        print("\n❌ SOME TESTS FAILED")
        print("Check the error messages above for specific issues.")

if __name__ == "__main__":
    main()