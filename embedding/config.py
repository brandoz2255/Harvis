"""
Configuration settings for the n8n workflow embedding system.
"""

import os
from typing import Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class EmbeddingConfig:
    """Configuration class for n8n workflow embedding."""
    
    # Database Configuration
    database_url: str = "postgresql://pguser:pgpassword@pgsql-db:5432/database"
    collection_name: str = "n8n_workflows"
    
    # Local workflow directories
    workflows_base_path: str = "/home/guruai/compose/rag-info"
    n8n_workflows_path: str = "/home/guruai/compose/rag-info/n8n-workflows/workflows"
    test_workflows_path: str = "/home/guruai/compose/rag-info/test-workflows"
    
    # Embedding Model Configuration
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384  # For all-MiniLM-L6-v2
    
    # Processing Configuration
    chunk_size: int = 1000
    chunk_overlap: int = 200
    max_workflows: Optional[int] = None  # None = process all workflows
    
    # Vector Database Configuration
    distance_strategy: str = "COSINE"  # COSINE, EUCLIDEAN, MAX_INNER_PRODUCT
    pre_delete_collection: bool = False
    use_jsonb: bool = True
    
    @classmethod
    def from_env(cls) -> 'EmbeddingConfig':
        """Create configuration from environment variables."""
        return cls(
            database_url=os.getenv('VECTOR_DATABASE_URL', cls.database_url),
            collection_name=os.getenv('VECTOR_COLLECTION_NAME', cls.collection_name),
            workflows_base_path=os.getenv('WORKFLOWS_BASE_PATH', cls.workflows_base_path),
            n8n_workflows_path=os.getenv('N8N_WORKFLOWS_PATH', cls.n8n_workflows_path),
            test_workflows_path=os.getenv('TEST_WORKFLOWS_PATH', cls.test_workflows_path),
            embedding_model=os.getenv('EMBEDDING_MODEL', cls.embedding_model),
            embedding_dimension=int(os.getenv('EMBEDDING_DIMENSION', str(cls.embedding_dimension))),
            chunk_size=int(os.getenv('CHUNK_SIZE', str(cls.chunk_size))),
            chunk_overlap=int(os.getenv('CHUNK_OVERLAP', str(cls.chunk_overlap))),
            max_workflows=int(os.getenv('MAX_WORKFLOWS')) if os.getenv('MAX_WORKFLOWS') else None,
            distance_strategy=os.getenv('DISTANCE_STRATEGY', cls.distance_strategy),
            pre_delete_collection=os.getenv('PRE_DELETE_COLLECTION', '').lower() == 'true',
            use_jsonb=os.getenv('USE_JSONB', 'true').lower() == 'true'
        )
    
    def get_workflow_paths(self) -> Dict[str, str]:
        """Get all configured workflow paths."""
        return {
            'n8n_workflows': self.n8n_workflows_path,
            'test_workflows': self.test_workflows_path
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'database_url': self.database_url,
            'collection_name': self.collection_name,
            'workflows_base_path': self.workflows_base_path,
            'n8n_workflows_path': self.n8n_workflows_path,
            'test_workflows_path': self.test_workflows_path,
            'embedding_model': self.embedding_model,
            'embedding_dimension': self.embedding_dimension,
            'chunk_size': self.chunk_size,
            'chunk_overlap': self.chunk_overlap,
            'max_workflows': self.max_workflows,
            'distance_strategy': self.distance_strategy,
            'pre_delete_collection': self.pre_delete_collection,
            'use_jsonb': self.use_jsonb
        }