"""
n8n Workflow Embedding Module

This module provides tools for processing local n8n workflows and 
storing them in a pgvector-enabled PostgreSQL database for semantic 
search and retrieval-augmented generation (RAG).

Main Components:
- workflow_processor: Extracts and formats workflow content from local JSON files
- embedding_manager: Handles embedding generation and vector database operations
"""

__version__ = "1.0.0"
__author__ = "Jarvis AI System"

from .workflow_processor import WorkflowProcessor
from .embedding_manager import EmbeddingManager
from .config import EmbeddingConfig

__all__ = [
    "WorkflowProcessor", 
    "EmbeddingManager",
    "EmbeddingConfig"
]