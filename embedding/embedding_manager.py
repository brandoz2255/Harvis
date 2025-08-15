"""
Embedding manager for generating embeddings and managing vector database operations.
"""

import logging
from typing import List, Optional, Dict, Any, Generator
from langchain_core.documents import Document
from langchain_postgres import PGVector
from langchain_community.embeddings import HuggingFaceEmbeddings
import psycopg2
import psycopg2.extras

from config import EmbeddingConfig
from workflow_processor import WorkflowProcessor

logger = logging.getLogger(__name__)

class EmbeddingManager:
    """Manages embedding generation and vector database operations for n8n workflows."""
    
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.embeddings = None
        self.vector_store = None
        self.workflow_processor = WorkflowProcessor(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap
        )
        
    def initialize_embeddings(self):
        """Initialize the embedding model."""
        try:
            logger.info(f"Initializing embedding model: {self.config.embedding_model}")
            self.embeddings = HuggingFaceEmbeddings(
                model_name=self.config.embedding_model,
                model_kwargs={'device': 'cpu'},  # Use CPU for compatibility
                encode_kwargs={'normalize_embeddings': True}
            )
            logger.info("Embedding model initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize embedding model: {e}")
            raise
    
    def initialize_vector_store(self):
        """Initialize the PGVector vector store."""
        if not self.embeddings:
            self.initialize_embeddings()
            
        try:
            logger.info(f"Connecting to vector database: {self.config.collection_name}")
            
            # Initialize PGVector
            self.vector_store = PGVector(
                connection=self.config.database_url,
                embeddings=self.embeddings,
                collection_name=self.config.collection_name,
                distance_strategy=self.config.distance_strategy,
                pre_delete_collection=self.config.pre_delete_collection,
                use_jsonb=self.config.use_jsonb
            )
            
            logger.info("Vector store initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize vector store: {e}")
            raise
    
    def setup_database(self):
        """Setup database with pgvector extension."""
        try:
            # Parse database URL to get connection parameters
            import urllib.parse as urlparse
            parsed = urlparse.urlparse(self.config.database_url)
            
            conn_params = {
                'host': parsed.hostname,
                'port': parsed.port,
                'database': parsed.path.lstrip('/'),
                'user': parsed.username,
                'password': parsed.password
            }
            
            # Connect and setup pgvector
            with psycopg2.connect(**conn_params) as conn:
                with conn.cursor() as cur:
                    # Enable pgvector extension
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    logger.info("pgvector extension enabled")
                    
                    # Check if we need to create the table
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_name = %s
                        );
                    """, (f"langchain_pg_embedding_{self.config.collection_name}",))
                    
                    table_exists = cur.fetchone()[0]
                    if not table_exists:
                        logger.info(f"Vector table for collection '{self.config.collection_name}' will be created automatically")
                    
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"Failed to setup database: {e}")
            raise
    
    def add_workflows_from_directory(self, directory_path: str, source_repo: str = "unknown",
                                   batch_size: int = 50) -> Dict[str, Any]:
        """Process and add workflows from a directory to the vector database."""
        if not self.vector_store:
            self.initialize_vector_store()
        
        try:
            documents_processed = 0
            documents_added = 0
            batch = []
            
            logger.info(f"Processing workflows from: {directory_path}")
            
            # Process workflows in batches
            for document in self.workflow_processor.process_directory(
                directory_path, source_repo, self.config.max_workflows
            ):
                batch.append(document)
                documents_processed += 1
                
                # Add batch to vector store when batch size is reached
                if len(batch) >= batch_size:
                    added_count = self._add_document_batch(batch)
                    documents_added += added_count
                    batch = []
                    
                    logger.info(f"Processed {documents_processed} documents, added {documents_added} to vector store")
            
            # Add remaining documents
            if batch:
                added_count = self._add_document_batch(batch)
                documents_added += added_count
            
            result = {
                "success": True,
                "documents_processed": documents_processed,
                "documents_added": documents_added,
                "source_repo": source_repo,
                "directory_path": directory_path
            }
            
            logger.info(f"Completed processing: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error adding workflows from directory {directory_path}: {e}")
            return {
                "success": False,
                "error": str(e),
                "documents_processed": 0,
                "documents_added": 0
            }
    
    def _add_document_batch(self, documents: List[Document]) -> int:
        """Add a batch of documents to the vector store."""
        try:
            # Filter out empty documents
            valid_documents = [doc for doc in documents if doc.page_content.strip()]
            
            if not valid_documents:
                logger.warning("No valid documents in batch")
                return 0
            
            # Add documents to vector store
            self.vector_store.add_documents(documents=valid_documents)
            return len(valid_documents)
            
        except Exception as e:
            logger.error(f"Error adding document batch: {e}")
            return 0
    
    def search_workflows(self, query: str, k: int = 5, filter_dict: Optional[Dict] = None) -> List[Document]:
        """Search for similar workflows in the vector database."""
        if not self.vector_store:
            self.initialize_vector_store()
        
        try:
            results = self.vector_store.similarity_search(
                query=query,
                k=k,
                filter=filter_dict
            )
            return results
        except Exception as e:
            logger.error(f"Error searching workflows: {e}")
            # Try fallback keyword search when vector search fails
            logger.info("🔄 Attempting fallback keyword search...")
            fallback_results = self._fallback_keyword_search(query, k)
            return [doc for doc, score in fallback_results]
    
    def search_workflows_with_score(self, query: str, k: int = 5, 
                                  filter_dict: Optional[Dict] = None) -> List[tuple]:
        """Search for similar workflows with similarity scores."""
        if not self.vector_store:
            self.initialize_vector_store()
        
        try:
            results = self.vector_store.similarity_search_with_score(
                query=query,
                k=k,
                filter=filter_dict
            )
            return results
        except Exception as e:
            logger.error(f"Error searching workflows with scores: {e}")
            # Try fallback keyword search when vector search fails
            logger.info("🔄 Attempting fallback keyword search...")
            return self._fallback_keyword_search(query, k)
    
    def _fallback_keyword_search(self, query: str, k: int = 5) -> List[tuple]:
        """Fallback keyword search when vector search fails"""
        try:
            import psycopg2
            
            conn = psycopg2.connect(self.config.database_url)
            cur = conn.cursor()
            
            # Search for workflows containing keywords from the query
            keywords = query.lower().split()
            like_conditions = []
            params = [self.config.collection_name]
            
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
            
            logger.info(f"📊 Fallback search found {len(results)} YouTube workflows")
            return results
            
        except Exception as e:
            logger.error(f"❌ Fallback search failed: {e}")
            return []
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the current collection."""
        if not self.vector_store:
            self.initialize_vector_store()
        
        try:
            # Parse database URL to get connection parameters
            import urllib.parse as urlparse
            parsed = urlparse.urlparse(self.config.database_url)
            
            conn_params = {
                'host': parsed.hostname,
                'port': parsed.port,
                'database': parsed.path.lstrip('/'),
                'user': parsed.username,
                'password': parsed.password
            }
            
            with psycopg2.connect(**conn_params) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    table_name = f"langchain_pg_embedding_{self.config.collection_name}"
                    
                    # Get total count
                    cur.execute(f"SELECT COUNT(*) as total FROM {table_name};")
                    total_count = cur.fetchone()['total']
                    
                    # Get source repo distribution
                    cur.execute(f"""
                        SELECT 
                            cmetadata->>'source_repo' as source_repo,
                            COUNT(*) as count
                        FROM {table_name}
                        WHERE cmetadata ? 'source_repo'
                        GROUP BY cmetadata->>'source_repo'
                        ORDER BY count DESC;
                    """)
                    source_repos = cur.fetchall()
                    
                    # Get node type distribution (top 10)
                    cur.execute(f"""
                        SELECT 
                            jsonb_array_elements_text(cmetadata->'node_types') as node_type,
                            COUNT(*) as count
                        FROM {table_name}
                        WHERE cmetadata ? 'node_types'
                        GROUP BY node_type
                        ORDER BY count DESC
                        LIMIT 10;
                    """)
                    top_node_types = cur.fetchall()
                    
                    return {
                        "collection_name": self.config.collection_name,
                        "total_documents": total_count,
                        "source_repos": [dict(row) for row in source_repos],
                        "top_node_types": [dict(row) for row in top_node_types]
                    }
                    
        except Exception as e:
            logger.error(f"Error getting collection stats: {e}")
            return {"error": str(e)}
    
    def delete_collection(self):
        """Delete the entire collection."""
        if not self.vector_store:
            self.initialize_vector_store()
        
        try:
            self.vector_store.delete_collection()
            logger.info(f"Collection '{self.config.collection_name}' deleted successfully")
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")
            raise
    
    def process_all_workflow_directories(self) -> Dict[str, Any]:
        """Process all configured workflow directories."""
        results = {}
        
        for repo_name, directory_path in self.config.get_workflow_paths().items():
            logger.info(f"Processing {repo_name} from {directory_path}")
            result = self.add_workflows_from_directory(directory_path, repo_name)
            results[repo_name] = result
        
        # Calculate totals
        total_processed = sum(r.get("documents_processed", 0) for r in results.values())
        total_added = sum(r.get("documents_added", 0) for r in results.values())
        
        return {
            "results_by_repo": results,
            "totals": {
                "documents_processed": total_processed,
                "documents_added": total_added,
                "successful_repos": len([r for r in results.values() if r.get("success", False)])
            }
        }
    
    def test_embedding_pipeline(self, sample_text: str = "Test workflow for email automation") -> Dict[str, Any]:
        """Test the embedding pipeline with a sample text."""
        try:
            if not self.embeddings:
                self.initialize_embeddings()
            
            # Generate embedding
            embedding = self.embeddings.embed_query(sample_text)
            
            return {
                "success": True,
                "sample_text": sample_text,
                "embedding_dimension": len(embedding),
                "embedding_sample": embedding[:5]  # First 5 dimensions
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }