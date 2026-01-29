"""
Embedding Adapter for RAG Corpus

Provides unified interface for generating embeddings using:
- Ollama's embedding API
- HuggingFace sentence-transformers (fallback)
"""

import asyncio
import logging
import os
from typing import List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class EmbeddingAdapter:
    """
    Adapter for generating text embeddings.
    
    Supports Ollama's embedding API with fallback to HuggingFace.
    """
    
    def __init__(
        self,
        model_name: str = "qwen3-embedding:4b-q4_K_M",
        ollama_url: str = "http://ollama:11434",
        use_huggingface_fallback: bool = True
    ):
        """
        Initialize the embedding adapter.
        
        Args:
            model_name: Ollama embedding model name
            ollama_url: URL of Ollama server
            use_huggingface_fallback: Whether to fall back to HuggingFace
        """
        self.model_name = model_name
        self.ollama_url = ollama_url.rstrip("/")
        self.use_huggingface_fallback = use_huggingface_fallback
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._hf_model = None
        self._embedding_dim: Optional[int] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60)
            )
        return self._session
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _get_huggingface_model(self):
        """Lazily load HuggingFace model."""
        if self._hf_model is None and self.use_huggingface_fallback:
            try:
                from sentence_transformers import SentenceTransformer
                # Use the same model as existing embedding system
                self._hf_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
                logger.info("Loaded HuggingFace fallback model: all-MiniLM-L6-v2")
            except ImportError:
                logger.warning("sentence-transformers not available for fallback")
        return self._hf_model
    
    async def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector as list of floats
        """
        try:
            return await self._embed_with_ollama(text)
        except Exception as e:
            logger.warning(f"Ollama embedding failed: {e}, trying fallback")
            return self._embed_with_huggingface(text)
    
    async def embed_batch(
        self,
        texts: List[str],
        batch_size: int = 32
    ) -> List[List[float]]:
        """
        Generate embeddings for a batch of texts.
        
        Args:
            texts: List of texts to embed
            batch_size: Number of texts to process at once
            
        Returns:
            List of embedding vectors
        """
        embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            logger.debug(f"Embedding batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}")
            
            # Try Ollama first
            try:
                batch_embeddings = await self._embed_batch_ollama(batch)
                embeddings.extend(batch_embeddings)
            except Exception as e:
                logger.warning(f"Ollama batch embedding failed: {e}, using fallback")
                batch_embeddings = self._embed_batch_huggingface(batch)
                embeddings.extend(batch_embeddings)
            
            # Small delay to avoid overwhelming the server
            await asyncio.sleep(0.1)
        
        return embeddings
    
    async def _embed_with_ollama(self, text: str) -> List[float]:
        """Generate embedding using Ollama API."""
        session = await self._get_session()
        
        payload = {
            "model": self.model_name,
            "prompt": text
        }
        
        logger.debug(f"Calling Ollama embeddings API with model: {self.model_name}")
        
        async with session.post(
            f"{self.ollama_url}/api/embeddings",
            json=payload
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.warning(f"Ollama embedding failed for model '{self.model_name}': {resp.status} - {error_text}")
                raise RuntimeError(f"Ollama API error: {resp.status} - {error_text}")
            
            data = await resp.json()
            embedding = data.get("embedding")
            
            if not embedding:
                raise RuntimeError("No embedding in response")
            
            # Store dimension for reference
            if self._embedding_dim is None:
                self._embedding_dim = len(embedding)
                logger.info(f"Ollama embedding dimension: {self._embedding_dim}")
            
            return embedding
    
    async def _embed_batch_ollama(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch using Ollama."""
        embeddings = []
        
        for text in texts:
            embedding = await self._embed_with_ollama(text)
            embeddings.append(embedding)
            await asyncio.sleep(0.05)  # Small delay between requests
        
        return embeddings
    
    def _embed_with_huggingface(self, text: str) -> List[float]:
        """Generate embedding using HuggingFace."""
        model = self._get_huggingface_model()
        if model is None:
            raise RuntimeError("No embedding model available")
        
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    def _embed_batch_huggingface(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch using HuggingFace."""
        model = self._get_huggingface_model()
        if model is None:
            raise RuntimeError("No embedding model available")
        
        embeddings = model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()
    
    async def check_health(self) -> dict:
        """
        Check if the embedding service is healthy.
        
        Returns:
            Health status dict
        """
        try:
            # Test Ollama
            session = await self._get_session()
            async with session.get(f"{self.ollama_url}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    has_embed_model = any(self.model_name in m for m in models)
                    
                    return {
                        "status": "healthy" if has_embed_model else "warning",
                        "ollama_available": True,
                        "embedding_model": self.model_name,
                        "model_loaded": has_embed_model,
                        "available_models": models[:10],  # Limit list
                    }
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
        
        # Check HuggingFace fallback
        hf_available = self._get_huggingface_model() is not None
        
        return {
            "status": "healthy" if hf_available else "unhealthy",
            "ollama_available": False,
            "huggingface_fallback": hf_available,
        }
    
    @property
    def embedding_dimension(self) -> int:
        """Get the embedding dimension."""
        if self._embedding_dim:
            return self._embedding_dim
        
        # Default dimensions for common models
        defaults = {
            "nomic-embed-text": 768,
            "qwen3-embedding:4b-q4_K_M": 2560,
            "qwen3-embedding": 2560,
            "mxbai-embed-large": 1024,
            "all-MiniLM-L6-v2": 384,
        }
        
        # Check for partial matches (model name without tag)
        for key, dim in defaults.items():
            if key in self.model_name or self.model_name in key:
                return dim
        
        return defaults.get(self.model_name, 768)


class CachedEmbeddingAdapter(EmbeddingAdapter):
    """
    Embedding adapter with caching.
    
    Caches embeddings to avoid re-computing for identical texts.
    """
    
    def __init__(self, *args, cache_size: int = 10000, **kwargs):
        super().__init__(*args, **kwargs)
        from functools import lru_cache
        
        self._cache: dict = {}
        self._cache_size = cache_size
    
    def _cache_key(self, text: str) -> str:
        """Generate cache key for text."""
        import hashlib
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    
    async def embed_text(self, text: str) -> List[float]:
        """Embed with caching."""
        key = self._cache_key(text)
        
        if key in self._cache:
            return self._cache[key]
        
        embedding = await super().embed_text(text)
        
        # Add to cache, evict oldest if full
        if len(self._cache) >= self._cache_size:
            # Simple eviction: remove first item
            first_key = next(iter(self._cache))
            del self._cache[first_key]
        
        self._cache[key] = embedding
        return embedding
    
    async def embed_batch(
        self,
        texts: List[str],
        batch_size: int = 32
    ) -> List[List[float]]:
        """Embed batch with caching."""
        embeddings = []
        texts_to_embed = []
        indices_to_embed = []
        
        # Check cache first
        for i, text in enumerate(texts):
            key = self._cache_key(text)
            if key in self._cache:
                embeddings.append((i, self._cache[key]))
            else:
                texts_to_embed.append(text)
                indices_to_embed.append(i)
        
        # Embed uncached texts
        if texts_to_embed:
            new_embeddings = await super().embed_batch(texts_to_embed, batch_size)
            
            for text, idx, emb in zip(texts_to_embed, indices_to_embed, new_embeddings):
                key = self._cache_key(text)
                if len(self._cache) < self._cache_size:
                    self._cache[key] = emb
                embeddings.append((idx, emb))
        
        # Sort by original index and return
        embeddings.sort(key=lambda x: x[0])
        return [emb for _, emb in embeddings]
    
    def clear_cache(self):
        """Clear the embedding cache."""
        self._cache.clear()
