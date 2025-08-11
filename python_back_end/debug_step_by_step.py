#!/usr/bin/env python3
"""
Step-by-step debugging script for Vibe Files
This will identify exactly what's wrong and provide specific fixes
"""

import asyncio
import asyncpg
import requests
import json
import os
import time
from datetime import datetime

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
BASE_URL = "http://localhost:8000"

class VibeFilesDebugger:
    def __init__(self):
        self.issues_found = []
        self.fixes_applied = []
        self.test_token = None
        self.test_session_id = f"debug-{int(time.time())}"
        
    def log_issue(self, issue):
        self.issues_found.append(issue)
        print(f"❌ ISSUE: {issue}")
        
    def log_fix(self, fix):
        self.fixes_applied.append(fix)
        print(f"✅ FIX: {fix}")
        
    def log_success(self, message):
        print(f"✅ {message}")
        
    def log_info(self, message):
        print(f"ℹ️  {message}")

    async def debug_database_connection(self):
        """Debug database connection and table creation"""
        print("\n🔍 DEBUGGING DATABASE CONNECTION")
        print("=" * 50)
        
        try:
            # Test basic connection
            self.log_info("Testing database connection...")
            conn = await asyncpg.connect(DATABASE_URL)
            self.log_success("Database connection successful")
            
            # Check if table exists
            self.log_info("Checking if vibe_files table exists...")
            table_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'vibe_files'
                )
            """)
            
            if not table_exists:
                self.log_issue("vibe_files table does not exist")
                self.log_info("Creating vibe_files table...")
                
                # Create the table
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
                
                # Create indexes
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_files_session_user ON vibe_files(session_id, user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_files_parent ON vibe_files(parent_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_files_type ON vibe_files(type)")
                
                self.log_fix("Created vibe_files table with indexes")
            else:
                self.log_success("vibe_files table exists")
            
            # Test table functionality
            self.log_info("Testing table functionality...")
            
            # Insert test record
            test_id = await conn.fetchval("""
                INSERT INTO vibe_files (name, type, content, path, session_id, user_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, "debug_test.txt", "file", "test content", "debug_test.txt", self.test_session_id, 1)
            
            # Query test record
            test_record = await conn.fetchrow(
                "SELECT * FROM vibe_files WHERE id = $1", test_id
            )
            
            if test_record:
                self.log_success("Table insert/select operations working")
                
                # Clean up test record
                await conn.execute("DELETE FROM vibe_files WHERE id = $1", test_id)
                self.log_success("Table delete operation working")
            else:
                self.log_issue("Table operations not working properly")
            
            await conn.close()
            return True
            
        except Exception as e:
            self.log_issue(f"Database error: {str(e)}")
            return False

    def debug_server_connection(self):
        """Debug server connection and API availability"""
        print("\n🔍 DEBUGGING SERVER CONNECTION")
        print("=" * 50)
        
        try:
            # Test basic server connection
            self.log_info("Testing server connection...")
            response = requests.get(f"{BASE_URL}/docs", timeout=5)
            
            if response.status_code == 200:
                self.log_success("Server is running and accessible")
            else:
                self.log_issue(f"Server returned status {response.status_code}")
                return False
                
        except requests.exceptions.ConnectionError:
            self.log_issue("Cannot connect to server - is it running?")
            self.log_info("Make sure your backend server is running on http://localhost:8000")
            return False
        except Exception as e:
            self.log_issue(f"Server connection error: {str(e)}")
            return False
        
        # Test debug endpoints
        try:
            self.log_info("Testing database debug endpoint...")
            response = requests.get(f"{BASE_URL}/api/vibe/debug/database", timeout=10)
            
            if response.status_code == 200:
                db_info = response.json()
                self.log_success("Database debug endpoint working")
                
                if not db_info.get('database_connected'):
                    self.log_issue("Database not connected according to API")
                    return False
                    
                if not db_info.get('table_exists'):
                    self.log_issue("Table doesn't exist according to API")
                    return False
                    
                self.log_success(f"Database has {db_info.get('total_files', 0)} files")
            else:
                self.log_issue(f"Database debug endpoint failed: {response.status_code}")
                return False
                
        except Exception as e:
            self.log_issue(f"Debug endpoint error: {str(e)}")
            return False
        
        return True

    def debug_authentication(self):
        """Debug authentication system"""
        print("\n🔍 DEBUGGING AUTHENTICATION")
        print("=" * 50)
        
        try:
            # Create test user
            self.log_info("Creating test user...")
            timestamp = int(time.time())
            user_data = {
                "username": f"debuguser_{timestamp}",
                "email": f"debug_{timestamp}@test.com",
                "password": "debug123456"
            }
            
            response = requests.post(f"{BASE_URL}/api/auth/signup", json=user_data, timeout=10)
            
            if response.status_code == 200:
                token_data = response.json()
                self.test_token = token_data['access_token']
                self.log_success("Test user created and authenticated")
            else:
                self.log_issue(f"Failed to create test user: {response.status_code}")
                self.log_info(f"Response: {response.text}")
                return False
                
        except Exception as e:
            self.log_issue(f"Authentication error: {str(e)}")
            return False
        
        # Test auth debug endpoint
        try:
            self.log_info("Testing authentication debug endpoint...")
            headers = {"Authorization": f"Bearer {self.test_token}"}
            response = requests.get(f"{BASE_URL}/api/vibe/debug/auth", headers=headers, timeout=10)
            
            if response.status_code == 200:
                auth_data = response.json()
                self.log_success("Authentication debug endpoint working")
                self.log_info(f"User ID: {auth_data.get('user_id')}")
            else:
                self.log_issue(f"Auth debug endpoint failed: {response.status_code}")
                return False
                
        except Exception as e:
            self.log_issue(f"Auth debug error: {str(e)}")
            return False
        
        return True

    def debug_file_operations(self):
        """Debug file creation, persistence, and drag-drop"""
        print("\n🔍 DEBUGGING FILE OPERATIONS")
        print("=" * 50)
        
        if not self.test_token:
            self.log_issue("No authentication token available")
            return False
        
        headers = {
            "Authorization": f"Bearer {self.test_token}",
            "Content-Type": "application/json"
        }
        
        try:
            # Test file creation
            self.log_info("Testing file creation...")
            
            # Create folder
            folder_data = {
                "sessionId": self.test_session_id,
                "name": "debug_folder",
                "type": "folder"
            }
            
            response = requests.post(f"{BASE_URL}/api/vibe/files", json=folder_data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                folder = response.json()
                folder_id = folder['id']
                self.log_success(f"Folder created: {folder['name']} (ID: {folder_id})")
            else:
                self.log_issue(f"Failed to create folder: {response.status_code}")
                self.log_info(f"Response: {response.text}")
                return False
            
            # Create file
            file_data = {
                "sessionId": self.test_session_id,
                "name": "debug_file.py",
                "type": "file",
                "content": "print('Debug test successful!')"
            }
            
            response = requests.post(f"{BASE_URL}/api/vibe/files", json=file_data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                file = response.json()
                file_id = file['id']
                self.log_success(f"File created: {file['name']} (ID: {file_id})")
            else:
                self.log_issue(f"Failed to create file: {response.status_code}")
                self.log_info(f"Response: {response.text}")
                return False
                
        except Exception as e:
            self.log_issue(f"File creation error: {str(e)}")
            return False
        
        try:
            # Test persistence
            self.log_info("Testing file persistence...")
            response = requests.get(f"{BASE_URL}/api/vibe/files", 
                                  params={"sessionId": self.test_session_id}, 
                                  headers=headers, timeout=10)
            
            if response.status_code == 200:
                files_data = response.json()
                file_count = files_data['total']
                self.log_success(f"Persistence working: found {file_count} files")
                
                if file_count < 2:
                    self.log_issue("Not all files were persisted")
                    return False
            else:
                self.log_issue(f"Failed to retrieve files: {response.status_code}")
                return False
                
        except Exception as e:
            self.log_issue(f"Persistence test error: {str(e)}")
            return False
        
        try:
            # Test drag and drop
            self.log_info("Testing drag and drop (move operation)...")
            move_data = {
                "targetParentId": folder_id
            }
            
            response = requests.put(f"{BASE_URL}/api/vibe/files/{file_id}/move", 
                                  json=move_data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                moved_file = response.json()
                self.log_success(f"Drag and drop working: file moved to {moved_file['path']}")
            else:
                self.log_issue(f"Drag and drop failed: {response.status_code}")
                self.log_info(f"Response: {response.text}")
                return False
                
        except Exception as e:
            self.log_issue(f"Drag and drop error: {str(e)}")
            return False
        
        try:
            # Test tree structure
            self.log_info("Testing tree structure...")
            response = requests.get(f"{BASE_URL}/api/vibe/files/tree", 
                                  params={"sessionId": self.test_session_id}, 
                                  headers=headers, timeout=10)
            
            if response.status_code == 200:
                tree_data = response.json()
                root_count = len(tree_data['tree'])
                self.log_success(f"Tree structure working: {root_count} root items")
                
                # Print tree structure
                def print_tree(items, indent=0):
                    for item in items:
                        prefix = "  " * indent
                        icon = "📁" if item['type'] == 'folder' else "📄"
                        print(f"{prefix}{icon} {item['name']}")
                        if item.get('children'):
                            print_tree(item['children'], indent + 1)
                
                print("Current tree structure:")
                print_tree(tree_data['tree'])
                
            else:
                self.log_issue(f"Failed to get tree structure: {response.status_code}")
                return False
                
        except Exception as e:
            self.log_issue(f"Tree structure error: {str(e)}")
            return False
        
        return True

    def generate_report(self):
        """Generate a comprehensive debug report"""
        print("\n📋 DEBUG REPORT")
        print("=" * 50)
        
        if not self.issues_found:
            print("🎉 NO ISSUES FOUND!")
            print("Your Vibe Files system is working correctly.")
            print("\nIf you're still having problems:")
            print("1. The issue might be in your frontend code")
            print("2. Check browser console for JavaScript errors")
            print("3. Verify API calls are using correct endpoints")
            print("4. Make sure authentication tokens are being sent")
        else:
            print(f"❌ FOUND {len(self.issues_found)} ISSUES:")
            for i, issue in enumerate(self.issues_found, 1):
                print(f"   {i}. {issue}")
        
        if self.fixes_applied:
            print(f"\n✅ APPLIED {len(self.fixes_applied)} FIXES:")
            for i, fix in enumerate(self.fixes_applied, 1):
                print(f"   {i}. {fix}")
        
        print("\n🔧 RECOMMENDED ACTIONS:")
        if "vibe_files table does not exist" in self.issues_found:
            print("   - Restart your backend server to trigger table creation")
        if "Cannot connect to server" in str(self.issues_found):
            print("   - Make sure your backend server is running")
        if "Database error" in str(self.issues_found):
            print("   - Check your database connection settings")
        if "Authentication" in str(self.issues_found):
            print("   - Check your JWT configuration")
        
        print("\n📁 FRONTEND INTEGRATION:")
        print("If backend tests pass but frontend doesn't work, use this code:")
        print("""
// Correct drag and drop implementation
const moveFile = async (fileId, targetFolderId, authToken) => {
  const response = await fetch(`/api/vibe/files/${fileId}/move`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${authToken}`
    },
    body: JSON.stringify({
      targetParentId: targetFolderId
    })
  });
  return response.json();
};

// Get files with persistence
const getFiles = async (sessionId, authToken) => {
  const response = await fetch(`/api/vibe/files?sessionId=${sessionId}`, {
    headers: { 'Authorization': `Bearer ${authToken}` }
  });
  return response.json();
};
        """)

async def main():
    """Main debugging function"""
    debugger = VibeFilesDebugger()
    
    print("🐛 VIBE FILES COMPREHENSIVE DEBUGGER")
    print("This will identify and fix all issues with your file system")
    print("=" * 60)
    
    # Step 1: Debug database
    db_ok = await debugger.debug_database_connection()
    
    # Step 2: Debug server
    server_ok = debugger.debug_server_connection()
    
    # Step 3: Debug authentication
    auth_ok = debugger.debug_authentication()
    
    # Step 4: Debug file operations
    files_ok = debugger.debug_file_operations()
    
    # Generate final report
    debugger.generate_report()
    
    # Overall status
    if db_ok and server_ok and auth_ok and files_ok:
        print("\n🎉 ALL SYSTEMS WORKING!")
        print("Your Vibe Files backend is fully functional.")
    else:
        print("\n⚠️  ISSUES DETECTED")
        print("Follow the recommended actions above to fix the problems.")

if __name__ == "__main__":
    asyncio.run(main())