#!/usr/bin/env python3
"""
Test script for n8n workflow builder AI analysis fix
Tests that AI-identified nodes are properly used instead of generic templates
"""

import sys
import os
import logging
from typing import Dict, Any

# Add the current directory to path so we can import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from n8n.workflow_builder import WorkflowBuilder

# Set up logging to see debug information
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

def test_ai_workflow_building():
    """Test that AI-specified nodes are properly used"""
    builder = WorkflowBuilder()
    
    # Simulate AI analysis that identifies specific nodes
    ai_analysis_requirements = {
        "trigger": "manual",
        "nodes_required": [
            "@n8n/n8n-nodes-langchain.agent",
            "n8n-nodes-base.youTube", 
            "n8n-nodes-base.code"
        ],
        "parameters": {
            "model": "mistral",
            "temperature": 0.7,
            "youtube_operation": "search",
            "query": "AI automation",
            "max_results": 5,
            "code": "// Process YouTube results\nreturn items.map(item => ({json: {title: item.json.title, url: item.json.url}}));"
        },
        "keywords": ["langchain", "youtube", "automation"]
    }
    
    print("=" * 60)
    print("TESTING N8N WORKFLOW BUILDER FIX")
    print("=" * 60)
    
    print(f"AI Analysis Requirements:")
    print(f"  - Trigger: {ai_analysis_requirements['trigger']}")
    print(f"  - Nodes Required: {ai_analysis_requirements['nodes_required']}")
    print(f"  - Parameters: {list(ai_analysis_requirements['parameters'].keys())}")
    print()
    
    # Build workflow using AI analysis
    workflow = builder.build_ai_workflow(
        name="Test AI Workflow",
        description="Test workflow with AI-identified nodes", 
        requirements=ai_analysis_requirements
    )
    
    print("WORKFLOW BUILT SUCCESSFULLY!")
    print(f"Workflow Name: {workflow.name}")
    print(f"Number of Nodes: {len(workflow.nodes)}")
    print()
    
    print("NODES CREATED:")
    for i, node in enumerate(workflow.nodes, 1):
        print(f"{i}. {node.name}")
        print(f"   Type: {node.type}")
        print(f"   Parameters: {list(node.parameters.keys()) if node.parameters else 'None'}")
        if node.parameters:
            # Show a few key parameters
            for key, value in list(node.parameters.items())[:3]:
                print(f"     {key}: {str(value)[:50]}{'...' if len(str(value)) > 50 else ''}")
        print()
    
    print("CONNECTIONS:")
    for from_node, connections in workflow.connections.items():
        for conn_type, conn_list in connections.items():
            for conn_group in conn_list:
                for conn in conn_group:
                    print(f"  {from_node} -> {conn.node}")
    print()
    
    # Verify that we got the expected nodes
    node_types = [node.type for node in workflow.nodes]
    expected_nodes = ai_analysis_requirements["nodes_required"]
    
    print("VERIFICATION:")
    success = True
    
    # Check if we have a trigger (manual trigger should be added automatically)
    has_trigger = any("trigger" in node_type.lower() or "manual" in node_type.lower() 
                     for node_type in node_types)
    if has_trigger:
        print("✓ Trigger node found")
    else:
        print("✗ No trigger node found")
        success = False
    
    # Check each expected node type
    for expected_node in expected_nodes:
        if expected_node in node_types:
            print(f"✓ Found expected node: {expected_node}")
        else:
            print(f"✗ Missing expected node: {expected_node}")
            success = False
    
    # Check that we don't have unwanted generic nodes
    unwanted_nodes = ["n8n-nodes-base.emailSend", "n8n-nodes-base.scheduleTrigger"]
    for unwanted in unwanted_nodes:
        if unwanted in node_types:
            print(f"✗ Found unwanted generic node: {unwanted}")
            success = False
        else:
            print(f"✓ No unwanted generic node: {unwanted}")
    
    print()
    if success:
        print("🎉 SUCCESS: All AI-identified nodes were properly used!")
        print("The workflow builder fix is working correctly.")
    else:
        print("❌ FAILURE: Workflow builder is not using AI-identified nodes properly.")
        print("Check the logs above for details.")
    
    return success

if __name__ == "__main__":
    test_ai_workflow_building()