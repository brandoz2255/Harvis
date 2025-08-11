#!/usr/bin/env python3
"""
Test script for Ollama cloud/local fallback system
"""

import os
import sys
import logging
import requests

# Add the current directory to the path so we can import from main.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import the fallback functions from main.py
from main import make_ollama_request, make_ollama_get_request, get_ollama_url

def test_ollama_fallback():
    """Test the Ollama fallback system"""
    print("🧪 Testing Ollama Cloud/Local Fallback System")
    print("=" * 50)
    
    # Test 1: Get working Ollama URL
    print("\n1. Testing get_ollama_url()...")
    try:
        working_url = get_ollama_url()
        print(f"✅ Working Ollama URL: {working_url}")
    except Exception as e:
        print(f"❌ Failed to get working URL: {e}")
        return False
    
    # Test 2: Test GET request (list models)
    print("\n2. Testing make_ollama_get_request() - List models...")
    try:
        response = make_ollama_get_request("/api/tags", timeout=10)
        if response.status_code == 200:
            models = response.json().get("models", [])
            print(f"✅ Successfully retrieved {len(models)} models")
            for model in models[:3]:  # Show first 3 models
                print(f"   - {model.get('name', 'Unknown')}")
        else:
            print(f"⚠️ GET request returned status {response.status_code}")
    except Exception as e:
        print(f"❌ GET request failed: {e}")
    
    # Test 3: Test POST request (simple chat)
    print("\n3. Testing make_ollama_request() - Simple chat...")
    try:
        payload = {
            "model": "llama3.2:3b",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant. Respond with exactly 'Hello, world!' and nothing else."},
                {"role": "user", "content": "Say hello"}
            ],
            "stream": False
        }
        
        response = make_ollama_request("/api/chat", payload, timeout=30)
        if response.status_code == 200:
            content = response.json().get("message", {}).get("content", "").strip()
            print(f"✅ Chat request successful")
            print(f"   Response: {content}")
        else:
            print(f"⚠️ Chat request returned status {response.status_code}")
    except Exception as e:
        print(f"❌ Chat request failed: {e}")
    
    print("\n🎉 Ollama fallback system test completed!")
    return True

if __name__ == "__main__":
    test_ollama_fallback()