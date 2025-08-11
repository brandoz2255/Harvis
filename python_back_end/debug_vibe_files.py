#!/usr/bin/env python3
"""
Debug script for Vibe Files API issues
"""

import requests
import json
import sys

def test_vibe_files_debug():
    """Test the vibe files endpoints with debugging"""
    
    BASE_URL = "http://localhost:8000"  # Adjust if needed
    SESSION_ID = "offline-1754590164569"
    
    print("🔍 Debugging Vibe Files API")
    print("=" * 40)
    
    # Test 1: Check if server is running
    print("\n1. Testing server availability...")
    try:
        response = requests.get(f"{BASE_URL}/docs", timeout=5)
        if response.status_code == 200:
            print("✅ Server is running")
        else:
            print(f"⚠️ Server returned {response.status_code}")
    except Exception as e:
        print(f"❌ Server not accessible: {e}")
        return
    
    # Test 2: Test without authentication (should fail with 401)
    print("\n2. Testing files endpoint without auth (should fail with 401)...")
    try:
        response = requests.get(
            f"{BASE_URL}/api/vibe/files",
            params={"sessionId": SESSION_ID}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
        
        if response.status_code == 422:
            print("🔍 422 Error - This suggests validation failed")
            try:
                error_detail = response.json()
                print(f"Error details: {json.dumps(error_detail, indent=2)}")
            except:
                pass
        elif response.status_code == 401:
            print("✅ Expected 401 - Authentication required")
        
    except Exception as e:
        print(f"Error: {e}")
    
    # Test 3: Test debug auth endpoint without auth
    print("\n3. Testing debug auth endpoint without auth...")
    try:
        response = requests.get(f"{BASE_URL}/api/vibe/debug/auth")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n💡 Next steps:")
    print("1. Make sure you're authenticated when making the request")
    print("2. Check that the JWT token is valid and not expired")
    print("3. Verify the sessionId parameter is being sent correctly")
    print("4. Check server logs for more detailed error information")

if __name__ == "__main__":
    test_vibe_files_debug()