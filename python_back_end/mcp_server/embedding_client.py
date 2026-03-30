import os
import logging
import httpx
from typing import List

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """
    Client for generating embeddings via HTTP to embedding servers.

    Supports:
    - qwen3-embedding (2560 dims) on dulc3-top:8080
    - nomic-embed-text (768 dims) on dulc3-top:8081
    """

    def __init__(self, qwen3_url: str, nomic_url: str):
        self.qwen3_url = qwen3_url.rstrip("/")
        self.nomic_url = nomic_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def generate(
        self, query: str, model: str = "nomic-embed-text"
    ) -> List[float]:
        """
        Generate embedding for a query.

        Args:
            query: Text query to embed
            model: Model name ("qwen3-embedding" or "nomic-embed-text")

        Returns:
            List of floats representing the embedding
        """
        client = await self._get_client()

        # Select URL and model name based on model type
        # llama.cpp uses OpenAI-compatible /v1/embeddings endpoint
        if model == "qwen3-embedding":
            url = f"{self.qwen3_url}/v1/embeddings"
            model_name = "qwen3-embedding"
        else:
            url = f"{self.nomic_url}/v1/embeddings"
            model_name = "nomic-embed-text-v1.5.Q4_K_M.gguf"

        try:
            response = await client.post(
                url,
                json={"model": model_name, "input": query},
            )
            response.raise_for_status()
            data = response.json()

            # llama.cpp OpenAI format: {"data": [{"embedding": [...]}]}
            if "data" in data and len(data["data"]) > 0:
                return data["data"][0]["embedding"]
            elif "embedding" in data:
                return data["embedding"]
            else:
                logger.warning(f"Unexpected response format: {data}")
                return []

        except httpx.HTTPError as e:
            logger.error(f"Failed to generate embedding for model {model}: {e}")
            raise

    async def generate_with_fallback(
        self, query: str, primary_model: str, fallback_model: str | None = None
    ) -> List[float]:
        """
        Generate embedding with fallback to alternative model.

        Args:
            query: Text query to embed
            primary_model: Primary model to try
            fallback_model: Fallback model if primary fails

        Returns:
            List of floats representing the embedding
        """
        try:
            return await self.generate(query, primary_model)
        except Exception as e:
            logger.warning(
                f"Primary model {primary_model} failed: {e}. "
                f"Trying fallback {fallback_model}..."
            )
            if fallback_model:
                return await self.generate(query, fallback_model)
            raise
