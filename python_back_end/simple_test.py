#!/usr/bin/env python3
"""
Simple test script to verify Vibe Files functionality
Run this to check if your issues are fixed
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_basic_functionality():
    """Test basic functionality step by step"""
    print("🧪 SIMPLE VIBE FILES TEST")
    print("=" * 40)
    
    # Step 1: Test server
    print("\n1. Testing server...")
    try:
        response = requests.get(f"{BASE_URL}/docs", timeout=5)
        if response.status_code == 200:
            print("✅ Server is running")
        else:
            print(f"❌ Server issue: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cannot connect to server: {e}")
        print("Make sure your backend server is running on http://localhost:8000")
        return False
    
    # Step 2: Test database
    print("\n2. Testing database...")
    try:
        response = requests.get(f"{BASE_URL}/api/vibe/debug/database", timeout=10)
        if response.status_code == 200:
            db_info = response.json()
            print(f"✅ Database connected: {db_info.get('database_connected')}")
            print(f"✅ Table exists: {db_info.get('table_exists')}")
            
            if not db_info.get('table_exists'):
                print("❌ ISSUE: Database table doesn't exist!")
                print("SOLUTION: Restart your backend server")
                return False
        else:
            print(f"❌ Database test failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Database test error: {e}")
        return False
    
    # Step 3: Create test user
    print("\n3. Creating test user...")
    timestamp = int(time.time())
    user_data = {
        "username": f"testuser_{timestamp}",
        "email": f"test_{timestamp}@test.com",
        "password": "test123456"
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/auth/signup", json=user_data, timeout=10)
        if response.status_code == 200:
            token_data = response.json()
            token = token_data['access_token']
            print("✅ Test user created and authenticated")
        else:
            print(f"❌ Failed to create user: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ User creation error: {e}")
        return False
    
    # Step 4: Test file operations
    print("\n4. Testing file operations...")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    session_id = f"test-{timestamp}"
    
    # Create folder
    try:
        folder_data = {
            "sessionId": session_id,
            "name": "test_folder",
            "type": "folder"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=folder_data, headers=headers, timeout=10)
        if response.status_code == 200:
            folder = response.json()
            folder_id = folder['id']
            print(f"✅ Created folder: {folder['name']}")
        else:
            print(f"❌ Failed to create folder: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Folder creation error: {e}")
        return False
    
    # Create file
    try:
        file_data = {
            "sessionId": session_id,
            "name": "test_file.py",
            "type": "file",
            "content": "print('Test successful!')"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=file_data, headers=headers, timeout=10)
        if response.status_code == 200:
            file = response.json()
            file_id = file['id']
            print(f"✅ Created file: {file['name']}")
        else:
            print(f"❌ Failed to create file: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ File creation error: {e}")
        return False
    
    # Step 5: Test persistence
    print("\n5. Testing persistence...")
    try:
        response = requests.get(f"{BASE_URL}/api/vibe/files", params={"sessionId": session_id}, headers=headers, timeout=10)
        if response.status_code == 200:
            files_data = response.json()
            print(f"✅ Persistence working: found {files_data['total']} files")
            
            if files_data['total'] < 2:
                print("❌ ISSUE: Not all files were saved!")
                return False
        else:
            print(f"❌ Failed to get files: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Persistence test error: {e}")
        return False
    
    # Step 6: Test drag and drop
    print("\n6. Testing drag and drop...")
    try:
        move_data = {
            "targetParentId": folder_id
        }
        
        response = requests.put(f"{BASE_URL}/api/vibe/files/{file_id}/move", json=move_data, headers=headers, timeout=10)
        if response.status_code == 200:
            moved_file = response.json()
            print(f"✅ Drag and drop working: file moved to {moved_file['path']}")
        else:
            print(f"❌ Drag and drop failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Drag and drop error: {e}")
        return False
    
    # Step 7: Test tree structure
    print("\n7. Testing tree structure...")
    try:
        response = requests.get(f"{BASE_URL}/api/vibe/files/tree", params={"sessionId": session_id}, headers=headers, timeout=10)
        if response.status_code == 200:
            tree_data = response.json()
            print(f"✅ Tree structure working: {len(tree_data['tree'])} root items")
            
            # Print the tree
            def print_tree(items, indent=0):
                for item in items:
                    prefix = "  " * indent
                    icon = "📁" if item['type'] == 'folder' else "📄"
                    print(f"{prefix}{icon} {item['name']}")
                    if item.get('children'):
                        print_tree(item['children'], indent + 1)
            
            print("Tree structure:")
            print_tree(tree_data['tree'])
            
        else:
            print(f"❌ Failed to get tree: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Tree structure error: {e}")
        return False
    
    return True

def main():
    """Main test function"""
    success = test_basic_functionality()
    
    if success:
        print("\n🎉 ALL TESTS PASSED!")
        print("=" * 40)
        print("✅ Server is running correctly")
        print("✅ Database persistence is working")
        print("✅ File creation is working")
        print("✅ Drag and drop is working")
        print("✅ Tree structure is working")
        print("\nYour Vibe Files system is fully functional!")
        print("\nIf you're still having issues in your frontend:")
        print("1. Check that you're using the correct API endpoints")
        print("2. Make sure you're sending the JWT token in headers")
        print("3. Use the browser developer tools to debug requests")
        print("4. Check the COMPLETE_FIX_GUIDE.md for frontend examples")
    else:
        print("\n❌ SOME TESTS FAILED")
        print("=" * 40)
        print("Check the error messages above to identify the issue.")
        print("Common solutions:")
        print("1. Restart your backend server")
        print("2. Check database connection")
        print("3. Make sure all dependencies are installed")
        print("4. Check server logs for detailed error messages")

if __name__ == "__main__":
    main()