#!/usr/bin/env python3
"""
Test script to verify n8n API connection and authentication
"""

import os
import sys
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_n8n_connection():
    """Test n8n API connection with basic auth"""
    
    # Get configuration from environment
    n8n_url = os.getenv("N8N_URL", "http://n8n:5678")
    n8n_user = os.getenv("N8N_USER", "admin")
    n8n_password = os.getenv("N8N_PASSWORD", "adminpass")
    
    print(f"Testing n8n connection to: {n8n_url}")
    print(f"Using basic auth with user: {n8n_user}")
    
    # Test endpoint
    url = f"{n8n_url}/rest/workflows"
    
    try:
        # Make request with basic auth
        response = requests.get(
            url,
            auth=HTTPBasicAuth(n8n_user, n8n_password),
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            workflows = response.json()
            print(f"✅ SUCCESS: Retrieved {len(workflows)} workflows")
            return True
        else:
            print(f"❌ FAILED: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ CONNECTION ERROR: {e}")
        return False

def test_workflow_creation():
    """Test creating a simple workflow"""
    
    n8n_url = os.getenv("N8N_URL", "http://n8n:5678")
    n8n_user = os.getenv("N8N_USER", "admin")
    n8n_password = os.getenv("N8N_PASSWORD", "adminpass")
    
    # Simple test workflow
    workflow_data = {
        "name": "Test Workflow - Connection Test",
        "nodes": [
            {
                "id": "start",
                "name": "Start",
                "type": "n8n-nodes-base.start",
                "position": [240, 300],
                "parameters": {}
            }
        ],
        "connections": {},
        "active": False
    }
    
    url = f"{n8n_url}/rest/workflows"
    
    try:
        response = requests.post(
            url,
            json=workflow_data,
            auth=HTTPBasicAuth(n8n_user, n8n_password),
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        print(f"Create workflow response: {response.status_code}")
        
        if response.status_code == 200:
            workflow = response.json()
            workflow_id = workflow.get('id')
            print(f"✅ SUCCESS: Created test workflow with ID: {workflow_id}")
            
            # Clean up - delete the test workflow
            delete_url = f"{n8n_url}/rest/workflows/{workflow_id}"
            delete_response = requests.delete(
                delete_url,
                auth=HTTPBasicAuth(n8n_user, n8n_password),
                timeout=10
            )
            print(f"Cleanup: Deleted test workflow (status: {delete_response.status_code})")
            return True
        else:
            print(f"❌ FAILED: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ CONNECTION ERROR: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("n8n API Connection Test")
    print("=" * 50)
    
    # Test 1: Basic connection
    print("\n1. Testing basic connection...")
    connection_ok = test_n8n_connection()
    
    if connection_ok:
        # Test 2: Workflow creation
        print("\n2. Testing workflow creation...")
        creation_ok = test_workflow_creation()
        
        if creation_ok:
            print("\n🎉 All tests passed! n8n API is working correctly.")
        else:
            print("\n⚠️ Connection works but workflow creation failed.")
    else:
        print("\n❌ Basic connection failed. Check your n8n configuration.")
    
    print("\n" + "=" * 50)