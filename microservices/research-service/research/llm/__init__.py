"""
LLM client and model management for research system.

Provides unified interface for Ollama with cloud fallback and smart model
selection policies based on task complexity and processing stage.
"""

from .ollama_client import OllamaClient, ModelResponse, GenerationError
from .model_policy import ModelPolicy, ModelTier, get_model_for_task

__all__ = [
    "OllamaClient",
    "ModelResponse", 
    "GenerationError",
    "ModelPolicy",
    "ModelTier",
    "get_model_for_task",
]