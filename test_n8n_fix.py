#!/usr/bin/env python3
"""
Test script to verify n8n workflow creation fix
"""

import sys
import os
sys.path.append('/home/guruai/compose/aidev/python_back_end')

from n8n.client import N8nClient
from n8n.workflow_builder import WorkflowBuilder

def test_workflow_creation():
    """Test creating a simple workflow to verify the fix"""
    print("🔧 Testing n8n workflow creation fix...")
    
    try:
        # Initialize client
        client = N8nClient()
        print(f"✅ Client initialized for {client.base_url}")
        
        # Test connection
        if not client.test_connection():
            print("❌ Connection test failed")
            return False
        print("✅ Connection test passed")
        
        # Create a simple workflow using the builder
        builder = WorkflowBuilder()
        
        # Create a simple workflow with nodes that would include 'active' field
        nodes = [
            {
                "name": "Manual Trigger",
                "type": "n8n-nodes-base.manualTrigger",
                "parameters": {}
            },
            {
                "name": "Test HTTP Request",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {
                    "url": "https://httpbin.org/json",
                    "requestMethod": "GET"
                }
            }
        ]
        
        workflow_config = builder.build_simple_workflow(
            name="Test Workflow - Active Field Fix", 
            nodes=nodes
        )
        
        print(f"🏗️  Built workflow config with {len(workflow_config.nodes)} nodes")
        print(f"📊 Config includes 'active' field: {'active' in workflow_config.dict()}")
        
        # Convert to dict (this will include the 'active' field)
        workflow_dict = workflow_config.dict()
        print(f"📝 Workflow dict keys: {list(workflow_dict.keys())}")
        
        # Try to create the workflow (this should sanitize the payload)
        print("🚀 Creating workflow...")
        result = client.create_workflow(workflow_dict)
        
        print("✅ SUCCESS: Workflow created successfully!")
        print(f"📋 Created workflow ID: {result.get('id', 'unknown')}")
        print(f"📋 Workflow name: {result.get('name', 'unknown')}")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

if __name__ == "__main__":
    success = test_workflow_creation()
    sys.exit(0 if success else 1)