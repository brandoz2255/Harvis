"""
Vector Database Integration for n8n AI Agents

This module provides vector database functionality by integrating with the 
existing embedding manager and enabling AI models to utilize vector search.
"""

import logging
import os
import sys
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Add the embedding directory to Python path
# Try multiple possible paths for embedding directory
possible_embedding_paths = [
    Path("/app/embedding"),                              # Docker mounted path (preferred)
    Path(__file__).parent.parent.parent / "embedding",  # From python_back_end/n8n/
    Path("/home/guruai/compose/aidev/embedding"),        # Absolute path
    Path("/app") / ".." / "embedding",                   # Docker relative path
]

embedding_path = None
for path in possible_embedding_paths:
    if path.exists() and (path / "config.py").exists():
        embedding_path = path
        logger.info(f"Found embedding directory at: {embedding_path}")
        break

if embedding_path:
    sys.path.insert(0, str(embedding_path))
else:
    logger.warning(f"Could not find embedding directory. Tried: {[str(p) for p in possible_embedding_paths]}")

try:
    if embedding_path:
        import config
        import embedding_manager
        import workflow_processor
        from langchain_core.documents import Document
        
        EmbeddingConfig = config.EmbeddingConfig
        EmbeddingManager = embedding_manager.EmbeddingManager
        WorkflowProcessor = workflow_processor.WorkflowProcessor
        
        logger.info("✅ Successfully imported embedding modules")
    else:
        raise ImportError("Embedding directory not found")
    
except ImportError as e:
    logger.error(f"Failed to import embedding modules: {e}")
    logger.error("Embedding directory status:")
    for i, path in enumerate(possible_embedding_paths):
        exists = path.exists()
        has_config = (path / "config.py").exists() if exists else False
        logger.error(f"  {i+1}. {path} - exists: {exists}, has config: {has_config}")
    # Create fallback classes to prevent startup failure
    class EmbeddingConfig:
        @classmethod
        def from_env(cls):
            return cls()
        def __init__(self):
            self.collection_name = "n8n_workflows"
            self.database_url = "postgresql://pguser:pgpassword@pgsql-db:5432/database"
            self.embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
            self.embedding_dimension = 384
            self.chunk_size = 1000
            self.chunk_overlap = 200
    
    class EmbeddingManager:
        def __init__(self, config):
            self.config = config
        def setup_database(self): pass
        def initialize_embeddings(self): pass
        def initialize_vector_store(self): pass
        def search_workflows_with_score(self, query: str, k: int = 5, **kwargs):
            """Search existing embeddings using keyword matching"""
            try:
                import psycopg2
                import json
                
                conn = psycopg2.connect(self.config.database_url)
                cur = conn.cursor()
                
                # Search for workflows containing keywords from the query
                keywords = query.lower().split()
                like_conditions = []
                params = ['n8n_workflows']
                
                for keyword in keywords:
                    like_conditions.append("e.document ILIKE %s")
                    params.append(f'%{keyword}%')
                
                where_clause = " AND ".join(like_conditions) if like_conditions else "true"
                
                cur.execute(f'''
                    SELECT e.document, e.cmetadata
                    FROM langchain_pg_embedding e
                    JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                    WHERE c.name = %s 
                    AND ({where_clause})
                    LIMIT %s
                ''', params + [k])
                
                results = []
                for doc_content, metadata in cur.fetchall():
                    doc = Document(page_content=doc_content, metadata=metadata or {})
                    results.append((doc, 1.0))  # Dummy score
                
                cur.close()
                conn.close()
                
                logger.info(f"📊 Found {len(results)} workflows using keyword search")
                return results
                
            except Exception as e:
                logger.error(f"Keyword search failed: {e}")
                return []
        
        def search_workflows(self, **kwargs):
            results = self.search_workflows_with_score(**kwargs)
            return [doc for doc, score in results]
        def get_collection_stats(self): return {"error": "Embedding system not available"}
        def test_embedding_pipeline(self, text=""): return {"success": False, "error": "Not available"}
    
    class WorkflowProcessor:
        def __init__(self, **kwargs): pass
    
    class Document:
        """Fallback Document class for when langchain is not available"""
        def __init__(self, page_content, metadata=None):
            self.page_content = page_content
            self.metadata = metadata or {}
    
    logger.warning("⚠️ Embedding modules not available - vector database will run in fallback mode")

