#!/usr/bin/env python3
"""
Main script for running n8n workflow embedding operations.

This script provides a command-line interface for:
- Processing local n8n workflow files 
- Generating embeddings using sentence transformers
- Storing embeddings in pgvector PostgreSQL database
- Searching workflows by semantic similarity

Usage:
    python main.py --help
    python main.py embed --all
    python main.py embed --repo n8n_workflows
    python main.py search "email automation workflow"
    python main.py stats
"""

import argparse
import logging
import sys
import json
from typing import Dict, Any

from config import EmbeddingConfig
from embedding_manager import EmbeddingManager
from workflow_processor import WorkflowProcessor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def setup_embedding_manager() -> EmbeddingManager:
    """Initialize the embedding manager with configuration."""
    config = EmbeddingConfig.from_env()
    logger.info(f"Using configuration: {config.collection_name}")
    
    manager = EmbeddingManager(config)
    
    # Setup database and vector store
    manager.setup_database()
    manager.initialize_vector_store()
    
    return manager

def embed_all_workflows(manager: EmbeddingManager) -> Dict[str, Any]:
    """Process and embed all configured workflow directories."""
    logger.info("Starting to embed all workflows...")
    return manager.process_all_workflow_directories()

def embed_single_repo(manager: EmbeddingManager, repo_name: str) -> Dict[str, Any]:
    """Process and embed workflows from a single repository."""
    config = manager.config
    workflow_paths = config.get_workflow_paths()
    
    if repo_name not in workflow_paths:
        raise ValueError(f"Unknown repository: {repo_name}. Available: {list(workflow_paths.keys())}")
    
    directory_path = workflow_paths[repo_name]
    logger.info(f"Embedding workflows from {repo_name} at {directory_path}")
    
    return manager.add_workflows_from_directory(directory_path, repo_name)

def search_workflows(manager: EmbeddingManager, query: str, k: int = 5) -> Dict[str, Any]:
    """Search for workflows using semantic similarity."""
    logger.info(f"Searching for: '{query}'")
    
    results = manager.search_workflows_with_score(query, k=k)
    
    search_results = []
    for doc, score in results:
        result = {
            "filename": doc.metadata.get("filename", "Unknown"),
            "name": doc.metadata.get("name", "Unknown"),
            "description": doc.metadata.get("description", ""),
            "score": float(score),
            "source_repo": doc.metadata.get("source_repo", "unknown"),
            "node_types": doc.metadata.get("node_types", []),
            "content_preview": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
        }
        search_results.append(result)
    
    return {
        "query": query,
        "results_count": len(search_results),
        "results": search_results
    }

def get_collection_stats(manager: EmbeddingManager) -> Dict[str, Any]:
    """Get statistics about the current collection."""
    logger.info("Getting collection statistics...")
    return manager.get_collection_stats()

def test_embedding_system(manager: EmbeddingManager) -> Dict[str, Any]:
    """Test the embedding system with sample data."""
    logger.info("Testing embedding system...")
    
    # Test embedding generation
    embedding_test = manager.test_embedding_pipeline()
    
    # Test workflow processing
    processor = WorkflowProcessor()
    config = manager.config
    
    workflow_stats = {}
    for repo_name, path in config.get_workflow_paths().items():
        stats = processor.get_workflow_statistics(path)
        workflow_stats[repo_name] = stats
    
    return {
        "embedding_test": embedding_test,
        "workflow_statistics": workflow_stats,
        "config": config.to_dict()
    }

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="n8n Workflow Embedding System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py embed --all                    # Embed all workflow repositories
  python main.py embed --repo n8n_workflows     # Embed only n8n_workflows repo
  python main.py search "email automation"      # Search for email automation workflows
  python main.py search "slack integration" -k 10  # Get top 10 results
  python main.py stats                          # Show collection statistics
  python main.py test                           # Test the system
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Embed command
    embed_parser = subparsers.add_parser('embed', help='Embed workflows into vector database')
    embed_group = embed_parser.add_mutually_exclusive_group(required=True)
    embed_group.add_argument('--all', action='store_true', help='Process all workflow repositories')
    embed_group.add_argument('--repo', type=str, help='Process specific repository (n8n_workflows, test_workflows)')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search workflows by similarity')
    search_parser.add_argument('query', type=str, help='Search query')
    search_parser.add_argument('-k', '--results', type=int, default=5, help='Number of results to return')
    
    # Stats command
    subparsers.add_parser('stats', help='Show collection statistics')
    
    # Test command
    subparsers.add_parser('test', help='Test the embedding system')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete collection')
    delete_parser.add_argument('--confirm', action='store_true', help='Confirm deletion')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        # Initialize embedding manager
        manager = setup_embedding_manager()
        
        if args.command == 'embed':
            if args.all:
                result = embed_all_workflows(manager)
            else:
                result = embed_single_repo(manager, args.repo)
            
            print(json.dumps(result, indent=2))
        
        elif args.command == 'search':
            result = search_workflows(manager, args.query, args.results)
            print(json.dumps(result, indent=2))
        
        elif args.command == 'stats':
            result = get_collection_stats(manager)
            print(json.dumps(result, indent=2))
        
        elif args.command == 'test':
            result = test_embedding_system(manager)
            print(json.dumps(result, indent=2))
        
        elif args.command == 'delete':
            if not args.confirm:
                print("This will delete the entire collection. Use --confirm to proceed.")
                return
            
            manager.delete_collection()
            print(f"Collection '{manager.config.collection_name}' deleted successfully")
    
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()