"""
Workflow processor for extracting and formatting n8n workflow content.
"""

import json
import os
from typing import List, Dict, Any, Optional, Generator, Tuple
from pathlib import Path
import logging
from dataclasses import dataclass

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

@dataclass
class WorkflowMetadata:
    """Metadata extracted from n8n workflow."""
    filename: str
    workflow_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = None
    node_count: int = 0
    trigger_types: List[str] = None
    node_types: List[str] = None
    source_repo: str = "unknown"
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.trigger_types is None:
            self.trigger_types = []
        if self.node_types is None:
            self.node_types = []

class WorkflowProcessor:
    """Process n8n workflow JSON files and extract meaningful content for embedding."""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
    def process_workflow_file(self, file_path: str, source_repo: str = "unknown") -> List[Document]:
        """Process a single n8n workflow JSON file and return LangChain Documents."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
            
            # Handle both dict and list formats
            if isinstance(raw_data, list):
                if not raw_data:
                    logger.warning(f"Empty array in workflow file: {file_path}")
                    return []
                # Take the first item if it's a list of workflows
                workflow_data = raw_data[0] if isinstance(raw_data[0], dict) else {}
                logger.debug(f"Processing array-format workflow: {file_path}")
            elif isinstance(raw_data, dict):
                workflow_data = raw_data
            else:
                logger.error(f"Unsupported JSON format in {file_path}: {type(raw_data)}")
                return []
            
            metadata = self._extract_metadata(workflow_data, file_path, source_repo)
            content = self._extract_content(workflow_data)
            
            # Create the main document
            main_doc = Document(
                page_content=content,
                metadata={
                    "filename": metadata.filename,
                    "workflow_id": metadata.workflow_id,
                    "name": metadata.name,
                    "description": metadata.description,
                    "tags": metadata.tags,
                    "node_count": metadata.node_count,
                    "trigger_types": metadata.trigger_types,
                    "node_types": metadata.node_types,
                    "source_repo": metadata.source_repo,
                    "document_type": "n8n_workflow",
                    "file_path": file_path
                }
            )
            
            # If content is too long, chunk it
            if len(content) > self.chunk_size:
                return self._chunk_document(main_doc)
            else:
                return [main_doc]
                
        except Exception as e:
            import traceback
            logger.error(f"Error processing workflow file {file_path}: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return []
    
    def process_directory(self, directory_path: str, source_repo: str = "unknown", 
                         max_files: Optional[int] = None) -> Generator[Document, None, None]:
        """Process all JSON workflow files in a directory."""
        if not os.path.exists(directory_path):
            logger.error(f"Directory does not exist: {directory_path}")
            return
            
        json_files = list(Path(directory_path).glob("*.json"))
        
        if max_files:
            json_files = json_files[:max_files]
            
        logger.info(f"Processing {len(json_files)} workflow files from {directory_path}")
        
        for i, file_path in enumerate(json_files):
            logger.debug(f"Processing file {i+1}/{len(json_files)}: {file_path.name}")
            documents = self.process_workflow_file(str(file_path), source_repo)
            
            for doc in documents:
                yield doc
    
    def _extract_metadata(self, workflow_data: Dict[str, Any], file_path: str, 
                         source_repo: str) -> WorkflowMetadata:
        """Extract metadata from workflow JSON."""
        filename = os.path.basename(file_path)
        
        # Extract basic workflow info with safe defaults
        workflow_id = workflow_data.get('id')
        name = workflow_data.get('name', filename.replace('.json', ''))
        description = workflow_data.get('description', '')
        tags = workflow_data.get('tags', [])
        
        # Ensure tags is a list
        if not isinstance(tags, list):
            tags = []
        
        # Extract nodes information
        nodes = workflow_data.get('nodes', [])
        if not isinstance(nodes, list):
            nodes = []
        node_count = len(nodes)
        
        # Extract node types and trigger types
        node_types = []
        trigger_types = []
        
        for node in nodes:
            if not isinstance(node, dict):
                continue
                
            node_type = node.get('type', '')
            if node_type:
                node_types.append(node_type)
                
                # Check if it's a trigger node
                if (node.get('typeVersion', 0) >= 1 and 
                    ('trigger' in node_type.lower() or 
                     node_type in ['Webhook', 'Cron', 'Manual Trigger', 'Schedule Trigger'])):
                    trigger_types.append(node_type)
        
        # Remove duplicates
        node_types = list(set(node_types))
        trigger_types = list(set(trigger_types))
        
        return WorkflowMetadata(
            filename=filename,
            workflow_id=workflow_id,
            name=name,
            description=description,
            tags=tags,
            node_count=node_count,
            trigger_types=trigger_types,
            node_types=node_types,
            source_repo=source_repo
        )
    
    def _extract_content(self, workflow_data: Dict[str, Any]) -> str:
        """Extract meaningful text content from workflow for embedding."""
        content_parts = []
        
        try:
            # Add workflow name and description
            if workflow_data.get('name'):
                content_parts.append(f"Workflow Name: {workflow_data['name']}")
            
            if workflow_data.get('description'):
                content_parts.append(f"Description: {workflow_data['description']}")
            
            # Add tags
            tags = workflow_data.get('tags', [])
            if tags and isinstance(tags, list):
                try:
                    content_parts.append(f"Tags: {', '.join(str(tag) for tag in tags)}")
                except Exception:
                    content_parts.append(f"Tags: [complex tags structure]")
            
            # Process nodes
            nodes = workflow_data.get('nodes', [])
            if nodes and isinstance(nodes, list):
                content_parts.append("\nWorkflow Nodes:")
                
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                        
                    node_info = []
                    
                    # Node name and type
                    node_name = node.get('name', 'Unknown')
                    node_type = node.get('type', 'Unknown')
                    node_info.append(f"- {node_name} ({node_type})")
                    
                    # Node parameters (extract meaningful ones)
                    parameters = node.get('parameters', {})
                    if parameters and isinstance(parameters, dict):
                        meaningful_params = self._extract_meaningful_parameters(parameters)
                        if meaningful_params:
                            node_info.append(f"  Parameters: {meaningful_params}")
                    
                    # Node notes/description
                    if node.get('notes'):
                        node_info.append(f"  Notes: {node['notes']}")
                    
                    content_parts.append('\n'.join(node_info))
        
            # Add connections info (simplified)
            connections = workflow_data.get('connections', {})
            if connections:
                connection_summary = self._summarize_connections(connections)
                if connection_summary:
                    content_parts.append(f"\nWorkflow Flow: {connection_summary}")
            
            return '\n\n'.join(content_parts)
            
        except Exception as e:
            logger.error(f"Error in _extract_content: {e}")
            import traceback
            logger.error(f"_extract_content traceback: {traceback.format_exc()}")
            # Return basic info if available
            try:
                name = workflow_data.get('name', 'Unknown Workflow')
                return f"Workflow Name: {name}\n[Error extracting additional content]"
            except:
                return "[Error extracting workflow content]"
    
    def _extract_meaningful_parameters(self, parameters: Dict[str, Any]) -> str:
        """Extract meaningful parameters from node configuration."""
        meaningful_params = []
        
        # Common meaningful parameter keys
        meaningful_keys = [
            'url', 'method', 'resource', 'operation', 'expression', 
            'field', 'value', 'conditions', 'rules', 'message', 'text',
            'subject', 'body', 'to', 'from', 'query', 'table', 'database',
            'webhook_url', 'api_key', 'endpoint'
        ]
        
        for key, value in parameters.items():
            if key.lower() in meaningful_keys and value:
                if isinstance(value, (str, int, bool)):
                    # Truncate long strings
                    str_value = str(value)
                    if len(str_value) > 100:
                        str_value = str_value[:100] + "..."
                    meaningful_params.append(f"{key}: {str_value}")
                elif isinstance(value, dict) and value:
                    meaningful_params.append(f"{key}: [complex object]")
                elif isinstance(value, list) and value:
                    # Handle list of strings vs list of dicts
                    if all(isinstance(item, str) for item in value):
                        list_str = ', '.join(str(item)[:50] for item in value[:3])  # First 3 items, truncated
                        if len(value) > 3:
                            list_str += f" (and {len(value)-3} more)"
                        meaningful_params.append(f"{key}: [{list_str}]")
                    else:
                        meaningful_params.append(f"{key}: [list with {len(value)} items]")
        
        return ', '.join(meaningful_params) if meaningful_params else ""
    
    def _summarize_connections(self, connections: Dict[str, Any]) -> str:
        """Create a summary of workflow connections/flow."""
        connection_parts = []
        
        for source_node, targets in connections.items():
            if isinstance(targets, dict):
                for output_index, target_list in targets.items():
                    if isinstance(target_list, list):
                        for target in target_list:
                            if isinstance(target, dict):
                                target_node = target.get('node')
                                if target_node:
                                    connection_parts.append(f"{source_node} → {target_node}")
                            elif isinstance(target, list):
                                # Handle nested list structures
                                for nested_target in target:
                                    if isinstance(nested_target, dict):
                                        target_node = nested_target.get('node')
                                        if target_node:
                                            connection_parts.append(f"{source_node} → {target_node}")
        
        return ', '.join(connection_parts[:10])  # Limit to first 10 connections
    
    def _chunk_document(self, document: Document) -> List[Document]:
        """Split a large document into smaller chunks while preserving metadata."""
        content = document.page_content
        chunks = []
        
        for i in range(0, len(content), self.chunk_size - self.chunk_overlap):
            chunk_content = content[i:i + self.chunk_size]
            
            # Update metadata with chunk info
            chunk_metadata = document.metadata.copy()
            chunk_metadata.update({
                "chunk_index": len(chunks),
                "is_chunk": True,
                "total_chunks": None  # Will be updated after all chunks are created
            })
            
            chunks.append(Document(
                page_content=chunk_content,
                metadata=chunk_metadata
            ))
        
        # Update total_chunks in all chunk metadata
        for chunk in chunks:
            chunk.metadata["total_chunks"] = len(chunks)
        
        return chunks
    
    def get_workflow_statistics(self, directory_path: str) -> Dict[str, Any]:
        """Get statistics about workflows in a directory."""
        if not os.path.exists(directory_path):
            return {"error": f"Directory does not exist: {directory_path}"}
        
        json_files = list(Path(directory_path).glob("*.json"))
        total_files = len(json_files)
        
        node_types = set()
        trigger_types = set()
        total_nodes = 0
        
        for file_path in json_files[:100]:  # Sample first 100 files for stats
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                
                # Handle both dict and list formats (same as main processing)
                if isinstance(raw_data, list):
                    if not raw_data:
                        continue
                    workflow_data = raw_data[0] if isinstance(raw_data[0], dict) else {}
                elif isinstance(raw_data, dict):
                    workflow_data = raw_data
                else:
                    continue
                
                nodes = workflow_data.get('nodes', [])
                if not isinstance(nodes, list):
                    continue
                    
                total_nodes += len(nodes)
                
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    node_type = node.get('type', '')
                    if node_type:
                        node_types.add(node_type)
                        if 'trigger' in node_type.lower():
                            trigger_types.add(node_type)
                            
            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
        
        return {
            "total_workflows": total_files,
            "unique_node_types": len(node_types),
            "unique_trigger_types": len(trigger_types),
            "average_nodes_per_workflow": total_nodes / min(100, total_files) if total_files > 0 else 0,
            "sample_node_types": list(node_types)[:20],  # First 20 node types
            "sample_trigger_types": list(trigger_types)
        }