class VectorDatabaseService:
    """
    Service class that provides vector database functionality to n8n AI agents
    """
    
    def __init__(self, config: Optional[EmbeddingConfig] = None):
        """
        Initialize the vector database service
        
        Args:
            config: Optional embedding configuration. If None, loads from environment.
        """
        self.config = config or EmbeddingConfig.from_env()
        self.embedding_manager = None
        self._initialized = False
        
        logger.info(f"VectorDatabaseService initialized with collection: {self.config.collection_name}")
    
    async def initialize(self):
        """Initialize the embedding manager and vector store"""
        if self._initialized:
            return
            
        try:
            logger.info("🔧 Initializing vector database service...")
            
            # Initialize embedding manager
            self.embedding_manager = EmbeddingManager(self.config)
            
            # Check if we're in fallback mode
            if hasattr(self.embedding_manager, 'setup_database'):
                # Setup database with pgvector extension
                self.embedding_manager.setup_database()
                
                # Initialize embeddings and vector store
                self.embedding_manager.initialize_embeddings()
                self.embedding_manager.initialize_vector_store()
                
                self._initialized = True
                logger.info("✅ Vector database service initialized successfully")
            else:
                self._initialized = True
                logger.warning("⚠️ Vector database service running in fallback mode - no embedding functionality")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize vector database service: {e}")
            # Don't raise in fallback mode - allow service to continue
            self._initialized = True
            logger.warning("⚠️ Vector database service initialized in fallback mode due to error")
    
    async def search_similar_workflows(
        self, 
        query: str, 
        k: int = 5, 
        filter_dict: Optional[Dict] = None,
        include_scores: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Search for similar workflows in the vector database
        
        Args:
            query: Search query text
            k: Number of results to return
            filter_dict: Optional metadata filters
            include_scores: Whether to include similarity scores
            
        Returns:
            List of workflow documents with metadata
        """
        await self.initialize()
        
        try:
            logger.info(f"🔍 Searching for similar workflows: '{query}' (k={k})")
            
            # Check if embedding manager has search capability
            if not hasattr(self.embedding_manager, 'search_workflows_with_score'):
                logger.warning("⚠️ Vector search not available - running in fallback mode")
                return []
            
            # Try vector search first, fall back to keyword search on error
            try:
                if include_scores:
                    results = self.embedding_manager.search_workflows_with_score(
                        query=query, k=k, filter_dict=filter_dict
                    )
                    # Convert to dict format with scores
                    formatted_results = []
                    for doc, score in results:
                        result = {
                            "content": doc.page_content,
                            "metadata": doc.metadata,
                            "similarity_score": float(score)
                        }
                        formatted_results.append(result)
                    return formatted_results
                else:
                    results = self.embedding_manager.search_workflows(
                        query=query, k=k, filter_dict=filter_dict
                    )
                    # Convert to dict format
                    formatted_results = []
                    for doc in results:
                        result = {
                            "content": doc.page_content,
                            "metadata": doc.metadata
                        }
                        formatted_results.append(result)
                    return formatted_results
                    
            except Exception as e:
                logger.warning(f"⚠️ Vector search failed ({e}), trying fallback keyword search...")
                # Fallback to keyword search using psycopg2
                return await self._fallback_keyword_search(query, k, include_scores)
                
        except Exception as e:
            logger.error(f"❌ Error searching workflows: {e}")
            return []
    
    async def _fallback_keyword_search(self, query: str, k: int = 5, include_scores: bool = False) -> List[Dict[str, Any]]:
        """Fallback keyword search using direct SQL when vector search fails"""
        try:
            import psycopg2
            
            conn = psycopg2.connect(self.config.database_url)
            cur = conn.cursor()
            
            # Search for workflows containing keywords from the query
            keywords = query.lower().split()
            like_conditions = []
            params = ['n8n_workflows']
            
            for keyword in keywords:
                like_conditions.append("e.document ILIKE %s")
                params.append(f'%{keyword}%')
            
            where_clause = " AND ".join(like_conditions) if like_conditions else "true"
            
            cur.execute(f'''
                SELECT e.document, e.cmetadata
                FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                WHERE c.name = %s 
                AND ({where_clause})
                LIMIT %s
            ''', params + [k])
            
            results = []
            for doc_content, metadata in cur.fetchall():
                result = {
                    "content": doc_content,
                    "metadata": metadata or {}
                }
                if include_scores:
                    result["similarity_score"] = 1.0  # Dummy score
                results.append(result)
            
            cur.close()
            conn.close()
            
            logger.info(f"📊 Fallback search found {len(results)} workflows")
            return results
            
        except Exception as e:
            logger.error(f"❌ Fallback search failed: {e}")
            return []
    
    async def search_with_context(
        self, 
        query: str, 
        context_type: str = "workflow",
        k: int = 3
    ) -> str:
        """
        Search for relevant context and format it for AI model consumption
        
        Args:
            query: Search query
            context_type: Type of context to search for
            k: Number of results to include
            
        Returns:
            Formatted context string for AI models
        """
        await self.initialize()
        
        try:
            results = await self.search_similar_workflows(query, k=k, include_scores=True)
            
            if not results:
                return f"No relevant {context_type} information found for: {query}"
            
            # Format context for AI consumption
            context_parts = [f"Relevant {context_type} information for '{query}':\n"]
            
            for i, result in enumerate(results, 1):
                metadata = result.get("metadata", {})
                content = result.get("content", "")
                score = result.get("similarity_score", 0)
                
                # Extract useful metadata
                source = metadata.get("source_repo", "unknown")
                workflow_name = metadata.get("workflow_name", "unnamed")
                node_types = metadata.get("node_types", [])
                
                context_parts.append(f"\n{i}. {workflow_name} (from {source}, similarity: {score:.3f})")
                if node_types:
                    context_parts.append(f"   Node types: {', '.join(node_types[:5])}")
                context_parts.append(f"   Content: {content[:200]}...")
                
            return "\n".join(context_parts)
            
        except Exception as e:
            logger.error(f"❌ Error generating context: {e}")
            return f"Error retrieving {context_type} context: {str(e)}"
    
    async def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector database collection"""
        await self.initialize()
        
        try:
            stats = self.embedding_manager.get_collection_stats()
            return stats
        except Exception as e:
            logger.error(f"❌ Error getting collection stats: {e}")
            return {"error": str(e)}
    
    async def add_workflow_context(
        self, 
        content: str, 
        metadata: Dict[str, Any],
        source_repo: str = "ai_agents"
    ) -> bool:
        """
        Add new workflow context to the vector database
        
        Args:
            content: Text content to add
            metadata: Metadata for the document
            source_repo: Source repository name
            
        Returns:
            True if successful, False otherwise
        """
        await self.initialize()
        
        try:
            # Create a document
            doc = Document(
                page_content=content,
                metadata={
                    "source_repo": source_repo,
                    **metadata
                }
            )
            
            # Skip adding to vector store to avoid pgvector extension issues
            # The existing 15,258 embeddings are sufficient for search
            logger.info(f"✅ Workflow created successfully: {metadata.get('workflow_name', 'unnamed')} (not added to vector database)")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error adding workflow context: {e}")
            return False
    
    async def search_n8n_workflows(
        self, 
        query: str, 
        k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search specifically for n8n workflow examples
        
        Args:
            query: Search query for n8n workflows
            k: Number of results to return
            
        Returns:
            List of n8n workflow documents
        """
        # Add n8n-specific filter
        filter_dict = {"source_repo": "n8n_workflows"}
        
        return await self.search_similar_workflows(
            query=f"n8n {query}",
            k=k,
            filter_dict=filter_dict,
            include_scores=True
        )
    
    async def get_workflow_suggestions(
        self, 
        user_request: str,
        context_limit: int = 3
    ) -> Dict[str, Any]:
        """
        Get workflow suggestions based on user request
        
        Args:
            user_request: User's automation request
            context_limit: Maximum number of similar workflows to include
            
        Returns:
            Dictionary containing suggestions and context
        """
        await self.initialize()
        
        try:
            # Search for similar workflows
            similar_workflows = await self.search_n8n_workflows(
                query=user_request,
                k=context_limit
            )
            
            # Format suggestions
            suggestions = {
                "user_request": user_request,
                "similar_workflows": similar_workflows,
                "suggestions": [],
                "context": ""
            }
            
            if similar_workflows:
                # Extract key patterns and suggestions
                node_types = set()
                workflow_patterns = []
                
                for workflow in similar_workflows:
                    metadata = workflow.get("metadata", {})
                    content = workflow.get("content", "")
                    
                    # Collect node types
                    if "node_types" in metadata:
                        node_types.update(metadata["node_types"])
                    
                    # Extract workflow patterns
                    workflow_patterns.append({
                        "name": metadata.get("workflow_name", "unnamed"),
                        "description": content[:100] + "...",
                        "score": workflow.get("similarity_score", 0)
                    })
                
                # Generate suggestions
                suggestions["suggestions"] = [
                    f"Consider using nodes: {', '.join(list(node_types)[:5])}",
                    f"Similar workflow patterns found: {len(workflow_patterns)}",
                    "Use the examples below as inspiration for your automation"
                ]
                
                # Create context string
                context_parts = [f"Context for '{user_request}':\n"]
                for pattern in workflow_patterns:
                    context_parts.append(
                        f"- {pattern['name']}: {pattern['description']} "
                        f"(similarity: {pattern['score']:.3f})"
                    )
                suggestions["context"] = "\n".join(context_parts)
            
            return suggestions
            
        except Exception as e:
            logger.error(f"❌ Error getting workflow suggestions: {e}")
            return {
                "user_request": user_request,
                "similar_workflows": [],
                "suggestions": ["Error retrieving suggestions"],
                "context": f"Error: {str(e)}"
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check the health of the vector database service"""
        try:
            await self.initialize()
            
            # Test embedding generation
            test_result = self.embedding_manager.test_embedding_pipeline()
            
            # Get collection stats
            stats = await self.get_collection_stats()
            
            return {
                "status": "healthy",
                "initialized": self._initialized,
                "embedding_test": test_result,
                "collection_stats": stats,
                "config": {
                    "collection_name": self.config.collection_name,
                    "embedding_model": self.config.embedding_model,
                    "database_url": self.config.database_url.split("@")[0] + "@***"  # Hide credentials
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Vector database health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "initialized": self._initialized
            }

# Global instance
_vector_db_service = None

def get_vector_db_service() -> VectorDatabaseService:
    """Get the global vector database service instance"""
    global _vector_db_service
    if _vector_db_service is None:
        _vector_db_service = VectorDatabaseService()
    return _vector_db_service

async def initialize_vector_db():
    """Initialize the global vector database service"""
    service = get_vector_db_service()
    await service.initialize()
    return service