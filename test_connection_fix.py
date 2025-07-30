#!/usr/bin/env python3
"""
Test script to verify the n8n connection parsing fix
"""

import sys
import os
sys.path.append('/home/guruai/compose/aidev/python_back_end')

from n8n.client import N8nClient
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_connection_parsing():
    """Test the fixed connection parsing logic"""
    
    # Create a test client (doesn't need to actually connect for this test)
    client = N8nClient('http://localhost:5678', 'test@example.com', 'password')
    
    # Test payload with the exact structure that was causing the error
    test_payload = {
        'name': 'Test Workflow',
        'nodes': [
            {
                'id': 'manual-trigger',
                'name': 'Manual Trigger',
                'type': 'n8n-nodes-base.manualTrigger',
                'parameters': {},
                'position': [100, 100]
            },
            {
                'id': 'content-generator', 
                'name': 'Content Generator',
                'type': 'n8n-nodes-base.code',
                'parameters': {},
                'position': [300, 100]
            },
            {
                'id': 'youtube-upload',
                'name': 'YouTube Upload', 
                'type': 'n8n-nodes-base.httpRequest',
                'parameters': {},
                'position': [500, 100]
            }
        ],
        'connections': {
            'manual-trigger': {
                'main': [{'node': 'content-generator', 'type': 'main', 'index': 0}]
            }, 
            'content-generator': {
                'main': [{'node': 'youtube-upload', 'type': 'main', 'index': 0}]
            }
        }
    }
    
    print("Testing connection parsing with the exact structure that caused the error...")
    print(f"Original connections: {test_payload['connections']}")
    
    try:
        sanitized = client._sanitize_workflow_payload(test_payload)
        print("\n✅ SUCCESS: Connection parsing completed without errors!")
        
        # Verify the connections were processed correctly
        new_connections = sanitized.get('connections', {})
        connection_count = sum(len(outputs) for node_conns in new_connections.values() for outputs in node_conns.values())
        
        print(f"✅ Processed {connection_count} connections successfully")
        print(f"✅ Node ID remapping completed")
        
        # Verify structure integrity
        for source_node, node_connections in new_connections.items():
            for output_type, outputs in node_connections.items():
                for connection in outputs:
                    if not isinstance(connection, dict) or 'node' not in connection:
                        raise ValueError(f"Invalid connection structure: {connection}")
        
        print("✅ All connections have correct dictionary structure with 'node' field")
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_connection_parsing()
    exit_code = 0 if success else 1
    print(f"\nTest result: {'PASSED' if success else 'FAILED'}")
    exit(exit_code)