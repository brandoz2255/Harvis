#!/usr/bin/env python3
"""
Test script for Vibe Files API
"""

import requests
import json
import os

# Test configuration
BASE_URL = "http://localhost:8000"  # Adjust if your server runs on different port
TEST_SESSION_ID = "offline-1754590164569"

def test_vibe_files_endpoint():
    """Test the vibe files endpoint"""
    print("🧪 Testing Vibe Files API")
    print("=" * 40)
    
    # Test 1: GET files without authentication (should fail)
    print("\n1. Testing GET /api/vibe/files without auth (should fail)...")
    try:
        response = requests.get(
            f"{BASE_URL}/api/vibe/files",
            params={"sessionId": TEST_SESSION_ID}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test 2: Check if we can get auth token (you'll need to implement login)
    print("\n2. Testing authentication...")
    print("Note: You'll need to implement proper authentication for full testing")
    
    # Test 3: Check endpoint structure
    print("\n3. Checking endpoint availability...")
    try:
        response = requests.get(f"{BASE_URL}/docs")
        if response.status_code == 200:
            print("✅ FastAPI docs available - server is running")
        else:
            print(f"⚠️ Server response: {response.status_code}")
    except Exception as e:
        print(f"❌ Server not accessible: {e}")

if __name__ == "__main__":
    test_vibe_files_endpoint()