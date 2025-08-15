#!/usr/bin/env python3
"""
Issue identifier for Vibe Files
This will quickly identify which of the two main issues you're experiencing
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_issue_1_persistence():
    """Test if files are persisting (Issue 1)"""
    print("🔍 TESTING ISSUE 1: Files not saving on refresh")
    print("=" * 50)
    
    # First, check if server is running
    try:
        response = requests.get(f"{BASE_URL}/docs", timeout=3)
        if response.status_code != 200:
            print("❌ Server is not running properly")
            return "server_not_running"
    except:
        print("❌ Cannot connect to server")
        print("SOLUTION: Start your backend server first")
        return "server_not_running"
    
    # Check database status
    try:
        response = requests.get(f"{BASE_URL}/api/vibe/debug/database", timeout=5)
        if response.status_code == 200:
            db_info = response.json()
            print(f"Database connected: {db_info.get('database_connected')}")
            print(f"Table exists: {db_info.get('table_exists')}")
            print(f"Total files: {db_info.get('total_files')}")
            
            if not db_info.get('database_connected'):
                print("❌ ISSUE 1 IDENTIFIED: Database not connected")
                return "database_not_connected"
            
            if not db_info.get('table_exists'):
                print("❌ ISSUE 1 IDENTIFIED: Database table doesn't exist")
                return "table_missing"
            
            print("✅ Database and table are working")
            return "persistence_ok"
            
        else:
            print("❌ Cannot check database status")
            return "database_check_failed"
    except Exception as e:
        print(f"❌ Database check error: {e}")
        return "database_check_failed"

def test_issue_2_drag_drop():
    """Test if drag and drop API is working (Issue 2)"""
    print("\n🔍 TESTING ISSUE 2: Drag and drop not working")
    print("=" * 50)
    
    # Try to create a test user for authentication
    try:
        timestamp = int(time.time())
        user_data = {
            "username": f"testuser_{timestamp}",
            "email": f"test_{timestamp}@test.com",
            "password": "test123456"
        }
        
        response = requests.post(f"{BASE_URL}/api/auth/signup", json=user_data, timeout=10)
        if response.status_code == 200:
            token = response.json()['access_token']
            print("✅ Authentication working")
        else:
            print("❌ Cannot create test user for drag-drop test")
            return "auth_failed"
    except Exception as e:
        print(f"❌ Authentication error: {e}")
        return "auth_failed"
    
    # Test file creation and move operation
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        session_id = f"test-{timestamp}"
        
        # Create folder
        folder_data = {
            "sessionId": session_id,
            "name": "test_folder",
            "type": "folder"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=folder_data, headers=headers, timeout=10)
        if response.status_code != 200:
            print("❌ Cannot create folder for drag-drop test")
            return "file_creation_failed"
        
        folder_id = response.json()['id']
        print("✅ Folder creation working")
        
        # Create file
        file_data = {
            "sessionId": session_id,
            "name": "test_file.txt",
            "type": "file",
            "content": "test"
        }
        
        response = requests.post(f"{BASE_URL}/api/vibe/files", json=file_data, headers=headers, timeout=10)
        if response.status_code != 200:
            print("❌ Cannot create file for drag-drop test")
            return "file_creation_failed"
        
        file_id = response.json()['id']
        print("✅ File creation working")
        
        # Test drag and drop (move operation)
        move_data = {
            "targetParentId": folder_id
        }
        
        response = requests.put(f"{BASE_URL}/api/vibe/files/{file_id}/move", json=move_data, headers=headers, timeout=10)
        if response.status_code == 200:
            print("✅ Drag and drop API working")
            return "drag_drop_ok"
        else:
            print(f"❌ ISSUE 2 IDENTIFIED: Drag and drop API failed")
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
            return "drag_drop_api_failed"
            
    except Exception as e:
        print(f"❌ Drag and drop test error: {e}")
        return "drag_drop_test_failed"

def provide_specific_solution(issue1_result, issue2_result):
    """Provide specific solutions based on identified issues"""
    print("\n🎯 SPECIFIC SOLUTIONS FOR YOUR ISSUES")
    print("=" * 50)
    
    # Issue 1 Solutions
    if issue1_result == "server_not_running":
        print("❌ ISSUE 1: Server not running")
        print("SOLUTION:")
        print("   1. Start your backend server:")
        print("      uvicorn main:app --reload")
        print("   2. Or: python main.py")
        print("   3. Make sure it's running on http://localhost:8000")
        
    elif issue1_result == "database_not_connected":
        print("❌ ISSUE 1: Database not connected")
        print("SOLUTION:")
        print("   1. Check your DATABASE_URL environment variable")
        print("   2. Make sure PostgreSQL is running")
        print("   3. Verify database credentials")
        
    elif issue1_result == "table_missing":
        print("❌ ISSUE 1: Database table missing")
        print("SOLUTION:")
        print("   1. Restart your backend server")
        print("   2. The startup event should create the table automatically")
        print("   3. Check server logs for any database errors")
        
    elif issue1_result == "persistence_ok":
        print("✅ ISSUE 1: Persistence is working correctly")
        print("   Your files should save on refresh")
    
    # Issue 2 Solutions
    if issue2_result == "auth_failed":
        print("\n❌ ISSUE 2: Authentication not working")
        print("SOLUTION:")
        print("   1. Check your JWT_SECRET environment variable")
        print("   2. Verify database connection for user storage")
        print("   3. Check server logs for authentication errors")
        
    elif issue2_result == "file_creation_failed":
        print("\n❌ ISSUE 2: File creation not working")
        print("SOLUTION:")
        print("   1. This is likely the same as Issue 1 (database problem)")
        print("   2. Fix the database connection first")
        
    elif issue2_result == "drag_drop_api_failed":
        print("\n❌ ISSUE 2: Drag and drop API not working")
        print("SOLUTION:")
        print("   1. Check server logs for specific error messages")
        print("   2. Verify the move endpoint is properly implemented")
        print("   3. This might be a backend code issue")
        
    elif issue2_result == "drag_drop_ok":
        print("\n✅ ISSUE 2: Drag and drop API is working correctly")
        print("   The backend is working. Issue is likely in frontend:")
        print("   1. Check browser console for JavaScript errors")
        print("   2. Verify frontend is calling: PUT /api/vibe/files/{id}/move")
        print("   3. Make sure request body has: {\"targetParentId\": \"folder_id\"}")
        print("   4. Include Authorization header with JWT token")

def main():
    """Main issue identification"""
    print("🔍 VIBE FILES ISSUE IDENTIFIER")
    print("This will quickly identify which issues you're experiencing")
    print("=" * 60)
    
    # Test both issues
    issue1_result = test_issue_1_persistence()
    issue2_result = test_issue_2_drag_drop()
    
    # Provide specific solutions
    provide_specific_solution(issue1_result, issue2_result)
    
    # Summary
    print("\n📋 SUMMARY")
    print("=" * 20)
    
    if issue1_result == "persistence_ok" and issue2_result == "drag_drop_ok":
        print("🎉 BOTH BACKEND SYSTEMS ARE WORKING!")
        print("If you're still having issues, the problem is in your frontend code.")
        print("Check the browser console and verify your API calls.")
    else:
        print("⚠️  BACKEND ISSUES DETECTED")
        print("Follow the solutions above to fix the backend first.")
        print("Then test your frontend integration.")
    
    print("\n🔧 NEXT STEPS:")
    print("1. Fix any backend issues identified above")
    print("2. Run: python debug_step_by_step.py (for detailed debugging)")
    print("3. Test your frontend integration")
    print("4. Check browser console for JavaScript errors")

if __name__ == "__main__":
    main()